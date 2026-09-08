"""Entry point — starts the Telegram bot with long polling."""

from __future__ import annotations

import logging
import sys

from config import BotConfig, load_config
from handlers import (
    cmd_help,
    cmd_start,
    cmd_unknown,
    make_cmd_done,
    make_cmd_list,
    make_cmd_plan,
    make_handle_message,
)
from integrations.llm_client import DeepSeekClient, LLMClient, NullLLMClient
from services.task_service import TaskService
from storage import TaskStore
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

logger = logging.getLogger(__name__)


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=getattr(logging, level_name, logging.INFO),
        stream=sys.stdout,
    )


def build_app(token: str) -> Application:
    return Application.builder().token(token).build()


def make_access_guard(allowed_ids: frozenset[int]):
    """Middleware: block users not in the allowlist (when the list is non-empty).

    Registered in handler group -1 so it runs before every other handler.
    Raising ApplicationHandlerStop is what actually stops PTB from calling
    any handler in later groups for this update — without it, a "blocked"
    reply would be sent but the message would still be processed normally.
    """

    async def access_guard(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is not None and user.id in allowed_ids:
            return  # allowed — let the update continue to normal handlers

        uid = user.id if user else "unknown"
        logger.warning("Blocked unauthorised access attempt from user_id=%s", uid)
        if update.effective_message:
            await update.effective_message.reply_text("⛔ У вас нет доступа к этому боту.")
        raise ApplicationHandlerStop

    return access_guard


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception(
        "Unhandled exception while processing update: %s", update, exc_info=context.error
    )
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Произошла внутренняя ошибка. Попробуйте ещё раз чуть позже."
            )
        except TelegramError:
            pass  # best-effort notification only


def build_llm_client(config: BotConfig) -> LLMClient:
    if config.deepseek_api_key:
        return DeepSeekClient(api_key=config.deepseek_api_key, model=config.llm_model)
    return NullLLMClient()


def register_handlers(app: Application, config: BotConfig) -> None:
    store = TaskStore(config.obsidian_file)
    llm = build_llm_client(config)
    service = TaskService(store, llm, sections=config.task_sections)

    if config.has_allowlist:
        app.add_handler(TypeHandler(Update, make_access_guard(config.allowed_user_ids)), group=-1)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", make_cmd_list(service)))
    app.add_handler(CommandHandler("done", make_cmd_done(service)))
    app.add_handler(CommandHandler("plan", make_cmd_plan(service)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, make_handle_message(service)))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    app.add_error_handler(on_error)


def main() -> None:
    # Logging must exist before load_config() can log anything meaningful.
    configure_logging("INFO")
    config = load_config()
    if config is None:
        logger.error("Cannot start: configuration is invalid (see errors above).")
        sys.exit(1)

    # Re-apply logging now that we know the configured LOG_LEVEL.
    configure_logging(config.log_level)

    app = build_app(config.token)
    register_handlers(app, config)

    logger.info(
        "Starting bot (long polling) | file=%s | allowlist=%s",
        config.obsidian_file,
        sorted(config.allowed_user_ids) or "disabled",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
