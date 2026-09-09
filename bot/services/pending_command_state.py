"""Tracks commands that are waiting for their parameter as the next message.

Used for the "command without an argument" UX: instead of just showing a
usage hint, the bot asks for the value and treats the very next plain-text
message from that chat as the missing argument. Deliberately separate from
``ReflectionState`` — they represent different kinds of "the next message
means something special" states and are checked independently by the
message handler.
"""

from __future__ import annotations


class PendingCommandState:
    def __init__(self) -> None:
        self._pending: dict[int, str] = {}

    def start(self, chat_id: int, command: str) -> None:
        self._pending[chat_id] = command

    def pop(self, chat_id: int) -> str | None:
        """Return and clear the pending command for *chat_id*, if any."""
        return self._pending.pop(chat_id, None)

    def is_pending(self, chat_id: int) -> bool:
        return chat_id in self._pending

    def clear(self, chat_id: int) -> None:
        self._pending.pop(chat_id, None)
