"""Search over the Obsidian vault and Gmail — semantic if configured, grep otherwise.

Grep-only (substring match over the one tasks/notes file, storage.py's
TaskStore) was the whole story until Second Brain: now, when a VaultIndex
and EmbeddingClient are wired in (via ``enable_semantic_search`` — see
main.py's post_init, which is where vault indexing gets confirmed working
at startup), search embeds the query and does a nearest-neighbour lookup
over chunks from the WHOLE vault, not just the tasks file. A MailIndex can
be wired in the same way (``enable_mail_search``, Gmail block E) — results
from both sources are merged and ranked together by distance (valid because
both are embedded with the same model/dimension), not shown as two separate
sections, so the closest match wins regardless of whether it's a note or an
email. Falls back to grep automatically if no semantic source is configured
at all, or if the embedding backend is unreachable at query time (Ollama
down) — same "degrade gracefully" pattern as the rest of the optional
integrations.
"""

from __future__ import annotations

from integrations.embedding_client import EmbeddingClient
from integrations.llm_client import LLMClient
from mail_index import MailIndex
from storage import TaskStore
from vault_index import VaultIndex


class SearchService:
    def __init__(self, store: TaskStore, llm: LLMClient, max_matches: int = 10) -> None:
        self._store = store
        self._llm = llm
        self._max_matches = max_matches
        self._vault_index: VaultIndex | None = None
        self._mail_index: MailIndex | None = None
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

    def enable_mail_search(self, mail_index: MailIndex, embeddings: EmbeddingClient) -> None:
        """Switch on Gmail semantic search, independent of vault search —
        either, both, or neither can be enabled. *embeddings* is passed
        here too (not just read from ``enable_semantic_search``) so mail
        search works standalone even when the vault isn't configured at all.
        """
        self._mail_index = mail_index
        self._embeddings = embeddings

    async def search(self, query: str) -> str:
        matches = await self._semantic_matches(query)
        if matches is None:
            matches = await self._grep_matches(query)

        if not matches:
            return f"🔍 Ничего не найдено по запросу «{query}»."

        return await self._llm.summarize_search(query, matches[: self._max_matches])

    async def _semantic_matches(self, query: str) -> list[str] | None:
        """Returns matched texts (vault chunks and/or mail messages, merged
        and ranked together by distance), or None if no semantic source is
        available right now (neither configured, or Ollama unreachable) —
        the caller should fall back to grep in that case. An empty list is
        a real "nothing indexed yet", distinct from "couldn't search".
        """
        if self._vault_index is None and self._mail_index is None:
            return None
        if self._embeddings is None:
            return None
        vectors = await self._embeddings.embed([query])
        if not vectors:
            return None
        query_vector = vectors[0]

        candidates: list[tuple[float, str]] = []
        if self._vault_index is not None:
            for result in await self._vault_index.search(query_vector, k=self._max_matches):
                candidates.append((result.distance, result.text))
        if self._mail_index is not None:
            for mail in await self._mail_index.search(query_vector, k=self._max_matches):
                sender = mail.sender_name or mail.sender_email or mail.sender
                text = f"[Письмо от {sender}, {mail.date:%Y-%m-%d}] {mail.subject}\n{mail.body}"
                candidates.append((mail.distance, text))

        candidates.sort(key=lambda c: c[0])
        return [text for _, text in candidates[: self._max_matches]]

    async def _grep_matches(self, query: str) -> list[str]:
        lines = await self._store.read_all_lines()
        query_lower = query.lower()
        return [line for line in lines if query_lower in line.lower()]
