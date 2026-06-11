"""Phase 1: parse raw markdown text into atomic blocks.

An *atomic block* is the smallest unit that should never be split across
chunk boundaries (except when it alone exceeds ``hard_max_size``, in
which case the splitters take over). Recognized types:

* FRONTMATTER  -- YAML frontmatter between ``---`` fences
* HEADER       -- ``#`` / ``##`` / ... lines
* CODE_FENCE   -- triple-backtick or tilde code blocks
* TABLE        -- first row + separator (column header)
* TABLE_ROW    -- one data row of a table
* LIST         -- bullet / ordered list with continuation lines
* BLOCKQUOTE   -- ``>``-prefixed paragraph
* MATH_BLOCK   -- ``$$ ... $$`` block
* HR           -- horizontal rule
* PARAGRAPH    -- default block
* BLANK        -- empty / whitespace-only line
"""

from __future__ import annotations

import re

from ._models import AtomicBlock, BlockType


_RE_HEADER = re.compile(r"^(#{1,6})\s+(.+)$")
_RE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_RE_TABLE_SEP = re.compile(r"^\s*\|?\s*[-:]+[-|\s:]*\|?\s*$")
_RE_LIST_ITEM = re.compile(r"^(\s{0,3})([-*+]|[0-9]+[.)])\s+")
_RE_BLOCKQUOTE = re.compile(r"^\s{0,3}(>)\s?")
_RE_MATH_OPEN = re.compile(r"^\s*\$\$$")
_RE_HR = re.compile(r"^\s{0,3}([-*_])\s*(\1\s*){2,}$")
_RE_FRONTMATTER_OPEN = re.compile(r"^---\s*$")

# Sentence boundary (used by the paragraph sub-splitter). Matches either:
# 1. a non-terminator run followed by one or more terminators and optional
#    trailing whitespace, OR
# 2. a trailing fragment that has no terminator at the end.
# Works for both Chinese (no space after 。) and English (space after .).
_RE_SENTENCE = re.compile(r"[^.!?。！？]+[.!?。！？]+\s*|[^.!?。！？]+\s*$")

# URL/email protection. Used by _protect_urls and _restore_urls to keep
# sentence-level splitting from cutting at dots inside URLs (e.g.
# ``api.openai.com``) or email local-part/domain separators.
# CJK / fullwidth punctuation ranges — must terminate URL/email matches
# because Chinese text has no whitespace between English and Chinese.
_CJK = "\u3000-\u303f\u4e00-\u9fff\uff00-\uffef"

_RE_URL = re.compile(rf"[A-Za-z][A-Za-z0-9+.\-]*://[^\s)\]<>\"'{_CJK}]+")
_RE_EMAIL = re.compile(
    rf"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{{2,}}\b"
)
# Markdown image / link reference: ![alt](url) or [text](url).
# The ``!`` in image syntax is NOT a sentence terminator.
_RE_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
# Version numbers like ``1.2.3`` or ``v1.2.3`` (must have ≥2 dots so we
# don't accidentally protect plain decimal numbers like ``1.2`` or
# ``3.14``). For single-dot patterns starting with a letter
# (e.g. ``Apache2.0``, ``Foo.5``), see ``_RE_VERSIONED_NAME`` below.
_RE_VERSION = re.compile(r"\b(?:v\d+|\d+)(?:\.\d+){2,}\b")
# Letter-prefixed dotted number: ``Apache2.0``, ``Foo.5``, ``Bar.99``.
# Catches the table-content bug where ``Apache2.0|Docker/K8s|...``
# would otherwise be matched as one giant "sentence" by the
# sentence regex (because ``2.`` looks like a terminator). Plain
# decimals like ``3.14`` are NOT protected (they start with a digit,
# not a letter) — that distinction is what lets the sentence regex
# still find sentence boundaries in normal text like
# ``The value is 3.14. Next sentence.``.
_RE_VERSIONED_NAME = re.compile(r"\b[A-Za-z][A-Za-z0-9]*\.\d+(?:\.\d+)*\b")
# Dotted number followed by a unit: ``1.8GB``, ``2.1GB``, ``0.8GB``,
# ``1.0GB``. Catches the same table-content bug as
# ``_RE_VERSIONED_NAME`` but for the more common case where the
# number is the cell value (memory size, latency, etc.). Requires
# at least one trailing letter so that plain decimals like ``3.14``
# are NOT matched — the trailing letter is what signals "this is a
# value with a unit, not a real decimal".
_RE_VALUED_NUM = re.compile(r"\b\d+\.\d+[A-Za-z]+\b")
# Method/property call before ``(``: ``obj.method(``.
# The ``(`` is a lookahead, not consumed.
_RE_FUNC_CALL = re.compile(r"\b\w+\.\w+(?=\s*\()")
# File name with lowercase extension: ``api.md``, ``test.py``, ``docs/api.md``.
# 2–5 letter extension excludes single-letter extensions and most
# abbreviations (which are usually uppercase or 1 letter).
_RE_FILE_NAME = re.compile(r"\b\w+\.[a-z]{2,5}\b")
# Fallback: any dotted word sequence with ≥3 segments. Catches
# module paths like ``foo.bar.baz`` that don't match the more
# specific patterns. Requires 3+ segments to avoid matching plain
# decimals like ``3.14`` (which has 2 segments).
_RE_DOTTED_SEQ = re.compile(r"\b\w+(?:\.\w+){2,}\b")
_PROTECT_CHAR = "\u2024"  # one-dot leader (U+2024): visually distinct placeholder
_BANG_PROTECT = "\u01c3"  # Latin letter 'ǃ' (rare): protects markdown image '!'


