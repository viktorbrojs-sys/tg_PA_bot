"""Cross-references a person's name across the vault and Google Calendar.

Combines two independent, already-existing sources:

- A plain substring search over the whole vault's chunks (``vault_scanner``
  — deliberately NOT the embeddings pipeline: a name lookup is a literal
  string match, not a semantic "what does the vault know about X" question,
  and this way it still works even when Ollama is down or not configured).
- Google Calendar's ``list_events``, matched against each event's attendee
  names/emails (``CalendarEvent.attendee_names``/``attendees``).

Both sources degrade independently, same as everywhere else in this
project: no vault configured -> note-mentions section is just empty; no
calendar configured (``NullCalendarClient``) -> meetings section is just
empty. Never an error either way — worst case, "nothing found".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from integrations.google_calendar import CalendarClient, CalendarEvent
from vault_scanner import chunk_vault

DEFAULT_LOOKBACK = timedelta(days=90)
MAX_NOTE_MENTIONS = 5
MAX_PAST_MEETINGS = 5
_SNIPPET_LIMIT = 220


@dataclass(frozen=True)
class NoteMention:
    file_path: Path
    heading: str | None
    text: str


class ContactService:
    def __init__(
        self,
        calendar: CalendarClient,
        vault_path: Path | None,
        lookback: timedelta = DEFAULT_LOOKBACK,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._calendar = calendar
        self._vault_path = vault_path
        self._lookback = lookback
        self._now = now

    async def find(self, name: str) -> str:
        mentions = self._find_note_mentions(name)
        meetings = await self._find_past_meetings(name)

        if not mentions and not meetings:
            return f"🔍 Ничего не нашёл про «{name}» — ни в заметках, ни во встречах."

        lines = [f"👤 {name}"]

        if mentions:
            lines.append("")
            lines.append("📝 Упоминания в заметках:")
            for mention in mentions:
                heading_part = f" — {mention.heading}" if mention.heading else ""
                snippet = _truncate(mention.text)
                lines.append(f"• {mention.file_path.as_posix()}{heading_part}: {snippet}")

        if meetings:
            lines.append("")
            lines.append("📅 Прошлые встречи:")
            for event in meetings:
                lines.append(f"• {event.start:%Y-%m-%d} — {event.summary}")

        return "\n".join(lines)

    def _find_note_mentions(self, name: str) -> list[NoteMention]:
        """Walks the whole vault fresh on every call — no caching. Fine for
        an infrequent, user-triggered lookup; would need reconsidering if
        this ever became a hot path (e.g. called from every digest).
        """
        if self._vault_path is None:
            return []
        name_lower = name.lower()
        mentions: list[NoteMention] = []
        for chunk in chunk_vault(self._vault_path):
            if name_lower in chunk.text.lower():
                mentions.append(
                    NoteMention(file_path=chunk.file_path, heading=chunk.heading, text=chunk.text)
                )
                if len(mentions) >= MAX_NOTE_MENTIONS:
                    break
        return mentions

    async def _find_past_meetings(self, name: str) -> list[CalendarEvent]:
        now = self._now()
        events = await self._calendar.list_events(now - self._lookback, now)
        name_lower = name.lower()
        matches = [
            event
            for event in events
            if any(name_lower in attendee.lower() for attendee in event.attendee_names)
            or any(name_lower in attendee.lower() for attendee in event.attendees)
        ]
        matches.sort(key=lambda event: event.start, reverse=True)
        return matches[:MAX_PAST_MEETINGS]


def _truncate(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    collapsed = " ".join(text.split())  # one-line snippet, whatever the chunk's own formatting
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
