"""Async-safe read/write access to the Obsidian tasks file.

All blocking file I/O lives here, behind a single asyncio.Lock so concurrent
Telegram updates can never interleave writes to the same file, and behind
``asyncio.to_thread`` so a slow disk never stalls the bot's event loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TASK_PREFIX = "- [ ] "
DONE_PREFIX = "- [x] "
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
SECTION_HEADER_PREFIX = "## "


def _insert_into_section(lines: list[str], section: str, new_line: str) -> list[str]:
    """Return *lines* with *new_line* inserted into the ``## {section}`` block.

    If the section header does not exist yet, it is created at the end of the
    file. This keeps existing (header-less) vaults working unchanged: callers
    that never pass a section never trigger this at all.
    """
    header = f"{SECTION_HEADER_PREFIX}{section}"
    header_idx = next((i for i, line in enumerate(lines) if line.strip() == header), None)

    if header_idx is None:
        result = list(lines)
        if result and result[-1].strip():
            result.append("")
        result.append(header)
        result.append(new_line)
        return result

    # Find the end of this section's block: the next header, or EOF.
    end_idx = len(lines)
    for i in range(header_idx + 1, len(lines)):
        if lines[i].startswith(SECTION_HEADER_PREFIX):
            end_idx = i
            break

    # Insert before any trailing blank lines so the new task sits with its
    # siblings instead of after a blank gap.
    insert_at = end_idx
    while insert_at > header_idx + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    result = list(lines)
    result.insert(insert_at, new_line)
    return result


class TaskStore:
    """Thread/async-safe wrapper around a single markdown tasks file."""

    def __init__(self, path: Path, now: Callable[[], datetime] = datetime.now) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        # Injectable clock so tests can freeze time instead of asserting on
        # whatever datetime.now() happens to return.
        self._now = now

    async def add_task(self, text: str, section: str | None = None) -> None:
        """Append a new open task, timestamped.

        If *section* is given, the task is filed under a ``## {section}``
        markdown header (created if missing) instead of being appended
        flat at the end of the file.
        """
        async with self._lock:
            await asyncio.to_thread(self._add_task_sync, text, section)

    async def list_open_tasks(self, limit: int | None = None) -> list[str]:
        """Return open tasks, most-recent-last.

        *limit* caps the number of tasks returned (most recent *limit*).
        ``None`` (the default) returns every open task in the file.
        """
        async with self._lock:
            return await asyncio.to_thread(self._list_open_tasks_sync, limit)

    async def mark_done(self, index: int) -> bool:
        """Mark the *index*-th (1-based, as shown by /list) open task as done.

        Returns True on success, False if the index is out of range.
        """
        async with self._lock:
            return await asyncio.to_thread(self._mark_done_sync, index)

    # ── sync helpers (always called via asyncio.to_thread) ──────────────────

    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
            logger.info("Created tasks file: %s", self.path)

    def _add_task_sync(self, text: str, section: str | None) -> None:
        self._ensure_file()
        timestamp = self._now().strftime(TIMESTAMP_FORMAT)
        line = f"{TASK_PREFIX}{timestamp} {text}"

        if section is None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(f"{line}\n")
            return

        lines = self._read_lines()
        new_lines = _insert_into_section(lines, section, line)
        self.path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def _read_lines(self) -> list[str]:
        self._ensure_file()
        return self.path.read_text(encoding="utf-8").splitlines()

    def _list_open_tasks_sync(self, limit: int | None) -> list[str]:
        lines = self._read_lines()
        open_tasks = [
            line[len(TASK_PREFIX):].strip()
            for line in lines
            if line.startswith(TASK_PREFIX)
        ]
        if limit is None:
            return open_tasks
        return open_tasks[-limit:]

    def _mark_done_sync(self, index: int) -> bool:
        lines = self._read_lines()
        open_positions = [i for i, line in enumerate(lines) if line.startswith(TASK_PREFIX)]
        if index < 1 or index > len(open_positions):
            return False

        line_no = open_positions[index - 1]
        task_text = lines[line_no][len(TASK_PREFIX):]
        lines[line_no] = f"{DONE_PREFIX}{task_text}"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
