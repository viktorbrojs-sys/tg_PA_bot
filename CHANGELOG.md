# Changelog

## 1.1.0 — code review pass

### Fixed
- **Critical:** the `ALLOWED_USER_IDS` allowlist did not actually block anyone.
  The guard handler replied "⛔ no access" but never stopped update
  propagation, so every other handler still ran for blocked users. Now raises
  `ApplicationHandlerStop`.
- File reads/writes (`/list`, `/done`, adding a task) ran synchronously inside
  async handlers, blocking the whole bot on slow disks/network filesystems.
  Moved to `asyncio.to_thread`.
- Concurrent messages could interleave writes to the tasks file with no
  locking. Added a per-file `asyncio.Lock` in the new `storage.py`.
- Replaced `assert` statements used for request validation in handlers
  (asserts vanish under `python -O`) with explicit `if update.message is None: return`.
- `config.py` loaded `.env` as a side effect of importing the module, making
  it hard to test and order-dependent. Moved into `load_config()`.
- Task text was logged verbatim at INFO level; logs now only record length,
  not content, to avoid leaking potentially private task text.

### Added
- `/done N` command to mark a task from `/list` as complete.
- Config validation: rejects an obviously malformed `TG_BOT_TOKEN`, checks the
  `OBSIDIAN_FILE` directory is writable, warns on invalid `ALLOWED_USER_IDS`
  entries instead of silently dropping them, validates `LOG_LEVEL`.
- Global error handler (`app.add_error_handler`) so unhandled exceptions are
  logged and the user gets a friendly message instead of the bot silently
  dying on that update.
- Handler for unknown commands (previously any `/foo` was silently ignored).
- Unit tests for `storage.py` and `config.py` (`pytest` + `pytest-asyncio`),
  including a concurrency test for the file lock.
- CI workflow (ruff, mypy, pytest) on every push/PR.
- `.env.example` (previously the template lived in a file literally named
  `.env`, which is gitignored — cloning the repo gave you no template at all).
- `LICENSE` (MIT), `CONTRIBUTING.md`, this changelog.

### Changed
- `pyproject.toml` dependencies now match `requirements.txt` exactly (they had
  drifted — `python-dotenv` was missing from `pyproject.toml`).

## 1.0.0

Initial version: `/start`, `/help`, `/list`, and plain-text → task-append,
with `ALLOWED_USER_IDS` allowlist support (see fix above) and configurable
`OBSIDIAN_FILE`/`LOG_LEVEL`.
