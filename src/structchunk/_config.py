"""All tuneable knobs for the chunkers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChunkerConfig:
    """Configuration shared by the linear and hierarchical chunkers."""

    max_chunk_size: int = 1500
    """Soft upper limit on chunk size in characters."""

    hard_max_size: int = 3000
    """Absolute maximum — a chunk is never larger than this."""

    min_chunk_size: int = 50
    """Don't produce chunks smaller than this (merge with neighbours)."""

    sub_split_table: bool = True
    """Allow splitting oversized tables at row boundaries."""

    sub_split_code: bool = True
    """Allow splitting oversized code blocks at line boundaries."""

    sub_split_list: bool = True
    """Allow splitting oversized lists at item boundaries."""

    sub_split_paragraph: bool = True
    """Allow splitting oversized paragraphs at sentence boundaries."""

    preserve_table_header: bool = True
    """When a table is split across chunks, prepend the header row(s)
    to each continuation chunk."""

    preserve_code_fence: bool = True
    """When a code block is split, re-open/close fences in each chunk."""

    doc_id: str = ""
    """Optional document identifier propagated to every chunk's metadata."""

    forward_intro_text: bool = True
    """When a section's first table or list is immediately preceded by a
    plain-text paragraph (not a markdown header), the paragraph's last
    sentence is forwarded to split continuations as an implicit title.
    Set to False to disable this behavior.
    """


__all__ = ["ChunkerConfig"]
