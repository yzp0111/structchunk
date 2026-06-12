# API 参考

[English](../api.md)

本页面记录了 `structchunk` 导出的所有公开名称。所有名称均可直接从顶级包导入：

```python
import structchunk

structchunk.chunk(...)
structchunk.MarkdownChunk
structchunk.BlockType
# 等等
```

## 高级函数

以下是大多数用户推荐的入口点。

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

对 Markdown 内容进行分块，用于 RAG 场景。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|-----------|------|---------|-------------|
| `content` | `str` | (必填) | 要分块的原始 Markdown 文本。 |
| `algorithm` | `str` | `"hierarchical"` | `"linear"` 为贪婪的逐块分块；`"hierarchical"` 为基于文档树的语义连贯分块。 |
| `max_chars` | `int \| None` | `None` | 便捷上限（例如 Dify 使用的 500）。如果设置，保证每个块最多 `max_chars` 个字符。同时设置 `max_chunk_size`（80%）和 `hard_max_size`（100%）。 |
| `forward_intro_text` | `bool` | `True` | 是否转发表格和列表的引言文本（参见 `ChunkerConfig`）。 |

所有额外的 `**kwargs` 会被转发到所选算法的分块函数。
如果未提供 `doc_id`，则会根据内容的 SHA-256 哈希自动派生（前 16 个十六进制字符）。

**返回：** `list[MarkdownChunk]`

**引发：** 如果 `algorithm` 不是 `"linear"` 或 `"hierarchical"`，或者 `max_chars` 设置为非正值，则引发 `ValueError`。

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

读取一个 Markdown 文件并对其分块。文件的绝对路径被用作 `doc_id`，除非调用方显式提供了一个。

---

### `chunk_to_dicts()`

```python
chunk_to_dicts(chunks: list[MarkdownChunk]) -> list[dict]
```

将分块列表序列化为 JSON 友好的字典。每个块通过 `MarkdownChunk.to_dict()` 转换。标识符字段以十进制字符串形式输出。

## 低级函数

这些函数实现了两种分块算法。它们由 `chunk()` 内部调用，但当您想绕过调度逻辑时也可以直接使用。

---

### `chunk_linear()`

```python
chunk_linear(content: str, **kwargs) -> list[MarkdownChunk]
```

贪婪的逐块分块。每个块（段落、表格、列表、代码围栏）被添加到当前块中，直到达到大小上限，然后开始一个新块。过大的块被委托给特定类型的子分割器：段落按句子边界分割，表格按行边界分割，列表按项边界分割，代码围栏按行边界分割。

---

### `chunk_hierarchical()`

```python
chunk_hierarchical(content: str, **kwargs) -> list[MarkdownChunk]
```

基于文档树的分块。从文档的标题层级构建一个章节树，然后自底向上遍历，为每个适合大小上限的章节生成一个块。过大的章节在自然边界处进行子分割。相邻的同级兄弟章节在适合合并时会被贪婪地合并。

## 数据类

---

### `MarkdownChunk`

```python
@dataclass
class MarkdownChunk:
    content: str
    metadata: ChunkMetadata
```

单个块：内容加上丰富的元数据。

**字段：**

| 字段 | 类型 | 说明 |
|-------|------|-------------|
| `content` | `str` | 块的文本内容。 |
| `metadata` | `ChunkMetadata` | 附加到此块的所有元数据。 |

**属性：**

| 属性 | 返回类型 | 说明 |
|----------|-------------|-------------|
| `chunk_id_hex` | `str` | `chunk_id` 的 16 字符小写十六进制字符串。用于 JSON 输出、日志行和调试。 |
| `chunk_id_str` | `str` | `chunk_id` 的十进制字符串（等同于 `str(int)`）。这是 Twitter、Discord 和 Instagram 在其 JSON API 中使用的格式。 |

**方法：**

`expand(include_breadcrumb: bool = True) -> str`
:   返回用路径上下文扩展后的块内容。实现"小到大"检索模式：将紧凑的 `.content` 用于向量相似度嵌入，但将扩展后的版本提供给 LLM 以获得更丰富的上下文。

`recompute_lengths() -> None`
:   根据当前字段值重新推导所有长度字段（`content_length`、`breadcrumb_length`、`total_length`）。在创建后对内容或路径字段进行任何修改后使用。

`to_dict() -> dict`
:   序列化为 JSON 友好的字典。标识符字段以十进制字符串形式输出。原始整数在 `self.metadata.chunk_id` 上，供希望跳过字符串转换的代码使用。

---

### `ChunkMetadata`

```python
@dataclass
class ChunkMetadata:
```

附加到 `MarkdownChunk` 的所有元数据字段。标识符字段（`chunk_id` / `prev_chunk_id` / `next_chunk_id`）是原始的 64 位 Snowflake 整数，与 SQL `BIGINT` 列存储的内容完全相同。使用 0 作为"无前驱 / 无后继"的哨兵值。

**字段：**

