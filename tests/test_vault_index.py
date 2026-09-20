from pathlib import Path

import pytest
from vault_index import VaultIndex
from vault_scanner import Chunk


def _chunk(chunk_id: str, text: str = "текст", heading: str | None = "Заголовок") -> Chunk:
    import hashlib

    return Chunk(
        chunk_id=chunk_id,
        file_path=Path("note.md"),
        heading=heading,
        text=text,
        content_hash=hashlib.sha1(text.encode("utf-8")).hexdigest(),
    )


@pytest.fixture
def index(tmp_path):
    return VaultIndex(tmp_path / "vault.db", embedding_dim=3)


@pytest.mark.asyncio
async def test_existing_hashes_empty_on_fresh_index(index):
    assert await index.existing_hashes() == {}


@pytest.mark.asyncio
async def test_upsert_then_existing_hashes(index):
    chunk = _chunk("note.md#Заголовок")
    await index.upsert([chunk], [[1.0, 0.0, 0.0]])

    assert await index.existing_hashes() == {chunk.chunk_id: chunk.content_hash}


@pytest.mark.asyncio
async def test_upsert_rejects_mismatched_lengths(index):
    with pytest.raises(ValueError, match="same length"):
        await index.upsert([_chunk("a")], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])


@pytest.mark.asyncio
async def test_upsert_empty_list_is_a_noop(index):
    await index.upsert([], [])
    assert await index.existing_hashes() == {}


@pytest.mark.asyncio
async def test_upsert_updates_existing_chunk_in_place(index):
    chunk_v1 = _chunk("note.md#X", text="старый текст")
    await index.upsert([chunk_v1], [[1.0, 0.0, 0.0]])

    chunk_v2 = _chunk("note.md#X", text="новый текст")
    await index.upsert([chunk_v2], [[0.0, 1.0, 0.0]])

    hashes = await index.existing_hashes()
    assert hashes == {"note.md#X": chunk_v2.content_hash}

    results = await index.search([0.0, 1.0, 0.0], k=1)
    assert results[0].text == "новый текст"


@pytest.mark.asyncio
async def test_search_returns_nearest_first(index):
    await index.upsert(
        [_chunk("a", text="a"), _chunk("b", text="b"), _chunk("c", text="c")],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    )

    results = await index.search([0.9, 0.1, 0.0], k=2)

    assert [r.chunk_id for r in results] == ["a", "b"]
    assert results[0].distance < results[1].distance


@pytest.mark.asyncio
async def test_search_result_carries_metadata(index):
    chunk = _chunk("note.md#Раздел", text="содержимое", heading="Раздел")
    await index.upsert([chunk], [[1.0, 0.0, 0.0]])

    results = await index.search([1.0, 0.0, 0.0], k=1)

    assert results[0].chunk_id == "note.md#Раздел"
    assert results[0].file_path == Path("note.md")
    assert results[0].heading == "Раздел"
    assert results[0].text == "содержимое"


@pytest.mark.asyncio
async def test_delete_missing_removes_stale_chunks(index):
    await index.upsert(
        [_chunk("keep", text="keep"), _chunk("gone", text="gone")],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )

    removed = await index.delete_missing({"keep"})

    assert removed == 1
    assert await index.existing_hashes() == {"keep": _chunk("keep", text="keep").content_hash}


@pytest.mark.asyncio
async def test_delete_missing_also_removes_vector_rows(index):
    await index.upsert(
        [_chunk("keep", text="keep"), _chunk("gone", text="gone")],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )
    await index.delete_missing({"keep"})

    # If the vec_chunks row for "gone" weren't removed, it would still show
    # up as a search result (there's nothing else in the index to outrank).
    results = await index.search([0.0, 1.0, 0.0], k=5)
    assert [r.chunk_id for r in results] == ["keep"]


@pytest.mark.asyncio
async def test_delete_missing_noop_when_nothing_stale(index):
    await index.upsert([_chunk("keep", text="keep")], [[1.0, 0.0, 0.0]])
    assert await index.delete_missing({"keep"}) == 0


@pytest.mark.asyncio
async def test_index_persists_across_instances(tmp_path):
    db_path = tmp_path / "vault.db"
    chunk = _chunk("note.md#X")

    first = VaultIndex(db_path, embedding_dim=3)
    await first.upsert([chunk], [[1.0, 0.0, 0.0]])

    second = VaultIndex(db_path, embedding_dim=3)
    assert await second.existing_hashes() == {chunk.chunk_id: chunk.content_hash}
