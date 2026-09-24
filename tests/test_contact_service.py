from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from integrations.gmail_client import MailMessage
from integrations.google_calendar import CalendarEvent, NullCalendarClient
from mail_index import MailIndex
from services.contact_service import ContactService

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeCalendarClient:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self._events = events
        self.calls: list[tuple[datetime, datetime]] = []

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        self.calls.append((start, end))
        return [e for e in self._events if start <= e.start <= end]


def _event(
    event_id: str,
    summary: str,
    start: datetime,
    attendees: tuple[str, ...] = (),
    attendee_names: tuple[str, ...] = (),
) -> CalendarEvent:
    return CalendarEvent(
        id=event_id,
        summary=summary,
        start=start,
        end=start + timedelta(hours=1),
        attendees=attendees,
        attendee_names=attendee_names or attendees,
    )


@pytest.mark.asyncio
async def test_find_reports_nothing_when_both_sources_empty(tmp_path):
    service = ContactService(NullCalendarClient(), vault_path=tmp_path, now=lambda: NOW)
    result = await service.find("Иванов")
    assert "Ничего не нашёл" in result


@pytest.mark.asyncio
async def test_find_reports_nothing_without_vault_or_calendar():
    service = ContactService(NullCalendarClient(), vault_path=None, now=lambda: NOW)
    result = await service.find("Иванов")
    assert "Ничего не нашёл" in result


@pytest.mark.asyncio
async def test_find_note_mentions(tmp_path):
    _write(
        tmp_path / "note.md",
        "## Встреча\nОбсудили проект с Ивановым, договорились созвониться.\n",
    )

    service = ContactService(NullCalendarClient(), vault_path=tmp_path, now=lambda: NOW)
    result = await service.find("Иванов")

    assert "Упоминания в заметках" in result
    assert "note.md" in result
    assert "Ивановым" in result
    assert "Прошлые встречи" not in result


@pytest.mark.asyncio
async def test_find_note_mentions_is_case_insensitive(tmp_path):
    _write(tmp_path / "note.md", "## X\nразговор с ивановым\n")

    service = ContactService(NullCalendarClient(), vault_path=tmp_path, now=lambda: NOW)
    result = await service.find("Иванов")

    assert "ивановым" in result


@pytest.mark.asyncio
async def test_find_past_meetings_by_attendee_name(tmp_path):
    events = [
        _event(
            "1", "Созвон", NOW - timedelta(days=5), attendee_names=("Иван Иванов",)
        ),
        _event("2", "Другая встреча", NOW - timedelta(days=3), attendee_names=("Пётр Петров",)),
    ]
    service = ContactService(FakeCalendarClient(events), vault_path=tmp_path, now=lambda: NOW)

    result = await service.find("Иванов")

    assert "Прошлые встречи" in result
    assert "Созвон" in result
    assert "Другая встреча" not in result
    assert "Упоминания в заметках" not in result


@pytest.mark.asyncio
async def test_find_past_meetings_by_attendee_email_when_no_display_name(tmp_path):
    events = [
        _event("1", "Созвон", NOW - timedelta(days=5), attendees=("ivanov@example.com",))
    ]
    service = ContactService(FakeCalendarClient(events), vault_path=tmp_path, now=lambda: NOW)

    result = await service.find("ivanov")

    assert "Созвон" in result


@pytest.mark.asyncio
async def test_find_combines_both_sources(tmp_path):
    _write(tmp_path / "note.md", "## X\nЗаметка про Иванова\n")
    events = [_event("1", "Созвон", NOW - timedelta(days=5), attendee_names=("Иванов",))]
    service = ContactService(FakeCalendarClient(events), vault_path=tmp_path, now=lambda: NOW)

    result = await service.find("Иванов")

    assert "Упоминания в заметках" in result
    assert "Прошлые встречи" in result


@pytest.mark.asyncio
async def test_find_past_meetings_sorted_most_recent_first(tmp_path):
    events = [
        _event("1", "Старая встреча", NOW - timedelta(days=30), attendee_names=("Иванов",)),
        _event("2", "Новая встреча", NOW - timedelta(days=1), attendee_names=("Иванов",)),
    ]
    service = ContactService(FakeCalendarClient(events), vault_path=tmp_path, now=lambda: NOW)

    result = await service.find("Иванов")

    assert result.index("Новая встреча") < result.index("Старая встреча")


