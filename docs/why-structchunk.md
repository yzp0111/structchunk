# Why structchunk?

[中文版](zh-CN/why-structchunk.md)

RAG (Retrieval-Augmented Generation) quality is dominated by chunk quality. Naive
splitters break tables mid-row, separate headers from their content, and produce
chunks whose embeddings can't recover the section context. structchunk was built
to fix the specific issues that hurt retrieval.

## The Problem with Naive Splitters

Most off-the-shelf chunkers (LangChain's `CharacterTextSplitter`,
`RecursiveCharacterTextSplitter`, LlamaIndex's `SentenceSplitter`, etc.) split on
character count or token count. This causes four recurring problems:

1. **Headers orphaned from content.** A header at the end of a chunk semantically
   leads the *next* group's content, but a character-count splitter leaves it
   dangling at the tail of the previous chunk. The embedding for that chunk has no
   idea what section the text belongs to.

2. **Tables split mid-row.** A wide table that crosses the size cap gets a row
   sliced in two. The continuation chunk has rows that no longer make sense
   without the column header.

3. **Section context lost.** A paragraph deep in a `### Subsection` ends up in the
   same chunk as a paragraph from an unrelated `### Subsection` if the size cap
   forces them together. The embedding can't tell which subsection the text
   belongs to.

4. **Long documents fail silently.** A 50-page markdown report may produce chunks
   that all look like the table of contents repeated. Without breadcrumb injection,
   no chunk is self-contained.

structchunk addresses all four with structure-aware parsing, header pull-up, table
header re-prepending, and post-pass breadcrumb injection.

## Design Principles

1. **Structure-aware.** Parse markdown into atomic block types (headers, code
   fences, tables, lists, paragraphs, blockquotes, math, HR) and respect those
   boundaries when chunking. Never split a row, list item, or sentence unless
   forced to by `hard_max_size`.

2. **Headers always lead their content.** A trailing header is moved forward to
   the next group. No orphan headers.

3. **Tables preserve their column headers.** When a table is split at row
   boundaries, the header row is re-prepended to each continuation chunk.

4. **Lists absorb their preceding paragraph.** When a list starts a new group, the
   immediately preceding paragraph (or marker line) is absorbed as context.

5. **In-document-order breadcrumbs with markdown-level prefix.** Each chunk
   carries `['# H1', '## H2', '### H3']` — the full path from document root to
   the current section. The post-pass injects any missing header so every chunk
   is self-contained.

6. **Snowflake BIGINT ids for database efficiency.** 8 bytes (vs UUID4's 16),
   sortable by creation time, B-tree friendly. See [Snowflake BIGINT IDs](#snowflake-bigint-ids) below.

7. **Pure Python, zero runtime dependencies.** No supply-chain risk, no version
   conflicts, no transitive vulnerabilities.

8. **Fork-safe ID generation.** `os.register_at_fork` resets the generator in
   each child process, so two workers never generate colliding ids.

## Comparison with Other Chunkers

| Feature | structchunk | LangChain `CharacterTextSplitter` | LangChain `MarkdownTextSplitter` | LlamaIndex `SentenceSplitter` | Custom regex |
|---------|-------------|-----------------------------------|----------------------------------|-------------------------------|--------------|
| Structure-aware | Yes (11 block types) | No | Partial (headers only) | No | Depends |
| Header pull-up | Yes | No | No | No | No |
| Table row-boundary split | Yes | No | No | No | No |
| Table header re-prepending | Yes | No | No | No | No |
| List item-boundary split | Yes | No | No | No | No |
| CJK + English sentence splitting | Yes | English only | English only | English only | No |
| URL/email protection in sentences | Yes | No | No | No | No |
| Hierarchical section tree | Yes | No | Partial | No | No |
| Section-complete invariant | Yes | No | No | No | No |
| Snowflake BIGINT ids | Yes | No | No | No | No |
| Zero runtime dependencies | Yes | No (depends on langchain) | No | No | Yes |

## Snowflake BIGINT IDs

`chunk.metadata.chunk_id` is a 64-bit Snowflake-like int (8 bytes) that maps
directly to a SQL `BIGINT PRIMARY KEY` column. `str(chunk_id)` produces the
standard decimal representation, which is the format Twitter, Discord,
Instagram, and every other Snowflake user emits in their JSON APIs.

| Property | Snowflake BIGINT (structchunk) | UUID4 | Snowflake as string |
|----------|-------------------------------|-------|---------------------|
| DB storage | `BIGINT` (8 bytes) | `UUID` (16 bytes) | `VARCHAR(N)` (16+ bytes) |
| Comparison cost | `btint8cmp`: 2 register compares | `uuid_cmp`: 16 bytes | `varstr_cmp`: collation-bound |
| Sortable by creation time | Yes | No | Yes |
| B-tree index locality | Adjacent IDs cluster | Random | Same as BIGINT |
| Round-trip with `int(s)` | Yes | No | Only with base arg |
| Industry usage | Twitter, Discord, Instagram, Snowflake (the DB) | Web app records | Almost nobody |

For RAG workloads with bulk inserts and time-range queries, BIGINT Snowflake
ids are the standard choice. The embedded timestamp is recoverable via
`structchunk.chunk_id_timestamp_ms(chunk_id)`.

**Timestamp saturation:** with the current epoch (2026-01-01) and 41-bit timestamp
field, the Snowflake id saturates around **2095-08-15**. After that, IDs would
overflow the standard SQL `BIGINT` range and may be rejected by databases.

## When NOT to Use structchunk

structchunk is purpose-built for markdown. If your input is:

- **Plain text** (no markdown structure): use LangChain's `CharacterTextSplitter`. The header-breadcrumb injection has no effect on plain text.
- **HTML**: use BeautifulSoup or a dedicated HTML chunker. (HTML support is on the roadmap.)
- **Code-only corpora**: use a code-aware splitter like `langchain.text_splitter.Language` or `tree-sitter`. structchunk's code sub-splitter is a fallback, not a code-aware parser.
- **Very short documents** (a few hundred words): any splitter works. structchunk's overhead is wasted.

For all other RAG use cases on markdown documents, structchunk produces higher-quality
chunks than naive splitters.

## Benchmarks

Coming soon. The maintainer is preparing a comparison against LangChain's
`MarkdownTextSplitter` and LlamaIndex's `SentenceSplitter` on a standard
RAG benchmark (e.g. HotpotQA, Natural Questions). If you have a benchmark
suite you'd like to see, open an issue.

## Real-World Usage

structchunk is a young library. If you're using it in production, please open
a PR to add your project to this section. We'd love to feature real-world
deployments.
