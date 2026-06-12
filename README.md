# structchunk

Structure-aware text chunking for RAG pipelines. v0.1.0

> Pure-Python, zero external dependencies. Two algorithms for markdown chunking: hierarchical (section-tree based, semantically coherent chunks) and linear (greedy block-by-block, fast). Every chunk carries a header breadcrumb for full document context, and Snowflake-like BIGINT IDs for database-friendly storage.

[中文版](README.zh-CN.md)

## Features

structchunk solves the core problems that hurt retrieval quality in RAG pipelines:
headers orphaned from content, tables broken mid-row, chunks missing section context.
It works on markdown documents and produces chunks that respect the document structure.

- **Structure-aware parsing**: respects markdown headers, code fences, tables, and lists to find natural break points. Naive splitters (LangChain CharacterTextSplitter, etc.) split on character count and break tables mid-row.

- **Two algorithms**: `hierarchical` (default, section-tree based) produces chunks that always start at a section header. `linear` (greedy block-by-block) gives fine-grained control over split points.

- **Header-prefix breadcrumbs**: each chunk carries an in-document-order breadcrumb with markdown-level prefix (e.g., `['# H1', '## H2', '### H3']`) that becomes part of the chunk content. Embeddings see the full section context.

- **H1 in every chunk**: the document title is injected into every chunk via a post-pass. No chunk is contextually orphaned. Deep-nested sections retain the document-level context.

- **Sentence-boundary splitting**: long paragraphs are split at sentence boundaries in both Chinese (。！？) and English (.!?). Single sentences are never broken unless they exceed the hard max size.

- **Table row-boundary splitting**: oversized tables are split at row boundaries with column headers re-prepended to every continuation chunk. Lists split at item boundaries, code blocks at line boundaries.

- **Context absorption**: when a table or list starts a new chunk group, the algorithm looks back for the most recent non-blank paragraph and absorbs it as context within the hard limit.

- **Snowflake BIGINT chunk IDs**: each chunk gets a 64-bit Snowflake-like int that maps directly to a SQL `BIGINT PRIMARY KEY` column. Sortable by creation time. The embedded timestamp is recoverable via `chunk_id_timestamp_ms()`.

- **Zero runtime dependencies**: pure Python with no required external packages. Only `pytest` is needed for the test suite.

- **Fork-safe and clock-resilient**: ID generation uses `os.register_at_fork` (POSIX) so worker processes never generate colliding IDs. System clock jumps are handled by spin-waiting up to 10 ms, then raising `RuntimeError`.

## Installation

```bash
pip install structchunk
```

From source (includes test dependencies):

```bash
git clone https://github.com/yzp0111/structchunk
cd structchunk
pip install -e ".[test]"
```

Via uv:

```bash
uv pip install structchunk
```

Requires Python 3.9 or later. No runtime dependencies beyond the standard library.

## Quick Start

```python
import structchunk

chunks = structchunk.chunk(
    "# Title\n\nSome content with a long paragraph that needs splitting.",
    max_chars=500,
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

The `chunk()` function is the main entry point. It accepts markdown text and returns
a list of `MarkdownChunk` objects. The `max_chars` parameter caps every chunk at the
given size. Additional keyword arguments are forwarded to the algorithm's chunk function.

The breadcrumb entry includes the `#` prefix, distinguishing header levels (`# H1`,
`## H2`, `### H3`). The H1 document title is present in every chunk, not just the first
one, so downstream embeddings always have the document-level context.

Each chunk also carries a Snowflake-like `chunk_id` (a Python `int` ready for SQL
`BIGINT`), `source_element_type` and `source_element_position` for provenance tracking,
character offsets into the original document, pre-computed character counts, and
`prev_chunk_id` / `next_chunk_id` pointers for linked-list traversal. Call
`chunk.expand(include_breadcrumb=True)` to get a retrieval-ready view with breadcrumb
prepended to content.

For file input, use `chunk_file()`:

```python
chunks = structchunk.chunk_file("path/to/document.md", max_chars=500)
```

The file's absolute path is used as the `doc_id` automatically. For JSON serialization:

```python
dicts = structchunk.chunk_to_dicts(chunks)
```

## Algorithms

