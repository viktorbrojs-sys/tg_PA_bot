"""Entry point — starts the Telegram bot with long polling."""

from __future__ import annotations

import logging
import sys
from datetime import timedelta

from config import BotConfig, load_config
from handlers import (
    BOT_COMMANDS,
    cmd_help,
    cmd_start,
    cmd_unknown,
    make_cmd_contact,
    make_cmd_deadline,
    make_cmd_done,
    make_cmd_list,
    make_cmd_plan,
    make_cmd_priority,
    make_cmd_reindex,
    make_cmd_review,
    make_cmd_search,
    make_cmd_setcategory,
    make_handle_message,
)
from integrations.embedding_client import (
    EmbeddingClient,
    NullEmbeddingClient,
    OllamaEmbeddingClient,
)
from integrations.gmail_client import GmailClient, GoogleGmailClient, NullGmailClient
from integrations.google_calendar import CalendarClient, GoogleCalendarClient, NullCalendarClient
from integrations.llm_client import DeepSeekClient, LLMClient, NullLLMClient
from integrations.weather_client import NullWeatherClient, OpenMeteoClient, WeatherClient
from scheduler.jobs import setup_scheduler
from services.contact_service import ContactService
from services.digest_service import DigestService
from services.meeting_brief_service import MeetingBriefService, MeetingBriefState
from services.pending_command_state import PendingCommandState
from services.reflection_service import ReflectionService, ReflectionState
from services.search_service import SearchService
from services.task_service import TaskService
from storage import TaskStore
from telegram import BotCommand, Update
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
from vault_index import VaultIndex

logger = logging.getLogger(__name__)


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=getattr(logging, level_name, logging.INFO),
        stream=sys.stdout,
    )


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


def build_calendar_client(config: BotConfig) -> CalendarClient:
    if (
        config.google_calendar_client_id
        and config.google_calendar_client_secret
        and config.google_calendar_refresh_token
    ):
        return GoogleCalendarClient(
            client_id=config.google_calendar_client_id,
            client_secret=config.google_calendar_client_secret,
            refresh_token=config.google_calendar_refresh_token,
            calendar_id=config.google_calendar_id,
        )
    return NullCalendarClient()


def build_weather_client(config: BotConfig) -> WeatherClient:
    if config.weather_latitude is not None and config.weather_longitude is not None:
        return OpenMeteoClient(config.weather_latitude, config.weather_longitude)
    return NullWeatherClient()


def build_gmail_client(config: BotConfig) -> GmailClient:
    if config.gmail_client_id and config.gmail_client_secret and config.gmail_refresh_token:
        return GoogleGmailClient(
            client_id=config.gmail_client_id,
            client_secret=config.gmail_client_secret,
            refresh_token=config.gmail_refresh_token,
        )
    return NullGmailClient()


def build_embedding_client(config: BotConfig) -> EmbeddingClient:
    if config.has_vault_index:
        return OllamaEmbeddingClient(
            base_url=config.ollama_base_url, model=config.ollama_embed_model
        )
    return NullEmbeddingClient()


