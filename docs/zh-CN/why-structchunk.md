# 为什么选 structchunk?

[English](../why-structchunk.md)

RAG（检索增强生成）的质量很大程度上取决于分块质量。朴素的分块器会从表格中间断开，将标题与其内容分离，并生成嵌入向量无法恢复章节上下文的块。structchunk 正是为了解决这些损害检索质量的具体问题而构建的。

## 朴素分块器的问题

大多数现成的分块器（LangChain 的 `CharacterTextSplitter`、`RecursiveCharacterTextSplitter`、LlamaIndex 的 `SentenceSplitter` 等）按字符数或 token 数进行分割。这会导致四个反复出现的问题：

1. **标题与内容分离。** 位于块末尾的标题在语义上引导的是*下一个*组的内容，但按字符数分割的分块器却让它悬在上一个块的尾部。该块的嵌入向量完全不知道这段文本属于哪个章节。

2. **表格在行中间断开。** 一个超过大小上限的宽表格会被从中间切为两半。续接块中的行在没有列表头的情况下失去了意义。

3. **章节上下文丢失。** 位于 `### 子章节` 深处的段落，如果因大小上限的限制而被强制与另一个不相关的 `### 子章节` 的段落放在同一个块中，嵌入向量无法区分该文本属于哪个子章节。

4. **长文档静默失败。** 一份 50 页的 markdown 报告生成的块可能看起来都像重复的目录。如果没有路径注入，没有一个块是自包含的。

structchunk 通过结构感知解析、标题上提、表头重新前置和后置路径注入，解决了以上所有四个问题。

## 设计原则

1. **结构感知。** 将 markdown 解析为原子块类型（标题、代码围栏、表格、列表、段落、块引用、数学公式、水平线），并在分块时尊重这些边界。除非 `hard_max_size` 强制要求，否则绝不分割行、列表项或句子。

2. **标题始终领先其内容。** 末尾的标题会被前移至下一个组。不存在孤立的标题。

3. **表格保留列标题。** 当表格在行边界处被分割时，表头行会被重新前置到每个续接块中。

4. **列表吸收其前面的段落。** 当列表开启一个新的组时，其前面的段落（或标记行）会被吸收作为上下文。

5. **文档顺序路径，带 markdown 级别前缀。** 每个块携带 `['# H1', '## H2', '### H3']` —— 从文档根到当前章节的完整路径。后置处理会注入任何缺失的标题，确保每个块自包含。

6. **Snowflake BIGINT ID，数据库友好。** 8 字节（对比 UUID4 的 16 字节），可按创建时间排序，对 B-tree 友好。详见下方的 [Snowflake BIGINT ID](#snowflake-bigint-id)。

7. **纯 Python，零运行时依赖。** 无供应链风险，无版本冲突，无传递性漏洞。

8. **Fork 安全的 ID 生成。** `os.register_at_fork` 在每个子进程中重置生成器，因此两个工作进程永远不会生成冲突的 ID。

## 与其他分块器的对比

| 特性 | structchunk | LangChain `CharacterTextSplitter` | LangChain `MarkdownTextSplitter` | LlamaIndex `SentenceSplitter` | Custom regex |
|---------|-------------|-----------------------------------|----------------------------------|-------------------------------|--------------|
| 结构感知 | 是（11 种块类型） | 否 | 部分（仅标题） | 否 | 取决于实现 |
| 标题上提 | 是 | 否 | 否 | 否 | 否 |
| 表格行边界分割 | 是 | 否 | 否 | 否 | 否 |
| 表头重新前置 | 是 | 否 | 否 | 否 | 否 |
| 列表项边界分割 | 是 | 否 | 否 | 否 | 否 |
| 中日韩 + 英文句子分割 | 是 | 仅英文 | 仅英文 | 仅英文 | 否 |
| URL/邮件在句子中保护 | 是 | 否 | 否 | 否 | 否 |
| 层次化章节树 | 是 | 否 | 部分 | 否 | 否 |
| 章节完整不变量 | 是 | 否 | 否 | 否 | 否 |
| Snowflake BIGINT ID | 是 | 否 | 否 | 否 | 否 |
| 零运行时依赖 | 是 | 否（依赖 langchain） | 否 | 否 | 是 |

## Snowflake BIGINT ID

`chunk.metadata.chunk_id` 是一个 64 位的 Snowflake 风格整数（8 字节），可直接映射到 SQL 的 `BIGINT PRIMARY KEY` 列。`str(chunk_id)` 生成标准的十进制表示形式，这也是 Twitter、Discord、Instagram 以及所有其他 Snowflake 用户在 JSON API 中使用的格式。

| 属性 | Snowflake BIGINT (structchunk) | UUID4 | Snowflake 字符串形式 |
|----------|-------------------------------|-------|---------------------|
| 数据库存储 | `BIGINT`（8 字节） | `UUID`（16 字节） | `VARCHAR(N)`（16+ 字节） |
| 比较成本 | `btint8cmp`：2 个寄存器比较 | `uuid_cmp`：16 字节 | `varstr_cmp`：受排序规则影响 |
| 可按创建时间排序 | 是 | 否 | 是 |
| B-tree 索引局部性 | 相邻 ID 聚集 | 随机分布 | 与 BIGINT 相同 |
| 与 `int(s)` 互转 | 是 | 否 | 仅带进制参数时 |
| 业界使用 | Twitter、Discord、Instagram、Snowflake（数据库） | Web 应用记录 | 几乎无人使用 |

对于涉及批量插入和时间范围查询的 RAG 工作负载，BIGINT Snowflake ID 是标准选择。嵌入的时间戳可通过 `structchunk.chunk_id_timestamp_ms(chunk_id)` 恢复。

**时间戳饱和：** 按当前纪元（2026-01-01）和 41 位时间戳字段计算，Snowflake ID 将在 **2095-08-15** 左右饱和。此后，ID 将超出标准 SQL `BIGINT` 范围，可能被数据库拒绝。

## 什么时候不应使用 structchunk

structchunk 是专为 markdown 打造的。如果你的输入是：

- **纯文本**（无 markdown 结构）：使用 LangChain 的 `CharacterTextSplitter`。标题路径注入对纯文本无效。
- **HTML**：使用 BeautifulSoup 或专用的 HTML 分块器。（HTML 支持已在路线图上。）
- **纯代码语料库**：使用代码感知的分块器，如 `langchain.text_splitter.Language` 或 `tree-sitter`。structchunk 的代码子分割器是回退方案，而非代码感知的解析器。
- **非常短的文档**（几百词）：任何分块器都可以。structchunk 的开销在此场景下是浪费的。

对于所有其他基于 markdown 文档的 RAG 用例，structchunk 能生成比朴素分块器更高质量的分块。

## 基准测试

即将推出。维护者正在准备在标准 RAG 基准（如 HotpotQA、Natural Questions）上与 LangChain 的 `MarkdownTextSplitter` 和 LlamaIndex 的 `SentenceSplitter` 进行对比。如果你有希望看到的基准套件，请提交 issue。

## 实际应用

structchunk 是一个年轻的开源库。如果你在生产环境中使用它，请提交 PR 将你的项目添加到这一节。我们非常乐意展示实际部署案例。
