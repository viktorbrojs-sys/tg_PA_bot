import base64
from datetime import UTC, datetime

import httpx
import pytest
from integrations.gmail_client import (
    MAX_BODY_CHARS,
    GoogleGmailClient,
    NullGmailClient,
    _extract_body,
    _html_to_text,
    _parse_message,
)

SINCE = datetime(2026, 3, 25, 0, 0, tzinfo=UTC)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _message(
    message_id: str = "m1",
    *,
    sender: str = "Иван Иванов <Ivan@Example.com>",
    subject: str = "Счёт на оплату",
    body_parts: list[dict] | None = None,
    labels: list[str] | None = None,
) -> dict:
    parts = body_parts if body_parts is not None else [
        {"mimeType": "text/plain", "body": {"data": _b64("Добрый день!")}}
    ]
    return {
        "id": message_id,
        "threadId": "t1",
        "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        "snippet": "Добрый день",
        "internalDate": "1790000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
            ],
            "parts": parts,
        },
    }


# ── Null client ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_null_gmail_client_returns_nothing():
    client = NullGmailClient()
    assert await client.list_unread() == []
    assert await client.list_ids_since(SINCE) == []
    assert await client.get_messages(["a"]) == []


# ── Parsing ─────────────────────────────────────────────────────────────────


def test_parse_message_extracts_fields():
    msg = _parse_message(_message())
    assert msg is not None
    assert msg.id == "m1"
    assert msg.thread_id == "t1"
    assert msg.sender_name == "Иван Иванов"
    assert msg.sender_email == "ivan@example.com"  # lowercased
    assert msg.subject == "Счёт на оплату"
    assert msg.body == "Добрый день!"
    assert msg.labels == ("INBOX", "UNREAD")
    assert msg.is_unread is True
    assert msg.date.tzinfo is not None
    assert msg.date.year == 2026


def test_parse_message_defaults_missing_subject_and_sender():
    item = _message()
    item["payload"]["headers"] = []
    msg = _parse_message(item)
    assert msg is not None
    assert msg.subject == "(без темы)"
    assert msg.sender == ""
    assert msg.sender_email == ""


def test_parse_message_without_id_is_none():
    assert _parse_message({"payload": {}}) is None


def test_parse_message_read_message_is_not_unread():
    msg = _parse_message(_message(labels=["INBOX"]))
    assert msg is not None
    assert msg.is_unread is False


def test_parse_message_survives_bad_internal_date():
    item = _message()
    item["internalDate"] = "not-a-number"
    msg = _parse_message(item)
    assert msg is not None
    assert msg.date == datetime.fromtimestamp(0, tz=UTC)


def test_parse_message_truncates_long_body():
    long_text = "а" * (MAX_BODY_CHARS + 500)
    msg = _parse_message(
        _message(body_parts=[{"mimeType": "text/plain", "body": {"data": _b64(long_text)}}])
    )
    assert msg is not None
    assert len(msg.body) == MAX_BODY_CHARS


def test_extract_body_prefers_plain_over_html():
    payload = {
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("plain text")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>html text</p>")}},
        ]
    }
    assert _extract_body(payload) == "plain text"


def test_extract_body_falls_back_to_stripped_html():
    payload = {
        "mimeType": "text/html",
        "body": {"data": _b64("<style>p{}</style><p>Привет</p><p>мир &amp; всем</p>")},
    }
    assert _extract_body(payload) == "Привет\nмир & всем"


def test_extract_body_walks_nested_multipart():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [{"mimeType": "text/plain", "body": {"data": _b64("вложенный")}}],
            }
        ],
    }
    assert _extract_body(payload) == "вложенный"


def test_extract_body_skips_attachments():
    payload = {
        "parts": [
            {
                "mimeType": "text/plain",
                "filename": "notes.txt",
                "body": {"data": _b64("attachment content")},
            }
        ]
    }
    assert _extract_body(payload) == ""


def test_extract_body_empty_when_no_text():
    assert _extract_body({"mimeType": "image/png", "body": {"attachmentId": "x"}}) == ""


def test_html_to_text_drops_script_and_collapses_whitespace():
    html = "<html><head><title>t</title></head><body><script>x()</script>a   b<br>c</body></html>"
    assert _html_to_text(html) == "a b\nc"


# ── Google client ───────────────────────────────────────────────────────────