@pytest.mark.asyncio
async def test_find_past_meetings_limited_to_max(tmp_path):
    events = [
        _event(str(i), f"Встреча {i}", NOW - timedelta(days=i), attendee_names=("Иванов",))
        for i in range(1, 10)
    ]
    service = ContactService(FakeCalendarClient(events), vault_path=tmp_path, now=lambda: NOW)

    result = await service.find("Иванов")

    assert result.count("Встреча") == 5


@pytest.mark.asyncio
async def test_find_note_mentions_limited_to_max(tmp_path):
    for i in range(10):
        _write(tmp_path / f"note{i}.md", f"## X\nПро Иванова номер {i}\n")

    service = ContactService(NullCalendarClient(), vault_path=tmp_path, now=lambda: NOW)
    result = await service.find("Иванов")

    assert result.count("note") == 5


@pytest.mark.asyncio
async def test_find_uses_lookback_window(tmp_path):
    calendar = FakeCalendarClient([])
    service = ContactService(
        calendar, vault_path=tmp_path, lookback=timedelta(days=30), now=lambda: NOW
    )

    await service.find("Иванов")

    (start, end) = calendar.calls[0]
    assert end == NOW
    assert start == NOW - timedelta(days=30)


@pytest.mark.asyncio
async def test_long_note_mention_is_truncated(tmp_path):
    long_text = "Иванов " + ("текст " * 100)
    _write(tmp_path / "note.md", f"## X\n{long_text}\n")

    service = ContactService(NullCalendarClient(), vault_path=tmp_path, now=lambda: NOW)
    result = await service.find("Иванов")

    assert "…" in result


def _mail(
    message_id: str,
    *,
    sender_name: str = "Иванов",
    subject: str = "Тема",
    body: str = "текст письма",
    date: datetime = NOW - timedelta(days=5),
) -> MailMessage:
    return MailMessage(
        id=message_id,
        thread_id=f"t-{message_id}",
        sender=f"{sender_name} <x@example.com>",
        sender_name=sender_name,
        sender_email="x@example.com",
        subject=subject,
        date=date,
        snippet="",
        body=body,
        labels=("INBOX",),
    )


@pytest.mark.asyncio
async def test_find_reports_nothing_across_all_three_sources(tmp_path):
    mail_index = MailIndex(tmp_path / "mail.db", embedding_dim=3)
    service = ContactService(
        NullCalendarClient(), vault_path=tmp_path, mail_index=mail_index, now=lambda: NOW
    )
    result = await service.find("Иванов")
    assert "Ничего не нашёл" in result


@pytest.mark.asyncio
async def test_find_mail_mentions(tmp_path):
    mail_index = MailIndex(tmp_path / "mail.db", embedding_dim=3)
    await mail_index.upsert([_mail("m1")], [[1.0, 0.0, 0.0]])

    service = ContactService(
        NullCalendarClient(), vault_path=tmp_path, mail_index=mail_index, now=lambda: NOW
    )
    result = await service.find("Иванов")

    assert "Письма" in result
    assert "Тема" in result
    assert "Упоминания в заметках" not in result
    assert "Прошлые встречи" not in result


@pytest.mark.asyncio
async def test_find_without_mail_index_skips_mail_section(tmp_path):
    _write(tmp_path / "note.md", "## X\nПро Иванова\n")

    service = ContactService(NullCalendarClient(), vault_path=tmp_path, now=lambda: NOW)
    result = await service.find("Иванов")

    assert "Письма" not in result
    assert "Упоминания в заметках" in result


@pytest.mark.asyncio
async def test_find_combines_all_three_sources(tmp_path):
    _write(tmp_path / "note.md", "## X\nЗаметка про Иванова\n")
    mail_index = MailIndex(tmp_path / "mail.db", embedding_dim=3)
    await mail_index.upsert([_mail("m1")], [[1.0, 0.0, 0.0]])
    events = [
        CalendarEvent(
            id="1",
            summary="Созвон",
            start=NOW - timedelta(days=3),
            end=NOW - timedelta(days=3) + timedelta(hours=1),
            attendee_names=("Иванов",),
        )
    ]

    class FakeCalendarClient:
        async def list_events(self, start, end):
            return [e for e in events if start <= e.start <= end]

    service = ContactService(
        FakeCalendarClient(), vault_path=tmp_path, mail_index=mail_index, now=lambda: NOW
    )
    result = await service.find("Иванов")

    assert "Упоминания в заметках" in result
    assert "Письма" in result
    assert "Прошлые встречи" in result
