#!/usr/bin/env python3
"""Одноразовая настройка: получить refresh token для Google Calendar.

Запустите этот скрипт один раз (на любой машине с браузером под рукой — ему
нужен только ваш Google-аккаунт, а не сервер, где крутится бот). Как создать
OAuth-клиент в Google Cloud Console — см. USER_GUIDE.md → «Google Calendar».

Использование:
    python scripts/google_calendar_auth.py

Скрипт распечатает ссылку и код: откройте ссылку в любом браузере, введите
код, разрешите доступ (только чтение календаря). После подтверждения выведет
готовые строки для .env.
"""

from __future__ import annotations

import sys
import time

import httpx

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def main() -> None:
    client_id = input("Google OAuth Client ID: ").strip()
    client_secret = input("Google OAuth Client Secret: ").strip()

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(DEVICE_CODE_URL, data={"client_id": client_id, "scope": SCOPE})
        resp.raise_for_status()
        device = resp.json()

        print()
        print(f"1. Откройте: {device['verification_url']}")
        print(f"2. Введите код: {device['user_code']}")
        print("3. Разрешите доступ (только чтение календаря) своему Google-аккаунту.")
        print()
        print("Ожидание подтверждения...")

        interval = device.get("interval", 5)
        deadline = time.monotonic() + device.get("expires_in", 1800)

        while time.monotonic() < deadline:
            time.sleep(interval)
            token_resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "device_code": device["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            payload = token_resp.json()

            if "refresh_token" in payload:
                print()
                print("Готово! Добавьте эти строки в .env:")
                print()
                print(f"GOOGLE_CALENDAR_CLIENT_ID={client_id}")
                print(f"GOOGLE_CALENDAR_CLIENT_SECRET={client_secret}")
                print(f"GOOGLE_CALENDAR_REFRESH_TOKEN={payload['refresh_token']}")
                return

            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue

            print(f"Ошибка авторизации: {payload}", file=sys.stderr)
            sys.exit(1)

        print("Время ожидания истекло, запустите скрипт заново.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
