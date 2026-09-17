from datetime import UTC, datetime, timedelta

import pytest
from integrations.google_calendar import CalendarClient, CalendarEvent
from integrations.llm_client import NullLLMClient
from integrations.weather_client import DailyWeather
from services.digest_service import DigestService, _pick_main_task
from services.task_service import TaskService
from storage import TaskStore

FIXED_NOW = datetime(2026, 9, 9, 10, 0)


@pytest.fixture
def task_service(tmp_path):
    store = TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW)
    return TaskService(store, NullLLMClient(), sections=("Работа", "Личное"))


@pytest.fixture
def digest(task_service):
    return DigestService(task_service, now=lambda: FIXED_NOW)


@pytest.mark.asyncio
async def test_morning_digest_with_no_tasks(digest):
    text = await digest.build_morning_digest()
    assert "нет" in text.lower()


@pytest.mark.asyncio
async def test_morning_digest_lists_open_count_and_main_task(task_service, digest):
    await task_service.add_task("Закончить презентацию")
    await task_service.add_task("Купить молоко")

    text = await digest.build_morning_digest()
    assert "Открытых задач: 2" in text
    assert "Закончить презентацию" in text  # first task = "main task of the day"


@pytest.mark.asyncio
async def test_morning_digest_prefers_higher_priority_task_as_main(task_service, digest):
    await task_service.add_task("Купить молоко")  # added first, no priority
    await task_service.add_task("Закончить отчёт")
    await task_service.set_priority(2, "критический")  # second task, but most urgent

    text = await digest.build_morning_digest()
    assert (
        "Главная задача дня: 2026-09-09 10:00 Закончить отчёт "
        "[category:: Входящие] [priority:: 1]" in text
    )


@pytest.mark.asyncio
async def test_morning_digest_flags_overdue_tasks(task_service, digest):
    await task_service.add_task("Сдать отчёт [due:: 2026-09-08]")  # yesterday relative to FIXED_NOW
    await task_service.add_task("Задача без дедлайна")

    text = await digest.build_morning_digest()
    assert "Просрочено" in text
    assert "Сдать отчёт" in text


@pytest.mark.asyncio
async def test_morning_digest_ignores_future_deadlines(task_service, digest):
    await task_service.add_task("Задача на будущее [due:: 2026-12-31]")

    text = await digest.build_morning_digest()
    assert "Просрочено" not in text


@pytest.mark.asyncio
async def test_evening_prompt_with_no_tasks(digest):
    text = await digest.build_evening_prompt()
    assert "не было" in text.lower()


@pytest.mark.asyncio
async def test_evening_prompt_lists_open_tasks(task_service, digest):
    await task_service.add_task("Закончить презентацию")
    await task_service.add_task("Купить молоко")

    text = await digest.build_evening_prompt()
    assert "1. " in text and "Закончить презентацию" in text
    assert "2. " in text and "Купить молоко" in text


@pytest.mark.asyncio
async def test_weekly_review_with_no_completed_tasks(digest):
    text = await digest.build_weekly_review()
    assert "нет задач" in text.lower()


@pytest.mark.asyncio
async def test_weekly_review_lists_recently_completed_tasks(task_service, digest):
    await task_service.add_task("Закончить отчёт")
    await task_service.add_task("Купить молоко")
    await task_service.mark_done(1)
    await task_service.mark_done(1)  # marks the remaining open task

    text = await digest.build_weekly_review()
    assert "выполнено задач за 7 дней — 2" in text
    assert "Закончить отчёт" in text
    assert "Купить молоко" in text


@pytest.mark.asyncio
async def test_weekly_review_excludes_tasks_completed_before_the_window(task_service):
    await task_service.add_task("Старая задача")
    await task_service.mark_done(1)  # completed at FIXED_NOW

    # "now" for the digest is 8 days after completion -> outside the 7-day window
    later = datetime(2026, 9, 17, 10, 0)
    digest = DigestService(task_service, now=lambda: later)

    text = await digest.build_weekly_review()
    assert "нет задач" in text.lower()


class FakeCalendarClient:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self._events = events

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [e for e in self._events if start <= e.start < end]


def _event(hour: int, summary: str = "Встреча") -> CalendarEvent:
    start = datetime(2026, 9, 9, hour, 0, tzinfo=UTC)
    return CalendarEvent(id=summary, summary=summary, start=start, end=start + timedelta(hours=1))


