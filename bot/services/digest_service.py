"""Morning digest / evening reflection prompt / weekly review generation.

Deliberately independent of any calendar/weather integration for now — those
are separate future integrations (see roadmap). This service only knows
about the Obsidian tasks file via ``TaskService``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta

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
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._tasks = task_service
        self._now = now

    async def build_morning_digest(self) -> str:
        tasks = await self._tasks.list_all_open_tasks()
        if not tasks:
            return (
                "🌅 Доброе утро! Открытых задач нет — можно спланировать день "
                "командой /plan."
            )

        today = self._now().date()
        overdue = [t for t in tasks if _is_overdue(t, today)]

        lines = ["🌅 Доброе утро!", f"Открытых задач: {len(tasks)}"]
        if overdue:
            lines.append(f"⚠️ Просрочено или истекает сегодня: {len(overdue)}")
            lines.extend(f"  • {t}" for t in overdue[:5])
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
