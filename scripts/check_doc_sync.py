#!/usr/bin/env python3
"""Verify EN/zh-CN heading parity for the structchunk documentation.

Walks the repo for .md files and checks that each English canonical file
has a corresponding zh-CN mirror with matching heading structure. The
mirror may translate heading text into Chinese, but the heading count
and the level of each heading must match.

Pairs checked:
    README.md          <-> README.zh-CN.md
    CHANGELOG.md       <-> CHANGELOG.zh-CN.md
    docs/README.md     <-> docs/zh-CN/README.md
    docs/installation.md <-> docs/zh-CN/installation.md
    docs/quickstart.md <-> docs/zh-CN/quickstart.md
    docs/algorithms.md <-> docs/zh-CN/algorithms.md
    docs/api.md        <-> docs/zh-CN/api.md
    docs/cli.md        <-> docs/zh-CN/cli.md
    docs/metadata.md   <-> docs/zh-CN/metadata.md
    docs/why-structchunk.md <-> docs/zh-CN/why-structchunk.md
    docs/database-schema.md <-> docs/zh-CN/database-schema.md

Exit codes:
    0  All pairs in sync
    1  One or more pairs have a discrepancy
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Heading pattern: one or more #, then space, then text. Captures the level and text.
_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$")

# Pairs to check. Each pair is (en_path, zh_path) relative to REPO_ROOT.
PAIRS: list[tuple[str, str]] = [
    ("README.md", "README.zh-CN.md"),
    ("CHANGELOG.md", "CHANGELOG.zh-CN.md"),
    ("docs/README.md", "docs/zh-CN/README.md"),
    ("docs/installation.md", "docs/zh-CN/installation.md"),
    ("docs/quickstart.md", "docs/zh-CN/quickstart.md"),
    ("docs/algorithms.md", "docs/zh-CN/algorithms.md"),
    ("docs/api.md", "docs/zh-CN/api.md"),
    ("docs/cli.md", "docs/zh-CN/cli.md"),
    ("docs/metadata.md", "docs/zh-CN/metadata.md"),
    ("docs/why-structchunk.md", "docs/zh-CN/why-structchunk.md"),
    ("docs/database-schema.md", "docs/zh-CN/database-schema.md"),
]


def extract_headings(path: Path) -> list[tuple[int, str]]:
    """Return a list of (level, text) tuples for H1..H6 headings in the file."""
    headings: list[tuple[int, str]] = []
    if not path.is_file():
        return headings
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            text = m.group(2)
            headings.append((level, text))
    return headings


def check_pair(en_rel: str, zh_rel: str) -> tuple[bool, str]:
    """Check one EN/zh-CN pair. Returns (ok, message)."""
    en_path = REPO_ROOT / en_rel
    zh_path = REPO_ROOT / zh_rel

    if not en_path.is_file():
        return False, f"  EN file missing: {en_rel}"
    if not zh_path.is_file():
        return False, f"  zh-CN file missing: {zh_rel}"

    en_h = extract_headings(en_path)
    zh_h = extract_headings(zh_path)

    if len(en_h) != len(zh_h):
        return False, (
            f"  heading count mismatch: EN has {len(en_h)} headings, "
            f"zh-CN has {len(zh_h)} headings"
        )

    for i, ((en_lvl, en_txt), (zh_lvl, zh_txt)) in enumerate(zip(en_h, zh_h)):
        if en_lvl != zh_lvl:
            return False, (
                f"  heading {i + 1} level mismatch: "
                f"EN is H{en_lvl} (`{en_txt}`), "
                f"zh-CN is H{zh_lvl} (`{zh_txt}`)"
            )

    return True, f"  {len(en_h)} headings, all levels match"


def main() -> int:
    print(f"Checking EN/zh-CN heading parity in {REPO_ROOT}")
    print(f"{'=' * 60}")

    n_total = 0
    n_pass = 0
    n_fail = 0

    for en_rel, zh_rel in PAIRS:
        n_total += 1
        print(f"\n[{n_total}] {en_rel}  <->  {zh_rel}")
        ok, msg = check_pair(en_rel, zh_rel)
        print(msg)
        if ok:
            n_pass += 1
        else:
            n_fail += 1

    print(f"\n{'=' * 60}")
    print(f"Total pairs: {n_total}")
    print(f"In sync:     {n_pass}")
    print(f"Mismatches:  {n_fail}")

    if n_fail == 0:
        print("\nAll pairs in sync. OK.")
        return 0
    else:
        print(f"\n{n_fail} pair(s) out of sync. FAIL.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
