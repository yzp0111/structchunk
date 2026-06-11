"""Command-line interface for structchunk.

Run after install via::

    structchunk path/to/doc.md
    structchunk doc.md --algorithm hierarchical --max-chars 300
    structchunk doc.md --format json --quiet
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import chunk, chunk_to_dicts


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="structchunk",
        description="Chunk a markdown file for RAG retrieval.",
    )
    parser.add_argument("input", help="Input markdown file path")
    parser.add_argument(
        "--algorithm",
        choices=["linear", "hierarchical"],
        default="hierarchical",
        help="Chunking algorithm (default: hierarchical)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=500,
        help="Hard cap on chunk size in characters (default: 500, Dify-friendly)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "md", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only save files, don't print summary",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./test_result/",
        help="Directory for output files (default: ./test_result/)",
    )
    return parser


def _print_summary(chunks, input_path: str, algorithm: str) -> None:
    if not chunks:
        print(f"No chunks produced from {input_path}.")
        return
    print(f"\n{'=' * 60}")
    print(f"Chunk Summary ({algorithm} algorithm)")
    print(f"{'=' * 60}")
    print(f"Total chunks: {len(chunks)}")
    sizes = [len(c.content) for c in chunks]
    print(f"Size range: {min(sizes)}-{max(sizes)} chars")
    print(f"Avg size: {sum(sizes) / len(sizes):.0f} chars")
    types: dict[str, int] = {}
    for c in chunks:
        t = c.metadata.source_element_type
        types[t] = types.get(t, 0) + 1
    print(f"Types: {dict(sorted(types.items()))}")
    continuations = sum(1 for c in chunks if c.metadata.continuation)
    print(f"Continuations: {continuations}")

    print(f"\n{'─' * 60}")
    for i, c in enumerate(chunks):
        bc = " > ".join(c.metadata.header_breadcrumb)
        src = (
            f"{c.metadata.source_element_type}"
            f"#{c.metadata.source_element_position}"
        )
        cont = " [cont]" if c.metadata.continuation else ""
        print(f"  {i:2d} | {len(c.content):4d}c | {src:16s} | {bc[:50]}{cont}")
    print(f"{'─' * 60}")


def _save_outputs(
    chunks,
    input_path: str,
    algorithm: str,
    max_chars: int,
    output_format: str,
    out_dir: Path | None = None,
) -> None:
    stem = Path(input_path).stem
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    base_name = f"{stem}-切块结果-{algorithm}-{timestamp}"

    if out_dir is None:
        out_dir = Path.cwd() / "test_result"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if output_format in ("json", "both"):
        json_path = out_dir / f"{base_name}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(chunk_to_dicts(chunks), f, ensure_ascii=False, indent=2)
        print(f"JSON saved: {json_path}")

    if output_format in ("md", "both"):
        md_path = out_dir / f"{base_name}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Chunk Results: {input_path}\n")
            f.write(f"# algorithm={algorithm}, max_chars={max_chars}\n")
            f.write(f"# Total chunks: {len(chunks)}\n\n")
            for i, c in enumerate(chunks):
                f.write(f"--- Chunk {i} ---\n")
                f.write(
                    f"breadcrumb: {' > '.join(c.metadata.header_breadcrumb)}\n"
                )
                f.write(
                    f"type: {c.metadata.source_element_type}"
                    f" | pos: {c.metadata.source_element_position}\n"
                )
                f.write(f"continuation: {c.metadata.continuation}\n")
                f.write(
                    f"chars: {len(c.content)}"
                    f" | range: {c.metadata.char_offset_start}-"
                    f"{c.metadata.char_offset_end}\n"
                )
                f.write(f"chunk_id: {c.metadata.chunk_id}\n")
                f.write(
                    f"prev: {c.metadata.prev_chunk_id}"
                    f" | next: {c.metadata.next_chunk_id}\n"
                )
                f.write(f"\n{c.content}\n\n")
        print(f"Markdown saved: {md_path}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    try:
        with open(args.input, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"File not found: {args.input}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as e:
        print(f"Could not decode {args.input} as UTF-8: {e}", file=sys.stderr)
        return 1

    start = time.time()
    chunks = chunk(
        content,
        algorithm=args.algorithm,
        max_chars=args.max_chars,
    )
    elapsed = time.time() - start

    _save_outputs(
        chunks,
        args.input,
        args.algorithm,
        args.max_chars,
        args.format,
        out_dir=Path(args.output_dir),
    )

    if not args.quiet:
        _print_summary(chunks, args.input, args.algorithm)
        print(f"\nChunked in {elapsed * 1000:.1f}ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
