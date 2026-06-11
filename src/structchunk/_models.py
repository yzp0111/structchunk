"""Data structures used throughout structchunk.

Public re-exports live in :mod:`structchunk`.  All names defined here are
considered implementation details except those listed in ``__all__``.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto


# ---------------------------------------------------------------------------
# Snowflake-like ID generation
# ---------------------------------------------------------------------------
#
# Why Snowflake and not UUID4:
#   * **8 bytes** in storage (vs 16 for UUID4) — half the row size, half
#     the B-tree fan-out, double the rows-per-page.
#   * **Sortable** by creation time (monotonically increasing) — lets
#     time-range queries use clustered B-tree range scans instead of a
#     full index sweep.
#   * **Index locality** — chunks created together live in nearby pages,
#     so a write-heavy workload gets sustained insert throughput without
#     the random-page-write storm that UUID4 primary keys cause.
#   * **Unique** — 41 bits timestamp (~70 years from epoch) + 10 bits
#     node (1024 machines) + 12 bits sequence (4096/ms/machine) gives
#     ~2^63 IDs before any structural collision is possible. The
#     non-structural birthday bound is 2^32 — collisions are
#     essentially impossible at any realistic workload.
#
# Layout (64 bits, MSB first):
#
#   0                   1                   2                   3
#   0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
#  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#  |0|                  timestamp (ms)             |   node  | seq  |
#  +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
#   1                  41                              10        12
#
_EPOCH_MS = 1735689600000  # 2026-01-01 00:00:00 UTC
_NODE_BITS = 10
_SEQUENCE_BITS = 12
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1  # 4095
_MAX_NODE = (1 << _NODE_BITS) - 1  # 1023


def _default_node_id() -> int:
    """Derive a stable per-machine node id from the hostname.

    No configuration needed: a multi-process / multi-host setup will
    naturally get different node ids (within the 1024-machine limit),
    so the timestamp+node+sequence decomposition still gives unique
    IDs even when many chunks are created in the same millisecond
    across different processes.
    """
    hostname = os.uname().nodename.encode("utf-8")
    return int(hashlib.md5(hostname).hexdigest()[:4], 16) & _MAX_NODE


class _SnowflakeGenerator:
    """Thread-safe Snowflake-like 64-bit ID generator.

    Single shared instance is enough for the whole process — the lock
    guarantees that two threads calling :meth:`next_id` in the same
    millisecond get different sequence numbers.
    """

    __slots__ = ("node_id", "sequence", "last_ms", "_lock")

    def __init__(self, node_id: int | None = None) -> None:
        self.node_id = node_id if node_id is not None else _default_node_id()
        self.sequence = 0
        self.last_ms = 0
        self._lock = threading.Lock()

    def next_id(self) -> int:
        """Return the next 64-bit Snowflake id as a non-negative int."""
        with self._lock:
            now = int(time.time() * 1000)
            if now == self.last_ms:
                self.sequence = (self.sequence +1) & _MAX_SEQUENCE
                if self.sequence ==0:
                    # Sequence exhausted within this millisecond — spin
                    # until the clock advances. In practice the next ms
                    # arrives within microseconds.
                    while int(time.time() *1000) <= self.last_ms:
                        pass
                    now = int(time.time() *1000)
            elif now < self.last_ms:
                # Clock went backwards (NTP step, suspend/resume). Spin-wait
                # up to10ms for the clock to catch up; if it does not, raise
                # rather than emit an id that collides with a previously-issued one.
                spin_deadline = time.time() +0.010
                caught_up = False
                while time.time() < spin_deadline:
                    now_check = int(time.time() *1000)
                    if now_check > self.last_ms:
                        now = now_check
                        self.sequence = (self.sequence +1) & _MAX_SEQUENCE
                        if self.sequence ==0:
                            self.sequence =1
                        caught_up = True
                        break
                    time.sleep(0.0001)
                if not caught_up:
                    raise RuntimeError(
                        "Snowflake clock not advancing within10ms; check NTP"
                    )
            else:
                self.sequence =0
            self.last_ms = now
            timestamp = now - _EPOCH_MS
            return (timestamp << (_NODE_BITS + _SEQUENCE_BITS)) | (
                self.node_id << _SEQUENCE_BITS
            ) | self.sequence

    def id_timestamp_ms(self, chunk_id_int: int) -> int:
        """Extract the embedded millisecond timestamp from a generated id.

        Useful for debugging or for ordering the few chunks that happen
        to be created on the same machine in the same millisecond by
        sequence (which the int ordering already preserves).
        """
        timestamp_bits = 64 - _NODE_BITS - _SEQUENCE_BITS
        return (chunk_id_int >> _SEQUENCE_BITS >> _NODE_BITS) + _EPOCH_MS


_snowflake = _SnowflakeGenerator()


# Fork-safety: a forked child would inherit the parent's ``last_ms`` /
# ``sequence`` / ``node_id`` and could emit colliding ids. Re-instantiate
# in each child so its state starts fresh. ``os.register_at_fork`` is
# POSIX-only; Windows has no fork so the module-level singleton is fine.
if hasattr(os, "register_at_fork"):

    def _reset_snowflake_in_child() -> None:
        global _snowflake
        _snowflake = _SnowflakeGenerator()

    os.register_at_fork(after_in_child=_reset_snowflake_in_child)


def _new_chunk_id() -> int:
    """Return a sortable, compact, unique chunk identifier as a 64-bit int.

    The canonical form is a Python ``int`` — exactly what a SQL ``BIGINT``
    column holds. For display or JSON, ``str(chunk_id)`` gives the
    standard decimal representation (e.g. ``"188704004562132992"``)
    which round-trips with ``int(s)`` and is the format used by
    Twitter, Discord, Instagram, and every other Snowflake user.

    Why int, not string:
        * PostgreSQL ``BIGINT`` is 8 bytes; ``VARCHAR(16)`` is 16+1 = 17
          bytes — 2.1x larger index entries, 2x more index pages, ~26%
          larger heap tuples.
        * ``btint8cmp`` is two register compares (7 lines of C); the
          string comparator is collation-bound and dominates BTree CPU
          time in profiled workloads.
        * Industry standard: Twitter, Mastodon, Instagram, Discord,
          Snowflake (the database) all store Snowflake ids as ``bigint``.
    """
    return _snowflake.next_id()


def _parse_chunk_id_str(value: str) -> int:
    """Parse a chunk id from a string. Accepts decimal (preferred)
    or hex (fallback, for backward compatibility). Returns 0 for
    non-numeric input.
    """
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return int(value, 16)
    except ValueError:
        return 0


def chunk_id_timestamp_ms(chunk_id: int | str) -> int:
    """Recover the millisecond timestamp embedded in a chunk id.

    Accepts the raw int (canonical) or a string in either decimal
    (preferred — what ``str(int_chunk_id)`` produces) or hex
    (for legacy callers). Returns 0 for non-Snowflake inputs.
    """
    if isinstance(chunk_id, int):
        value = chunk_id
    elif isinstance(chunk_id, str):
        value = _parse_chunk_id_str(chunk_id)
    else:
        return 0
    if value <= 0:
        return 0
    extracted = (value >> _SEQUENCE_BITS >> _NODE_BITS) + _EPOCH_MS
    if extracted < _EPOCH_MS or extracted > int(time.time() * 1000) + 60_000:
        return 0
    return extracted


def _last_sentence(text: str) -> str:
    """Extract the last complete sentence from ``text``.

    A sentence ends at '.', '!', '?', '。', '！', '？' followed by either
    another terminator, whitespace, newline, or end-of-string.

    Returns the substring up to and including the last terminator.
    If no terminator is found, returns the stripped text (treating the
    whole block as one "sentence" — common for headings/labels).

    Examples:
        >>> _last_sentence("Hello world.")
        'Hello world.'
        >>> _last_sentence("First sentence. Second one.")
        'First sentence. Second one.'
        >>> _last_sentence("重要提示：以下是性能数据。另一句。")
        '重要提示：以下是性能数据。另一句。'
        >>> _last_sentence("no terminator here")
        'no terminator here'
    """
    terminators = ".!?。！？"
    last_idx = -1
    for i, ch in enumerate(text):
        if ch in terminators:
            last_idx = i
    if last_idx == -1:
        return text.strip()
    return text[: last_idx + 1].strip()


class BlockType(Enum):
    """Type of an atomic markdown block."""

    FRONTMATTER = auto()
    HEADER = auto()
    CODE_FENCE = auto()
    TABLE = auto()
    TABLE_ROW = auto()
    LIST = auto()
    BLOCKQUOTE = auto()
    MATH_BLOCK = auto()
    HR = auto()
    PARAGRAPH = auto()
    BLANK = auto()


@dataclass
class AtomicBlock:
    """An unsplittable unit of markdown content.

    ``meta`` carries type-specific extras (level for headers, lang for code,
    header_rows for tables, ordered for lists, etc.).
    """

    block_type: BlockType
    lines: list[str]
    char_start: int
    char_end: int
    meta: dict = field(default_factory=dict)


@dataclass
class HeaderInfo:
    """A header entry in the breadcrumb stack."""

    level: int
    text: str


@dataclass
class ChunkMetadata:
    """All metadata fields attached to a :class:`MarkdownChunk`.

    Identifier fields (chunk_id / prev_chunk_id / next_chunk_id) are
    raw 64-bit Snowflake ints — exactly what a SQL ``BIGINT`` column
    stores. Use :attr:`MarkdownChunk.chunk_id_hex` for the 16-char
    hex string representation (JSON, logs, debugging). Use 0 as the
    sentinel for "no predecessor / no successor".
    """

    chunk_id: int
    chunk_index: int
    total_chunks: int
    char_offset_start: int
    char_offset_end: int
    # header_breadcrumb entries include the markdown-level prefix,
    # e.g. ['# H1', '## H2', '### H3'].
    header_breadcrumb: list[str]
    header_path: list[HeaderInfo] = field(default_factory=list)
    has_more: bool = False
    source_meta: dict = field(default_factory=dict)

    # RAG completeness fields (small-to-big retrieval pattern).
    # doc_id identifies the source document — all chunks from the same
    # document share the same doc_id. Auto-derived from the file path
    # (when using chunk_file) or from a content hash (when using chunk).
    doc_id: str = ""
    prev_chunk_id: int = 0
    next_chunk_id: int = 0
    source_element_type: str = ""
    source_element_position: str = ""
    continuation: bool = False

    # Pre-computed char counts. Storing these lets DB queries filter and
    # aggregate on length without loading the full content (columnar
    # projection), and lets the user inspect chunk sizes in one read.
    # Set automatically by MarkdownChunk.__post_init__ from len(content).
    content_length: int = 0
    breadcrumb_length: int = 0
    total_length: int = 0

    # Section-complete invariant (hierarchical algorithm only).
    # True means the entire section lives in this chunk (whole section
    # was emitted as a single chunk); False means this is a tail/residual
    # of a section that was split across multiple chunks. Downstream
    # passes (e.g. ``merge_tiny``) must not merge a non-section-complete
    # chunk into a different section's head, since that would mix two
    # distinct sections into a single breadcrumb-bearing chunk.
    # Defaults to True so the linear algorithm (which has no section
    # concept) and externally-constructed chunks behave permissively.
    is_section_complete: bool = True


@dataclass
class MarkdownChunk:
    """A single chunk: content plus rich metadata."""

    content: str
    metadata: ChunkMetadata

    def __post_init__(self) -> None:
        """Auto-fill length fields if caller left them at 0.

        Users can override by passing an explicit value (e.g. when
        serialising a chunk that was loaded back from storage with
        pre-computed lengths).
        """
        md = self.metadata
        if md.content_length == 0:
            md.content_length = len(self.content)
        if md.breadcrumb_length == 0 and md.header_breadcrumb:
            md.breadcrumb_length = sum(len(h) for h in md.header_breadcrumb)
        if md.total_length == 0:
            md.total_length = md.content_length

    @property
    def chunk_id_hex(self) -> str:
        """Return the chunk_id as a 16-char lowercase hex string.

        Use this for JSON output, log lines, and any context where a
        human-readable string is more useful than a raw 19-digit
        decimal int. For database storage, use the raw int
        (``self.metadata.chunk_id``) directly in a ``BIGINT`` column.
        """
        return f"{self.metadata.chunk_id:016x}"

    @property
    def chunk_id_str(self) -> str:
        """Return the chunk_id as a decimal string (matches ``str(int)``).

        This is the format Twitter, Discord, Instagram and every other
        Snowflake user emits in their JSON APIs. Round-trips with
        ``int(s)`` for direct database insertion.
        """
        return str(self.metadata.chunk_id)

    def expand(
        self,
        include_breadcrumb: bool = True,
    ) -> str:
        """Return the chunk content expanded with breadcrumb context.

        This implements the "small-to-big" retrieval pattern: embed the
        compact ``.content`` for vector similarity, but feed the expanded
        version to the LLM for richer context.
        """
        parts: list[str] = []
        if include_breadcrumb and self.metadata.header_breadcrumb:
            parts.append(" > ".join(self.metadata.header_breadcrumb))
        parts.append(self.content)
        return "\n\n".join(parts)

    def recompute_lengths(self) -> None:
        """Re-derive all length fields from the current field values.

        Use after any post-creation mutation that changes the
        content/breadcrumb fields, since :meth:`__post_init__` only
        runs at construction time.
        """
        md = self.metadata
        md.content_length = len(self.content)
        md.breadcrumb_length = sum(len(h) for h in md.header_breadcrumb)
        md.total_length = md.content_length

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict.

        Identifier fields are emitted as decimal strings — the same
        format Twitter, Discord and Instagram use for Snowflake ids.
        Round-trip with ``int(s)`` for direct database insertion
        (``BIGINT`` column). The raw int is on
        ``self.metadata.chunk_id`` for code that wants to skip the
        string conversion.
        """
        md = self.metadata
        return {
            "content": self.content,
            "metadata": {
                "chunk_id": str(md.chunk_id),
                "chunk_index": md.chunk_index,
                "total_chunks": md.total_chunks,
                "char_offset_start": md.char_offset_start,
                "char_offset_end": md.char_offset_end,
                "header_breadcrumb": md.header_breadcrumb,
                "has_more": md.has_more,
                "doc_id": md.doc_id,
                "prev_chunk_id": str(md.prev_chunk_id) if md.prev_chunk_id else "",
                "next_chunk_id": str(md.next_chunk_id) if md.next_chunk_id else "",
                "source_element_type": md.source_element_type,
                "source_element_position": md.source_element_position,
                "continuation": md.continuation,
                "content_length": md.content_length,
                "breadcrumb_length": md.breadcrumb_length,
                "total_length": md.total_length,
            },
        }


__all__ = [
    "BlockType",
    "AtomicBlock",
    "HeaderInfo",
    "ChunkMetadata",
    "MarkdownChunk",
]
