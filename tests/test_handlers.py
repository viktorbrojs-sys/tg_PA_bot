from datetime import datetime

import pytest
from handlers import BOT_COMMANDS, _run_done, _run_plan, _run_search
from integrations.llm_client import NullLLMClient
from services.search_service import SearchService
from services.task_service import TaskService
from storage import TaskStore

FIXED_NOW = datetime(2026, 9, 9, 12, 0)


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW)


@pytest.fixture
def task_service(store):
    return TaskService(store, NullLLMClient(), sections=("Работа", "Личное"))


@pytest.mark.asyncio
async def test_run_done_marks_valid_index(task_service):
    await task_service.add_task("первая задача")

    reply = await _run_done(task_service, "1")
    assert "выполненная" in reply

    remaining = await task_service.list_all_open_tasks()
    assert remaining == []


@pytest.mark.asyncio
async def test_run_done_rejects_non_numeric_argument(task_service):
    reply = await _run_done(task_service, "не число")
    assert "номер задачи" in reply.lower()


@pytest.mark.asyncio
async def test_run_done_reports_missing_index(task_service):
    reply = await _run_done(task_service, "42")
    assert "Не нашёл" in reply


@pytest.mark.asyncio
async def test_run_plan_splits_and_stores_tasks(task_service):
    reply = await _run_plan(task_service, "первая\nвторая")
    assert "Добавлено задач: 2" in reply

    tasks = await task_service.list_all_open_tasks()
    assert len(tasks) == 2


@pytest.mark.asyncio
async def test_run_search_delegates_to_search_service(store):
    await store.add_task("Настроить доступ к серверу")
    search_service = SearchService(store, NullLLMClient())

    reply = await _run_search(search_service, "сервер")
    assert "сервер" in reply.lower()


def test_bot_commands_include_all_parameterised_commands():
    names = {command for command, _ in BOT_COMMANDS}
    assert {"search", "done", "plan"} <= names
