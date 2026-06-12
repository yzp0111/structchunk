# 数据库模式示例

[English](../database-schema.md)

structchunk 设计用于直接集成向量数据库。本页展示了一个完整的 PostgreSQL 模式（含 [pgvector](https://github.com/pgvector/pgvector)），以及 MySQL、SQLite 和 MongoDB 的说明。

## PostgreSQL 与 pgvector

```sql
CREATE TABLE chunks (
    chunk_id BIGINT PRIMARY KEY,            -- Snowflake int, 8 bytes
    doc_id TEXT NOT NULL,                    -- content hash or file path
    chunk_index INT NOT NULL,
    total_chunks INT NOT NULL,
    content TEXT NOT NULL,
    content_length INT NOT NULL,             -- pre-computed, filterable
    total_length INT NOT NULL,               -- same as content_length since v0.4.0
    header_breadcrumb TEXT[],
    embedding VECTOR(1024),                  -- pgvector column
    created_at_ms BIGINT GENERATED ALWAYS AS
        (structchunk.chunk_id_timestamp_ms(chunk_id)) STORED
);

CREATE INDEX idx_chunks_doc_id ON chunks (doc_id);
CREATE INDEX idx_chunks_chunk_id ON chunks (chunk_id);
```

## 模式说明

- **`chunk_id` 使用 `BIGINT`**：8 字节对比 UUID4 的 16 字节，B 树扇出减半，每页行数翻倍。完整对比见[为什么选择 structchunk？](why-structchunk.md#snowflake-bigint-ids)。
- **`doc_id` 使用 `TEXT`**：对于字符串输入，是 SHA-256 内容哈希（16 位十六进制字符）；对于 `chunk_file()`，是绝对文件路径。同一文档具有相同的 `doc_id`。在此列上建立索引，以便快速查找"某文档的所有块"。
- **`content_length`、`total_length`**：预计算的字符数，用于快速过滤（如"显示 500 字符以下的块"），而无需加载完整内容。
- **`header_breadcrumb` 使用 `TEXT[]`**：形如 `['# H1', '## H2']` 的列表，带有 markdown 级别前缀。可用于基于路径的检索增强，以及在 UI 中显示章节路径。
- **`embedding VECTOR(1024)`**：pgvector 列。根据你的嵌入模型调整维度（例如 OpenAI `text-embedding-3-small` 使用 1536，许多 BGE 模型使用 1024，部分小型模型使用 768）。

## Snowflake ID 作为 BIGINT

`structchunk.chunk_id` 是一个 64 位类 Snowflake 整数。标准 SQL `BIGINT` 列类型正好匹配。`str(chunk_id)` 生成标准的十进制表示（例如 `"188704004562132992"`），可通过 `int(s)` 往返转换，用于直接插入数据库。

避免将 ID 存储为字符串。`VARCHAR(16)` 列占用 17 字节（16+1 长度前缀），是 `BIGINT` 存储空间的 2 倍以上。字符串比较还受排序规则限制，且比整数比较慢得多。

## 自动生成的时间戳列

PostgreSQL 支持通过生成列恢复 Snowflake ID 中嵌入的毫秒级时间戳：

```sql
created_at_ms BIGINT GENERATED ALWAYS AS
    (structchunk.chunk_id_timestamp_ms(chunk_id)) STORED
```

`structchunk.chunk_id_timestamp_ms()` 是一个 SQL 函数，你需要在数据库中定义。以下是一个镜像了库中提取逻辑的 Python 实现：

```sql
-- Python reference (lib's _models.py:201-203)
-- timestamp_bits = 64 - 10 - 12 = 42
-- _EPOCH_MS = 1735689600000  (2026-01-01 00:00:00 UTC)
-- extracted = (value >> 12 >> 10) + 1735689600000

-- Equivalent in plpgsql:
CREATE OR REPLACE FUNCTION structchunk_chunk_id_timestamp_ms(chunk_id BIGINT)
RETURNS BIGINT AS $$
BEGIN
    RETURN (chunk_id >> 22) + 1735689600000;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

（在插入时使用 Python 内的 `structchunk.chunk_id_timestamp_ms()`，或使用上述 plpgsql 函数在 SQL 侧恢复。两者产生的结果完全相同。）

## 其他数据库

### MySQL

```sql
CREATE TABLE chunks (
    chunk_id BIGINT PRIMARY KEY,
    doc_id VARCHAR(64) NOT NULL,
    chunk_index INT NOT NULL,
    total_chunks INT NOT NULL,
    content TEXT NOT NULL,
    content_length INT NOT NULL,
    total_length INT NOT NULL,
    header_breadcrumb JSON,         -- store as JSON array
    embedding LONGBLOB               -- or use a vector extension
) ENGINE=InnoDB;
```

`BIGINT` 与 PostgreSQL 相同。将 `header_breadcrumb` 存储为 JSON 数组（MySQL 5.7+ 支持原生 JSON）。

### SQLite

```sql
CREATE TABLE chunks (
    chunk_id INTEGER PRIMARY KEY,   -- 8-byte integer
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_length INTEGER NOT NULL,
    total_length INTEGER NOT NULL,
    header_breadcrumb TEXT          -- JSON-encoded array
);
```

SQLite 的 `INTEGER` 是 8 字节（根据类型亲和性规则），因此可以完整存储 Snowflake ID。将 `header_breadcrumb` 存储为 JSON 编码的字符串。

### MongoDB

```javascript
db.chunks.insertOne({
    chunk_id: NumberLong("188704004562132992"),
    doc_id: "abc123def4567890",
    chunk_index: 0,
    total_chunks: 5,
    content: "...",
    content_length: 487,
    total_length: 487,
    header_breadcrumb: ["# Title", "## Section"],
    embedding: [...]  // array of floats
})
```

使用 `NumberLong`（BSON int64）存储 `chunk_id`。将 `header_breadcrumb` 存储为原生 BSON 数组。向量搜索可使用 MongoDB Atlas Vector Search 或 [pgvector-mongo](https://github.com/timescale/pgvector-mongo) 风格的集成。
