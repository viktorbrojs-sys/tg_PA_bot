# Telegram → Obsidian Bot

[![CI](https://github.com/viktorbrojs-sys/tg_PA_bot/actions/workflows/ci.yml/badge.svg)](https://github.com/viktorbrojs-sys/tg_PA_bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

Telegram-бот для добавления задач прямо в Obsidian-хранилище.
Напишите боту любой текст — задача сразу появится в вашем markdown-файле как
`- [ ] ГГГГ-ММ-ДД ЧЧ:ММ Текст` (дата и время добавления проставляются автоматически).

---

## Команды бота

| Команда     | Действие                                            |
|-------------|------------------------------------------------------|
| Любой текст | Добавляет `- [ ] ГГГГ-ММ-ДД ЧЧ:ММ текст` в файл задач |
| `/list`     | Последние 20 невыполненных задач                     |
| `/done N`   | Отмечает N-ю задачу из `/list` как выполненную        |
| `/start`    | Приветствие + краткая инструкция                      |
| `/help`     | Справка по командам                                   |

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
  main.py        — точка входа: логирование, регистрация хендлеров, polling
  config.py      — загрузка и валидация конфигурации из env
  storage.py     — async-safe чтение/запись файла задач (единая точка I/O)
  handlers.py    — /start, /help, /list, /done и обработка текстовых сообщений
tests/
  test_config.py
  test_storage.py
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
- Идеи на будущее: `/list all` (включая выполненные), маршрутизация задач по
  ключевому префиксу в разные файлы (`работа: ...` → `Работа.md`),
  автоматическая дата добавления, режим webhook для облачного деплоя.

## Стек

- **Python** 3.12
- **[python-telegram-bot](https://python-telegram-bot.org/)** 22.7 (asyncio, PTB v20+)
- Long polling — не нужен внешний IP или домен
