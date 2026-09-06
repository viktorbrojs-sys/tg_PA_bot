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
        "- [x] 2026-09-07 14:32 second",
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
