"""Read-only Gmail access.

Same pattern as ``google_calendar.py``: an abstraction (``GmailClient``) with
a no-op fallback (``NullGmailClient``) so the bot works fine without Gmail
configured — the digest just won't have a mail section and the mail index
stays empty.

Auth uses a long-lived refresh token obtained once via
``scripts/gmail_auth.py`` (loopback flow, Desktop-app OAuth client). Scope is
``gmail.readonly`` only — the bot never modifies, sends or deletes mail.

The API is split in two steps on purpose: listing ids is cheap (one request
per 100 messages), fetching a message with its body is one request each.
The mail indexer (block D) diffs ids against what it already has and only
fetches the new ones, so a re-run doesn't re-download the whole inbox.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"

LIST_PAGE_SIZE = 100  # Gmail API maximum for messages.list
DEFAULT_MAX_MESSAGES = 5000  # safety cap for one listing, not a product limit
MAX_BODY_CHARS = 8000  # enough for embedding/search; keeps the index small
FETCH_CONCURRENCY = 5
TOKEN_EXPIRY_MARGIN_SECONDS = 60


@dataclass(frozen=True)
class MailMessage:
    id: str
    thread_id: str
    sender: str  # raw ``From`` header, e.g. "Иван <ivan@example.com>"
    sender_name: str  # display name, "" if the header has none
    sender_email: str  # lowercased address, "" if unparseable
    subject: str
    date: datetime  # timezone-aware
    snippet: str  # Gmail's own short preview
    body: str  # plain text, truncated to MAX_BODY_CHARS; "" if none found
    # Gmail labels are kept (INBOX, UNREAD, IMPORTANT, CATEGORY_PROMOTIONS...)
    # so noise like promotions can be filtered later without reindexing.
    labels: tuple[str, ...] = ()

    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.labels


class GmailClient(Protocol):
    async def list_unread(
        self, limit: int = 10, important_only: bool = False
    ) -> list[MailMessage]:
        """Newest unread inbox messages (for the morning digest)."""
        ...

    async def list_ids_since(
        self, since: datetime, max_messages: int = DEFAULT_MAX_MESSAGES
    ) -> list[str]:
        """Ids of inbox messages received after ``since``, newest first.

        Spam and trash are excluded (Gmail's default for ``messages.list``).
        """
        ...

    async def get_messages(self, ids: list[str]) -> list[MailMessage]:
        """Fetch full messages by id. Ids that fail to load are skipped."""
        ...


class NullGmailClient:
    """Fallback used when Gmail isn't configured — never any mail."""

    async def list_unread(
        self, limit: int = 10, important_only: bool = False
    ) -> list[MailMessage]:
        return []

    async def list_ids_since(
        self, since: datetime, max_messages: int = DEFAULT_MAX_MESSAGES
    ) -> list[str]:
        return []

    async def get_messages(self, ids: list[str]) -> list[MailMessage]:
        return []


class GoogleGmailClient:
    """Read-only client for one Gmail mailbox via the REST API (no SDK)."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0

    async def _get_access_token(self) -> str | None:
        # Cached: a first indexing run makes hundreds of calls in a row.
        if self._access_token and time.monotonic() < self._access_token_expires_at:
            return self._access_token

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    TOKEN_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": self._refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                token = str(payload["access_token"])
                expires_in = float(payload.get("expires_in", 3600))
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Gmail token refresh failed: %s", exc)
                return None

        self._access_token = token
        self._access_token_expires_at = (
            time.monotonic() + expires_in - TOKEN_EXPIRY_MARGIN_SECONDS
        )
        return token

    async def list_unread(
        self, limit: int = 10, important_only: bool = False
    ) -> list[MailMessage]:
        query = "in:inbox is:unread"
        if important_only:
            query += " is:important"
        ids = await self._list_ids(query, limit)
        return await self.get_messages(ids)

    async def list_ids_since(
        self, since: datetime, max_messages: int = DEFAULT_MAX_MESSAGES
    ) -> list[str]:
        # ``after:`` accepts epoch seconds, which avoids timezone ambiguity.
        query = f"in:inbox after:{int(since.timestamp())}"
        return await self._list_ids(query, max_messages)

    async def _list_ids(self, query: str, limit: int) -> list[str]:
        token = await self._get_access_token()
        if token is None or limit <= 0:
            return []

        ids: list[str] = []
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            while len(ids) < limit:
                params: dict[str, str | int] = {
                    "q": query,
                    "maxResults": min(LIST_PAGE_SIZE, limit - len(ids)),
                }
                if page_token:
                    params["pageToken"] = page_token
                try:
                    resp = await client.get(
                        MESSAGES_URL,
                        params=params,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("Gmail list failed: %s", exc)
                    break  # keep what we already have rather than drop it

                ids.extend(str(m["id"]) for m in data.get("messages", []) if m.get("id"))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return ids[:limit]

    async def get_messages(self, ids: list[str]) -> list[MailMessage]:
        token = await self._get_access_token()
        if token is None or not ids:
            return []

        semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
        async with httpx.AsyncClient(timeout=15.0) as client:

            async def fetch(message_id: str) -> MailMessage | None:
                async with semaphore:
                    try:
                        resp = await client.get(
                            f"{MESSAGES_URL}/{message_id}",
                            params={"format": "full"},
                            headers={"Authorization": f"Bearer {token}"},
                        )
                        resp.raise_for_status()
                        return _parse_message(resp.json())
                    except (httpx.HTTPError, ValueError) as exc:
                        logger.warning("Gmail message %s fetch failed: %s", message_id, exc)
                        return None

            results = await asyncio.gather(*(fetch(i) for i in ids))
        return [m for m in results if m is not None]  # order of ``ids`` is preserved


def _parse_message(item: dict[str, Any]) -> MailMessage | None:
    message_id = item.get("id")
    if not message_id:
        return None

    payload = item.get("payload") or {}
    headers = {
        str(h.get("name", "")).lower(): str(h.get("value", ""))
        for h in payload.get("headers", [])
    }

    sender = headers.get("from", "")
    name, email = parseaddr(sender)

    return MailMessage(
        id=str(message_id),
        thread_id=str(item.get("threadId", "")),
        sender=sender,
        sender_name=name,
        sender_email=email.lower(),
        subject=headers.get("subject") or "(без темы)",
        date=_parse_date(item.get("internalDate")),
        snippet=str(item.get("snippet", "")),
        body=_extract_body(payload)[:MAX_BODY_CHARS],
        labels=tuple(str(label) for label in item.get("labelIds", [])),
    )


def _parse_date(internal_date: Any) -> datetime:
    # ``internalDate`` (epoch ms, when Gmail received the message) is used
    # instead of the ``Date`` header: the header is sender-controlled, often
    # malformed, and can lie about the time.
    try:
        return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return datetime.fromtimestamp(0, tz=UTC)


def _extract_body(payload: dict[str, Any]) -> str:
    """Plain text of a message; prefers text/plain, falls back to stripped HTML."""
    plain: list[str] = []
    html: list[str] = []
    _collect_parts(payload, plain, html)

    if plain:
        return "\n".join(plain).strip()
    if html:
        return _html_to_text("\n".join(html))
    return ""


def _collect_parts(part: dict[str, Any], plain: list[str], html: list[str]) -> None:
    # Attachments carry a filename (their data is skipped, not indexed).
    if part.get("filename"):
        return

    mime = part.get("mimeType", "")
    data = (part.get("body") or {}).get("data")
    if data and mime in ("text/plain", "text/html"):
        text = _decode_base64url(data)
        (plain if mime == "text/plain" else html).append(text)

    for sub in part.get("parts", []):
        _collect_parts(sub, plain, html)


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except ValueError:
        return ""


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "head"}
    _BREAK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAK:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self._chunks).splitlines())
        return "\n".join(line for line in lines if line)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed HTML must never break indexing
        logger.warning("Could not parse HTML mail body")
    return parser.text()
