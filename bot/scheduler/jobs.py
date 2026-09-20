"""Cron-style scheduling for proactive messages (morning digest, evening
reflection). Deliberately its own module: proactive behaviour must not live
inside Telegram handlers, since it's triggered by time, not by an incoming
update.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from config import BotConfig
from integrations.embedding_client import EmbeddingClient
from services.digest_service import DigestService
from services.meeting_brief_service import MeetingBriefService
from services.reflection_service import ReflectionState
from services.vault_indexer import reindex_vault
from telegram.ext import Application
from vault_index import VaultIndex

logger = logging.getLogger(__name__)

# How often to poll for upcoming meetings. Must be small enough that no
# meeting starting within its lead-time window is missed between polls —
# see MeetingBriefService's poll_window, which this should stay well inside.
MEETING_BRIEF_POLL_MINUTES = 5


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":", 1)
    return int(hour_str), int(minute_str)


def setup_scheduler(
    app: Application,
    config: BotConfig,
    digest: DigestService,
    reflection_state: ReflectionState,
    meeting_briefs: MeetingBriefService | None = None,
    vault_index: VaultIndex | None = None,
    embeddings: EmbeddingClient | None = None,
) -> AsyncIOScheduler | None:
    """Register the morning/evening/weekly jobs (need TELEGRAM_CHAT_ID), plus
    meeting-brief polling if *meeting_briefs* is given (Google Calendar
    configured), plus periodic vault reindexing if *vault_index*/*embeddings*
    are given (OBSIDIAN_VAULT_PATH configured — Second Brain). The chat-based
    jobs and vault reindexing are independent: reindexing needs no chat to
    message, so it still runs even without TELEGRAM_CHAT_ID set. Returns None
    only if there is nothing at all to schedule.
    """
    tz = ZoneInfo(config.timezone)
    scheduler = AsyncIOScheduler(timezone=config.timezone)
    registered: list[str] = []

    if config.chat_id is None:
        logger.warning(
            "TELEGRAM_CHAT_ID not configured — morning digest and evening "
            "reflection are disabled. Set it in .env to enable proactive messages."
        )
    else:
        chat_id = config.chat_id

        async def send_morning_digest() -> None:
            text = await digest.build_morning_digest()
            await app.bot.send_message(chat_id=chat_id, text=text)

        async def send_evening_prompt() -> None:
            text = await digest.build_evening_prompt()
            reflection_state.start(chat_id)
            await app.bot.send_message(chat_id=chat_id, text=text)

        async def send_weekly_review() -> None:
            text = await digest.build_weekly_review()
            await app.bot.send_message(chat_id=chat_id, text=text)

        morning_hour, morning_minute = _parse_hhmm(config.morning_digest_time)
        scheduler.add_job(
            send_morning_digest,
            CronTrigger(hour=morning_hour, minute=morning_minute),
            id="morning_digest",
            replace_existing=True,
        )
        registered.append(f"morning digest at {config.morning_digest_time}")

        evening_hour, evening_minute = _parse_hhmm(config.evening_reflection_time)
        scheduler.add_job(
            send_evening_prompt,
            CronTrigger(hour=evening_hour, minute=evening_minute),
            id="evening_reflection",
            replace_existing=True,
        )
        registered.append(f"evening reflection at {config.evening_reflection_time}")

        weekly_hour, weekly_minute = _parse_hhmm(config.weekly_review_time)
        scheduler.add_job(
            send_weekly_review,
            CronTrigger(
                day_of_week=config.weekly_review_day, hour=weekly_hour, minute=weekly_minute
            ),
            id="weekly_review",
            replace_existing=True,
        )
        registered.append(
            f"weekly review on {config.weekly_review_day} at {config.weekly_review_time}"
        )

        if meeting_briefs is not None:
            briefs = meeting_briefs  # narrowed to non-None for the closure below

            async def send_meeting_briefs() -> None:
                due = await briefs.due_briefs(datetime.now(tz=tz))
                for _event, brief in due:
                    await app.bot.send_message(chat_id=chat_id, text=brief)

            scheduler.add_job(
                send_meeting_briefs,
                IntervalTrigger(minutes=MEETING_BRIEF_POLL_MINUTES),
                id="meeting_briefs",
                replace_existing=True,
            )
            registered.append("meeting briefs")

    if config.has_vault_index and vault_index is not None and embeddings is not None:
        vault_path = config.obsidian_vault_path
        assert vault_path is not None  # guaranteed by has_vault_index

        async def run_vault_reindex() -> None:
            stats = await reindex_vault(vault_path, vault_index, embeddings)
            if stats.failed:
                logger.warning(
                    "Scheduled vault reindex could not complete (embedding backend unavailable)"
                )

        scheduler.add_job(
            run_vault_reindex,
            IntervalTrigger(minutes=config.vault_reindex_interval_minutes),
            id="vault_reindex",
            replace_existing=True,
        )
        registered.append(f"vault reindex every {config.vault_reindex_interval_minutes}min")

    if not registered:
        return None

    scheduler.start()
    logger.info("Scheduler started: %s", ", ".join(registered))
    return scheduler
