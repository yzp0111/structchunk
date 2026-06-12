# CLI 参考

[English](../cli.md)

## 命令格式

```
structchunk <input> [flags]
```

## 说明

`structchunk` 是 structchunk 库的命令行入口。它读取一个 markdown 文件，运行所选的切分算法，并将结果以 JSON 和 Markdown 两种格式（或仅一种，取决于 `--format`）保存到磁盘。

该 CLI 在您执行 `pip install structchunk` 时自动安装。安装后，运行 `structchunk --help` 即可在终端中查看此帮助文本。

默认情况下，CLI 会打印一个汇总表格，显示每个块的索引、字符数、来源类型和路径路径，以及总计统计信息（总块数、大小范围、类型分布、续块数量、运行耗时）。传递 `--quiet` 可禁止此输出。

## 参数

| 参数 | 说明 |
|------|------|
| `input` | 必需。输入 markdown 文件的路径。必须是 UTF-8 编码。 |

## 选项

| 标志 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--algorithm` | `linear` 或 `hierarchical` | `hierarchical` | 切分算法。Hierarchical（默认）能感知文档结构。Linear 为贪心算法。 |
| `--max-chars` | int | `500` | 块大小的硬性上限（字符数）。Dify 友好的默认值。 |
| `--format` | `json`、`md` 或 `both` | `both` | 输出格式。`json` 输出一个包含所有块的 JSON 文件。`md` 输出人类可读的 Markdown 摘要。`both` 则同时写入两种格式。 |
| `--quiet` | 标志（布尔值） | `False` | 禁止打印块汇总信息。文件仍会正常保存。 |
| `--output-dir` | 路径 | `./test_result/` | 输出文件的目标目录。如果目录不存在则会自动创建。 |

## 示例

### 默认用法

```
structchunk document.md
```

使用 hierarchical 算法和 `max-chars=500` 对 `document.md` 进行切分，并将 JSON 和 Markdown 文件保存到 `./test_result/`。

### 使用 linear 算法

```
structchunk document.md --algorithm linear
```

### 更小的块大小

```
structchunk document.md --max-chars 300
```

每个块最多 300 个字符。

### 仅输出 JSON

```
structchunk document.md --format json
```

### 自定义输出目录

```
structchunk document.md --output-dir /tmp/chunks
```

## 输出文件

输出文件名包含源文件的主文件名（stem）、算法名称和时间戳：

```
<stem>-切块结果-<algorithm>-<YYYYMMDD_HHMMSS>.json
<stem>-切块结果-<algorithm>-<YYYYMMDD_HHMMSS>.md
```

例如，在 2026-06-12 14:32:05 使用 hierarchical 算法对 `report.md` 进行切分将生成：

```
report-切块结果-hierarchical-20260612_143205.json
report-切块结果-hierarchical-20260612_143205.md
```

`json` 文件包含一个块字典数组（与 `chunk_to_dicts()` 的输出结构相同）。`md` 文件是一个人类可读的摘要，每个块一个章节，显示路径、源元素类型、字符数和内容。

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 成功。输出文件已写入。 |
| `1` | 失败。输入文件未找到，或文件无法按 UTF-8 解码。错误信息将打印到 stderr。 |

## 参见

- [快速入门](quickstart.md) — 编程用法
- [算法](algorithms.md) — 算法内部细节
- [API 参考](api.md) — Python API
