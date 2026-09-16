"""Meeting prep: a short brief sent shortly before a calendar event, built
from matching Obsidian notes (via the existing grep-based ``SearchService``).

``MeetingBriefState`` is deliberately tiny and in-memory, mirroring
``ReflectionState``/``PendingCommandState``: it only needs to remember which
event IDs have already been notified about, so a periodic scheduler job
doesn't re-send the same brief every time it polls.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from integrations.google_calendar import CalendarClient, CalendarEvent

from services.search_service import SearchService

DEFAULT_LEAD_TIME = timedelta(minutes=30)
DEFAULT_POLL_WINDOW = timedelta(minutes=5)


class MeetingBriefState:
    def __init__(self) -> None:
        self._notified: set[str] = set()

    def already_notified(self, event_id: str) -> bool:
        return event_id in self._notified

    def mark_notified(self, event_id: str) -> None:
        self._notified.add(event_id)


class MeetingBriefService:
    def __init__(
        self,
        calendar: CalendarClient,
        search: SearchService,
        state: MeetingBriefState,
        lead_time: timedelta = DEFAULT_LEAD_TIME,
        poll_window: timedelta = DEFAULT_POLL_WINDOW,
    ) -> None:
        self._calendar = calendar
        self._search = search
        self._state = state
        self._lead_time = lead_time
        self._poll_window = poll_window

    async def due_briefs(self, now: datetime) -> list[tuple[CalendarEvent, str]]:
        """Return (event, brief text) for events starting within the lead-time
        window around *now* that haven't been briefed yet, marking each as
        notified so a later call (e.g. the next scheduler tick) won't repeat it.
        """
        window_start = now + self._lead_time - self._poll_window
        window_end = now + self._lead_time + self._poll_window

        events = await self._calendar.list_events(window_start, window_end)

        due: list[tuple[CalendarEvent, str]] = []
        for event in events:
            if self._state.already_notified(event.id):
                continue
            if not (window_start <= event.start <= window_end):
                continue  # overlapping event that doesn't *start* in the window

            brief = await self._build_brief(event)
            self._state.mark_notified(event.id)
            due.append((event, brief))
        return due

    async def _build_brief(self, event: CalendarEvent) -> str:
        notes = await self._search.search(event.summary)

        lines = [f"📋 Скоро встреча: {event.summary}", f"Начало: {event.start.strftime('%H:%M')}"]
        if event.location:
            lines.append(f"Место: {event.location}")
        if event.attendees:
            lines.append(f"Участники: {', '.join(event.attendees)}")
        lines.append("")
        lines.append(notes)
        return "\n".join(lines)
