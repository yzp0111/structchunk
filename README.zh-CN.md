# structchunk

面向 RAG 管道的结构感知文本分块。v0.1.0

> 纯 Python 实现，零外部依赖。提供两种 Markdown 分块算法：hierarchical（基于章节树，语义连贯的分块）和 linear（贪心逐块拼接，速度快）。每个分块携带标题路径导航以保留完整文档上下文，以及类 Snowflake BIGINT ID，便于数据库存储。

[English](README.md)

## 特性

structchunk 解决了影响 RAG 管道检索质量的核心问题：标题与内容分离、表格在行中断开、分块缺少章节上下文。它针对 Markdown 文档设计，生成尊重文档结构的分块。

- **结构感知解析**：尊重 Markdown 标题、代码围栏、表格和列表，找到自然断点。朴素分割器（如 LangChain CharacterTextSplitter 等）按字符数切分，会在行中断开表格。

- **两种算法**：`hierarchical`（默认，基于章节树）生成始终从章节标题开始的分块。`linear`（贪心逐块拼接）提供对分割点的精细控制。

- **标题前缀路径**：每个分块携带一个按文档顺序排列的路径导航，包含 Markdown 级别前缀（例如 `['# H1', '## H2', '### H3']`），成为分块内容的一部分。嵌入向量可看到完整的章节上下文。

- **每个分块都包含 H1**：文档标题通过后处理注入到每个分块中。没有分块会上下文孤立。深层嵌套的章节仍保留文档级上下文。

- **句边界分割**：长段落在中英文句号（。！？）和（.!?）处进行句边界分割。除非超过硬性大小上限，单个句子不会被拆分。

- **表格行边界分割**：过大的表格在行边界处分割，列标题会重新前置到每个续接分块。列表在项边界处分割，代码块在行边界处分割。

- **上下文吸收**：当表格或列表开始一个新的分块组时，算法会回溯查找最近的非空段落，并在硬性限制内将其吸收为上下文。

- **Snowflake BIGINT 分块 ID**：每个分块获得一个 64 位类 Snowflake 整数，可直接映射到 SQL `BIGINT PRIMARY KEY` 列。可按创建时间排序。嵌入的时间戳可通过 `chunk_id_timestamp_ms()` 恢复。

- **零运行时依赖**：纯 Python，无需任何外部包。仅测试套件需要 `pytest`。

- **进程安全与时钟韧性**：ID 生成使用 `os.register_at_fork`（POSIX），确保工作进程不会产生冲突 ID。系统时钟跳变通过自旋等待最多 10 毫秒处理，超出后抛出 `RuntimeError`。

## 安装

```bash
pip install structchunk
```

从源码安装（包含测试依赖）：

```bash
git clone https://github.com/yzp0111/structchunk
cd structchunk
pip install -e ".[test]"
```

通过 uv 安装：

```bash
uv pip install structchunk
```

需要 Python 3.9 或更高版本。除标准库外无运行时依赖。

## 快速开始

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

输出（默认 `hierarchical` 算法）：

```
[0] ['# Title']
# Title

Some content with a long paragraph that needs splitting.
```

`chunk()` 函数是主要入口点。它接受 Markdown 文本并返回一个 `MarkdownChunk` 对象列表。`max_chars` 参数限制每个分块的大小。额外的关键字参数会传递到算法的分块函数。

路径条目包含 `#` 前缀，用于区分标题级别（`# H1`、`## H2`、`### H3`）。H1 文档标题出现在每个分块中，而不仅仅是第一个分块，因此下游嵌入始终具有文档级上下文。

每个分块还携带一个类 Snowflake 的 `chunk_id`（Python `int` 类型，可直接用于 SQL `BIGINT`）、用于溯源跟踪的 `source_element_type` 和 `source_element_position`、原始文档中的字符偏移量、预计算的字符数，以及用于链表遍历的 `prev_chunk_id` / `next_chunk_id` 指针。调用 `chunk.expand(include_breadcrumb=True)` 可获取路径前置到内容后的检索就绪视图。

对于文件输入，使用 `chunk_file()`：

```python
chunks = structchunk.chunk_file("path/to/document.md", max_chars=500)
```

文件的绝对路径会自动用作 `doc_id`。对于 JSON 序列化：

```python
dicts = structchunk.chunk_to_dicts(chunks)
```

## 算法