@pytest.mark.asyncio
async def test_morning_digest_includes_todays_calendar_events(task_service):
    calendar: CalendarClient = FakeCalendarClient([_event(14, "Созвон с командой")])
    digest = DigestService(task_service, calendar=calendar, now=lambda: FIXED_NOW, timezone="UTC")

    text = await digest.build_morning_digest()
    assert "Встречи сегодня (1)" in text
    assert "14:00" in text
    assert "Созвон с командой" in text


@pytest.mark.asyncio
async def test_morning_digest_without_calendar_configured_has_no_events_section(digest):
    text = await digest.build_morning_digest()
    assert "Встречи сегодня" not in text


@pytest.mark.asyncio
async def test_morning_digest_shows_events_even_with_no_open_tasks(tmp_path):
    empty_task_service = TaskService(
        TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW),
        NullLLMClient(),
        sections=("Работа",),
    )
    calendar: CalendarClient = FakeCalendarClient([_event(9, "Утренняя встреча")])
    digest = DigestService(
        empty_task_service, calendar=calendar, now=lambda: FIXED_NOW, timezone="UTC"
    )

    text = await digest.build_morning_digest()
    assert "Открытых задач нет" in text
    assert "Утренняя встреча" in text


class FakeWeatherClient:
    def __init__(self, weather: DailyWeather | None) -> None:
        self._weather = weather

    async def today(self) -> DailyWeather | None:
        return self._weather


@pytest.mark.asyncio
async def test_morning_digest_includes_weather_line(task_service):
    weather = DailyWeather(
        date=FIXED_NOW.date(),
        temp_min=12.0,
        temp_max=20.0,
        precipitation_probability=10,
        weather_code=0,
    )
    digest = DigestService(task_service, weather=FakeWeatherClient(weather), now=lambda: FIXED_NOW)

    text = await digest.build_morning_digest()
    assert "Погода: ясно" in text
    assert "12" in text and "20" in text
    assert "зонт" not in text  # low precipitation probability


@pytest.mark.asyncio
async def test_morning_digest_suggests_umbrella_on_high_precipitation(task_service):
    weather = DailyWeather(
        date=FIXED_NOW.date(),
        temp_min=10.0,
        temp_max=15.0,
        precipitation_probability=70,
        weather_code=61,
    )
    digest = DigestService(task_service, weather=FakeWeatherClient(weather), now=lambda: FIXED_NOW)

    text = await digest.build_morning_digest()
    assert "зонт" in text


@pytest.mark.asyncio
async def test_morning_digest_without_weather_configured_has_no_weather_line(digest):
    text = await digest.build_morning_digest()
    assert "Погода" not in text


@pytest.mark.asyncio
async def test_morning_digest_shows_weather_even_with_no_open_tasks(tmp_path):
    empty_task_service = TaskService(
        TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW),
        NullLLMClient(),
        sections=("Работа",),
    )
    weather = DailyWeather(
        date=FIXED_NOW.date(),
        temp_min=5.0,
        temp_max=8.0,
        precipitation_probability=5,
        weather_code=3,
    )
    digest = DigestService(
        empty_task_service, weather=FakeWeatherClient(weather), now=lambda: FIXED_NOW
    )

    text = await digest.build_morning_digest()
    assert "Открытых задач нет" in text
    assert "Погода" in text


def test_pick_main_task_defaults_to_first_when_none_tagged():
    tasks = ["первая", "вторая", "третья"]
    assert _pick_main_task(tasks) == "первая"


def test_pick_main_task_prefers_most_urgent_tag():
    tasks = [
        "обычная [priority:: 4]",
        "срочная [priority:: 1]",
        "средняя [priority:: 3]",
    ]
    assert _pick_main_task(tasks) == "срочная [priority:: 1]"


def test_pick_main_task_ranks_fyi_last_despite_being_index_zero():
    tasks = ["информационная [priority:: 0]", "обычная без тега"]
    assert _pick_main_task(tasks) == "обычная без тега"


def test_pick_main_task_ties_broken_by_original_order():
    tasks = ["первая [priority:: 2]", "вторая [priority:: 2]"]
    assert _pick_main_task(tasks) == "первая [priority:: 2]"
