"""Scan the Obsidian vault and split notes into chunks for embedding.

Pure and synchronous — no asyncio, no dependency on TaskStore or any
embedding backend, so it's trivially unit-testable with a tmp_path vault.
The async wrapping (``asyncio.to_thread``) and the embedding/index side of
things belong one layer up, in ``VaultIndex`` (Second Brain block C).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# Directories never worth indexing: Obsidian's own config/trash and the
# usual noise a vault might have alongside notes.
_IGNORED_DIR_NAMES = frozenset({".obsidian", ".trash", ".git", ".obsidian-git", "node_modules"})

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# Pseudo-heading key for any text that appears before the first real
# heading in a file (or for a file with no headings at all).
_PREAMBLE_KEY = "\x00preamble"


@dataclass(frozen=True)
class Chunk:
    """One semantic piece of a note: one heading section's body text.

    ``chunk_id`` is derived from the file path and heading text, not from
    position in the file — so inserting or reordering *other* sections
    doesn't change this chunk's id, which matters for incremental
    re-indexing (only *changed* chunks should need re-embedding). It is
    NOT guaranteed stable if the heading text itself is renamed, or if a
    file has several identical headings and their relative order changes
    — an acceptable gap for a first version.

    ``content_hash`` (sha1 of the body text) is what actually decides
    whether a chunk needs re-embedding — compare it to what's already in
    the index rather than re-embedding every chunk on every scan.
    """

    chunk_id: str
    file_path: Path  # relative to the vault root
    heading: str | None  # None for text before the first heading
    text: str
    content_hash: str


def scan_vault(vault_path: Path) -> list[Path]:
    """Return every markdown file under *vault_path*, skipping ignored dirs.

    Paths are absolute, sorted for deterministic ordering (matters for
    tests and for stable logging — not for correctness of the index).
    """
    return sorted(
        path
        for path in vault_path.rglob("*.md")
        if not _IGNORED_DIR_NAMES & set(path.relative_to(vault_path).parts[:-1])
    )


def chunk_file(vault_path: Path, file_path: Path) -> list[Chunk]:
    """Split one markdown file into chunks, one per heading section.

    A "section" is a heading line plus everything up to the next heading
    of any level (this is intentionally coarse — a ``## Section`` with
    ``### Sub-section`` children becomes one chunk, not several; splitting
    on every heading level tends to produce chunks too small to carry
    useful context for semantic search). Text before the first heading, if
    any, becomes its own chunk. Sections with no body text are skipped —
    nothing there to embed.
    """
    text = file_path.read_text(encoding="utf-8")
    rel_path = file_path.relative_to(vault_path)

    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            sections.append((current_heading, current_lines))
            current_heading = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_heading, current_lines))

    chunks: list[Chunk] = []
    seen_heading_counts: dict[str, int] = {}
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue

        heading_key = heading if heading is not None else _PREAMBLE_KEY
        occurrence = seen_heading_counts.get(heading_key, 0)
        seen_heading_counts[heading_key] = occurrence + 1
        suffix = f":{occurrence}" if occurrence else ""

        chunks.append(
            Chunk(
                chunk_id=f"{rel_path.as_posix()}#{heading_key}{suffix}",
                file_path=rel_path,
                heading=heading,
                text=body,
                content_hash=hashlib.sha1(body.encode("utf-8")).hexdigest(),
            )
        )
    return chunks


def chunk_vault(vault_path: Path) -> list[Chunk]:
    """Chunk every markdown file in the vault. Convenience wrapper for scripts/jobs."""
    chunks: list[Chunk] = []
    for file_path in scan_vault(vault_path):
        chunks.extend(chunk_file(vault_path, file_path))
    return chunks
