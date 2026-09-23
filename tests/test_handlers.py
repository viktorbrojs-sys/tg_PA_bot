from datetime import UTC, datetime, timedelta

import pytest
from handlers import (
    BOT_COMMANDS,
    REINDEX_FAILED_TEXT,
    REINDEX_INDEX_NOT_READY_TEXT,
    REINDEX_MAIL_FAILED_TEXT,
    REINDEX_MAIL_INDEX_NOT_READY_TEXT,
    REINDEX_MAIL_NOT_CONFIGURED_TEXT,
    REINDEX_NOT_CONFIGURED_TEXT,
    _has_valid_deadline_args,
    _has_valid_priority_args,
    _has_valid_setcategory_args,
    _run_contact,
    _run_deadline,
    _run_done,
    _run_plan,
    _run_priority,
    _run_reindex,
    _run_reindex_mail,
    _run_search,
    _run_setcategory,
)
from integrations.gmail_client import MailMessage
from integrations.google_calendar import NullCalendarClient
from integrations.llm_client import NullLLMClient
from mail_index import MailIndex
from services.contact_service import ContactService
from services.search_service import SearchService
from services.task_service import TaskService
from storage import TaskStore
from vault_index import VaultIndex

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


class FakeEmbeddingClient:
    def __init__(self, fail: bool = False):
        self._fail = fail

    async def embed(self, texts):
        if self._fail:
            return None
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_run_reindex_not_configured():
    reply = await _run_reindex(vault_path=None, vault_index=None, embeddings=None)
    assert reply == REINDEX_NOT_CONFIGURED_TEXT


@pytest.mark.asyncio
async def test_run_reindex_index_not_ready(tmp_path):
    reply = await _run_reindex(vault_path=tmp_path, vault_index=None, embeddings=None)
    assert reply == REINDEX_INDEX_NOT_READY_TEXT


@pytest.mark.asyncio
async def test_run_reindex_success(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("## X\nТекст заметки.\n", encoding="utf-8")
    index = VaultIndex(tmp_path / "index.db", embedding_dim=3)

    reply = await _run_reindex(vault, index, FakeEmbeddingClient())

    assert "Готово" in reply
    assert "добавлено 1" in reply


@pytest.mark.asyncio
async def test_run_reindex_reports_failure_when_embeddings_unavailable(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("## X\nТекст заметки.\n", encoding="utf-8")
    index = VaultIndex(tmp_path / "index.db", embedding_dim=3)

    reply = await _run_reindex(vault, index, FakeEmbeddingClient(fail=True))

    assert reply == REINDEX_FAILED_TEXT


class FakeGmailClient:
    def __init__(self, messages: dict | None = None):
        self._messages = messages or {}

    async def list_unread(self, limit=10, important_only=False):
        return []

    async def list_ids_since(self, since, max_messages=5000):
        return list(self._messages.keys())

    async def get_messages(self, ids):
        return [self._messages[i] for i in ids if i in self._messages]

    async def count_unread(self):
        return None


def _mail_message(message_id: str):
    return MailMessage(
        id=message_id,
        thread_id=f"t-{message_id}",
        sender="Иван <x@example.com>",
        sender_name="Иван",
        sender_email="x@example.com",
        subject="Тема",
        date=datetime(2026, 9, 9, tzinfo=UTC),
        snippet="",
        body="текст",
        labels=("INBOX",),
    )


@pytest.mark.asyncio
async def test_run_reindex_mail_not_configured():
    reply = await _run_reindex_mail(
        gmail_configured=False,
        mail_index=None,
        gmail=None,
        embeddings=None,
        retention=timedelta(days=180),
    )
    assert reply == REINDEX_MAIL_NOT_CONFIGURED_TEXT


@pytest.mark.asyncio
async def test_run_reindex_mail_index_not_ready():
    reply = await _run_reindex_mail(
        gmail_configured=True,
        mail_index=None,
        gmail=None,
        embeddings=None,
        retention=timedelta(days=180),
    )
    assert reply == REINDEX_MAIL_INDEX_NOT_READY_TEXT


@pytest.mark.asyncio
async def test_run_reindex_mail_success(tmp_path):
    index = MailIndex(tmp_path / "mail.db", embedding_dim=3)
    gmail = FakeGmailClient({"m1": _mail_message("m1")})

    reply = await _run_reindex_mail(
        gmail_configured=True,
        mail_index=index,
        gmail=gmail,
        embeddings=FakeEmbeddingClient(),
        retention=timedelta(days=180),
    )

    assert "Готово" in reply
    assert "добавлено 1" in reply


@pytest.mark.asyncio
async def test_run_reindex_mail_reports_failure_when_embeddings_unavailable(tmp_path):
    index = MailIndex(tmp_path / "mail.db", embedding_dim=3)
    gmail = FakeGmailClient({"m1": _mail_message("m1")})

    reply = await _run_reindex_mail(
        gmail_configured=True,
        mail_index=index,
        gmail=gmail,
        embeddings=FakeEmbeddingClient(fail=True),
        retention=timedelta(days=180),
    )

    assert reply == REINDEX_MAIL_FAILED_TEXT
