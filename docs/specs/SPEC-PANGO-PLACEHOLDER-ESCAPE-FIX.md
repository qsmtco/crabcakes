# SPEC: Pango Placeholder + Escape Fix (Combined)

**Date:** 2026-07-30
**Author:** Supervisor (mechanism corrected by Debugger audit)
**Status:** Ready for implementation
**Depends on:** SPEC-PANGO-ANCHOR-TAG-FIX.md (already implemented — the `<a>` emission fix)
**Target branch:** main

> **Architecture compliance:** Fixes `utils/escaping.py` and `utils/markdown.py` only. No layer violations.

---

## 1. Overview

### Problem
After the Pango `<a>`-tag fix (2026-07-30), 45 message segments in the persisted Supervisor conversation are still rejected by `Pango.parse_markup`. Two distinct root causes remain:

1. **Placeholder-shadowing (Mode 1, 10 failures):** Step 3 of `format_markdown` consumes code-span placeholders. When a markdown link's label is a backticked code span (`` [`code.md`](url) ``), Step 1 replaces `` `code.md` `` with `\x00CODE0\x00`, then Step 3's regex captures the placeholder as the label, stores `f'<u>\x00CODE0\x00</u>'` in `anchor_spans`, and the null byte survives to the final markup. Pango's GLib parser uses C-string semantics — `\x00` terminates the string — so it sees an open `<u>` with no close.

2. **`escape_for_pango` preserves unsupported `<a>` tag (Modes 2/3/4, 27 failures):** `_PANGO_KNOWN_TAGS` in `utils/escaping.py:31` includes `"a"`, so `escape_for_pango` passes `<a href="...">` through unchanged. But Pango 1.52 does NOT support `<a>` — the tag reaches `format_markdown` and then `set_markup` intact, where Pango rejects it.

### Root Cause (verified by Debugger)
- **Mode 1:** `format_markdown` Step 3's `_link_replace_and_protect` (line 230) stores `f'<u>{label}</u>'` where `label` may contain `\x00CODE{N}\x00` placeholders. Step 5 (code restoration) never resolves them because the placeholder was consumed from `protected`. The null bytes reach Pango.
- **Modes 2/3/4:** `escape_for_pango` preserves `<a>` because it's in `_PANGO_KNOWN_TAGS`. The preserved `<a>` reaches `format_markdown`, Step 3b wraps its href in a null-containing placeholder, and Pango rejects both the null and the unknown tag.

### Solution Summary
1. **`utils/escaping.py`:** Remove `"a"` from `_PANGO_KNOWN_TAGS`. Now `escape_for_pango` always escapes `<a>` to `&lt;a&gt;`. (Eliminates Modes 2/3/4.)
2. **`utils/markdown.py`:** In Step 3's `_link_replace_and_protect`, resolve code-span placeholders in the label before storing the anchor HTML. If the label is or contains `\x00CODE{N}\x00`, resolve to `<tt>code_text</tt>` first, then wrap in `<u>`. (Eliminates Mode 1.)

### Scope

| In scope | Out of scope |
|----------|-------------|
| `utils/escaping.py` — remove `"a"` from `_PANGO_KNOWN_TAGS` | Migration script for old conversation data (deferred) |
| `utils/markdown.py` — resolve placeholders in Step 3 labels | Restoring link clickability (future spec) |
| `tests/test_escaping.py` — update `<a>`-preservation assertions | Bare-hostname auto-linking removal (separate UX concern) |
| `tests/test_markdown.py` — add code-span-label regression test | |

---

## 2. Changes by File

### 2.1 `utils/escaping.py`

**Edit 1:** Remove `"a"` from `_PANGO_KNOWN_TAGS` (line ~40).

Current:
```python
_PANGO_KNOWN_TAGS: frozenset[str] = frozenset({
    # Text style tags
    "b", "i", "u", "s", "tt", "big", "small",
    # Span tag (generic container with attributes)
    "span",
    # Anchor tag
    "a",
    # Sub/superscript
    "sub", "sup",
    # Overline
    "o",
})
```

Fixed:
```python
_PANGO_KNOWN_TAGS: frozenset[str] = frozenset({
    # Text style tags
    "b", "i", "u", "s", "tt", "big", "small",
    # Span tag (generic container with attributes)
    "span",
    # Sub/superscript
    "sub", "sup",
    # Overline
    "o",
    # NOTE: "a" (anchor) is NOT included — Pango 1.52 does not support <a>
    # in markup. escape_for_pango escapes <a> to &lt;a&gt; so it never
    # reaches format_markdown or Gtk.Label.set_markup.
})
```

### 2.2 `utils/markdown.py`

