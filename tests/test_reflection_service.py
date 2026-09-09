from datetime import datetime

import pytest
from services.reflection_service import ReflectionService, ReflectionState
from services.task_service import TaskService
from storage import TaskStore

FIXED_NOW = datetime(2026, 9, 9, 21, 0)


class FakeLLMClient:
    """Deterministic matcher: 'completed' text names indices directly, e.g. 'done 1,3'."""

    async def classify_task(self, text: str, sections: list[str]) -> str:
        return "Входящие"

    async def split_into_tasks(self, text: str) -> list[str]:
        return [text]

    async def match_completed_tasks(self, reply: str, tasks: list[str]) -> list[int]:
        if not reply.startswith("done "):
            return []
        return [int(n) for n in reply.removeprefix("done ").split(",") if n.strip()]

    async def summarize_search(self, query: str, matches: list[str]) -> str:
        return "\n".join(matches)


@pytest.fixture
def task_service(tmp_path):
    store = TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW)
    return TaskService(store, FakeLLMClient(), sections=("Работа",))


@pytest.fixture
def reflection(task_service):
    return ReflectionService(task_service, FakeLLMClient())


def test_reflection_state_tracks_awaiting_chats():
    state = ReflectionState()
    assert not state.is_awaiting(42)

    state.start(42)
    assert state.is_awaiting(42)
    assert not state.is_awaiting(99)

    state.clear(42)
    assert not state.is_awaiting(42)


@pytest.mark.asyncio
async def test_process_reply_with_no_open_tasks(reflection):
    summary = await reflection.process_reply("done 1")
    assert "не было" in summary.lower()


@pytest.mark.asyncio
async def test_process_reply_marks_matching_tasks_done(task_service, reflection):
    for text in ("первая", "вторая", "третья"):
        await task_service.add_task(text)

    summary = await reflection.process_reply("done 1,3")

    assert "✅ Отметил как выполненные (2)" in summary
    assert "первая" in summary
    assert "третья" in summary
    assert "🔁 Переносится на завтра (1)" in summary
    assert "вторая" in summary

    remaining = await task_service.list_all_open_tasks()
    assert len(remaining) == 1
    assert "вторая" in remaining[0]


@pytest.mark.asyncio
async def test_process_reply_with_no_matches(task_service, reflection):
    await task_service.add_task("единственная задача")

    summary = await reflection.process_reply("ничего не делал")

    assert "Не нашёл" in summary
    assert "🔁 Переносится на завтра (1)" in summary
    remaining = await task_service.list_all_open_tasks()
    assert len(remaining) == 1


@pytest.mark.asyncio
async def test_process_reply_ignores_out_of_range_indices(task_service, reflection):
    await task_service.add_task("единственная задача")

    summary = await reflection.process_reply("done 1,99")

    assert "единственная задача" in summary
    assert "Открытых задач не осталось" in summary
    remaining = await task_service.list_all_open_tasks()
    assert len(remaining) == 0
