# Quick Start

[中文版](zh-CN/quickstart.md)

## Hello World

The simplest possible usage — chunk a markdown string and print each chunk:

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

The `chunk()` function returns a list of `MarkdownChunk` objects. Each chunk has
`.content` (the text to embed) and `.metadata` (a `ChunkMetadata` with header
breadcrumb, character offsets, IDs, and more — see
[Metadata Reference](metadata.md)).

The `max_chars=500` argument caps every chunk at 500 characters, which is the
default for the [Dify](https://dify.ai) RAG platform. The default algorithm
(`hierarchical`) is structure-aware and produces semantically coherent chunks.

## Choosing an Algorithm

structchunk ships with two algorithms. Pick based on your input:

| Algorithm | Best for | Behavior |
|-----------|----------|----------|
| `hierarchical` (default) | Documents with clear section hierarchy (technical docs, reports, books) | Builds a section tree, walks bottom-up, emits one chunk per section that fits. Sibling sections merge greedily (subject to the section-complete invariant). |
| `linear` | Documents without strict section structure, or when you want fine-grained control over split points | Greedy block-by-block. Oversized blocks delegate to type-specific sub-splitters (paragraph→sentence, table→row, list→item, code→line). |

Switch with the `algorithm` keyword:

```python
# Hierarchical (default — section-aware)
chunks = structchunk.chunk(content, algorithm="hierarchical", max_chars=500)

# Linear (greedy)
chunks = structchunk.chunk(content, algorithm="linear", max_chars=500)
```

For a deeper comparison, see [Algorithms](algorithms.md).

## Common Patterns

### Chunk a file

```python
chunks = structchunk.chunk_file("path/to/document.md", max_chars=500)
```

`chunk_file()` reads the file at the given path. The file's absolute path is
used as the `doc_id` automatically — same path, same `doc_id`.

### Get JSON-friendly dicts

For storage or sending over a network, serialize to dicts:

```python
dicts = structchunk.chunk_to_dicts(chunks)
# dicts[0]["content"] -> the text
# dicts[0]["metadata"]["chunk_id"] -> Snowflake id as decimal string
# dicts[0]["metadata"]["header_breadcrumb"] -> ['# Title', '## Section']
```

### Customize chunking behavior

The `chunk()` function accepts many keyword arguments to fine-tune behavior.
For a complete list, see [API Reference](api.md). The most common ones:

```python
chunks = structchunk.chunk(
    content,
    max_chars=500,           # hard cap (Dify-friendly)
    forward_intro_text=True, # forward leading paragraph to table/list continuations
    doc_id="my-doc-001",     # override the auto-derived doc_id
)
```

## Next Steps

- [Algorithms](algorithms.md) — detailed algorithm internals
- [API Reference](api.md) — every public function, class, and configuration field
- [Metadata Reference](metadata.md) — all 17 fields on `ChunkMetadata`
- [CLI Reference](cli.md) — use structchunk from the command line
- [Database Schema](database-schema.md) — store chunks in PostgreSQL with pgvector
