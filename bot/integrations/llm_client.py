"""LLM client abstraction.

Every service that needs an LLM (task classification, day-planning, and
later: digests, search, meeting briefs) depends only on the ``LLMClient``
protocol below, never on a specific provider. This keeps the rest of the app
testable with ``NullLLMClient`` and avoids locking the whole codebase to one
vendor's SDK/API shape.

``NullLLMClient`` is also the real production fallback when no API key is
configured: the bot must stay fully usable without an LLM (files land in the
catch-all ``DEFAULT_SECTION`` instead of a classified one, and day-planning
falls back to a plain line/bullet split).
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

# Catch-all section used whenever classification isn't available or the
# model couldn't confidently pick one of the configured sections.
DEFAULT_SECTION = "Входящие"


class LLMClient(Protocol):
    async def classify_task(self, text: str, sections: list[str]) -> str:
        """Return the best-matching section for *text*.

        Must return either one of *sections* or ``DEFAULT_SECTION``.
        """
        ...

    async def split_into_tasks(self, text: str) -> list[str]:
        """Turn a free-form message into a list of discrete task strings."""
        ...


class NullLLMClient:
    """No-op fallback used when no LLM API key is configured."""

    async def classify_task(self, text: str, sections: list[str]) -> str:
        return DEFAULT_SECTION

    async def split_into_tasks(self, text: str) -> list[str]:
        return _naive_split(text)


class DeepSeekClient:
    """``LLMClient`` backed by DeepSeek's OpenAI-compatible chat completions API."""

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    async def _chat(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return str(content).strip()

    async def classify_task(self, text: str, sections: list[str]) -> str:
        if not sections:
            return DEFAULT_SECTION

        system = (
            "Ты классифицируешь входящие задачи пользователя по разделам его "
            f"списка дел. Доступные разделы: {', '.join(sections)}. "
            f"Если ни один раздел явно не подходит, ответь «{DEFAULT_SECTION}». "
            "Ответь ТОЛЬКО названием одного раздела, без пояснений и кавычек."
        )
        try:
            answer = await self._chat(system, text)
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            logger.warning("LLM classification failed, using default section: %s", exc)
            return DEFAULT_SECTION

        for section in [*sections, DEFAULT_SECTION]:
            if section.lower() == answer.lower():
                return section
        logger.info("LLM returned an unrecognised section (%r), using default", answer)
        return DEFAULT_SECTION

    async def split_into_tasks(self, text: str) -> list[str]:
        system = (
            "Разбей сообщение пользователя на отдельные короткие задачи на день. "
            'Ответь ТОЛЬКО JSON-массивом строк, например: ["Задача 1", "Задача 2"]. '
            "Без markdown, пояснений или лишнего текста."
        )
        try:
            answer = await self._chat(system, text)
            tasks = json.loads(answer)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            logger.warning("LLM day-planning failed, falling back to line split: %s", exc)
            return _naive_split(text)

        if isinstance(tasks, list) and all(isinstance(t, str) for t in tasks):
            cleaned = [t.strip() for t in tasks if t.strip()]
            if cleaned:
                return cleaned
        return _naive_split(text)


def _naive_split(text: str) -> list[str]:
    """Split free text into tasks by line, stripping common bullet markers."""
    lines = (line.strip(" \t-•·*").strip() for line in text.splitlines())
    return [line for line in lines if line]
