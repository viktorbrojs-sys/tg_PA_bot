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
DEFAULT_GOOGLE_CALENDAR_ID = "primary"
DEFAULT_MEETING_BRIEF_LEAD_MINUTES = 30
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
DEFAULT_VAULT_REINDEX_INTERVAL_MINUTES = 60
DEFAULT_MAIL_REINDEX_INTERVAL_MINUTES = 60
DEFAULT_MAIL_INDEX_RETENTION_DAYS = 180

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
    google_calendar_client_id: str | None
    google_calendar_client_secret: str | None
    google_calendar_refresh_token: str | None
    google_calendar_id: str
    meeting_brief_lead_minutes: int
    weather_latitude: float | None
    weather_longitude: float | None
    obsidian_vault_path: Path | None
    ollama_base_url: str
    ollama_embed_model: str
    vault_reindex_interval_minutes: int
    vault_index_db_path: Path
    gmail_client_id: str | None
    gmail_client_secret: str | None
    gmail_refresh_token: str | None
    mail_index_db_path: Path
    mail_reindex_interval_minutes: int
    mail_index_retention_days: int

    @property
    def has_allowlist(self) -> bool:
        return bool(self.allowed_user_ids)

    @property
    def has_llm(self) -> bool:
        return bool(self.deepseek_api_key)

    @property
    def has_calendar(self) -> bool:
        return bool(
            self.google_calendar_client_id
            and self.google_calendar_client_secret
            and self.google_calendar_refresh_token
        )

    @property
    def has_gmail(self) -> bool:
        return bool(
            self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token
        )

    @property
    def has_weather(self) -> bool:
        return self.weather_latitude is not None and self.weather_longitude is not None

    @property
    def has_vault_index(self) -> bool:
        return self.obsidian_vault_path is not None


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


def _resolve_positive_int(env_var: str, default: int) -> int:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    logger.warning("Ignoring invalid %s=%r, using default %s", env_var, raw, default)
    return default


def _resolve_coordinate(env_var: str, min_value: float, max_value: float) -> float | None:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r (not a number)", env_var, raw)
        return None
    if not (min_value <= value <= max_value):
        logger.warning("Ignoring out-of-range %s=%r", env_var, raw)
        return None
    return value


def _resolve_obsidian_vault_path() -> Path | None:
    """Whole-vault semantic search (Second Brain) is opt-in: unset ->
    feature disabled, the bot behaves exactly as before (grep-only search).
    Unlike OBSIDIAN_FILE, this directory must already exist — we don't want
    to silently create an empty "vault" the person never asked for.
    """
    raw = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _resolve_vault_index_db_path() -> Path:
    """Where the sqlite-vec index file lives. Deliberately NOT inside the
    Obsidian vault itself (default: a dotfolder in the home directory) —
    it's a derived/rebuildable artifact, not a note, and keeping it out of
    the vault avoids confusing Obsidian Sync/git-based vault backups with a
    binary file that changes on every reindex.
    """
    raw = os.environ.get("VAULT_INDEX_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".tg_pa_bot" / "vault_index.db"


def _resolve_mail_index_db_path() -> Path:
    """Where the mail search index lives — separate file from the vault
    index (different schema, different content, independently prunable by
    retention), same dotfolder convention.
    """
    raw = os.environ.get("MAIL_INDEX_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".tg_pa_bot" / "mail_index.db"


def _validate_obsidian_vault_path(path: Path) -> str | None:
    """Return an error message if the vault path is unusable, else None."""
    if not path.exists():
        return f"OBSIDIAN_VAULT_PATH does not exist: {path}"
    if not path.is_dir():
        return f"OBSIDIAN_VAULT_PATH is not a directory: {path}"
    return None


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

    obsidian_vault_path = _resolve_obsidian_vault_path()
    if obsidian_vault_path is not None:
        vault_error = _validate_obsidian_vault_path(obsidian_vault_path)
        if vault_error:
            logger.error("Некорректный OBSIDIAN_VAULT_PATH: %s", vault_error)
            return None

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
        google_calendar_client_id=os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "").strip() or None,
        google_calendar_client_secret=(
            os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", "").strip() or None
        ),
        google_calendar_refresh_token=(
            os.environ.get("GOOGLE_CALENDAR_REFRESH_TOKEN", "").strip() or None
        ),
        google_calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
        or DEFAULT_GOOGLE_CALENDAR_ID,
        meeting_brief_lead_minutes=_resolve_positive_int(
            "MEETING_BRIEF_LEAD_MINUTES", DEFAULT_MEETING_BRIEF_LEAD_MINUTES
        ),
        weather_latitude=_resolve_coordinate("WEATHER_LATITUDE", -90.0, 90.0),
        weather_longitude=_resolve_coordinate("WEATHER_LONGITUDE", -180.0, 180.0),
        obsidian_vault_path=obsidian_vault_path,
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_OLLAMA_BASE_URL,
        ollama_embed_model=os.environ.get("OLLAMA_EMBED_MODEL", "").strip()
        or DEFAULT_OLLAMA_EMBED_MODEL,
        vault_reindex_interval_minutes=_resolve_positive_int(
            "VAULT_REINDEX_INTERVAL_MINUTES", DEFAULT_VAULT_REINDEX_INTERVAL_MINUTES
        ),
        vault_index_db_path=_resolve_vault_index_db_path(),
        gmail_client_id=os.environ.get("GMAIL_CLIENT_ID", "").strip() or None,
        gmail_client_secret=os.environ.get("GMAIL_CLIENT_SECRET", "").strip() or None,
        gmail_refresh_token=os.environ.get("GMAIL_REFRESH_TOKEN", "").strip() or None,
        mail_index_db_path=_resolve_mail_index_db_path(),
        mail_reindex_interval_minutes=_resolve_positive_int(
            "MAIL_REINDEX_INTERVAL_MINUTES", DEFAULT_MAIL_REINDEX_INTERVAL_MINUTES
        ),
        mail_index_retention_days=_resolve_positive_int(
            "MAIL_INDEX_RETENTION_DAYS", DEFAULT_MAIL_INDEX_RETENTION_DAYS
        ),
    )

    env_source = "file .env" if _ENV_FILE.exists() else "environment"
    logger.info(
        "Config loaded from %s: file=%s allowlist=%s llm=%s sections=%s "
        "chat_id=%s digest=%s reflection=%s weekly_review=%s %s tz=%s "
        "calendar=%s gmail=%s weather=%s vault_index=%s",
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
        "google" if config.has_calendar else "disabled",
        "google" if config.has_gmail else "disabled",
        "open-meteo" if config.has_weather else "disabled",
        f"{config.obsidian_vault_path} (ollama:{config.ollama_embed_model})"
        if config.has_vault_index
        else "disabled",
    )
    return config
