# structchunk

**Structure-aware text chunking for RAG pipelines.**

Pure-Python. No external dependencies. Two algorithms — pick the one that fits your docs.

## Why

RAG quality lives or dies by chunk quality. Naive splitters break tables, separate headers from their content, and produce chunks whose embeddings can't recover the section context. `structchunk` was built to fix the specific issues that hurt retrieval:

- Headers always **lead** their content (never orphaned at the end of a chunk).
- Tables are split at row boundaries, with the column header prepended to every continuation.
- Every chunk carries an accurate, **in-document-order** header breadcrumb with markdown-level prefix (e.g. `# H1`, `## H2`, `### H3`).
- Long paragraphs are split at sentence boundaries in both Chinese (。) and English (.).
- Tables and lists automatically absorb the preceding paragraph or marker line as context.
- H1 (document title) appears in **every** chunk for full document context.
- No `*[续]*` continuation markers — breadcrumb injection provides parent context.

The current implementation targets **markdown** as the primary input format. Future releases will add plain-text and HTML support.

## Install

```bash
pip install structchunk
```

From source (includes test dependencies):

```bash
git clone https://github.com/yzp0111/structchunk
cd structchunk
pip install -e ".[test]"
```

## Quick start

```python
import structchunk

chunks = structchunk.chunk(
 "# Title\n\nSome content with a long paragraph that needs splitting.",
 max_chars=500, # Dify-friendly: every chunk ≤500 chars
)

for c in chunks:
 print(f"[{c.metadata.chunk_index}] {c.metadata.header_breadcrumb}")
 print(c.content)
 print()
```

Output (default `hierarchical` algorithm):

```
[0] ['# Title']
# Title

Some content with a long paragraph that needs splitting.
```

Note the breadcrumb entry includes the `#` prefix. The H1 document title is present in every chunk.

## Algorithms

| Algorithm | Default | When to use |
|---|---|---|
| `hierarchical` | ✓ | Documents with clear section hierarchy (technical docs, reports, books). Produces semantically coherent chunks that always start at a section header. |
| `linear` | — | Documents without strict section structure, or when you want fine-grained control over split points. Fast. Pass `algorithm="linear"` explicitly to opt in. |

### Linear

Greedy block-by-block assembly. Oversized blocks are delegated to type-specific sub-splitters (paragraph→sentence, table→row, list→item, code→line).

```python
chunks = structchunk.chunk(content, algorithm="linear", max_chars=500)
```

### Hierarchical

Builds a section tree from header hierarchy, walks it bottom-up, and emits one chunk per section that fits. Oversized sections are sub-split. Adjacent same-level sibling sections are greedily merged when they fit together, subject to the **section-complete invariant** (see algorithm details below).

```python
chunks = structchunk.chunk(content, algorithm="hierarchical", max_chars=500)
```

## CLI

After install:

```bash
structchunk document.md # hierarchical (default),500c cap
structchunk document.md --algorithm linear # greedy block-by-block
structchunk document.md --max-chars300 --format json
structchunk document.md --output-dir /tmp/chunks # custom output directory
```

Output files are saved to `./test_result/` by default (override with `--output-dir`).

## Why structchunk?

If you're evaluating chunkers, here's what makes `structchunk` different:

- **Structure-aware**: parses markdown headers, code fences, tables, and lists to find natural break points. Naive splitters (LangChain `CharacterTextSplitter`, etc.) split on character count and break tables mid-row.
- **Hierarchical algorithm**: produces chunks that always start at a section header. Tables get column headers re-prepended on continuation. Lists get a parent paragraph re-injected. H1 is preserved in every chunk.
- **Header-prefix breadcrumbs**: each chunk carries an in-document-order breadcrumb that becomes part of the chunk content, so embeddings see the full context.
- **Snowflake BIGINT chunk IDs**: each chunk gets a64-bit Snowflake-like ID suitable for SQL `BIGINT PRIMARY KEY` columns. Sortable by creation time.
- **Pure Python, no dependencies**: zero external runtime dependencies. Only `pytest` is required for the test suite.
- **Fork-safe**: generator is fork-safe via `os.register_at_fork(after_in_child=...)` (POSIX). Two worker processes won't generate colliding IDs.
- **Clock-resilient**: when the system clock goes backwards (NTP step, suspend/resume), the generator spin-waits up to10ms, then raises `RuntimeError` rather than silently emitting a colliding ID.

