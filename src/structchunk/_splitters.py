"""Sub-splitters for atomic blocks that alone exceed ``hard_max_size``.

Each splitter respects the block's internal structure:

* paragraphs: sentence boundaries (both Chinese and English)
* code:      line boundaries, re-open/close fences
* tables:    row boundaries, header rows prepended to each chunk
* lists:     item boundaries (lines starting with ``-`` / ``*`` / ``1.``)

``force_split_long_strings`` is the last-resort fallback that splits at
arbitrary character boundaries, used only when even a single
sentence/line/row exceeds the hard limit.
"""

from __future__ import annotations

import re

from ._models import BlockType
from ._parser import (
    _RE_LIST_ITEM,
    _RE_SENTENCE,
    _protect_urls,
    _restore_urls,
)


def _force_split_long_strings(chunks: list[str], hard_max: int) -> list[str]:
    if hard_max <= 0:
        return chunks
    result: list[str] = []
    for c in chunks:
        if len(c) <= hard_max:
            result.append(c)
        else:
            for start in range(0, len(c), hard_max):
                result.append(c[start : start + hard_max])
    return result


def split_paragraph_at_sentences(
    text: str, max_size: int, hard_max: int
) -> list[str]:
    """Split a paragraph at sentence boundaries.

    Each sentence is kept intact — a single sentence is never broken
    mid-sentence. URLs and emails are protected: their internal dots
    are swapped to a placeholder so the sentence regex doesn't treat
    ``api.openai.com`` as three separate sentences. If a sentence
    itself exceeds hard_max, it is force-split (last-resort fallback).
    """
    if not text:
        return [""]

    protected_text, protected_items = _protect_urls(text)
    sentences = _RE_SENTENCE.findall(protected_text)
    if not sentences:
        return [_restore_urls(text[:hard_max], protected_items)]

    sentences = [_restore_urls(s, protected_items) for s in sentences]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        slen = len(sent)
        if current and current_len + slen > max_size:
            chunks.append("".join(current))
            current = [sent]
            current_len = slen
        else:
            current.append(sent)
            current_len += slen
    if current:
        chunks.append("".join(current))

    return _force_split_long_strings(chunks, hard_max)


def split_code_block(
    lines: list[str], max_size: int, hard_max: int, lang: str = ""
) -> list[str]:
    """Split code lines, re-opening/closing fences in each chunk."""
    inner_lines = lines
    if inner_lines and inner_lines[0].strip().startswith(("```", "~~~")):
        inner_lines = inner_lines[1:]
    if inner_lines and inner_lines[-1].strip().startswith(("```", "~~~")):
        inner_lines = inner_lines[:-1]

    if not inner_lines:
        return ["```\n```"]

    fence = "```" + (lang if lang else "")
    chunks: list[str] = []
    current: list[str] = []
    current_len = len(fence) + 1

    for line in inner_lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_size:
            chunks.append(fence + "\n" + "\n".join(current) + "\n```")
            current = [line]
            current_len = len(fence) + 1 + line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append(fence + "\n" + "\n".join(current) + "\n```")

    return _force_split_long_strings(chunks, hard_max)


def split_table_rows(
    header_lines: list[str],
    data_rows: list[str],
    max_size: int,
    hard_max: int,
) -> list[str]:
    """Split table data rows, prepending the header to each chunk."""
    header_text = "\n".join(header_lines)
    header_len = len(header_text) + 1

    chunks: list[str] = []
    current_rows: list[str] = []
    current_len = header_len

    for row in data_rows:
        row_len = len(row) + 1
        if current_rows and current_len + row_len > max_size:
            chunks.append(header_text + "\n" + "\n".join(current_rows))
            current_rows = [row]
            current_len = header_len + row_len
        else:
            current_rows.append(row)
            current_len += row_len

    if current_rows:
        chunks.append(header_text + "\n" + "\n".join(current_rows))

    return _force_split_long_strings(chunks, hard_max)


def split_list_items(
    lines: list[str], max_size: int, hard_max: int
) -> list[str]:
    """Split a list at item boundaries (one item = one bullet/numbered block)."""
    items: list[list[str]] = []
    current_item: list[str] = []

    for line in lines:
        if _RE_LIST_ITEM.match(line) or (not current_item):
            if current_item:
                items.append(current_item)
            current_item = [line]
        else:
            current_item.append(line)
    if current_item:
        items.append(current_item)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for item_lines in items:
        item_text = "\n".join(item_lines)
        item_len = len(item_text) + 1
        if current and current_len + item_len > max_size:
            chunks.append("\n".join(current))
            current = [item_text]
            current_len = item_len
        else:
            current.append(item_text)
            current_len += item_len

    if current:
        chunks.append("\n".join(current))

    return _force_split_long_strings(chunks, hard_max)


__all__ = [
    "split_paragraph_at_sentences",
    "split_code_block",
    "split_table_rows",
    "split_list_items",
    "_force_split_long_strings",
]
