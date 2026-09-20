"""Search over the Obsidian vault — semantic if configured, grep otherwise.

Grep-only (substring match over the one tasks/notes file, storage.py's
TaskStore) was the whole story until Second Brain: now, when a VaultIndex
and EmbeddingClient are wired in (via ``enable_semantic_search`` — see
main.py's post_init, which is where vault indexing gets confirmed working
at startup), search embeds the query and does a nearest-neighbour lookup
over chunks from the WHOLE vault, not just the tasks file. Falls back to
grep automatically if semantic search isn't configured, or if the embedding
backend is unreachable at query time (Ollama down) — same "degrade
gracefully" pattern as the rest of the optional integrations.
"""

from __future__ import annotations

from integrations.embedding_client import EmbeddingClient
from integrations.llm_client import LLMClient
from storage import TaskStore
from vault_index import VaultIndex


class SearchService:
    def __init__(self, store: TaskStore, llm: LLMClient, max_matches: int = 10) -> None:
        self._store = store
        self._llm = llm
        self._max_matches = max_matches
        self._vault_index: VaultIndex | None = None
        self._embeddings: EmbeddingClient | None = None

    def enable_semantic_search(self, vault_index: VaultIndex, embeddings: EmbeddingClient) -> None:
        """Switch on whole-vault semantic search. Called once, from main.py's
        post_init, only after confirming the embedding backend actually
        responds — so once this has been called, ``search()`` still falls
        back to grep per-query if Ollama later becomes unreachable, but
        never because the feature simply wasn't set up.
        """
        self._vault_index = vault_index
        self._embeddings = embeddings

    async def search(self, query: str) -> str:
        matches = await self._semantic_matches(query)
        if matches is None:
            matches = await self._grep_matches(query)

        if not matches:
            return f"🔍 Ничего не найдено по запросу «{query}»."

        return await self._llm.summarize_search(query, matches[: self._max_matches])

    async def _semantic_matches(self, query: str) -> list[str] | None:
        """Returns matched chunk texts, or None if semantic search isn't
        available right now (not configured, or Ollama unreachable) — the
        caller should fall back to grep in that case. An empty list is a
        real "nothing indexed yet", distinct from "couldn't search".
        """
        if self._vault_index is None or self._embeddings is None:
            return None
        vectors = await self._embeddings.embed([query])
        if not vectors:
            return None
        results = await self._vault_index.search(vectors[0], k=self._max_matches)
        return [result.text for result in results]

    async def _grep_matches(self, query: str) -> list[str]:
        lines = await self._store.read_all_lines()
        query_lower = query.lower()
        return [line for line in lines if query_lower in line.lower()]
