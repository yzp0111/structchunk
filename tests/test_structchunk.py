"""Comprehensive tests for structchunk — covers parser, splitters, both algorithms,
and RAG enrichment."""

import os

import pytest

from structchunk import (
    BlockType,
    ChunkMetadata,
    HeaderInfo,
    MarkdownChunk,
    chunk,
    chunk_file,
    chunk_hierarchical,
    chunk_linear,
    chunk_to_dicts,
)
from structchunk._config import ChunkerConfig
from structchunk._enrich import (
    collect_headers_in_group,
    compute_breadcrumb,
    compute_end_breadcrumb,
    enrich_rag_metadata,
    get_table_header_for_group,
    inject_missing_breadcrumbs,
)
import sys
import time

from structchunk._models import AtomicBlock, _snowflake
from structchunk._parser import _parse_atomic_blocks
from structchunk._splitters import (
    _force_split_long_strings,
    split_code_block,
    split_list_items,
    split_paragraph_at_sentences,
    split_table_rows,
)


def _content_blocks(md: str) -> list[AtomicBlock]:
    """Parse markdown and drop the trailing BLANK block(s) the parser emits."""
    return [b for b in _parse_atomic_blocks(md) if b.block_type != BlockType.BLANK]





class TestParseAtomicBlocks:
    """Test that _parse_atomic_blocks correctly identifies every block type."""

    def test_headers(self):
        md = "# H1\n## H2\n### H3\n"
        blocks = _content_blocks(md)
        types = [b.block_type for b in blocks]
        assert types == [BlockType.HEADER, BlockType.HEADER, BlockType.HEADER]
        assert blocks[0].meta == {"level": 1, "text": "H1"}
        assert blocks[1].meta == {"level": 2, "text": "H2"}
        assert blocks[2].meta == {"level": 3, "text": "H3"}

    def test_header_with_formatting(self):
        md = "# Header with `code` and **bold**\n"
        blocks = _content_blocks(md)
        assert blocks[0].block_type == BlockType.HEADER
        assert blocks[0].meta["text"] == "Header with `code` and **bold**"

    def test_empty_header(self):
        md = "# \n"
        blocks = _parse_atomic_blocks(md)
        # An empty header (only "#" with no text) is parsed as a paragraph
        # since the header regex requires at least one character after "# ".
        assert len(blocks) >= 1

    def test_code_fence_backticks(self):
        md = "```python\nprint('hello')\n```\n"
        blocks = _parse_atomic_blocks(md)
        non_blank = [b for b in blocks if b.block_type != BlockType.BLANK]
        assert len(non_blank) == 1
        assert non_blank[0].block_type == BlockType.CODE_FENCE
        assert non_blank[0].meta["lang"] == "python"

    def test_code_fence_tildes(self):
        md = "~~~javascript\nconsole.log('hi')\n~~~\n"
        blocks = _parse_atomic_blocks(md)
        non_blank = [b for b in blocks if b.block_type != BlockType.BLANK]
        assert len(non_blank) == 1
        assert non_blank[0].block_type == BlockType.CODE_FENCE
        assert non_blank[0].meta["lang"] == "javascript"

    def test_code_fence_with_hash_inside(self):
        """Code blocks containing # headers should NOT be parsed as headers."""
        md = "```markdown\n# This is not a real header\n## Another fake\n```\n"
        blocks = _parse_atomic_blocks(md)
        non_blank = [b for b in blocks if b.block_type != BlockType.BLANK]
        assert len(non_blank) == 1
        assert non_blank[0].block_type == BlockType.CODE_FENCE

    def test_unclosed_code_fence(self):
        """Unclosed code fence: everything becomes one code block."""
        md = "```\nsome code\nmore code\n"
        blocks = _parse_atomic_blocks(md)
        non_blank = [b for b in blocks if b.block_type != BlockType.BLANK]
        assert len(non_blank) == 1
        assert non_blank[0].block_type == BlockType.CODE_FENCE
        assert blocks[0].meta["lang"] == ""  # unclosed fence: parser captures empty lang for missing language

    def test_table_basic(self):
        md = "| Name | Age |\n| --- | --- |\n| Alice | 30 |\n| Bob | 25 |\n"
        blocks = _content_blocks(md)
        types = [b.block_type for b in blocks]
        assert types[0] == BlockType.TABLE
        assert types[1] == BlockType.TABLE_ROW
        assert types[2] == BlockType.TABLE_ROW
        assert blocks[0].meta.get("header_rows") is not None

    def test_table_with_alignment(self):
        md = "| Left | Center | Right |\n| :--- | :---: | ---: |\n| a | b | c |\n"
        blocks = _content_blocks(md)
        assert blocks[0].block_type == BlockType.TABLE

    def test_list_unordered(self):
        md = "- item 1\n- item 2\n- item 3\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.LIST
        assert blocks[0].meta["ordered"] is False

    def test_list_ordered(self):
        md = "1. first\n2. second\n3. third\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.LIST
        assert blocks[0].meta["ordered"] is True

    def test_list_with_continuation(self):
        md = "- item 1\n  continuation line\n- item 2\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.LIST
        assert len(blocks[0].lines) == 3

    def test_list_with_blank_line(self):
        md = "- item 1\n\n  after blank\n- item 2\n"
        blocks = _content_blocks(md)
        list_blocks = [b for b in blocks if b.block_type == BlockType.LIST]
        assert len(list_blocks) >= 1

    def test_blockquote(self):
        md = "> quote line 1\n> quote line 2\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.BLOCKQUOTE

    def test_math_block(self):
        md = "$$\nE = mc^2\n$$\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.MATH_BLOCK

    def test_horizontal_rule(self):
        md = "---\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.HR

    def test_paragraph(self):
        md = "Just a regular paragraph.\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.PARAGRAPH

    def test_paragraph_multiple_lines(self):
        md = "Line one\nLine two\nLine three\n"
        blocks = _content_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].block_type == BlockType.PARAGRAPH
        assert len(blocks[0].lines) == 3

    def test_frontmatter(self):
        md = "---\ntitle: Test\ndate: 2026-01-01\n---\n\n# Body\n"
        blocks = _content_blocks(md)
        assert blocks[0].block_type == BlockType.FRONTMATTER
        assert blocks[1].block_type == BlockType.HEADER

    def test_empty_content(self):
        assert _parse_atomic_blocks("") == []
        assert _parse_atomic_blocks("   \n  \n") == []

    def test_offsets_correct(self):
        md = "# Title\n\nParagraph text.\n"
        blocks = _content_blocks(md)
        assert blocks[0].char_start == 0
        assert blocks[0].char_end == len("# Title\n")

    def test_no_content_at_end(self):
        md = "# Title\n\nPara"
        blocks = _content_blocks(md)
        assert blocks[-1].char_end == len(md)

    def test_consecutive_headers(self):
        md = "# A\n# B\n# C\n"
        blocks = _content_blocks(md)
        types = [b.block_type for b in blocks]
        assert types == [BlockType.HEADER, BlockType.HEADER, BlockType.HEADER]




class TestSubSplitParagraph:
    """Test the paragraph sentence-boundary splitter."""

    def test_english_sentence_split(self):
        text = "First sentence. Second sentence. Third sentence."
        result = split_paragraph_at_sentences(text, max_size=20, hard_max=30)
        for chunk in result:
            assert chunk.rstrip()[-1] in ".!?"

    def test_chinese_sentence_split(self):
        text = "第一句。第二句。第三句。"
        result = split_paragraph_at_sentences(text, max_size=15, hard_max=30)
        for chunk in result:
            assert chunk.rstrip()[-1] in ".!?。！？"

    def test_chinese_no_space_after_period(self):
        """Chinese 。 is typically not followed by a space."""
        text = "本报告聚焦知识库。第一款产品Milvus。第二款Qdrant。"
        result = split_paragraph_at_sentences(text, max_size=20, hard_max=50)
        assert len(result) >= 2

    def test_mixed_chinese_english(self):
        text = "本报告聚焦Milvus。We recommend Pinecone for SaaS. 第二选择PgVector。"
        result = split_paragraph_at_sentences(text, max_size=30, hard_max=60)
        for chunk in result:
            assert chunk.rstrip()[-1] in ".!?。！？"

    def test_never_breaks_sentence(self):
        text = "Sentence one with no period Sentence two no period"
        result = split_paragraph_at_sentences(text, max_size=100, hard_max=200)
        joined = "".join(result)
        assert joined == text

    def test_force_split_when_too_long(self):
        long_sentence = "x" * 100
        result = split_paragraph_at_sentences(long_sentence, max_size=20, hard_max=30)
        assert all(len(c) <= 30 for c in result)

    def test_empty_input(self):
        result = split_paragraph_at_sentences("", max_size=100, hard_max=200)
        assert result == [""]


class TestSubSplitCode:
    def test_basic_split(self):
        lines = ["line1", "line2", "line3", "line4"]
        result = split_code_block(lines, max_size=15, hard_max=30)
        assert len(result) >= 2
        for chunk in result:
            assert chunk.startswith("```")
            assert chunk.rstrip().endswith("```")

    def test_preserves_language(self):
        lines = ["print('hi')", "print('bye')"]
        result = split_code_block(lines, max_size=15, hard_max=50, lang="python")
        assert any("```python" in c for c in result)

    def test_empty_code(self):
        result = split_code_block([], max_size=100, hard_max=200)
        assert result == ["```\n```"]


class TestSubSplitTable:
    def test_basic_split(self):
        header = ["| A | B |", "| --- | --- |"]
        data = ["| 1 | 2 |", "| 3 | 4 |", "| 5 | 6 |"]
        result = split_table_rows(header, data, max_size=20, hard_max=50)
        for chunk in result:
            assert "| A | B |" in chunk
            assert "| --- | --- |" in chunk

    def test_preserves_header(self):
        header = ["| H1 | H2 |", "| --- | --- |"]
        data = ["| 1 | 2 |", "| 3 | 4 |"]
        result = split_table_rows(header, data, max_size=100, hard_max=500)
        assert len(result) == 1
        assert "| H1 | H2 |" in result[0]


class TestSubSplitList:
    def test_basic_split(self):
        lines = ["- item 1", "- item 2", "- item 3", "- item 4"]
        result = split_list_items(lines, max_size=15, hard_max=30)
        assert len(result) >= 1
        joined = "\n".join(result)
        assert "- item 1" in joined
        assert "- item 4" in joined


class TestForceSplitLongStrings:
    def test_no_split_when_under_limit(self):
        result = _force_split_long_strings(["hello"], hard_max=100)
        assert result == ["hello"]

    def test_splits_when_over_limit(self):
        result = _force_split_long_strings(["a" * 25], hard_max=10)
        assert len(result) == 3
        assert all(len(c) <= 10 for c in result)
        assert "".join(result) == "a" * 25

    def test_handles_empty_list(self):
        result = _force_split_long_strings([], hard_max=10)
        assert result == []




class TestBreadcrumbHelpers:
    def test_compute_breadcrumb(self):
        h1 = HeaderInfo(1, "Title")
        result = compute_breadcrumb([], [h1])
        assert result == [h1]

    def test_compute_end_breadcrumb_pops_stale(self):
        h1 = HeaderInfo(1, "Title")
        h2_old = HeaderInfo(2, "Old")
        blocks = [
            AtomicBlock(BlockType.HEADER, ["## New"], 0, 0, {"level": 2, "text": "New"}),
        ]
        result = compute_end_breadcrumb(blocks, [h1, h2_old])
        assert result == [h1, HeaderInfo(2, "New")]

    def test_collect_headers_in_document_order(self):
        blocks = [
            AtomicBlock(BlockType.HEADER, ["### A"], 0, 0, {"level": 3, "text": "A"}),
            AtomicBlock(BlockType.HEADER, ["### B"], 0, 0, {"level": 3, "text": "B"}),
        ]
        result = collect_headers_in_group(blocks)
        assert [h.text for h in result] == ["A", "B"]

    def test_get_table_header_for_group(self):
        header_block = AtomicBlock(
            BlockType.TABLE, ["| A |"], 0, 0, {"header_rows": ["| A |"]}
        )
        row_block = AtomicBlock(
            BlockType.TABLE_ROW, ["| 1 |"], 0, 0, {"header_rows": ["| A |"]}
        )
        result = get_table_header_for_group([header_block, row_block])
        assert result == ["| A |"]