## Advanced options

All options are passed as keyword arguments to `chunk()`:

```python
chunks = structchunk.chunk(
 content,
 max_chars=500, # hard cap (Dify default)
 max_chunk_size=1500, # soft cap (try to merge up to this)
 hard_max_size=3000, # absolute cap (never exceed)
 min_chunk_size=50, # tiny chunks get merged with neighbours
 sub_split_paragraph=True, # split long paragraphs at sentence boundaries
 sub_split_table=True, # split oversized tables at row boundaries
 sub_split_code=True, # split oversized code blocks at line boundaries
 sub_split_list=True, # split oversized lists at item boundaries
 preserve_table_header=True, # re-prepend column headers to table continuations
 preserve_code_fence=True, # re-open code fences on continuation chunks
 forward_intro_text=True, # forward leading paragraph to table/list continuations
 doc_id="my-doc-001", # propagate into every chunk's metadata
)
```

## Each chunk carries

- `content` — the text to embed
- `metadata.header_breadcrumb` — full path of parent headers with `#` prefix (e.g. `['# H1', '## H2']`)
- `metadata.header_path` — structured header info (level + text)
- `metadata.source_element_type` — `paragraph`, `table`, `list`, `code`, etc.
- `metadata.source_element_position` — sequence number within type
- `metadata.continuation` — `True` if this chunk continues a previous one
- `metadata.has_more` — `True` if the source element continues in a subsequent chunk
- `metadata.prev_chunk_id` / `next_chunk_id` — linked list for traversal
- `metadata.char_offset_start` / `char_offset_end` — original document offsets
- `metadata.content_length` / `breadcrumb_length` / `total_length` — pre-computed char counts
- `metadata.chunk_id` is a64-bit Snowflake-like **int** (BIGINT-ready); `str(chunk_id)` gives the standard decimal display form
- `metadata.is_section_complete` — `True` if the section fits in one chunk, `False` if it's a tail of a split section

Call `chunk.expand(include_breadcrumb=True)` to get the small-to-big retrieval view: breadcrumb + content.

## Why Snowflake-like chunk_id as a BIGINT int (not a string, not UUID4)

`chunk.metadata.chunk_id` is a64-bit Snowflake-like int (8 bytes) that
maps directly to a SQL `BIGINT` column. `str(chunk_id)` produces the
standard decimal representation.

| Property | Snowflake BIGINT (this library) | UUID4 | Snowflake as string |
|---|---|---|---|
| DB storage | `BIGINT` (8 bytes) | `UUID` (16 bytes) | `VARCHAR(N)` (16+ bytes) |
| Comparison cost | `btint8cmp`:2 register compares | `uuid_cmp`:16 bytes | `varstr_cmp`: collation-bound |
| Sortable by creation time | Yes | No | Yes |
| B-tree index locality | Adjacent IDs cluster | Random | Same as BIGINT |
| Round-trip with `int(s)` | Yes | No | Only with base arg |
| Industry usage | Twitter, Discord, Instagram, Snowflake (the DB) | Web app records | Almost nobody |

For RAG workloads with bulk inserts and time-range queries, BIGINT
Snowflake ids are the standard choice. The embedded timestamp is
recoverable via `structchunk.chunk_id_timestamp_ms(chunk_id)`.

**Timestamp saturation:** with the current epoch (2026-01-01) and41-bit timestamp field, the Snowflake id saturates around **2095-08-15**. After that, IDs would overflow the standard SQL `BIGINT` range and may be rejected by databases.

`doc_id` is a SHA-256 content hash (16 hex chars) when chunking strings, or
the absolute file path when chunking files — same document, same `doc_id`.

## Database schema (PostgreSQL example)

