# PHASE 1b — Orphan Tag + Auto-Link Tests

**Spec:** `docs/specs/spec-orphan-tag-autolink.md`
**Files to change:** `tests/test_escaping.py`, `tests/test_markdown.py`

Both fixes are ALREADY IMPLEMENTED in the code:
- `utils/escaping.py` lines 209-225: orphan tag sweep
- `utils/markdown.py` line 37: `=` added to lookbehind

This phase is TESTS ONLY.

---

## FIX 3 — Tests for orphan tag sweep

**File:** `tests/test_escaping.py` — append after `TestStrictEntityUnescape` class.

```python
class TestOrphanTagSweep:
    """Orphan opening tags (no matching close) must be escaped."""

    def test_orphan_a_tag_escaped(self):
        result = escape_for_pango('renders <a href="..."> tags')
        assert '<a ' not in result
        assert '&lt;a' in result

    def test_orphan_b_tag_escaped(self):
        result = escape_for_pango('<b>bold')
        assert '<b>' not in result
        assert '&lt;b&gt;' in result

    def test_valid_tag_pair_preserved(self):
        assert escape_for_pango('<b>bold</b>') == '<b>bold</b>'

    def test_valid_a_tag_pair_preserved(self):
        result = escape_for_pango('<a href="https://x.com">link</a>')
        assert '<a href="https://x.com">link</a>' == result

    def test_nested_valid_tags_preserved(self):
        assert escape_for_pango('<b><i>nested</i></b>') == '<b><i>nested</i></b>'

    def test_grep_output_with_a_tag(self):
        """The exact crash trigger: plain text containing <a href="...">."""
        result = escape_for_pango('# ← renders <a href="..."> tags')
        assert '<a ' not in result
        assert '&lt;a' in result

    def test_no_orphan_when_all_closed(self):
        """When all tags are properly closed, sweep does nothing."""
        result = escape_for_pango('<b>one</b> <i>two</i>')
        assert result == '<b>one</b> <i>two</i>'
```

---

## FIX 4 — Tests for auto-link lookbehind

**File:** `tests/test_markdown.py` — append after `TestAngleBracketAutoLink` class.

```python
class TestAutoLinkAttributeProtection:
    """Auto-link regex must not match URLs inside href="..." attributes."""

    def test_url_in_href_not_double_linked(self):
        """A pre-existing <a href="URL"> must not get nested <a> tags."""
        result = format_markdown('<a href="https://example.com">link</a>')
        assert result.count('<a ') == 1, f"Nested <a> tags: {result}"

    def test_plain_url_still_links(self):
        """Regression: plain URLs without attributes still auto-link."""
        result = format_markdown("check https://example.com for info")
        assert '<a href="https://example.com">' in result

    def test_url_after_equals_not_linked(self):
        """URL preceded by = should not auto-link."""
        result = format_markdown('value=https://example.com')
        assert '<a ' not in result
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Do NOT touch any production code files. Only add tests.
- Read `tests/test_escaping.py` and `tests/test_markdown.py` before editing to find the correct insertion point.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# 1. New orphan tag tests
python3 -m pytest tests/test_escaping.py::TestOrphanTagSweep -v

# 2. New auto-link tests
python3 -m pytest tests/test_markdown.py::TestAutoLinkAttributeProtection -v

# 3. Full regression
python3 -m pytest tests/test_escaping.py tests/test_markdown.py -v
```

## Deliverables

```
COMPLETENESS:
- [x/not done] 7 orphan tag tests added — evidence: (command 1)
- [x/not done] 3 auto-link protection tests added — evidence: (command 2)
- [x/not done] Existing tests pass — evidence: (command 3)
```
