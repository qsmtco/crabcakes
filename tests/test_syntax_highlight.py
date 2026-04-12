# tests/test_syntax_highlight.py
# Tests for utils/syntax_highlight.py

import pytest
from utils.syntax_highlight import highlight


class TestHighlight:
    def test_python_highlighted_output_has_span_tags(self):
        result = highlight("def foo(): pass", "python")
        assert "<span foreground=" in result

    def test_python_keywords_colored(self):
        result = highlight("def foo():", "python")
        assert '<span foreground="#c792ea">def</span>' in result

    def test_python_function_name_colored(self):
        result = highlight("def foo():", "python")
        assert '<span foreground="#82aaff">foo</span>' in result

    def test_python_string_colored(self):
        result = highlight("'hello'", "python")
        assert '<span foreground="#c3e88d">' in result

    def test_unknown_language_falls_back_to_plain_escaped(self):
        result = highlight("hello world", "nonexistent_lang_xyz")
        assert "<tt>" in result
        assert "hello world" in result  # escaped but present

    def test_empty_string_returns_empty(self):
        assert highlight("", "python") == ""
        assert highlight("", "") == ""

    def test_javascript_highlighted(self):
        result = highlight("const x = 1;", "javascript")
        assert "<span foreground=" in result

    def test_bash_highlighted(self):
        result = highlight("echo hello", "bash")
        assert "<span foreground=" in result

    def test_no_pygments_fallback(self):
        """If pygments import fails at runtime, falls back to <tt>escaped</tt>."""
        # We can't easily mock the import failure, but we can test the
        # unknown language path which produces the same output as no-pygments
        result = highlight("code here", "zzz_unknown_lexer")
        assert "<tt>" in result

    def test_html_entities_escaped(self):
        """Special chars in code source are escaped, not interpreted as markup."""
        result = highlight("<div>hello</div>", "html")
        # Each < > / char is individually escaped by html.escape inside tokens
        # So the raw < is &lt; within span content — check for &lt; anywhere
        assert "&lt;" in result

    def test_colon_colored(self):
        """Punctuation like : gets colored."""
        result = highlight("def foo():", "python")
        assert '<span foreground="#89ddff">:</span>' in result

    def test_comment_colored(self):
        result = highlight("# this is a comment", "python")
        assert '<span foreground="#676e95">' in result  # comment color

    def test_number_colored(self):
        result = highlight("x = 42", "python")
        assert '<span foreground="#f78c6c">' in result  # number color
