# tests/test_block_parser.py
# Tests for utils/block_parser.py — block segment extraction.

import pytest
from utils.block_parser import extract_blocks


class TestFencedCodeBlocks:
    def test_code_block_with_lang(self):
        result = extract_blocks("```python\nprint('hi')\n```")
        assert len(result) == 1
        assert result[0]["type"] == "code"
        assert result[0]["lang"] == "python"
        assert "print" in result[0]["content"]

    def test_code_block_without_lang(self):
        result = extract_blocks("```\nhello world\n```")
        assert len(result) == 1
        assert result[0]["type"] == "code"
        assert result[0]["lang"] == ""

    def test_code_block_multiline(self):
        result = extract_blocks("```js\nconst x = 1;\nconst y = 2;\n```")
        assert result[0]["type"] == "code"
        assert result[0]["lang"] == "js"
        assert "const y" in result[0]["content"]

    def test_mixed_text_and_code(self):
        result = extract_blocks("Hello\n\n```python\nx = 1\n```\n\nWorld")
        assert len(result) == 3
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "code"
        assert result[2]["type"] == "text"

    def test_code_block_trailing_newline_stripped(self):
        result = extract_blocks("```\ncode\n```\n")
        assert result[0]["content"] == "code"
        assert not result[0]["content"].endswith("\n")


class TestHeadings:
    def test_heading_level_1(self):
        result = extract_blocks("# Main Title")
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 1
        assert result[0]["content"] == "Main Title"

    def test_heading_level_3(self):
        result = extract_blocks("### Section Three")
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 3

    def test_heading_level_6(self):
        result = extract_blocks("###### Six")
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 6

    def test_heading_with_text_after(self):
        result = extract_blocks("# Title\n\nSome body text")
        assert result[0]["type"] == "heading"
        assert result[1]["type"] == "text"


class TestBlockquotes:
    def test_single_line_blockquote(self):
        result = extract_blocks("> A wise quote")
        assert result[0]["type"] == "quote"
        assert "wise quote" in result[0]["content"]

    def test_multiline_blockquote(self):
        result = extract_blocks("> Line one\n> Line two\n> Line three")
        assert result[0]["type"] == "quote"
        assert "Line one" in result[0]["content"]
        assert "Line three" in result[0]["content"]

    def test_blockquote_with_space_after_gt(self):
        result = extract_blocks(">  Indented quote")
        assert result[0]["type"] == "quote"


class TestTerminal:
    def test_single_terminal_command(self):
        result = extract_blocks("$ pip install foo")
        assert result[0]["type"] == "terminal"
        assert "pip install foo" in result[0]["content"]

    def test_multiline_terminal(self):
        result = extract_blocks("$ cd /home\n$ ls -la")
        assert result[0]["type"] == "terminal"
        assert "cd /home" in result[0]["content"]
        assert "ls -la" in result[0]["content"]

    def test_terminal_with_output_lines(self):
        # Terminal block: first line starts with $, output lines may follow without $
        result = extract_blocks("$ make build\nCompiling...\nDone.")
        assert result[0]["type"] == "terminal"
        assert "make build" in result[0]["content"]
        assert "Compiling" in result[0]["content"]
        assert "Done" in result[0]["content"]


class TestTaskLists:
    def test_unchecked_task(self):
        result = extract_blocks("- [ ] Buy groceries")
        assert result[0]["type"] == "task"
        assert "Buy groceries" in result[0]["content"]
        # Note: the content format is "[ ] text" as a string

    def test_checked_task(self):
        result = extract_blocks("- [x] Done thing")
        assert result[0]["type"] == "task"
        assert "Done thing" in result[0]["content"]

    def test_mixed_checked_unchecked(self):
        result = extract_blocks("- [ ] Item one\n- [x] Item two")
        assert result[0]["type"] == "task"
        assert "Item one" in result[0]["content"]
        assert "Item two" in result[0]["content"]


