# 变更日志

[English](CHANGELOG.md)

所有 structchunk 的显著变更都记录在此文件中。

本格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/spec/v2.0.0.html)。

## [未发布]

## [0.1.0] - 2026-06-12

### 新增
- 双语文档（英文为规范，中文为镜像）
- `docs/` 目录，按主题组织的指南（安装、快速开始、算法、API、CLI、元数据、为什么选 structchunk、数据库模式）
- GitHub 社区健康文件（议题模板、PR 模板、CODEOWNERS、FUNDING）
- `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`AUTHORS.md`
- `scripts/check_doc_sync.py` 用于 EN/zh-CN 标题一致性校验

## [0.1.0] - 2026-06-11

### 新增
- **两种算法**：`hierarchical`（默认，结构感知，bottom-up 兄弟节点合并的树形遍历）和 `linear`（贪心逐块合并）
- **类 Snowflake 的 BIGINT 分块 ID**：64 位整数，可直接用作 SQL `BIGINT PRIMARY KEY` 列。通过 `os.register_at_fork` 实现 fork 安全，时钟回退时自旋等待最多 10ms，否则抛出 `RuntimeError`
- **带前缀的标题路径**：每个分块携带文档顺序的路径（`['# H1', '## H2']`）
- **section-complete 不变量**：`is_section_complete` 标志防止跨分节的尾部合并
- **表格表头重新前置**：按行边界切分的表格在续块上重新附带表头
- **列表/表格前言转发**：将前置段落转发到续块
- **行前缀匹配的路径注入**：避免 `## Section2` 与 `## Section2.5` 的误判
- **友好的 CLI 错误**：`--algorithm`、`--max-chars`、`--format`、`--output-dir` 标志
- **纯 Python，零运行时依赖**：测试套件仅需 `pytest`
- **192 个测试通过**：覆盖解析器、子分块器、两种算法、RAG 元数据、边界情况
