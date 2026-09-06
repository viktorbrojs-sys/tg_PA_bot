import asyncio

import pytest
from storage import TaskStore


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.md")


@pytest.mark.asyncio
async def test_add_task_creates_file_and_appends(store):
    await store.add_task("Buy milk")
    await store.add_task("Walk the dog")

    content = store.path.read_text(encoding="utf-8")
    assert content == "- [ ] Buy milk\n- [ ] Walk the dog\n"


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
    assert lines == ["- [ ] first", "- [x] second"]


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
    assert all(line.startswith("- [ ] task ") for line in lines)
