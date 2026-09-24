"""Vector index over Gmail messages, backed by sqlite-vec.

Deliberately a copy of ``vault_index.py``'s structure rather than sharing a
class with it (user's own call): the two have already diverged in what they
key on (mail is diffed by id, since a received message's content never
changes; vault chunks are diffed by content hash, since a note's section can
be edited in place) and mail additionally needs retention pruning by date,
which vault's index has no equivalent of. Revisit a shared base only once
this second copy has proven the pattern is actually the same in practice.

Async-safe wrapper (``asyncio.Lock`` + ``asyncio.to_thread``), same pattern
as ``TaskStore``/``VaultIndex``. The index is a *derived* artifact — losing
the .db file only means Gmail gets re-fetched and re-embedded, no mail is
lost (Gmail itself is the source of truth).
"""

from __future__ import annotations

import asyncio
import sqlite3
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from integrations.gmail_client import MailMessage


@dataclass(frozen=True)
class MailSearchResult:
    message_id: str
    thread_id: str
    sender: str
    sender_name: str
    sender_email: str
    subject: str
    date: datetime
    body: str
    labels: tuple[str, ...]
    distance: float


def _to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _iso(dt: datetime) -> str:
    # Always UTC before formatting, so lexicographic string comparison in
    # SQL (``date < ?``) agrees with chronological order regardless of what
    # offset the datetime came in with.
    return dt.astimezone(UTC).isoformat()


