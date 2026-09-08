from datetime import datetime

import pytest
from services.task_service import PlannedTask, TaskService
from storage import TaskStore

FIXED_NOW = datetime(2026, 9, 7, 14, 32)


class FakeLLMClient:
    """Deterministic stand-in for LLMClient, so tests don't depend on a real API."""

    def __init__(self, section_by_keyword: dict[str, str], default: str) -> None:
        self._section_by_keyword = section_by_keyword
        self._default = default

    async def classify_task(self, text: str, sections: list[str]) -> str:
        for keyword, section in self._section_by_keyword.items():
            if keyword in text.lower():
                return section
        return self._default

    async def split_into_tasks(self, text: str) -> list[str]:
        return [line.strip() for line in text.split(",") if line.strip()]


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW)


@pytest.fixture
def llm():
    return FakeLLMClient(
        section_by_keyword={"отчёт": "Работа", "молоко": "Личное"},
        default="Входящие",
    )


@pytest.fixture
def service(store, llm):
    return TaskService(store, llm, sections=("Работа", "Личное"))


@pytest.mark.asyncio
async def test_add_task_files_under_classified_section(service, store):
    section = await service.add_task("Закончить отчёт")
    assert section == "Работа"

    content = store.path.read_text(encoding="utf-8")
    assert "## Работа" in content
    assert "Закончить отчёт" in content


@pytest.mark.asyncio
async def test_add_task_falls_back_to_default_section(service):
    section = await service.add_task("Что-то неопределённое")
    assert section == "Входящие"


@pytest.mark.asyncio
async def test_plan_day_splits_classifies_and_stores_each_piece(service, store):
    planned = await service.plan_day("Закончить отчёт, купить молоко, полить цветы")

    assert planned == [
        PlannedTask(text="Закончить отчёт", section="Работа"),
        PlannedTask(text="купить молоко", section="Личное"),
        PlannedTask(text="полить цветы", section="Входящие"),
    ]

    content = store.path.read_text(encoding="utf-8")
    assert "## Работа" in content
    assert "## Личное" in content
    assert "## Входящие" in content


@pytest.mark.asyncio
async def test_list_all_open_tasks_returns_every_task_regardless_of_section(service):
    await service.add_task("Закончить отчёт")
    await service.add_task("купить молоко")
    await service.add_task("прочее дело")

    tasks = await service.list_all_open_tasks()
    assert len(tasks) == 3


@pytest.mark.asyncio
async def test_list_recent_open_tasks_respects_limit(service):
    for i in range(5):
        await service.add_task(f"задача {i}")

    tasks = await service.list_recent_open_tasks(2)
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_mark_done_delegates_to_store(service):
    await service.add_task("Закончить отчёт")
    assert await service.mark_done(1) is True
    assert await service.mark_done(99) is False
