"""Async-safe read/write access to the Obsidian tasks file.

All blocking file I/O lives here, behind a single asyncio.Lock so concurrent
Telegram updates can never interleave writes to the same file, and behind
``asyncio.to_thread`` so a slow disk never stalls the bot's event loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TASK_PREFIX = "- [ ] "
DONE_PREFIX = "- [x] "
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
SECTION_HEADER_PREFIX = "## "
DONE_MARKER = "✅ "
_DONE_TIMESTAMP_PATTERN = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"
_DONE_TIMESTAMP_RE = re.compile(rf"{re.escape(DONE_MARKER)}({_DONE_TIMESTAMP_PATTERN})$")

# Deadline tag, optional per task: Dataview/Tasks-plugin inline field syntax,
# e.g. "[due:: 2026-09-20]" anywhere in the task text. This lets Obsidian's
# Dataview plugin read task.due natively, without a DataviewJS parser.
DEADLINE_TAG_RE = re.compile(r"\[due::\s*(\d{4}-\d{2}-\d{2})\s*\]", re.IGNORECASE)

# Priority tag, optional per task: "[priority:: N]" where N is the 0-5 index
# below (not the word) — Dataview's SORT is a plain string/number sort, and a
# number sorts by actual urgency while a word would sort alphabetically.
# Levels and numbering match the scale from Victor's own office task table
# (0 FYI .. 5 План) rather than an invented scheme, so it's familiar.
PRIORITY_LEVELS: tuple[str, ...] = ("fyi", "критический", "высокий", "средний", "низкий", "план")
PRIORITY_LABELS: dict[str, str] = {
    "fyi": "FYI",
    "критический": "Критический",
    "высокий": "Высокий",
    "средний": "Средний",
    "низкий": "Низкий",
    "план": "План",
}
# Urgency for picking the "main task of the day" — deliberately NOT the same
# order as PRIORITY_LEVELS: "FYI" is index 0 in Victor's numbering but is
# informational only, so it must rank as the LEAST urgent of all, even below
# an untagged task (which has no signal either way, so it sits in the middle).
PRIORITY_URGENCY: dict[str, int] = {
    "критический": 0,
    "высокий": 1,
    "средний": 2,
    "низкий": 3,
    "план": 4,
    "fyi": 6,
}
# Rank used for tasks with no priority tag at all — worse than any explicit
# actionable priority, but still better than an explicit "FYI" tag.
UNTAGGED_PRIORITY_URGENCY = 5
PRIORITY_TAG_RE = re.compile(r"\[priority::\s*([0-5])\s*\]", re.IGNORECASE)

# Category tag, optional per task: "[category:: Раздел]" — written automatically
# from the LLM's classification (mirrors the "## Раздел" section header the
# task also lives under) and overridable via /setcategory. Kept separate from
# the section header so Dataview can read task.category without needing
# task.header, and so a manual override doesn't require moving the line
# between sections.
CATEGORY_TAG_RE = re.compile(r"\[category::\s*([^\]]+?)\s*\]", re.IGNORECASE)


def extract_deadline(text: str) -> date | None:
    match = DEADLINE_TAG_RE.search(text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def extract_priority(text: str) -> str | None:
    match = PRIORITY_TAG_RE.search(text)
    if not match:
        return None
    index = int(match.group(1))
    if 0 <= index < len(PRIORITY_LEVELS):
        return PRIORITY_LEVELS[index]
    return None


def extract_category(text: str) -> str | None:
    match = CATEGORY_TAG_RE.search(text)
    return match.group(1).strip() or None if match else None


def parse_priority_input(raw_value: str) -> str | None:
    """Accept either a level word or its 0-5 index (Victor's own numbering:
    0 FYI, 1 Критический, 2 Высокий, 3 Средний, 4 Низкий, 5 План). Returns
    the canonical lowercase level, or None if unrecognised.
    """
    value = raw_value.strip().lower()
    if value.isdigit():
        index = int(value)
        if 0 <= index < len(PRIORITY_LEVELS):
            return PRIORITY_LEVELS[index]
        return None
    return value if value in PRIORITY_LABELS else None


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
        """Mark the *index*-th (1-based, as shown by /list) open task as done,
        appending a "✅ ГГГГ-ММ-ДД ЧЧ:ММ" completion timestamp.

        Returns True on success, False if the index is out of range.
        """
        async with self._lock:
            return await asyncio.to_thread(self._mark_done_sync, index)

    async def read_all_lines(self) -> list[str]:
        """Return every raw line in the file (tasks, headers, free text) — used for search."""
        async with self._lock:
            return await asyncio.to_thread(self._read_lines)

    async def list_completed_since(self, since: datetime) -> list[str]:
        """Return completed tasks whose completion timestamp is at/after *since*.

        Tasks marked done before this feature existed (no "✅ timestamp"
        suffix) are silently skipped — there's no way to know when they were
        actually completed, so it would be misleading to guess.
        """
        async with self._lock:
            return await asyncio.to_thread(self._list_completed_since_sync, since)

    async def set_deadline(self, index: int, deadline: date | None) -> bool:
        """Set (or, with ``deadline=None``, remove) the ``[due:: ГГГГ-ММ-ДД]``
        tag on the *index*-th open task. Deadlines are per-task and optional —
        most tasks have none, which is expected, not an error state.
        """
        new_tag = f"[due:: {deadline.isoformat()}]" if deadline is not None else None
        async with self._lock:
            return await asyncio.to_thread(self._set_tag_sync, index, DEADLINE_TAG_RE, new_tag)

    async def set_priority(self, index: int, priority: str | None) -> bool:
        """Set (or, with ``priority=None``, remove) the ``[priority:: N]`` tag
        on the *index*-th open task, where N is *priority*'s 0-5 index in
        ``PRIORITY_LEVELS`` (use ``parse_priority_input`` to get a canonical
        level from free-form user input). Stored as a number, not the word,
        so Dataview's SORT sorts by actual urgency rather than alphabetically.
        """
        priority_index = PRIORITY_LEVELS.index(priority) if priority is not None else None
        new_tag = f"[priority:: {priority_index}]" if priority_index is not None else None
        async with self._lock:
            return await asyncio.to_thread(self._set_tag_sync, index, PRIORITY_TAG_RE, new_tag)

    async def set_category(self, index: int, category: str | None) -> bool:
        """Set (or, with ``category=None``, remove) the ``[category:: ...]``
        tag on the *index*-th open task — a manual override of whatever the
        LLM filed the task under when it was created.
        """
        new_tag = f"[category:: {category}]" if category is not None else None
        async with self._lock:
            return await asyncio.to_thread(self._set_tag_sync, index, CATEGORY_TAG_RE, new_tag)

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
        completed_at = self._now().strftime(TIMESTAMP_FORMAT)
        lines[line_no] = f"{DONE_PREFIX}{task_text} {DONE_MARKER}{completed_at}"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    def _set_tag_sync(self, index: int, tag_re: re.Pattern[str], new_tag: str | None) -> bool:
        """Replace whatever *tag_re* currently matches in the task's text with
        *new_tag* (or remove it entirely if *new_tag* is None). Shared by
        ``set_deadline`` and ``set_priority`` — same shape, different tag.
        """
        lines = self._read_lines()
        open_positions = [i for i, line in enumerate(lines) if line.startswith(TASK_PREFIX)]
        if index < 1 or index > len(open_positions):
            return False

        line_no = open_positions[index - 1]
        text = lines[line_no][len(TASK_PREFIX):]
        without_tag = re.sub(r"\s*" + tag_re.pattern, "", text, flags=re.IGNORECASE).strip()
        if new_tag is not None:
            without_tag = f"{without_tag} {new_tag}".strip()
        lines[line_no] = f"{TASK_PREFIX}{without_tag}"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    def _list_completed_since_sync(self, since: datetime) -> list[str]:
        lines = self._read_lines()
        results = []
        for line in lines:
            if not line.startswith(DONE_PREFIX):
                continue
            match = _DONE_TIMESTAMP_RE.search(line)
            if match is None:
                continue
            completed_at = datetime.strptime(match.group(1), TIMESTAMP_FORMAT)
            if completed_at >= since:
                results.append(line[len(DONE_PREFIX):])
        return results
