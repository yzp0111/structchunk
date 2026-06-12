# Algorithms

[中文版](zh-CN/algorithms.md)

## Overview

structchunk offers two chunking algorithms. Both parse text into the
same atomic block representation but differ in assembly.

**Linear (greedy)**: walks blocks in document order, fills each chunk
until the size cap. Fast, simple, good for flat documents.

**Hierarchical (section-tree)**: builds a tree from the document's
header structure, walks it bottom-up, emits one chunk per section.
Default. Produces chunks that always start at a section header. Best
for technical docs, reports, and books.

Both share the same sub-splitters, breadcrumb construction, context
absorption, and post-processing pipeline.

## Linear Algorithm

The linear algorithm (`chunk_linear`) uses greedy block-by-block
assembly:

1. Parse text into atomic blocks.
2. Walk blocks in document order. Accumulate into a group while
   total size stays under `max_chunk_size`.
3. When the next block would exceed the cap, scan backwards for the
   last header and split there (**header pull-up**).
4. Oversized blocks go to type-specific sub-splitters.
5. Compute the RAG breadcrumb for each group.
6. Context absorption: when a TABLE or LIST starts a new group, scan
   backwards for the most recent non-blank, non-table/list block and
   absorb it if it fits within `hard_max_size`.
7. Post-process: re-split chunks whose body plus injected breadcrumb
   exceeds `hard_max_size`, inject missing breadcrumbs, merge tiny
   same-breadcrumb chunks, enrich metadata.

Use for flat documents without strict section structure or when you
want fine-grained control over split points.

## Hierarchical Algorithm

The hierarchical algorithm (`chunk_hierarchical`) builds and walks a
section tree:

1. Parse text into atomic blocks.
2. Build a tree of `_Section` nodes. Each section is a header plus
   its content blocks and child sub-sections.
3. Walk the tree bottom-up via `_section_to_chunks`.
4. Leaf section (no children): if it fits within `max_chunk_size`,
   emit one chunk (`is_section_complete=True`). Otherwise, sub-split
   and emit multiple chunks (`is_section_complete=False`).
5. Internal section (with children): process children first, then
   merge parent content with the first child if everything fits.
6. Adjacent same-level siblings are greedily merged subject to the
   section-complete invariant: a complete section can merge; a tail
   from a split section cannot.
7. Post-processing is the same as the linear algorithm.

The result: every chunk belongs to a section, headers lead their
content, and no table-tail-plus-next-section-header mashups occur.

## Comparison

| Aspect | Linear | Hierarchical |
|---|---|---|
| Strategy | Greedy block-by-block | Section-tree bottom-up |
| Headers required | No | Yes |
| Chunk boundaries | Content-size based | Section-boundary based |
| Speed | Faster | Slightly slower |
| Default | No | Yes |

## Sub-splitters

When an atomic block alone exceeds `max_chunk_size`, it is delegated
to a type-specific sub-splitter:

**Paragraph** (`split_paragraph_at_sentences`): splits at sentence
boundaries. Each sentence stays intact. URLs and emails are protected
so internal dots don't trigger false splits. If one sentence exceeds
`hard_max_size`, the `_force_split_long_strings` fallback splits at
character boundaries.

**Table** (`split_table_rows`): splits at row boundaries. Column
headers are prepended to every continuation chunk.

**List** (`split_list_items`): splits at item boundaries. Each item
(a line starting with `-`, `*`, or `1.` plus continuation lines)
stays intact.

**Code** (`split_code_block`): splits at line boundaries. Each
fragment re-opens and re-closes the fence.

**`force_split_long_strings`**: last-resort fallback. When even a
single sentence, table cell, list item, or code line exceeds
`hard_max_size`, this splits at arbitrary character boundaries.

Sub-splitting can be disabled per type via config flags:
`sub_split_paragraph`, `sub_split_table`, `sub_split_list`,
`sub_split_code`.

## Sentence Boundary Splitting

The sentence boundary regex, defined in `_parser.py`, handles both
Chinese and English:

```
[^.!?。！？]+[.!?。！？]+\s*|[^.!?。！？]+\s*$
```

This matches (1) a run of non-terminator characters followed by
terminators and optional whitespace, or (2) a trailing fragment with
no terminator.

