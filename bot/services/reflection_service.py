"""Evening reflection: bot asks "what got done", user answers in free text,
matching open tasks get marked done.

``ReflectionState`` is deliberately tiny and in-memory: it just tracks which
chat IDs are currently expected to reply to a reflection prompt, so the
plain-text message handler can route the very next message there instead of
treating it as a new task.
"""

from __future__ import annotations

from integrations.llm_client import LLMClient

from services.task_service import TaskService


class ReflectionState:
    def __init__(self) -> None:
        self._awaiting: set[int] = set()

    def start(self, chat_id: int) -> None:
        self._awaiting.add(chat_id)

    def is_awaiting(self, chat_id: int) -> bool:
        return chat_id in self._awaiting

    def clear(self, chat_id: int) -> None:
        self._awaiting.discard(chat_id)


class ReflectionService:
    def __init__(self, task_service: TaskService, llm: LLMClient) -> None:
        self._tasks = task_service
        self._llm = llm

    async def process_reply(self, reply: str) -> str:
        # Snapshot the open tasks *before* marking anything done — indices in
        # the returned list stay valid as the reference for display text even
        # as the underlying file mutates below.
        open_tasks = await self._tasks.list_all_open_tasks()
        if not open_tasks:
            return "Записал, спасибо! Открытых задач и так не было."

        raw_indices = await self._llm.match_completed_tasks(reply, open_tasks)
        valid_indices = sorted(
            {i for i in raw_indices if 1 <= i <= len(open_tasks)}
        )

        # mark_done() re-reads the file and re-numbers open tasks on every
        # call, so completing task N shifts every later index down by one.
        # Processing from the highest index down avoids that shift affecting
        # indices we haven't handled yet.
        done_texts: dict[int, str] = {}
        for index in sorted(valid_indices, reverse=True):
            if await self._tasks.mark_done(index):
                done_texts[index] = open_tasks[index - 1]

        # Anything not marked done stays open — nothing to change in the file
        # for that (it never left the open list), but we call it out
        # explicitly so "перенос на завтра" is visible rather than implicit.
        carried_over = [
            text for i, text in enumerate(open_tasks, start=1) if i not in done_texts
        ]

        lines: list[str] = []
        if done_texts:
            lines.append(f"✅ Отметил как выполненные ({len(done_texts)}):")
            lines.extend(f"  • {done_texts[i]}" for i in sorted(done_texts))
        else:
            lines.append("Не нашёл среди открытых задач того, что вы описали.")

        if carried_over:
            lines.append(f"\n🔁 Переносится на завтра ({len(carried_over)}):")
            lines.extend(f"  • {t}" for t in carried_over)
        else:
            lines.append("\n🎉 Открытых задач не осталось!")

        return "\n".join(lines)
