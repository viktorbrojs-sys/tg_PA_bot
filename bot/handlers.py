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

from services.pending_command_state import PendingCommandState
from services.reflection_service import ReflectionService, ReflectionState
from services.search_service import SearchService
from services.task_service import TaskService
from telegram import Update
from telegram.ext import ContextTypes

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
    ("done", "Отметить задачу как выполненную (номер из /list)"),
    ("help", "Справка по командам"),
]

WELCOME_TEXT = (
    "👋 Бот-секретарь для Obsidian.\n\n"
    "Просто напишите текст — задача автоматически классифицируется по разделу "
    "и появится в вашем файле.\n\n"
    "Команды:\n"
    "/list — все открытые задачи (можно /list 20 — только последние N)\n"
    "/plan <текст> — разбить сообщение на несколько задач на день\n"
    "/search <запрос> — найти информацию в заметках\n"
    "/done N — отметить задачу N (из /list) как выполненную\n"
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
    "• /search <запрос> — найти информацию в заметках\n"
    "• /done N — отметить N-ю задачу из /list как выполненную\n"
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


# ── plain-text messages: reflection reply > pending command > new task ──────


def make_handle_message(
    task_service: TaskService,
    search_service: SearchService,
    reflection_state: ReflectionState,
    reflection_service: ReflectionService,
    pending_state: PendingCommandState,
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
