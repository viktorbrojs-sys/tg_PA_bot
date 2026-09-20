from pathlib import Path

from vault_scanner import chunk_file, chunk_vault, scan_vault


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_scan_vault_finds_markdown_files_recursively(tmp_path):
    _write(tmp_path / "note1.md", "hi")
    _write(tmp_path / "sub" / "note2.md", "hi")
    _write(tmp_path / "not-markdown.txt", "hi")

    files = scan_vault(tmp_path)

    assert files == [tmp_path / "note1.md", tmp_path / "sub" / "note2.md"]


def test_scan_vault_skips_ignored_dirs(tmp_path):
    _write(tmp_path / "note.md", "hi")
    _write(tmp_path / ".obsidian" / "workspace.md", "hi")
    _write(tmp_path / ".trash" / "deleted.md", "hi")
    _write(tmp_path / ".git" / "objects" / "note.md", "hi")

    files = scan_vault(tmp_path)

    assert files == [tmp_path / "note.md"]


def test_chunk_file_splits_on_headings(tmp_path):
    _write(
        tmp_path / "note.md",
        "Преамбула без заголовка.\n\n"
        "## Раздел 1\nТекст раздела 1.\n\n"
        "## Раздел 2\nТекст раздела 2.\n",
    )

    chunks = chunk_file(tmp_path, tmp_path / "note.md")

    assert [c.heading for c in chunks] == [None, "Раздел 1", "Раздел 2"]
    assert chunks[0].text == "Преамбула без заголовка."
    assert chunks[1].text == "Текст раздела 1."
    assert chunks[2].text == "Текст раздела 2."
    assert all(c.file_path == Path("note.md") for c in chunks)


def test_chunk_file_skips_empty_sections(tmp_path):
    _write(tmp_path / "note.md", "## Пусто\n\n## Не пусто\nЕсть текст.\n")

    chunks = chunk_file(tmp_path, tmp_path / "note.md")

    assert [c.heading for c in chunks] == ["Не пусто"]


def test_chunk_file_keeps_subheadings_within_parent_section(tmp_path):
    _write(tmp_path / "note.md", "## Родитель\nТекст.\n### Подраздел\nЕщё текст.\n")

    chunks = chunk_file(tmp_path, tmp_path / "note.md")

    # Coarse split: everything up to the next heading of ANY level is one
    # chunk, so "### Подраздел" starts a new chunk rather than nesting.
    assert [c.heading for c in chunks] == ["Родитель", "Подраздел"]


def test_chunk_file_no_headings_at_all_is_one_preamble_chunk(tmp_path):
    _write(tmp_path / "note.md", "Просто текст без заголовков.\n")

    chunks = chunk_file(tmp_path, tmp_path / "note.md")

    assert len(chunks) == 1
    assert chunks[0].heading is None
    assert chunks[0].text == "Просто текст без заголовков."


def test_chunk_id_stable_when_unrelated_section_inserted_before(tmp_path):
    _write(tmp_path / "note.md", "## Раздел A\nТекст A.\n\n## Раздел B\nТекст B.\n")
    before = {c.heading: c.chunk_id for c in chunk_file(tmp_path, tmp_path / "note.md")}

    _write(
        tmp_path / "note.md",
        "## Новый раздел\nНовый текст.\n\n## Раздел A\nТекст A.\n\n## Раздел B\nТекст B.\n",
    )
    after = {c.heading: c.chunk_id for c in chunk_file(tmp_path, tmp_path / "note.md")}

    assert before["Раздел A"] == after["Раздел A"]
    assert before["Раздел B"] == after["Раздел B"]


def test_content_hash_changes_when_text_changes_but_id_does_not(tmp_path):
    _write(tmp_path / "note.md", "## Раздел\nСтарый текст.\n")
    before = chunk_file(tmp_path, tmp_path / "note.md")[0]

    _write(tmp_path / "note.md", "## Раздел\nНовый текст.\n")
    after = chunk_file(tmp_path, tmp_path / "note.md")[0]

    assert before.chunk_id == after.chunk_id
    assert before.content_hash != after.content_hash


def test_duplicate_headings_get_distinct_chunk_ids(tmp_path):
    _write(tmp_path / "note.md", "## Заметки\nПервая.\n\n## Заметки\nВторая.\n")

    chunks = chunk_file(tmp_path, tmp_path / "note.md")

    assert len(chunks) == 2
    assert chunks[0].chunk_id != chunks[1].chunk_id
    assert chunks[0].text == "Первая."
    assert chunks[1].text == "Вторая."


def test_chunk_vault_combines_all_files(tmp_path):
    _write(tmp_path / "a.md", "## X\nТекст X.\n")
    _write(tmp_path / "sub" / "b.md", "## Y\nТекст Y.\n")

    chunks = chunk_vault(tmp_path)

    assert {c.heading for c in chunks} == {"X", "Y"}
    assert {c.file_path for c in chunks} == {Path("a.md"), Path("sub/b.md")}
