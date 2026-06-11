"""structchunk — production-quality markdown chunking for RAG.

Two algorithms are provided:

* ``linear`` — greedy block-by-block. Fast, fine-grained, lower-level
  control over where splits happen.
* ``hierarchical`` — document-tree based on the header hierarchy. Each
  chunk clearly belongs to a section. Headers always lead their content.

Quick start
-----------

>>> import structchunk
>>> chunks = structchunk.chunk("# Hello\\n\\nWorld.", algorithm="linear", max_chars=500)
>>> chunks[0].content
'# Hello\\n\\nWorld.'
>>> chunks[0].metadata.header_breadcrumb
['Hello']
"""

from __future__ import annotations

from ._models import (
    AtomicBlock,
    BlockType,
    ChunkMetadata,
    HeaderInfo,
    MarkdownChunk,
    chunk_id_timestamp_ms,
)
from ._version import __version__
from .hierarchical import chunk_hierarchical
from .linear import chunk_linear

__all__ = [
    "__version__",
    "chunk",
    "chunk_file",
    "chunk_to_dicts",
    "chunk_linear",
    "chunk_hierarchical",
    "MarkdownChunk",
    "ChunkMetadata",
    "BlockType",
    "AtomicBlock",
    "HeaderInfo",
    "chunk_id_timestamp_ms",
]


def chunk(
    content: str,
    *,
    algorithm: str = "hierarchical",
    max_chars: int | None = None,
    forward_intro_text: bool = True,
    **kwargs,
) -> list[MarkdownChunk]:
    """Chunk markdown content for RAG.

    Parameters
    ----------
    content : str
        The raw markdown text to chunk.
    algorithm : {"linear", "hierarchical"}, default "hierarchical"
        - ``"linear"``: greedy block-by-block chunking.
        - ``"hierarchical"``: document-tree based, semantically coherent.
    max_chars : int, optional
        Convenience cap (e.g. 500 for Dify). If set, every chunk is
        guaranteed to be at most ``max_chars`` characters. Sets both
        ``max_chunk_size`` (80%) and ``hard_max_size`` (100%).
    **kwargs
        Forwarded to the algorithm's chunk function. See
        :func:`chunk_linear` and :func:`chunk_hierarchical` for the
        full list of options.

    Returns
    -------
    list[MarkdownChunk]
    """
    if algorithm not in ("linear", "hierarchical"):
        raise ValueError(
            f"Unknown algorithm: {algorithm!r}. Must be 'linear' or 'hierarchical'."
        )
    if max_chars is not None and max_chars < 1:
        raise ValueError(
            f"max_chars must be a positive integer, got {max_chars!r}."
        )

    if "doc_id" not in kwargs or not kwargs["doc_id"]:
        import hashlib
        kwargs["doc_id"] = hashlib.sha256(
            content.encode("utf-8")
        ).hexdigest()[:16]

    if algorithm == "hierarchical":
        return chunk_hierarchical(
            content,
            max_chars=max_chars,
            forward_intro_text=forward_intro_text,
            **kwargs,
        )
    if algorithm != "linear":
        raise ValueError(
            f"Unknown algorithm: {algorithm!r}. Use 'linear' or 'hierarchical'."
        )
    return chunk_linear(
        content,
        max_chars=max_chars,
        forward_intro_text=forward_intro_text,
        **kwargs,
    )


def chunk_file(
    path: str,
    *,
    algorithm: str = "hierarchical",
    forward_intro_text: bool = True,
    **kwargs,
) -> list[MarkdownChunk]:
    """Read a markdown file and chunk it.

    The file's absolute path is used as ``doc_id`` unless the caller
    provides one explicitly.
    """
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if "doc_id" not in kwargs or not kwargs["doc_id"]:
        from pathlib import Path
        kwargs["doc_id"] = str(Path(path).resolve())
    return chunk(
        content,
        algorithm=algorithm,
        forward_intro_text=forward_intro_text,
        **kwargs,
    )


def chunk_to_dicts(chunks: list[MarkdownChunk]) -> list[dict]:
    """Serialize a chunk list to JSON-friendly dicts."""
    return [c.to_dict() for c in chunks]
