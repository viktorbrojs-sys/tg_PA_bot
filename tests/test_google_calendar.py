from datetime import UTC, datetime

import httpx
import pytest
from integrations.google_calendar import (
    GoogleCalendarClient,
    NullCalendarClient,
    _parse_datetime,
    _parse_event,
)

START = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
END = datetime(2026, 9, 16, 0, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_null_calendar_client_always_returns_no_events():
    client = NullCalendarClient()
    events = await client.list_events(START, END)
    assert events == []


def test_parse_datetime_handles_timed_event():
    dt = _parse_datetime("2026-09-15T14:30:00+03:00")
    assert dt.hour == 14
    assert dt.minute == 30


def test_parse_datetime_handles_all_day_event():
    dt = _parse_datetime("2026-09-15")
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 15


def test_parse_datetime_handles_utc_z_suffix():
    dt = _parse_datetime("2026-09-15T11:00:00Z")
    assert dt.tzinfo is not None


def test_parse_event_extracts_fields():
    item = {
        "id": "abc123",
        "summary": "Созвон с Ивановым",
        "start": {"dateTime": "2026-09-15T14:00:00+03:00"},
        "end": {"dateTime": "2026-09-15T15:00:00+03:00"},
        "location": "Zoom",
        "attendees": [{"email": "ivanov@example.com"}, {"displayName": "no email"}],
    }
    event = _parse_event(item)
    assert event is not None
    assert event.id == "abc123"
    assert event.summary == "Созвон с Ивановым"
    assert event.location == "Zoom"
    assert event.attendees == ("ivanov@example.com",)
    # No displayName for ivanov@example.com -> falls back to the email itself.
    assert event.attendee_names == ("ivanov@example.com",)


def test_parse_event_uses_display_name_when_present():
    item = {
        "id": "abc123",
        "summary": "Созвон",
        "start": {"dateTime": "2026-09-15T14:00:00+03:00"},
        "end": {"dateTime": "2026-09-15T15:00:00+03:00"},
        "attendees": [{"email": "ivanov@example.com", "displayName": "Иван Иванов"}],
    }
    event = _parse_event(item)
    assert event is not None
    assert event.attendees == ("ivanov@example.com",)
    assert event.attendee_names == ("Иван Иванов",)


def test_parse_event_defaults_missing_summary():
    item = {
        "id": "x",
        "start": {"date": "2026-09-15"},
        "end": {"date": "2026-09-16"},
    }
    event = _parse_event(item)
    assert event is not None
    assert event.summary == "(без названия)"


def test_parse_event_returns_none_for_missing_dates():
    assert _parse_event({"id": "x", "start": {}, "end": {}}) is None


def _mock_token_and_events(monkeypatch, events_payload: dict) -> None:
    async def fake_post(self, url, headers=None, data=None, json=None):  # noqa: ARG001
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"access_token": "fake-token"}, request=request)

    async def fake_get(self, url, params=None, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=events_payload, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


@pytest.mark.asyncio
async def test_google_calendar_client_lists_events(monkeypatch):
    _mock_token_and_events(
        monkeypatch,
        {
            "items": [
                {
                    "id": "1",
                    "summary": "Встреча",
                    "start": {"dateTime": "2026-09-15T10:00:00+03:00"},
                    "end": {"dateTime": "2026-09-15T11:00:00+03:00"},
                }
            ]
        },
    )
    client = GoogleCalendarClient("id", "secret", "refresh")

    events = await client.list_events(START, END)
    assert len(events) == 1
    assert events[0].summary == "Встреча"


@pytest.mark.asyncio
async def test_google_calendar_client_returns_empty_on_token_failure(monkeypatch):
    async def fake_post(self, url, headers=None, data=None, json=None):  # noqa: ARG001
        raise httpx.ConnectError("boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = GoogleCalendarClient("id", "secret", "refresh")

    events = await client.list_events(START, END)
    assert events == []


@pytest.mark.asyncio
async def test_google_calendar_client_returns_empty_on_events_fetch_failure(monkeypatch):
    async def fake_post(self, url, headers=None, data=None, json=None):  # noqa: ARG001
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"access_token": "fake-token"}, request=request)

    async def fake_get(self, url, params=None, headers=None):  # noqa: ARG001
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleCalendarClient("id", "secret", "refresh")

    events = await client.list_events(START, END)
    assert events == []
