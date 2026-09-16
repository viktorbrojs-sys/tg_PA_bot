from datetime import UTC, datetime, timedelta

import pytest
from integrations.google_calendar import CalendarClient, CalendarEvent
from services.meeting_brief_service import MeetingBriefService, MeetingBriefState

NOW = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)


class FakeCalendarClient:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self._events = events

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [e for e in self._events if start <= e.start <= end]


class FakeSearchService:
    async def search(self, query: str) -> str:
        return f"заметки по «{query}»"


def _event(event_id: str, minutes_from_now: int, **kwargs) -> CalendarEvent:
    start = NOW + timedelta(minutes=minutes_from_now)
    extra = {k: v for k, v in kwargs.items() if k != "summary"}
    return CalendarEvent(
        id=event_id,
        summary=kwargs.get("summary", "Встреча"),
        start=start,
        end=start + timedelta(hours=1),
        **extra,
    )


def test_meeting_brief_state_lifecycle():
    state = MeetingBriefState()
    assert not state.already_notified("e1")
    state.mark_notified("e1")
    assert state.already_notified("e1")
    assert not state.already_notified("e2")


@pytest.mark.asyncio
async def test_due_briefs_returns_event_starting_within_lead_window():
    calendar: CalendarClient = FakeCalendarClient([_event("1", minutes_from_now=30)])
    service = MeetingBriefService(calendar, FakeSearchService(), MeetingBriefState())

    due = await service.due_briefs(NOW)
    assert len(due) == 1
    event, brief = due[0]
    assert event.id == "1"
    assert "Встреча" in brief
    assert "заметки по «Встреча»" in brief


@pytest.mark.asyncio
async def test_due_briefs_ignores_events_outside_window():
    calendar: CalendarClient = FakeCalendarClient([_event("1", minutes_from_now=120)])
    service = MeetingBriefService(calendar, FakeSearchService(), MeetingBriefState())

    due = await service.due_briefs(NOW)
    assert due == []


@pytest.mark.asyncio
async def test_due_briefs_does_not_repeat_already_notified_event():
    calendar: CalendarClient = FakeCalendarClient([_event("1", minutes_from_now=30)])
    state = MeetingBriefState()
    service = MeetingBriefService(calendar, FakeSearchService(), state)

    first = await service.due_briefs(NOW)
    assert len(first) == 1

    second = await service.due_briefs(NOW)
    assert second == []


@pytest.mark.asyncio
async def test_brief_includes_location_and_attendees():
    calendar: CalendarClient = FakeCalendarClient(
        [_event("1", minutes_from_now=30, location="Zoom", attendees=("a@example.com",))]
    )
    service = MeetingBriefService(calendar, FakeSearchService(), MeetingBriefState())

    (_event_obj, brief) = (await service.due_briefs(NOW))[0]
    assert "Zoom" in brief
    assert "a@example.com" in brief