**Edit 2:** In Step 3's `_link_replace_and_protect` (line ~230), resolve code-span placeholders in the label.

Current:
```python
    def _link_replace_and_protect(m):
        label = m.group(1)
        url = m.group(2)
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
        # Pango does NOT support <a href> in markup (raises Unknown tag 'a').
        # Render link text as underlined (non-clickable). HIGH-6 validation
        # is preserved: non-allowlisted schemes still get the warning prefix.
        # Clickable links require Pango AttrType.LINK (future spec).
        anchor_html = f'<u>{label}</u>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
```

Fixed:
```python
    def _link_replace_and_protect(m):
        label = m.group(1)
        url = m.group(2)
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
        # Resolve code-span placeholders in the label BEFORE storing.
        # Step 1 may have replaced `code` with \x00CODE{N}\x00. If we store
        # the placeholder in anchor_html, Step 5 (code restoration) won't
        # find it (it was consumed from `protected`), and the null bytes
        # reach Pango, which uses C-string semantics and truncates at \x00.
        label = _CODE_PLACEHOLDER_RE.sub(_resolve_code_in_label, label)
        # Pango does NOT support <a href> in markup (raises Unknown tag 'a').
        # Render link text as underlined (non-clickable). HIGH-6 validation
        # is preserved: non-allowlisted schemes still get the warning prefix.
        # Clickable links require Pango AttrType.LINK (future spec).
        anchor_html = f'<u>{label}</u>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
```

And add the `_resolve_code_in_label` helper before `_link_replace_and_protect`:

```python
    def _resolve_code_in_label(m):
        """Resolve a \x00CODE{N}\x00 placeholder to <tt>code</tt> for use inside anchor_html."""
        idx = int(m.group(1))
        if idx < len(code_spans):
            content = code_spans[idx]
            if '&' in content:
                return f'<tt>{content}</tt>'
            return f'<tt>{html.escape(content)}</tt>'
        return m.group(0)
```

**Note:** The same fix must be applied to Step 3a's `_angle_link_replace` (line ~258) — angle-bracket auto-links can also contain code-span placeholders in their display text. However, angle-links capture the URL itself as display text, which is unlikely to be a code span. **Apply the fix only where the label comes from user text (Step 3).** Verify whether Step 3a needs it.

### 2.3 `tests/test_escaping.py`

Update assertions that expect `escape_for_pango` to PRESERVE `<a>` tags. After the fix, `<a>` is escaped like any other unknown tag.

**Tests to update** (from grep: lines 75, 124, 160, 189, 202-203, 209-210):
- `test_anchor_tag_preserved` (line 74) → `test_anchor_tag_escaped` — now expects `&lt;a href=...&gt;`
- `test_link_tag_with_url` (line ~123) → now expects escaped output
- `test_valid_a_tag_pair_preserved` → `test_a_tag_pair_escaped`
- `test_grep_output_with_a_tag` → may still pass (tests orphan escaping)
- `test_buggy_autolink_output_robust` (line ~160) → update expected output

**Read each test before editing.** Run pytest to see failures, then update each to match actual output.

### 2.4 `tests/test_markdown.py`

Add regression test:
```python
def test_markdown_link_with_code_span_label():
    """Regression: [\\`code\\`](url) must produce valid Pango markup.

    Step 3 must resolve code-span placeholders in link labels before
    storing anchor_html, otherwise null bytes reach Pango.
    """
    from utils.escaping import escape_for_pango
    result = format_markdown(escape_for_pango("[`context.md`](https://example.com)"))
    # Must not contain null bytes
    assert '\x00' not in result
    # Must contain the code text
    assert 'context.md' in result
```

---

## 3. Acceptance Criteria

- [ ] `"a"` removed from `_PANGO_KNOWN_TAGS` in `utils/escaping.py`
- [ ] Step 3 `_link_replace_and_protect` resolves code-span placeholders via `_resolve_code_in_label`
- [ ] `_resolve_code_in_label` helper added to `format_markdown`
- [ ] `escape_for_pango('<a href="x">y</a>')` returns escaped output (not preserved)
- [ ] `format_markdown` output for `` [`code`](url) `` contains no null bytes
- [ ] All `test_escaping.py` tests pass (updated assertions)
- [ ] All `test_markdown.py` tests pass (including new regression test)
- [ ] Re-running the 348-message conversation probe shows ≤6 failures (only pre-existing data)

---

## 4. Implementation Order

### Phase 1: `utils/escaping.py` — remove `"a"` from known tags
### Phase 2: `utils/markdown.py` — resolve placeholders in Step 3
### Phase 3: Update tests (`test_escaping.py` + `test_markdown.py`)
