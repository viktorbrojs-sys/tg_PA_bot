from datetime import datetime

import pytest
from handlers import (
    BOT_COMMANDS,
    _has_valid_deadline_args,
    _has_valid_priority_args,
    _has_valid_setcategory_args,
    _run_contact,
    _run_deadline,
    _run_done,
    _run_plan,
    _run_priority,
    _run_search,
    _run_setcategory,
)
from integrations.google_calendar import NullCalendarClient
from integrations.llm_client import NullLLMClient
from services.contact_service import ContactService
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


@pytest.fixture
def contact_service(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return ContactService(NullCalendarClient(), vault_path=vault, now=lambda: FIXED_NOW)


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
    assert {"search", "done", "plan", "deadline", "priority"} <= names


@pytest.mark.asyncio
async def test_run_deadline_sets_tag(task_service):
    await task_service.add_task("Сдать отчёт")

    reply = await _run_deadline(task_service, "1 2026-09-20")
    assert "2026-09-20" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[due:: 2026-09-20]" in tasks[0]


@pytest.mark.asyncio
async def test_run_deadline_off_removes_tag(task_service):
    await task_service.add_task("Сдать отчёт")
    await _run_deadline(task_service, "1 2026-09-20")

    reply = await _run_deadline(task_service, "1 off")
    assert "убран" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[due:: 2026-09-20]" not in tasks[0]


@pytest.mark.asyncio
async def test_run_deadline_rejects_bad_date(task_service):
    await task_service.add_task("Сдать отчёт")
    reply = await _run_deadline(task_service, "1 не дата")
    assert "формат" in reply.lower() or "ГГГГ-ММ-ДД" in reply


@pytest.mark.asyncio
async def test_run_deadline_reports_missing_index(task_service):
    reply = await _run_deadline(task_service, "42 2026-09-20")
    assert "Не нашёл" in reply


def test_has_valid_deadline_args():
    assert _has_valid_deadline_args("1 2026-09-20") is True
    assert _has_valid_deadline_args("1 off") is True
    assert _has_valid_deadline_args("1 не дата") is False
    assert _has_valid_deadline_args("2026-09-20") is False  # missing index
    assert _has_valid_deadline_args("") is False


@pytest.mark.asyncio
async def test_run_priority_sets_tag_by_word(task_service):
    await task_service.add_task("Сдать отчёт")

    reply = await _run_priority(task_service, "1 высокий")
    assert "Высокий" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[priority:: 2]" in tasks[0]


@pytest.mark.asyncio
async def test_run_priority_sets_tag_by_number(task_service):
    await task_service.add_task("Сдать отчёт")

    reply = await _run_priority(task_service, "1 1")
    assert "Критический" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[priority:: 1]" in tasks[0]


@pytest.mark.asyncio
async def test_run_priority_off_removes_tag(task_service):
    await task_service.add_task("Сдать отчёт")
    await _run_priority(task_service, "1 высокий")

    reply = await _run_priority(task_service, "1 off")
    assert "убран" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[priority:: 2]" not in tasks[0]


@pytest.mark.asyncio
async def test_run_setcategory_sets_tag(task_service):
    await task_service.add_task("Сдать отчёт")

    reply = await _run_setcategory(task_service, "1 Маркетинг")
    assert "Маркетинг" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[category:: Маркетинг]" in tasks[0]


@pytest.mark.asyncio
async def test_run_setcategory_off_removes_tag(task_service):
    await task_service.add_task("Сдать отчёт")
    await _run_setcategory(task_service, "1 Маркетинг")

    reply = await _run_setcategory(task_service, "1 off")
    assert "убран" in reply

    tasks = await task_service.list_all_open_tasks()
    assert "[category::" not in tasks[0]


@pytest.mark.asyncio
async def test_run_setcategory_reports_missing_index(task_service):
    reply = await _run_setcategory(task_service, "42 Маркетинг")
    assert "Не нашёл" in reply


def test_has_valid_setcategory_args():
    assert _has_valid_setcategory_args("1 Маркетинг") is True
    assert _has_valid_setcategory_args("1 off") is True
    assert _has_valid_setcategory_args("1") is False  # missing category
    assert _has_valid_setcategory_args("Маркетинг") is False  # missing index
    assert _has_valid_setcategory_args("") is False


@pytest.mark.asyncio
async def test_run_priority_rejects_unknown_level(task_service):
    await task_service.add_task("Сдать отчёт")
    reply = await _run_priority(task_service, "1 суперважно")
    assert "не распознан" in reply.lower()


@pytest.mark.asyncio
async def test_run_priority_reports_missing_index(task_service):
    reply = await _run_priority(task_service, "42 высокий")
    assert "Не нашёл" in reply


def test_has_valid_priority_args():
    assert _has_valid_priority_args("1 высокий") is True
    assert _has_valid_priority_args("1 2") is True
    assert _has_valid_priority_args("1 off") is True
    assert _has_valid_priority_args("1 суперважно") is False
    assert _has_valid_priority_args("высокий") is False  # missing index


@pytest.mark.asyncio
async def test_run_contact_reports_nothing_found(contact_service):
    reply = await _run_contact(contact_service, "Иванов")
    assert "Ничего не нашёл" in reply


@pytest.mark.asyncio
async def test_run_contact_finds_note_mention(contact_service, tmp_path):
    vault = tmp_path / "vault"
    (vault / "note.md").write_text("## Встреча\nСозвонились с Ивановым.\n", encoding="utf-8")

    reply = await _run_contact(contact_service, "Иванов")

    assert "Упоминания в заметках" in reply
    assert "note.md" in reply
