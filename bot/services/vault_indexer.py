"""Orchestrates (re)indexing the vault: scan -> diff -> embed -> upsert -> prune.

Telegram-free business logic, same layering as the other ``services/*.py``
modules — depends on ``vault_scanner`` (pure), ``EmbeddingClient`` (the
integrations-layer abstraction) and ``VaultIndex`` (storage), never on
python-telegram-bot. Called both from a one-off script and from the
scheduled reindex job (same function either way — "reindex now" and
"reindex on a timer" are the same operation).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from integrations.embedding_client import EmbeddingClient
from vault_index import VaultIndex
from vault_scanner import Chunk, chunk_vault

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReindexStats:
    added: int
    updated: int
    deleted: int
    unchanged: int
    failed: bool = False


async def reindex_vault(
    vault_path: Path, index: VaultIndex, embeddings: EmbeddingClient
) -> ReindexStats:
    """Bring *index* up to date with *vault_path*'s current markdown files.

    Only chunks that are new or whose ``content_hash`` changed get
    (re-)embedded — everything else is left untouched, which is what makes
    repeated runs cheap. Chunks whose file/section no longer exists in the
    vault are pruned from the index. If the embedding backend is unavailable
    (e.g. Ollama unreachable), this run is aborted without touching the
    index — better to serve stale-but-correct results than a half-updated
    index — and ``ReindexStats.failed`` is set so the caller can log/alert.
    """
    chunks = chunk_vault(vault_path)
    existing_hashes = await index.existing_hashes()

    to_embed: list[Chunk] = []
    unchanged = 0
    for chunk in chunks:
        if existing_hashes.get(chunk.chunk_id) == chunk.content_hash:
            unchanged += 1
        else:
            to_embed.append(chunk)

    added = sum(1 for c in to_embed if c.chunk_id not in existing_hashes)
    updated = len(to_embed) - added

    if to_embed:
        vectors = await embeddings.embed([c.text for c in to_embed])
        if vectors is None:
            logger.error("Vault reindex: embedding backend unavailable, aborting this run")
            return ReindexStats(added=0, updated=0, deleted=0, unchanged=unchanged, failed=True)
        await index.upsert(to_embed, vectors)

    deleted = await index.delete_missing({c.chunk_id for c in chunks})

    logger.info(
        "Vault reindex done: %d added, %d updated, %d deleted, %d unchanged",
        added,
        updated,
        deleted,
        unchanged,
    )
    return ReindexStats(added=added, updated=updated, deleted=deleted, unchanged=unchanged)
