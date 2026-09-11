# Contributing

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env  # fill in TG_BOT_TOKEN for manual testing
```

## Before opening a PR

```bash
ruff check .        # lint
mypy                # type-check
pytest -v           # unit tests
```

All three run in CI on every push and pull request; a red CI run will block merging.

## Code style

- Python 3.12, type hints everywhere, `from __future__ import annotations`.
- Layered architecture — respect it when adding features:
  - `bot/handlers.py` — thin Telegram glue only: parse the update, call a
    service, format the reply. No business logic here.
  - `bot/services/*.py` — business logic, Telegram-free, unit-tested without
    python-telegram-bot (`task_service`, `digest_service`,
    `reflection_service`, `search_service`, `pending_command_state`).
  - `bot/integrations/*.py` — external providers behind an abstraction
    (`llm_client.LLMClient`), with a no-op fallback (`NullLLMClient`) so the
    bot stays fully functional without the optional API key configured.
  - `bot/scheduler/jobs.py` — cron-style proactive messaging (APScheduler),
    kept separate from Telegram update handling since it's time-triggered.
  - `bot/storage.py` — the only place that touches the tasks file directly.
- Blocking file I/O belongs in `bot/storage.py` behind `asyncio.to_thread`,
  never directly inside a handler or service coroutine.
- Inject the clock (`now: Callable[[], datetime] = datetime.now`, or similar)
  wherever timing matters, instead of calling `datetime.now()`/`date.today()`
  directly — that's what makes `storage`/`digest_service` tests deterministic.
- No `assert` for input validation that can fail in production (asserts are
  removed when Python runs with `-O`) — use explicit `if` checks instead.
- New user-facing behaviour needs: tests, a `CHANGELOG.md` entry, and a
  `README.md`/`USER_GUIDE.md` update in the same commit/PR — don't let docs
  drift from what the code actually does.

## Commit messages

Conventional, short, imperative: `fix: stop access guard from leaking`,
`feat: add /done command`.