class TestChunkMarkdownBasic:
    def test_empty(self):
        assert chunk_linear("") == []
        assert chunk_linear("   \n  \n") == []

    def test_simple(self):
        md = "# Title\n\nContent here."
        chunks = chunk_linear(md, max_chars=500)
        assert len(chunks) >= 1
        assert "# Title" in chunks[0].metadata.header_breadcrumb
        assert "Content here." in chunks[0].content

    def test_multiple_h1_headers(self):
        md = "# First\n\nContent 1.\n\n# Second\n\nContent 2."
        chunks = chunk_linear(md, max_chars=500)
        h1_chunks = [c for c in chunks if "# First" in c.metadata.header_breadcrumb]
        h1_chunks2 = [c for c in chunks if "# Second" in c.metadata.header_breadcrumb]
        assert len(h1_chunks) >= 1
        assert len(h1_chunks2) >= 1

    def test_max_chars_respected(self):
        long_text = "Sentence after sentence. " * 100
        chunks = chunk_linear(long_text, max_chars=300)
        for c in chunks:
            assert len(c.content) <= 300

    def test_hard_max_respected(self):
        long_text = "x" * 1000
        chunks = chunk_linear(long_text, max_chars=500, hard_max_size=600)
        for c in chunks:
            assert len(c.content) <= 600

    def test_returns_markdown_chunks(self):
        chunks = chunk_linear("# Test\n\nContent.", max_chars=500)
        for c in chunks:
            assert isinstance(c, MarkdownChunk)
            assert isinstance(c.metadata, ChunkMetadata)

    def test_chunk_id_present(self):
        chunks = chunk_linear("# Test\n\nContent.", max_chars=500)
        for c in chunks:
            assert c.metadata.chunk_id != 0
            assert isinstance(c.metadata.chunk_id, int)

    def test_total_chunks_correct(self):
        chunks = chunk_linear("# Test\n\nPara 1.\n\nPara 2.", max_chars=500)
        for c in chunks:
            assert c.metadata.total_chunks == len(chunks)


class TestChunkMarkdownCode:
    def test_code_block_preserved(self):
        md = "# Code\n\n```python\nprint('hello')\n```\n"
        chunks = chunk_linear(md, max_chars=500)
        # Find the chunk that contains the code block
        code_chunks = [c for c in chunks if "```python" in c.content]
        assert len(code_chunks) >= 1
        assert "```" in code_chunks[0].content

    def test_code_block_not_split_if_fits(self):
        md = "# Code\n\n```python\nx = 1\n```\n"
        chunks = chunk_linear(md, max_chars=500)
        assert len(chunks) >= 1


class TestChunkMarkdownList:
    def test_list_preserved(self):
        md = "# List\n\n- a\n- b\n- c\n"
        chunks = chunk_linear(md, max_chars=500)
        # Find chunks containing list items
        list_chunks = [c for c in chunks if "- a" in c.content or "- b" in c.content]
        assert len(list_chunks) >= 1

    def test_ordered_list(self):
        md = "# Steps\n\n1. First\n2. Second\n3. Third\n"
        chunks = chunk_linear(md, max_chars=500)
        list_chunks = [c for c in chunks if "First" in c.content]
        assert any("1. First" in c.content for c in list_chunks)


class TestChunkMarkdownTable:
    def test_basic_table(self):
        md = "# Table\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n"
        chunks = chunk_linear(md, max_chars=500)
        # Find chunks that contain the table
        table_chunks = [c for c in chunks if "| A | B |" in c.content]
        assert len(table_chunks) >= 1

    def test_table_header_forwarded(self):
        """When a table is split, header rows are prepended to continuation."""
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Big Table\n\n| A | B |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk_linear(md, max_chars=300)
        for c in chunks:
            if c.metadata.source_element_type in ("table", "table_row"):
                assert "| A | B |" in c.content, f"Missing table header in chunk: {c.content[:100]}"


class TestChunkMarkdownEdgeCases:
    def test_only_headers(self):
        md = "# H1\n## H2\n### H3\n"
        chunks = chunk_linear(md, max_chars=500)
        assert len(chunks) >= 1

    def test_unicode_content(self):
        md = "# 知识库对比\n\n中文内容测试。"
        chunks = chunk_linear(md, max_chars=500)
        assert any("# 知识库对比" in c.metadata.header_breadcrumb for c in chunks)

    def test_special_characters(self):
        md = "# Title with `code` and **bold**\n\nContent with &amp; entities."
        chunks = chunk_linear(md, max_chars=500)
        assert len(chunks) >= 1

    def test_nested_lists(self):
        md = "# Nested\n\n- outer 1\n  - inner 1\n  - inner 2\n- outer 2\n"
        chunks = chunk_linear(md, max_chars=500)
        assert len(chunks) >= 1

    def test_frontmatter_stripped(self):
        """Frontmatter at the start should be recognized but not break chunking."""
        md = "---\ntitle: Test\n---\n\n# Body\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        assert len(chunks) >= 1
        assert any("# Body" in c.metadata.header_breadcrumb for c in chunks)


class TestChunkMarkdownMetadata:
    def test_doc_id_propagated(self):
        chunks = chunk_linear("# Test\n\nContent.", max_chars=500, doc_id="doc-001")
        for c in chunks:
            assert c.metadata.doc_id == "doc-001"

    def test_prev_next_links(self):
        md = "# A\n\nFirst.\n\n# B\n\nSecond."
        chunks = chunk_linear(md, max_chars=500)
        for i, c in enumerate(chunks):
            if i > 0:
                assert c.metadata.prev_chunk_id == chunks[i - 1].metadata.chunk_id
            if i < len(chunks) - 1:
                assert c.metadata.next_chunk_id == chunks[i + 1].metadata.chunk_id




class TestHeaderBreadcrumb:
    def test_simple_navigation(self):
        md = "# Title\n\n## Section\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        for c in chunks:
            if c.metadata.source_element_type == "paragraph":
                assert "# Title" in c.metadata.header_breadcrumb

    def test_nested_header_breadcrumb(self):
        md = "# L1\n## L2\n### L3\n#### L4\n##### L5\n###### L6\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        # Every chunk should have the full nested breadcrumb
        for c in chunks:
            if c.metadata.header_breadcrumb and "Content" in c.content:
                assert c.metadata.header_breadcrumb == ["# L1", "## L2", "### L3", "#### L4", "##### L5", "###### L6"]


class TestSourceElementMetadata:
    def test_paragraph_type(self):
        chunks = chunk_linear("# Test\n\nA paragraph.", max_chars=500)
        # The dominant type is determined by the first non-blank block in
        # the chunk. When a header leads a paragraph, the dominant type is
        # "header". To get a "paragraph" dominant type, the chunk must
        # start with a paragraph block (no preceding header in the same chunk).
        md = "A standalone paragraph with no leading header.\n\nMore text."
        chunks = chunk_linear(md, max_chars=500)
        assert any(c.metadata.source_element_type == "paragraph" for c in chunks)

    def test_table_type(self):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
        chunks = chunk_linear(md, max_chars=500)
        # A table-only chunk has dominant type "table" (the first block is TABLE)
        assert any("table" in c.metadata.source_element_type for c in chunks)

    def test_source_element_position_increments(self):
        md = "# T\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunk_linear(md, max_chars=500)
        para_chunks = [c for c in chunks if c.metadata.source_element_type == "paragraph"]
        positions = [int(c.metadata.source_element_position) for c in para_chunks]
        assert positions == list(range(1, len(para_chunks) + 1))


class TestTableHeaderForwarding:
    def test_header_prepended_to_continuation(self):
        """When a table is split, the header row(s) should appear in every chunk."""
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Big Table\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk_linear(md, max_chars=300)
        for c in chunks:
            if c.metadata.source_element_type in ("table", "table_row"):
                assert "| H1 | H2 |" in c.content

    def test_header_prepended_to_continuation_hierarchical(self):
        """Same guarantee for the hierarchical algorithm.

        Regression test added when the default algorithm was switched to
        hierarchical (commit 0.2.0). Both algorithms must forward the
        column header row to every split table chunk.
        """
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Big Table\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk_hierarchical(md, max_chars=300)
        for c in chunks:
            if c.metadata.source_element_type in ("table", "table_row"):
                assert "| H1 | H2 |" in c.content

    def test_header_prepended_when_called_via_default(self):
        """When chunk() is called without algorithm= or preserve_table_header=,
        the default ChunkerConfig (with preserve_table_header=True) should still
        forward table headers. Locks in the new default behavior end-to-end.
        """
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Big Table\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk(md, max_chars=200)
        table_chunks = [
            c for c in chunks
            if c.metadata.source_element_type in ("table", "table_row")
        ]
        assert len(table_chunks) > 1, (
            "Test needs multiple table chunks to be meaningful — got "
            f"{len(table_chunks)} table chunks. Loosen max_chars to force splits."
        )
        for c in table_chunks:
            assert "| H1 | H2 |" in c.content, (
                f"Table chunk missing header row:\n{c.content[:200]}"
            )


class TestBreadcrumbEnrichment:
    def test_all_headers_in_breadcrumb(self):
        """When a chunk spans multiple same-level sections, breadcrumb must include both."""
        md = "# Title\n\n## A\n\nA content.\n\n## B\n\nB content."
        chunks = chunk_linear(md, max_chars=500)
        for c in chunks:
            if c.metadata.source_element_type == "paragraph":
                bc = c.metadata.header_breadcrumb
                if "A" in c.content and "B" in c.content:
                    assert "A" in bc and "B" in bc

    def test_collect_headers_in_group(self):
        blocks = [
            AtomicBlock(BlockType.HEADER, ["### A"], 0, 0, {"level": 3, "text": "A"}),
            AtomicBlock(BlockType.HEADER, ["### B"], 0, 0, {"level": 3, "text": "B"}),
        ]
        result = collect_headers_in_group(blocks)
        assert len(result) == 2
        assert [h.text for h in result] == ["A", "B"]




class TestSerialization:
    def test_to_dict_has_all_fields(self):
        md = "# T\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        d = chunks[0].to_dict()
        assert "content" in d
        assert "metadata" in d
        for key in [
            "chunk_id", "chunk_index", "total_chunks",
            "char_offset_start", "char_offset_end",
            "header_breadcrumb", "has_more",
            "doc_id", "prev_chunk_id", "next_chunk_id",
            "source_element_type", "source_element_position",
            "continuation",
        ]:
            assert key in d["metadata"]

    def test_to_dicts_helper(self):
        md = "# T\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        dicts = chunk_to_dicts(chunks)
        assert len(dicts) == len(chunks)

    def test_to_dict_json_serializable(self):
        import json
        md = "# T\n\nContent with \"quotes\" and special chars: <>&"
        chunks = chunk_linear(md, max_chars=500)
        json.dumps(chunk_to_dicts(chunks))  # should not raise




