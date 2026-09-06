"""Bot configuration — loaded from a .env file or environment variables."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Ищем .env в корне проекта (на уровень выше папки bot/).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


@dataclass(frozen=True)
class BotConfig:
    token: str
    obsidian_file: Path
    allowed_user_ids: frozenset[int]
    log_level: str

    @property
    def has_allowlist(self) -> bool:
        return bool(self.allowed_user_ids)


def _resolve_obsidian_file() -> Path:
    raw = os.environ.get("OBSIDIAN_FILE", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / "ObsidianVault" / "Задачи.md"


def _resolve_allowed_user_ids() -> frozenset[int]:
    raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return frozenset()

    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # Telegram user ids are always positive, but chat/channel ids can be
        # negative — accept an optional leading "-" so both work.
        if part.lstrip("-").isdigit():
            ids.add(int(part))
        else:
            logger.warning("Ignoring invalid entry in ALLOWED_USER_IDS: %r", part)
    return frozenset(ids)


def _validate_obsidian_file(path: Path) -> str | None:
    """Return an error message if the tasks file cannot possibly be written, else None."""
    if path.exists() and path.is_dir():
        return f"OBSIDIAN_FILE points to a directory, not a file: {path}"
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"Cannot create directory for OBSIDIAN_FILE ({parent}): {exc}"
    if not os.access(parent, os.W_OK):
        return f"Directory is not writable: {parent}"
    return None


def load_config() -> BotConfig | None:
    """Load and validate configuration. Returns None (after logging why) on failure."""
    # override=False: real environment variables (e.g. Replit Secrets, systemd
    # Environment=) always win over whatever is in the .env file.
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    if not token:
        logger.error(
            "TG_BOT_TOKEN не задан.\n"
            "  • Локально: заполните TG_BOT_TOKEN в файле .env (см. .env.example)\n"
            "  • На Replit: добавьте секрет TG_BOT_TOKEN в разделе Secrets"
        )
        return None
    if ":" not in token:
        logger.error(
            "TG_BOT_TOKEN выглядит некорректно (ожидается формат 123456:ABC-DEF...). "
            "Проверьте значение, полученное от @BotFather."
        )
        return None

    obsidian_file = _resolve_obsidian_file()
    error = _validate_obsidian_file(obsidian_file)
    if error:
        logger.error("Некорректный OBSIDIAN_FILE: %s", error)
        return None

    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        logger.warning("Неизвестный LOG_LEVEL=%r, использую INFO", log_level)
        log_level = "INFO"

    config = BotConfig(
        token=token,
        obsidian_file=obsidian_file,
        allowed_user_ids=_resolve_allowed_user_ids(),
        log_level=log_level,
    )

    env_source = "file .env" if _ENV_FILE.exists() else "environment"
    logger.info(
        "Config loaded from %s: file=%s allowlist=%s",
        env_source,
        config.obsidian_file,
        sorted(config.allowed_user_ids) or "disabled",
    )
    return config
