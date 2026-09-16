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
from services.digest_service import DigestService
from services.meeting_brief_service import MeetingBriefService
from services.reflection_service import ReflectionState
from telegram.ext import Application

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
) -> AsyncIOScheduler | None:
    """Register the morning/evening/weekly jobs, plus meeting-brief polling if
    *meeting_briefs* is given (i.e. Google Calendar is configured). Returns
    None (and logs a warning) if there's no chat to proactively message —
    set TELEGRAM_CHAT_ID to enable.
    """
    if config.chat_id is None:
        logger.warning(
            "TELEGRAM_CHAT_ID not configured — morning digest and evening "
            "reflection are disabled. Set it in .env to enable proactive messages."
        )
        return None

    chat_id = config.chat_id
    tz = ZoneInfo(config.timezone)
    scheduler = AsyncIOScheduler(timezone=config.timezone)

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

    evening_hour, evening_minute = _parse_hhmm(config.evening_reflection_time)
    scheduler.add_job(
        send_evening_prompt,
        CronTrigger(hour=evening_hour, minute=evening_minute),
        id="evening_reflection",
        replace_existing=True,
    )

    weekly_hour, weekly_minute = _parse_hhmm(config.weekly_review_time)
    scheduler.add_job(
        send_weekly_review,
        CronTrigger(
            day_of_week=config.weekly_review_day, hour=weekly_hour, minute=weekly_minute
        ),
        id="weekly_review",
        replace_existing=True,
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

    scheduler.start()
    logger.info(
        "Scheduler started: morning digest at %s, evening reflection at %s, "
        "weekly review on %s at %s (%s), meeting briefs %s",
        config.morning_digest_time,
        config.evening_reflection_time,
        config.weekly_review_day,
        config.weekly_review_time,
        config.timezone,
        "enabled" if meeting_briefs is not None else "disabled (no calendar configured)",
    )
    return scheduler
