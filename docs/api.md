# API Reference

[中文版](zh-CN/api.md)

This page documents every public name exported by `structchunk`. All names can be
imported directly from the top-level package:

```python
import structchunk

structchunk.chunk(...)
structchunk.MarkdownChunk
structchunk.BlockType
# etc.
```

## High-level Functions

These are the recommended entry points for most users.

---

### `chunk()`

```python
chunk(
    content: str,
    *,
    algorithm: str = "hierarchical",
    max_chars: int | None = None,
    forward_intro_text: bool = True,
    **kwargs,
) -> list[MarkdownChunk]
```

Chunk markdown content for RAG.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `content` | `str` | (required) | The raw markdown text to chunk. |
| `algorithm` | `str` | `"hierarchical"` | `"linear"` for greedy block-by-block chunking; `"hierarchical"` for document-tree based, semantically coherent chunks. |
| `max_chars` | `int \| None` | `None` | Convenience cap (e.g. 500 for Dify). If set, every chunk is guaranteed to be at most `max_chars` characters. Sets both `max_chunk_size` (80%) and `hard_max_size` (100%). |
| `forward_intro_text` | `bool` | `True` | Whether to forward introductory text for tables and lists (see `ChunkerConfig`). |

All additional `**kwargs` are forwarded to the selected algorithm's chunk function.
If `doc_id` is not provided, it is auto-derived from a SHA-256 hash of the content
(first 16 hex characters).

**Returns:** `list[MarkdownChunk]`

**Raises:** `ValueError` if `algorithm` is not `"linear"` or `"hierarchical"`, or if
`max_chars` is set to a non-positive value.

---

### `chunk_file()`

```python
chunk_file(
    path: str,
    *,
    algorithm: str = "hierarchical",
    forward_intro_text: bool = True,
    **kwargs,
) -> list[MarkdownChunk]
```

Read a markdown file and chunk it. The file's absolute path is used as `doc_id`
unless the caller provides one explicitly.

---

### `chunk_to_dicts()`

```python
chunk_to_dicts(chunks: list[MarkdownChunk]) -> list[dict]
```

Serialize a chunk list to JSON-friendly dicts. Each chunk is converted via
`MarkdownChunk.to_dict()`. Identifier fields are emitted as decimal strings.

## Low-level Functions

These functions implement the two chunking algorithms. They are called internally
by `chunk()` but can also be used directly when you want to bypass the dispatch
logic.

---

### `chunk_linear()`

```python
chunk_linear(content: str, **kwargs) -> list[MarkdownChunk]
```

Greedy block-by-block chunking. Each block (paragraph, table, list, code fence) is
added to the current chunk until the size cap is reached, then a new chunk starts.
Oversized blocks are delegated to type-specific sub-splitters: paragraphs split at
sentence boundaries, tables at row boundaries, lists at item boundaries, code fences
at line boundaries.

---

### `chunk_hierarchical()`

```python
chunk_hierarchical(content: str, **kwargs) -> list[MarkdownChunk]
```

Document-tree based chunking. Builds a section tree from the document's header
hierarchy, then walks it bottom-up, emitting one chunk per section that fits within
the size cap. Oversized sections are sub-split at natural boundaries. Adjacent
same-level sibling sections are greedily merged when they fit together.

## Data Classes

---

### `MarkdownChunk`

```python
@dataclass
class MarkdownChunk:
    content: str
    metadata: ChunkMetadata
```

A single chunk: content plus rich metadata.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `content` | `str` | The chunk text content. |
| `metadata` | `ChunkMetadata` | All metadata attached to this chunk. |

**Properties:**

| Property | Return Type | Description |
|----------|-------------|-------------|
| `chunk_id_hex` | `str` | The `chunk_id` as a 16-char lowercase hex string. Use for JSON output, log lines, and debugging. |
| `chunk_id_str` | `str` | The `chunk_id` as a decimal string (matches `str(int)`). This is the format Twitter, Discord, and Instagram use in their JSON APIs. |

**Methods:**

`expand(include_breadcrumb: bool = True) -> str`
:   Return the chunk content expanded with breadcrumb context. Implements the
    "small-to-big" retrieval pattern: embed the compact `.content` for vector
    similarity, but feed the expanded version to the LLM for richer context.

`recompute_lengths() -> None`
:   Re-derive all length fields (`content_length`, `breadcrumb_length`,
    `total_length`) from the current field values. Use after any post-creation
    mutation that changes the content or breadcrumb fields.

`to_dict() -> dict`
:   Serialize to a JSON-friendly dict. Identifier fields are emitted as decimal
    strings. The raw int is on `self.metadata.chunk_id` for code that wants to
    skip the string conversion.

---

### `ChunkMetadata`

```python
@dataclass
class ChunkMetadata:
```

