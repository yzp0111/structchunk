"""Linear (greedy) markdown chunker.

Walks atomic blocks in document order and greedily assembles chunks
that stay under ``max_chunk_size``. Oversized atomic blocks are
delegated to the type-specific sub-splitters.

Key design choices
------------------
* Context absorption: a TABLE or LIST block absorbs the immediately
  preceding non-blank, non-table/list block as context. This ensures
  the first chunk of a table/list carries the paragraph or marker line
  that summarises it.
* Header pull-up: trailing headers are moved to the next group so
  they lead their content.
* RAG breadcrumb: built from the end-of-group path (no stale same-level
  headers) plus all in-group headers in document order.
"""

from __future__ import annotations

import uuid

from ._config import ChunkerConfig
from ._enrich import (
    _extract_intro_text,
    _re_split_with_prefix_budget,
    collect_headers_in_group,
    compute_end_breadcrumb,
    enrich_rag_metadata,
    get_table_header_for_group,
    inject_missing_breadcrumbs,
    merge_tiny,
)
from ._models import (
    AtomicBlock,
    BlockType,
    ChunkMetadata,
    HeaderInfo,
    MarkdownChunk,
    _new_chunk_id,
)
from ._parser import _block_text, _parse_atomic_blocks
from ._splitters import (
    _force_split_long_strings,
    split_code_block,
    split_list_items,
    split_paragraph_at_sentences,
    split_table_rows,
)

# Backwards-compatible alias: the test suite imports
# ``_extract_intro_text_linear`` from this module. The function is now
# shared via ``_enrich._extract_intro_text``; the alias preserves the
# historical name without re-defining the function here.
_extract_intro_text_linear = _extract_intro_text


def _sub_split_block(block: AtomicBlock, config: ChunkerConfig) -> list[str]:
    """Apply type-specific sub-splitting to an oversized block."""
    text = _block_text(block)

    if block.block_type == BlockType.PARAGRAPH and config.sub_split_paragraph:
        return split_paragraph_at_sentences(
            text, config.max_chunk_size, config.hard_max_size
        )

    if block.block_type == BlockType.CODE_FENCE and config.sub_split_code:
        return split_code_block(
            block.lines,
            config.max_chunk_size,
            config.hard_max_size,
            lang=block.meta.get("lang", ""),
        )

    if block.block_type in (BlockType.TABLE, BlockType.TABLE_ROW):
        if config.sub_split_table:
            header_rows = block.meta.get("header_rows", [])
            if block.block_type == BlockType.TABLE:
                data_rows = block.lines[len(header_rows):]
            else:
                data_rows = block.lines
            if header_rows:
                return split_table_rows(
                    header_rows,
                    data_rows,
                    config.max_chunk_size,
                    config.hard_max_size,
                )
        return _force_split_long_strings([text], config.hard_max_size)

    if block.block_type == BlockType.LIST and config.sub_split_list:
        return split_list_items(
            block.lines, config.max_chunk_size, config.hard_max_size
        )

    return _force_split_long_strings([text], config.hard_max_size)


def _make_chunk(
    content: str,
    blocks: list[AtomicBlock],
    headers: list[HeaderInfo],
    index: int,
    total: int,
    config: ChunkerConfig,
    table_header_rows: list[str] | None,
    breadcrumb_texts: list[str] | None = None,
) -> MarkdownChunk:
    breadcrumb = (
        breadcrumb_texts
        if breadcrumb_texts is not None
        else [f"{'#' * h.level} {h.text}" for h in headers]
    )

    block_types = [b.block_type for b in blocks if b.block_type != BlockType.BLANK]
    dominant_type = block_types[0] if block_types else BlockType.PARAGRAPH

    if (
        blocks
        and blocks[0].block_type == BlockType.TABLE_ROW
        and config.preserve_table_header
        and table_header_rows
    ):
        header_prefix = "\n".join(table_header_rows)
        if not content.startswith(header_prefix):
            content = header_prefix + "\n" + content

    return MarkdownChunk(
        content=content,
        metadata=ChunkMetadata(
            chunk_id=_new_chunk_id(),
            chunk_index=index,
            total_chunks=total,
            char_offset_start=blocks[0].char_start if blocks else 0,
            char_offset_end=blocks[-1].char_end if blocks else 0,
            header_breadcrumb=breadcrumb,
            header_path=list(headers),
            has_more=index < total - 1,
            source_meta={
                "dominant_type": dominant_type.name,
                "block_types": [bt.name for bt in block_types],
            },
        ),
    )