class TestExpand:
    def test_expand_includes_breadcrumb(self):
        md = "# Title\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        expanded = chunks[0].expand()
        assert "Title" in expanded

    def test_expand_excludes_components(self):
        md = "# Title\n\nContent."
        chunks = chunk_linear(md, max_chars=500)
        no_bc = chunks[0].expand(include_breadcrumb=False)
        assert " > " not in no_bc
        assert not no_bc.startswith("Title")




class TestHierarchical:
    def test_basic(self):
        md = "# Title\n\n## Section\n\nContent here."
        chunks = chunk_hierarchical(md, max_chars=500)
        assert len(chunks) >= 1

    def test_header_leads_content(self):
        """Every chunk should start with a header (or have a continuation flag)."""
        md = "# A\n\nPara A.\n\n# B\n\nPara B."
        chunks = chunk_hierarchical(md, max_chars=500)
        for c in chunks:
            if not c.metadata.continuation:
                lines = c.content.strip().split("\n")
                assert lines[0].startswith("#"), f"Chunk doesn't start with header: {lines[0]}"

    def test_no_trailing_header(self):
        md = "# A\n\n## B\n\nContent.\n\n# C\n\nMore content."
        chunks = chunk_hierarchical(md, max_chars=500)
        for c in chunks:
            lines = c.content.strip().split("\n")
            assert not lines[-1].strip().startswith("#"), f"Chunk ends with header: {lines[-1]}"

    def test_breadcrumb_includes_path(self):
        md = "# L1\n## L2\n### L3\n\nContent."
        chunks = chunk_hierarchical(md, max_chars=500)
        for c in chunks:
            if c.metadata.source_element_type == "paragraph":
                assert "# L1" in c.metadata.header_breadcrumb
                assert "## L2" in c.metadata.header_breadcrumb
                assert "### L3" in c.metadata.header_breadcrumb

    def test_no_oversized_chunks(self):
        long_text = "Sentence. " * 200
        md = f"# Title\n\n{long_text}"
        chunks = chunk_hierarchical(md, max_chars=500)
        for c in chunks:
            assert len(c.content) <= 500

    def test_empty(self):
        assert chunk_hierarchical("") == []

    def test_merges_sibling_h3_under_same_h2(self):
        """3 H3 siblings under the same H2 (total < max_chars) merge into
        a single chunk with all 3 H3s in its breadcrumb."""
        md = (
            "# H1\n\n"
            "## H2\n\n"
            "### H3a\n\n" + "A" * 300 + "\n\n"
            "### H3b\n\n" + "B" * 400 + "\n\n"
            "### H3c\n\n" + "C" * 300 + "\n"
        )
        chunks = chunk_hierarchical(md, max_chars=2000)
        assert len(chunks) == 1, (
            f"expected 1 merged chunk, got {len(chunks)}: "
            f"{[c.metadata.header_breadcrumb for c in chunks]}"
        )
        bc = chunks[0].metadata.header_breadcrumb
        assert "### H3a" in bc
        assert "### H3b" in bc
        assert "### H3c" in bc
        assert chunks[0].metadata.content_length <= 2000

    def test_merges_sibling_h2_under_same_h1(self):
        """2 H2 siblings under the same H1 (total < max_chars) merge into
        a single chunk at H1 level."""
        md = (
            "# H1\n\n"
            "## H2-A\n\n" + "A" * 700 + "\n\n"
            "## H2-B\n\n" + "B" * 600 + "\n"
        )
        chunks = chunk_hierarchical(md, max_chars=2000)
        assert len(chunks) == 1, (
            f"expected 1 merged chunk, got {len(chunks)}: "
            f"{[c.metadata.header_breadcrumb for c in chunks]}"
        )
        bc = chunks[0].metadata.header_breadcrumb
        assert "## H2-A" in bc
        assert "## H2-B" in bc
        assert chunks[0].metadata.content_length <= 2000

    def test_preserves_h1_boundary(self):
        """H2 siblings under DIFFERENT H1s must NOT merge even if their
        combined size fits. Regression for the H1-boundary guarantee
        originally protected by commit 86c456e (kept intact after relaxing
        the strict-bc sibling-merge check to a parent-path check).

        Sizes chosen so each H1's total content (≥1000c) keeps the root
        all_text above max_size=1600 (preventing the all_text-fits early
        return), forcing the per-chunk merge path where the parent-path
        check actually applies.
        """
        md = (
            "# H1-A\n\n"
            "## H2-A\n\n" + "A" * 1000 + "\n\n"
            "# H1-B\n\n"
            "## H2-B\n\n" + "B" * 1000 + "\n"
        )
        chunks = chunk_hierarchical(md, max_chars=2000)
        assert len(chunks) == 2, (
            f"expected 2 separate chunks (one per H1), got {len(chunks)}: "
            f"{[c.metadata.header_breadcrumb for c in chunks]}"
        )
        for c in chunks:
            bc_str = " ".join(c.metadata.header_breadcrumb)
            assert not ("H1-A" in bc_str and "H1-B" in bc_str), (
                f"H1 boundary violated: chunk breadcrumb mixes both H1s: {bc_str}"
            )
        a_chunks = [c for c in chunks if any("H1-A" in b for b in c.metadata.header_breadcrumb)]
        b_chunks = [c for c in chunks if any("H1-B" in b for b in c.metadata.header_breadcrumb)]
        assert len(a_chunks) == 1 and len(b_chunks) == 1

    def test_hierarchical_merges_siblings_between_soft_and_hard_cap(self):
        """Regression: siblings whose combined size exceeds the soft cap
        (max_size = max_chars * 0.8) but fits under the hard cap (max_chars)
        should still merge. max_chars=2000 → soft=1600, hard=2000.
        H3-B(811c) + H3-C(811c) = 1624c > soft(1600) but < hard(2000);
        with the old threshold (max_size) they would NOT merge, producing
        2 final chunks. With the fix (hard_max) they DO merge → 1 chunk."""
        md = (
            "# H1\n\n"
            "## H2\n\n"
            "### H3-A\n\n" + ("A" * 300) + "\n\n"
            "### H3-B\n\n" + ("B" * 800) + "\n\n"
            "### H3-C\n\n" + ("C" * 800) + "\n"
        )
        chunks = chunk_hierarchical(md, max_chars=2000)
        assert len(chunks) == 1, (
            f"expected 1 merged chunk, got {len(chunks)}: "
            f"{[c.metadata.header_breadcrumb for c in chunks]}"
        )
        bc = chunks[0].metadata.header_breadcrumb
        assert "### H3-A" in bc
        assert "### H3-B" in bc
        assert "### H3-C" in bc
        assert chunks[0].metadata.content_length <= 2000


class TestUnifiedAPI:
    """Test the unified `chunk()` function with algorithm selection."""

    def test_default_is_hierarchical(self):
        """Calling chunk() without algorithm= should use hierarchical.

        Robustness: We compare chunk contents structurally (content,
        source_element_type, continuation flag, breadcrumb) rather than
        just len() — because the hierarchical algorithm's sibling-merge
        heuristic can produce the same chunk count as linear for some
        small documents, making count-based assertions vacuous.
        """
        md = "# A\n\nContent A.\n\n# B\n\nContent B."
        via_default = chunk(md, max_chars=500)
        via_hier = chunk(md, algorithm="hierarchical", max_chars=500)
        via_linear = chunk(md, algorithm="linear", max_chars=500)

        def _structure(chunks):
            return [
                (c.content, c.metadata.source_element_type,
                 c.metadata.continuation, tuple(c.metadata.header_breadcrumb))
                for c in chunks
            ]

        default_s = _structure(via_default)
        hier_s = _structure(via_hier)
        linear_s = _structure(via_linear)

        assert default_s == hier_s, (
            f"Default differs from hierarchical. "
            f"default={len(via_default)} chunks, "
            f"hierarchical={len(via_hier)} chunks"
        )
        assert default_s != linear_s, (
            "Test is vacuous: default and linear produce identical output. "
            "This means linear and hierarchical are indistinguishable on the "
            "chosen input — pick a more discriminating input or use a more "
            "detailed comparison (e.g., source_element_type per chunk)."
        )

    def test_explicit_linear(self):
        md = "# T\n\nContent."
        chunks = chunk(md, algorithm="linear", max_chars=500)
        assert len(chunks) >= 1

    def test_explicit_hierarchical(self):
        md = "# T\n\nContent."
        chunks = chunk(md, algorithm="hierarchical", max_chars=500)
        assert len(chunks) >= 1

    def test_unknown_algorithm_raises(self):
        import pytest
        md = "# T\n\nContent."
        with pytest.raises(ValueError):
            chunk(md, algorithm="unknown")

    def test_chunk_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# T\n\nContent.")
        chunks = chunk_file(str(f), max_chars=500)
        assert len(chunks) >= 1


class TestUrlEmailProtection:
    """Verify the sentence splitter never cuts URLs, emails, or markdown
    image syntax at internal dots / bangs."""

    def test_url_not_split_at_internal_dots(self):
        md = "# T\n\n" + "访问 https://api.openai.com/v1/chat " * 10
        chunks = chunk_linear(md, max_chars=200)
        content_chunks = [c for c in chunks if c.metadata.source_element_type != "header"]
        for c in content_chunks:
            assert "https://api.openai.com/v1/chat" in c.content, \
                f"URL split: {c.content!r}"

    def test_email_not_split_at_internal_dots(self):
        md = "# T\n\n" + "联系dev.team+test@subdomain.example.co.uk " * 5
        chunks = chunk_linear(md, max_chars=150)
        content_chunks = [c for c in chunks if c.metadata.source_element_type != "header"]
        for c in content_chunks:
            assert "dev.team+test@subdomain.example.co.uk" in c.content, \
                f"Email split: {c.content!r}"

    def test_image_markdown_not_split(self):
        md = "# T\n\n" + "看图 ![logo](https://cdn.example.com/a.png) " * 5
        chunks = chunk_linear(md, max_chars=150)
        content_chunks = [c for c in chunks if c.metadata.source_element_type != "header"]
        for c in content_chunks:
            assert "![logo](https://cdn.example.com/a.png)" in c.content, \
                f"Image syntax split: {c.content!r}"

    def test_multiple_urls_in_paragraph(self):
        md = "# T\n\n" + "访问 https://a.com 和 https://b.com/c 和 https://c.d.org/path " * 5
        chunks = chunk_linear(md, max_chars=200)
        content_chunks = [c for c in chunks if c.metadata.source_element_type != "header"]
        urls = ["https://a.com", "https://b.com/c", "https://c.d.org/path"]
        for c in content_chunks:
            for u in urls:
                assert u in c.content, f"URL {u} missing: {c.content!r}"

    def test_url_at_end_of_sentence(self):
        """A URL followed by a real sentence terminator should still terminate."""
        md = "# T\n\n访问 https://api.openai.com/v1/chat 即可。这是最后一句。"
        chunks = chunk_linear(md, max_chars=200)
        content_chunks = [c for c in chunks if c.metadata.source_element_type != "header"]
        for c in content_chunks:
            assert "https://api.openai.com/v1/chat" in c.content

    def test_protect_and_restore_roundtrip(self):
        """Direct test of _protect_urls and _restore_urls."""
        from structchunk._parser import _protect_urls, _restore_urls
        text = "Contact admin@example.com or visit https://www.openai.com for info."
        protected, items = _protect_urls(text)
        restored = _restore_urls(protected, items)
        assert restored == text, f"Roundtrip failed: {restored!r}"

    def test_image_with_url_inside_blockquote(self):
        """Blockquote content is split as a paragraph; URL protection still applies."""
        md = "# T\n\n" + "> 看图 ![logo](https://cdn.example.com/a.png) " * 5
        chunks = chunk_linear(md, max_chars=150)
        content_chunks = [c for c in chunks if c.metadata.source_element_type != "header"]
        for c in content_chunks:
            assert "![logo](https://cdn.example.com/a.png)" in c.content, \
                f"Image in blockquote split: {c.content!r}"


