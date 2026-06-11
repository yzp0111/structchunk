"""Hierarchical (document-tree) markdown chunker.

Builds a section tree from header hierarchy, then walks it bottom-up.
Each section that fits within ``max_chars`` becomes one chunk; oversized
sections are sub-split; small sibling sections under the same parent
can be greedily merged.

The result: every chunk clearly belongs to a section, headers always
lead their content, and no "table tail + next section header" mashups.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from ._config import ChunkerConfig
from ._enrich import (
    _extract_intro_text,
    _re_split_with_prefix_budget,
    enrich_rag_metadata,
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


@dataclass
class _Section:
    header: HeaderInfo | None
    level: int
    blocks: list[AtomicBlock]
    children: list["_Section"] = field(default_factory=list)

    def text(self) -> str:
        parts: list[str] = []
        if self.header:
            parts.append(f"{'#' * self.header.level} {self.header.text}")
        for b in self.blocks:
            if b.block_type != BlockType.BLANK:
                parts.append(_block_text(b))
        return "\n\n".join(parts)

    def section_size(self) -> int:
        return len(self.text())

    def breadcrumb(
        self, parent_path: list[HeaderInfo] | None = None
    ) -> list[HeaderInfo]:
        path = list(parent_path) if parent_path else []
        if self.header:
            while path and path[-1].level >= self.header.level:
                path.pop()
            path.append(self.header)
        return path


def _build_section_tree(blocks: list[AtomicBlock]) -> _Section:
    root = _Section(header=None, level=0, blocks=[], children=[])
    stack: list[_Section] = [root]

    for block in blocks:
        if block.block_type == BlockType.HEADER:
            level = block.meta.get("level", 1)
            text = block.meta.get("text", "")
            hdr = HeaderInfo(level, text)
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            section = _Section(header=hdr, level=level, blocks=[], children=[])
            stack[-1].children.append(section)
            stack.append(section)
        else:
            stack[-1].blocks.append(block)

    return root


def _sub_split_block_h(block: AtomicBlock, max_size: int, hard_max: int) -> list[str]:
    bt = _block_text(block)
    if block.block_type == BlockType.PARAGRAPH:
        return split_paragraph_at_sentences(bt, max_size, hard_max)
    if block.block_type == BlockType.CODE_FENCE:
        return split_code_block(
            block.lines, max_size, hard_max,
            lang=block.meta.get("lang", ""),
        )
    if block.block_type in (BlockType.TABLE, BlockType.TABLE_ROW):
        header_rows = block.meta.get("header_rows", [])
        data_rows = (
            block.lines[len(header_rows):]
            if block.block_type == BlockType.TABLE
            else block.lines
        )
        if header_rows:
            return split_table_rows(header_rows, data_rows, max_size, hard_max)
        return _force_split_long_strings([bt], hard_max)
    if block.block_type == BlockType.LIST:
        return split_list_items(block.lines, max_size, hard_max)
    return _force_split_long_strings([bt], hard_max)


def _split_oversized_text(
    text: str, max_size: int, hard_max: int, blocks: list[AtomicBlock]
) -> list[str]:
    if len(text) <= max_size:
        return [text]

    parts: list[str] = []
    current = ""
    for block in blocks:
        if block.block_type == BlockType.BLANK:
            continue
        bt = _block_text(block)
        if not current:
            current = bt
        elif len(current) + len(bt) + 2 <= max_size:
            current = current + "\n\n" + bt
        else:
            if len(bt) > max_size:
                sub = _sub_split_block_h(block, max_size, hard_max)
                if sub:
                    if current:
                        sub[0] = current + "\n\n" + sub[0]
                    parts.extend(sub)
                elif current:
                    parts.append(current)
                current = ""
            else:
                if current:
                    parts.append(current)
                current = bt
    if current:
        parts.append(current)

    return _force_split_long_strings(parts, hard_max)


def _dominant_type(blocks: list[AtomicBlock]) -> str:
    """Return the dominant content type of a section's blocks.

    Priority: TABLE/TABLE_ROW > LIST > CODE > PARAGRAPH.
    A section containing a table is primarily a table, even if it also
    has a leading paragraph (e.g. an intro paragraph like "表0：xxx").
    Per user request 2026-06-10, chunks containing tables should be
    labeled src=table, not src=paragraph.
    """
    # Check for structured content first
    for b in blocks:
        if b.block_type in (BlockType.TABLE, BlockType.TABLE_ROW):
            return "table"
        if b.block_type == BlockType.LIST:
            return "list"
        if b.block_type == BlockType.CODE_FENCE:
            return "code"
    # Fall back to first non-blank/non-header block
    for b in blocks:
        if b.block_type != BlockType.BLANK and b.block_type != BlockType.HEADER:
            return b.block_type.name.lower()
    if blocks and blocks[0].block_type == BlockType.HEADER:
        return "header"
    return "paragraph"


def _has_content_blocks(blocks: list[AtomicBlock]) -> bool:
    """True when *blocks* contains at least one non-blank, non-header block."""
    return any(
        b.block_type not in (BlockType.BLANK, BlockType.HEADER)
        for b in blocks
    )


def _apply_continuation_forwarding(
    sub_parts: list[str],
    blocks: list[AtomicBlock],
    header_text: str,
    config: ChunkerConfig,
) -> list[str]:
    """Apply table-header, intro-text, and *[续]* forwarding to sub_parts.

    Used in BOTH the leaf-split path and the merge path of
    _section_to_chunks() so the forwarding semantics are consistent
    regardless of whether a section has child sub-sections.

    Mutates and returns sub_parts in place (caller convenience).
    """
    if not sub_parts or len(sub_parts) <= 1:
        return sub_parts
    # 1. Forward table column header rows.
    table_header_lines: list[str] = []
    for b in blocks:
        if b.block_type in (BlockType.TABLE, BlockType.TABLE_ROW):
            hr = b.meta.get("header_rows", [])
            if hr:
                table_header_lines = hr
                break
    if table_header_lines:
        table_header_str = "\n".join(table_header_lines)
        for i in range(1, len(sub_parts)):
            if table_header_str not in sub_parts[i]:
                sub_parts[i] = table_header_str + "\n\n" + sub_parts[i]
    # 2. Forward plain-text intro (last sentence of paragraph before table/list).
    if config.forward_intro_text:
        intro_text = _extract_intro_text(blocks)
        if intro_text:
            for i in range(1, len(sub_parts)):
                if intro_text not in sub_parts[i]:
                    sub_parts[i] = intro_text + "\n\n" + sub_parts[i]
    # 3. Forward section header (first sub-part gets the full header;
    #    continuation sub-parts get no marker — the breadcrumb injection
    #    in inject_missing_breadcrumbs handles context for continuations).
    #    NOTE: *[续]* marker removed (user request 2026-06-10).
    if header_text:
        sub_parts[0] = header_text + "\n\n" + sub_parts[0]
    return sub_parts


def _section_to_chunks(
    section: _Section,
    parent_path: list[HeaderInfo],
    max_size: int,
    hard_max: int,
    min_size: int,
    config: ChunkerConfig,
) -> list[dict]:
    my_path = section.breadcrumb(parent_path)
    # header_breadcrumb entries include the markdown-level prefix for clarity
    # (e.g. '# H1', '## H2', '### H3'). User request 2026-06-10.
    my_bc = [f"{'#' * h.level} {h.text}" for h in my_path]
    own_text = section.text()
    own_size = len(own_text) if own_text else 0
    header_text = (
        f"{'#' * section.header.level} {section.header.text}"
        if section.header
        else ""
    )

    if not section.children:
        et = _dominant_type(section.blocks)
        if own_size == 0:
            return []
        section_block_types = [b.block_type.name for b in section.blocks if b.block_type != BlockType.BLANK]
        if own_size <= max_size:
            return [{
                "content": own_text,
                "breadcrumb": list(my_bc),
                "header_path": list(my_path),
                "element_type": et,
                "is_continuation": False,
                "is_section_complete": True,
                "block_types": list(section_block_types),
            }]
        sub_parts = _split_oversized_text(own_text, max_size, hard_max, section.blocks)
        # Apply table-header, intro, and *[续]* forwarding.
        _apply_continuation_forwarding(sub_parts, section.blocks, header_text, config)
        # Split leaf: no part is section-complete (section was emitted as
        # multiple chunks), so none can cross-level merge at parent level.
        # All sub-parts carry the same block_types (from the section's blocks)
        # so downstream consumers see the full set of types present in the chunk.
        return [
            {
                "content": p,
                "breadcrumb": list(my_bc),
                "header_path": list(my_path),
                "element_type": et,
                "is_continuation": (i > 0),
                "is_section_complete": False,
                "block_types": list(section_block_types),
            }
            for i, p in enumerate(sub_parts)
        ]

    child_chunks: list[list[dict]] = []
    for child in section.children:
        child_chunks.append(
            _section_to_chunks(child, my_path, max_size, hard_max, min_size, config)
        )

    flat_children = [c for cl in child_chunks for c in cl]
    all_text_parts: list[str] = []
    if own_text:
        all_text_parts.append(own_text)
    for fc in flat_children:
        all_text_parts.append(fc["content"])
    all_text = "\n\n".join(all_text_parts)

    if len(all_text) <= max_size and all_text.strip():
        all_bc = list(my_bc)
        all_hp = list(my_path)
        all_block_types: list[str] = []
        seen_bt: set[str] = set()
        for fc in flat_children:
            for h in fc["breadcrumb"]:
                if h not in all_bc:
                    all_bc.append(h)
            for hp_entry in fc.get("header_path", []):
                if hp_entry not in all_hp:
                    all_hp.append(hp_entry)
            for bt in fc.get("block_types", []):
                if bt not in seen_bt:
                    seen_bt.add(bt)
                    all_block_types.append(bt)
        for b in section.blocks:
            if b.block_type != BlockType.BLANK:
                bt_name = b.block_type.name
                if bt_name not in seen_bt:
                    seen_bt.add(bt_name)
                    all_block_types.append(bt_name)
        et = _dominant_type(section.blocks)
        if et == "paragraph" and not _has_content_blocks(section.blocks) and flat_children:
            et = flat_children[0]["element_type"]
        return [{
            "content": all_text,
            "breadcrumb": all_bc,
            "header_path": all_hp,
            "element_type": et,
            "is_continuation": False,
            "is_section_complete": True,
            "block_types": all_block_types,
        }]

    if own_text and flat_children:
        combined = own_text + "\n\n" + flat_children[0]["content"]
        combined_bc = list(my_bc)
        combined_hp = list(my_path)
        for h in flat_children[0]["breadcrumb"]:
            if h not in combined_bc:
                combined_bc.append(h)
        for hp_entry in flat_children[0].get("header_path", []):
            if hp_entry not in combined_hp:
                combined_hp.append(hp_entry)
        combined_block_types: list[str] = []
        seen_bt2: set[str] = set()
        for b in section.blocks:
            if b.block_type != BlockType.BLANK:
                bt_name = b.block_type.name
                if bt_name not in seen_bt2:
                    seen_bt2.add(bt_name)
                    combined_block_types.append(bt_name)
        for bt in flat_children[0].get("block_types", []):
            if bt not in seen_bt2:
                seen_bt2.add(bt)
                combined_block_types.append(bt)
        if len(combined) <= hard_max:
            flat_children[0] = {
                "content": combined,
                "breadcrumb": combined_bc,
                "header_path": combined_hp,
                "element_type": _dominant_type(section.blocks)
                if _has_content_blocks(section.blocks)
                else flat_children[0]["element_type"],
                "is_continuation": False,
                "is_section_complete": True,
                "block_types": combined_block_types,
            }
        else:
            own_block_types_pre = [b.block_type.name for b in section.blocks if b.block_type != BlockType.BLANK]
            own_parts = _split_oversized_text(
                own_text, max_size, hard_max, section.blocks
            )
            for sp_idx, sp in enumerate(reversed(own_parts)):
                child_et = flat_children[0]["element_type"] if flat_children else "paragraph"
                flat_children.insert(
                    0,
                    {
                        "content": sp,
                        "breadcrumb": list(my_bc),
                        "header_path": list(my_path),
                        "element_type": _dominant_type(section.blocks)
                        if _has_content_blocks(section.blocks)
                        else child_et,
                        "is_continuation": (sp_idx > 0),
                        "is_section_complete": False,
                        "block_types": list(own_block_types_pre),
                    },
                )
            # Apply table-header, intro, and *[续]* forwarding to the prepended
            # own_parts (which are now at the start of flat_children).
            if own_parts:
                prepended_strings = [
                    flat_children[i]["content"] for i in range(len(own_parts))
                ]
                forwarded = _apply_continuation_forwarding(
                    prepended_strings, section.blocks, header_text, config
                )
                for i, content in enumerate(forwarded):
                    flat_children[i]["content"] = content

    result: list[dict] = []
    merge_buffer: list[dict] = []
    merge_size = 0

    # Use LCP (longest common prefix) instead of single-entry strip. This
    # allows cross-level sibling merge (e.g. a H2 chunk and an adjacent H2
    # chunk sharing H1 as common ancestor). H1 boundary is preserved because
    # different H1s have LCP=[].
    def _lcp(a: list[str], b: list[str]) -> list[str]:
        n = min(len(a), len(b))
        for i in range(n):
            if a[i] != b[i]:
                return a[:i]
        return a[:n]

    def _can_merge_with_buffer(last: dict, cur: dict) -> bool:
        last_bc = last["breadcrumb"]
        cur_bc = cur["breadcrumb"]
        if last_bc == cur_bc:
            return True  # same section (continuation), can always merge
        # Cross-section: require both chunks to represent a complete section
        # (their parent section was emitted as a single chunk). A tail from a
        # split section must NOT cross-level merge into an adjacent sibling —
        # that would violate the "完整同级" rule.
        if not last.get("is_section_complete", False):
            return False
        if not cur.get("is_section_complete", False):
            return False
        common = _lcp(last_bc, cur_bc)
        return bool(common)  # different H1s (LCP empty) cannot merge

    def _emit_buffer(buf: list[dict]) -> dict:
        merged_text = "\n\n".join(c["content"] for c in buf)
        merged_bc = list(my_bc)
        merged_hp = list(my_path)
        merged_block_types: list[str] = []
        seen_bt3: set[str] = set()
        for c in buf:
            for h in c["breadcrumb"]:
                if h not in merged_bc:
                    merged_bc.append(h)
            for hp_entry in c.get("header_path", []):
                if hp_entry not in merged_hp:
                    merged_hp.append(hp_entry)
            for bt in c.get("block_types", []):
                if bt not in seen_bt3:
                    seen_bt3.add(bt)
                    merged_block_types.append(bt)
        merged_et = buf[0]["element_type"] if buf else "paragraph"
        # Preserve continuation flag on single-element flush; otherwise
        # a split-section tail would lose its split-status and become
        # mergeable with a new sibling at the ancestor level.
        merged_cont = (
            False
            if len(buf) > 1
            else bool(buf[0].get("is_continuation", False))
        )
        # is_section_complete is set by the outer post-merge-loop pass,
        # based on whether THIS section emitted as 1 chunk (True) or N (False).
        return {
            "content": merged_text,
            "breadcrumb": merged_bc,
            "header_path": merged_hp,
            "element_type": merged_et,
            "is_continuation": merged_cont,
            "block_types": merged_block_types,
        }

    for cc in flat_children:
        cc_size = len(cc["content"])
        if (
            merge_buffer
            and _can_merge_with_buffer(merge_buffer[-1], cc)
            and merge_size + cc_size + 2 <= hard_max  # Use hard_max (user's max_chars) as sibling-merge threshold, not max_size (soft cap). Per user spec: merge whenever combined < max_chars.
        ):
            merge_buffer.append(cc)
            merge_size += cc_size + 2
        else:
            if merge_buffer:
                result.append(_emit_buffer(merge_buffer))
                merge_buffer = []
                merge_size = 0

            if cc_size <= max_size:
                merge_buffer = [cc]
                merge_size = cc_size
            else:
                result.append(cc)
                merge_buffer = []
                merge_size = 0

    if merge_buffer:
        result.append(_emit_buffer(merge_buffer))

    # Mark is_section_complete on this section's emitted chunks. If THIS
    # section was emitted as a single chunk, that chunk is section-complete
    # (the whole section lives in one piece). If THIS section was emitted
    # as multiple chunks, NONE of them are section-complete — the section
    # was split, so its pieces are residuals/tails relative to broader
    # sibling-merge at the parent level (per "完整同级" rule).
    if len(result) == 1:
        result[0]["is_section_complete"] = True
    elif len(result) > 1:
        for r in result:
            r["is_section_complete"] = False

    return result


def chunk_hierarchical(
    content: str,
    *,
    max_chars: int | None = None,
    max_chunk_size: int = 1500,
    hard_max_size: int = 3000,
    min_chunk_size: int = 50,
    preserve_table_header: bool = True,
    preserve_code_fence: bool = True,
    sub_split_table: bool = True,
    sub_split_list: bool = True,
    sub_split_paragraph: bool = True,
    doc_id: str = "",
    forward_intro_text: bool = True,
) -> list[MarkdownChunk]:
    """Chunk markdown content using the document-tree (hierarchical) algorithm."""
    if not content or not content.strip():
        return []

    if max_chars is not None:
        hard_max_size = max_chars
        max_chunk_size = max(1, int(max_chars * 0.8))

    blocks = _parse_atomic_blocks(content)
    blocks = [b for b in blocks if b.block_type != BlockType.BLANK]
    if not blocks:
        return []

    tree = _build_section_tree(blocks)
    config = ChunkerConfig(
        max_chunk_size=max_chunk_size,
        hard_max_size=hard_max_size,
        min_chunk_size=min_chunk_size,
        preserve_table_header=preserve_table_header,
        forward_intro_text=forward_intro_text,
    )
    raw = _section_to_chunks(tree, [], max_chunk_size, hard_max_size, min_chunk_size, config)
    if not raw:
        return []

    chunks: list[MarkdownChunk] = []
    offset = 0
    for r in raw:
        content_text = r["content"]
        bc = r["breadcrumb"]
        hp = r.get("header_path", [])
        et = r["element_type"]
        # Use the threaded block_types if present (P1 D consistency with
        # linear.py), else fall back to the single dominant type.
        block_types_meta = r.get("block_types") or [et.upper()]
        chunk = MarkdownChunk(
            content=content_text,
            metadata=ChunkMetadata(
                chunk_id=_new_chunk_id(),
                chunk_index=0,
                total_chunks=0,
                char_offset_start=offset,
                char_offset_end=offset + len(content_text),
                header_breadcrumb=bc,
                header_path=hp,
                has_more=False,
                source_element_type=et,
                source_element_position="",
                source_meta={
                    "dominant_type": et.upper(),
                    "block_types": list(block_types_meta),
                },
                is_section_complete=r.get("is_section_complete", True),
            ),
        )
        chunks.append(chunk)
        offset += len(content_text)

    # First pass: split based on chunk content (no breadcrumb inlined yet)
    chunks = _re_split_with_prefix_budget(chunks, hard_max_size)
    # Inject missing breadcrumb headers
    inject_missing_breadcrumbs(chunks)
    # Second pass: after breadcrumb injection, chunks may exceed hard_max_size
    # because the injected prefix wasn't accounted for in the first pass.
    # Re-apply the prefix-aware re-split so chunks with the inlined prefix
    # are properly split to fit within the cap.
    chunks = _re_split_with_prefix_budget(chunks, hard_max_size)
    chunks = merge_tiny(chunks, config)

    total = len(chunks)
    for i, chunk in enumerate(chunks):
        chunk.metadata.chunk_index = i
        chunk.metadata.total_chunks = total
        chunk.metadata.has_more = i < total - 1

    enrich_rag_metadata(chunks, ChunkerConfig(doc_id=doc_id))

    return chunks


__all__ = ["chunk_hierarchical"]
