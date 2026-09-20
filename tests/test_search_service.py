from datetime import datetime
from pathlib import Path

import pytest
from integrations.llm_client import NullLLMClient
from services.search_service import SearchService
from storage import TaskStore
from vault_index import VaultIndex
from vault_scanner import Chunk

FIXED_NOW = datetime(2026, 9, 9, 12, 0)


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW)


@pytest.fixture
def search(store):
    return SearchService(store, NullLLMClient())


@pytest.mark.asyncio
async def test_search_returns_message_when_nothing_matches(search):
    result = await search.search("сервер")
    assert "Ничего не найдено" in result


@pytest.mark.asyncio
async def test_search_finds_matching_lines_case_insensitively(store, search):
    await store.add_task("Настроить доступ к серверу")
    await store.add_task("Купить молоко")

    result = await search.search("СЕРВЕРУ")
    assert "Настроить доступ к серверу" in result
    assert "Купить молоко" not in result


@pytest.mark.asyncio
async def test_search_respects_max_matches(store):
    for i in range(5):
        await store.add_task(f"задача про сервер {i}")

    search = SearchService(store, NullLLMClient(), max_matches=2)
    result = await search.search("сервер")
    assert result.count("задача про сервер") == 2


class FakeEmbeddingClient:
    def __init__(self, vector: list[float] | None = None, fail: bool = False):
        self._vector = vector if vector is not None else [1.0, 0.0, 0.0]
        self._fail = fail
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(texts)
        if self._fail:
            return None
        return [self._vector for _ in texts]


@pytest.mark.asyncio
async def test_search_uses_semantic_results_when_enabled(store, tmp_path):
    index = VaultIndex(tmp_path / "index.db", embedding_dim=3)
    await index.upsert(
        [
            Chunk(
                chunk_id="note.md#X",
                file_path=Path("note.md"),
                heading="X",
                text="Договорились встретиться в среду",
                content_hash="hash",
            )
        ],
        [[1.0, 0.0, 0.0]],
    )
    # Unrelated data in the grep-only tasks file, to prove it's NOT what
    # search() falls back to once semantic search is enabled.
    await store.add_task("Купить молоко")

    search = SearchService(store, NullLLMClient())
    search.enable_semantic_search(index, FakeEmbeddingClient())

    result = await search.search("когда встреча")
    assert "Договорились встретиться в среду" in result
    assert "Купить молоко" not in result


@pytest.mark.asyncio
async def test_search_falls_back_to_grep_when_embeddings_unavailable(store, tmp_path):
    index = VaultIndex(tmp_path / "index.db", embedding_dim=3)
    await store.add_task("Настроить доступ к серверу")

    search = SearchService(store, NullLLMClient())
    search.enable_semantic_search(index, FakeEmbeddingClient(fail=True))

    result = await search.search("сервер")
    assert "Настроить доступ к серверу" in result


@pytest.mark.asyncio
async def test_search_semantic_empty_index_does_not_fall_back_to_grep(store, tmp_path):
    index = VaultIndex(tmp_path / "index.db", embedding_dim=3)  # nothing indexed yet
    await store.add_task("Настроить доступ к серверу")

    search = SearchService(store, NullLLMClient())
    search.enable_semantic_search(index, FakeEmbeddingClient())

    result = await search.search("сервер")
    assert "Ничего не найдено" in result
    assert "Настроить доступ к серверу" not in result