class TestPlainText:
    def test_plain_text_single_line(self):
        result = extract_blocks("Hello world")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert result[0]["content"] == "Hello world"

    def test_plain_text_multiline(self):
        # Single newline (no blank line) = one paragraph = one text segment
        result = extract_blocks("Line one\nLine two")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "Line one" in result[0]["content"]
        assert "Line two" in result[0]["content"]

    def test_plain_text_with_hash(self):
        # A # in the middle of text is not a heading
        result = extract_blocks("Version #123 released")
        assert result[0]["type"] == "text"
        assert "#123" in result[0]["content"]


class TestEdgeCases:
    def test_empty_string(self):
        result = extract_blocks("")
        assert result == [{"type": "text", "content": ""}]

    def test_blank_lines_only(self):
        result = extract_blocks("\n\n   \n\n")
        assert result == [{"type": "text", "content": ""}]

    def test_all_block_types_together(self):
        text = "# Heading\n\n> A quote\n\n```python\ncode\n```\n\n$ cmd\n\n- [ ] task"
        result = extract_blocks(text)
        types = [r["type"] for r in result]
        assert "heading" in types
        assert "quote" in types
        assert "code" in types
        assert "terminal" in types
        assert "task" in types


class TestHeadingRegex:
    """Bug #6: heading regex must accept bare ## and no-space variants."""

    def test_no_space_heading(self):
        """##no-space should be a level-2 heading with content 'no-space'."""
        result = extract_blocks("##no-space")
        assert len(result) == 1
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 2
        assert result[0]["content"] == "no-space"

    def test_standard_heading_with_space(self):
        """Regression: ### heading must still work."""
        result = extract_blocks("### has space")
        assert len(result) == 1
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 3
        assert result[0]["content"] == "has space"

    def test_bare_markers_empty_content(self):
        """## with no content should be a heading with empty content."""
        result = extract_blocks("##")
        assert len(result) == 1
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 2
        assert result[0]["content"] == ""

    def test_six_hashes_max(self):
        """###### heading should be level 6."""
        result = extract_blocks("###### max heading")
        assert len(result) == 1
        assert result[0]["type"] == "heading"
        assert result[0]["level"] == 6
        assert result[0]["content"] == "max heading"

    def test_seven_hashes_not_heading(self):
        """####### too many should NOT be a heading (>6 hashes)."""
        result = extract_blocks("####### too many")
        # Should fall through to text, not heading
        assert any(r["type"] != "heading" for r in result), (
            "7+ hashes should not be a heading"
        )


