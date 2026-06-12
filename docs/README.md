# structchunk Documentation

[中文版](zh-CN/README.md)

## Overview

structchunk is a structure-aware markdown text chunker for RAG (Retrieval-Augmented
Generation) pipelines. This documentation covers installation, algorithms, the Python
API, the CLI, and metadata reference. The Chinese version of this documentation is in
[`zh-CN/`](zh-CN/README.md).

## User Guide

- [Installation](installation.md) — install from PyPI, source, or uv
- [Quick Start](quickstart.md) — first 5 minutes with structchunk
- [Algorithms](algorithms.md) — how `linear` and `hierarchical` work in detail
- [Metadata Reference](metadata.md) — every field on `ChunkMetadata`
- [Why structchunk?](why-structchunk.md) — design rationale and trade-offs vs other chunkers

## API Reference

- [API Reference](api.md) — public Python functions, classes, and configuration
- [CLI Reference](cli.md) — command-line flags, examples, and exit codes
- [Database Schema](database-schema.md) — PostgreSQL with pgvector, MySQL, SQLite, MongoDB

## Project Info

- [README](../README.md) — project entry point
- [Changelog](../CHANGELOG.md) — release history
- [Contributing](../CONTRIBUTING.md) — how to contribute
- [Code of Conduct](../CODE_OF_CONDUCT.md) — community standards
- [Security Policy](../SECURITY.md) — how to report security issues
- [Authors](../AUTHORS.md) — project lead and contributors
- [License](../LICENSE) — MIT

## Languages

This documentation is available in two languages:

- **English (canonical)**: the files in this directory
- **Chinese (zh-CN mirror)**: the files in [`zh-CN/`](zh-CN/README.md) — a translation of the English originals, with heading-parity checked by `scripts/check_doc_sync.py`
