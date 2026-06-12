# 快速开始

[English](../quickstart.md)

## Hello World

最简单的用法是对 Markdown 字符串进行分块并打印每个块：

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

输出（默认使用 `hierarchical` 算法）：

```
[0] ['# Title']
# Title

Some content with a long paragraph that needs splitting.
```

`chunk()` 函数返回一个 `MarkdownChunk` 对象列表。每个块包含 `.content`（用于嵌入的文本）和 `.metadata`（一个 `ChunkMetadata` 对象，包含标题路径、字符偏移量、ID 等信息，详见[元数据参考](metadata.md)）。

`max_chars=500` 参数限制每个块不超过 500 个字符，这也是 [Dify](https://dify.ai) RAG 平台的默认值。默认算法（`hierarchical`）能够感知文档结构，生成语义连贯的块。

## 选择算法

structchunk 提供了两种算法，可根据输入类型选择：

| 算法 | 适用场景 | 行为 |
|-----------|----------|----------|
| `hierarchical`（默认） | 具有清晰章节层次结构的文档（技术文档、报告、书籍） | 构建章节树，自底向上遍历，为每个适合的章节生成一个块。同级兄弟章节会贪婪合并（受章节完整不变性约束）。 |
| `linear` | 没有严格章节结构的文档，或需要精细控制分割点时 | 逐块贪婪组装。过大的块交由类型特定的子分割器处理（段落拆分为句子、表格拆分为行、列表拆分为项、代码拆分为行）。 |

使用 `algorithm` 关键字切换：

```python
# Hierarchical（默认，章节感知）
chunks = structchunk.chunk(content, algorithm="hierarchical", max_chars=500)

# Linear（贪婪）
chunks = structchunk.chunk(content, algorithm="linear", max_chars=500)
```

更深入的比较请参阅[算法](algorithms.md)。

## 常用模式

### 对文件分块

```python
chunks = structchunk.chunk_file("path/to/document.md", max_chars=500)
```

`chunk_file()` 读取指定路径的文件。文件的绝对路径会自动用作 `doc_id`，同一路径对应同一 `doc_id`。

### 获取 JSON 友好的字典

为便于存储或网络传输，可将块序列化为字典：

```python
dicts = structchunk.chunk_to_dicts(chunks)
# dicts[0]["content"] -> 待嵌入的文本
# dicts[0]["metadata"]["chunk_id"] -> Snowflake id 的十进制字符串形式
# dicts[0]["metadata"]["header_breadcrumb"] -> ['# Title', '## Section']
```

### 自定义分块行为

`chunk()` 函数接受多个关键字参数以微调分块行为。完整列表请参阅 [API 参考](api.md)。最常用的参数如下：

```python
chunks = structchunk.chunk(
    content,
    max_chars=500,           # 硬限制（Dify 友好）
    forward_intro_text=True, # 将前导段落转发给表格/列表的后续块
    doc_id="my-doc-001",     # 覆盖自动生成的 doc_id
)
```

## 下一步

- [算法](algorithms.md) — 算法详细内部原理
- [API 参考](api.md) — 所有公开函数、类和配置字段
- [元数据参考](metadata.md) — `ChunkMetadata` 的全部 17 个字段
- [CLI 参考](cli.md) — 在命令行中使用 structchunk
- [数据库模式](database-schema.md) — 在 PostgreSQL 中配合 pgvector 存储块