| 字段 | 类型 | 说明 |
|-------|------|-------------|
| `chunk_id` | `int` | 此块的唯一 Snowflake ID（64 位）。 |
| `chunk_index` | `int` | 此块在文档块列表中的从零开始索引。 |
| `total_chunks` | `int` | 文档的块总数。 |
| `char_offset_start` | `int` | 原始文档中的起始字符偏移量。 |
| `char_offset_end` | `int` | 原始文档中的结束字符偏移量（不包含）。 |
| `header_breadcrumb` | `list[str]` | 带有 Markdown 级别前缀的路径条目，例如 `['# H1', '## H2', '### H3']`。 |
| `header_path` | `list[HeaderInfo]` | 作为 `HeaderInfo` 对象的结构化标题路径。 |
| `has_more` | `bool` | 此块之后是否还有更多块（便捷标志）。 |
| `source_meta` | `dict` | 任意来源元数据。 |
| `doc_id` | `str` | 文档标识符。来自同一文档的所有块共享此值。从文件路径（通过 `chunk_file()`）或内容哈希（通过 `chunk()`）自动派生。 |
| `prev_chunk_id` | `int` | 序列中前一个块的 Snowflake ID（如果没有则为 0）。 |
| `next_chunk_id` | `int` | 序列中下一个块的 Snowflake ID（如果没有则为 0）。 |
| `source_element_type` | `str` | 此块中第一个块的 `BlockType` 名称。 |
| `source_element_position` | `str` | 源元素的位置描述。 |
| `continuation` | `bool` | 此块是否为被分割块的延续部分。 |
| `content_length` | `int` | 预计算的 `content` 字符长度。由 `__post_init__` 自动设置。 |
| `breadcrumb_length` | `int` | 预计算的路径字符长度。由 `__post_init__` 自动设置。 |
| `total_length` | `int` | 预计算的总长度（`content_length`）。由 `__post_init__` 自动设置。 |
| `is_section_complete` | `bool` | 层次化算法的章节完整不变量。`True` 表示整个章节都在此块中。 |

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

Markdown 内容的不可分割单元。`meta` 携带类型特定的附加信息（标题的级别、代码的语言、表格的表头行数、列表的有序性等）。

---

### `HeaderInfo`

```python
@dataclass
class HeaderInfo:
    level: int
    text: str
```

路径栈中的标题条目。

**字段：**

| 字段 | 类型 | 说明 |
|-------|------|-------------|
| `level` | `int` | 标题级别（1-6，对应 `#` 到 `######`）。 |
| `text` | `str` | 标题文本内容（不含 `#` 前缀）。 |

## 枚举

---

### `BlockType`

```python
class BlockType(Enum):
```

原子 Markdown 块的类型。每个值对应 Markdown 文档中的一个不同结构元素。

| 值 | 说明 |
|-------|-------------|
| `FRONTMATTER` | 文档开头的 YAML/TOML 前置元数据块。 |
| `HEADER` | Markdown 标题（`#` 到 `######`）。 |
| `CODE_FENCE` | 围栏代码块。 |
| `TABLE` | 完整的 Markdown 表格。 |
| `TABLE_ROW` | 表格中的单个行。 |
| `LIST` | 列表（有序或无序）。 |
| `BLOCKQUOTE` | 块引用部分。 |
| `MATH_BLOCK` | 数学块（例如 `$$...$$`）。 |
| `HR` | 水平分割线（`---`、`***`、`___`）。 |
| `PARAGRAPH` | 纯文本段落。 |
| `BLANK` | 空行。 |

## 工具函数

---

### `chunk_id_timestamp_ms()`

```python
chunk_id_timestamp_ms(chunk_id: int | str) -> int
```

恢复嵌入在 Snowflake 块 ID 中的毫秒时间戳。

接受原始 `int`（规范形式）或字符串（十进制优先，即 `str(int_chunk_id)` 产生的，或十六进制用于旧调用方）。对非 Snowflake 输入返回 0。

**返回：** Unix 毫秒时间戳，如果输入不是有效的 Snowflake ID 则返回 0。

## 配置

---

### `ChunkerConfig`

```python
@dataclass
class ChunkerConfig:
```

线性分块器和层次化分块器共享的配置。将各个字段作为关键字参数传递给 `chunk()`、`chunk_linear()` 或 `chunk_hierarchical()`。

| 字段 | 类型 | 默认值 | 说明 |
|-------|------|---------|-------------|
| `max_chunk_size` | `int` | `1500` | 块大小的软上限（字符数）。 |
| `hard_max_size` | `int` | `3000` | 绝对最大值。块永远不会超过这个大小。 |
| `min_chunk_size` | `int` | `50` | 不生成小于此值的块（与相邻块合并）。 |
| `sub_split_table` | `bool` | `True` | 允许在行边界处分割过大的表格。 |
| `sub_split_code` | `bool` | `True` | 允许在行边界处分割过大的代码块。 |
| `sub_split_list` | `bool` | `True` | 允许在项边界处分割过大的列表。 |
| `sub_split_paragraph` | `bool` | `True` | 允许在句子边界处分割过大的段落。 |
| `preserve_table_header` | `bool` | `True` | 当表格被分割到多个块中时，将表头行前置到每个延续块中。 |
| `preserve_code_fence` | `bool` | `True` | 当代码块被分割时，在每个块中重新打开/关闭围栏。 |
| `doc_id` | `str` | `""` | 可选的文档标识符，会传播到每个块的元数据中。 |
| `forward_intro_text` | `bool` | `True` | 当一个章节的第一个表格或列表之前紧跟着一个纯文本段落（而非 Markdown 标题）时，该段落的最后一个句子会被转发到分割延续部分作为隐式标题。设置为 `False` 可禁用此功能。 |

## 版本

---

### `__version__`

```python
__version__: str = "0.1.0"
```

包的版本字符串，遵循[语义化版本控制](https://semver.org/)。
