from pathlib import Path

import config


def test_resolve_allowed_user_ids_parses_and_filters(monkeypatch):
    monkeypatch.setenv("ALLOWED_USER_IDS", " 123, abc, 456 ,,")
    ids = config._resolve_allowed_user_ids()
    assert ids == frozenset({123, 456})


def test_resolve_allowed_user_ids_empty(monkeypatch):
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    assert config._resolve_allowed_user_ids() == frozenset()


def test_resolve_obsidian_file_default(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_FILE", raising=False)
    result = config._resolve_obsidian_file()
    assert result == Path.home() / "ObsidianVault" / "Задачи.md"


def test_resolve_obsidian_file_expands_user(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_FILE", "~/some/tasks.md")
    result = config._resolve_obsidian_file()
    assert result == (Path.home() / "some" / "tasks.md").resolve()


def test_load_config_fails_without_token(monkeypatch, tmp_path):
    monkeypatch.delenv("TG_BOT_TOKEN", raising=False)
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")
    assert config.load_config() is None


def test_load_config_rejects_malformed_token(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_BOT_TOKEN", "not-a-real-token")
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")
    assert config.load_config() is None


def test_load_config_success(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("OBSIDIAN_FILE", str(tmp_path / "vault" / "tasks.md"))
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("WEATHER_LATITUDE", raising=False)
    monkeypatch.delenv("WEATHER_LONGITUDE", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")

    cfg = config.load_config()
    assert cfg is not None
    assert cfg.token == "123456:ABCDEF"
    assert cfg.obsidian_file == (tmp_path / "vault" / "tasks.md").resolve()
    assert cfg.has_allowlist is False
    assert cfg.has_llm is False
    assert cfg.task_sections == config.DEFAULT_TASK_SECTIONS
    assert cfg.chat_id is None
    assert cfg.timezone == config.DEFAULT_TIMEZONE
    assert cfg.morning_digest_time == config.DEFAULT_MORNING_DIGEST_TIME
    assert cfg.evening_reflection_time == config.DEFAULT_EVENING_REFLECTION_TIME
    assert cfg.weekly_review_day == config.DEFAULT_WEEKLY_REVIEW_DAY
    assert cfg.weekly_review_time == config.DEFAULT_WEEKLY_REVIEW_TIME
    assert cfg.has_calendar is False
    assert cfg.google_calendar_id == config.DEFAULT_GOOGLE_CALENDAR_ID
    assert cfg.meeting_brief_lead_minutes == config.DEFAULT_MEETING_BRIEF_LEAD_MINUTES
    assert cfg.has_weather is False
    assert cfg.has_vault_index is False
    assert cfg.obsidian_vault_path is None
    assert cfg.ollama_base_url == config.DEFAULT_OLLAMA_BASE_URL
    assert cfg.ollama_embed_model == config.DEFAULT_OLLAMA_EMBED_MODEL
    assert cfg.vault_reindex_interval_minutes == config.DEFAULT_VAULT_REINDEX_INTERVAL_MINUTES


def test_resolve_task_sections_parses_and_trims(monkeypatch):
    monkeypatch.setenv("TASK_SECTIONS", " Работа , Личное ,, Проект X")
    assert config._resolve_task_sections() == ("Работа", "Личное", "Проект X")


def test_resolve_task_sections_defaults_when_empty(monkeypatch):
    monkeypatch.delenv("TASK_SECTIONS", raising=False)
    assert config._resolve_task_sections() == config.DEFAULT_TASK_SECTIONS


def test_resolve_chat_id_uses_explicit_value(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    assert config._resolve_chat_id(frozenset({123, 456})) == 555


def test_resolve_chat_id_falls_back_to_sole_allowed_user(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert config._resolve_chat_id(frozenset({123})) == 123


def test_resolve_chat_id_none_when_ambiguous(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert config._resolve_chat_id(frozenset({123, 456})) is None
    assert config._resolve_chat_id(frozenset()) is None


def test_resolve_time_hhmm_accepts_valid_value(monkeypatch):
    monkeypatch.setenv("MORNING_DIGEST_TIME", "07:30")
    assert config._resolve_time_hhmm("MORNING_DIGEST_TIME", "08:00") == "07:30"


def test_resolve_time_hhmm_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("MORNING_DIGEST_TIME", "25:99")
    assert config._resolve_time_hhmm("MORNING_DIGEST_TIME", "08:00") == "08:00"


def test_resolve_weekday_accepts_valid_value(monkeypatch):
    monkeypatch.setenv("WEEKLY_REVIEW_DAY", "Fri")
    assert config._resolve_weekday("WEEKLY_REVIEW_DAY", "sun") == "fri"


def test_resolve_weekday_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("WEEKLY_REVIEW_DAY", "someday")
    assert config._resolve_weekday("WEEKLY_REVIEW_DAY", "sun") == "sun"


def test_resolve_positive_int_accepts_valid_value(monkeypatch):
    monkeypatch.setenv("MEETING_BRIEF_LEAD_MINUTES", "45")
    assert config._resolve_positive_int("MEETING_BRIEF_LEAD_MINUTES", 30) == 45


def test_resolve_positive_int_rejects_zero_and_negative(monkeypatch):
    monkeypatch.setenv("MEETING_BRIEF_LEAD_MINUTES", "0")
    assert config._resolve_positive_int("MEETING_BRIEF_LEAD_MINUTES", 30) == 30
    monkeypatch.setenv("MEETING_BRIEF_LEAD_MINUTES", "-5")
    assert config._resolve_positive_int("MEETING_BRIEF_LEAD_MINUTES", 30) == 30


def test_resolve_positive_int_defaults_when_empty(monkeypatch):
    monkeypatch.delenv("MEETING_BRIEF_LEAD_MINUTES", raising=False)
    assert config._resolve_positive_int("MEETING_BRIEF_LEAD_MINUTES", 30) == 30


def test_has_calendar_requires_all_three_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("OBSIDIAN_FILE", str(tmp_path / "tasks.md"))
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")

    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GOOGLE_CALENDAR_REFRESH_TOKEN", raising=False)
    cfg = config.load_config()
    assert cfg is not None
    assert cfg.has_calendar is False

    monkeypatch.setenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "refresh")
    cfg = config.load_config()
    assert cfg is not None
    assert cfg.has_calendar is True


def test_resolve_coordinate_accepts_valid_value(monkeypatch):
    monkeypatch.setenv("WEATHER_LATITUDE", "55.75")
    assert config._resolve_coordinate("WEATHER_LATITUDE", -90.0, 90.0) == 55.75


def test_resolve_coordinate_rejects_out_of_range(monkeypatch):
    monkeypatch.setenv("WEATHER_LATITUDE", "200")
    assert config._resolve_coordinate("WEATHER_LATITUDE", -90.0, 90.0) is None


def test_resolve_coordinate_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv("WEATHER_LATITUDE", "not-a-number")
    assert config._resolve_coordinate("WEATHER_LATITUDE", -90.0, 90.0) is None


def test_resolve_coordinate_none_when_empty(monkeypatch):
    monkeypatch.delenv("WEATHER_LATITUDE", raising=False)
    assert config._resolve_coordinate("WEATHER_LATITUDE", -90.0, 90.0) is None


def test_has_weather_requires_both_coordinates(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("OBSIDIAN_FILE", str(tmp_path / "tasks.md"))
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")

    monkeypatch.setenv("WEATHER_LATITUDE", "55.75")
    monkeypatch.delenv("WEATHER_LONGITUDE", raising=False)
    cfg = config.load_config()
    assert cfg is not None
    assert cfg.has_weather is False

    monkeypatch.setenv("WEATHER_LONGITUDE", "37.62")
    cfg = config.load_config()
    assert cfg is not None
    assert cfg.has_weather is True


def test_resolve_obsidian_vault_path_unset_is_none(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert config._resolve_obsidian_vault_path() is None


def test_resolve_obsidian_vault_path_expands_user(monkeypatch, tmp_path):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "~/some/vault")
    result = config._resolve_obsidian_vault_path()
    assert result == (Path.home() / "some" / "vault").resolve()


def test_validate_obsidian_vault_path_missing_dir(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert config._validate_obsidian_vault_path(missing) is not None


def test_validate_obsidian_vault_path_rejects_file(tmp_path):
    a_file = tmp_path / "not-a-dir.md"
    a_file.write_text("hi", encoding="utf-8")
    assert config._validate_obsidian_vault_path(a_file) is not None


def test_validate_obsidian_vault_path_accepts_existing_dir(tmp_path):
    assert config._validate_obsidian_vault_path(tmp_path) is None


def test_load_config_with_vault_path(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("OBSIDIAN_FILE", str(vault / "tasks.md"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")

    cfg = config.load_config()
    assert cfg is not None
    assert cfg.has_vault_index is True
    assert cfg.obsidian_vault_path == vault.resolve()
    assert cfg.ollama_embed_model == "mxbai-embed-large"


def test_load_config_fails_with_missing_vault_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("OBSIDIAN_FILE", str(tmp_path / "tasks.md"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "no-such-vault"))
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")

    assert config.load_config() is None