def _install_fake_api(monkeypatch, *, list_pages=None, messages=None, fail_ids=()):
    """Patch httpx so token/list/get calls are answered locally.

    Returns a dict recording calls, so tests can assert on query params.
    """
    calls: dict = {"token": 0, "list_params": [], "get_ids": []}
    list_pages = list(list_pages or [])
    messages = messages or {}

    async def fake_post(self, url, headers=None, data=None, json=None):  # noqa: ARG001
        calls["token"] += 1
        request = httpx.Request("POST", url)
        return httpx.Response(
            200, json={"access_token": "fake-token", "expires_in": 3600}, request=request
        )

    async def fake_get(self, url, params=None, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        if url.endswith("/messages"):
            calls["list_params"].append(dict(params or {}))
            return httpx.Response(200, json=list_pages.pop(0), request=request)
        message_id = url.rsplit("/", 1)[1]
        calls["get_ids"].append(message_id)
        if message_id in fail_ids:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json=messages[message_id], request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    return calls


@pytest.mark.asyncio
async def test_list_unread_builds_query_and_fetches_messages(monkeypatch):
    calls = _install_fake_api(
        monkeypatch,
        list_pages=[{"messages": [{"id": "m1"}, {"id": "m2"}]}],
        messages={"m1": _message("m1"), "m2": _message("m2", subject="Второе")},
    )
    client = GoogleGmailClient("id", "secret", "refresh")

    result = await client.list_unread(limit=5)

    assert [m.id for m in result] == ["m1", "m2"]
    assert calls["list_params"][0]["q"] == "in:inbox is:unread"
    assert calls["list_params"][0]["maxResults"] == 5


@pytest.mark.asyncio
async def test_list_unread_important_only_adds_filter(monkeypatch):
    calls = _install_fake_api(monkeypatch, list_pages=[{}])
    client = GoogleGmailClient("id", "secret", "refresh")

    assert await client.list_unread(important_only=True) == []
    assert calls["list_params"][0]["q"] == "in:inbox is:unread is:important"


@pytest.mark.asyncio
async def test_list_ids_since_uses_epoch_and_paginates(monkeypatch):
    calls = _install_fake_api(
        monkeypatch,
        list_pages=[
            {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p2"},
            {"messages": [{"id": "c"}]},
        ],
    )
    client = GoogleGmailClient("id", "secret", "refresh")

    ids = await client.list_ids_since(SINCE)

    assert ids == ["a", "b", "c"]
    assert calls["list_params"][0]["q"] == f"in:inbox after:{int(SINCE.timestamp())}"
    assert "pageToken" not in calls["list_params"][0]
    assert calls["list_params"][1]["pageToken"] == "p2"


@pytest.mark.asyncio
async def test_list_ids_since_respects_max_messages(monkeypatch):
    calls = _install_fake_api(
        monkeypatch,
        list_pages=[{"messages": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "nextPageToken": "p2"}],
    )
    client = GoogleGmailClient("id", "secret", "refresh")

    ids = await client.list_ids_since(SINCE, max_messages=2)

    assert ids == ["a", "b"]
    assert len(calls["list_params"]) == 1  # limit reached, no second page
    assert calls["list_params"][0]["maxResults"] == 2


@pytest.mark.asyncio
async def test_get_messages_skips_failed_ids_and_keeps_order(monkeypatch):
    _install_fake_api(
        monkeypatch,
        messages={"m1": _message("m1"), "m3": _message("m3")},
        fail_ids={"m2"},
    )
    client = GoogleGmailClient("id", "secret", "refresh")

    result = await client.get_messages(["m1", "m2", "m3"])

    assert [m.id for m in result] == ["m1", "m3"]


@pytest.mark.asyncio
async def test_access_token_is_cached_between_calls(monkeypatch):
    calls = _install_fake_api(
        monkeypatch,
        list_pages=[{}, {}],
        messages={"m1": _message("m1")},
    )
    client = GoogleGmailClient("id", "secret", "refresh")

    await client.list_ids_since(SINCE)
    await client.list_ids_since(SINCE)
    await client.get_messages(["m1"])

    assert calls["token"] == 1


@pytest.mark.asyncio
async def test_returns_empty_on_token_failure(monkeypatch):
    async def fake_post(self, url, headers=None, data=None, json=None):  # noqa: ARG001
        raise httpx.ConnectError("boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    client = GoogleGmailClient("id", "secret", "refresh")

    assert await client.list_unread() == []
    assert await client.list_ids_since(SINCE) == []
    assert await client.get_messages(["m1"]) == []


@pytest.mark.asyncio
async def test_list_failure_keeps_ids_already_collected(monkeypatch):
    state = {"n": 0}

    async def fake_post(self, url, headers=None, data=None, json=None):  # noqa: ARG001
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"access_token": "t"}, request=request)

    async def fake_get(self, url, params=None, headers=None):  # noqa: ARG001
        request = httpx.Request("GET", url)
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(
                200, json={"messages": [{"id": "a"}], "nextPageToken": "p2"}, request=request
            )
        raise httpx.ConnectError("boom", request=request)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    client = GoogleGmailClient("id", "secret", "refresh")

    assert await client.list_ids_since(SINCE) == ["a"]
