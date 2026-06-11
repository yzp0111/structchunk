"""RAG-specific chunk enrichment: breadcrumb management, post-processing.

These helpers are shared by both chunking algorithms and operate on the
final list of :class:`MarkdownChunk` objects.
"""

from __future__ import annotations

from ._config import ChunkerConfig
from ._models import (
    AtomicBlock,
    BlockType,
    ChunkMetadata,
    HeaderInfo,
    MarkdownChunk,
    _last_sentence,
    _new_chunk_id,
)


def compute_breadcrumb(
    blocks: list[AtomicBlock], header_stack_before: list[HeaderInfo]
) -> list[HeaderInfo]:
    """Compute end-state header breadcrumb after processing all blocks.

    Standard header-stack semantics: a deeper header pushes; a
    same/higher-level header pops and replaces.
    """
    breadcrumb: list[HeaderInfo] = list(header_stack_before)
    for block in blocks:
        if block.block_type == BlockType.HEADER:
            level = block.meta.get("level", 1)
            text = block.meta.get("text", "")
            while breadcrumb and breadcrumb[-1].level >= level:
                breadcrumb.pop()
            breadcrumb.append(HeaderInfo(level, text))
    return breadcrumb


def collect_headers_in_group(blocks: list[AtomicBlock]) -> list[HeaderInfo]:
    """Return every header in *blocks* in document order.

    Unlike :func:`compute_breadcrumb` (which collapses same-level
    headers to the last), this keeps all of them so RAG retrieval can
    match any section header present in the chunk.
    """
    headers: list[HeaderInfo] = []
    for block in blocks:
        if block.block_type == BlockType.HEADER:
            headers.append(HeaderInfo(
                block.meta.get("level", 1),
                block.meta.get("text", ""),
            ))
    return headers


def compute_end_breadcrumb(
    blocks: list[AtomicBlock], start_breadcrumb: list[HeaderInfo]
) -> list[HeaderInfo]:
    breadcrumb: list[HeaderInfo] = list(start_breadcrumb)
    for block in blocks:
        if block.block_type == BlockType.HEADER:
            level = block.meta.get("level", 1)
            text = block.meta.get("text", "")
            while breadcrumb and breadcrumb[-1].level >= level:
                breadcrumb.pop()
            breadcrumb.append(HeaderInfo(level, text))
    return breadcrumb


def get_table_header_for_group(blocks: list[AtomicBlock]) -> list[str] | None:
    """Find the table header rows for a group of blocks.

    For groups starting with a TABLE_ROW, find the TABLE block that owns
    those rows (matched via ``header_rows`` in each block's meta). This
    prevents the wrong table's header from being attached to
    continuation rows.
    """
    for block in blocks:
        if block.block_type == BlockType.TABLE and "header_rows" in block.meta:
            return block.meta["header_rows"]
        if block.block_type == BlockType.TABLE_ROW and "header_rows" in block.meta:
            return block.meta["header_rows"]
    return None


def enforce_hard_max(
    chunks: list[MarkdownChunk], config: ChunkerConfig
) -> list[MarkdownChunk]:
    result: list[MarkdownChunk] = []
    for chunk in chunks:
        if len(chunk.content) <= config.hard_max_size:
            result.append(chunk)
        else:
            from ._splitters import _force_split_long_strings
            parts = _force_split_long_strings([chunk.content], config.hard_max_size)
            for j, part in enumerate(parts):
                result.append(MarkdownChunk(
                    content=part,
                    metadata=ChunkMetadata(
                        chunk_id=chunk.metadata.chunk_id if j == 0 else _new_chunk_id(),
                        chunk_index=0,
                        total_chunks=0,
                        char_offset_start=chunk.metadata.char_offset_start,
                        char_offset_end=chunk.metadata.char_offset_end,
                        header_breadcrumb=list(chunk.metadata.header_breadcrumb),
                        header_path=list(chunk.metadata.header_path),
                        has_more=False,
                    ),
                ))
    return result