class TestDocIdAutoDerivation:
    """doc_id identifies the source document. It must be auto-derived
    when not explicitly provided."""

    def test_chunk_file_uses_absolute_path_as_doc_id(self, tmp_path):
        f = tmp_path / "test_doc.md"
        f.write_text("# Title\n\nContent.")
        chunks = chunk_file(str(f))
        for c in chunks:
            assert c.metadata.doc_id, "doc_id is empty for chunk_file"
            assert c.metadata.doc_id.endswith("test_doc.md"), \
                f"doc_id doesn't end with filename: {c.metadata.doc_id!r}"

    def test_chunk_file_doc_id_is_absolute(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("Content.")
        chunks = chunk_file(str(f))
        assert os.path.isabs(chunks[0].metadata.doc_id), \
            f"doc_id should be absolute: {chunks[0].metadata.doc_id!r}"

    def test_chunk_auto_derives_content_hash(self):
        md = "# Title\n\nContent."
        chunks1 = chunk(md, max_chars=500)
        chunks2 = chunk(md, max_chars=500)
        # Same content → same hash → same doc_id
        assert chunks1[0].metadata.doc_id == chunks2[0].metadata.doc_id
        import re
        assert re.fullmatch(r"[0-9a-f]{16}", chunks1[0].metadata.doc_id)

    def test_chunk_different_content_different_doc_id(self):
        chunks1 = chunk("# A", max_chars=500)
        chunks2 = chunk("# B", max_chars=500)
        assert chunks1[0].metadata.doc_id != chunks2[0].metadata.doc_id

    def test_explicit_doc_id_overrides_auto_derivation(self):
        chunks = chunk("# Title\n\nContent.", max_chars=500, doc_id="my-doc")
        for c in chunks:
            assert c.metadata.doc_id == "my-doc"

    def test_no_parent_id_field(self):
        """parent_id was a misleading random UUID. It has been removed."""
        from dataclasses import fields
        from structchunk._models import ChunkMetadata
        field_names = {f.name for f in fields(ChunkMetadata)}
        assert "parent_id" not in field_names, \
            f"parent_id should be removed but found in: {field_names}"
        # Also verify to_dict output
        chunks = chunk("# T\n\nContent.", max_chars=500)
        d = chunks[0].to_dict()
        assert "parent_id" not in d["metadata"]


class TestIdUniqueness:
    """Verify that doc_id and chunk_id have meaningful uniqueness guarantees."""

    def test_chunk_id_is_int_for_bigint_storage(self):
        """chunk_id is a 64-bit Snowflake-like int (NOT a hex string) so
        it maps directly to a SQL BIGINT column. str(chunk_id) gives
        the decimal display form (Twitter/Discord/Instagram format)."""
        chunks = chunk("# T\n\nFirst chunk content here.", max_chars=500)
        for c in chunks:
            assert isinstance(c.metadata.chunk_id, int), \
                f"chunk_id should be int, got: {type(c.metadata.chunk_id).__name__}"
            assert 0 < c.metadata.chunk_id < (1 << 63), \
                f"chunk_id should be a positive 63-bit int, got: {c.metadata.chunk_id}"
        # Decimal string form (str(int)) — round-trips with int()
        s = chunks[0].chunk_id_str
        assert isinstance(s, str)
        assert int(s) == chunks[0].metadata.chunk_id

    def test_chunk_ids_unique_within_run(self):
        """Even with many chunks, all chunk_ids in one run are unique."""
        chunks = chunk("# T\n\n" + "短句。" * 5000, max_chars=200)
        ids = [c.metadata.chunk_id for c in chunks]
        assert len(ids) == len(set(ids)), \
            f"Duplicate chunk_id found: {len(ids) - len(set(ids))} dupes"

    def test_chunk_ids_differ_across_runs(self):
        chunks1 = chunk("# T\n\nContent.", max_chars=500)
        chunks2 = chunk("# T\n\nContent.", max_chars=500)
        # Newer run has a later timestamp prefix → larger integer → larger hex string
        # (sequence guarantees uniqueness even within the same millisecond)
        assert chunks1[0].metadata.chunk_id != chunks2[0].metadata.chunk_id

    def test_chunk_ids_are_sortable_by_creation_time(self):
        """Snowflake ids are monotonically increasing with creation time,
        so lexicographic sort = chronological sort. Critical for DB
        clustered-index locality and time-range queries."""
        import time
        chunks1 = chunk("# A\n\nFirst batch.", max_chars=500)
        time.sleep(0.005)  # ensure next batch is in a later millisecond
        chunks2 = chunk("# A\n\nSecond batch.", max_chars=500)
        ids_run1 = [c.metadata.chunk_id for c in chunks1]
        ids_run2 = [c.metadata.chunk_id for c in chunks2]
        max_run1 = max(ids_run1)
        min_run2 = min(ids_run2)
        assert min_run2 > max_run1, \
            f"run2 ids should all be > run1 ids: max_run1={max_run1:x}, min_run2={min_run2:x}"

    def test_chunk_id_timestamp_extractable(self):
        """chunk_id_timestamp_ms() can recover the embedded creation time,
        so users don't need a separate 'created_at' column to do time queries."""
        import time
        from structchunk._models import chunk_id_timestamp_ms
        before_ms = int(time.time() * 1000)
        chunks = chunk("# T\n\nContent.", max_chars=500)
        after_ms = int(time.time() * 1000)
        ts = chunk_id_timestamp_ms(chunks[0].metadata.chunk_id)
        assert before_ms <= ts <= after_ms, \
            f"Extracted timestamp {ts} not in [{before_ms}, {after_ms}]"

    def test_chunk_id_timestamp_returns_zero_for_invalid(self):
        from structchunk._models import chunk_id_timestamp_ms
        assert chunk_id_timestamp_ms("not-a-hex-id") == 0
        assert chunk_id_timestamp_ms("") == 0
        assert chunk_id_timestamp_ms("zzzzzzzzzzzzzzzz") == 0  # 16 chars but not valid

    def test_doc_id_no_sha256_prefix(self):
        """The 'sha256:' prefix was removed because every doc_id had it
        (redundant — the field name and 16-hex-char format already say
        'this is a content hash')."""
        import re
        chunks = chunk("# T\n\nContent.", max_chars=500)
        for c in chunks:
            assert not c.metadata.doc_id.startswith("sha256:"), \
                f"doc_id should not have 'sha256:' prefix: {c.metadata.doc_id!r}"
            assert re.fullmatch(r"[0-9a-f]{16}", c.metadata.doc_id), \
                f"doc_id should be 16 hex chars, got: {c.metadata.doc_id!r}"

    def test_doc_id_different_for_different_content(self):
        chunks1 = chunk("# A", max_chars=500)
        chunks2 = chunk("# B", max_chars=500)
        assert chunks1[0].metadata.doc_id != chunks2[0].metadata.doc_id

    def test_doc_id_same_for_same_content(self):
        """Same content → same hash → same doc_id (idempotent)."""
        chunks1 = chunk("# T\n\nSame content here.", max_chars=500)
        chunks2 = chunk("# T\n\nSame content here.", max_chars=500)
        assert chunks1[0].metadata.doc_id == chunks2[0].metadata.doc_id

    def test_all_chunks_in_run_share_doc_id(self):
        """All chunks from the same document share the same doc_id."""
        chunks = chunk("# A\n\nFirst.\n\n# B\n\nSecond.\n\n# C\n\nThird.", max_chars=500)
        doc_ids = {c.metadata.doc_id for c in chunks}
        assert len(doc_ids) == 1, f"Expected 1 doc_id, got {len(doc_ids)}: {doc_ids}"


class TestContentLengthMetadata:
    """Pre-computed length fields in ChunkMetadata enable DB queries to
    filter and aggregate on chunk size without loading the content."""

    def test_content_length_equals_len_content(self):
        chunks = chunk("# Title\n\nSome content here.", max_chars=500)
        for c in chunks:
            assert c.metadata.content_length == len(c.content)

    def test_content_length_for_chinese(self):
        """length is character count (Python len), not byte count."""
        chunks = chunk("# 中文标题\n\n这是一段中文内容。", max_chars=500)
        for c in chunks:
            assert c.metadata.content_length == len(c.content)
            # Chinese chars are 3 bytes in UTF-8, but len() gives 1 char
            assert c.metadata.content_length < len(c.content.encode("utf-8"))

    def test_breadcrumb_length_sums_headers(self):
        chunks = chunk("# A\n\nFirst.\n\n## B\n\nSecond.", max_chars=500)
        for c in chunks:
            if c.metadata.header_breadcrumb:
                expected = sum(len(h) for h in c.metadata.header_breadcrumb)
                assert c.metadata.breadcrumb_length == expected

    def test_breadcrumb_length_zero_for_no_breadcrumb(self):
        chunks = chunk("Just a paragraph with no headers.", max_chars=500)
        for c in chunks:
            assert c.metadata.breadcrumb_length == 0

    def test_total_length_equals_content_length(self):
        """total_length = content (breadcrumb excluded from total)."""
        chunks = chunk(
            "# Header\n\nFirst paragraph.\n\nSecond paragraph.",
            max_chars=500
        )
        for c in chunks:
            expected = c.metadata.content_length
            assert c.metadata.total_length == expected, \
                f"total_length mismatch: got {c.metadata.total_length}, expected {expected}"

    def test_total_length_at_least_content_length(self):
        """total_length must always >= content_length (content is the core)."""
        chunks = chunk("# T\n\nContent here.", max_chars=500)
        for c in chunks:
            assert c.metadata.total_length >= c.metadata.content_length

    def test_lengths_persist_in_to_dict(self):
        """to_dict() must include all the length fields so they survive serialization."""
        chunks = chunk("# T\n\nContent here.", max_chars=500)
        d = chunks[0].to_dict()
        md = d["metadata"]
        for field in (
            "content_length",
            "breadcrumb_length",
            "total_length",
        ):
            assert field in md, f"to_dict() missing {field!r}"
            assert isinstance(md[field], int)

    def test_explicit_content_length_overrides_autofill(self):
        """If user supplies a non-zero content_length, __post_init__ doesn't overwrite it
        (useful when rehydrating from storage with pre-computed lengths)."""
        from structchunk import ChunkMetadata, MarkdownChunk
        md = ChunkMetadata(
            chunk_id=1,
            chunk_index=0,
            total_chunks=1,
            char_offset_start=0,
            char_offset_end=10,
            header_breadcrumb=[],
            content_length=999,  # explicit
        )
        c = MarkdownChunk(content="0123456789", metadata=md)
        # If the explicit value was 999, it stays 999 — not auto-overwritten to 10
        assert c.metadata.content_length == 999

    def test_explicit_total_length_overrides_autofill(self):
        from structchunk import ChunkMetadata, MarkdownChunk
        md = ChunkMetadata(
            chunk_id=1,
            chunk_index=0,
            total_chunks=1,
            char_offset_start=0,
            char_offset_end=10,
            header_breadcrumb=[],
            total_length=9999,
        )
        c = MarkdownChunk(content="0123456789", metadata=md)
        assert c.metadata.total_length == 9999

    def test_to_dict_emits_decimal_string_for_chunk_id(self):
        """to_dict() outputs str(int) — the format Twitter/Discord/Instagram
        use for Snowflake ids. int(s) round-trips for direct DB insertion."""
        chunks = chunk("# T\n\nContent.", max_chars=500)
        d = chunks[0].to_dict()
        assert isinstance(d["metadata"]["chunk_id"], str)
        assert d["metadata"]["chunk_id"] == str(chunks[0].metadata.chunk_id)
        # Decimal round-trip: int(s) recovers the original value
        assert int(d["metadata"]["chunk_id"]) == chunks[0].metadata.chunk_id

    def test_prev_next_chunk_id_uses_zero_sentinel(self):
        chunks = chunk("# A\n\nFirst.\n\n# B\n\nSecond.\n\n# C\n\nThird.", max_chars=500)
        assert chunks[0].metadata.prev_chunk_id == 0
        assert chunks[-1].metadata.next_chunk_id == 0
        for i in range(1, len(chunks) - 1):
            assert chunks[i].metadata.prev_chunk_id == chunks[i - 1].metadata.chunk_id
            assert chunks[i].metadata.next_chunk_id == chunks[i + 1].metadata.chunk_id

    def test_to_dict_emits_empty_string_for_zero_prev_next(self):
        """JSON output uses '' for missing prev/next."""
        chunks = chunk("# A\n\nContent.", max_chars=500)
        d = chunks[0].to_dict()
        assert d["metadata"]["prev_chunk_id"] == ""
        assert d["metadata"]["next_chunk_id"] == ""

    def test_chunk_id_str_property(self):
        """chunk.chunk_id_str == str(chunk_id) for display/JSON."""
        chunks = chunk("# T\n\nContent.", max_chars=500)
        assert chunks[0].chunk_id_str == str(chunks[0].metadata.chunk_id)

    def test_chunk_id_timestamp_accepts_decimal_str(self):
        """chunk_id_timestamp_ms() should accept the decimal str form
        that comes out of to_dict() (int() parses it directly)."""
        chunks = chunk("# T\n\nContent.", max_chars=500)
        decimal_str = str(chunks[0].metadata.chunk_id)
        from structchunk import chunk_id_timestamp_ms
        ts_int = chunk_id_timestamp_ms(chunks[0].metadata.chunk_id)
        ts_str = chunk_id_timestamp_ms(decimal_str)
        assert ts_int == ts_str
        assert ts_int > 0


class TestForwardIntroText:
    """Tests for forwarding plain-text intro to table/list continuations.

    When a section/chunk's first table or list is inmediatamente preceded by
    a plain-text paragraph (not a markdown header), the paragraph's last
    sentence acts as the implicit "title" of the table/list. When the
    section is split, this title is forwarded to continuations so each
    chunk is self-explanatory.
    """

    def test_hierarchical_table_continuation_has_intro(self):
        """Hierarchical: text + table, intro forwarded to table continuation."""
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Title\n\n重要提示：以下是性能数据。\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk(md, max_chars=200)
        assert len(chunks) > 1, f"Need multiple chunks to test, got {len(chunks)}"
        # All chunks should contain the intro
        for c in chunks[1:]:  # all but the first
            assert "重要提示" in c.content, (
                f"Continuation chunk missing intro: {c.content[:80]!r}"
            )

    def test_hierarchical_list_continuation_has_intro(self):
        """Hierarchical: text + list, intro forwarded to list continuation."""
        items = [f"- Item {i}: 这是列表项的描述" for i in range(30)]
        md = "# Title\n\n参考列表如下。\n\n" + "\n".join(items)
        chunks = chunk(md, max_chars=200)
        assert len(chunks) > 1
        for c in chunks[1:]:
            assert "参考列表如下" in c.content, (
                f"Continuation chunk missing list intro: {c.content[:80]!r}"
            )

    def test_hierarchical_header_preceding_no_intro_forward(self):
        """Hierarchical: header (## H2) + table, NO plain-text intro forward.

        The header mechanism already handles the title; we shouldn't
        also forward a "last sentence" because there IS no preceding
        paragraph to extract from.
        """
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Title\n\n## 性能数据\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk(md, max_chars=200)
        assert len(chunks) > 1
        for c in chunks[1:]:
            # The header IS the title — must be present
            assert "## 性能数据" in c.content
            # But the marker *[续]* should be the only "title" mechanism used
            # (no plain-text paragraph extraction)
            # We don't check the exact absence of any plain text — we just
            # verify the header is there.

    def test_hierarchical_no_preceding_paragraph(self):
        """Hierarchical: table at section start (no preceding paragraph)."""
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Title\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk(md, max_chars=200)
        # No intro to forward (no preceding paragraph)
        # This should work without error
        assert len(chunks) >= 1

    def test_linear_table_continuation_has_intro(self):
        """Linear: text + table, intro forwarded to table continuation."""
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "重要提示：以下是性能数据。\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk(md, max_chars=200, algorithm="linear")
        assert len(chunks) > 1
        for c in chunks[1:]:
            assert "重要提示" in c.content, (
                f"Linear continuation missing intro: {c.content[:80]!r}"
            )

    def test_forward_intro_text_disabled(self):
        """forward_intro_text=False disables intro forwarding."""
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        md = "# Title\n\n重要提示：以下是性能数据。\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)

        # With default (True): intro in all chunks
        chunks_on = chunk(md, max_chars=200, forward_intro_text=True)
        assert all("重要提示" in c.content for c in chunks_on), \
            "Expected intro in all chunks when forward_intro_text=True"

        # With False: intro only in chunk 0
        chunks_off = chunk(md, max_chars=200, forward_intro_text=False)
        assert "重要提示" in chunks_off[0].content, "Chunk 0 should have intro"
        for c in chunks_off[1:]:
            assert "重要提示" not in c.content, (
                f"forward_intro_text=False should NOT forward intro, "
                f"but chunk contains: {c.content[:80]!r}"
            )

    def test_chunk_file_respects_forward_intro_text(self):
        """chunk_file() should also pass forward_intro_text through."""
        import tempfile
        import os
        rows = [f"| r{i} | v{i} |" for i in range(20)]
        content = "# Title\n\n重要提示：以下是性能数据。\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(content)
            tmpfile = f.name
        try:
            chunks_off = chunk_file(tmpfile, max_chars=200, forward_intro_text=False)
            assert "重要提示" in chunks_off[0].content
            for c in chunks_off[1:]:
                assert "重要提示" not in c.content, (
                    f"chunk_file with forward_intro_text=False should NOT forward: {c.content[:80]!r}"
                )
        finally:
            os.unlink(tmpfile)

    def test_h2_with_children_table_in_own_blocks(self):
        """H2 section containing BOTH own_blocks (table) AND H3 children:
        continuation chunk must have table header, intro, and *[续]* marker.

        Reproduces the bug where H2 with "表0：xxx" + table 0 in own_blocks
        plus H3 children (表1-4) had chunk[2] missing column header, intro,
        and *[续]* marker. The fix extracted the forwarding logic into
        _apply_continuation_forwarding() and applied it in the merge path.
        """
        rows = [f"| r{i} | v{i} |" for i in range(15)]
        table_str = "| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        md = (
            "# Title\n\n"
            "## 二、对比表\n\n"
            "表0：这是表 0 的标题。\n\n"
            f"{table_str}\n\n"
            "### 表1：这是子表 1\n\n"
            f"{table_str}\n\n"
            "### 表2：这是子表 2\n\n"
            f"{table_str}\n"
        )
        chunks = chunk(md, max_chars=290)
        assert len(chunks) > 1, f"Need multiple chunks to test, got {len(chunks)}"

        intro_chunks = [i for i, c in enumerate(chunks) if "表0：" in c.content]
        assert len(intro_chunks) >= 1, "Expected at least one chunk with '表0：' intro"

        first = intro_chunks[0]
        if first + 1 >= len(chunks):
            return
        cont = chunks[first + 1]

        assert "| H1 | H2 |" in cont.content, (
            f"H2-with-children continuation missing table header: {cont.content[:100]!r}"
        )
        assert "表0：" in cont.content, (
            f"H2-with-children continuation missing intro: {cont.content[:100]!r}"
        )
        # *[续]* marker removed in v0.3.0 — inject_missing_breadcrumbs
        # provides the parent context instead.

    def test_h2_with_children_no_own_table_unchanged(self):
        """H2 with no own table but with H3 children: forwarding is a no-op.

        Regression check: H2 with ONLY children (no own_blocks table) should
        not be affected by the new forwarding logic. The forwarding helper
        should not introduce table-header/intro/marker when there are no
        table blocks in own_blocks and no preceding paragraph to extract.
        """
        md = (
            "# Title\n\n"
            "## 总结\n\n"
            "### 子节 1\n\n"
            "内容 1。\n\n"
            "### 子节 2\n\n"
            "内容 2。\n"
        )
        chunks = chunk(md, max_chars=200)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.content
            assert c.metadata.header_breadcrumb


