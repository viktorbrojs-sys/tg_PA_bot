# Telegram → Obsidian Bot

[![CI](https://github.com/viktorbrojs-sys/tg_PA_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/viktorbrojs-sys/tg_PA_bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

Telegram-бот-секретарь поверх Obsidian-хранилища: принимает задачи текстом,
классифицирует их по разделам через ИИ, ведёт markdown-файл задач и умеет
проактивно писать сами — утренний дайджест, вечерняя рефлексия, еженедельный
обзор. Полностью рабочий и без ИИ-ключа (fallback на общий раздел).

- **Установка и деплой (Linux/Windows, автозапуск)** → `INSTALL.md`
- **Как пользоваться день в день (команды, настройка)** → `USER_GUIDE.md`
- **Архитектура, разработка, вклад в проект** → этот файл + `CONTRIBUTING.md`
- **Куда движется проект** → `NEXT_STEPS.md`

---

## Команды бота

Список команд регистрируется в Telegram через `setMyCommands` при старте —
они появятся в меню по кнопке ≡ рядом с полем ввода и во всплывающей
подсказке при наборе `/`.

Команды с обязательным параметром (`/search`, `/done`, `/plan`, `/deadline`,
`/priority`, `/setcategory`, `/contact`) можно вводить и без него — бот сам
спросит значение и подставит ваш следующий ответ.

| Команда         | Действие                                                              |
|------------------|------------------------------------------------------------------------|
| Любой текст     | ИИ классифицирует текст по разделу и добавляет `- [ ] ГГГГ-ММ-ДД ЧЧ:ММ текст [category:: Раздел]` под `## Раздел` |
| `/plan <текст>` | Разбивает одно сообщение на несколько задач, классифицирует и сохраняет каждую |
| `/list`         | Все невыполненные задачи (с разбивкой на несколько сообщений при необходимости) |
| `/list N`       | Последние N невыполненных задач                                        |
| `/search <запрос>` | Поиск по всему vault и почте (если настроен Second Brain/Gmail) или по файлу задач |
| `/contact <имя>` | Найти человека: упоминания в заметках, письма, прошлые встречи из Google Calendar |
| `/done N`       | Отмечает N-ю задачу из `/list` как выполненную (с таймстемпом завершения) |
| `/deadline N ГГГГ-ММ-ДД` | Ставит дедлайн задаче N (необязательно — не у каждой задачи он нужен); `/deadline N off` убирает |
| `/priority N <уровень>` | Ставит приоритет задаче N: слово (`критический`, `высокий`, `средний`, `низкий`, `план`, `fyi`) или цифра 0-5; `/priority N off` убирает |
| `/setcategory N <раздел>` | Меняет раздел (категорию) задачи N, например «Маркетинг»; `/setcategory N off` убирает |
| `/reindex`      | Обновить индекс vault для семантического поиска сейчас, не дожидаясь расписания |
| `/reindex_mail` | То же самое для индекса почты (только при настроенном Gmail)          |
| `/review`       | Еженедельный обзор — что выполнено за последние 7 дней                 |
| `/start`        | Приветствие + краткая инструкция                                       |
| `/help`         | Справка по командам                                                     |

### Шкала приоритетов

Совпадает с офисным задачником (числовой индекс — для быстрого ввода):

| # | Уровень | Пример ввода |
|---|---------|--------------|
| 0 | FYI | `/priority 3 fyi` или `/priority 3 0` |
| 1 | Критический | `/priority 3 критический` или `/priority 3 1` |
| 2 | Высокий | `/priority 3 высокий` или `/priority 3 2` |
| 3 | Средний | `/priority 3 средний` или `/priority 3 3` |
| 4 | Низкий | `/priority 3 низкий` или `/priority 3 4` |
| 5 | План | `/priority 3 план` или `/priority 3 5` |

Утренний дайджест выбирает «главную задачу дня» с учётом приоритета — самую
срочную (не просто первую в списке). `FYI` никогда не становится «главной».

### Формат тегов и таблица в Obsidian (Dataview)

Дедлайн, приоритет и раздел хранятся прямо в тексте задачи как
[Dataview-совместимые inline-поля](https://blacksmithgu.github.io/obsidian-dataview/annotation/add-metadata/):

```
- [ ] 2026-09-07 14:32 Сдать отчёт [due:: 2026-09-20] [priority:: 1] [category:: Работа]
```

Приоритет хранится числом (0-5, см. шкалу выше), а не словом — иначе
Dataview сортирует его по алфавиту, а не по важности. Раздел (`category`)
дублирует `## Раздел`-заголовок, под которым лежит задача, но как отдельное
поле — так его видно в табличном представлении без открытия структуры файла.

Если установить плагин [Dataview](https://github.com/blacksmithgu/obsidian-dataview),
эти теги можно вывести таблицей прямо в заметке — см. раздел про Dataview в
`USER_GUIDE.md`.

### Проактивный секретарь (опционально)

Если задан `TELEGRAM_CHAT_ID` (или в `ALLOWED_USER_IDS` указан ровно один
пользователь — тогда используется его ID), бот сам пишет по расписанию:

- **Утренний дайджест** (`MORNING_DIGEST_TIME`, по умолчанию 08:00) — сколько
  открытых задач, какие просрочены (тег `[due:: ГГГГ-ММ-ДД]` в тексте задачи),
  погода на сегодня (если настроена), встречи из Google Calendar (если
  настроен) и главная задача дня. Пробки — пока не реализовано.
- **Вечерняя рефлексия** (`EVENING_REFLECTION_TIME`, по умолчанию 21:00) —
  бот спрашивает, что сделано; ваш следующий ответ свободным текстом
  разбирается, отмечает соответствующие задачи выполненными и показывает,
  что переносится на завтра.
- **Еженедельный обзор** (`WEEKLY_REVIEW_DAY`/`WEEKLY_REVIEW_TIME`, по
  умолчанию воскресенье 20:00) — что выполнено за последние 7 дней. Задачи,
  отмеченные выполненными до появления этой функции, в обзор не попадают —
  для них нет даты завершения.
- **Подготовка к встрече** (`MEETING_BRIEF_LEAD_MINUTES`, по умолчанию за 30
  минут) — если настроен Google Calendar, бот сам присылает краткую выжимку
  по предстоящей встрече: тема, время, место, участники и что нашлось по
  этой теме в заметках (`/search` по названию встречи).

См. `.env.example` для `TIMEZONE` и настройки времени.

### Google Calendar (опционально, только чтение)

Даёт встречи в утреннем дайджесте и подготовку к встрече. Настройка:

1. Создайте OAuth-клиент в [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   — тип **TVs and Limited Input devices** (не «Web application» и не
   «Desktop app» — этот тип не требует redirect URI).
2. Включите **Google Calendar API** для проекта.
3. Запустите `python scripts/google_calendar_auth.py`, введите Client ID и
   Client Secret — скрипт откроет авторизацию через код на отдельном
   устройстве (device flow) и распечатает готовые строки для `.env`.
4. Добавьте эти строки в `.env`, перезапустите бота.

Без этой настройки бот работает как раньше — дайджест просто не упоминает
встречи. Доступ — только на чтение (`calendar.readonly`), бот никогда не
создаёт и не меняет события.

### Погода (опционально, бесплатно, без ключа)

[Open-Meteo](https://open-meteo.com/) — не требует регистрации или ключа.
Нужны только координаты:

```ini
WEATHER_LATITUDE=55.75
WEATHER_LONGITUDE=37.62
```

Без этих переменных дайджест просто не упоминает погоду.

### Second Brain: семантический поиск по всему vault (опционально)

Без настройки `/search` ищет только по файлу задач (`OBSIDIAN_FILE`) обычным
grep. С `OBSIDIAN_VAULT_PATH` бот индексирует **весь** Obsidian-vault и ищет
по смыслу, не только по точному совпадению слов.

Требуется локально запущенная [Ollama](https://ollama.com/) — эмбеддинги
считаются через неё (`/api/embed`), никаких тяжёлых Python-зависимостей
(torch и т.п.) в самом боте нет, модель живёт в Ollama:

```bash
ollama pull nomic-embed-text   # или другая embedding-модель
```

```ini
OBSIDIAN_VAULT_PATH=~/ObsidianVault
OLLAMA_BASE_URL=http://localhost:11434   # по умолчанию, можно не задавать
OLLAMA_EMBED_MODEL=nomic-embed-text      # по умолчанию, можно не задавать
```

Что это даёт:

- **`/search <запрос>`** — ищет по смыслу по всем заметкам vault, не только
  по файлу задач.
- **`/contact <имя>`** — упоминания человека в заметках (точное совпадение
  подстроки — это уже не семантический поиск, а обычный grep по всему
  vault, надёжнее для имён) + прошлые встречи с ним из Google Calendar за
  последние 90 дней, если календарь настроен.
- **Подготовка к встрече** (см. ниже) автоматически начинает искать по
  всему vault вместо одного файла задач — код не менялся, просто
  `/search`, которым она пользуется, стал умнее.

Индекс — производный артефакт (пересобирается из markdown), хранится в
`~/.tg_pa_bot/vault_index.db` (не внутри vault — чтобы не путать Obsidian
Sync/git-бэкапы бинарником, который меняется на каждой переиндексации).
Переиндексация идёт сама по расписанию (`VAULT_REINDEX_INTERVAL_MINUTES`,
по умолчанию раз в час — эмбеддится только новое/изменённое), либо вручную:
`/reindex` из Telegram или `python scripts/reindex_vault.py` из терминала.

Без `OBSIDIAN_VAULT_PATH` (или если Ollama недоступна) всё работает как
раньше — grep по файлу задач, без ошибок.

### Gmail (опционально, только чтение)

Бот никогда не отправляет, не удаляет и не меняет почту — только читает.
Отдельные креды и refresh token, не связаны с Google Calendar.

1. В том же проекте Google Cloud Console (см. настройку Calendar выше)
   создайте ещё один OAuth-клиент, но типа **Desktop app** (не «TVs and
   Limited Input devices» — Google не разрешает Gmail-scope для этого типа
   клиента). Включите Gmail API для проекта.
2. Переведите OAuth consent screen в статус **«In production»** — иначе
   refresh token живёт всего 7 дней и бот через неделю перестанет читать
   почту (для личного использования полная верификация Google не нужна,
   будет только предупреждение «app isn't verified», его можно пропустить).
3. Запустите на машине с браузером:
   ```bash
   python scripts/gmail_auth.py
   ```
   Скрипт поднимет временный локальный сервер, откроет браузер и после
   подтверждения выведет три строки для `.env`.
4. Добавьте их в `.env`:
   ```ini
   GMAIL_CLIENT_ID=...
   GMAIL_CLIENT_SECRET=...
   GMAIL_REFRESH_TOKEN=...
   ```

Что это даёт:

- **Сводка непрочитанных писем в утреннем дайджесте** — до 5 последних, с
  точным общим числом непрочитанных.
- **`/search` и `/contact`** начинают учитывать почту наравне с vault (если
  Second Brain тоже настроен) — см. разделы выше.
- Требует ту же Ollama, что и Second Brain (эмбеддинги для поиска по
  почте) — если Second Brain не настроен, а Gmail настроен, эмбеддинги всё
  равно включаются автоматически, отдельно настраивать не нужно.

Почта индексируется локально (`sqlite-vec`, файл
`~/.tg_pa_bot/mail_index.db`, отдельно от индекса vault) с retention
**180 дней** (`MAIL_INDEX_RETENTION_DAYS`) — старые письма автоматически
убираются из локального индекса (не из Gmail, сама почта не трогается).
Переиндексация — по расписанию (`MAIL_REINDEX_INTERVAL_MINUTES`, по
умолчанию раз в час) или вручную: `/reindex_mail` из Telegram.

Без `GMAIL_*` переменных всё работает как раньше — Gmail-раздел дайджеста
просто не показывается, `/search`/`/contact` не включают почту.

### ИИ-классификация (опционально)

Без `DEEPSEEK_API_KEY` бот полностью рабочий: все новые задачи попадают в
раздел `Входящие`, а `/plan` просто делит сообщение по строкам. С ключом —
задачи автоматически раскладываются по разделам из `TASK_SECTIONS`
(по умолчанию `Работа,Личное`), а `/plan` использует LLM, чтобы вычленить
отдельные задачи из свободного текста. См. `.env.example`.

---

## Установка и запуск

### Требования

- Python 3.12+
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

### 1. Получить токен бота

1. Откройте Telegram, найдите [@BotFather](https://t.me/BotFather).
2. Отправьте `/newbot` → задайте имя и username (должен заканчиваться на `bot`).
3. Скопируйте токен вида `123456789:ABCdefGHI...`.

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Создать файл `.env`

```bash
cp .env.example .env
```

Откройте `.env` в любом редакторе и заполните `TG_BOT_TOKEN` (обязательно) и,
при необходимости, остальные переменные — см. таблицу ниже.

> `.env` добавлен в `.gitignore` — токен не попадёт в репозиторий.

### 4. Запустить бота

```bash
cd bot
python main.py
```

Вывод при успешном старте:

```
2026-05-27 12:00:00  INFO  config — Config loaded: file=~/ObsidianVault/Задачи.md allowlist=disabled
2026-05-27 12:00:00  INFO  __main__ — Starting bot (long polling) | file=... | allowlist=disabled
2026-05-27 12:00:01  INFO  Application — Application started
```

Теперь напишите боту в Telegram любой текст — он появится в вашем файле задач.

---

## Настройка переменных окружения

| Переменная         | Обязательная | Описание                                                   |
|--------------------|:------------:|-------------------------------------------------------------|
| `TG_BOT_TOKEN`     | **да**       | Токен от @BotFather                                          |
| `OBSIDIAN_FILE`    | нет          | Путь к файлу задач (default: `~/ObsidianVault/Задачи.md`)    |
| `ALLOWED_USER_IDS` | нет          | Telegram user_id через запятую; пусто = доступ всем          |
| `LOG_LEVEL`        | нет          | `DEBUG` / `INFO` / `WARNING` / `ERROR` (default: `INFO`)     |
| `DEEPSEEK_API_KEY` | нет          | Ключ DeepSeek для ИИ-классификации; без него — правило-based fallback |
| `LLM_MODEL`        | нет          | Модель DeepSeek (default: `deepseek-chat`)                   |
| `TASK_SECTIONS`    | нет          | Разделы для классификации через запятую (default: `Работа,Личное`) |
| `TELEGRAM_CHAT_ID` | нет          | Чат для проактивных сообщений; авто-определяется, если в `ALLOWED_USER_IDS` один ID |
| `TIMEZONE`         | нет          | IANA-часовой пояс для расписания (default: `Europe/Moscow`)  |
| `MORNING_DIGEST_TIME` | нет       | Время утреннего дайджеста, ЧЧ:ММ (default: `08:00`)          |
| `EVENING_REFLECTION_TIME` | нет   | Время вечерней рефлексии, ЧЧ:ММ (default: `21:00`)            |
| `WEEKLY_REVIEW_DAY` | нет         | День еженедельного обзора, mon–sun (default: `sun`)           |
| `WEEKLY_REVIEW_TIME` | нет        | Время еженедельного обзора, ЧЧ:ММ (default: `20:00`)          |
| `GOOGLE_CALENDAR_CLIENT_ID` | нет  | OAuth Client ID для Google Calendar (см. `scripts/google_calendar_auth.py`) |
| `GOOGLE_CALENDAR_CLIENT_SECRET` | нет | OAuth Client Secret для Google Calendar                    |
| `GOOGLE_CALENDAR_REFRESH_TOKEN` | нет | Refresh token, полученный скриптом авторизации             |
| `GOOGLE_CALENDAR_ID` | нет         | ID календаря (default: `primary` — основной календарь)        |
| `MEETING_BRIEF_LEAD_MINUTES` | нет | За сколько минут до встречи слать подготовку (default: `30`)  |
| `WEATHER_LATITUDE` | нет         | Широта для погоды в дайджесте (Open-Meteo, без ключа)          |
| `WEATHER_LONGITUDE` | нет        | Долгота для погоды в дайджесте                                 |
| `OBSIDIAN_VAULT_PATH` | нет      | Путь к папке Obsidian-хранилища — включает Second Brain (семантический поиск по всему vault, `/contact`); директория должна существовать |
| `OLLAMA_BASE_URL`  | нет          | Адрес локальной Ollama для эмбеддингов (default: `http://localhost:11434`) |
| `OLLAMA_EMBED_MODEL` | нет        | Модель эмбеддингов в Ollama (default: `nomic-embed-text`)       |
| `VAULT_REINDEX_INTERVAL_MINUTES` | нет | Как часто переиндексировать vault в фоне (default: `60`)   |
| `VAULT_INDEX_DB_PATH` | нет      | Куда писать файл индекса vault (default: `~/.tg_pa_bot/vault_index.db`) |
| `GMAIL_CLIENT_ID`  | нет          | OAuth Client ID для Gmail, тип Desktop app (см. `scripts/gmail_auth.py`) |
| `GMAIL_CLIENT_SECRET` | нет       | OAuth Client Secret для Gmail                                  |
| `GMAIL_REFRESH_TOKEN` | нет       | Refresh token, полученный скриптом авторизации                 |
| `MAIL_INDEX_DB_PATH` | нет        | Куда писать файл индекса почты (default: `~/.tg_pa_bot/mail_index.db`) |
| `MAIL_REINDEX_INTERVAL_MINUTES` | нет | Как часто переиндексировать почту в фоне (default: `60`)   |
| `MAIL_INDEX_RETENTION_DAYS` | нет | Сколько дней почты хранить в локальном индексе (default: `180`) |

**Как узнать свой Telegram user_id:** напишите [@userinfobot](https://t.me/userinfobot) — он пришлёт ваш ID в ответ.

**Пример с ограничением доступа:**

```ini
ALLOWED_USER_IDS=123456789,987654321
```

При заданном `ALLOWED_USER_IDS` бот отвечает `⛔ У вас нет доступа к этому боту.`
любому пользователю не из списка и не обрабатывает его сообщения дальше.

---

## Автозапуск

В папке [`deploy/`](deploy/) есть готовые скрипты, которые сами ставят
зависимости, создают `.env` и настраивают автозапуск + автоперезапуск при
падении:

- **Linux (systemd)** — `deploy/linux/install.sh`
- **Windows (Планировщик заданий)** — `deploy\windows\install.bat`

Подробная пошаговая инструкция — в [INSTALL.md](INSTALL.md).

---

## Синхронизация с Obsidian

Бот пишет задачи в локальный файл. Для синхронизации на все устройства:

- **[Syncthing](https://syncthing.net/)** — бесплатно, p2p, без облака (рекомендуется)
- **Obsidian Sync** — официальное платное решение
- **iCloud / Dropbox / OneDrive** — если хранилище уже там

---

## Разработка

```bash
pip install -r requirements-dev.txt
ruff check .     # линт
mypy             # проверка типов
pytest -v        # юнит-тесты
```

Подробнее — в [CONTRIBUTING.md](CONTRIBUTING.md).

## Структура проекта

```
bot/
  main.py                          — точка входа: логирование, сборка сервисов,
                                      регистрация хендлеров, планировщик, polling
  config.py                        — загрузка и валидация конфигурации из env
  storage.py                       — async-safe чтение/запись файла задач (единая точка I/O)
  handlers.py                      — команды и обработка текстовых сообщений
  vault_scanner.py                 — сканирование vault и чанкинг markdown по заголовкам
  vault_index.py                   — VaultIndex: векторное хранилище на sqlite-vec
  mail_index.py                    — MailIndex: то же для почты (диффинг по id, не по хэшу)
  services/
    task_service.py                — классификация задач, планировщик дня, /list
    digest_service.py              — утренний дайджест (+ встречи, погода, непрочитанные письма), вечерняя рефлексия, /review
    reflection_service.py          — разбор ответа на вечернюю рефлексию
    search_service.py              — поиск: семантический по vault+почте (если настроены) или grep по файлу
    contact_service.py             — /contact: упоминания в vault, письма, прошлые встречи
    vault_indexer.py               — reindex_vault(): diff/эмбеддинг/прунинг индекса vault
    mail_indexer.py                — reindex_mail(): то же для почты, + retention-прунинг
    pending_command_state.py       — команды, ожидающие параметр следующим сообщением
    meeting_brief_service.py       — подготовка к встрече (context brief)
  integrations/
    llm_client.py                  — абстракция LLM: DeepSeekClient + NullLLMClient fallback
    google_calendar.py             — абстракция календаря: GoogleCalendarClient + NullCalendarClient
    gmail_client.py                — абстракция почты: GoogleGmailClient + NullGmailClient
    weather_client.py              — абстракция погоды: OpenMeteoClient + NullWeatherClient
    embedding_client.py            — абстракция эмбеддингов: OllamaEmbeddingClient + NullEmbeddingClient
  scheduler/
    jobs.py                        — APScheduler: дайджест/рефлексия/обзор/встречи/реиндекс vault/реиндекс почты по расписанию
scripts/
  google_calendar_auth.py          — одноразовый скрипт получения refresh token для Calendar
  gmail_auth.py                    — то же для Gmail (loopback-flow с PKCE, не device-flow)
  reindex_vault.py                 — ручной запуск полной переиндексации vault
tests/                              — 297 тестов на все модули выше
.github/workflows/ci.yml — lint + type-check + tests на каждый push/PR
requirements.txt      — рантайм-зависимости
requirements-dev.txt  — + пакеты для разработки/тестов
pyproject.toml
CHANGELOG.md
CONTRIBUTING.md
LICENSE
```

## Известные ограничения и планы

- Файл задач читается/пишется как обычный локальный файл: если вы деплоите
  бота в контейнер или облачный хостинг, файл будет жить внутри контейнера
  и не будет автоматически синхронизирован с вашим Obsidian-хранилищем на
  других устройствах — для реального использования запускайте бота локально
  и синхронизируйте файл через Syncthing/Obsidian Sync/облако.
- Нельзя запускать две копии бота с одним токеном одновременно (Telegram
  ответит `409 Conflict` на long polling).
- Утренний дайджест теперь включает встречи из Google Calendar и погоду
  (если настроены) — пробки пока не подключены (нужен платный/ключевой API).
- Подготовка к встрече ищет заметки через `/search` по названию встречи —
  семантически, если настроен `OBSIDIAN_VAULT_PATH`, иначе простым
  совпадением по подстроке.
- «Перенос на завтра» после вечерней рефлексии — информационный (бот
  показывает список оставшихся задач), без модели «дня» для каждой задачи.
- Поиск человека по имени (`/contact`) — точное совпадение подстроки, не
  морфология и не семантика (специально: для имён это надёжнее, чем
  эмбеддинги, и работает даже без настроенной Ollama).
- Семантический поиск (`/search`, Second Brain, почта) требует локально
  запущенной Ollama — без `OBSIDIAN_VAULT_PATH`/`GMAIL_*` или при
  недоступной Ollama поиск тихо откатывается на grep по файлу задач, без
  ошибок.
- Почта индексируется локально с retention 180 дней (`MAIL_INDEX_RETENTION_DAYS`) —
  `/search`/`/contact` не найдут письмо старше этого окна, даже если оно
  всё ещё есть в Gmail (сама переписка нигде не удаляется, только выпадает
  из локального поискового индекса).
- Идеи на будущее: пробки в дайджест (требует платный API), режим webhook
  для облачного деплоя.

## Стек

- **Python** 3.12
- **[python-telegram-bot](https://python-telegram-bot.org/)** 22.7 (asyncio, PTB v20+)
- **APScheduler** — планировщик проактивных сообщений и переиндексации vault/почты
- **httpx** — HTTP-клиент для DeepSeek API, Google Calendar, Gmail, Ollama
- **[sqlite-vec](https://github.com/asg017/sqlite-vec)** — векторное хранилище для Second Brain и поиска по почте, без внешнего сервиса
- **[Ollama](https://ollama.com/)** (опционально, вне процесса бота) — локальные эмбеддинги для семантического поиска
- Long polling — не нужен внешний IP или домен
