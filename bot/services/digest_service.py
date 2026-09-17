"""Morning digest / evening reflection prompt / weekly review generation.

Traffic is still a separate future integration (needs a keyed API, unlike
weather/calendar). Weather and calendar events are both optional — pass a
real client to include them in the morning digest; without one (the
Null* fallback, the default), the digest is exactly what it was before that
feature existed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from integrations.google_calendar import CalendarClient, NullCalendarClient
from integrations.weather_client import (
    UMBRELLA_THRESHOLD,
    NullWeatherClient,
    WeatherClient,
    describe_weather_code,
)

from services.task_service import TaskService

# Matches the deadline tag convention from the feature list: "@2026-09-10".
_DEADLINE_RE = re.compile(r"@(\d{4}-\d{2}-\d{2})")

WEEKLY_REVIEW_WINDOW = timedelta(days=7)


def _extract_deadline(task_text: str) -> date | None:
    match = _DEADLINE_RE.search(task_text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _is_overdue(task_text: str, today: date) -> bool:
    deadline = _extract_deadline(task_text)
    return deadline is not None and deadline <= today


class DigestService:
    def __init__(
        self,
        task_service: TaskService,
        calendar: CalendarClient | None = None,
        weather: WeatherClient | None = None,
        now: Callable[[], datetime] = datetime.now,
        timezone: str = "UTC",
    ) -> None:
        self._tasks = task_service
        self._calendar = calendar or NullCalendarClient()
        self._weather = weather or NullWeatherClient()
        self._now = now
        self._tz = ZoneInfo(timezone)

    async def build_morning_digest(self) -> str:
        tasks = await self._tasks.list_all_open_tasks()
        weather_line = await self._build_weather_line()
        events_text = await self._build_events_section()

        lines = ["🌅 Доброе утро!"]
        if weather_line:
            lines.append(weather_line)

        if not tasks:
            lines.append("Открытых задач нет — можно спланировать день командой /plan.")
            if events_text:
                lines.append(events_text)
            return "\n".join(lines)

        today = self._now().date()
        overdue = [t for t in tasks if _is_overdue(t, today)]

        lines.append(f"Открытых задач: {len(tasks)}")
        if overdue:
            lines.append(f"⚠️ Просрочено или истекает сегодня: {len(overdue)}")
            lines.extend(f"  • {t}" for t in overdue[:5])
        if events_text:
            lines.append(events_text)
        lines.append(f"\nГлавная задача дня: {tasks[0]}")
        return "\n".join(lines)

    async def build_evening_prompt(self) -> str:
        tasks = await self._tasks.list_all_open_tasks()
        if not tasks:
            return "🌙 На сегодня не было открытых задач. Как прошёл день?"

        lines = ["🌙 Что сделано из запланированного? Опишите свободным текстом.", ""]
        lines.extend(f"{i + 1}. {t}" for i, t in enumerate(tasks))
        return "\n".join(lines)

    async def build_weekly_review(self) -> str:
        since = self._now() - WEEKLY_REVIEW_WINDOW
        completed = await self._tasks.list_completed_since(since)

        if not completed:
            return (
                "📊 Еженедельный обзор: за последние 7 дней нет задач, "
                "отмеченных выполненными (или они были закрыты до появления "
                "этой функции — для них нет даты выполнения)."
            )

        lines = [f"📊 Еженедельный обзор: выполнено задач за 7 дней — {len(completed)}", ""]
        lines.extend(f"✅ {t}" for t in completed)
        return "\n".join(lines)

    async def _build_events_section(self) -> str | None:
        now_dt = self._now()
        local_now = now_dt if now_dt.tzinfo else now_dt.replace(tzinfo=self._tz)
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        events = await self._calendar.list_events(start, end)
        if not events:
            return None

        lines = [f"\n📅 Встречи сегодня ({len(events)}):"]
        lines.extend(f"  • {e.start.strftime('%H:%M')} — {e.summary}" for e in events)
        return "\n".join(lines)

    async def _build_weather_line(self) -> str | None:
        weather = await self._weather.today()
        if weather is None:
            return None

        description = describe_weather_code(weather.weather_code)
        line = (
            f"🌤 Погода: {description}, "
            f"{weather.temp_min:.0f}…{weather.temp_max:.0f}°C"
        )
        if weather.precipitation_probability >= UMBRELLA_THRESHOLD:
            line += f", вероятность осадков {weather.precipitation_probability}% — возьмите зонт ☔"
        return line
