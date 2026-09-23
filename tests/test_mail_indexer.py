from datetime import UTC, datetime, timedelta

import pytest
from integrations.gmail_client import MailMessage
from mail_index import MailIndex
from services.mail_indexer import reindex_mail

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class FakeGmailClient:
    def __init__(self, messages: dict[str, MailMessage] | None = None) -> None:
        self._messages = messages or {}
        self.list_ids_since_calls: list[datetime] = []

    async def list_unread(self, limit=10, important_only=False):
        return []

    async def list_ids_since(self, since: datetime, max_messages: int = 5000) -> list[str]:
        self.list_ids_since_calls.append(since)
        return list(self._messages.keys())

    async def get_messages(self, ids: list[str]) -> list[MailMessage]:
        return [self._messages[i] for i in ids if i in self._messages]

    async def count_unread(self):
        return None


class FakeEmbeddingClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        self.calls.append(texts)
        if self.fail:
            return None
        return [[float(i), 0.0, 0.0] for i in range(len(texts))]


def _message(message_id: str, *, date: datetime = NOW, subject: str = "Тема") -> MailMessage:
    return MailMessage(
        id=message_id,
        thread_id=f"t-{message_id}",
        sender="Иван <x@example.com>",
        sender_name="Иван",
        sender_email="x@example.com",
        subject=subject,
        date=date,
        snippet="сниппет",
        body="тело письма",
        labels=("INBOX",),
    )


@pytest.fixture
def index(tmp_path):
    return MailIndex(tmp_path / "mail.db", embedding_dim=3)


@pytest.mark.asyncio
async def test_reindex_empty_inbox_is_a_noop(index):
    gmail = FakeGmailClient({})
    embeddings = FakeEmbeddingClient()

    stats = await reindex_mail(gmail, index, embeddings, timedelta(days=180), NOW)

    assert (stats.added, stats.deleted, stats.failed) == (0, 0, False)
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_reindex_adds_new_messages(index):
    gmail = FakeGmailClient({"m1": _message("m1")})
    embeddings = FakeEmbeddingClient()

    stats = await reindex_mail(gmail, index, embeddings, timedelta(days=180), NOW)

    assert stats.added == 1
    assert await index.existing_ids() == {"m1"}


@pytest.mark.asyncio
async def test_reindex_skips_already_indexed_ids(index):
    await index.upsert([_message("m1")], [[1.0, 0.0, 0.0]])
    gmail = FakeGmailClient({"m1": _message("m1"), "m2": _message("m2")})
    embeddings = FakeEmbeddingClient()

    stats = await reindex_mail(gmail, index, embeddings, timedelta(days=180), NOW)

    assert stats.added == 1  # only m2
    assert embeddings.calls == [["Тема\n\nтело письма"]]  # only m2 was embedded
    assert await index.existing_ids() == {"m1", "m2"}


@pytest.mark.asyncio
async def test_reindex_uses_retention_as_since_cutoff(index):
    gmail = FakeGmailClient({})
    embeddings = FakeEmbeddingClient()

    await reindex_mail(gmail, index, embeddings, timedelta(days=30), NOW)

    assert gmail.list_ids_since_calls == [NOW - timedelta(days=30)]


@pytest.mark.asyncio
async def test_reindex_prunes_messages_older_than_retention(index):
    await index.upsert(
        [_message("old", date=NOW - timedelta(days=200)), _message("new", date=NOW)],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )
    gmail = FakeGmailClient({})
    embeddings = FakeEmbeddingClient()

    stats = await reindex_mail(gmail, index, embeddings, timedelta(days=180), NOW)

    assert stats.deleted == 1
    assert await index.existing_ids() == {"new"}


@pytest.mark.asyncio
async def test_reindex_aborts_without_touching_index_when_embedding_fails(index):
    await index.upsert([_message("old", date=NOW - timedelta(days=200))], [[1.0, 0.0, 0.0]])
    gmail = FakeGmailClient({"new": _message("new")})
    embeddings = FakeEmbeddingClient(fail=True)

    stats = await reindex_mail(gmail, index, embeddings, timedelta(days=180), NOW)

    assert stats.failed is True
    assert (stats.added, stats.deleted) == (0, 0)
    # Neither the new message was added nor the old one pruned.
    assert await index.existing_ids() == {"old"}


@pytest.mark.asyncio
async def test_reindex_embed_text_prefers_body_over_snippet(index):
    gmail = FakeGmailClient({"m1": _message("m1", subject="Заголовок")})
    embeddings = FakeEmbeddingClient()

    await reindex_mail(gmail, index, embeddings, timedelta(days=180), NOW)

    assert embeddings.calls == [["Заголовок\n\nтело письма"]]
