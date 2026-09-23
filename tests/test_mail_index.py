from datetime import UTC, datetime

import pytest
from integrations.gmail_client import MailMessage
from mail_index import MailIndex


def _message(
    message_id: str,
    *,
    sender_name: str = "Иван",
    subject: str = "Тема",
    date: datetime = datetime(2026, 9, 1, tzinfo=UTC),
    body: str = "текст письма",
    labels: tuple[str, ...] = ("INBOX",),
) -> MailMessage:
    return MailMessage(
        id=message_id,
        thread_id=f"t-{message_id}",
        sender=f"{sender_name} <x@example.com>",
        sender_name=sender_name,
        sender_email="x@example.com",
        subject=subject,
        date=date,
        snippet="",
        body=body,
        labels=labels,
    )


@pytest.fixture
def index(tmp_path):
    return MailIndex(tmp_path / "mail.db", embedding_dim=3)


@pytest.mark.asyncio
async def test_existing_ids_empty_on_fresh_index(index):
    assert await index.existing_ids() == set()


@pytest.mark.asyncio
async def test_upsert_then_existing_ids(index):
    await index.upsert([_message("m1")], [[1.0, 0.0, 0.0]])
    assert await index.existing_ids() == {"m1"}


@pytest.mark.asyncio
async def test_upsert_rejects_mismatched_lengths(index):
    with pytest.raises(ValueError, match="same length"):
        await index.upsert([_message("m1")], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


@pytest.mark.asyncio
async def test_upsert_empty_list_is_a_noop(index):
    await index.upsert([], [])
    assert await index.existing_ids() == set()


@pytest.mark.asyncio
async def test_upsert_updates_existing_message_in_place(index):
    await index.upsert([_message("m1", subject="Старая тема")], [[1.0, 0.0, 0.0]])
    await index.upsert([_message("m1", subject="Новая тема")], [[0.0, 1.0, 0.0]])

    assert await index.existing_ids() == {"m1"}
    results = await index.search([0.0, 1.0, 0.0], k=1)
    assert results[0].subject == "Новая тема"


@pytest.mark.asyncio
async def test_search_returns_nearest_first(index):
    await index.upsert(
        [_message("a"), _message("b"), _message("c")],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    )

    results = await index.search([0.9, 0.1, 0.0], k=2)

    assert [r.message_id for r in results] == ["a", "b"]
    assert results[0].distance < results[1].distance


@pytest.mark.asyncio
async def test_search_result_carries_metadata(index):
    msg = _message(
        "m1", sender_name="Пётр", subject="Договор", body="текст", labels=("INBOX", "IMPORTANT")
    )
    await index.upsert([msg], [[1.0, 0.0, 0.0]])

    results = await index.search([1.0, 0.0, 0.0], k=1)

    assert results[0].message_id == "m1"
    assert results[0].thread_id == "t-m1"
    assert results[0].sender_name == "Пётр"
    assert results[0].subject == "Договор"
    assert results[0].body == "текст"
    assert results[0].labels == ("INBOX", "IMPORTANT")
    assert results[0].date == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_delete_older_than_removes_old_messages(index):
    await index.upsert(
        [
            _message("old", date=datetime(2026, 1, 1, tzinfo=UTC)),
            _message("new", date=datetime(2026, 9, 1, tzinfo=UTC)),
        ],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    removed = await index.delete_older_than(datetime(2026, 6, 1, tzinfo=UTC))

    assert removed == 1
    assert await index.existing_ids() == {"new"}


@pytest.mark.asyncio
async def test_delete_older_than_also_removes_vector_rows(index):
    await index.upsert(
        [
            _message("old", date=datetime(2026, 1, 1, tzinfo=UTC)),
            _message("new", date=datetime(2026, 9, 1, tzinfo=UTC)),
        ],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )
    await index.delete_older_than(datetime(2026, 6, 1, tzinfo=UTC))

    # If the vec row for "old" weren't removed, it would still show up here.
    results = await index.search([1.0, 0.0, 0.0], k=5)
    assert [r.message_id for r in results] == ["new"]


@pytest.mark.asyncio
async def test_delete_older_than_noop_when_nothing_old(index):
    await index.upsert([_message("new", date=datetime(2026, 9, 1, tzinfo=UTC))], [[1.0, 0.0, 0.0]])
    assert await index.delete_older_than(datetime(2026, 1, 1, tzinfo=UTC)) == 0


@pytest.mark.asyncio
async def test_index_persists_across_instances(tmp_path):
    db_path = tmp_path / "mail.db"
    await MailIndex(db_path, embedding_dim=3).upsert([_message("m1")], [[1.0, 0.0, 0.0]])

    second = MailIndex(db_path, embedding_dim=3)
    assert await second.existing_ids() == {"m1"}