class TestMixedContentParagraphs:
    """Heading/quote/task followed by non-matching lines within the same paragraph.

    These are the cases that caused data loss (heading) or format degradation
    (quote/task) before the fix. The root cause: _classify_paragraph returned
    a single dict, discarding lines after the first block-type match.
    """

    def test_heading_then_body_single_newline(self):
        """### X\nbody must produce heading + text, not heading only."""
        result = extract_blocks("### X\nbody")
        assert len(result) == 2
        assert result[0]["type"] == "heading"
        assert result[0]["content"] == "X"
        assert result[1]["type"] == "text"
        assert result[1]["content"] == "body"

    def test_heading_then_multiline_body(self):
        """## X\nl2\nl3\nl4 must preserve all body lines."""
        result = extract_blocks("## X\nl2\nl3\nl4")
        assert len(result) == 2
        assert result[0]["type"] == "heading"
        assert result[1]["type"] == "text"
        assert "l2" in result[1]["content"]
        assert "l3" in result[1]["content"]
        assert "l4" in result[1]["content"]

    def test_heading_then_body_no_data_loss(self):
        """The word 'body' must appear somewhere in the output segments."""
        result = extract_blocks("### Heading\nbody text here")
        all_content = " ".join(seg.get("content", "") for seg in result)
        assert "body text here" in all_content, "body text was lost!"

    def test_quote_then_text(self):
        """> quote\nnon-quote must produce quote + text, not text only."""
        result = extract_blocks("> quote\nnon-quote-line")
        assert len(result) == 2
        assert result[0]["type"] == "quote"
        assert "quote" in result[0]["content"]
        assert result[1]["type"] == "text"
        assert result[1]["content"] == "non-quote-line"

    def test_task_then_text(self):
        """- [ ] task\nnot-task must produce task + text, not text only."""
        result = extract_blocks("- [ ] task\nnot-task")
        assert len(result) == 2
        assert result[0]["type"] == "task"
        assert "task" in result[0]["content"]
        assert result[1]["type"] == "text"
        assert result[1]["content"] == "not-task"

    def test_recursive_nesting_heading_quote_text(self):
        """### Heading\n> quote\nbody → [heading, quote, text]."""
        result = extract_blocks("### Heading\n> quote\nbody")
        assert len(result) == 3
        assert result[0]["type"] == "heading"
        assert result[0]["content"] == "Heading"
        assert result[1]["type"] == "quote"
        assert result[1]["content"] == "quote"
        assert result[2]["type"] == "text"
        assert result[2]["content"] == "body"

    def test_two_headings_single_newline(self):
        """## A\n## B → [heading(A), heading(B)]."""
        result = extract_blocks("## A\n## B")
        assert len(result) == 2
        assert result[0]["type"] == "heading"
        assert result[0]["content"] == "A"
        assert result[1]["type"] == "heading"
        assert result[1]["content"] == "B"

    def test_heading_only_no_body(self):
        """### Heading (no body) → single heading segment, no recursion."""
        result = extract_blocks("### Heading")
        assert len(result) == 1
        assert result[0]["type"] == "heading"
        assert result[0]["content"] == "Heading"

    def test_quote_multiline_then_text(self):
        """> line1\n> line2\nplain → [quote(2 lines), text]."""
        result = extract_blocks("> line1\n> line2\nplain")
        assert len(result) == 2
        assert result[0]["type"] == "quote"
        assert "line1" in result[0]["content"]
        assert "line2" in result[0]["content"]
        assert result[1]["type"] == "text"
        assert result[1]["content"] == "plain"

    def test_task_multiple_then_text(self):
        """- [ ] a\n- [x] b\nplain → [task(2 items), text]."""
        result = extract_blocks("- [ ] a\n- [x] b\nplain")
        assert len(result) == 2
        assert result[0]["type"] == "task"
        assert "a" in result[0]["content"]
        assert "b" in result[0]["content"]
        assert result[1]["type"] == "text"
        assert result[1]["content"] == "plain"


class TestMixedContentRegressions:
    """Ensure existing behavior is preserved after the rewrite."""

    def test_blank_line_heading_body_still_works(self):
        """Regression: # Title\n\nbody still produces 2 segments."""
        result = extract_blocks("# Title\n\nSome body text")
        assert result[0]["type"] == "heading"
        assert result[1]["type"] == "text"

    def test_multiline_quote_all_lines(self):
        """Regression: > l1\n> l2\n> l3 → 1 quote segment."""
        result = extract_blocks("> Line one\n> Line two\n> Line three")
        assert len(result) == 1
        assert result[0]["type"] == "quote"
        assert "Line one" in result[0]["content"]
        assert "Line three" in result[0]["content"]

    def test_mixed_tasks_all_lines(self):
        """Regression: - [ ] a\n- [x] b → 1 task segment."""
        result = extract_blocks("- [ ] Item one\n- [x] Item two")
        assert len(result) == 1
        assert result[0]["type"] == "task"

    def test_empty_string(self):
        """Regression: empty input returns [{"type": "text", "content": ""}]."""
        result = extract_blocks("")
        assert result == [{"type": "text", "content": ""}]

    def test_plain_text_multiline(self):
        """Regression: single-newline plain text = 1 text segment."""
        result = extract_blocks("Line one\nLine two")
        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "Line one" in result[0]["content"]
        assert "Line two" in result[0]["content"]
