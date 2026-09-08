"""Task-related business logic, independent of Telegram.

Handlers should only call into ``TaskService`` — they must not talk to
``TaskStore`` or ``LLMClient`` directly. This is what keeps handlers thin and
the classification/day-planning behaviour unit-testable without spinning up
python-telegram-bot at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from integrations.llm_client import LLMClient
from storage import TaskStore


@dataclass(frozen=True)
class PlannedTask:
    text: str
    section: str


class TaskService:
    def __init__(
        self,
        store: TaskStore,
        llm: LLMClient,
        sections: tuple[str, ...],
    ) -> None:
        self._store = store
        self._llm = llm
        self._sections = sections

    async def add_task(self, text: str) -> str:
        """Classify and store a single task. Returns the section it was filed under."""
        section = await self._llm.classify_task(text, list(self._sections))
        await self._store.add_task(text, section=section)
        return section

    async def plan_day(self, text: str) -> list[PlannedTask]:
        """Split free-form text into tasks, classify and store each.

        Used for "напишите одним сообщением план на день" — the message is
        broken into discrete tasks (via the LLM, or a plain line split as a
        fallback) and every piece is filed like a normal classified task.
        """
        pieces = await self._llm.split_into_tasks(text)
        planned: list[PlannedTask] = []
        for piece in pieces:
            section = await self._llm.classify_task(piece, list(self._sections))
            await self._store.add_task(piece, section=section)
            planned.append(PlannedTask(text=piece, section=section))
        return planned

    async def list_all_open_tasks(self) -> list[str]:
        """Every open task in the file — the "полный список задач" feature."""
        return await self._store.list_open_tasks(limit=None)

    async def list_recent_open_tasks(self, limit: int) -> list[str]:
        return await self._store.list_open_tasks(limit=limit)

    async def mark_done(self, index: int) -> bool:
        return await self._store.mark_done(index)
