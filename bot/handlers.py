"""Telegram command and message handlers.

Handlers stay thin: parse the update, call into ``TaskService``, format the
reply. All classification/day-planning/storage logic lives in
``services/task_service.py`` so it can be unit-tested without Telegram.
"""

from __future__ import annotations

import logging

from services.task_service import TaskService
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Telegram's hard cap is 4096 chars; leave headroom for formatting.
MESSAGE_CHUNK_LIMIT = 3500

WELCOME_TEXT = (
    "👋 Бот-секретарь для Obsidian.\n\n"
    "Просто напишите текст — задача автоматически классифицируется по разделу "
    "и появится в вашем файле.\n\n"
    "Команды:\n"
    "/list — все открытые задачи (можно /list 20 — только последние N)\n"
    "/plan <текст> — разбить сообщение на несколько задач на день\n"
    "/done N — отметить задачу N (из /list) как выполненную\n"
    "/help — справка"
)

HELP_TEXT = (
    "📋 Как пользоваться:\n\n"
    "• Любой текст → задача добавится, ИИ сам определит раздел\n"
    "• /list — полный список открытых задач\n"
    "• /list N — последние N открытых задач\n"
    "• /plan <текст> — разбить сообщение на несколько задач одним вызовом\n"
    "• /done N — отметить N-ю задачу из /list как выполненную\n"
    "• /start — приветствие\n"
    "• /help — эта справка"
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


def make_cmd_list(service: TaskService):
    async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

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


def make_cmd_done(service: TaskService):
    async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        args = ctx.args or []
        if len(args) != 1 or not args[0].isdigit():
            await update.message.reply_text("Использование: /done N — где N — номер из /list.")
            return

        index = int(args[0])
        try:
            ok = await service.mark_done(index)
        except OSError as exc:
            logger.error("Failed to update tasks file: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        if ok:
            await update.message.reply_text(f"✅ Задача {index} отмечена как выполненная.")
        else:
            await update.message.reply_text(
                f"⚠️ Не нашёл задачу с номером {index}. Проверьте /list."
            )

    return cmd_done


def make_cmd_plan(service: TaskService):
    async def cmd_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        text = " ".join(ctx.args or []).strip()
        if not text:
            await update.message.reply_text(
                "Использование: /plan <текст>. Например:\n"
                "/plan Позвонить Иванову, закончить презентацию, забрать посылку"
            )
            return

        try:
            planned = await service.plan_day(text)
        except OSError as exc:
            logger.error("Failed to write planned tasks: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        if not planned:
            await update.message.reply_text("🤔 Не удалось выделить ни одной задачи из текста.")
            return

        lines = [f"• {p.text} → {p.section}" for p in planned]
        await update.message.reply_text(
            f"✅ Добавлено задач: {len(planned)}\n\n" + "\n".join(lines)
        )

    return cmd_plan


def make_handle_message(service: TaskService):
    async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.message.text is None:
            return
        text = update.message.text.strip()
        if not text:
            return

        try:
            section = await service.add_task(text)
        except OSError as exc:
            logger.error("Failed to write task: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        user_id = update.effective_user.id if update.effective_user else "?"
        logger.info("Task added by user=%s (%d chars) -> section=%s", user_id, len(text), section)
        await update.message.reply_text(f"✅ Добавлено в «{section}»")

    return handle_message
