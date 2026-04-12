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
