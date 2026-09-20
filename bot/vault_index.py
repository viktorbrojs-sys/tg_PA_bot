"""Vector index over vault chunks, backed by sqlite-vec.

Async-safe wrapper (``asyncio.Lock`` + ``asyncio.to_thread``, same pattern as
``TaskStore`` in storage.py) around a small SQLite database with two tables:
a normal ``chunks`` table (path/heading/text/content_hash, keyed by
``Chunk.chunk_id``) and a sqlite-vec virtual table (``vec_chunks``) holding
one embedding per chunk, linked by SQLite's own ``rowid``.

The index is a *derived* artifact — everything in it can be recomputed from
the vault's markdown files via ``vault_scanner``, so losing the .db file is
never data loss, only a slow rebuild. ``existing_hashes()`` is what makes
rebuilds cheap after the first one: diff it against a fresh
``chunk_vault()`` scan and only re-embed what actually changed.

Each operation opens its own short-lived connection (sqlite3 connections
aren't safe to share across threads, and every method already hops onto a
worker thread via ``asyncio.to_thread`` — mirroring how the connection would
be used anyway). This isn't a hot path (periodic re-indexing + occasional
search), so the reconnect overhead doesn't matter in practice.
"""

from __future__ import annotations

import asyncio
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec
from vault_scanner import Chunk


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    file_path: Path
    heading: str | None
    text: str
    distance: float


def _to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class VaultIndex:
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
            "CREATE TABLE IF NOT EXISTS chunks ("
            "id INTEGER PRIMARY KEY, "
            "chunk_id TEXT UNIQUE NOT NULL, "
            "file_path TEXT NOT NULL, "
            "heading TEXT, "
            "text TEXT NOT NULL, "
            "content_hash TEXT NOT NULL)"
        )
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING "
            f"vec0(embedding float[{self._embedding_dim}])"
        )
        return db

    async def existing_hashes(self) -> dict[str, str]:
        """``chunk_id -> content_hash`` for everything currently indexed."""
        async with self._lock:
            return await asyncio.to_thread(self._existing_hashes_sync)

    def _existing_hashes_sync(self) -> dict[str, str]:
        db = self._connect()
        try:
            rows = db.execute("SELECT chunk_id, content_hash FROM chunks").fetchall()
            return dict(rows)
        finally:
            db.close()

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Insert or update *chunks* with their *embeddings* (same order/length)."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")
        if not chunks:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_sync, chunks, embeddings)

    def _upsert_sync(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        db = self._connect()
        try:
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                blob = _to_blob(embedding)
                row = db.execute(
                    "SELECT id FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
                ).fetchone()
                if row is not None:
                    row_id = row[0]
                    db.execute(
                        "UPDATE chunks SET file_path=?, heading=?, text=?, content_hash=? "
                        "WHERE id=?",
                        (
                            chunk.file_path.as_posix(),
                            chunk.heading,
                            chunk.text,
                            chunk.content_hash,
                            row_id,
                        ),
                    )
                    db.execute("UPDATE vec_chunks SET embedding=? WHERE rowid=?", (blob, row_id))
                else:
                    cursor = db.execute(
                        "INSERT INTO chunks (chunk_id, file_path, heading, text, content_hash) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            chunk.chunk_id,
                            chunk.file_path.as_posix(),
                            chunk.heading,
                            chunk.text,
                            chunk.content_hash,
                        ),
                    )
                    row_id = cursor.lastrowid
                    db.execute(
                        "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)", (row_id, blob)
                    )
            db.commit()
        finally:
            db.close()

    async def delete_missing(self, current_chunk_ids: set[str]) -> int:
        """Remove chunks no longer present in the vault (deleted/renamed notes).

        Returns how many chunks were removed.
        """
        async with self._lock:
            return await asyncio.to_thread(self._delete_missing_sync, current_chunk_ids)

    def _delete_missing_sync(self, current_chunk_ids: set[str]) -> int:
        db = self._connect()
        try:
            existing_ids = {row[0] for row in db.execute("SELECT chunk_id FROM chunks")}
            stale_ids = existing_ids - current_chunk_ids
            if not stale_ids:
                return 0
            row_ids = [
                row[0]
                for cid in stale_ids
                for row in db.execute("SELECT id FROM chunks WHERE chunk_id = ?", (cid,))
            ]
            db.executemany(
                "DELETE FROM chunks WHERE chunk_id = ?", [(cid,) for cid in stale_ids]
            )
            db.executemany(
                "DELETE FROM vec_chunks WHERE rowid = ?", [(rid,) for rid in row_ids]
            )
            db.commit()
            return len(stale_ids)
        finally:
            db.close()

    async def search(self, query_embedding: list[float], k: int = 5) -> list[SearchResult]:
        async with self._lock:
            return await asyncio.to_thread(self._search_sync, query_embedding, k)

    def _search_sync(self, query_embedding: list[float], k: int) -> list[SearchResult]:
        db = self._connect()
        try:
            rows = db.execute(
                "SELECT c.chunk_id, c.file_path, c.heading, c.text, v.distance "
                "FROM vec_chunks v JOIN chunks c ON c.id = v.rowid "
                "WHERE v.embedding MATCH ? AND k = ? "
                "ORDER BY v.distance",
                (_to_blob(query_embedding), k),
            ).fetchall()
            return [
                SearchResult(
                    chunk_id=row[0],
                    file_path=Path(row[1]),
                    heading=row[2],
                    text=row[3],
                    distance=row[4],
                )
                for row in rows
            ]
        finally:
            db.close()
