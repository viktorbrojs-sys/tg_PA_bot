"""Morning digest / evening reflection prompt / weekly review generation.

Traffic is still a separate future integration (needs a keyed API, unlike
weather/calendar). Weather and calendar events are both optional — pass a
real client to include them in the morning digest; without one (the
Null* fallback, the default), the digest is exactly what it was before that
feature existed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from integrations.gmail_client import GmailClient, NullGmailClient
from integrations.google_calendar import CalendarClient, NullCalendarClient
from integrations.weather_client import (
    UMBRELLA_THRESHOLD,
    NullWeatherClient,
    WeatherClient,
    describe_weather_code,
)
from storage import PRIORITY_URGENCY, UNTAGGED_PRIORITY_URGENCY, extract_deadline, extract_priority

from services.task_service import TaskService

WEEKLY_REVIEW_WINDOW = timedelta(days=7)
MAIL_DIGEST_PREVIEW_LIMIT = 5


def _is_overdue(task_text: str, today: date) -> bool:
    deadline = extract_deadline(task_text)
    return deadline is not None and deadline <= today


def _pick_main_task(tasks: list[str]) -> str:
    """Pick the task to call out as "главная задача дня".

    Prefers the most urgent priority tag present (see PRIORITY_URGENCY —
    note this is NOT the same order as the 0-5 numbering, since "FYI" is
    informational, ranking below even an untagged task). ``min()`` returns
    the first item on ties, so with no priorities tagged at all this is
    exactly the old "just take the first task" behaviour.
    """

    def urgency(task: str) -> int:
        priority = extract_priority(task)
        if priority is None:
            return UNTAGGED_PRIORITY_URGENCY
        return PRIORITY_URGENCY.get(priority, UNTAGGED_PRIORITY_URGENCY)

    return min(tasks, key=urgency)


class DigestService:
    def __init__(
        self,
        task_service: TaskService,
        calendar: CalendarClient | None = None,
        weather: WeatherClient | None = None,
        gmail: GmailClient | None = None,
        now: Callable[[], datetime] = datetime.now,
        timezone: str = "UTC",
    ) -> None:
        self._tasks = task_service
        self._calendar = calendar or NullCalendarClient()
        self._weather = weather or NullWeatherClient()
        self._gmail = gmail or NullGmailClient()
        self._now = now
        self._tz = ZoneInfo(timezone)

    async def build_morning_digest(self) -> str:
        tasks = await self._tasks.list_all_open_tasks()
        weather_line = await self._build_weather_line()
        events_text = await self._build_events_section()
        mail_text = await self._build_mail_section()

        lines = ["🌅 Доброе утро!"]
        if weather_line:
            lines.append(weather_line)

        if not tasks:
            lines.append("Открытых задач нет — можно спланировать день командой /plan.")
            if events_text:
                lines.append(events_text)
            if mail_text:
                lines.append(mail_text)
            return "\n".join(lines)

        today = self._now().date()
        overdue = [t for t in tasks if _is_overdue(t, today)]

        lines.append(f"Открытых задач: {len(tasks)}")
        if overdue:
            lines.append(f"⚠️ Просрочено или истекает сегодня: {len(overdue)}")
            lines.extend(f"  • {t}" for t in overdue[:5])
        if events_text:
            lines.append(events_text)
        if mail_text:
            lines.append(mail_text)
        lines.append(f"\nГлавная задача дня: {_pick_main_task(tasks)}")
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

    async def _build_mail_section(self) -> str | None:
        messages = await self._gmail.list_unread(limit=MAIL_DIGEST_PREVIEW_LIMIT)
        if not messages:
            return None

        total = await self._gmail.count_unread()
        if total is not None:
            lines = [f"\n📧 Непрочитанных писем: {total}"]
        else:
            lines = ["\n📧 Непрочитанные письма:"]
        lines.extend(
            f"  • {m.sender_name or m.sender_email or m.sender}: {m.subject}" for m in messages
        )
        if total is not None and total > len(messages):
            lines.append(f"  …и ещё {total - len(messages)}")
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