class MailIndex:
    def __init__(self, db_path: Path, embedding_dim: int) -> None:
        self._db_path = db_path
        self._embedding_dim = embedding_dim
        self._lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._db_path)
        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
        db.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "id INTEGER PRIMARY KEY, "
            "message_id TEXT UNIQUE NOT NULL, "
            "thread_id TEXT NOT NULL, "
            "sender TEXT NOT NULL, "
            "sender_name TEXT NOT NULL, "
            "sender_email TEXT NOT NULL, "
            "subject TEXT NOT NULL, "
            "date TEXT NOT NULL, "
            "body TEXT NOT NULL, "
            "labels TEXT NOT NULL)"
        )
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS vec_messages USING "
            f"vec0(embedding float[{self._embedding_dim}])"
        )
        return db

    async def existing_ids(self) -> set[str]:
        """Gmail message ids already in the index.

        Unlike vault chunks, a received message's content never changes, so
        there's nothing to diff by content hash — an id already indexed
        needs no update, only ids NOT in this set need fetching/embedding.
        """
        async with self._lock:
            return await asyncio.to_thread(self._existing_ids_sync)

    def _existing_ids_sync(self) -> set[str]:
        db = self._connect()
        try:
            return {row[0] for row in db.execute("SELECT message_id FROM messages")}
        finally:
            db.close()

    async def upsert(self, messages: list[MailMessage], embeddings: list[list[float]]) -> None:
        if len(messages) != len(embeddings):
            raise ValueError("messages and embeddings must be the same length")
        if not messages:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_sync, messages, embeddings)

    def _upsert_sync(self, messages: list[MailMessage], embeddings: list[list[float]]) -> None:
        db = self._connect()
        try:
            for message, embedding in zip(messages, embeddings, strict=True):
                blob = _to_blob(embedding)
                row = db.execute(
                    "SELECT id FROM messages WHERE message_id = ?", (message.id,)
                ).fetchone()
                if row is not None:
                    row_id = row[0]
                    db.execute(
                        "UPDATE messages SET thread_id=?, sender=?, sender_name=?, "
                        "sender_email=?, subject=?, date=?, body=?, labels=? WHERE id=?",
                        (
                            message.thread_id,
                            message.sender,
                            message.sender_name,
                            message.sender_email,
                            message.subject,
                            _iso(message.date),
                            message.body,
                            ",".join(message.labels),
                            row_id,
                        ),
                    )
                    db.execute("UPDATE vec_messages SET embedding=? WHERE rowid=?", (blob, row_id))
                else:
                    cursor = db.execute(
                        "INSERT INTO messages (message_id, thread_id, sender, sender_name, "
                        "sender_email, subject, date, body, labels) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            message.id,
                            message.thread_id,
                            message.sender,
                            message.sender_name,
                            message.sender_email,
                            message.subject,
                            _iso(message.date),
                            message.body,
                            ",".join(message.labels),
                        ),
                    )
                    row_id = cursor.lastrowid
                    db.execute(
                        "INSERT INTO vec_messages (rowid, embedding) VALUES (?, ?)",
                        (row_id, blob),
                    )
            db.commit()
        finally:
            db.close()

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Prune messages received before *cutoff* (retention). Returns how
        many were removed. Gmail is the source of truth for mail — this
        only shrinks the local search index, nothing is deleted from Gmail.
        """
        async with self._lock:
            return await asyncio.to_thread(self._delete_older_than_sync, cutoff)

    def _delete_older_than_sync(self, cutoff: datetime) -> int:
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT id FROM messages WHERE date < ?", (_iso(cutoff),)
            ).fetchall()
            row_ids = [row[0] for row in rows]
            if not row_ids:
                return 0
            db.executemany(
                "DELETE FROM messages WHERE id = ?", [(rid,) for rid in row_ids]
            )
            db.executemany(
                "DELETE FROM vec_messages WHERE rowid = ?", [(rid,) for rid in row_ids]
            )
            db.commit()
            return len(row_ids)
        finally:
            db.close()

    async def search_text(self, query: str, limit: int = 5) -> list[MailSearchResult]:
        """Literal, case-insensitive substring match across sender/subject/
        body of already-indexed messages, most recent first. Not semantic —
        same reasoning as ``ContactService`` preferring literal name
        matching over embeddings for people search. Filtering happens in
        Python, not via SQL ``LIKE``: SQLite's default ``LIKE`` only
        case-folds ASCII, so Cyrillic and other non-ASCII names would
        silently stop matching with ``COLLATE NOCASE`` alone.
        """
        async with self._lock:
            return await asyncio.to_thread(self._search_text_sync, query, limit)

    def _search_text_sync(self, query: str, limit: int) -> list[MailSearchResult]:
        db = self._connect()
        try:
            query_lower = query.lower()
            rows = db.execute(
                "SELECT message_id, thread_id, sender, sender_name, sender_email, "
                "subject, date, body, labels FROM messages"
            ).fetchall()
            matches = [
                row
                for row in rows
                if query_lower in row[3].lower()  # sender_name
                or query_lower in row[4].lower()  # sender_email
                or query_lower in row[5].lower()  # subject
                or query_lower in row[7].lower()  # body
            ]
            matches.sort(key=lambda row: row[6], reverse=True)  # date, ISO string, desc
            return [
                MailSearchResult(
                    message_id=row[0],
                    thread_id=row[1],
                    sender=row[2],
                    sender_name=row[3],
                    sender_email=row[4],
                    subject=row[5],
                    date=datetime.fromisoformat(row[6]),
                    body=row[7],
                    labels=tuple(row[8].split(",")) if row[8] else (),
                    distance=0.0,  # meaningless here — this path never ranks by similarity
                )
                for row in matches[:limit]
            ]
        finally:
            db.close()

    async def search(self, query_embedding: list[float], k: int = 5) -> list[MailSearchResult]:
        async with self._lock:
            return await asyncio.to_thread(self._search_sync, query_embedding, k)

    def _search_sync(self, query_embedding: list[float], k: int) -> list[MailSearchResult]:
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT m.message_id, m.thread_id, m.sender, m.sender_name, m.sender_email, "
                "m.subject, m.date, m.body, m.labels, v.distance "
                "FROM vec_messages v JOIN messages m ON m.id = v.rowid "
                "WHERE v.embedding MATCH ? AND k = ? "
                "ORDER BY v.distance",
                (_to_blob(query_embedding), k),
            ).fetchall()
            return [
                MailSearchResult(
                    message_id=row[0],
                    thread_id=row[1],
                    sender=row[2],
                    sender_name=row[3],
                    sender_email=row[4],
                    subject=row[5],
                    date=datetime.fromisoformat(row[6]),
                    body=row[7],
                    labels=tuple(row[8].split(",")) if row[8] else (),
                    distance=row[9],
                )
                for row in rows
            ]
        finally:
            db.close()