| 算法 | 默认值 | 适用场景 |
|---|---|---|
| `hierarchical` | 是 | 具有清晰章节层次结构的文档（技术文档、报告、书籍）。生成的分块在语义上前后连贯，每个分块始终以章节标题开头。 |
| `linear` | 否 | 没有严格章节结构的文档，或希望细粒度控制切分点的场景。贪心逐块组装，配合类型特定的子分割器，速度更快。 |

```python
# 层次算法（默认，基于文档树）
chunks = structchunk.chunk(content, algorithm="hierarchical", max_chars=500)

# 线性算法（贪心逐块）
chunks = structchunk.chunk(content, algorithm="linear", max_chars=500)
```

hierarchical 算法从文档的标题层次结构构建章节树。它自底向上遍历树，为每个适合大小上限的章节生成一个分块。这是默认算法，因为它产生语义最连贯的分块。过大的章节在自然边界（句子、表格行、列表项、代码行）处进行子分割。相邻的同级章节在适合大小时会被贪心地合并，但受限于章节完整性约束：完整的章节可以与兄弟章节合并，但分割后的残余尾部不能合并。这防止了不同章节之间的交叉污染。hierarchical 是技术文档、报告、书籍或任何具有清晰标题结构内容的正确选择。

linear 算法使用贪心的逐块组装。每个块（段落、表格、列表、代码围栏）被添加到当前分块，直到超出大小上限，然后开始新分块。过大的块交由类型特定的子分割器处理：段落在句边界分割，表格在行边界分割，列表在项边界分割，代码围栏在行边界分割。linear 算法更简单、更快，适合没有章节层次的平面文档。

两种算法共享相同的配置参数：`max_chars`、`max_chunk_size`、`hard_max_size`、`min_chunk_size`、`sub_split_paragraph`、`sub_split_table`、`sub_split_code`、`sub_split_list`、`preserve_table_header`、`preserve_code_fence`、`forward_intro_text` 和 `doc_id`。详情请参阅 API 参考文档。

## 命令行

安装后，`structchunk` 命令作为控制台脚本可用：

```bash
structchunk document.md                                       # 层次算法，500 字符上限
structchunk document.md --algorithm linear                    # 贪心逐块
structchunk document.md --max-chars 300 --format json          # 300 字符上限，JSON 输出
structchunk document.md --quiet                                # 不打印汇总
structchunk document.md --output-dir /tmp/chunks               # 自定义输出目录
```

| 标志 | 默认值 | 说明 |
|---|---|---|
| `--algorithm` | `hierarchical` | 分块算法：`hierarchical` 或 `linear` |
| `--max-chars` | `500` | 分块字符数的硬上限 |
| `--format` | `both` | 输出格式：`json`、`md` 或 `both` |
| `--quiet` | `False` | 仅保存文件，不打印汇总 |
| `--output-dir` | `./test_result/` | 输出文件的目录 |

输出文件名包含输入文件的主文件名、算法名称和时间戳：

- `document-hierarchical-20250101_120000.json`
- `document-hierarchical-20250101_120000.md`

JSON 输出包含完整的分块列表，所有元数据字段以字典形式序列化，适合程序化消费。Markdown 输出将每个分块渲染为人类可读的章节，包含路径、源元素类型、字符范围、分块 ID 和链表指针。

当未使用 `--quiet` 时，CLI 会打印一个汇总表，显示每个分块的索引、字符数、源类型和路径路径，以及聚合统计信息：总分块数、大小范围、类型分布、续接块数和耗时。

输出目录默认为 `./test_result/`，如果不存在则自动创建。

## 文档

- [快速开始](docs/quickstart.md)
- [算法详解](docs/algorithms.md)（句子切分、标题前置、上下文吸收、路径构造、兄弟合并）
- [API 参考](docs/api.md)（`chunk()`、`chunk_file()`、`chunk_to_dicts()` 及关键字参数）
- [CLI 使用](docs/cli.md)（标志、输出格式、示例）
- [元数据参考](docs/metadata.md)（`ChunkMetadata` 的所有字段）
- [为什么选 structchunk？](docs/why-structchunk.md)（设计理念、UUID4 与 Snowflake BIGINT 的对比、fork 安全性）
- [数据库模式](docs/database-schema.md)（使用 BIGINT 主键和 pgvector 列的 PostgreSQL 模式）

## 贡献

欢迎贡献。请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解：

- 开发环境搭建和从源码安装
- 项目结构和模块概览
- 运行测试套件
- 提交拉取请求和报告问题

欢迎在 GitHub 上提交问题报告和拉取请求。

## 许可证

[MIT](LICENSE)
