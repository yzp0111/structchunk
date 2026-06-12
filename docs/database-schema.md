# Database Schema Examples

[中文版](zh-CN/database-schema.md)

structchunk is designed for direct integration with vector databases. This page
shows a complete PostgreSQL schema with [pgvector](https://github.com/pgvector/pgvector),
plus notes on MySQL, SQLite, and MongoDB.

## PostgreSQL with pgvector

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

## Schema Notes

- **`chunk_id` as `BIGINT`**: 8 bytes vs 16 for UUID4, half the B-tree fan-out, double the rows-per-page. See [Why structchunk?](why-structchunk.md#snowflake-bigint-ids) for the full comparison.
- **`doc_id` as `TEXT`**: a SHA-256 content hash (16 hex chars) for string inputs, or the absolute file path for `chunk_file()`. Same document, same `doc_id`. Index on this column for fast "all chunks of this document" lookups.
- **`content_length`, `total_length`**: pre-computed character counts for fast filtering ("show me chunks under 500 chars") without loading the full content.
- **`header_breadcrumb` as `TEXT[]`**: the list `['# H1', '## H2']` with markdown-level prefix. Useful for breadcrumb-based retrieval boosting and for displaying the section path in a UI.
- **`embedding VECTOR(1024)`**: a pgvector column. Adjust the dimension to match your embedding model (e.g. 1536 for OpenAI `text-embedding-3-small`, 1024 for many BGE models, 768 for some smaller models).

## Snowflake ID as BIGINT

`structchunk.chunk_id` is a 64-bit Snowflake-like int. The standard SQL `BIGINT`
column type fits it exactly. `str(chunk_id)` produces the standard decimal
representation (e.g. `"188704004562132992"`), which round-trips with `int(s)`
for direct database insertion.

Avoid storing the id as a string. A `VARCHAR(16)` column is 17 bytes (16+1 for
the length prefix), more than 2x the storage of `BIGINT`. String comparison is
also collation-bound and significantly slower than integer comparison.

## Generated Column for Timestamp

PostgreSQL supports a generated column that recovers the millisecond timestamp
embedded in the Snowflake id:

```sql
created_at_ms BIGINT GENERATED ALWAYS AS
    (structchunk.chunk_id_timestamp_ms(chunk_id)) STORED
```

`structchunk.chunk_id_timestamp_ms()` is a SQL function you'll need to define
in your database. Here's a Python implementation that mirrors the lib's
extraction:

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

(Use the in-Python `structchunk.chunk_id_timestamp_ms()` at insert time, or
the plpgsql function above for SQL-side recovery. Both produce identical
results.)

## Other Databases

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

`BIGINT` is the same as PostgreSQL. Store `header_breadcrumb` as a JSON array
(MySQL 5.7+ has native JSON support).

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

SQLite's `INTEGER` is 8 bytes (per the type affinity rules), so it holds the
full Snowflake id. Store `header_breadcrumb` as a JSON-encoded string.

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

Use `NumberLong` (BSON int64) for `chunk_id`. Store `header_breadcrumb` as a
native BSON array. For vector search, use MongoDB Atlas Vector Search or
[pgvector-mongo](https://github.com/timescale/pgvector-mongo)-style integrations.