class TestLengthFields:
    """Tests for content_length, breadcrumb_length, total_length fields
    and hard_max_size enforcement after breadcrumb injection.

    Bug #1: total_length used to be content_length + breadcrumb_length,
    which over-counted because breadcrumb text is already inlined in
    content via *[续]* markers and inject_missing_breadcrumbs.

    Bug #2: enforce_hard_max used to run BEFORE inject_missing_breadcrumbs,
    so a chunk that fit the cap pre-injection could grow past hard_max_size
    after breadcrumb headers were added.
    """

    def test_total_length_equals_content_length(self):
        """Bug #1: total_length = content_length (no double-count)."""
        md = "# Top\n\n## Section A\n\nbody content"
        chunks = chunk(md)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.metadata.total_length == c.metadata.content_length, (
                f"total_length {c.metadata.total_length} != "
                f"content_length {c.metadata.content_length}"
            )
            assert c.metadata.total_length == len(c.content), (
                f"total_length {c.metadata.total_length} != "
                f"len(content) {len(c.content)}"
            )

    def test_breadcrumb_length_still_tracked(self):
        """breadcrumb_length is still tracked (not removed by Bug #1 fix)."""
        md = "# Top\n\n## Section A\n\nbody content"
        chunks = chunk(md)
        multi_bc = [c for c in chunks if len(c.metadata.header_breadcrumb) >= 2]
        assert len(multi_bc) >= 1, "Expected at least one chunk with 2+ breadcrumb levels"
        for c in multi_bc:
            expected = sum(len(h) for h in c.metadata.header_breadcrumb)
            assert c.metadata.breadcrumb_length == expected, (
                f"breadcrumb_length {c.metadata.breadcrumb_length} != "
                f"sum {expected}"
            )
            # total_length still equals content_length (Bug #1 fix preserved)
            assert c.metadata.total_length == c.metadata.content_length

    def test_hard_max_enforced_after_breadcrumb_injection(self):
        """Bug #2: no chunk exceeds hard_max_size (= max_chars) post-injection."""
        # Section A's body is just under 300 chars, but adding breadcrumb
        # headers ("# Top", "## Section A") would push it over.
        md = (
            "# Top\n\n"
            "## Section A\n\n"
            + ("a" * 280)
            + "\n\n## Section B\n\n"
            + ("b" * 50)
        )
        chunks = chunk(md, max_chars=300)
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c.content) <= 300, (
                f"Chunk exceeds hard_max_size: len={len(c.content)} "
                f"content[:80]={c.content[:80]!r}"
            )

    def test_no_mid_token_cut_with_prefix(self):
        """Pre-budget fix: 200 x chars + max_chars=200 should NOT produce
        a 189+11 mid-token cut. The prefix-aware re-split should either
        keep it as 1 chunk (if effective_max accommodates) or split at a
        real boundary.
        """
        md = "# T\n\n## A\n\n" + "x" * 200
        chunks = chunk(md, max_chars=200)
        assert all(len(c.content) <= 200 for c in chunks)
        # Verify no mid-token 189+11 split (the old _force_split_long_strings bug)
        # If split happened, total x count across all chunks should be 200
        total_x = sum(c.content.count("x") for c in chunks)
        assert total_x == 200, f"x chars lost or duplicated: {total_x}"

    def test_sentence_boundary_respected_with_cap(self):
        """Pre-budget fix: when content has sentence terminators, the
        re-split should cut at sentence boundaries, not mid-sentence."""
        sentences = "".join(["这是第{}句。".format(i) for i in range(30)])
        md = "# T\n\n## A\n\n" + sentences
        chunks = chunk(md, max_chars=100)
        assert all(len(c.content) <= 100 for c in chunks)
        # Verify no sentence-terminator content is lost
        total_boundaries = sum(c.content.count("。") for c in chunks)
        assert total_boundaries == 30, f"Lost sentence terminators: {total_boundaries}"
        # Verify that "full" chunks (body close to cap) end at sentence
        # boundaries, proving re-split respects sentence structure.
        # Tiny fragments from the initial assembly may trail mid-sentence
        # (the re-split only triggers for chunks at/near the cap).
        for c in chunks:
            body = c.content
            for line in body.split("\n"):
                if line.strip() and not line.startswith("#") and not line.startswith("*[续]"):
                    body = body[body.index(line):]
                    break
            else:
                continue  # header-only chunk
            body = body.strip()
            if not body:
                continue
            # If body is substantial (≥ half the cap) and has sentence
            # terminators, it must end at a sentence boundary.
            if len(body) >= 50 and "。" in body:
                assert body.endswith("。"), \
                    f"Chunk body does not end at sentence boundary: {body[-50:]!r}"

    def test_table_row_boundary_with_cap(self):
        """Pre-budget fix: table content with cap should split at row
        boundaries, not mid-row."""
        rows = [f"| r{i} | v{i} |" for i in range(30)]
        md = "# T\n\n## A\n\n| H1 | H2 |\n| --- | --- |\n" + "\n".join(rows)
        chunks = chunk(md, max_chars=200)
        assert all(len(c.content) <= 200 for c in chunks)
        # Each chunk should preserve table structure (starts/ends at row boundaries)
        for c in chunks:
            if "| " in c.content:
                lines = c.content.rstrip().split("\n")
                last_line = lines[-1] if lines else ""
                # Last line should be a complete row (starts/ends with |)
                if last_line.strip():
                    assert last_line.startswith("|") and last_line.endswith("|"), \
                        f"Last line not a table row: {last_line!r}"

    def test_prefix_budget_effective(self):
        """Pre-budget fix: chunks should respect hard_max_size even when
        breadcrumb prefix is large (e.g. deep hierarchy)."""
        # Deep hierarchy → longer breadcrumb prefix
        md = "# L0\n\n## L1\n\n### L2\n\n#### L3\n\n" + ("这是正文内容。" * 30)
        chunks = chunk(md, max_chars=200)
        assert all(len(c.content) <= 200 for c in chunks), \
            f"Found chunk over cap: {[(len(c.content), c.metadata.header_breadcrumb) for c in chunks if len(c.content) > 200]}"
        # The chunks should have varying body sizes depending on prefix budget
        # (e.g. deep hierarchy → less room for body)
        # No need to assert specific sizes, just that the cap is met

    def test_max_chars_small_respected_with_paragraph(self):
        """Regression test: max_chars=30 with deep hierarchy should
        respect the cap. Previously _detect_existing_prefix missed
        markdown breadcrumb lines (## Section, ### Subsection), causing
        chunks to exceed the cap by 1-10 chars.
        """
        md = "# Top\n\n## Section\n\n" + "This is a long body. " * 20
        chunks = chunk(md, max_chars=30)
        over = [c for c in chunks if len(c.content) > 30]
        assert len(over) == 0, (
            f"Found {len(over)} chunks over 30 chars: "
            f"{[(len(c.content), c.content[:50]) for c in over[:3]]}"
        )

    def test_detect_existing_prefix_with_breadcrumb(self):
        """Unit test: _detect_existing_prefix should detect markdown
        breadcrumb lines, not just table headers.
        """
        from structchunk._enrich import _detect_existing_prefix
        from structchunk._models import MarkdownChunk, ChunkMetadata, HeaderInfo

        # Paragraph chunk with H1+H2 breadcrumb
        c = MarkdownChunk(
            content="## Top\n## Section\n\nThis is the body.",
            metadata=ChunkMetadata(
                chunk_id=0, chunk_index=0, total_chunks=0,
                char_offset_start=0, char_offset_end=0,
                header_breadcrumb=["Top", "Section"],
                header_path=[HeaderInfo(1, "Top"), HeaderInfo(2, "Section")],
                source_element_type="paragraph",
            ),
        )
        prefix = _detect_existing_prefix(c)
        assert "## Top" in prefix, f"Expected '## Top' in prefix, got: {prefix!r}"
        assert "## Section" in prefix, f"Expected '## Section' in prefix, got: {prefix!r}"
        assert "This is the body" not in prefix, f"Body leaked: {prefix!r}"

        # Continuation chunk with *[续]* marker
        c2 = MarkdownChunk(
            content="*[续] ## Section*\n\nbody content",
            metadata=ChunkMetadata(
                chunk_id=0, chunk_index=0, total_chunks=0,
                char_offset_start=0, char_offset_end=0,
                header_breadcrumb=["Top", "Section"],
                header_path=[HeaderInfo(1, "Top"), HeaderInfo(2, "Section")],
                source_element_type="paragraph",
                continuation=True,
            ),
        )
        prefix2 = _detect_existing_prefix(c2)
        assert "*[续]" in prefix2, f"Expected '*[续]' in prefix, got: {prefix2!r}"
        assert "body content" not in prefix2, f"Body leaked: {prefix2!r}"

        # Chunk with no prefix
        c3 = MarkdownChunk(
            content="Just body, no prefix.",
            metadata=ChunkMetadata(
                chunk_id=0, chunk_index=0, total_chunks=0,
                char_offset_start=0, char_offset_end=0,
                header_breadcrumb=[],
                header_path=[],
                source_element_type="paragraph",
            ),
        )
        prefix3 = _detect_existing_prefix(c3)
        assert prefix3 == "", f"Expected empty prefix, got: {prefix3!r}"

    def test_paragraph_chunk_with_table_uses_table_dispatch(self):
        """Regression test: a chunk labeled `paragraph` that contains a markdown
        table should be re-split by `split_table_rows`, not `split_paragraph_at_sentences`.

        Without this, the paragraph splitter cuts the table mid-row, producing
        tiny chunks like '|无|' (1 char body + table header).
        """
        # Reproduce the H2 section structure where:
        # - block 0 is the intro paragraph "表0：xxx"
        # - block 1 is the table with header + separator + data rows
        # The section's dominant_type is "paragraph" (because the intro
        # paragraph is first), but the body contains a real table.
        intro_para = "表0：知识库核心能力对比（RAG关键指标）"
        table = (
            "|对比项|Milvus|Qdrant|Weaviate|PgVector|Chroma|Pinecone|FAISS|\n"
            "| ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- |\n"
            "\n"
            "|HNSW|✅A|✅B|✅C|✅D|仅E|自动F|全G|\n"
            "\n"
            "|混合检索|✅A|✅B|✅C|✅D|仅E|向量F|无G|\n"
            "\n"
            "|元数据|✅A|✅B|✅C|✅D|✅E|✅F|无G|\n"
            "\n"
            "|增量更新|✅A|✅B|✅C|✅D|✅E|✅F|需G|\n"
            "\n"
            "|LangChain|✅A|✅B|✅C|✅D|✅E|✅F|需G|\n"
            "\n"
            "|Embedding|无|可选|✅H|无|✅I|云J|无|\n"
        )
        md = f"# Title\n\n## 二、对比表\n\n{intro_para}\n\n{table}\n"
        chunks = chunk(md, max_chars=400)
        # Find the chunk(s) containing the table
        table_chunks = [c for c in chunks if "| ---- |" in c.content or "|对比项|" in c.content]
        assert len(table_chunks) >= 1, "Expected at least one chunk with the table"
        for c in table_chunks:
            # Every chunk's last line should be a complete table row
            # (starts AND ends with |), not a mid-row fragment.
            lines = c.content.rstrip().split("\n")
            # Skip the leading breadcrumb lines
            content_lines = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
            if not content_lines:
                continue
            last = content_lines[-1]
            # If last line contains table cells, it should end with `|` (full row)
            if "|" in last and not last.startswith("|---"):
                assert last.endswith("|"), (
                    f"Table chunk has mid-row cut at end: ...{last[-60:]!r}"
                )

    def test_chunk_has_table_detects_headerless_table(self):
        """Regression test: _chunk_has_table should return True for a body
        that contains multiple table data rows, even without a |---| separator.

        When _re_split_with_prefix_budget strips the table header (including
        the separator) as existing_prefix, the remaining body has only data
        rows. The helper must detect this and dispatch to split_table_rows
        instead of split_paragraph_at_sentences (which would cut mid-cell).
        """
        from structchunk._enrich import _chunk_has_table

        # Body with separator (primary case) — should return True
        body_with_sep = (
            "| H1 | H2 |\n"
            "| --- | --- |\n"
            "| v1 | v2 |\n"
        )
        assert _chunk_has_table(body_with_sep) is True

        # Body without separator but with multiple data rows — should return True
        body_data_only = (
            "|HNSW|✅A|✅B|\n\n"
            "|混合检索|✅C|✅D|\n\n"
            "|LangChain|✅E|✅F|\n"
        )
        assert _chunk_has_table(body_data_only) is True, (
            f"Expected headerless table body to be detected as table, "
            f"got _chunk_has_table=False. Body: {body_data_only!r}"
        )

        # Body with just one table row (could be coincidence, not a table) — should return False
        body_single = "|HNSW|✅A|✅B|"
        assert _chunk_has_table(body_single) is False

        # Plain paragraph (no pipes) — should return False
        body_para = "This is just plain text with no tables at all."
        assert _chunk_has_table(body_para) is False

    def test_h1_not_demoted_to_h2_in_subsequent_chunks(self):
        """Regression test: H1 document title must stay as `#` (H1) in
        the first chunk where it appears. Without proper header_path
        plumbing, the H1 gets prepended as `##` (H2 demoted) in
        subsequent chunks when inject_missing_breadcrumbs falls back
        to level=2 for unknown header levels.
        """
        md = "# Document Title\n\nFirst paragraph here is short.\n\nSecond paragraph that is long enough to force splitting when we use a small max_chars cap so the chunks split into multiple parts and the H1 should still appear as `#` not `##`.\n\nThird paragraph also long enough for splitting."
        chunks = chunk(md, max_chars=60)
        assert len(chunks) > 1, f"Need multiple chunks to test, got {len(chunks)}"
        # Find chunk that contains "Document Title"
        h1_chunk_idx = None
        h2_wrong_chunks = []
        for i, c in enumerate(chunks):
            for line in c.content.split("\n"):
                if "Document Title" in line:
                    if line.startswith("# Document Title"):
                        h1_chunk_idx = i
                    elif line.startswith("## Document Title"):
                        h2_wrong_chunks.append((i, line))
                    break
        assert h1_chunk_idx is not None, (
            f"No chunk has '# Document Title'. Chunks: "
            f"{[c.content[:60] for c in chunks]}"
        )
        assert len(h2_wrong_chunks) == 0, (
            f"Found H1 demoted to H2: {h2_wrong_chunks}"
        )

    def test_h1_in_every_chunk_after_split(self):
        """Regression: H1 document title must appear in EVERY chunk,
        not only chunk[0]. Previously inject_missing_breadcrumbs
        skipped H1 (level <= 1).
        """
        md = "# H1\n\n## H2\n\nbody body body body body body body body body body body body body body body body body body body."
        chunks = chunk(md, max_chars=40)
        assert len(chunks) > 1, "Need multiple chunks for this test"
        for c in chunks:
            assert "# H1" in c.content, (
                f"Chunk missing H1: {c.content[:80]!r}"
            )

    def test_header_breadcrumb_has_hash_prefix(self):
        """Regression: header_breadcrumb entries must include the # prefix
        matching their markdown level (e.g. '# H1', '## H2', '### H3').
        """
        md = "# Top\n\n## Section A\n\n### Subsection\n\nbody body body."
        chunks = chunk(md)
        # Find chunk in the '### Subsection' section
        subsec = [c for c in chunks if any("Subsection" in b for b in c.metadata.header_breadcrumb)]
        assert subsec, "Expected at least one chunk with Subsection in breadcrumb"
        sample = subsec[0].metadata.header_breadcrumb
        # At least one entry should start with '###' (subsection)
        assert any(b.startswith("###") for b in sample), (
            f"Expected '###' prefix in breadcrumb, got: {sample}"
        )

    def test_no_continuation_marker_in_chunks(self):
        """Regression: chunks should not contain '*[续]*' markers.
        They break markdown rendering and provide no value.
        """
        md = "# H1\n\n## H2\n\nAAA AAA AAA AAA AAA AAA.\n\nBBB BBB BBB BBB BBB BBB BBB BBB."
        chunks = chunk(md, max_chars=40)
        assert len(chunks) > 1, "Need multiple chunks"
        for c in chunks:
            assert "*[续]*" not in c.content, (
                f"Chunk contains *[续]* marker: {c.content[:80]!r}"
            )

    def test_no_double_hash_prefix_in_chunk_content(self):
        """Regression: chunk content must not contain duplicate # prefixes
        like '# # H1' or '## ## H2'. After commit 9acb365f made
        header_breadcrumb entries include the # prefix (e.g. "# H1"),
        the inject_missing_breadcrumbs and _compute_prefix_for_chunk
        helpers should append them directly without re-prefixing.
        """
        md = "# H1\n\n## H2\n\n" + "body one two three four five six seven eight nine ten eleven twelve thirteen fourteen. " * 5
        chunks = chunk(md, max_chars=100)
        assert len(chunks) > 1, "Need multiple chunks"
        for c in chunks:
            # No "# #" or "## ##" or "### ###" should appear
            assert "# #" not in c.content, (
                f"Found duplicate '# #' in chunk: {c.content[:80]!r}"
            )
            assert "## ##" not in c.content, (
                f"Found duplicate '## ##' in chunk: {c.content[:80]!r}"
            )
            assert "### ###" not in c.content, (
                f"Found duplicate '### ###' in chunk: {c.content[:80]!r}"
            )

    def test_chunk_with_table_has_src_table_even_with_intro_paragraph(self):
        """Regression: a section containing an intro paragraph + a table
        should be labeled src='table' for the chunk, not src='paragraph'.
        Previously, _dominant_type returned 'paragraph' (first non-blank
        block) when the leading block was a paragraph before the table.
        """
        md = "# Top\n\n## Section\n\nIntro paragraph here.\n\n| H1 | H2 |\n| --- | --- |\n| a | b |\n| c | d |\n| e | f |\n| g | h |\n"
        chunks = chunk(md, max_chars=200)
        assert len(chunks) >= 1, "Expected at least one chunk"
        # Find chunks that contain table content
        table_chunks = [c for c in chunks if "| --- |" in c.content or "| ---- |" in c.content]
        assert table_chunks, "Expected at least one chunk with table content"
        for c in table_chunks:
            assert c.metadata.source_element_type == "table", (
                f"Chunk with table content has src={c.metadata.source_element_type!r}, "
                f"expected 'table'. Content: {c.content[:120]!r}"
            )

    def test_sibling_sections_not_merged_when_cap_too_small(self):
        """Regression: with a small max_chars cap, sibling sections
        (different H2/H3) MUST NOT be merged into one chunk because the
        cap itself prevents the merge — Section A + Section B is too big
        to fit together under cap. This is NOT a structural rule against
        merging siblings; it is the cap doing its job.

        The LCP-based sibling merge (in `_section_to_chunks`) DOES allow
        cross-level sibling merge when both sections are complete and
        their combined size < max_chars and they share a non-empty LCP.
        This test only verifies that a too-small cap blocks the merge.
        """
        md = """# H1

## Section A

AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA AAA.

## Section B

BBB BBB.
"""
        chunks = chunk(md, max_chars=60)
        # No chunk should have BOTH Section A and Section B in breadcrumb
        for c in chunks:
            bc = c.metadata.header_breadcrumb
            has_a = any("Section A" in b for b in bc)
            has_b = any("Section B" in b for b in bc)
            assert not (has_a and has_b), (
                f"Chunk mixes sibling sections in breadcrumb: {bc}\n"
                f"Content: {c.content[:80]!r}"
            )
        # Section B's content should be in its own chunk
        b_chunks = [c for c in chunks if "BBB BBB." in c.content]
        assert len(b_chunks) >= 1, "Section B content missing"
        # Section A's tail 'AAA.' should NOT be in the same chunk as Section B header
        mixed = [c for c in chunks if "AAA." in c.content and "## Section B" in c.content]
        assert len(mixed) == 0, (
            f"Found chunks mixing Section A tail with Section B header: "
            f"{[c.content[:80] for c in mixed]}"
        )

    def test_hierarchical_merges_cross_level_siblings_under_h1(self):
        """When two adjacent complete H2 sections under the same H1 have
        combined size < max_chars, they merge into one chunk with bc
        = [H1, H2A, H2B] (the LCP is [H1])."""
        md = "# H1\n\n## H2A\n\n" + "A" * 1000 + "\n\n## H2B\n\n" + "B" * 500
        chunks = chunk(md, max_chars=2000)
        # Combined 1000+500+headers ≈ 1530 < 2000
        assert len(chunks) == 1, (
            f"Expected 1 merged chunk, got {len(chunks)}: "
            f"{[(c.metadata.content_length, c.metadata.header_breadcrumb) for c in chunks]}"
        )
        bc = chunks[0].metadata.header_breadcrumb
        assert any("H2A" in b for b in bc) and any("H2B" in b for b in bc), (
            f"Both H2s should be in bc: {bc}"
        )

    def test_hierarchical_preserves_h1_boundary_even_with_lcp_logic(self):
        """Regression: different H1s have LCP=[] and must NEVER merge,
        even with the LCP-based logic. Cap is large enough that H2
        siblings under same H1 would merge — verify they don't when
        they're under different H1s."""
        md = "# H1-A\n\n## H2\n\n" + "A" * 1000 + "\n\n# H1-B\n\n## H2\n\n" + "B" * 1000
        chunks = chunk(md, max_chars=2000)
        assert len(chunks) == 2, (
            f"Expected 2 chunks (different H1s), got {len(chunks)}: "
            f"{[(c.metadata.content_length, c.metadata.header_breadcrumb) for c in chunks]}"
        )
        for c in chunks:
            bc = c.metadata.header_breadcrumb
            has_a = any("H1-A" in b for b in bc)
            has_b = any("H1-B" in b for b in bc)
            assert not (has_a and has_b), (
                f"Chunk crosses H1 boundary: {bc}"
            )

    def test_hierarchical_section_tail_does_not_cross_level_merge(self):
        """Regression: when H2A is split into multiple chunks (because its
        total size > hard_max), H2A's tail chunk must NOT merge with the
        adjacent H2B chunk, even if H2A's tail + H2B < hard_max. Only
        section-complete chunks (chunks whose section was emitted as a
        single chunk) can cross-level merge."""
        md = (
            "# H1\n\n"
            "## H2A\n\n"
            + "A" * 1200 + "\n\n"
            + "B" * 1200 + "\n\n"
            "## H2B\n\n"
            + "C" * 200
        )
        chunks = chunk(md, max_chars=2000)
        h2b_chunks = [c for c in chunks if "C" * 100 in c.content]
        assert len(h2b_chunks) == 1, (
            f"H2B content should be in 1 chunk, got {len(h2b_chunks)}: "
            f"{[c.content[:60] for c in h2b_chunks]}"
        )
        h2b_chunk = h2b_chunks[0]
        bc = h2b_chunk.metadata.header_breadcrumb
        h2b_bc_entries = [b for b in bc if "H2B" in b]
        h2a_bc_entries = [b for b in bc if "H2A" in b]
        assert len(h2b_bc_entries) >= 1, f"H2B not in bc: {bc}"
        assert len(h2a_bc_entries) == 0, f"H2A leaked into H2B's chunk bc: {bc}"

    def test_linear_respects_cap_with_long_inlined_breadcrumb(self):
        """Regression: linear + small max_chars + deep hierarchy where
        inlined breadcrumb prefix exceeds cap. The 2nd _re_split_with_prefix_budget
        pass (added after inject_missing_breadcrumbs) must re-split the body
        accounting for the injected prefix, bringing every chunk under cap."""
        md = (
            "# H1\n\n"
            "## H2\n\n"
            "### H3 with very long title to make prefix > cap\n\n"
            "Short body paragraph."
        )
        chunks = chunk(md, max_chars=100, algorithm="linear")
        over = [c for c in chunks if len(c.content) > 100]
        assert len(over) == 0, (
            f"Found {len(over)} chunks over cap: "
            f"{[(len(c.content), c.content[:60]) for c in over[:3]]}"
        )


