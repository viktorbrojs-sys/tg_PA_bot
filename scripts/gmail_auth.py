#!/usr/bin/env python3
"""Одноразовая настройка: получить refresh token для Gmail (только чтение).

Почему не device flow, как у Google Calendar: Google не разрешает scope
Gmail в «TVs and Limited Input devices» — запрос упадёт с invalid_scope.
Поэтому здесь loopback-flow для клиента типа «Desktop app»: скрипт
поднимает временный сервер на 127.0.0.1, открывает браузер, ловит код
авторизации и обменивает его на токен (с PKCE).

Запускайте на машине с браузером (не обязательно там, где крутится бот).
Как создать OAuth-клиент — см. USER_GUIDE.md → «Gmail».

Использование:
    python scripts/gmail_auth.py

Перед запуском: в Google Cloud Console → OAuth consent screen переведите
приложение в статус «In production». Пока приложение в «Testing»,
refresh token живёт всего 7 дней и бот через неделю перестанет читать почту.
(Для личного использования проверка Google не нужна — будет только
предупреждение «app isn't verified», его можно пропустить.)
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
WAIT_SECONDS = 300


def _make_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, str] = {}
    done = threading.Event()

    def do_GET(self) -> None:  # noqa: N802 (имя задано http.server)
        params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if "code" in params or "error" in params:
            type(self).result = params
            type(self).done.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Готово, можно закрыть вкладку и вернуться в терминал.".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # не шумим в терминале


def main() -> None:
    client_id = input("Gmail OAuth Client ID (тип Desktop app): ").strip()
    client_secret = input("Gmail OAuth Client Secret: ").strip()

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    verifier, challenge = _make_pkce()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # гарантирует выдачу refresh_token
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    print()
    print("Открываю браузер. Если не открылся — перейдите по ссылке вручную:")
    print(url)
    print()
    webbrowser.open(url)
    print("Ожидание подтверждения...")

    got_answer = _CallbackHandler.done.wait(timeout=WAIT_SECONDS)
    server.shutdown()
    if not got_answer:
        print("Время ожидания истекло, запустите скрипт заново.", file=sys.stderr)
        sys.exit(1)

    params = _CallbackHandler.result
    if "error" in params:
        print(f"Google вернул ошибку: {params['error']}", file=sys.stderr)
        sys.exit(1)
    if params.get("state") != state:
        print("Неверный state в ответе — прерываю из соображений безопасности.", file=sys.stderr)
        sys.exit(1)

    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": params["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15.0,
    )
    payload = resp.json()
    if "refresh_token" not in payload:
        print(f"Не удалось получить refresh token: {payload}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Готово! Добавьте эти строки в .env:")
    print()
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={payload['refresh_token']}")


if __name__ == "__main__":
    main()