def merge_tiny(
    chunks: list[MarkdownChunk], config: ChunkerConfig
) -> list[MarkdownChunk]:
    if len(chunks) <= 1:
        return chunks

    merged: list[MarkdownChunk] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = merged[-1]
        curr = chunks[i]
        would_exceed = (
            len(prev.content) + len(curr.content) + 2 > config.hard_max_size
        )
        # Only merge tiny chunks that share the same breadcrumb (same
        # section path). Merging across siblings would produce a chunk
        # whose breadcrumb mixes two sections.
        same_breadcrumb = (
            prev.metadata.header_breadcrumb == curr.metadata.header_breadcrumb
        )
        # Section-complete invariant: a tail/residual chunk from a split
        # section (is_section_complete=False) must not absorb a different
        # section's head, even if breadcrumbs happen to differ. Without
        # this guard, the hierarchical algorithm's "完整同级" rule is
        # violated downstream of section emission.
        prev_section_complete = prev.metadata.is_section_complete
        if (
            len(prev.content) < config.min_chunk_size
            and not would_exceed
            and same_breadcrumb
            and prev_section_complete
        ):
            prev.content = prev.content + "\n\n" + curr.content
            prev.metadata.char_offset_end = curr.metadata.char_offset_end
        else:
            merged.append(curr)
    return merged


def inject_missing_breadcrumbs(chunks: list[MarkdownChunk]) -> list[MarkdownChunk]:
    """Prepend any breadcrumb headers not already present in chunk content.

    Ensures the embedded text always carries the full hierarchical context
    even for continuation chunks where the header line was placed in the
    first chunk only. The H1 document title is skipped — it would be
    redundant on every chunk.
    """
    for chunk in chunks:
        bc = chunk.metadata.header_breadcrumb
        if not bc:
            continue
        # Line-prefix match: substring `h in chunk.content` false-positives
        # on shared prefixes (e.g. "## Section 2" inside "## Section 2.5"),
        # so compare the breadcrumb against the set of stripped content lines.
        content_lines = {
            line.strip() for line in chunk.content.split("\n") if line.strip()
        }
        missing_lines: list[str] = []
        for h in bc:
            if h.strip() in content_lines:
                continue
            # header_breadcrumb entries already include the markdown-level
            # prefix (e.g. "# H1", "## H2") since commit 9acb365f — append
            # directly without re-prefixing (would produce "# # H1" otherwise).
            missing_lines.append(h)
        if missing_lines:
            context_block = "\n".join(missing_lines) + "\n\n"
            chunk.content = context_block + chunk.content
    return chunks


def enrich_rag_metadata(
    chunks: list[MarkdownChunk], config: ChunkerConfig
) -> None:
    """Populate RAG-completeness fields on every chunk in place.
    """
    if not chunks:
        return

    type_counts: dict[str, int] = {}
    for i, chunk in enumerate(chunks):
        chunk.metadata.doc_id = config.doc_id
        chunk.metadata.prev_chunk_id = (
            chunks[i - 1].metadata.chunk_id if i > 0 else 0
        )
        chunk.metadata.next_chunk_id = (
            chunks[i + 1].metadata.chunk_id if i < len(chunks) - 1 else 0
        )
        chunk.metadata.continuation = bool(
            i > 0
            and chunk.metadata.header_breadcrumb
            and chunks[i - 1].metadata.header_breadcrumb
            == chunk.metadata.header_breadcrumb
        )

        block_types = chunk.metadata.source_meta.get("block_types", [])
        dominant = chunk.metadata.source_meta.get("dominant_type", "PARAGRAPH")
        chunk.metadata.source_element_type = dominant.lower()

        type_counts[dominant] = type_counts.get(dominant, 0) + 1
        chunk.metadata.source_element_position = f"{type_counts[dominant]}"
        # type_counts is internal scratch; do NOT write back to source_meta
        # (was previously leaked as the "_type_seq_counts" key).

    for chunk in chunks:
        chunk.recompute_lengths()


