from datetime import datetime

import pytest
from integrations.llm_client import NullLLMClient
from services.search_service import SearchService
from storage import TaskStore

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