def register_handlers(app: Application, config: BotConfig) -> None:
    store = TaskStore(config.obsidian_file)
    llm = build_llm_client(config)
    calendar = build_calendar_client(config)
    weather = build_weather_client(config)
    gmail = build_gmail_client(config)

    task_service = TaskService(store, llm, sections=config.task_sections)
    search_service = SearchService(store, llm)
    contact_service = ContactService(calendar, vault_path=config.obsidian_vault_path)
    digest_service = DigestService(
        task_service, calendar=calendar, weather=weather, gmail=gmail, timezone=config.timezone
    )
    reflection_state = ReflectionState()
    reflection_service = ReflectionService(task_service, llm)
    pending_state = PendingCommandState()

    meeting_brief_service: MeetingBriefService | None = None
    if config.has_calendar:
        meeting_brief_service = MeetingBriefService(
            calendar,
            search_service,
            MeetingBriefState(),
            lead_time=timedelta(minutes=config.meeting_brief_lead_minutes),
        )

    # Stashed so the post_init callback (which runs once the event loop is
    # already up) can wire the scheduler without rebuilding all of this.
    app.bot_data["digest_service"] = digest_service
    app.bot_data["reflection_state"] = reflection_state
    app.bot_data["meeting_brief_service"] = meeting_brief_service
    app.bot_data["embeddings"] = build_embedding_client(config)
    app.bot_data["search_service"] = search_service

    if config.has_allowlist:
        app.add_handler(TypeHandler(Update, make_access_guard(config.allowed_user_ids)), group=-1)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("list", make_cmd_list(task_service, pending_state)))
    app.add_handler(CommandHandler("done", make_cmd_done(task_service, pending_state)))
    app.add_handler(CommandHandler("deadline", make_cmd_deadline(task_service, pending_state)))
    app.add_handler(CommandHandler("priority", make_cmd_priority(task_service, pending_state)))
    app.add_handler(
        CommandHandler("setcategory", make_cmd_setcategory(task_service, pending_state))
    )
    app.add_handler(CommandHandler("plan", make_cmd_plan(task_service, pending_state)))
    app.add_handler(CommandHandler("search", make_cmd_search(search_service, pending_state)))
    app.add_handler(CommandHandler("contact", make_cmd_contact(contact_service, pending_state)))
    app.add_handler(CommandHandler("reindex", make_cmd_reindex(config.obsidian_vault_path)))
    app.add_handler(CommandHandler("review", make_cmd_review(digest_service)))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            make_handle_message(
                task_service,
                search_service,
                reflection_state,
                reflection_service,
                pending_state,
                contact_service,
            ),
        )
    )
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))

    app.add_error_handler(on_error)


def build_app(config: BotConfig) -> Application:
    async def post_init(app: Application) -> None:
        # Registers the "/" command popup and the ≡ menu button in Telegram
        # clients. Must run after the event loop is up, so it lives here
        # (post_init) rather than in register_handlers().
        await app.bot.set_my_commands(
            [BotCommand(command, description) for command, description in BOT_COMMANDS]
        )

        # The scheduler needs a running event loop, which only exists once
        # PTB's Application has been initialised — hence wiring it here too.
        digest_service: DigestService = app.bot_data["digest_service"]
        reflection_state: ReflectionState = app.bot_data["reflection_state"]
        meeting_brief_service: MeetingBriefService | None = app.bot_data["meeting_brief_service"]

        # VaultIndex needs the embedding dimension up front (sqlite-vec's
        # vec0 tables have a fixed vector width), which we only learn by
        # actually calling Ollama — so this probe happens here, once, at
        # startup, rather than baking a per-model dimension table into the
        # config layer. If Ollama isn't reachable yet, vault indexing is
        # simply skipped for this run (same "degrade gracefully" pattern as
        # a misconfigured calendar/weather integration) — it'll pick back up
        # on the next bot restart once Ollama is up.
        embeddings: EmbeddingClient = app.bot_data["embeddings"]
        vault_index: VaultIndex | None = None
        if config.has_vault_index:
            probe = await embeddings.embed(["_dimension_probe_"])
            if not probe:
                logger.error(
                    "OBSIDIAN_VAULT_PATH задан, но Ollama (%s, модель %s) недоступна — "
                    "индексация vault отключена для этого запуска бота.",
                    config.ollama_base_url,
                    config.ollama_embed_model,
                )
            else:
                vault_index = VaultIndex(config.vault_index_db_path, embedding_dim=len(probe[0]))
                app.bot_data["vault_index"] = vault_index
                search_service: SearchService = app.bot_data["search_service"]
                search_service.enable_semantic_search(vault_index, embeddings)

        app.bot_data["scheduler"] = setup_scheduler(
            app,
            config,
            digest_service,
            reflection_state,
            meeting_brief_service,
            vault_index=vault_index,
            embeddings=embeddings if vault_index is not None else None,
        )

    return Application.builder().token(config.token).post_init(post_init).build()


def main() -> None:
    # Logging must exist before load_config() can log anything meaningful.
    configure_logging("INFO")
    config = load_config()
    if config is None:
        logger.error("Cannot start: configuration is invalid (see errors above).")
        sys.exit(1)

    # Re-apply logging now that we know the configured LOG_LEVEL.
    configure_logging(config.log_level)

    app = build_app(config)
    register_handlers(app, config)

    logger.info(
        "Starting bot (long polling) | file=%s | allowlist=%s",
        config.obsidian_file,
        sorted(config.allowed_user_ids) or "disabled",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
