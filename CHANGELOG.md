# Changelog

[中文版](CHANGELOG.zh-CN.md)

All notable changes to structchunk are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Bilingual documentation (English canonical, Chinese mirror)
- `docs/` directory with topic-organized guides (installation, quickstart, algorithms, api, cli, metadata, why-structchunk, database-schema)
- GitHub community health files (issue templates, PR template, CODEOWNERS, FUNDING)
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `AUTHORS.md`
- `scripts/check_doc_sync.py` for EN/zh-CN heading parity verification

## [0.1.0] - 2026-06-11

### Added
- **Two algorithms**: `hierarchical` (default, structure-aware, tree-walked with bottom-up sibling merge) and `linear` (greedy block-by-block)
- **Snowflake-like BIGINT chunk IDs**:64-bit integers suitable for SQL `BIGINT PRIMARY KEY` columns. Fork-safe via `os.register_at_fork`, clock-resilient (spin-waits up to10ms, then raises `RuntimeError`)
- **Header-prefix breadcrumbs**: each chunk carries an in-document-order breadcrumb (`['# H1', '## H2']`)
- **Section-complete invariant**: `is_section_complete` flag prevents cross-section merge of split-section tails
- **Table header re-prepending**: tables split at row boundaries get column headers re-attached
- **List/table intro forwarding**: a leading paragraph is forwarded to continuation chunks
- **Line-prefix match for breadcrumb injection**: no false positives on `## Section2` vs `## Section2.5`
- **CLI with friendly errors**: `--algorithm`, `--max-chars`, `--format`, `--output-dir` flags
- **Pure Python, zero runtime dependencies**: only `pytest` is required for the test suite
- **192 tests passing**: covers parser, splitters, both algorithms, RAG metadata, edge cases
