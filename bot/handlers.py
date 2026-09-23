"""Telegram command and message handlers.

Handlers stay thin: parse the update, call into the services, format the
reply. All classification/day-planning/storage logic lives under
``services/`` so it can be unit-tested without Telegram.

Commands that need a required parameter (``/search``, ``/done``, ``/plan``)
support two flows:
  1. Inline: ``/search сервер`` — runs immediately.
  2. Prompted: ``/search`` (no argument) — the bot asks for the value, and
     the next plain-text message from that chat is used as the parameter
     instead of being classified as a new task. See ``PendingCommandState``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from integrations.embedding_client import EmbeddingClient
from integrations.gmail_client import GmailClient
from mail_index import MailIndex
from services.contact_service import ContactService
from services.digest_service import DigestService
from services.mail_indexer import reindex_mail
from services.pending_command_state import PendingCommandState
from services.reflection_service import ReflectionService, ReflectionState
from services.search_service import SearchService
from services.task_service import TaskService
from services.vault_indexer import reindex_vault
from storage import PRIORITY_LABELS, PRIORITY_LEVELS, parse_priority_input
from telegram import Update
from telegram.ext import ContextTypes
from vault_index import VaultIndex

logger = logging.getLogger(__name__)

# Telegram's hard cap is 4096 chars; leave headroom for formatting.
MESSAGE_CHUNK_LIMIT = 3500

# Single source of truth for the Telegram commands menu (the "/" popup and
# the ≡ button next to the text field), registered via bot.set_my_commands()
# in main.py. Telegram requires: 1-32 chars, lowercase latin letters/digits/
# underscores only; description up to 256 chars.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("list", "Все открытые задачи (или /list N — последние N)"),
    ("plan", "Разбить сообщение на несколько задач на день"),
    ("search", "Найти информацию в заметках"),
    ("contact", "Найти человека: упоминания в заметках + прошлые встречи"),
    ("reindex", "Обновить индекс vault для семантического поиска сейчас"),
    ("reindex_mail", "Обновить индекс почты для поиска сейчас"),
    ("done", "Отметить задачу как выполненную (номер из /list)"),
    ("deadline", "Установить или убрать дедлайн у задачи"),
    ("priority", "Установить или убрать приоритет у задачи"),
    ("setcategory", "Изменить раздел (категорию) у задачи"),
    ("review", "Еженедельный обзор выполненных задач"),
    ("help", "Справка по командам"),
]

_PRIORITY_LEVELS_HINT = ", ".join(
    f"{i} {PRIORITY_LABELS[level]}" for i, level in enumerate(PRIORITY_LEVELS)
)

WELCOME_TEXT = (
    "👋 Бот-секретарь для Obsidian.\n\n"
    "Просто напишите текст — задача автоматически классифицируется по разделу "
    "и появится в вашем файле.\n\n"
    "Команды:\n"
    "/list — все открытые задачи (можно /list 20 — только последние N)\n"
    "/plan <текст> — разбить сообщение на несколько задач на день\n"
    "/search <запрос> — найти информацию в заметках\n"
    "/contact <имя> — найти человека: упоминания в заметках + прошлые встречи\n"
    "/reindex — обновить индекс vault для семантического поиска сейчас\n"
    "/reindex_mail — обновить индекс почты для поиска сейчас\n"
    "/done N — отметить задачу N (из /list) как выполненную\n"
    "/deadline N ГГГГ-ММ-ДД — поставить дедлайн задаче N (необязательно для всех)\n"
    "/priority N уровень — поставить приоритет задаче N\n"
    "/setcategory N раздел — изменить раздел задачи N\n"
    "/review — еженедельный обзор выполненных задач\n"
    "/help — справка\n\n"
    "Если ввести команду без параметра (например, просто /search), бот сам "
    "спросит значение и подставит ваш следующий ответ."
)

HELP_TEXT = (
    "📋 Как пользоваться:\n\n"
    "• Любой текст → задача добавится, ИИ сам определит раздел\n"
    "• /list — полный список открытых задач\n"
    "• /list N — последние N открытых задач\n"
    "• /plan <текст> — разбить сообщение на несколько задач одним вызовом\n"
    "• /search <запрос> — найти информацию в заметках (по всему vault и "
    "прошлым заметкам, если настроен OBSIDIAN_VAULT_PATH; иначе — по файлу "
    "задач)\n"
    "• /contact <имя> — найти человека: упоминания в заметках (по всему vault, "
    "если настроен OBSIDIAN_VAULT_PATH) + прошлые встречи из Google Calendar "
    "за последние 90 дней (если настроен)\n"
    "• /reindex — обновить индекс vault прямо сейчас, не дожидаясь фонового "
    "расписания (актуально только при настроенном OBSIDIAN_VAULT_PATH)\n"
    "• /reindex_mail — то же самое для индекса почты (актуально только при "
    "настроенном Gmail)\n"
    "• /done N — отметить N-ю задачу из /list как выполненную\n"
    "• /deadline N ГГГГ-ММ-ДД — поставить дедлайн задаче N; /deadline N off — убрать. "
    "Дедлайн ставится по желанию, не у каждой задачи он есть\n"
    f"• /priority N уровень — поставить приоритет задаче N ({_PRIORITY_LEVELS_HINT}); "
    "/priority N off — убрать\n"
    "• /setcategory N раздел — изменить раздел задачи N (например «3 Маркетинг»); "
    "/setcategory N off — убрать\n"
    "• /review — еженедельный обзор выполненных задач (за последние 7 дней)\n"
    "• /start — приветствие\n"
    "• /help — эта справка\n\n"
    "Команду с параметром можно вводить и без него — бот спросит значение "
    "отдельным сообщением."
)

GENERIC_ERROR_TEXT = (
    "❌ Не удалось выполнить операцию с файлом задач.\n"
    "Проверьте доступ к файлу и переменную OBSIDIAN_FILE."
)


def _chunk_task_lines(lines: list[str], header: str) -> list[str]:
    """Group numbered task lines into Telegram-message-sized chunks."""
    chunks: list[str] = []
    current = header
    for line in lines:
        candidate = f"{current}\n{line}"
        if len(candidate) > MESSAGE_CHUNK_LIMIT and current != header:
            chunks.append(current)
            current = line
        else:
            current = candidate
    chunks.append(current)
    return chunks


def _chat_id(update: Update) -> int | None:
    return update.effective_chat.id if update.effective_chat else None


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def cmd_unknown(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "🤔 Неизвестная команда. Наберите /help, чтобы увидеть список доступных."
    )


# ── /list — no prompting: no argument is a valid request (full list) ────────


def make_cmd_list(service: TaskService, pending_state: PendingCommandState):
    async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)  # a fresh command cancels any stale prompt

        args = ctx.args or []
        limit: int | None = None
        if args:
            if not args[0].isdigit():
                await update.message.reply_text(
                    "Использование: /list — полный список, или /list N — последние N."
                )
                return
            limit = int(args[0])

        try:
            if limit is None:
                tasks = await service.list_all_open_tasks()
            else:
                tasks = await service.list_recent_open_tasks(limit)
        except OSError as exc:
            logger.error("Failed to read tasks file: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        if not tasks:
            await update.message.reply_text("🎉 Нет невыполненных задач!")
            return

        header = (
            f"📋 Все открытые задачи ({len(tasks)}):"
            if limit is None
            else f"📋 Последние открытые задачи (до {limit}):"
        )
        lines = [f"{i + 1}. {t}" for i, t in enumerate(tasks)]
        for chunk in _chunk_task_lines(lines, header):
            await update.message.reply_text(chunk)

    return cmd_list


# ── /done — required numeric argument ────────────────────────────────────────


async def _run_done(service: TaskService, raw_arg: str) -> str:
    arg = raw_arg.strip()
    if not arg.isdigit():
        return "Нужен номер задачи (число) — посмотрите /list."

    index = int(arg)
    ok = await service.mark_done(index)
    if ok:
        return f"✅ Задача {index} отмечена как выполненная."
    return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."


def make_cmd_done(service: TaskService, pending_state: PendingCommandState):
    async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        args = ctx.args or []
        if len(args) != 1 or not args[0].isdigit():
            if chat_id is not None:
                pending_state.start(chat_id, "done")
            await update.message.reply_text(
                "Какую задачу отметить выполненной? Пришлите номер из /list следующим сообщением."
            )
            return

        try:
            reply = await _run_done(service, args[0])
        except OSError as exc:
            logger.error("Failed to update tasks file: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_done


# ── /deadline — optional per-task deadline: <номер> <ГГГГ-ММ-ДД> or <номер> off ─

_DEADLINE_OFF_VALUES = {"off", "нет", "убрать", "-"}


async def _run_deadline(service: TaskService, raw: str) -> str:
    parts = raw.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return (
            "Не понял. Формат: «<номер> <ГГГГ-ММ-ДД>», например «3 2026-09-20», "
            "или «3 off», чтобы убрать дедлайн."
        )

    index = int(parts[0])
    value = parts[1].strip().lower()

    if value in _DEADLINE_OFF_VALUES:
        ok = await service.set_deadline(index, None)
        if ok:
            return f"🗓 Дедлайн у задачи {index} убран."
        return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."

    try:
        deadline = date.fromisoformat(parts[1].strip())
    except ValueError:
        return "Дата должна быть в формате ГГГГ-ММ-ДД, например 2026-09-20."

    ok = await service.set_deadline(index, deadline)
    if ok:
        return f"🗓 Дедлайн задачи {index}: {deadline.isoformat()}."
    return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."


def _has_valid_deadline_args(raw: str) -> bool:
    parts = raw.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return False
    value = parts[1].strip().lower()
    if value in _DEADLINE_OFF_VALUES:
        return True
    try:
        date.fromisoformat(parts[1].strip())
    except ValueError:
        return False
    return True


def make_cmd_deadline(service: TaskService, pending_state: PendingCommandState):
    async def cmd_deadline(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        raw = " ".join(ctx.args or []).strip()
        if not _has_valid_deadline_args(raw):
            if chat_id is not None:
                pending_state.start(chat_id, "deadline")
            await update.message.reply_text(
                "Какой задаче и на какую дату поставить дедлайн? Пришлите номер (из "
                "/list) и дату через пробел, например «3 2026-09-20», или «3 off», "
                "чтобы убрать дедлайн. Дедлайн необязателен — можно оставить как есть."
            )
            return

        try:
            reply = await _run_deadline(service, raw)
        except OSError as exc:
            logger.error("Failed to update task deadline: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_deadline


# ── /priority — <номер> <уровень 0-5 или слово>, or <номер> off ────────────────

_PRIORITY_OFF_VALUES = {"off", "нет", "убрать", "-"}


async def _run_priority(service: TaskService, raw: str) -> str:
    parts = raw.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return (
            "Не понял. Формат: «<номер> <приоритет>», например «3 высокий» или "
            f"«3 2» ({_PRIORITY_LEVELS_HINT}). «3 off» — убрать приоритет."
        )

    index = int(parts[0])
    value = parts[1].strip().lower()

    if value in _PRIORITY_OFF_VALUES:
        ok = await service.set_priority(index, None)
        if ok:
            return f"🚩 Приоритет у задачи {index} убран."
        return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."

    level = parse_priority_input(value)
    if level is None:
        return f"Приоритет не распознан. Допустимо: {_PRIORITY_LEVELS_HINT}."

    ok = await service.set_priority(index, level)
    if ok:
        return f"🚩 Приоритет задачи {index}: {PRIORITY_LABELS[level]}."
    return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."


def _has_valid_priority_args(raw: str) -> bool:
    parts = raw.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return False
    value = parts[1].strip().lower()
    return value in _PRIORITY_OFF_VALUES or parse_priority_input(value) is not None


def make_cmd_priority(service: TaskService, pending_state: PendingCommandState):
    async def cmd_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        raw = " ".join(ctx.args or []).strip()
        if not _has_valid_priority_args(raw):
            if chat_id is not None:
                pending_state.start(chat_id, "priority")
            await update.message.reply_text(
                "Какой задаче и какой приоритет поставить? Пришлите номер (из /list) "
                f"и уровень через пробел, например «3 высокий» или «3 2» "
                f"({_PRIORITY_LEVELS_HINT}). «3 off» — убрать приоритет."
            )
            return

        try:
            reply = await _run_priority(service, raw)
        except OSError as exc:
            logger.error("Failed to update task priority: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_priority


# ── /setcategory — <номер> <раздел>, or <номер> off ─────────────────────────

_CATEGORY_OFF_VALUES = {"off", "нет", "убрать", "-"}


async def _run_setcategory(service: TaskService, raw: str) -> str:
    parts = raw.split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        return (
            "Не понял. Формат: «<номер> <раздел>», например «3 Маркетинг». "
            "«3 off» — убрать раздел."
        )

    index = int(parts[0])
    value = parts[1].strip()

    if value.lower() in _CATEGORY_OFF_VALUES:
        ok = await service.set_category(index, None)
        if ok:
            return f"🗂 Раздел у задачи {index} убран."
        return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."

    ok = await service.set_category(index, value)
    if ok:
        return f"🗂 Раздел задачи {index}: {value}."
    return f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."


def _has_valid_setcategory_args(raw: str) -> bool:
    parts = raw.split(maxsplit=1)
    return len(parts) == 2 and parts[0].isdigit() and bool(parts[1].strip())


def make_cmd_setcategory(service: TaskService, pending_state: PendingCommandState):
    async def cmd_setcategory(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        raw = " ".join(ctx.args or []).strip()
        if not _has_valid_setcategory_args(raw):
            if chat_id is not None:
                pending_state.start(chat_id, "setcategory")
            await update.message.reply_text(
                "Какой задаче и какой раздел поставить? Пришлите номер (из /list) "
                "и раздел через пробел, например «3 Маркетинг». «3 off» — убрать раздел."
            )
            return

        try:
            reply = await _run_setcategory(service, raw)
        except OSError as exc:
            logger.error("Failed to update task category: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_setcategory


# ── /plan — required free-text argument ──────────────────────────────────────


async def _run_plan(service: TaskService, text: str) -> str:
    planned = await service.plan_day(text)
    if not planned:
        return "🤔 Не удалось выделить ни одной задачи из текста."

    lines = [f"• {p.text} → {p.section}" for p in planned]
    return f"✅ Добавлено задач: {len(planned)}\n\n" + "\n".join(lines)


def make_cmd_plan(service: TaskService, pending_state: PendingCommandState):
    async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        text = " ".join(ctx.args or []).strip()
        if not text:
            if chat_id is not None:
                pending_state.start(chat_id, "plan")
            await update.message.reply_text(
                "Что запланировать на день? Опишите одним сообщением, например:\n"
                "«Позвонить Иванову, закончить презентацию, забрать посылку»."
            )
            return

        try:
            reply = await _run_plan(service, text)
        except OSError as exc:
            logger.error("Failed to write planned tasks: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_plan


# ── /search — required free-text argument ────────────────────────────────────


async def _run_search(service: SearchService, query: str) -> str:
    return await service.search(query)


def make_cmd_search(service: SearchService, pending_state: PendingCommandState):
    async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        query = " ".join(ctx.args or []).strip()
        if not query:
            if chat_id is not None:
                pending_state.start(chat_id, "search")
            await update.message.reply_text("🔍 Что искать? Напишите запрос следующим сообщением.")
            return

        try:
            reply = await _run_search(service, query)
        except OSError as exc:
            logger.error("Failed to read tasks file for search: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_search


# ── /contact — required free-text argument (person's name) ───────────────────


async def _run_contact(service: ContactService, name: str) -> str:
    return await service.find(name)


def make_cmd_contact(service: ContactService, pending_state: PendingCommandState):
    async def cmd_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        chat_id = _chat_id(update)
        if chat_id is not None:
            pending_state.clear(chat_id)

        name = " ".join(ctx.args or []).strip()
        if not name:
            if chat_id is not None:
                pending_state.start(chat_id, "contact")
            await update.message.reply_text(
                "👤 Чьё имя искать? Напишите следующим сообщением."
            )
            return

        try:
            reply = await _run_contact(service, name)
        except OSError as exc:
            logger.error("Failed to search vault for contact: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_contact


# ── /reindex — no arguments, syncs the vault search index on demand ──────────

REINDEX_NOT_CONFIGURED_TEXT = (
    "🔍 OBSIDIAN_VAULT_PATH не настроен — индексировать нечего. "
    "Семантический поиск (Second Brain) выключен."
)
REINDEX_INDEX_NOT_READY_TEXT = (
    "⚠️ Индекс vault ещё не готов — либо Ollama была недоступна при старте "
    "бота (проверьте OLLAMA_BASE_URL/OLLAMA_EMBED_MODEL), либо бот только "
    "что перезапустился. Переиндексация заработает после следующего "
    "успешного старта, когда Ollama будет доступна."
)
REINDEX_FAILED_TEXT = (
    "⚠️ Ollama недоступна прямо сейчас — переиндексация прервана, индекс не тронут."
)


async def _run_reindex(
    vault_path: Path | None,
    vault_index: VaultIndex | None,
    embeddings: EmbeddingClient | None,
) -> str:
    if vault_path is None:
        return REINDEX_NOT_CONFIGURED_TEXT
    if vault_index is None or embeddings is None:
        return REINDEX_INDEX_NOT_READY_TEXT

    stats = await reindex_vault(vault_path, vault_index, embeddings)
    if stats.failed:
        return REINDEX_FAILED_TEXT

    return (
        f"✅ Готово: добавлено {stats.added}, обновлено {stats.updated}, "
        f"удалено {stats.deleted}, без изменений {stats.unchanged}."
    )


def make_cmd_reindex(vault_path: Path | None):
    async def cmd_reindex(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        # vault_index/embeddings only exist once post_init's Ollama dim-probe
        # has succeeded (main.py), so they're read from bot_data at call
        # time rather than captured at registration time, when they'd still
        # be None even in a correctly-configured setup.
        vault_index = ctx.application.bot_data.get("vault_index")
        embeddings = ctx.application.bot_data.get("embeddings")

        try:
            reply = await _run_reindex(vault_path, vault_index, embeddings)
        except OSError as exc:
            logger.error("Vault reindex failed: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_reindex


# ── /reindex-mail — no arguments, syncs the Gmail search index on demand ─────

REINDEX_MAIL_NOT_CONFIGURED_TEXT = "📧 Gmail не настроен — индексировать нечего."
REINDEX_MAIL_INDEX_NOT_READY_TEXT = (
    "⚠️ Индекс почты ещё не готов — либо Ollama была недоступна при старте "
    "бота (проверьте OLLAMA_BASE_URL/OLLAMA_EMBED_MODEL), либо бот только "
    "что перезапустился. Переиндексация заработает после следующего "
    "успешного старта, когда Ollama будет доступна."
)
REINDEX_MAIL_FAILED_TEXT = (
    "⚠️ Ollama недоступна прямо сейчас — переиндексация прервана, индекс не тронут."
)


async def _run_reindex_mail(
    gmail_configured: bool,
    mail_index: MailIndex | None,
    gmail: GmailClient | None,
    embeddings: EmbeddingClient | None,
    retention: timedelta,
) -> str:
    if not gmail_configured:
        return REINDEX_MAIL_NOT_CONFIGURED_TEXT
    if mail_index is None or gmail is None or embeddings is None:
        return REINDEX_MAIL_INDEX_NOT_READY_TEXT

    stats = await reindex_mail(gmail, mail_index, embeddings, retention, datetime.now(UTC))
    if stats.failed:
        return REINDEX_MAIL_FAILED_TEXT

    return f"✅ Готово: добавлено {stats.added}, удалено по retention {stats.deleted}."


def make_cmd_reindex_mail(gmail_configured: bool, retention: timedelta):
    async def cmd_reindex_mail(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        # Same reasoning as /reindex: mail_index/embeddings only exist once
        # post_init's Ollama dim-probe has succeeded, so read from bot_data
        # at call time. gmail itself is always in bot_data once configured
        # (built in register_handlers, independent of the dim-probe) — it's
        # mail_index specifically that gates on Ollama being reachable.
        mail_index = ctx.application.bot_data.get("mail_index")
        gmail = ctx.application.bot_data.get("gmail")
        embeddings = ctx.application.bot_data.get("embeddings")

        try:
            reply = await _run_reindex_mail(
                gmail_configured, mail_index, gmail, embeddings, retention
            )
        except OSError as exc:
            logger.error("Mail reindex failed: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(reply)

    return cmd_reindex_mail


# ── /review — on-demand weekly review (also sent proactively by the scheduler) ─


def make_cmd_review(digest: DigestService):
    async def cmd_review(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        try:
            text = await digest.build_weekly_review()
        except OSError as exc:
            logger.error("Failed to build weekly review: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        await update.message.reply_text(text)

    return cmd_review


# ── plain-text messages: reflection reply > pending command > new task ──────


def make_handle_message(
    task_service: TaskService,
    search_service: SearchService,
    reflection_state: ReflectionState,
    reflection_service: ReflectionService,
    pending_state: PendingCommandState,
    contact_service: ContactService,
):
    async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.message.text is None:
            return
        text = update.message.text.strip()
        if not text:
            return

        chat_id = _chat_id(update)

        # A pending evening-reflection prompt takes priority over everything
        # else — the very next message from that chat is the answer to
        # "что сделано?", not a new task or a command argument.
        if chat_id is not None and reflection_state.is_awaiting(chat_id):
            reflection_state.clear(chat_id)
            try:
                summary = await reflection_service.process_reply(text)
            except OSError as exc:
                logger.error("Failed to process reflection reply: %s", exc)
                await update.message.reply_text(GENERIC_ERROR_TEXT)
                return
            await update.message.reply_text(summary)
            return

        # A command issued without its argument (e.g. bare "/search") is
        # waiting for this message to be that argument.
        if chat_id is not None and pending_state.is_pending(chat_id):
            command = pending_state.pop(chat_id)
            try:
                if command == "search":
                    reply = await _run_search(search_service, text)
                elif command == "done":
                    reply = await _run_done(task_service, text)
                elif command == "plan":
                    reply = await _run_plan(task_service, text)
                elif command == "deadline":
                    reply = await _run_deadline(task_service, text)
                elif command == "priority":
                    reply = await _run_priority(task_service, text)
                elif command == "setcategory":
                    reply = await _run_setcategory(task_service, text)
                elif command == "contact":
                    reply = await _run_contact(contact_service, text)
                else:  # pragma: no cover — defensive, all known commands handled above
                    reply = None
            except OSError as exc:
                logger.error("Failed to complete pending command %r: %s", command, exc)
                await update.message.reply_text(GENERIC_ERROR_TEXT)
                return

            if reply is not None:
                await update.message.reply_text(reply)
                return

        try:
            section = await task_service.add_task(text)
        except OSError as exc:
            logger.error("Failed to write task: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        user_id = update.effective_user.id if update.effective_user else "?"
        logger.info("Task added by user=%s (%d chars) -> section=%s", user_id, len(text), section)
        await update.message.reply_text(f"✅ Добавлено в «{section}»")

    return handle_message