**URL and email protection**: before splitting, `_protect_urls`
swaps internal dots in URLs (`api.openai.com`), email addresses,
version numbers (`v1.2.3`), file names (`docs/api.md`), function
calls (`obj.method(`), and dotted sequences (`foo.bar.baz`) with a
Unicode placeholder (one-dot leader U+2024). This prevents the regex
from treating each dot as a sentence terminator. After splitting,
`_restore_urls` swaps them back.

**Single-sentence integrity**: a single sentence is never broken.
The sub-splitter accumulates whole sentences until the size cap is
reached. If one sentence exceeds `hard_max_size`, the
`_force_split_long_strings` fallback splits at character boundaries.

## Header Pull-Up

When the linear algorithm would split a group, it scans backwards for
the last header. If found (and the prefix before it meets
`min_chunk_size`), the split point shifts to just before that header.
This guarantees a header leads its content rather than trailing at
the end of a previous chunk.

The hierarchical algorithm does not need explicit pull-up: sections
are defined by their header, so every chunk naturally starts with
one.

A secondary pass then walks adjacent groups and moves trailing
headers from the end of one group to the start of the next. If the
last group consists only of headers, it merges into the preceding
group.

## Context Absorption

When a TABLE or LIST starts a new chunk group, the algorithm scans
backwards for the most recent non-blank block that is not itself a
TABLE or LIST. If it fits within `hard_max_size`, it is prepended.

For example, a paragraph like `**首选：XXX**` or `Important notice.`
that immediately precedes a table is absorbed as contextual summary.
RAG embeddings then see the paragraph alongside the table data.

Both algorithms share this. The linear algorithm does it during group
assembly (`assemble_chunks`). The hierarchical algorithm's leaf-split
path uses `_extract_intro_text` to forward the last sentence of the
preceding paragraph to continuation chunks.

## RAG Breadcrumb

Every chunk carries a `header_breadcrumb` field: a list of
markdown-level-prefixed header strings like
`['# H1', '## H2', '### H3']`.

The breadcrumb is built in two steps:

1. **End-of-group path**: start from the header stack as it existed
   before the group, then apply all group headers using standard
   header-stack semantics (a deeper header pushes; a
   same/higher-level header pops). This produces the correct
   end-state path with no stale same-level headers.

2. **Strip and re-add**: pop the last entry of the end-of-group path,
   then add all headers that appear inside the group in **document
   order**. This avoids stale same-level headers (e.g. `表1` leaking
   into a `表2` chunk) and wrong order (e.g. `场景4` before `场景3`).

## Missing-Breadcrumb Injection

After assembly, `inject_missing_breadcrumbs` walks every chunk and
checks whether each `header_breadcrumb` entry is already present in
the chunk's content. Entries are matched against stripped content
lines to avoid false positives from shared prefixes (e.g. `## Section
2` does not match `## Section 2.5`).

For each missing entry, the header line is prepended. Every chunk
becomes self-contained: even a deep-nested continuation chunk carries
its full ancestor path in the text. The H1 document title is included
in every chunk, so no chunk is contextually orphaned.

The injection runs twice (before and after
`_re_split_with_prefix_budget`) to handle chunks re-split after
breadcrumb injection.

## Hierarchical Sibling Merge

After bottom-up processing, `_section_to_chunks` produces a list of
chunks for a parent section. Adjacent chunks from the same parent's
children are candidates for greedy merging.

The merge enforces the **section-complete invariant**:

- A chunk representing a **complete** section
  (`is_section_complete=True`) can merge with adjacent same-level
  siblings.
- A **residual/tail** chunk from a split section
  (`is_section_complete=False`) cannot merge with a different
  sibling's content, even if breadcrumbs share a common prefix.

This prevents a section's tail from incorrectly absorbing the
beginning of a different section. For example, a long `## Section A`
that spills into a second chunk must not absorb `## Section B`'s
first block.

Internally, each emitted chunk carries an `is_section_complete` flag.
A section emitted as a single chunk gets `True`; a section split
across multiple chunks marks all its pieces `False`. The merger
checks this flag on both sides before allowing a cross-section merge.

The merge uses longest-common-prefix (LCP) comparison of breadcrumbs.
This allows cross-level sibling merge (e.g. `## A` and `## B`
sharing `# Title` as common ancestor) while preserving the H1
boundary (different H1s have LCP=[] and cannot merge).
