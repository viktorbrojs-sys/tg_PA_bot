from pathlib import Path

import pytest
from services.vault_indexer import reindex_vault
from vault_index import VaultIndex


class FakeEmbeddingClient:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        self.calls.append(texts)
        if self.fail:
            return None
        # Deterministic, distinguishable-enough vector per text.
        return [[float(len(t) % 7), float(i), 0.0] for i, t in enumerate(texts)]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    return vault_dir


@pytest.fixture
def index(tmp_path):
    return VaultIndex(tmp_path / "index.db", embedding_dim=3)


@pytest.mark.asyncio
async def test_reindex_empty_vault_is_a_noop(vault, index):
    embeddings = FakeEmbeddingClient()

    stats = await reindex_vault(vault, index, embeddings)

    assert (stats.added, stats.updated, stats.deleted, stats.unchanged) == (0, 0, 0, 0)
    assert stats.failed is False
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_reindex_adds_new_chunks(vault, index):
    _write(vault / "note.md", "## Раздел\nТекст.\n")
    embeddings = FakeEmbeddingClient()

    stats = await reindex_vault(vault, index, embeddings)

    assert (stats.added, stats.updated, stats.deleted, stats.unchanged) == (1, 0, 0, 0)
    assert await index.existing_hashes()  # something got indexed


@pytest.mark.asyncio
async def test_reindex_twice_with_no_changes_embeds_nothing(vault, index):
    _write(vault / "note.md", "## Раздел\nТекст.\n")
    embeddings = FakeEmbeddingClient()
    await reindex_vault(vault, index, embeddings)

    stats = await reindex_vault(vault, index, embeddings)

    assert (stats.added, stats.updated, stats.deleted, stats.unchanged) == (0, 0, 0, 1)
    assert embeddings.calls == [["Текст."]]  # only the first run called embed


@pytest.mark.asyncio
async def test_reindex_reembeds_only_changed_chunk(vault, index):
    _write(vault / "note.md", "## A\nТекст A.\n\n## B\nТекст B.\n")
    embeddings = FakeEmbeddingClient()
    await reindex_vault(vault, index, embeddings)

    _write(vault / "note.md", "## A\nТекст A изменён.\n\n## B\nТекст B.\n")
    stats = await reindex_vault(vault, index, embeddings)

    assert (stats.added, stats.updated, stats.deleted, stats.unchanged) == (0, 1, 0, 1)
    assert embeddings.calls[-1] == ["Текст A изменён."]


@pytest.mark.asyncio
async def test_reindex_prunes_deleted_notes(vault, index):
    _write(vault / "note.md", "## A\nТекст A.\n")
    embeddings = FakeEmbeddingClient()
    await reindex_vault(vault, index, embeddings)

    (vault / "note.md").unlink()
    stats = await reindex_vault(vault, index, embeddings)

    assert (stats.added, stats.updated, stats.deleted, stats.unchanged) == (0, 0, 1, 0)
    assert await index.existing_hashes() == {}


@pytest.mark.asyncio
async def test_reindex_aborts_without_touching_index_when_embedding_fails(vault, index):
    _write(vault / "note.md", "## A\nТекст A.\n")
    embeddings = FakeEmbeddingClient(fail=True)

    stats = await reindex_vault(vault, index, embeddings)

    assert stats.failed is True
    assert (stats.added, stats.updated, stats.deleted) == (0, 0, 0)
    assert await index.existing_hashes() == {}


@pytest.mark.asyncio
async def test_reindex_failed_run_does_not_prune_existing_chunks(vault, index):
    _write(vault / "keep.md", "## A\nТекст A.\n")
    ok_embeddings = FakeEmbeddingClient()
    await reindex_vault(vault, index, ok_embeddings)

    _write(vault / "new.md", "## B\nТекст B.\n")
    failing_embeddings = FakeEmbeddingClient(fail=True)
    stats = await reindex_vault(vault, index, failing_embeddings)

    assert stats.failed is True
    # The previously-indexed chunk must survive an aborted run.
    assert "keep.md#A" in await index.existing_hashes()