def assemble_chunks(
    blocks: list[AtomicBlock], config: ChunkerConfig
) -> list[MarkdownChunk]:
    raw_groups: list[list[AtomicBlock]] = []
    current_group: list[AtomicBlock] = []
    current_size = 0

    for idx, block in enumerate(blocks):
        block_size = block.char_end - block.char_start

        # Context absorption: when starting a new group with a TABLE or
        # LIST, pull in the preceding non-blank, non-table/list block as
        # context. The preceding paragraph/marker is the effective summary
        # for RAG.
        if not current_group and block.block_type in (
            BlockType.TABLE, BlockType.TABLE_ROW, BlockType.LIST,
        ):
            for j in range(idx - 1, -1, -1):
                prev_block = blocks[j]
                if prev_block.block_type == BlockType.BLANK:
                    continue
                if prev_block.block_type in (
                    BlockType.TABLE, BlockType.TABLE_ROW, BlockType.LIST,
                ):
                    break
                prev_size = prev_block.char_end - prev_block.char_start
                if prev_size + block_size <= config.hard_max_size:
                    current_group.append(prev_block)
                    current_size += prev_size
                break

        if current_group and current_size + block_size > config.max_chunk_size:
            best_split = len(current_group)
            for j in range(len(current_group) - 1, 0, -1):
                if current_group[j].block_type == BlockType.HEADER:
                    prefix_size = sum(
                        b.char_end - b.char_start for b in current_group[:j]
                    )
                    if prefix_size >= config.min_chunk_size:
                        best_split = j
                        break

            raw_groups.append(list(current_group[:best_split]))
            current_group = current_group[best_split:]
            current_size = sum(
                b.char_end - b.char_start for b in current_group
            )

        current_group.append(block)
        current_size += block_size

    if current_group:
        raw_groups.append(list(current_group))

    for i in range(len(raw_groups) - 1):
        while raw_groups[i] and raw_groups[i][-1].block_type == BlockType.HEADER:
            raw_groups[i + 1].insert(0, raw_groups[i].pop())

    raw_groups = [g for g in raw_groups if g]

    if len(raw_groups) >= 2 and len(raw_groups[-1]) > 0:
        last_group = raw_groups[-1]
        all_headers = all(b.block_type == BlockType.HEADER for b in last_group)
        if all_headers:
            raw_groups[-2].extend(raw_groups[-1])
            raw_groups.pop()

    chunks: list[MarkdownChunk] = []
    header_stack: list[HeaderInfo] = []

    for idx, group_blocks in enumerate(raw_groups):
        end_breadcrumb = compute_end_breadcrumb(group_blocks, header_stack)
        header_stack = list(end_breadcrumb)

        parts: list[str] = []
        oversized_parts: list[str] = []

        for block in group_blocks:
            bt = _block_text(block)
            bs = block.char_end - block.char_start

            if bs > config.max_chunk_size:
                sub_chunks = _sub_split_block(block, config)
                oversized_parts.extend(sub_chunks)
            else:
                parts.append(bt)

        group_headers = collect_headers_in_group(group_blocks)
        # RAG breadcrumb: start from the end-of-group path (which correctly
        # pops stale same-level headers), then strip the last entry so we
        # can re-add ALL in-group headers in document order.
        breadcrumb_texts = [f"{'#' * h.level} {h.text}" for h in end_breadcrumb]
        if (
            breadcrumb_texts
            and group_headers
            and breadcrumb_texts[-1]
            == f"{'#' * group_headers[-1].level} {group_headers[-1].text}"
        ):
            breadcrumb_texts.pop()
        seen = set(breadcrumb_texts)
        for h in group_headers:
            prefixed = f"{'#' * h.level} {h.text}"
            if prefixed not in seen:
                seen.add(prefixed)
                breadcrumb_texts.append(prefixed)

        group_idx = idx  # preserve original group index (idx gets mutated below)
        group_start_idx = len(chunks)

        if parts:
            table_header = get_table_header_for_group(group_blocks)
            chunks.append(_make_chunk(
                "\n\n".join(parts),
                group_blocks,
                end_breadcrumb,
                idx,
                len(raw_groups),
                config,
                table_header,
                breadcrumb_texts=breadcrumb_texts,
            ))
            for sub in oversized_parts:
                idx += 1
                chunks.append(_make_chunk(
                    sub,
                    group_blocks,
                    end_breadcrumb,
                    idx,
                    len(raw_groups) + len(oversized_parts),
                    config,
                    table_header,
                    breadcrumb_texts=breadcrumb_texts,
                ))
        else:
            table_header = get_table_header_for_group(group_blocks)
            for i, sub in enumerate(oversized_parts):
                chunks.append(_make_chunk(
                    sub,
                    group_blocks,
                    end_breadcrumb,
                    idx + i,
                    len(raw_groups) + len(oversized_parts) - 1,
                    config,
                    table_header,
                    breadcrumb_texts=breadcrumb_texts,
                ))

        # Forward intro text to continuation chunks (group-split + oversized)
        if config.forward_intro_text:
            intro = _extract_intro_text(group_blocks)
            if not intro and group_idx > 0:
                intro = _extract_intro_text(raw_groups[group_idx - 1])
            if intro and group_blocks and group_blocks[0].block_type in (
                BlockType.TABLE, BlockType.TABLE_ROW, BlockType.LIST,
            ):
                for ci in range(group_start_idx, len(chunks)):
                    c = chunks[ci]
                    if intro not in c.content:
                        c.content = intro + "\n\n" + c.content
                        c.recompute_lengths()

    chunks = _re_split_with_prefix_budget(chunks, config.hard_max_size)
    chunks = inject_missing_breadcrumbs(chunks)
    # Second re_split: after breadcrumb injection, chunks may exceed
    # hard_max_size because the injected prefix wasn't accounted for
    # in the first pass. Mirrors hierarchical's pipeline (hierarchical.py:513+520).
    chunks = _re_split_with_prefix_budget(chunks, config.hard_max_size)

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata.total_chunks = total
        chunk.metadata.has_more = i < total - 1

    chunks = merge_tiny(chunks, config)

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata.chunk_index = i
        chunk.metadata.total_chunks = total
        chunk.metadata.has_more = i < total - 1

    enrich_rag_metadata(chunks, config)

    return chunks


