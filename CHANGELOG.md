# Changelog

## 1.7.0 — weather in the morning digest (Open-Meteo, no key)

### Added
- **`integrations/weather_client.py`** — `WeatherClient` abstraction,
  `OpenMeteoClient` (free, keyless forecast API) and `NullWeatherClient`
  fallback, same pattern as the other integrations.
- **Утренний дайджест** теперь показывает погоду на сегодня (краткое
  описание, диапазон температур), если координаты настроены — раздел просто
  не появляется без них. При вероятности осадков ≥40% дайджест подсказывает
  взять зонт.
- Конфиг: `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, свойство
  `BotConfig.has_weather` (обе координаты обязательны вместе).
- `README.md`/`USER_GUIDE.md`/`.env.example` — раздел настройки погоды (где
  взять координаты).
- 15 новых тестов (парсинг прогноза, мок HTTP, интеграция в дайджест,
  резолвер координат); итого 108, ruff+mypy чистые.

## 1.6.0 — Google Calendar (read-only): events in digest, meeting prep

### Added
- **`integrations/google_calendar.py`** — `CalendarClient` abstraction,
  `GoogleCalendarClient` (raw REST API via httpx, no SDK dependency;
  refresh-token auth, read-only `calendar.readonly` scope) and
  `NullCalendarClient` fallback so the bot works exactly as before without
  Google Calendar configured.
- **Утренний дайджест** теперь показывает сегодняшние встречи, если
  календарь настроен — раздел просто не появляется без него.
- **`services/meeting_brief_service.py`** — `MeetingBriefService` +
  `MeetingBriefState`: за `MEETING_BRIEF_LEAD_MINUTES` минут (по умолчанию
  30) до события бот присылает тему, время, место, участников и что
  нашлось по теме встречи через `SearchService`. Каждое событие брифуется
  ровно один раз (трекинг в памяти, без дублей при повторном опросе).
- Планировщик: новая периодическая задача (каждые 5 минут) опроса
  предстоящих встреч — добавляется только если календарь настроен.
- **`scripts/google_calendar_auth.py`** — одноразовый скрипт для
  пользователя: OAuth Device Flow (без браузерного redirect), печатает
  готовые строки `GOOGLE_CALENDAR_*` для `.env`.
- Конфиг: `GOOGLE_CALENDAR_CLIENT_ID/SECRET/REFRESH_TOKEN/ID`,
  `MEETING_BRIEF_LEAD_MINUTES`, свойство `BotConfig.has_calendar`.
- `README.md`/`USER_GUIDE.md`/`.env.example` — раздел настройки Google
  Calendar (создание OAuth-клиента, запуск скрипта авторизации).
- 22 новых теста (парсинг событий календаря, мок HTTP для токена/событий,
  `MeetingBriefService`, интеграция в дайджест, резолверы конфига); итого
  93, ruff+mypy чистые.

## 1.5.1 — user guide, docs refresh

### Added
- **`USER_GUIDE.md`** — пользовательская инструкция по повседневному
  использованию: первый запуск и опциональные настройки (ИИ-ключ,
  проактивные сообщения), все команды с примерами, объяснение утреннего
  дайджеста/вечерней рефлексии/еженедельного обзора, частые ситуации.

### Changed
- `README.md` — обновлено вступление (бот давно не просто «добавляет задачи
  в Obsidian», это секретарь с ИИ-классификацией и проактивными
  сообщениями), добавлены ссылки на `USER_GUIDE.md`/`INSTALL.md`/`NEXT_STEPS.md`.
- `INSTALL.md` — добавлена ссылка на `USER_GUIDE.md` для настройки
  опциональных функций после установки.
- `CONTRIBUTING.md` → «Code style» — переписан под актуальную слоистую
  архитектуру (`handlers` → `services` → `integrations`/`scheduler` →
  `storage`), включая принцип инжектируемых часов и правило «фича = тесты +
  CHANGELOG + README/USER_GUIDE в одном коммите». Старое описание
  ссылалось на архитектуру версии 1.0, где вся логика была в `storage.py`.

## 1.5.0 — completion timestamps, weekly review, simplified carry-over

### Added
- **Таймстемп выполнения задачи**: `/done` теперь дописывает
  `✅ ГГГГ-ММ-ДД ЧЧ:ММ` к строке при отметке задачи выполненной. Без этого
  нельзя было сказать, что вообще значит «сделано за неделю».
- **Еженедельный обзор**: по расписанию (`WEEKLY_REVIEW_DAY`/`WEEKLY_REVIEW_TIME`,
  по умолчанию воскресенье 20:00) бот присылает список задач, выполненных за
  последние 7 дней. Задачи, отмеченные выполненными до этого обновления (без
  таймстемпа), в обзор не попадают — честно, так как для них нет даты
  завершения. Доступен и вручную — команда `/review`.
- **Упрощённый перенос на завтра**: в конце вечерней рефлексии бот явно
  показывает список задач, которые остаются открытыми («🔁 Переносится на
  завтра») — без изменения структуры хранения (это по-прежнему открытые
  задачи, просто теперь видно, что именно "переносится").
- `TaskStore.list_completed_since(since)` / `TaskService.list_completed_since`.
- `DigestService` теперь принимает единый инжектируемый `now: () -> datetime`
  (раньше было отдельно `today: () -> date`) — используется и для дедлайнов,
  и для окна еженедельного обзора.
- Конфиг: `WEEKLY_REVIEW_DAY`, `WEEKLY_REVIEW_TIME`.
- 17 новых/обновлённых тестов; итого 71, ruff+mypy чистые.

## 1.4.2 — prompted command parameters

### Added
- **`/search`, `/done`, `/plan` без параметра теперь не просто показывают
  подсказку по использованию, а спрашивают значение** и ждут его следующим
  сообщением — вместо того чтобы заново вводить всю команду с аргументом.
- Новый `services/pending_command_state.py` (`PendingCommandState`) —
  отслеживает, какая команда ждёт параметр от конкретного чата; выполнение
  команды вынесено в переиспользуемые функции (`_run_search`, `_run_done`,
  `_run_plan`), вызываемые и при инлайн-аргументе, и при follow-up сообщении.
- Любой новый вызов команды сбрасывает предыдущий незавершённый запрос
  параметра (нет риска, что случайный текст после незавершённого `/search`
  улетит не туда).
- 9 новых тестов; итого 63, ruff+mypy чистые.

## 1.4.1 — Telegram commands menu

### Added
- Список команд (`/list`, `/plan`, `/search`, `/done`, `/help`) регистрируется
  через `bot.set_my_commands()` при старте — теперь они появляются как меню
  по кнопке ≡ рядом с полем ввода и во всплывающей подсказке при вводе `/`.
- `handlers.BOT_COMMANDS` — единый источник списка команд с описаниями.
- Тест на соответствие ограничениям Telegram (длина имени/описания, только
  `a-z0-9_`, отсутствие дублей).

## 1.4.0 — scheduler, morning digest, evening reflection, deadline reminders, search

### Added
- **Планировщик** (`scheduler/jobs.py`, APScheduler): проактивные сообщения
  по расписанию, независимо от входящих апдейтов Telegram.
- **Утренний дайджест**: в настроенное время (`MORNING_DIGEST_TIME`, по
  умолчанию 08:00) бот сам присылает сводку — сколько открытых задач,
  какие просрочены (по тегу `@ГГГГ-ММ-ДД` в тексте задачи) и что главное на
  сегодня. Календарь/погода/пробки — в будущих итерациях, сейчас дайджест
  строится только по задачам из Obsidian.
- **Вечерняя рефлексия**: в `EVENING_REFLECTION_TIME` (по умолчанию 21:00)
  бот присылает список открытых задач и спрашивает, что сделано. Следующий
  свободный текст от пользователя разбирается (через LLM или по ключевым
  словам без него) и отмечает соответствующие задачи как выполненные.
- **`/search <запрос>`** — быстрый поиск по всему файлу задач/заметок
  (подстрока по всем строкам, не только по задачам), с кратким ответом от
  LLM поверх найденных строк (или списком строк без LLM). Семантический
  поиск (embeddings) — отдельная будущая фаза.
- `TaskStore.read_all_lines()` — доступ к сырому содержимому файла для поиска.
- Новые сервисы: `services/digest_service.py`, `services/reflection_service.py`,
  `services/search_service.py`.
- `LLMClient` пополнился методами `match_completed_tasks` и `summarize_search`
  (у обоих есть fallback без LLM-ключа).
- Конфиг: `TELEGRAM_CHAT_ID` (с удобным дефолтом — если в `ALLOWED_USER_IDS`
  ровно один ID, он же используется как chat_id для проактивных сообщений),
  `TIMEZONE`, `MORNING_DIGEST_TIME`, `EVENING_REFLECTION_TIME`.
- 23 новых теста (дайджест, рефлексия, поиск, новые резолверы конфига,
  парсинг времени планировщика); итого 53, ruff+mypy чистые.

## 1.3.0 — sections, AI classification, day planner, full task list

### Added
- **Полный список задач**: `/list` теперь по умолчанию показывает все открытые
  задачи (а не последние 20), с автоматической разбивкой на несколько
  сообщений, если список не влезает в лимит Telegram. `/list N` по-прежнему
  показывает только последние N задач.
- **Умная классификация задач**: любой обычный текст теперь классифицируется
  через LLM (DeepSeek) по разделам (`TASK_SECTIONS`, по умолчанию
  `Работа,Личное`) и добавляется под соответствующий `## Раздел` в файле.
  Без настроенного `DEEPSEEK_API_KEY` всё падает в раздел `Входящие` — бот
  остаётся полностью рабочим и без ИИ.