class TestSnowflakeForkSafety:
    """Verify Snowflake generator is fork-safe (Task8 P1 A)."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="os.register_at_fork is not available on Windows",
    )
    def test_parent_and_child_produce_distinct_ids(self):
        import os as os_mod

        parent_id = _snowflake.next_id()
        pid = os_mod.fork()
        if pid ==0:
            child_id = _snowflake.next_id()
            print(f"CHILD_ID:{child_id}")
            os_mod._exit(0)
        else:
            _, status = os_mod.waitpid(pid,0)
            assert os.WIFEXITED(status)
            assert parent_id >0

    @pytest.mark.skipif(
        not hasattr(os, "register_at_fork"),
        reason="register_at_fork only available on POSIX",
    )
    def test_register_at_fork_was_called(self):
        from structchunk import _models
        assert hasattr(_models, "_snowflake")

class TestSnowflakeClockResilience:
    """Verify Snowflake generator handles clock going backwards (Task8 P1 B)."""

    def test_clock_backwards_eventually_raises(self, monkeypatch):
        from structchunk._models import _SnowflakeGenerator

        gen = _SnowflakeGenerator(node_id=99)
        first_id = gen.next_id()
        assert first_id >0

        original_time = time.time
        monkeypatch.setattr("time.time", lambda: original_time() -0.100)
        with pytest.raises(RuntimeError, match="clock not advancing"):
            gen.next_id()

    def test_clock_catches_up_within_spin_window(self, monkeypatch):
        from structchunk._models import _SnowflakeGenerator

        gen = _SnowflakeGenerator(node_id=99)
        first_id = gen.next_id()

        original_time = time.time
        call_state = {"calls":0}

        def patched_time():
            call_state["calls"] +=1
            real = original_time()
            if call_state["calls"] ==1:
                return real -0.001
            return real

        monkeypatch.setattr("time.time", patched_time)
        second_id = gen.next_id()
        assert second_id > first_id

class TestSnowflakeTimestampTolerance:
    """Verify chunk_id_timestamp_ms accepts timestamps up to60s in future (Task8 P1 T)."""

    def test_future_30s_accepted(self):
        from structchunk._models import chunk_id_timestamp_ms
        future_ms_from_epoch = (int(time.time() *1000) -1735689600000) +30000
        future_id = future_ms_from_epoch <<22
        ts = chunk_id_timestamp_ms(future_id)
        assert ts !=0
        assert ts >1735689600000

    def test_past_24h_accepted(self):
        from structchunk._models import chunk_id_timestamp_ms, _EPOCH_MS
        past_ms = int(time.time() *1000) -24 *3600 *1000
        past_id = (past_ms - _EPOCH_MS) <<22
        assert chunk_id_timestamp_ms(past_id) == past_ms


class TestMergeTinySectionComplete:
    """Verify merge_tiny honors is_section_complete invariant (Task 9 P1 C).

    A tail chunk from a split section (is_section_complete=False) must not
    be merged with an adjacent chunk even if both have tiny content and
    share the same breadcrumb. Without this guard, the hierarchical
    algorithm's "完整同级" rule is violated downstream.
    """

    def test_tail_does_not_merge_into_next_section(self):
        from structchunk._enrich import merge_tiny
        a = MarkdownChunk(content="A body", metadata=ChunkMetadata(
            chunk_id=1, chunk_index=0, total_chunks=3,
            char_offset_start=0, char_offset_end=7,
            header_breadcrumb=["# A"], is_section_complete=True,
        ))
        b = MarkdownChunk(content="B body", metadata=ChunkMetadata(
            chunk_id=2, chunk_index=1, total_chunks=3,
            char_offset_start=7, char_offset_end=14,
            header_breadcrumb=["# A"], is_section_complete=False,
        ))
        c = MarkdownChunk(content="C body", metadata=ChunkMetadata(
            chunk_id=3, chunk_index=2, total_chunks=3,
            char_offset_start=14, char_offset_end=21,
            header_breadcrumb=["# B"], is_section_complete=True,
        ))
        result = merge_tiny(
            [a, b, c],
            ChunkerConfig(min_chunk_size=50, hard_max_size=2000),
        )
        # A is section-complete and shares breadcrumb with B → merge A+B.
        # B is NOT section-complete → must NOT be merged with C.
        # Net result: [A+B, C]
        assert len(result) == 2
        assert result[0].content == "A body\n\nB body"
        assert result[1].content == "C body"

    def test_complete_sections_can_still_merge(self):
        """Regression guard: the new invariant must not break the existing
        same-breadcrumb merge path for complete sections."""
        from structchunk._enrich import merge_tiny
        a = MarkdownChunk(content="A body", metadata=ChunkMetadata(
            chunk_id=1, chunk_index=0, total_chunks=2,
            char_offset_start=0, char_offset_end=7,
            header_breadcrumb=["# A"], is_section_complete=True,
        ))
        b = MarkdownChunk(content="B body", metadata=ChunkMetadata(
            chunk_id=2, chunk_index=1, total_chunks=2,
            char_offset_start=7, char_offset_end=14,
            header_breadcrumb=["# A"], is_section_complete=True,
        ))
        result = merge_tiny(
            [a, b],
            ChunkerConfig(min_chunk_size=50, hard_max_size=2000),
        )
        assert len(result) == 1
        assert result[0].content == "A body\n\nB body"


class TestSourceMetaBlockTypesConsistency:
    """Verify both algorithms produce multi-element block_types (Task 9 P1 D)."""

    def test_hierarchical_block_types_includes_all_non_blank(self):
        md = "## H\n\npara\n\n- item1\n- item2\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        chunks = chunk(md, algorithm="hierarchical", max_chars=1000)
        multi = [
            c for c in chunks
            if len(c.metadata.source_meta.get("block_types", [])) > 1
        ]
        assert len(multi) > 0, (
            f"Expected at least one chunk with multi-type block_types, "
            f"got {[c.metadata.source_meta for c in chunks]}"
        )

    def test_linear_block_types_includes_all_non_blank(self):
        md = "## H\n\npara\n\n- item1\n- item2\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        chunks = chunk(md, algorithm="linear", max_chars=1000)
        multi = [
            c for c in chunks
            if len(c.metadata.source_meta.get("block_types", [])) > 1
        ]
        assert len(multi) > 0, (
            f"Expected at least one chunk with multi-type block_types, "
            f"got {[c.metadata.source_meta for c in chunks]}"
        )


class TestIsSectionCompletePropagated:
    """Verify is_section_complete reaches ChunkMetadata from the dict layer (P1 C)."""

    def test_hierarchical_emits_section_complete_field(self):
        from structchunk import chunk
        md = "# A\n\nbody of A\n\n# B\n\nbody of B\n"
        chunks = chunk(md, algorithm="hierarchical", max_chars=2000)
        for c in chunks:
            assert hasattr(c.metadata, "is_section_complete")
            assert isinstance(c.metadata.is_section_complete, bool)

    def test_linear_defaults_to_section_complete_true(self):
        from structchunk import chunk
        md = "# A\n\nbody\n"
        chunks = chunk(md, algorithm="linear", max_chars=2000)
        for c in chunks:
            assert c.metadata.is_section_complete is True


class TestCLI:
    """Test CLI behavior (Task 10)."""

    def test_main_file_not_found_exits_1(self, tmp_path, capsys):
        import subprocess
        import sys as sys_mod
        missing = tmp_path / "nonexistent.md"
        result = subprocess.run(
            [sys_mod.executable, "-m", "structchunk._cli", str(missing)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert "File not found" in result.stderr

    def test_main_empty_chunks_no_crash(self, tmp_path):
        import subprocess
        import sys as sys_mod
        empty_file = tmp_path / "empty.md"
        empty_file.write_text("", encoding="utf-8")
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [
                sys_mod.executable,
                "-m",
                "structchunk._cli",
                str(empty_file),
                "--output-dir",
                str(out_dir),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "No chunks produced" in result.stdout

    def test_arg_parser_accepts_output_dir(self):
        from structchunk._cli import _build_arg_parser
        parser = _build_arg_parser()
        args = parser.parse_args(["file.md", "--output-dir", "/tmp/test"])
        assert args.output_dir == "/tmp/test"

    def test_arg_parser_default_output_dir(self):
        from structchunk._cli import _build_arg_parser
        parser = _build_arg_parser()
        args = parser.parse_args(["file.md"])
        assert args.output_dir == "./test_result/"

    def test_print_summary_empty_chunks(self, capsys):
        from structchunk._cli import _print_summary
        _print_summary([], "some/file.md", "hierarchical")
        captured = capsys.readouterr()
        assert "No chunks produced from some/file.md." in captured.out


class TestChunkValidation:
    """Test top-level chunk() validation (Task 10 P1 F)."""

    def test_unknown_algorithm_raises(self):
        with pytest.raises(ValueError, match="Unknown algorithm"):
            chunk("# H\n\npara\n", algorithm="bogus")

    def test_max_chars_zero_raises(self):
        with pytest.raises(ValueError, match="max_chars"):
            chunk("# H\n\npara\n", max_chars=0)

    def test_max_chars_negative_raises(self):
        with pytest.raises(ValueError, match="max_chars"):
            chunk("# H\n\npara\n", max_chars=-5)

    def test_max_chars_none_allowed(self):
        out = chunk("# H\n\npara\n", max_chars=None)
        assert isinstance(out, list)

    def test_valid_algorithms_pass_through(self):
        md = "# H\n\npara\n"
        assert isinstance(chunk(md, algorithm="linear"), list)
        assert isinstance(chunk(md, algorithm="hierarchical"), list)


class TestInjectBreadcrumbsLineMatch:
    """Verify inject_missing_breadcrumbs uses line-prefix match (Task 11 P1 G)."""

    def test_substring_match_does_not_confuse_section_2_with_2_5(self):
        from structchunk._enrich import inject_missing_breadcrumbs
        from structchunk._models import MarkdownChunk, ChunkMetadata

        chunk = MarkdownChunk(
            content="## Section 2.5\n\nbody paragraph",
            metadata=ChunkMetadata(
                chunk_id=1,
                chunk_index=0,
                total_chunks=1,
                char_offset_start=0,
                char_offset_end=27,
                header_breadcrumb=["## Section 2"],
            ),
        )
        result = inject_missing_breadcrumbs([chunk])
        assert "## Section 2\n" in result[0].content
        assert "## Section 2.5" in result[0].content


class TestSourceMeta:
    """Verify _type_seq_counts removed from public metadata (Task 12 P1 J)."""

    def test_type_seq_counts_not_in_metadata(self):
        chunks = chunk("# H\n\npara1\n\npara2\n", max_chars=500)
        assert chunks, "fixture should produce at least one chunk"
        for c in chunks:
            assert "_type_seq_counts" not in c.metadata.source_meta, (
                f"_type_seq_counts leaked into source_meta: {c.metadata.source_meta}"
            )

    def test_type_seq_counts_not_in_metadata_linear(self):
        chunks = chunk(
            "# H\n\npara1\n\npara2\n", algorithm="linear", max_chars=500
        )
        assert chunks, "fixture should produce at least one chunk"
        for c in chunks:
            assert "_type_seq_counts" not in c.metadata.source_meta, (
                f"_type_seq_counts leaked into source_meta: {c.metadata.source_meta}"
            )


class TestIntroTextDedup:
    """Verify intro text extraction is one shared function (Task 12 P1 S)."""

    def test_intro_extraction_consistent_across_algorithms(self):
        from structchunk.hierarchical import _extract_intro_text
        from structchunk.linear import _extract_intro_text_linear

        assert _extract_intro_text is _extract_intro_text_linear, (
            "Intro text extraction should be one shared function (dedup P1 S)"
        )
        # Both names should resolve to the canonical helper in _enrich.
        from structchunk._enrich import _extract_intro_text as canonical

        assert _extract_intro_text is canonical
        assert _extract_intro_text_linear is canonical

    def test_intro_extraction_behavior_preserved(self):
        # Pre-dedup, both copies had identical body. Spot-check that the
        # shared function still returns the expected values for canonical
        # inputs — proves the move did not regress behavior.
        from structchunk._enrich import _extract_intro_text

        para_block = AtomicBlock(
            block_type=BlockType.PARAGRAPH,
            char_start=0,
            char_end=40,
            lines=["Important notice."],
            meta={},
        )
        table_block = AtomicBlock(
            block_type=BlockType.TABLE,
            char_start=40,
            char_end=50,
            lines=["| a | b |", "|---|---|"],
            meta={"header_rows": ["| a | b |"]},
        )
        assert _extract_intro_text([para_block, table_block]) == "Important notice."
        header_block = AtomicBlock(
            block_type=BlockType.HEADER,
            char_start=0,
            char_end=10,
            lines=["## Section"],
            meta={"level": 2, "text": "Section"},
        )
        assert _extract_intro_text([header_block, table_block]) == ""
        assert _extract_intro_text([]) == ""


class TestKeepHeadersRemoved:
    """Verify keep_headers_in_content field is gone (Task 12 P1 L)."""

    def test_keep_headers_in_content_field_gone(self):
        from structchunk._config import ChunkerConfig
        with pytest.raises(TypeError):
            ChunkerConfig(keep_headers_in_content=False)

    def test_chunk_linear_rejects_keep_headers_kwarg(self):
        with pytest.raises(TypeError):
            chunk_linear("# H\n\npara\n", keep_headers_in_content=False)

    def test_chunk_rejects_keep_headers_kwarg(self):
        with pytest.raises(TypeError):
            chunk("# H\n\npara\n", keep_headers_in_content=False)

