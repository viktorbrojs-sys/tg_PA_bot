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


DEFAULT_TASK_SECTIONS = ("Работа", "Личное")
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_TIMEZONE = "Europe/Moscow"
DEFAULT_MORNING_DIGEST_TIME = "08:00"
DEFAULT_EVENING_REFLECTION_TIME = "21:00"
DEFAULT_WEEKLY_REVIEW_DAY = "sun"
DEFAULT_WEEKLY_REVIEW_TIME = "20:00"

# Values accepted by APScheduler's CronTrigger(day_of_week=...).
_VALID_WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


@dataclass(frozen=True)
class BotConfig:
    token: str
    obsidian_file: Path
    allowed_user_ids: frozenset[int]
    log_level: str
    deepseek_api_key: str | None
    llm_model: str
    task_sections: tuple[str, ...]
    chat_id: int | None
    timezone: str
    morning_digest_time: str
    evening_reflection_time: str
    weekly_review_day: str
    weekly_review_time: str

    @property
    def has_allowlist(self) -> bool:
        return bool(self.allowed_user_ids)

    @property
    def has_llm(self) -> bool:
        return bool(self.deepseek_api_key)


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


def _resolve_task_sections() -> tuple[str, ...]:
    raw = os.environ.get("TASK_SECTIONS", "").strip()
    if not raw:
        return DEFAULT_TASK_SECTIONS
    sections = tuple(s.strip() for s in raw.split(",") if s.strip())
    return sections or DEFAULT_TASK_SECTIONS


def _resolve_chat_id(allowed_user_ids: frozenset[int]) -> int | None:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if raw:
        if raw.lstrip("-").isdigit():
            return int(raw)
        logger.warning("Ignoring invalid TELEGRAM_CHAT_ID: %r", raw)

    # Convenience default for the common single-user setup: in a private
    # Telegram chat, chat_id == user_id, so if there's exactly one allowed
    # user we already know where to send proactive messages.
    if len(allowed_user_ids) == 1:
        return next(iter(allowed_user_ids))
    return None


def _resolve_time_hhmm(env_var: str, default: str) -> str:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    parts = raw.split(":")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour < 24 and 0 <= minute < 60:
            return raw
    logger.warning("Ignoring invalid %s=%r, using default %s", env_var, raw, default)
    return default


def _resolve_weekday(env_var: str, default: str) -> str:
    raw = os.environ.get(env_var, "").strip().lower()
    if not raw:
        return default
    if raw in _VALID_WEEKDAYS:
        return raw
    logger.warning("Ignoring invalid %s=%r, using default %s", env_var, raw, default)
    return default


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
    # override=False: real environment variables (e.g. systemd Environment=,
    # a process manager, or a container's secret manager) always win over
    # whatever is in the .env file.
    load_dotenv(dotenv_path=_ENV_FILE, override=False)

    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    if not token:
        logger.error(
            "TG_BOT_TOKEN не задан. Заполните TG_BOT_TOKEN в файле .env "
            "(см. .env.example) или задайте его как переменную окружения."
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

    deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or None
    llm_model = os.environ.get("LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
    allowed_user_ids = _resolve_allowed_user_ids()

    config = BotConfig(
        token=token,
        obsidian_file=obsidian_file,
        allowed_user_ids=allowed_user_ids,
        log_level=log_level,
        deepseek_api_key=deepseek_api_key,
        llm_model=llm_model,
        task_sections=_resolve_task_sections(),
        chat_id=_resolve_chat_id(allowed_user_ids),
        timezone=os.environ.get("TIMEZONE", "").strip() or DEFAULT_TIMEZONE,
        morning_digest_time=_resolve_time_hhmm("MORNING_DIGEST_TIME", DEFAULT_MORNING_DIGEST_TIME),
        evening_reflection_time=_resolve_time_hhmm(
            "EVENING_REFLECTION_TIME", DEFAULT_EVENING_REFLECTION_TIME
        ),
        weekly_review_day=_resolve_weekday("WEEKLY_REVIEW_DAY", DEFAULT_WEEKLY_REVIEW_DAY),
        weekly_review_time=_resolve_time_hhmm("WEEKLY_REVIEW_TIME", DEFAULT_WEEKLY_REVIEW_TIME),
    )

    env_source = "file .env" if _ENV_FILE.exists() else "environment"
    logger.info(
        "Config loaded from %s: file=%s allowlist=%s llm=%s sections=%s "
        "chat_id=%s digest=%s reflection=%s weekly_review=%s %s tz=%s",
        env_source,
        config.obsidian_file,
        sorted(config.allowed_user_ids) or "disabled",
        "deepseek" if config.has_llm else "disabled (rule-based fallback)",
        list(config.task_sections),
        config.chat_id or "not set (proactive messages disabled)",
        config.morning_digest_time,
        config.evening_reflection_time,
        config.weekly_review_day,
        config.weekly_review_time,
        config.timezone,
    )
    return config
