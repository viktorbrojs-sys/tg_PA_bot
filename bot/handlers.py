"""Telegram command and message handlers."""

from __future__ import annotations

import logging

from storage import TaskStore
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

LIST_LIMIT = 20

WELCOME_TEXT = (
    "👋 Бот для добавления задач в Obsidian.\n\n"
    "Просто напишите любой текст — задача появится в вашем файле как `- [ ] текст`.\n\n"
    "Команды:\n"
    "/list — последние до 20 невыполненных задач\n"
    "/done N — отметить задачу N (из /list) как выполненную\n"
    "/help — справка"
)

HELP_TEXT = (
    "📋 Как пользоваться:\n\n"
    "• Любой текст → задача добавится как `- [ ] текст`\n"
    "• /list — последние невыполненные задачи (до 20)\n"
    "• /done N — отметить N-ю задачу из /list как выполненную\n"
    "• /start — приветствие\n"
    "• /help — эта справка"
)

GENERIC_ERROR_TEXT = (
    "❌ Не удалось выполнить операцию с файлом задач.\n"
    "Проверьте доступ к файлу и переменную OBSIDIAN_FILE."
)


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


def make_cmd_list(store: TaskStore):
    async def cmd_list(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        try:
            tasks = await store.list_open_tasks(LIST_LIMIT)
        except OSError as exc:
            logger.error("Failed to read tasks file: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        if not tasks:
            await update.message.reply_text("🎉 Нет невыполненных задач!")
            return

        body = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(tasks))
        await update.message.reply_text(
            f"📋 Последние невыполненные задачи (до {LIST_LIMIT}):\n\n{body}"
        )

    return cmd_list


def make_cmd_done(store: TaskStore):
    async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return

        args = ctx.args or []
        if len(args) != 1 or not args[0].isdigit():
            await update.message.reply_text("Использование: /done N — где N — номер из /list.")
            return

        index = int(args[0])
        try:
            ok = await store.mark_done(index)
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


def make_handle_message(store: TaskStore):
    async def handle_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or update.message.text is None:
            return
        text = update.message.text.strip()
        if not text:
            return

        try:
            await store.add_task(text)
        except OSError as exc:
            logger.error("Failed to write task: %s", exc)
            await update.message.reply_text(GENERIC_ERROR_TEXT)
            return

        user_id = update.effective_user.id if update.effective_user else "?"
        logger.info("Task added by user=%s (%d chars)", user_id, len(text))
        await update.message.reply_text("✅ Добавлено в задачи")

    return handle_message
