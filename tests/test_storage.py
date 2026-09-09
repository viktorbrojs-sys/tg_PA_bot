import asyncio
from datetime import datetime

import pytest
from storage import TaskStore

FIXED_NOW = datetime(2026, 9, 7, 14, 32)


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.md", now=lambda: FIXED_NOW)


@pytest.mark.asyncio
async def test_add_task_creates_file_and_appends_with_timestamp(store):
    await store.add_task("Buy milk")
    await store.add_task("Walk the dog")

    content = store.path.read_text(encoding="utf-8")
    assert content == (
        "- [ ] 2026-09-07 14:32 Buy milk\n"
        "- [ ] 2026-09-07 14:32 Walk the dog\n"
    )


@pytest.mark.asyncio
async def test_list_open_tasks_ignores_done_and_respects_limit(store):
    for i in range(3):
        await store.add_task(f"task {i}")
    # Manually mark one done and add a non-task line, mimicking a real vault file.
    store.path.write_text(
        "- [x] task 0\n# Notes\n- [ ] task 1\n- [ ] task 2\n", encoding="utf-8"
    )

    tasks = await store.list_open_tasks(limit=1)
    assert tasks == ["task 2"]

    tasks = await store.list_open_tasks(limit=20)
    assert tasks == ["task 1", "task 2"]


@pytest.mark.asyncio
async def test_mark_done_updates_correct_line(store):
    await store.add_task("first")
    await store.add_task("second")

    ok = await store.mark_done(2)
    assert ok is True

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "- [ ] 2026-09-07 14:32 first",
        "- [x] 2026-09-07 14:32 second ✅ 2026-09-07 14:32",
    ]


@pytest.mark.asyncio
async def test_mark_done_out_of_range_returns_false(store):
    await store.add_task("only one")
    assert await store.mark_done(0) is False
    assert await store.mark_done(2) is False


@pytest.mark.asyncio
async def test_concurrent_writes_do_not_corrupt_file(store):
    await asyncio.gather(*(store.add_task(f"task {i}") for i in range(50)))

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    assert all(line.startswith("- [ ] 2026-09-07 14:32 task ") for line in lines)


@pytest.mark.asyncio
async def test_list_open_tasks_no_limit_returns_everything(store):
    for i in range(25):
        await store.add_task(f"task {i}")

    tasks = await store.list_open_tasks()  # no limit -> full list
    assert len(tasks) == 25
    assert tasks[0] == "2026-09-07 14:32 task 0"
    assert tasks[-1] == "2026-09-07 14:32 task 24"


@pytest.mark.asyncio
async def test_add_task_with_section_creates_header(store):
    await store.add_task("Buy milk", section="Личное")

    content = store.path.read_text(encoding="utf-8")
    assert content == (
        "## Личное\n"
        "- [ ] 2026-09-07 14:32 Buy milk\n"
    )


@pytest.mark.asyncio
async def test_add_task_with_section_appends_to_existing_header(store):
    await store.add_task("first", section="Работа")
    await store.add_task("second", section="Работа")

    content = store.path.read_text(encoding="utf-8")
    assert content == (
        "## Работа\n"
        "- [ ] 2026-09-07 14:32 first\n"
        "- [ ] 2026-09-07 14:32 second\n"
    )


@pytest.mark.asyncio
async def test_add_task_with_different_sections_creates_separate_blocks(store):
    await store.add_task("work task", section="Работа")
    await store.add_task("personal task", section="Личное")
    await store.add_task("another work task", section="Работа")

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "## Работа",
        "- [ ] 2026-09-07 14:32 work task",
        "- [ ] 2026-09-07 14:32 another work task",
        "",
        "## Личное",
        "- [ ] 2026-09-07 14:32 personal task",
    ]


@pytest.mark.asyncio
async def test_add_task_with_section_leaves_headerless_content_untouched(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("- [ ] 2026-09-01 10:00 legacy task\n", encoding="utf-8")

    await store.add_task("new task", section="Работа")

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        "- [ ] 2026-09-01 10:00 legacy task",
        "",
        "## Работа",
        "- [ ] 2026-09-07 14:32 new task",
    ]


@pytest.mark.asyncio
async def test_read_all_lines_returns_raw_content_including_non_task_lines(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    content = "## Работа\n- [ ] 2026-09-01 10:00 task\nfree text note\n"
    store.path.write_text(content, encoding="utf-8")

    lines = await store.read_all_lines()
    assert lines == ["## Работа", "- [ ] 2026-09-01 10:00 task", "free text note"]


@pytest.mark.asyncio
async def test_list_completed_since_returns_only_tasks_completed_after_cutoff(store):
    await store.add_task("old one")
    await store.add_task("recent one")
    await store.mark_done(1)  # completed at FIXED_NOW (2026-09-07 14:32)
    await store.mark_done(1)  # remaining open task ("recent one") completed too

    since_after_completion = datetime(2026, 9, 7, 15, 0)
    assert await store.list_completed_since(since_after_completion) == []

    since_before_completion = datetime(2026, 9, 7, 14, 0)
    completed = await store.list_completed_since(since_before_completion)
    assert len(completed) == 2
    assert all("✅ 2026-09-07 14:32" in line for line in completed)


@pytest.mark.asyncio
async def test_list_completed_since_ignores_legacy_done_tasks_without_timestamp(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("- [x] 2026-09-01 10:00 legacy done task\n", encoding="utf-8")

    completed = await store.list_completed_since(datetime(2020, 1, 1))
    assert completed == []
