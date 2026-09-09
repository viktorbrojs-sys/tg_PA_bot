"""Cron-style scheduling for proactive messages (morning digest, evening
reflection). Deliberately its own module: proactive behaviour must not live
inside Telegram handlers, since it's triggered by time, not by an incoming
update.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import BotConfig
from services.digest_service import DigestService
from services.reflection_service import ReflectionState
from telegram.ext import Application

logger = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":", 1)
    return int(hour_str), int(minute_str)


def setup_scheduler(
    app: Application,
    config: BotConfig,
    digest: DigestService,
    reflection_state: ReflectionState,
) -> AsyncIOScheduler | None:
    """Register the morning/evening jobs. Returns None (and logs a warning) if
    there's no chat to proactively message — set TELEGRAM_CHAT_ID to enable.
    """
    if config.chat_id is None:
        logger.warning(
            "TELEGRAM_CHAT_ID not configured — morning digest and evening "
            "reflection are disabled. Set it in .env to enable proactive messages."
        )
        return None

    chat_id = config.chat_id
    scheduler = AsyncIOScheduler(timezone=config.timezone)

    async def send_morning_digest() -> None:
        text = await digest.build_morning_digest()
        await app.bot.send_message(chat_id=chat_id, text=text)

    async def send_evening_prompt() -> None:
        text = await digest.build_evening_prompt()
        reflection_state.start(chat_id)
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

    scheduler.start()
    logger.info(
        "Scheduler started: morning digest at %s, evening reflection at %s (%s)",
        config.morning_digest_time,
        config.evening_reflection_time,
        config.timezone,
    )
    return scheduler
