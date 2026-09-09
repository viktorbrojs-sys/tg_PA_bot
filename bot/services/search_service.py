"""Quick search over the Obsidian tasks/notes file.

This is a deliberately simple substring-grep search, not semantic search —
that's queued for a later phase (needs an embeddings index over the whole
vault, not just this one file). This version is still useful today and has
no new infrastructure dependency.
"""

from __future__ import annotations

from integrations.llm_client import LLMClient
from storage import TaskStore


class SearchService:
    def __init__(self, store: TaskStore, llm: LLMClient, max_matches: int = 10) -> None:
        self._store = store
        self._llm = llm
        self._max_matches = max_matches

    async def search(self, query: str) -> str:
        lines = await self._store.read_all_lines()
        query_lower = query.lower()
        matches = [line for line in lines if query_lower in line.lower()]
        if not matches:
            return f"🔍 Ничего не найдено по запросу «{query}»."

        return await self._llm.summarize_search(query, matches[: self._max_matches])
