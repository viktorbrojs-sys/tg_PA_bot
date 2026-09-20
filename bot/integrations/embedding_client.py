"""Embeddings via a local Ollama server, for Second Brain semantic search.

Same pattern as ``WeatherClient``/``DeepSeekClient``: an abstraction
(``EmbeddingClient``) with a no-op fallback (``NullEmbeddingClient``) so the
bot works fine without Ollama configured — vault indexing and semantic
search just stay disabled (``BotConfig.has_vault_index`` gates this one
layer up, in main.py's wiring).

Ollama, not a Python embedding library (sentence-transformers/fastembed):
Victor already runs Ollama locally for other things, so this is a plain
HTTP client with no new heavy dependency (no torch, no bundled model) —
the model lives in Ollama, not in this process.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Return one embedding vector per input text, in the same order.

        Returns ``None`` (never a partial list) if embeddings could not be
        computed at all — e.g. Ollama unreachable, model not pulled — so
        callers can tell "nothing to embed" (``[]`` for empty *texts*) apart
        from "embedding failed" (``None``).
        """
        ...


class NullEmbeddingClient:
    """No-op fallback used when vault indexing isn't configured."""

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None


class OllamaEmbeddingClient:
    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": texts},
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.error("Ollama embeddings request failed: %s", exc)
            return None
        except ValueError as exc:  # malformed JSON
            logger.error("Ollama returned malformed JSON: %s", exc)
            return None

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            logger.error("Unexpected Ollama /api/embed response shape: %r", data)
            return None
        return embeddings