| Algorithm | Default | When to use |
|---|---|---|
| `hierarchical` | Yes | Documents with clear section hierarchy (technical docs, reports, books). Produces semantically coherent chunks that always start at a section header. |
| `linear` | No | Documents without strict section structure, or when you want fine-grained control over split points. Fast greedy assembly with type-specific sub-splitters. |

```python
# Hierarchical (default, section-tree based)
chunks = structchunk.chunk(content, algorithm="hierarchical", max_chars=500)

# Linear (greedy block-by-block)
chunks = structchunk.chunk(content, algorithm="linear", max_chars=500)
```

The hierarchical algorithm builds a section tree from the document's header hierarchy.
It walks the tree bottom-up and emits one chunk per section that fits within the size cap.
It is the default because it produces the most semantically coherent chunks. Oversized
sections are sub-split at natural boundaries (sentence, table row, list item, code line).
Adjacent same-level sibling sections are greedily merged when they fit together, subject
to a section-complete invariant: a complete section can merge with siblings, but a
residual tail from a split section cannot. This prevents cross-contamination between
different sections. Hierarchical is the right choice for technical docs, reports, books,
or any content with a clear heading structure.

The linear algorithm uses greedy block-by-block assembly. Each block (paragraph, table,
list, code fence) is added to the current chunk until it would exceed the size cap, then
a new chunk starts. Oversized blocks are delegated to type-specific sub-splitters:
paragraphs split at sentence boundaries, tables at row boundaries, lists at item
boundaries, code fences at line boundaries. The linear algorithm is simpler and faster,
making it a good choice for flat documents without section hierarchy.

Both algorithms share the same configuration parameters: `max_chars`, `max_chunk_size`,
`hard_max_size`, `min_chunk_size`, `sub_split_paragraph`, `sub_split_table`,
`sub_split_code`, `sub_split_list`, `preserve_table_header`, `preserve_code_fence`,
`forward_intro_text`, and `doc_id`. See the API reference for details on each parameter.

## CLI

After installation, the `structchunk` command is available as a console script:

```bash
structchunk document.md                                       # hierarchical, 500c cap
structchunk document.md --algorithm linear                    # greedy block-by-block
structchunk document.md --max-chars 300 --format json          # 300c cap, JSON output
structchunk document.md --quiet                                # suppress summary
structchunk document.md --output-dir /tmp/chunks               # custom output directory
```

| Flag | Default | Description |
|---|---|---|
| `--algorithm` | `hierarchical` | Chunking algorithm: `hierarchical` or `linear` |
| `--max-chars` | `500` | Hard cap on chunk size in characters |
| `--format` | `both` | Output format: `json`, `md`, or `both` |
| `--quiet` | `False` | Only save files, don't print summary |
| `--output-dir` | `./test_result/` | Directory for output files |

Output files include the input file stem, algorithm name, and a timestamp in their filename:

- `document-hierarchical-20250101_120000.json`
- `document-hierarchical-20250101_120000.md`

JSON output contains the full chunk list with all metadata fields serialized as dicts,
suitable for programmatic consumption. Markdown output renders each chunk as a
human-readable section with breadcrumb, source element type, character range, chunk ID,
and linked-list pointers.

When `--quiet` is omitted, the CLI prints a summary table showing each chunk's index,
character count, source type, and breadcrumb path, along with aggregate statistics:
total chunks, size range, type distribution, continuation count, and elapsed time.

The output directory defaults to `./test_result/` and is created automatically if it
does not exist.

## Documentation

- [Quick Start](docs/quickstart.md)
- [Algorithms](docs/algorithms.md) (sentence splitting, header pull-up, context absorption, breadcrumb construction, sibling merge)
- [API Reference](docs/api.md) (`chunk()`, `chunk_file()`, `chunk_to_dicts()`, keyword arguments)
- [CLI Usage](docs/cli.md) (flags, output formats, examples)
- [Metadata Reference](docs/metadata.md) (all fields on `ChunkMetadata`)
- [Why structchunk?](docs/why-structchunk.md) (design rationale, UUID4 vs Snowflake BIGINT, fork safety)
- [Database Schema](docs/database-schema.md) (PostgreSQL schema with BIGINT primary key and pgvector column)

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Development setup and installation from source
- Project layout and module overview
- Running the test suite
- Submitting pull requests and reporting bugs

Bug reports and pull requests are welcome on GitHub.

## License

[MIT](LICENSE)