```sql
CREATE TABLE chunks (
 chunk_id BIGINT PRIMARY KEY, -- Snowflake int,8 bytes
 doc_id TEXT NOT NULL, -- content hash or file path
 chunk_index INT NOT NULL,
 total_chunks INT NOT NULL,
 content TEXT NOT NULL,
 content_length INT NOT NULL, -- pre-computed, filterable
 total_length INT NOT NULL, -- same as content_length since v0.4.0
 header_breadcrumb TEXT[],
 embedding VECTOR(1024), -- pgvector column
 created_at_ms BIGINT GENERATED ALWAYS AS
 (structchunk.chunk_id_timestamp_ms(chunk_id)) STORED
);
```

## Algorithm details

### Sentence boundary splitting

Long paragraphs are split at sentence boundaries using a regex that handles both Chinese (`。！？`) and English (`.!?`):

- Matches a non-terminator run followed by terminators and optional whitespace
- Falls back to trailing fragments without terminators
- Single sentences are never broken — only force-split when one sentence alone exceeds `hard_max_size`

### Header pull-up

A header at the END of a group semantically belongs to the NEXT group's content, so it's moved forward. This guarantees headers always lead their content.

### Context absorption

When a TABLE or LIST starts a new group, the algorithm looks back for the most recent non-blank, non-table/list block (a paragraph, a `**首选：XXX**` marker, etc.) and absorbs it as context — if it fits within the hard limit. This is the "effective summary" the user wants for RAG.

**Intro text forwarding**: When a section's first table or list is preceded by a plain-text paragraph (not a markdown header), the paragraph's last sentence is forwarded to split continuation chunks as the implicit "title" of the table/list. This prevents continuation chunks from appearing contextually orphaned. Configurable via `forward_intro_text` (default `True`).

### RAG breadcrumb (in document order, with `#` prefix)

Built in two steps:

1. Take the end-of-group breadcrumb (correctly pops stale same-level headers).
2. Strip its last entry, then re-add **all** in-group headers in document order. This avoids two bugs at once:
 - Stale same-level headers (e.g. `表1` leaking into a `表2` chunk)
 - Wrong order (e.g. `场景4` listed before `场景3`)

Breadcrumb entries now include the markdown-level prefix, e.g. `['# H1', '## H2', '### H3']`.

### Missing-breadcrumb injection

After assembly, a post-pass prepends any breadcrumb header not present in the content. H1 (document title) is included in every chunk. Ensures every chunk is self-contained for embedding.

### Hierarchical sibling-merge (section-complete invariant)

The hierarchical algorithm's merge logic enforces a **section-complete invariant**: a chunk that represents a *complete* section (the entire section fits in one chunk) can merge with adjacent same-level sibling sections; a *residual/tail* chunk from a split section cannot. This prevents cross-contamination where a section's tail incorrectly merges into a different sibling's content.

Internally, the `_section_to_chunks` function marks each emitted chunk with an `is_section_complete` flag. The merge pass checks this flag before combining adjacent siblings, enforcing the "完整同级" (complete same-level) rule:

- Same-level sibling sections whose combined size fits within `max_chars` are merged.
- A split section's tail chunk (flagged `is_section_complete=False`) never merges with a different section's head.
- H1 boundaries are always preserved.

## Development

```bash
git clone https://github.com/yzp0111/structchunk
cd structchunk
pip install -e ".[test]"
pytest
```

> **Note**: `test_result/` is a dev-only CLI output directory; it is git-ignored.

Run the example:

```bash
python examples/basic.py path/to/file.md
```

Project layout:
```
src/structchunk/
├── __init__.py # public API: chunk, chunk_file, chunk_to_dicts
├── _version.py
├── _config.py # ChunkerConfig
├── _models.py # AtomicBlock, BlockType, MarkdownChunk, ChunkMetadata
├── _parser.py # _parse_atomic_blocks, regex constants
├── _splitters.py # sentence / table / list / code sub-splitters
├── _enrich.py # breadcrumb, RAG metadata
├── linear.py # linear (greedy) chunker
├── hierarchical.py # hierarchical (tree) chunker
└── _cli.py # CLI entry point
examples/
└── basic.py # basic usage demo (both algorithms)
```

## License

MIT
