# structchunk 文档

[English](../README.md)

## 概述

structchunk 是一个面向 RAG（检索增强生成）管道的结构感知 markdown 文本分块器。本文档涵盖安装、算法、Python API、CLI 和元数据参考。本文档的中文版位于 [`zh-CN/`](README.md) 目录（译注：本文件即中文版的 docs README，所有 zh-CN 文档都在当前目录下）。

## 用户指南

- [安装](installation.md) — 从 PyPI、源码或 uv 安装
- [快速开始](quickstart.md) — 5 分钟上手 structchunk
- [算法](algorithms.md) — `linear` 与 `hierarchical` 的详细工作机制
- [元数据参考](metadata.md) — `ChunkMetadata` 的所有字段
- [为什么选 structchunk？](why-structchunk.md) — 设计理念与对比其他分块器

## API 参考

- [API 参考](api.md) — 公共 Python 函数、类和配置
- [CLI 参考](cli.md) — 命令行标志、示例和退出码
- [数据库模式](database-schema.md) — PostgreSQL + pgvector、MySQL、SQLite、MongoDB

## 项目信息

- [README](../../README.zh-CN.md) — 项目入口
- [变更日志](../../CHANGELOG.zh-CN.md) — 发布历史
- [贡献指南](../../CONTRIBUTING.md) — 如何贡献
- [行为准则](../../CODE_OF_CONDUCT.md) — 社区规范
- [安全策略](../../SECURITY.md) — 如何报告安全问题
- [作者](../../AUTHORS.md) — 项目负责人与贡献者
- [许可证](../../LICENSE) — MIT

## 语言版本

本文档提供两种语言版本：

- **英文（规范）**：[`docs/`](../README.md) 目录下的文件
- **中文（zh-CN 镜像）**：[`docs/zh-CN/`](README.md) 目录下的文件，是英文原文的翻译，标题一致性由 `scripts/check_doc_sync.py` 校验