def _extract_intro_text(blocks: list[AtomicBlock]) -> str:
    """Return the implicit "title" of the first table or list in ``blocks``.

    The title is the last sentence of the paragraph block immediately
    preceding the first table or list block (TABLE / TABLE_ROW / LIST).
    If the preceding block is a HEADER (or any other type), return ""
    because the existing breadcrumb mechanism handles it.

    Examples:
        [Para("Important notice."), Table(...)] → "Important notice."
        [Header("## Section"), Table(...)] → ""  (header handles it)
        [Table(...)] → ""  (no preceding paragraph)
        [Para("x"), CodeBlock(...), Table(...)] → ""  (paragraph not adjacent)
    """
    target_types = {BlockType.TABLE, BlockType.TABLE_ROW, BlockType.LIST}
    for idx, block in enumerate(blocks):
        if block.block_type in target_types and idx > 0:
            prev = blocks[idx - 1]
            if prev.block_type == BlockType.PARAGRAPH:
                return _last_sentence("\n".join(prev.lines))
            return ""
    return ""


def _compute_prefix_for_chunk(chunk: MarkdownChunk) -> str:
    """Return the prefix string that will be prepended to this chunk.

    Computed from chunk.metadata.header_breadcrumb (NOT from chunk.content).
    This is the EXACT string that inject_missing_breadcrumbs will prepend
    when it runs. By computing it here (BEFORE inject), we can pre-budget
    the body length to fit within hard_max_size.

    Components:
    1. Breadcrumb header lines for entries NOT already in chunk.content
       (e.g. H2/H3 lines that need to be re-injected for context).
    2. *[续]* marker removed (user request 2026-06-10) — continuation
       chunks rely on inject_missing_breadcrumbs for parent context.
    """
    parts: list[str] = []
    bc = chunk.metadata.header_breadcrumb
    if bc:
        # Line-prefix match: see inject_missing_breadcrumbs for rationale.
        content_lines = {
            line.strip() for line in chunk.content.split("\n") if line.strip()
        }
        for h in bc:
            if h.strip() in content_lines:
                continue
            # header_breadcrumb entries already include the markdown-level
            # prefix (e.g. "# H1", "## H2") — append directly without
            # re-prefixing (would produce "# # H1" otherwise).
            parts.append(h)
    return "\n\n".join(parts) + ("\n\n" if parts else "")


def _detect_existing_prefix(chunk: MarkdownChunk) -> str:
    """Detect any prefix already inlined in chunk.content by upstream pipeline.

    Upstream (hierarchical's _apply_continuation_forwarding, _split_oversized_text)
    prepends:
      1. Markdown breadcrumb lines, e.g. `## Section`, `### Subsection`
         (joined by \\n, then \\n\\n separator before body)
      2. `*[续] {header}*` marker on continuation chunks
      3. Intro text (last sentence of preceding paragraph)
      4. Table column headers (`| col |\\n| --- | --- |`)

    Detection order:
      1. Table separator line (`|---`) → everything before it is prefix.
      2. `*[续]*` continuation marker → everything before it is prefix.
      3. Leading markdown headers (`## ...`, `### ...`) → consecutive headers
         (with optional blank lines) form the prefix.

    Returns the inlined prefix (without trailing data portion), or empty
    string if none detected.
    """
    content = chunk.content
    lines = content.split("\n")

    # 1. Look for table separator line (captures everything before it)
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("|") and "---" in stripped:
            if i >= 1:
                prefix_lines = lines[: i + 1]
                return "\n".join(prefix_lines) + "\n\n"
            return ""

    # 2. Look for *[续]* continuation marker
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("*[续]") and stripped.endswith("*"):
            prefix_lines = lines[: i + 1]
            prefix = "\n".join(prefix_lines)
            if not prefix.endswith("\n"):
                prefix += "\n"
            if not prefix.endswith("\n\n") and i + 1 < len(lines):
                prefix += "\n"
            return prefix

    # 3. Look for leading markdown headers (the bug fix)
    prefix_indices: list[int] = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped:
            # Allow empty lines between consecutive headers
            continue
        is_header = stripped[0] == "#" and len(stripped) > 1 and stripped[1] in (" ", "#")
        if is_header:
            prefix_indices.append(i)
            continue
        break
    if prefix_indices:
        last_idx = max(prefix_indices)
        prefix_lines = lines[: last_idx + 1]
        prefix = "\n".join(prefix_lines)
        # Ensure trailing blank-line separator before body
        if not prefix.endswith("\n"):
            prefix += "\n"
        if not prefix.endswith("\n\n") and last_idx + 1 < len(lines):
            prefix += "\n"
        return prefix

    return ""


