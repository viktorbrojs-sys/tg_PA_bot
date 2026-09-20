#!/usr/bin/env python3
"""Одноразовая (или ручная) полная переиндексация vault для Second Brain.

Обычно переиндексация идёт сама по расписанию (см. VAULT_REINDEX_INTERVAL_MINUTES
в .env — job внутри бота, scheduler/jobs.py), пока бот запущен. Этот скрипт
нужен, если:

- вы только что настроили OBSIDIAN_VAULT_PATH и хотите проиндексировать
  сразу, не дожидаясь первого срабатывания job'а или перезапуска бота;
- вы сильно изменили vault (например, импортировали много старых заметок)
  и хотите обновить индекс немедленно;
- бот не запущен, а проверить индексацию нужно.

Использование:
    cd bot && python ../scripts/reindex_vault.py

Требует настроенных OBSIDIAN_VAULT_PATH и доступной Ollama (OLLAMA_BASE_URL,
OLLAMA_EMBED_MODEL — см. .env). Без OBSIDIAN_VAULT_PATH скрипт сразу
завершится с понятным сообщением — это не ошибка, просто фича выключена.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Тот же трюк, что и в tests/conftest.py: bot/ — плоский пакет, его модули
# импортируются без префикса (from config import ...), поэтому добавляем
# bot/ в sys.path вместо превращения его в полноценный Python-пакет.
_BOT_DIR = Path(__file__).resolve().parent.parent / "bot"
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

from config import load_config  # noqa: E402
from integrations.embedding_client import OllamaEmbeddingClient  # noqa: E402
from services.vault_indexer import reindex_vault  # noqa: E402
from vault_index import VaultIndex  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("reindex_vault")


async def main() -> int:
    config = load_config()
    if config is None:
        logger.error("Конфигурация некорректна (см. ошибки выше) — переиндексация невозможна.")
        return 1

    if not config.has_vault_index:
        logger.info(
            "OBSIDIAN_VAULT_PATH не задан — Second Brain выключен, индексировать нечего."
        )
        return 0

    vault_path = config.obsidian_vault_path
    assert vault_path is not None  # гарантировано has_vault_index

    embeddings = OllamaEmbeddingClient(
        base_url=config.ollama_base_url, model=config.ollama_embed_model
    )

    logger.info("Определяю размерность эмбеддингов (%s)...", config.ollama_embed_model)
    probe = await embeddings.embed(["_dimension_probe_"])
    if not probe:
        logger.error(
            "Ollama (%s) недоступна или модель %s не отвечает — переиндексация прервана.",
            config.ollama_base_url,
            config.ollama_embed_model,
        )
        return 1

    index = VaultIndex(config.vault_index_db_path, embedding_dim=len(probe[0]))

    logger.info("Индексирую vault: %s -> %s", vault_path, config.vault_index_db_path)
    stats = await reindex_vault(vault_path, index, embeddings)

    if stats.failed:
        logger.error("Переиндексация прервана (эмбеддинги недоступны в процессе работы).")
        return 1

    logger.info(
        "Готово: добавлено %d, обновлено %d, удалено %d, без изменений %d.",
        stats.added,
        stats.updated,
        stats.deleted,
        stats.unchanged,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