def _protect_urls(text: str) -> tuple[str, list[str]]:
    """Replace ``.`` inside URLs, emails, version numbers, function
    calls, and file names, and ``!`` in markdown image syntax, with
    placeholder characters.

    The sentence-boundary regex would otherwise cut at every internal
    dot in patterns like ``api.openai.com``, ``v1.2.3``,
    ``obj.method()``, or ``docs/api.md``. Swapping the dots to a
    Unicode placeholder keeps the token intact during splitting. Call
    :func:`_restore_urls` to swap them back.

    Order of application matters: image syntax and URL/email first
    (they're consumed as whole units), then the broader dotted patterns.
    A URL like ``https://api.openai.com/v1`` is already fully protected
    by the URL step, so the dotted fallback only catches sequences the
    earlier patterns missed.
    """
    protected: list[str] = []

    def _sub_dots(match: re.Match) -> str:
        original = match.group(0)
        protected.append(original)
        return original.replace(".", _PROTECT_CHAR)

    def _sub_image(match: re.Match) -> str:
        original = match.group(0)
        protected.append(original)
        return _BANG_PROTECT + original[1:]

    text = _RE_MD_IMAGE.sub(_sub_image, text)
    text = _RE_URL.sub(_sub_dots, text)
    text = _RE_EMAIL.sub(_sub_dots, text)
    text = _RE_VERSION.sub(_sub_dots, text)
    text = _RE_FUNC_CALL.sub(_sub_dots, text)
    text = _RE_FILE_NAME.sub(_sub_dots, text)
    text = _RE_VERSIONED_NAME.sub(_sub_dots, text)
    text = _RE_VALUED_NUM.sub(_sub_dots, text)
    text = _RE_DOTTED_SEQ.sub(_sub_dots, text)
    return text, protected


def _restore_urls(text: str, protected: list[str]) -> str:
    """Reverse :func:`_protect_urls` — swap the placeholder dots and bang back.

    When a markdown image ``![alt](url)`` is protected, both the image
    syntax (with its ``!`` swapped) and the URL inside it (with its dots
    swapped) end up in ``protected``. After the first restoration replaces
    the image, the inner URL placeholder is gone from the text, so the
    second restoration would no-op. We guard against that with a
    membership check.
    """
    for original in protected:
        if original.startswith("!["):
            placeholder = _BANG_PROTECT + original[1:].replace(".", _PROTECT_CHAR)
        else:
            placeholder = original.replace(".", _PROTECT_CHAR)
        if placeholder in text:
            text = text.replace(placeholder, original, 1)
    return text


def _line_len(line: str) -> int:
    return len(line) + 1


def _block_text(block: AtomicBlock) -> str:
    return "\n".join(block.lines)


