"""Basic usage example for structchunk.

Demonstrates both the linear and hierarchical algorithms. Since v0.4.0,
the default algorithm is ``hierarchical`` (was ``linear``). This example
passes both algorithms explicitly for clarity.

Run with:
    PYTHONPATH=src python3 examples/basic.py path/to/file.md
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import structchunk


def main(path: str = None) -> None:
    if path is None:
        md = """# 知识库RAG场景向量库选型

## 一、概述

本报告对比7款主流向量库。

## 二、对比表

| 数据库 | 优点 |
| --- | --- |
| Milvus | 企业级 |
| Qdrant | 高性能 |
"""
    else:
        md = Path(path).read_text(encoding="utf-8")

    print("=== Linear algorithm ===")
    for c in structchunk.chunk(md, algorithm="linear", max_chars=500):
        bc = " > ".join(c.metadata.header_breadcrumb) or "(none)"
        print(f"[{c.metadata.chunk_index}] {len(c.content)}c | {c.metadata.source_element_type} | {bc}")

    print("\n=== Hierarchical algorithm ===")
    for c in structchunk.chunk(md, max_chars=500, algorithm="hierarchical"):
        bc = " > ".join(c.metadata.header_breadcrumb) or "(none)"
        print(f"[{c.metadata.chunk_index}] {len(c.content)}c | {c.metadata.source_element_type} | {bc}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
