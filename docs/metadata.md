# ChunkMetadata Reference

[中文版](zh-CN/metadata.md)

## Overview

Every `MarkdownChunk` returned by `chunk()` carries a `ChunkMetadata` object with
19 fields covering identifiers, position, source provenance, continuation
state, character counts, and section completeness. These fields are
designed for direct storage in a SQL database (e.g. as a `chunks` table with
a `BIGINT PRIMARY KEY` and various filterable columns) and for retrieval
ranking during RAG (e.g. breadcrumb-based boosting).

For the JSON-friendly serialization, see [`MarkdownChunk.to_dict()`](api.md#markdown-chunk).

## Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | `int` | Snowflake-like 64-bit unique id. Maps to SQL `BIGINT`. |
| `prev_chunk_id` | `int` | The `chunk_id` of the previous chunk, or `0` if this is the first. |
| `next_chunk_id` | `int` | The `chunk_id` of the next chunk, or `0` if this is the last. |
| `chunk_index` | `int` | 0-based position of this chunk in the document. |
| `total_chunks` | `int` | Total number of chunks in the document. |
| `doc_id` | `str` | Document identifier (SHA-256 content hash for strings, file path for `chunk_file`). |
| `header_breadcrumb` | `list[str]` | Ordered list of parent headers with markdown-level prefix, e.g. `['# H1', '## H2']`. |
| `header_path` | `list[HeaderInfo]` | Structured breadcrumb (level + text), parallel to `header_breadcrumb`. |
| `source_element_type` | `str` | Type of source block: `paragraph`, `table`, `list`, `code`, etc. |
| `source_element_position` | `str` | Sequence number of this source block within its type. |
| `source_meta` | `dict` | Type-specific metadata (header level, code language, table column count, etc.). |
| `continuation` | `bool` | `True` if this chunk continues a previous chunk. |
| `has_more` | `bool` | `True` if the source element continues in a subsequent chunk. |
| `char_offset_start` | `int` | Character offset where this chunk starts in the original document. |
| `char_offset_end` | `int` | Character offset where this chunk ends in the original document. |
| `content_length` | `int` | Pre-computed length of `.content` in characters. |
| `breadcrumb_length` | `int` | Pre-computed total length of all breadcrumb entries. |
| `total_length` | `int` | Same as `content_length` since v0.4.0 (the breadcrumb is part of the content). |
| `is_section_complete` | `bool` | `True` if the section fits in one chunk; `False` if this is a tail of a split section. Hierarchical only. |

## Identifier Fields

`chunk_id`, `prev_chunk_id`, and `next_chunk_id` are raw 64-bit Snowflake ints,
exactly what a SQL `BIGINT` column holds. `0` is the sentinel for "no predecessor"
or "no successor" — not a valid Snowflake id.

For JSON output, convert to string with `MarkdownChunk.chunk_id_str` (decimal)
or `MarkdownChunk.chunk_id_hex` (16-char hex). See the [API Reference](api.md#markdown-chunk).

```python
c = chunks[0]
print(c.metadata.chunk_id)        # int, e.g. 188704004562132992
print(c.chunk_id_str)             # str, "188704004562132992"
print(c.chunk_id_hex)             # str, "029f0c9d210b8000" (16 hex chars)
```

## Breadcrumb Fields

`header_breadcrumb` is a `list[str]` with the markdown-level prefix. For example,
a chunk inside `## Section` under `# Title` has:

```python
["# Title", "## Section"]
```

`header_path` is a parallel `list[HeaderInfo]` with structured level/text:

```python
[
    HeaderInfo(level=1, text="Title"),
    HeaderInfo(level=2, text="Section"),
]
```

The H1 document title is included in every chunk's breadcrumb, so embeddings
always have document-level context.

## Position Fields

- `chunk_index` (0-based) and `total_chunks` give the chunk's position in the document.
- `char_offset_start` and `char_offset_end` give the original document's character
  offsets (inclusive start, exclusive end).

Use these to highlight the source span in a UI: from `char_offset_start` to
`char_offset_end` in the original markdown.

## Source Tracking

- `source_element_type` is one of `paragraph`, `table`, `list`, `code`, `header`, `block_quote`, `math`, `hr`, `frontmatter`, etc.
- `source_element_position` is the sequence number of this source block within its type (e.g. the 3rd table in the document).
- `source_meta` carries type-specific extras: header level, code language, table column count, etc.

This lets you group chunks by their source element when building a UI
("show me all chunks from table #3").

## Continuation & Linking

- `continuation = True` means this chunk is a continuation of a previous chunk (a table row that spilled over, a long code block, etc.).
- `has_more = True` means this chunk is followed by at least one more chunk carrying the rest of the same source element.
- `prev_chunk_id` and `next_chunk_id` are the linked-list pointers. Use them to walk a chain forward or backward in O(n) where n is the chain length.

A small example: a long code block might produce 3 chunks `[A, B, C]` with:

```python
A.continuation = False
A.has_more = True
A.next_chunk_id = B.chunk_id

B.continuation = True
B.has_more = True
B.prev_chunk_id = A.chunk_id
B.next_chunk_id = C.chunk_id

C.continuation = True
C.has_more = False
C.prev_chunk_id = B.chunk_id
```

## Length Fields

- `content_length` is `len(c.content)` (pre-computed for fast filtering).
- `breadcrumb_length` is `sum(len(h) for h in c.metadata.header_breadcrumb)`.
- `total_length` equals `content_length` (since v0.4.0, the breadcrumb is part of the content — they're not summed).

These are pre-computed so a database query can filter on `content_length`
without loading the full content (columnar projection optimization).

## Section Completeness

`is_section_complete` is `True` when the entire section lives in this chunk
(whole section was emitted as a single chunk), `False` when this is a
tail/residual of a section that was split across multiple chunks.

Downstream passes (e.g. `merge_tiny`) must not merge a non-section-complete
chunk into a different section's head, since that would mix two distinct
sections into a single breadcrumb-bearing chunk.

This flag is always `True` for chunks produced by the `linear` algorithm
(which has no section concept). Defaults to `True` for externally
constructed chunks (e.g. from deserialization).

## Linked-List Traversal

Walk the chunk chain forward:

```python
chunks = structchunk.chunk(content)
current = chunks[0]
while current is not None:
    print(current.chunk_id_str, current.content[:50])
    next_id = current.metadata.next_chunk_id
    current = next(
        (c for c in chunks if c.metadata.chunk_id == next_id),
        None,
    ) if next_id else None
```

Or backward from the last chunk:

```python
chunks = structchunk.chunk(content)
current = chunks[-1]
while current is not None:
    print(current.chunk_id_str, current.content[:50])
    prev_id = current.metadata.prev_chunk_id
    current = next(
        (c for c in chunks if c.metadata.chunk_id == prev_id),
        None,
    ) if prev_id else None
```
