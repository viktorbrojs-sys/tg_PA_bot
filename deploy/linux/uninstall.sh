#!/usr/bin/env bash
# Останавливает и полностью удаляет systemd-сервис бота.
# Файлы проекта (.env, venv, код) не трогает.

set -euo pipefail

SERVICE_NAME="tg-obsidian-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    echo "==> Останавливаю и отключаю сервис"
    sudo systemctl stop "$SERVICE_NAME" || true
    sudo systemctl disable "$SERVICE_NAME" || true
fi

if [ -f "$SERVICE_FILE" ]; then
    echo "==> Удаляю $SERVICE_FILE"
    sudo rm -f "$SERVICE_FILE"
fi

sudo systemctl daemon-reload
sudo systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true

echo "Сервис '${SERVICE_NAME}' удалён. Код проекта и .env не тронуты."
