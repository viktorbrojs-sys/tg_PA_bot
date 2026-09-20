"""Read-only Google Calendar access.

Same pattern as ``llm_client.py``: an abstraction (``CalendarClient``) with a
no-op fallback (``NullCalendarClient``) so the bot works fine without
Google Calendar configured — digests just won't mention events, and the
meeting-prep job simply never fires.

Auth uses a long-lived refresh token obtained once via
``scripts/google_calendar_auth.py`` (device flow) — the bot itself never
needs interactive browser auth, only a refresh token minted ahead of time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL_TEMPLATE = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    summary: str
    start: datetime
    end: datetime
    attendees: tuple[str, ...] = ()  # emails
    attendee_names: tuple[str, ...] = ()  # display names, same order as attendees
    # (falls back to the email itself when Google has no display name for
    # that attendee) — kept separate from `attendees` rather than replacing
    # it, so existing "join emails" callers don't need to change.
    location: str | None = None


class CalendarClient(Protocol):
    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Return events starting or ending within [start, end), by start time."""
        ...


class NullCalendarClient:
    """Fallback used when Google Calendar isn't configured — never any events."""

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return []


class GoogleCalendarClient:
    """Read-only client for one Google Calendar via the REST API (no SDK)."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        calendar_id: str = "primary",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._calendar_id = calendar_id

    async def _get_access_token(self) -> str | None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": self._refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                resp.raise_for_status()
                token = resp.json()["access_token"]
            except (httpx.HTTPError, KeyError, TypeError) as exc:
                logger.warning("Google Calendar token refresh failed: %s", exc)
                return None
            return str(token)

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        token = await self._get_access_token()
        if token is None:
            return []

        url = EVENTS_URL_TEMPLATE.format(calendar_id=self._calendar_id)
        params = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    url, params=params, headers={"Authorization": f"Bearer {token}"}
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, KeyError, TypeError) as exc:
                logger.warning("Google Calendar events fetch failed: %s", exc)
                return []

        events: list[CalendarEvent] = []
        for item in data.get("items", []):
            event = _parse_event(item)
            if event is not None:
                events.append(event)
        return events


def _parse_event(item: dict[str, Any]) -> CalendarEvent | None:
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})
    start_str = start_raw.get("dateTime") or start_raw.get("date")
    end_str = end_raw.get("dateTime") or end_raw.get("date")
    if not start_str or not end_str:
        return None

    try:
        start = _parse_datetime(start_str)
        end = _parse_datetime(end_str)
    except ValueError:
        logger.warning("Skipping calendar event with unparseable dates: %r", item.get("id"))
        return None

    attendees = tuple(a["email"] for a in item.get("attendees", []) if a.get("email"))
    attendee_names = tuple(
        a.get("displayName") or a["email"] for a in item.get("attendees", []) if a.get("email")
    )
    return CalendarEvent(
        id=str(item.get("id", "")),
        summary=str(item.get("summary") or "(без названия)"),
        start=start,
        end=end,
        attendees=attendees,
        attendee_names=attendee_names,
        location=item.get("location"),
    )


def _parse_datetime(value: str) -> datetime:
    # All-day events come as a bare date ("2026-09-15"); timed events as a
    # full RFC3339 datetime with an offset.
    if len(value) == 10:
        return datetime.fromisoformat(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
