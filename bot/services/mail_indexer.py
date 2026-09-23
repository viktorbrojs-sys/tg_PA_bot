"""Orchestrates (re)indexing mail: list new ids -> fetch -> embed -> upsert -> prune.

Same layering as ``services/vault_indexer.py`` — Telegram-free business
logic depending only on ``GmailClient`` (integration), ``EmbeddingClient``
(integration) and ``MailIndex`` (storage). Called both from a one-off script
and from the scheduled reindex job.

Diffing is by id, not content hash (unlike vault): a received message's
content never changes, so "already indexed" is all that's needed to skip
it — no update path for existing messages the way vault chunks have one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from integrations.embedding_client import EmbeddingClient
from integrations.gmail_client import GmailClient, MailMessage
from mail_index import MailIndex

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailReindexStats:
    added: int
    deleted: int
    failed: bool = False


def _embed_text(message: MailMessage) -> str:
    body = message.body or message.snippet
    return f"{message.subject}\n\n{body}"


async def reindex_mail(
    gmail: GmailClient,
    index: MailIndex,
    embeddings: EmbeddingClient,
    retention: timedelta,
    now: datetime,
) -> MailReindexStats:
    """Bring *index* up to date with Gmail's inbox, within *retention*.

    Lists inbox message ids received since ``now - retention`` (cheap: one
    request per 100 ids), fetches and embeds only the ones not already in
    the index, then prunes anything older than the retention window. If the
    embedding backend is unavailable, this run is aborted without touching
    the index at all (added AND pruning both skipped) — same "a failed run
    touches nothing" invariant as ``reindex_vault``.
    """
    cutoff = now - retention
    existing_ids = await index.existing_ids()

    all_ids = await gmail.list_ids_since(cutoff)
    new_ids = [i for i in all_ids if i not in existing_ids]

    added = 0
    if new_ids:
        messages = await gmail.get_messages(new_ids)
        if messages:
            vectors = await embeddings.embed([_embed_text(m) for m in messages])
            if vectors is None:
                logger.error("Mail reindex: embedding backend unavailable, aborting this run")
                return MailReindexStats(added=0, deleted=0, failed=True)
            await index.upsert(messages, vectors)
            added = len(messages)

    deleted = await index.delete_older_than(cutoff)

    logger.info("Mail reindex done: %d added, %d deleted (retention prune)", added, deleted)
    return MailReindexStats(added=added, deleted=deleted)