def chunk_linear(
    content: str,
    *,
    max_chunk_size: int = 1500,
    hard_max_size: int = 3000,
    min_chunk_size: int = 50,
    preserve_table_header: bool = True,
    preserve_code_fence: bool = True,
    sub_split_table: bool = True,
    sub_split_code: bool = True,
    sub_split_list: bool = True,
    sub_split_paragraph: bool = True,
    doc_id: str = "",
    max_chars: int | None = None,
    forward_intro_text: bool = True,
) -> list[MarkdownChunk]:
    """Chunk markdown content using the linear (greedy) algorithm.

    Parameters
    ----------
    content : str
        Raw markdown text.
    max_chars : int, optional
        Convenience cap: sets ``hard_max_size=max_chars`` and
        ``max_chunk_size=int(max_chars * 0.8)``. Use this for Dify
        (≤500 chars per chunk).
    """
    if max_chars is not None:
        hard_max_size = max_chars
        max_chunk_size = max(1, int(max_chars * 0.8))

    config = ChunkerConfig(
        max_chunk_size=max_chunk_size,
        hard_max_size=hard_max_size,
        min_chunk_size=min_chunk_size,
        preserve_table_header=preserve_table_header,
        preserve_code_fence=preserve_code_fence,
        sub_split_table=sub_split_table,
        sub_split_code=sub_split_code,
        sub_split_list=sub_split_list,
        sub_split_paragraph=sub_split_paragraph,
        doc_id=doc_id,
        forward_intro_text=forward_intro_text,
    )

    blocks = _parse_atomic_blocks(content)
    blocks = [b for b in blocks if b.block_type != BlockType.BLANK]
    if not blocks:
        return []

    return assemble_chunks(blocks, config)


__all__ = ["chunk_linear", "assemble_chunks"]
