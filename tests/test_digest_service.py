from datetime import datetime

import pytest
from integrations.llm_client import NullLLMClient
from services.digest_service import DigestService
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
async def test_morning_digest_flags_overdue_tasks(task_service, digest):
    await task_service.add_task("Сдать отчёт @2026-09-08")  # yesterday relative to FIXED_NOW
    await task_service.add_task("Задача без дедлайна")

    text = await digest.build_morning_digest()
    assert "Просрочено" in text
    assert "Сдать отчёт" in text


@pytest.mark.asyncio
async def test_morning_digest_ignores_future_deadlines(task_service, digest):
    await task_service.add_task("Задача на будущее @2026-12-31")

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
