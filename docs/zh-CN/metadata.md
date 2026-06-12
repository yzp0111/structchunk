# ChunkMetadata 参考

[English](../metadata.md)

## 概述

每个由 `chunk()` 返回的 `MarkdownChunk` 都携带一个包含 19 个字段的 `ChunkMetadata` 对象，涵盖标识符、位置、来源溯源、续接状态、字符计数和分节完整性。这些字段设计用于直接存储在 SQL 数据库中（例如，作为包含 `BIGINT PRIMARY KEY` 和各种可过滤列的 `chunks` 表），并用于在 RAG 期间进行检索排序（例如，基于路径的加权提升）。

关于 JSON 友好的序列化，请参见 [`MarkdownChunk.to_dict()`](api.md#markdown-chunk)。

## 字段参考

| 字段 | 类型 | 描述 |
|-------|------|-------------|
| `chunk_id` | `int` | Snowflake 风格的 64 位唯一 ID。对应 SQL `BIGINT`。 |
| `prev_chunk_id` | `int` | 前一个块的 `chunk_id`，如果是第一个块则为 `0`。 |
| `next_chunk_id` | `int` | 后一个块的 `chunk_id`，如果是最后一个块则为 `0`。 |
| `chunk_index` | `int` | 该块在文档中的基于 0 的位置。 |
| `total_chunks` | `int` | 文档中的总块数。 |
| `doc_id` | `str` | 文档标识符（字符串内容的 SHA-256 内容哈希，`chunk_file` 的文件路径）。 |
| `header_breadcrumb` | `list[str]` | 带 markdown 层级前缀的父级标题有序列表，例如 `['# H1', '## H2']`。 |
| `header_path` | `list[HeaderInfo]` | 结构化路径（层级 + 文本），与 `header_breadcrumb` 平行。 |
| `source_element_type` | `str` | 源块类型：`paragraph`、`table`、`list`、`code` 等。 |
| `source_element_position` | `str` | 该源块在其类型内的序号。 |
| `source_meta` | `dict` | 类型特定的元数据（标题层级、代码语言、表格列数等）。 |
| `continuation` | `bool` | 如果该块是前一个块的续接，则为 `True`。 |
| `has_more` | `bool` | 如果源元素在后续块中继续，则为 `True`。 |
| `char_offset_start` | `int` | 该块在原始文档中起始的字符偏移量。 |
| `char_offset_end` | `int` | 该块在原始文档中结束的字符偏移量。 |
| `content_length` | `int` | 预计算的 `.content` 字符长度。 |
| `breadcrumb_length` | `int` | 预计算的所有路径条目的总长度。 |
| `total_length` | `int` | 自 v0.4.0 起等同于 `content_length`（路径已成为内容的一部分）。 |
| `is_section_complete` | `bool` | 如果该分节完整地包含在一个块中，则为 `True`；如果这是被拆分分节的尾部，则为 `False`。仅限 hierarchical 模式。 |

## 标识符字段

`chunk_id`、`prev_chunk_id` 和 `next_chunk_id` 是原始的 64 位 Snowflake 整数，正是 SQL `BIGINT` 列所持有的数据类型。`0` 是表示"无前驱"或"无后继"的哨兵值，并非有效的 Snowflake ID。

对于 JSON 输出，可以使用 `MarkdownChunk.chunk_id_str`（十进制）或 `MarkdownChunk.chunk_id_hex`（16 字符十六进制）转换为字符串。请参见 [API 参考](api.md#markdown-chunk)。

```python
c = chunks[0]
print(c.metadata.chunk_id)        # int, e.g. 188704004562132992
print(c.chunk_id_str)             # str, "188704004562132992"
print(c.chunk_id_hex)             # str, "029f0c9d210b8000" (16 hex chars)
```

## 路径字段

`header_breadcrumb` 是一个 `list[str]`，带有 markdown 层级前缀。例如，位于 `# Title` 下的 `## Section` 中的块会得到：

```python
["# Title", "## Section"]
```

`header_path` 是一个并行的 `list[HeaderInfo]`，包含结构化的层级/文本：

```python
[
    HeaderInfo(level=1, text="Title"),
    HeaderInfo(level=2, text="Section"),
]
```

H1 文档标题会包含在每个块的路径中，因此嵌入向量始终拥有文档级别的上下文。

## 位置字段

- `chunk_index`（基于 0）和 `total_chunks` 给出了该块在文档中的位置。
- `char_offset_start` 和 `char_offset_end` 给出了原始文档中的字符偏移量（起始包含，结束不包含）。

在用户界面中使用这些值来高亮显示源范围：从原始 markdown 的 `char_offset_start` 到 `char_offset_end`。

## 来源追踪

- `source_element_type` 是以下之一：`paragraph`、`table`、`list`、`code`、`header`、`block_quote`、`math`、`hr`、`frontmatter` 等。
- `source_element_position` 是该源块在其类型内的序号（例如，文档中的第 3 个表格）。
- `source_meta` 携带类型特定的额外信息：标题层级、代码语言、表格列数等。

这使您可以在构建用户界面时按源元素对块进行分组（"显示所有来自表格 #3 的块"）。

## 续接与链接

- `continuation = True` 表示该块是前一个块的续接（跨页的表格行、长代码块等）。
- `has_more = True` 表示该块之后至少还有一个块携带同一源元素的剩余部分。
- `prev_chunk_id` 和 `next_chunk_id` 是链表指针。使用它们可以在链中向前或向后遍历，时间复杂度为 O(n)，其中 n 为链长。

一个简单的例子：长代码块可能生成 3 个块 `[A, B, C]`：

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

## 长度字段

- `content_length` 是 `len(c.content)`（预计算，用于快速过滤）。
- `breadcrumb_length` 是 `sum(len(h) for h in c.metadata.header_breadcrumb)`。
- `total_length` 等于 `content_length`（自 v0.4.0 起，路径已成为内容的一部分，不再相加）。

这些值已预先计算，因此数据库查询可以在不加载完整内容的情况下按 `content_length` 进行过滤（列式投影优化）。

## 分节完整性

`is_section_complete` 在完整分节位于该块中时为 `True`（整个分节作为一个块发出），如果这是被拆分分节的尾部/残余部分，则为 `False`。

后续处理（例如 `merge_tiny`）不得将不完整的块合并到不同分节的头部，因为那样会将两个不同的分节混合到单个携带路径的块中。

对于由 `linear` 算法（没有分节概念）生成的块，此标志始终为 `True`。对于外部构建的块（例如来自反序列化），默认值为 `True`。

## 链表遍历

向前遍历块链：

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

或从最后一个块向后遍历：

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