- **`/plan <текст>`** — разбивает одно сообщение на несколько задач (через
  LLM или построчно как fallback), классифицирует и сохраняет каждую.
- Новый слой `services/task_service.py`: вся бизнес-логика задач вынесена из
  хендлеров, чтобы классификация и планирование дня тестировались без
  Telegram.
- Новый слой `integrations/llm_client.py`: абстракция `LLMClient` +
  `DeepSeekClient` + `NullLLMClient` (заглушка на случай отсутствия ключа).
- `storage.TaskStore.add_task` умеет писать в конкретный `## Раздел`
  (создавая заголовок при необходимости), сохраняя старое плоское поведение,
  если раздел не передан.
- Конфиг: `DEEPSEEK_API_KEY`, `LLM_MODEL`, `TASK_SECTIONS`.
- Тесты на новую секционную логику storage, `LLMClient` (включая fallback на
  ошибках HTTP/JSON) и `TaskService`.

## 1.2.0 — add timestamps to tasks

### Added
- Every task added via plain text now gets a `ГГГГ-ММ-ДД ЧЧ:ММ` timestamp
  prefix, e.g. `- [ ] 2026-09-07 14:32 Купить молоко`. Implemented in
  `TaskStore._add_task_sync` with an injectable clock (`now` constructor
  param) so it stays unit-testable without mocking `datetime` globally.
- Updated/extended `storage.py` tests to assert on the new format.

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
