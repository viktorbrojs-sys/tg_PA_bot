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
- Blocking file I/O belongs in `bot/storage.py` behind `asyncio.to_thread`,
  never directly inside a handler coroutine.
- Handlers stay thin: parse input, call `storage`/`config`, format a reply.
  Business logic (parsing the tasks file, marking tasks done, etc.) belongs
  in `storage.py` so it can be unit-tested without a Telegram connection.
- No `assert` for input validation that can fail in production (asserts are
  removed when Python runs with `-O`) — use explicit `if` checks instead.

## Commit messages

Conventional, short, imperative: `fix: stop access guard from leaking`,
`feat: add /done command`.