All metadata fields attached to a `MarkdownChunk`. Identifier fields
(`chunk_id` / `prev_chunk_id` / `next_chunk_id`) are raw 64-bit Snowflake
ints, exactly what a SQL `BIGINT` column stores. Use 0 as the sentinel for
"no predecessor / no successor".

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | `int` | Unique Snowflake ID for this chunk (64-bit). |
| `chunk_index` | `int` | Zero-based index of this chunk in the document's chunk list. |
| `total_chunks` | `int` | Total number of chunks for the document. |
| `char_offset_start` | `int` | Start character offset into the original document. |
| `char_offset_end` | `int` | End character offset (exclusive) into the original document. |
| `header_breadcrumb` | `list[str]` | Breadcrumb entries with markdown-level prefix, e.g. `['# H1', '## H2', '### H3']`. |
| `header_path` | `list[HeaderInfo]` | Structured header path as `HeaderInfo` objects. |
| `has_more` | `bool` | Whether there are more chunks after this one (convenience flag). |
| `source_meta` | `dict` | Arbitrary source metadata. |
| `doc_id` | `str` | Document identifier. All chunks from the same document share this. Auto-derived from file path (via `chunk_file()`) or content hash (via `chunk()`). |
| `prev_chunk_id` | `int` | Snowflake ID of the previous chunk in sequence (0 if none). |
| `next_chunk_id` | `int` | Snowflake ID of the next chunk in sequence (0 if none). |
| `source_element_type` | `str` | The `BlockType` name of the first block in this chunk. |
| `source_element_position` | `str` | Position description of the source element. |
| `continuation` | `bool` | Whether this chunk is a continuation of a split block. |
| `content_length` | `int` | Pre-computed character length of `content`. Set automatically by `__post_init__`. |
| `breadcrumb_length` | `int` | Pre-computed character length of the breadcrumb. Set automatically by `__post_init__`. |
| `total_length` | `int` | Pre-computed total length (`content_length`). Set automatically by `__post_init__`. |
| `is_section_complete` | `bool` | Section-complete invariant for the hierarchical algorithm. `True` means the entire section lives in this chunk. |

---

### `AtomicBlock`

```python
@dataclass
class AtomicBlock:
    block_type: BlockType
    lines: list[str]
    char_start: int
    char_end: int
    meta: dict = {}
```

An unsplittable unit of markdown content. `meta` carries type-specific extras
(level for headers, lang for code, header_rows for tables, ordered for lists, etc.).

---

### `HeaderInfo`

```python
@dataclass
class HeaderInfo:
    level: int
    text: str
```

A header entry in the breadcrumb stack.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `level` | `int` | Header level (1-6, corresponding to `#` through `######`). |
| `text` | `str` | The header text content (without the `#` prefix). |

## Enumerations

---

### `BlockType`

```python
class BlockType(Enum):
```

Type of an atomic markdown block. Each value corresponds to a distinct structural
element in the markdown document.

| Value | Description |
|-------|-------------|
| `FRONTMATTER` | YAML/TOML frontmatter block at the start of a document. |
| `HEADER` | A markdown header (`#` through `######`). |
| `CODE_FENCE` | A fenced code block. |
| `TABLE` | A complete markdown table. |
| `TABLE_ROW` | An individual row within a table. |
| `LIST` | A list (ordered or unordered). |
| `BLOCKQUOTE` | A blockquote section. |
| `MATH_BLOCK` | A math block (e.g. `$$...$$`). |
| `HR` | A horizontal rule (`---`, `***`, `___`). |
| `PARAGRAPH` | A plain text paragraph. |
| `BLANK` | An empty/blank line. |

## Utility Functions

---

### `chunk_id_timestamp_ms()`

```python
chunk_id_timestamp_ms(chunk_id: int | str) -> int
```

Recover the millisecond timestamp embedded in a Snowflake chunk ID.

Accepts the raw `int` (canonical) or a string in either decimal (preferred,
what `str(int_chunk_id)` produces) or hex (for legacy callers). Returns 0 for
non-Snowflake inputs.

**Returns:** Unix timestamp in milliseconds, or 0 if the input is not a valid
Snowflake ID.

## Configuration

---

### `ChunkerConfig`

```python
@dataclass
class ChunkerConfig:
```

Configuration shared by the linear and hierarchical chunkers. Pass individual
fields as keyword arguments to `chunk()`, `chunk_linear()`, or
`chunk_hierarchical()`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_chunk_size` | `int` | `1500` | Soft upper limit on chunk size in characters. |
| `hard_max_size` | `int` | `3000` | Absolute maximum. A chunk is never larger than this. |
| `min_chunk_size` | `int` | `50` | Don't produce chunks smaller than this (merge with neighbours). |
| `sub_split_table` | `bool` | `True` | Allow splitting oversized tables at row boundaries. |
| `sub_split_code` | `bool` | `True` | Allow splitting oversized code blocks at line boundaries. |
| `sub_split_list` | `bool` | `True` | Allow splitting oversized lists at item boundaries. |
| `sub_split_paragraph` | `bool` | `True` | Allow splitting oversized paragraphs at sentence boundaries. |
| `preserve_table_header` | `bool` | `True` | When a table is split across chunks, prepend the header row(s) to each continuation chunk. |
| `preserve_code_fence` | `bool` | `True` | When a code block is split, re-open/close fences in each chunk. |
| `doc_id` | `str` | `""` | Optional document identifier propagated to every chunk's metadata. |
| `forward_intro_text` | `bool` | `True` | When a section's first table or list is immediately preceded by a plain-text paragraph (not a markdown header), the paragraph's last sentence is forwarded to split continuations as an implicit title. Set to `False` to disable. |

## Version

---

### `__version__`

```python
__version__: str = "0.1.0"
```

The package version string, following [Semantic Versioning](https://semver.org/).