def _parse_atomic_blocks(content: str) -> list[AtomicBlock]:
    """Walk lines of *content* and group them into atomic blocks."""
    if not content or not content.strip():
        return []

    lines = content.split("\n")
    blocks: list[AtomicBlock] = []

    offset = 0
    i = 0

    if lines and _RE_FRONTMATTER_OPEN.match(lines[0].strip()):
        fence_lines = [lines[0]]
        end = _line_len(lines[0])
        j = 1
        found_close = False
        while j < len(lines):
            fence_lines.append(lines[j])
            end += _line_len(lines[j])
            if lines[j].strip() == "---" and j > 0:
                found_close = True
                j += 1
                break
            j += 1
        if found_close:
            blocks.append(AtomicBlock(
                BlockType.FRONTMATTER, fence_lines, offset, end,
                meta={"text": "\n".join(fence_lines)},
            ))
            offset = end
            i = j
            while i < len(lines) and not lines[i].strip():
                offset += _line_len(lines[i])
                i += 1
        else:
            i = 0

    while i < len(lines):
        line = lines[i]
        llen = _line_len(line)
        stripped = line.strip()

        if not stripped:
            blocks.append(AtomicBlock(
                BlockType.BLANK, [line], offset, offset + llen,
            ))
            offset += llen
            i += 1
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_char = stripped[0]
            lang = stripped.lstrip(fence_char).strip()
            code_lines = [line]
            end = offset + llen
            j = i + 1
            while j < len(lines):
                code_lines.append(lines[j])
                end += _line_len(lines[j])
                if lines[j].strip().startswith(fence_char * 3) and len(lines[j].strip()) >= 3:
                    j += 1
                    break
                j += 1
            blocks.append(AtomicBlock(
                BlockType.CODE_FENCE, code_lines, offset, end,
                meta={"lang": lang},
            ))
            offset = end
            i = j
            continue

        if _RE_MATH_OPEN.match(stripped):
            math_lines = [line]
            end = offset + llen
            j = i + 1
            while j < len(lines):
                math_lines.append(lines[j])
                end += _line_len(lines[j])
                if _RE_MATH_OPEN.match(lines[j].strip()):
                    j += 1
                    break
                j += 1
            blocks.append(AtomicBlock(
                BlockType.MATH_BLOCK, math_lines, offset, end,
                meta={"lang": "math"},
            ))
            offset = end
            i = j
            continue

        m = _RE_HEADER.match(stripped)
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            blocks.append(AtomicBlock(
                BlockType.HEADER, [line], offset, offset + llen,
                meta={"level": level, "text": text},
            ))
            offset += llen
            i += 1
            continue

        if _RE_HR.match(stripped) and not stripped.startswith("|"):
            blocks.append(AtomicBlock(
                BlockType.HR, [line], offset, offset + llen,
            ))
            offset += llen
            i += 1
            continue

        if _RE_TABLE_ROW.match(line):
            header_lines: list[str] = [line]
            end = offset + llen
            j = i + 1

            if j < len(lines) and (_RE_TABLE_SEP.match(lines[j].strip())
                                    or (_RE_TABLE_ROW.match(lines[j]) and "---" in lines[j])):
                header_lines.append(lines[j])
                end += _line_len(lines[j])
                j += 1

            blocks.append(AtomicBlock(
                BlockType.TABLE, header_lines, offset, end,
                meta={"header_rows": list(header_lines)},
            ))
            offset = end

            while j < len(lines) and _RE_TABLE_ROW.match(lines[j]):
                row = lines[j]
                rlen = _line_len(row)
                blocks.append(AtomicBlock(
                    BlockType.TABLE_ROW, [row], offset, offset + rlen,
                    meta={"header_rows": list(header_lines)},
                ))
                offset += rlen
                j += 1
            i = j
            continue

        if _RE_BLOCKQUOTE.match(line):
            bq_lines = [line]
            end = offset + llen
            j = i + 1
            while j < len(lines) and (lines[j].strip().startswith(">")
                                       or (lines[j].strip()
                                           and not lines[j].strip().startswith("#")
                                           and not lines[j].strip().startswith("```")
                                           and not lines[j].strip().startswith("---")
                                           and not _RE_TABLE_ROW.match(lines[j])
                                           and not _RE_LIST_ITEM.match(lines[j]))):
                if lines[j].strip().startswith(">"):
                    bq_lines.append(lines[j])
                    end += _line_len(lines[j])
                    j += 1
                    continue
                elif not lines[j].strip():
                    break
                else:
                    break
            blocks.append(AtomicBlock(
                BlockType.BLOCKQUOTE, bq_lines, offset, end,
            ))
            offset = end
            i = j
            continue

        if _RE_LIST_ITEM.match(line):
            list_lines = [line]
            end = offset + llen
            ordered = re.match(r"^\s*\d+[.)]", stripped) is not None
            j = i + 1
            while j < len(lines):
                nl = lines[j]
                if _RE_LIST_ITEM.match(nl):
                    list_lines.append(nl)
                    end += _line_len(nl)
                    j += 1
                    continue
                if nl and (nl[0] in (" ", "\t") or nl.startswith("  ")):
                    list_lines.append(nl)
                    end += _line_len(nl)
                    j += 1
                    continue
                if not nl.strip():
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines) and (_RE_LIST_ITEM.match(lines[k])
                                            or (lines[k].startswith("  ") or lines[k].startswith("\t"))):
                        list_lines.append(nl)
                        end += _line_len(nl)
                        j += 1
                        continue
                    break
                break
            blocks.append(AtomicBlock(
                BlockType.LIST, list_lines, offset, end,
                meta={"ordered": ordered},
            ))
            offset = end
            i = j
            continue

        para_lines = [line]
        end = offset + llen
        j = i + 1
        while j < len(lines) and lines[j].strip():
            nl = lines[j]
            if (_RE_HEADER.match(nl.strip())
                or nl.strip().startswith("```")
                or nl.strip().startswith("~~~")
                or _RE_TABLE_ROW.match(nl)
                or _RE_LIST_ITEM.match(nl)
                or _RE_BLOCKQUOTE.match(nl)
                or _RE_HR.match(nl.strip())
                or _RE_MATH_OPEN.match(nl.strip())):
                break
            para_lines.append(nl)
            end += _line_len(nl)
            j += 1
        blocks.append(AtomicBlock(
            BlockType.PARAGRAPH, para_lines, offset, end,
        ))
        offset = end
        i = j

    if blocks and content and not content.endswith("\n"):
        blocks[-1] = AtomicBlock(
            blocks[-1].block_type,
            blocks[-1].lines,
            blocks[-1].char_start,
            len(content),
            blocks[-1].meta,
        )

    return blocks


__all__ = ["_parse_atomic_blocks", "_block_text", "_RE_SENTENCE"]
