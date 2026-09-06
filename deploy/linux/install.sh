#!/usr/bin/env bash
# Установка Telegram -> Obsidian Bot как systemd-сервиса (Linux Mint / любой
# дистрибутив с systemd). Скрипт идемпотентен - его можно запускать повторно
# (например, после обновления кода), он просто переустановит сервис.
#
# Использование:
#   cd deploy/linux
#   ./install.sh
#
# Что делает:
#   1. Проверяет Python 3.12+.
#   2. Создаёт venv в корне проекта и ставит зависимости из requirements.txt.
#   3. Создаёт .env из .env.example (если его ещё нет) и просит вставить токен.
#   4. Генерирует systemd unit-файл и включает автозапуск + автоперезапуск.

set -euo pipefail

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVICE_NAME="tg-obsidian-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"

echo "==> Проект: $PROJECT_DIR"

# ---------------------------------------------------------------------------
# 1. Проверка Python
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "Ошибка: python3 не найден. Установите его: sudo apt install python3 python3-venv" >&2
    exit 1
fi

PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 12 ]; }; then
    echo "Предупреждение: обнаружен Python $PY_VERSION, проекту нужен 3.12+."
    echo "Попробуйте установить: sudo apt install python3.12 python3.12-venv"
    read -r -p "Продолжить с текущей версией Python на свой риск? [y/N] " REPLY
    if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo "==> Python: $(python3 --version)"

# ---------------------------------------------------------------------------
# 2. Виртуальное окружение и зависимости
# ---------------------------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "==> Создаю виртуальное окружение: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

echo "==> Устанавливаю зависимости из requirements.txt"
"$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 3. Файл .env
# ---------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
    echo "==> Создаю .env из .env.example"
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
    chmod 600 "$ENV_FILE"

    echo
    echo "Нужен токен бота от @BotFather (формат 123456789:ABC-DEF...)."
    read -r -p "Введите TG_BOT_TOKEN (Enter - оставить пустым и заполнить .env вручную позже): " TOKEN
    if [ -n "$TOKEN" ]; then
        # Заменяем строку с примером токена на введённое значение.
        sed -i "s|^TG_BOT_TOKEN=.*|TG_BOT_TOKEN=${TOKEN}|" "$ENV_FILE"
        echo "Токен сохранён в $ENV_FILE"
    else
        echo "Не забудьте открыть $ENV_FILE и заполнить TG_BOT_TOKEN перед запуском!"
    fi
else
    echo "==> Файл .env уже существует - оставляю как есть ($ENV_FILE)"
fi

# ---------------------------------------------------------------------------
# 4. systemd-сервис
# ---------------------------------------------------------------------------
BOT_USER="${SUDO_USER:-$(id -un)}"
BOT_GROUP="$(id -gn "$BOT_USER")"

echo "==> Генерирую unit-файл для пользователя: $BOT_USER"
TMP_SERVICE_FILE="$(mktemp)"
sed \
    -e "s|__BOT_USER__|${BOT_USER}|g" \
    -e "s|__BOT_GROUP__|${BOT_GROUP}|g" \
    -e "s|__PROJECT_DIR__|${PROJECT_DIR}|g" \
    "$SCRIPT_DIR/tg-obsidian-bot.service.template" > "$TMP_SERVICE_FILE"

echo "==> Копирую сервис в $SERVICE_FILE (нужны права root)"
sudo cp "$TMP_SERVICE_FILE" "$SERVICE_FILE"
rm -f "$TMP_SERVICE_FILE"

echo "==> Включаю автозапуск и запускаю сервис"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2
echo
echo "======================================================================"
sudo systemctl status "$SERVICE_NAME" --no-pager -l || true
echo "======================================================================"
echo
echo "Готово! Бот запущен как systemd-сервис '${SERVICE_NAME}'."
echo "Он будет автоматически запускаться при загрузке системы и"
echo "перезапускаться при падении (Restart=always)."
echo
echo "Полезные команды:"
echo "  sudo systemctl status ${SERVICE_NAME}     - статус"
echo "  journalctl -u ${SERVICE_NAME} -f          - логи в реальном времени"
echo "  sudo systemctl restart ${SERVICE_NAME}    - перезапустить вручную"
echo "  sudo systemctl stop ${SERVICE_NAME}       - остановить"
echo "  ./uninstall.sh                            - полностью удалить сервис"
