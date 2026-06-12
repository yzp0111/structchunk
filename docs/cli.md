# CLI Reference

[中文版](zh-CN/cli.md)

## Synopsis

```
structchunk <input> [flags]
```

## Description

`structchunk` is the command-line entry point for the structchunk library. It reads a
markdown file, runs the chosen chunking algorithm, and saves the results to disk in
both JSON and Markdown formats (or just one, depending on `--format`).

The CLI is installed automatically when you `pip install structchunk`. After install,
run `structchunk --help` to see this help text from your shell.

By default the CLI prints a summary table showing each chunk's index, character count,
source type, and breadcrumb path, plus aggregate statistics (total chunks, size range,
type distribution, continuation count, elapsed time). Pass `--quiet` to suppress this.

## Arguments

| Argument | Description |
|----------|-------------|
| `input` | Required. Path to the input markdown file. Must be UTF-8 encoded. |

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--algorithm` | `linear` or `hierarchical` | `hierarchical` | Chunking algorithm. Hierarchical (default) is structure-aware. Linear is greedy. |
| `--max-chars` | int | `500` | Hard cap on chunk size in characters. Dify-friendly default. |
| `--format` | `json`, `md`, or `both` | `both` | Output format(s). `json` emits a single JSON file with all chunks. `md` emits a human-readable Markdown summary. `both` writes both. |
| `--quiet` | flag (boolean) | `False` | Suppress the chunk summary printout. Files are still saved. |
| `--output-dir` | path | `./test_result/` | Directory for the output files. Created if it does not exist. |

## Examples

### Default usage

```
structchunk document.md
```

Chunks `document.md` with the hierarchical algorithm, `max-chars=500`, and saves both
JSON and Markdown to `./test_result/`.

### Use the linear algorithm

```
structchunk document.md --algorithm linear
```

### Tighter chunk size

```
structchunk document.md --max-chars 300
```

Every chunk is at most 300 characters.

### JSON output only

```
structchunk document.md --format json
```

### Custom output directory

```
structchunk document.md --output-dir /tmp/chunks
```

## Output Files

Output filenames include the source file's stem, the algorithm, and a timestamp:

```
<stem>-切块结果-<algorithm>-<YYYYMMDD_HHMMSS>.json
<stem>-切块结果-<algorithm>-<YYYYMMDD_HHMMSS>.md
```

For example, chunking `report.md` with the hierarchical algorithm at 14:32:05 on
2026-06-12 produces:

```
report-切块结果-hierarchical-20260612_143205.json
report-切块结果-hierarchical-20260612_143205.md
```

The `json` file contains an array of chunk dicts (the same shape as
`chunk_to_dicts()`). The `md` file is a human-readable summary with one section
per chunk, showing the breadcrumb, source element type, character count, and
content.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success. Output files written. |
| `1` | Failure. Either the input file was not found, or the file could not be decoded as UTF-8. An error message is printed to stderr. |

## See Also

- [Quick Start](quickstart.md) — programmatic usage
- [Algorithms](algorithms.md) — algorithm internals
- [API Reference](api.md) — Python API