def _chunk_has_table(content: str) -> bool:
    """Return True if the chunk content contains a markdown table.

    Detection is in two passes:
    1. Primary: look for a `|---|` separator line (the most reliable
       table indicator).
    2. Fallback: if at least 2 lines start with `|`, treat it as
       table data. This catches cases where the separator has been
       stripped as a "prefix" by `_re_split_with_prefix_budget`, leaving
       only the data rows behind.

    Used by `_re_split_with_prefix_budget` to override the metadata's
    `source_element_type` label when the chunk actually contains table
    content but was labeled as paragraph (e.g. when an H2 section
    starts with a plain-text paragraph "表0：xxx" then contains a table).
    Without this override, the paragraph splitter cuts the table
    mid-row, breaking table semantics.
    """
    if not content:
        return False
    pipe_line_count = 0
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("|"):
            continue
        # Primary signal: table separator line (e.g. `| --- |` or `|---|`)
        if "---" in stripped:
            return True
        # Fallback signal: data row (count lines that look like table rows)
        pipe_line_count += 1
    # If at least 2 pipe-prefixed non-separator lines, treat as table
    return pipe_line_count >= 2


def _re_split_with_prefix_budget(
    chunks: list[MarkdownChunk], hard_max_size: int
) -> list[MarkdownChunk]:
    """Re-split each chunk whose body + prefix would exceed hard_max_size.

    IMPORTANT: this is called BEFORE inject_missing_breadcrumbs. The chunk
    content has NOT yet had the prefix inlined. The body is the entire
    chunk.content; the prefix is computed from chunk.metadata.
    """
    from ._splitters import (
        split_paragraph_at_sentences,
        split_table_rows,
        split_list_items,
        split_code_block,
        _force_split_long_strings,
    )
    result: list[MarkdownChunk] = []
    for chunk in chunks:
        existing_prefix = _detect_existing_prefix(chunk)
        computed_prefix = _compute_prefix_for_chunk(chunk)
        # Determine which prefix to use for budget calculation.
        # If existing_prefix is inlined, we MUST subtract it from the cap
        # (so the body fits) and account for any further breadcrumb that
        # inject_missing_breadcrumbs will add. When the inlined prefix
        # alone exceeds hard_max_size, fall back to a metadata-only
        # budget (the cap cannot be perfectly respected in this edge
        # case, but the body is still properly split).
        if existing_prefix:
            if len(existing_prefix) + len(computed_prefix) <= hard_max_size:
                body = chunk.content[len(existing_prefix):]
                # -2 reserves room for the "\n\n" separator that
                # inject_missing_breadcrumbs appends after the prefix.
                effective_max = hard_max_size - len(existing_prefix) - len(computed_prefix) - 2
                can_reattach_prefix = True
            else:
                # Inlined prefix alone exceeds cap — strip it from the body
                # to avoid wasting the split budget on text that will be
                # re-derived from metadata by inject_missing_breadcrumbs.
                body = chunk.content[len(existing_prefix):]
                effective_max = hard_max_size - len(computed_prefix) - 2
                can_reattach_prefix = False
        else:
            body = chunk.content
            effective_max = hard_max_size - len(computed_prefix) - 2
            can_reattach_prefix = False
        if len(chunk.content) + len(computed_prefix) + 2 <= hard_max_size:
            result.append(chunk)
            continue
        if effective_max <= 0:
            if len(computed_prefix) > hard_max_size:
                # Computed prefix alone exceeds the cap. Drop it and let
                # inject_missing_breadcrumbs handle what fits.
                computed_prefix = ""
                effective_max = hard_max_size - len(existing_prefix) - 2
                if effective_max <= 0:
                    # Even existing_prefix alone is too big — cap cannot
                    # be respected; keep as-is.
                    result.append(chunk)
                    continue
            else:
                # Last resort: cap is so small that even the body has no room
                # This means the entire chunk is the prefix (e.g. just a header).
                # Keep as-is — the cap cannot be respected.
                result.append(chunk)
                continue
        # Dispatch based on ACTUAL chunk content, not just the metadata label.
        # A chunk labeled `paragraph` may still contain a markdown table
        # (e.g. when an H2 section starts with "表0：xxx" then a table).
        # The metadata's source_element_type is the SECTION's dominant type,
        # but for re-splitting the chunk's content we need to use the actual
        # content's structure to avoid cutting tables mid-row.
        elem_type = chunk.metadata.source_element_type.lower()
        if elem_type != "table" and _chunk_has_table(body):
            elem_type = "table"
        new_bodies: list[str] = []
        if elem_type == "table":
            body_lines = body.split("\n")
            header_lines2: list[str] = []
            data_rows: list[str] = []
            seen_sep = False
            for ln in body_lines:
                if not header_lines2 and ln.strip().startswith("|"):
                    header_lines2.append(ln)
                elif header_lines2 and not seen_sep and ln.strip().startswith("|---"):
                    header_lines2.append(ln)
                    seen_sep = True
                elif ln.strip().startswith("|"):
                    data_rows.append(ln)
            if header_lines2 and data_rows:
                new_bodies = split_table_rows(
                    header_lines2, data_rows, effective_max, effective_max
                )
            else:
                new_bodies = _force_split_long_strings([body], effective_max)
        elif elem_type == "code":
            new_bodies = split_code_block(
                body.split("\n"), effective_max, effective_max
            )
        elif elem_type == "list":
            new_bodies = split_list_items(
                body.split("\n"), effective_max, effective_max
            )
        else:
            new_bodies = split_paragraph_at_sentences(
                body, effective_max, effective_max
            )
        if not new_bodies:
            result.append(chunk)
            continue
        for j, new_body in enumerate(new_bodies):
            if not new_body.strip():
                continue
            # Re-attach prefix only if one was stripped AND the result still
            # fits within hard_max_size (including the metadata-derived prefix
            # that inject_missing_breadcrumbs will add later). When the inlined
            # prefix alone exceeds hard_max_size, dropping it prevents a runaway
            # split (where the prefix is re-added to every sub-chunk producing
            # chunks that all exceed the cap, which then can't be merged).
            if existing_prefix and can_reattach_prefix and len(existing_prefix) + len(new_body) <= hard_max_size:
                new_content = existing_prefix + new_body
            else:
                new_content = new_body
            new_chunk = MarkdownChunk(
                content=new_content,
                metadata=ChunkMetadata(
                    chunk_id=chunk.metadata.chunk_id if j == 0 else _new_chunk_id(),
                    chunk_index=0,
                    total_chunks=0,
                    char_offset_start=chunk.metadata.char_offset_start,
                    char_offset_end=chunk.metadata.char_offset_end,
                    header_breadcrumb=list(chunk.metadata.header_breadcrumb),
                    header_path=list(chunk.metadata.header_path),
                    has_more=chunk.metadata.has_more,
                    source_meta=dict(chunk.metadata.source_meta),
                ),
            )
            new_chunk.metadata.continuation = chunk.metadata.continuation
            new_chunk.metadata.doc_id = chunk.metadata.doc_id
            new_chunk.metadata.prev_chunk_id = chunk.metadata.prev_chunk_id
            new_chunk.metadata.next_chunk_id = chunk.metadata.next_chunk_id
            new_chunk.metadata.source_element_type = chunk.metadata.source_element_type
            new_chunk.metadata.source_element_position = chunk.metadata.source_element_position
            result.append(new_chunk)
    return result


__all__ = [
    "compute_breadcrumb",
    "compute_end_breadcrumb",
    "collect_headers_in_group",
    "get_table_header_for_group",
    "enforce_hard_max",
    "merge_tiny",
    "inject_missing_breadcrumbs",
    "enrich_rag_metadata",
    "_compute_prefix_for_chunk",
    "_re_split_with_prefix_budget",
    "_extract_intro_text",
]

