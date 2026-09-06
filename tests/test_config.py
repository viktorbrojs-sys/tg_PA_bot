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
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "does-not-exist.env")

    cfg = config.load_config()
    assert cfg is not None
    assert cfg.token == "123456:ABCDEF"
    assert cfg.obsidian_file == (tmp_path / "vault" / "tasks.md").resolve()
    assert cfg.has_allowlist is False
