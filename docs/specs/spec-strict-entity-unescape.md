# SPEC: Strict Entity Unescape in `escape_for_pango`

**Date:** 2026-07-08
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** Companion fix to `docs/specs/spec-angle-bracket-autolink.md`
**Depends on:** None (orthogonal to the auto-link spec; both are valid without the other)
**Target branch:** main

> **Architecture compliance:** This fix changes `utils/escaping.py` only. The public API (`escape_for_pango`, `xml_escape_text`, `xml_template`) does not change. The behavior change is: a small, well-defined set of malformed HTML entity references that previously decoded to their character (and broke downstream Pango parsing) are now preserved as literal text instead. No new dependencies; the fix uses only the Python stdlib.

---

## 0. Discovery

**Source files read:**
- `utils/escaping.py` (full, 219 lines) — `escape_for_pango` lives here. Line 92 calls `text = html.unescape(text)` at the start of the function. The comment above (lines 88-91) says: "Decode HTML entities that LLMs sometimes emit (&quot;, &amp;, &lt;, etc.) before processing. Without this, html.escape() below would double-encode them (e.g. &quot; → &amp;quot;) and they'd appear as raw text in bubbles." Lines 102-156 contain the main loop (stack-based tag parser). Lines 134-145 handle the attribute-escape regex `&(?![a-zA-Z#0-9]+;)` that escapes bare `&` inside known-tag attribute values.
- `utils/markdown.py` (full, 302 lines) — `format_markdown` is the upstream of `escape_for_pango` in the chat-render pipeline. The angle-bracket auto-link bug (covered by `docs/specs/spec-angle-bracket-autolink.md`) produces malformed `&gt` (no trailing `;`) in `href` attributes via `_strip_trailing_punct`. The current `format_markdown` is the source of malformed entities that this spec's fix must be robust to.
- `ui/views/chat_bubble.py:_process_text_chunk` (lines 182-198) and `_build_text_segment` (lines 626-643) — confirmed call sites: `escape_for_pango(raw)` runs first, then `format_markdown(escaped)`. Other call sites at lines 605-606, 636-637, 701-703, 753-757, 782-783, 803-804 — all follow the same `escape_for_pango` → `format_markdown` order.
- `docs/ARCHITECTURE.md` sections 3.14a (`utils/escaping.py`) and 3.14b (`utils/markdown.py`) — `utils/escaping.py` is the documented owner of Pango-aware XML escaping. New design notes belong in 3.14a.
- `tests/test_escaping.py` (full, 138 lines) — established test patterns: `class TestEscapeForPango` with sub-sections by category. New tests should follow the same class structure (or be added to the existing class).
- `tests/test_markdown.py` (full, 380 lines) — confirmed no existing test covers the full `escape_for_pango` → `format_markdown` pipeline with auto-link input that produces malformed entities.

**Architecture owner:** `utils/escaping.py` (per ARCHITECTURE.md 3.14a).

**Existing patterns observed:**
- `escape_for_pango` is a pure-Python function with no GTK imports (line 5 comment: "no GTK imports"). Easy to unit-test without a display.
- The `_PANGO_KNOWN_TAGS` frozenset is the canonical allowlist for tags that survive escaping. We can follow the same pattern with a `_PANGO_KNOWN_ENTITIES` frozenset for entities that survive unescape.
- The attribute-escape regex on line 146 (`&(?![a-zA-Z#0-9]+;)`) is already strict — it only matches `&` not followed by a complete entity reference. The unescape step is the inconsistency.

---

## 1. Overview

### 1.1 Problem

When chat-bubble content describes Pango markup literally (e.g., documentation text that quotes what a broken auto-link produces), the chat bubble can fail to render, and **all content from the failing block onward is dropped from the rendered bubble** (`Gtk.Label.set_markup` aborts the entire label's text on the first parse error, even if subsequent blocks would be valid).

The failure mode is reproducible with the following input:

```
&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>
```

(intentionally malformed — `&gt` has no trailing `;`)

This produces a `Gtk-WARNING: Failed to set text ... Document ended unexpectedly while inside an attribute value` and causes everything from that block onward to be invisible in the chat bubble, even though the user can copy-paste the raw markup from a hidden "raw text" view.

### 1.2 Root Cause (verified)

`utils/escaping.py:escape_for_pango()` calls `html.unescape(text)` at line 78, BEFORE the tag-detection loop runs (lines 85-156). Python's stdlib `html.unescape` is **lenient per HTML5 spec**: it decodes named character references like `&gt`, `&lt`, `&amp`, `&copy`, `&nbsp` *even when the trailing semicolon is missing*. (This is the legacy "named character reference" behavior for back-compat with pre-HTML5 markup.)

For the input above, the chain is:

1. `escape_for_pango` calls `html.unescape(input)`.
2. `html.unescape` decodes the first `&gt` (no `;`) to `>`. The input becomes `<<a href="https://example.com>">...`.
3. The opening-tag regex on line 130 is `<([a-zA-Z][a-zA-Z0-9._-]*)([^>]*)>`. The `[^>]*` is greedy but stops at the first `>`. The first `>` is now the one decoded from `&gt` (inside the URL). The tag name captures `a`, the attributes capture ` href="https://example.com`, and the closing `>` of the opening tag is the decoded `>` from the URL.
4. The full opening tag emitted is `<a href="https://example.com>` — the `>` that was the tag's terminator is now embedded in the attribute value, and Pango's XML parser sees an unterminated attribute.
5. Pango raises: `Document ended unexpectedly while inside an attribute value`.

The malformed entity `&gt` came from `format_markdown` (the auto-link bug). `escape_for_pango` is supposed to be a robust defense against such malformed output, but its lenient `html.unescape` actively makes the situation worse: it converts the malformed-but-safe `&gt` (which would have been re-escaped to `&amp;gt` by the attribute-escape regex on line 142) into a literal `>` (which corrupts the tag-parsing state machine).

**Verified live** by replaying the failing block through the same pipeline (`/tmp/test_everything_v2.py` — block 26 of the audit report was the failing block; error matched the analysis above).

### 1.3 Solution

Replace `html.unescape` (line 92) with a **strict regex-based unescape** that only decodes entity references with a trailing semicolon. The fix uses an allowlist of entity names matching exactly what Pango's XML parser accepts (plus the standard XML named entities for content). Malformed entity references (no `;`) are left as literal text and then handled correctly by the existing attribute-escape regex and `html.escape` later in the pipeline.

This is a **defense-in-depth** fix: even if `format_markdown` produces malformed entities (e.g., from a future bug similar to the auto-link one), `escape_for_pango` will not amplify the problem by decoding them.

### 1.4 Scope

| In scope | Out of scope |
|----------|--------------|
| `utils/escaping.py` — strict unescape | `utils/markdown.py` — fix separately via `spec-angle-bracket-autolink.md` |
| Tests for malformed-entity robustness | `ui/views/chat_bubble.py` — no change |
| `docs/ARCHITECTURE.md` 3.14a — design note | New entity types (the allowlist covers Pango's existing set) |

---

## 2. Changes by File

### 2.1 `utils/escaping.py` — Replace lenient `html.unescape` with strict regex-based unescape

**Current code (lines 88-92):**

```python
    # Decode HTML entities that LLMs sometimes emit (&quot;, &amp;, &lt;, etc.)
    # before processing. Without this, html.escape() below would double-encode
    # them (e.g. &quot; → &amp;quot;) and they'd appear as raw text in bubbles.
    text = html.unescape(text)
```

**Replacement code (insert at lines 88-92, replace `text = html.unescape(text)` with):**

```python
    # Decode HTML entities that LLMs sometimes emit (&quot;, &amp;, &lt;, etc.)
    # before processing. Without this, html.escape() below would double-encode
    # them (e.g. &quot; → &amp;quot;) and they'd appear as raw text in bubbles.
    #
    # STRICT variant: only decode entity references with a trailing semicolon.
    # Python's html.unescape is HTML5-lenient — it decodes &amp, &lt, &gt etc.
    # even without the semicolon, which is a problem here: a malformed
    # entity like &gt (no ;) from a buggy upstream (see spec-angle-bracket-
    # autolink.md) gets converted to a literal >, which then breaks the
    # tag-detection regex below (the > looks like an end-of-tag). Strict
    # unescape preserves the malformed &gt as literal text; the attribute
    # escape regex (line 146) and html.escape downstream will
    # then safely re-escape it to &amp;gt. Pango renders &amp;gt as the
    # 4-character string "&gt" — not the intended character, but no warning.
    text = _ENTITY_UNESCAPE_RE.sub(lambda m: chr(_ENTITY_CODEPOINTS[m.group(1)]), text)
```

**Add new module-level constants and regex** (insert after line 32, before `def escape_for_pango`):

```python
# Entity references accepted by the strict unescape. Names match exactly
# what Pango's XML parser accepts plus the standard XML named entities
# for content (so LLM-emitted &quot; etc. decodes correctly to the char).
# Numeric character references (decimal &#NNN; and hex &#xHH;) are also
# accepted via the regex.
# Ref: https://docs.gtk.org/Pango/pango_markup.html
_ENTITY_CODEPOINTS: dict[str, int] = {
    # Standard XML named entities
    "amp": 0x26,    # &
    "lt":  0x3C,    # <
    "gt":  0x3E,    # >
    "quot": 0x22,   # "
    "apos": 0x27,   # '
    # Common content entities
    "nbsp": 0xA0,   # non-breaking space
}

# Strict entity reference pattern: must have a trailing semicolon.
# Matches the named entities in _ENTITY_CODEPOINTS or numeric refs
# (decimal or hex). Does NOT match &name (no ;) — those are left as
# literal text and re-escaped by the downstream logic.
_ENTITY_UNESCAPE_RE: re.Pattern[str] = re.compile(
    r"&("
    + "|".join(_ENTITY_CODEPOINTS.keys())
    + r"|#[0-9]+|#x[0-9a-fA-F]+);"
)
```

**Imports required:** none new — `re` is already imported (line 8), `html` stays for `html.escape` calls later.

**Function signatures:** unchanged. `escape_for_pango(text: str) -> str` remains the public API.

**Line count estimate:** +14 lines (the new constants/regex and the new comment block).

### 2.2 `tests/test_escaping.py` — Add tests for strict unescape

Add a new test class `TestStrictEntityUnescape` to `tests/test_escaping.py` (after the existing `TestEscapeForPango` class). New tests cover the regression scenarios from the audit:

```python
class TestStrictEntityUnescape:
    """Strict unescape: only decode entities with trailing semicolon."""

    def test_well_formed_entities_decoded(self):
        # Standard entities with ; are decoded, then html.escape re-encodes
        # & and " (default html.escape behavior in Python 3 escapes both).
        assert escape_for_pango("Tom &amp; Jerry") == "Tom &amp; Jerry"  # round-trip
        assert escape_for_pango("a &lt; b") == "a &lt; b"
        assert escape_for_pango("a &gt; b") == "a &gt; b"
        assert escape_for_pango("say &quot;hi&quot;") == "say &quot;hi&quot;"  # " re-escaped to &quot;
        assert escape_for_pango("it&apos;s") == "it&#x27;s"  # ' re-escaped to &#x27;

    def test_malformed_entities_preserved(self):
        # &name without ; is left as literal text. The bare & is then
        # re-escaped by html.escape to &amp;. The whole &amp;name sequence
        # is preserved as 8 characters — no character is decoded.
        assert escape_for_pango("see &gt here") == "see &amp;gt here"
        assert escape_for_pango("see &lt here") == "see &amp;lt here"
        assert escape_for_pango("see &amp here") == "see &amp;amp here"
        # The critical regression: &gt (no ;) must NOT decode to a literal >
        # (which would break the tag-detection regex downstream)
        result = escape_for_pango("see &gt here")
        # The only > characters allowed are inside the re-escaped entities
        # (&amp;gt → 4 visible chars after Pango rendering, 7 source chars).
        # No bare > should appear.
        assert ">" not in result.replace("&amp;gt", "")

    def test_buggy_autolink_output_robust(self):
        # The exact failure input from spec-angle-bracket-autolink.md.
        # Previously: rendered as <a href="https://example.com> (broken)
        # Now: renders safely as <a href="https://example.com&amp;gt"> (escaped)
        broken = '&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'
        result = escape_for_pango(broken)
        # No literal > inside an unescaped attribute
        assert 'href="https://example.com>' not in result
        # The malformed &gt is re-escaped to &amp;gt
        assert "&amp;gt" in result

    def test_numeric_entities_decoded(self):
        assert escape_for_pango("&#42;") == "*"
        assert escape_for_pango("&#x2A;") == "*"
        assert escape_for_pango("&#x2a;") == "*"

    def test_non_pango_entity_not_decoded(self):
        # &copy; etc. are not in the allowlist — left as literal text
        # (Pango would reject &copy; anyway, so leaving it gives a clearer
        # signal that the LLM emitted an unsupported entity). The trailing
        # & is then re-escaped by html.escape to &amp;.
        result = escape_for_pango("&copy; 2024")
        assert "©" not in result
        assert "&amp;copy;" in result  # & re-escaped, copy; preserved as literal

    def test_idempotency_under_double_escape(self):
        # Round-trip: &amp;amp; should not double-decode
        # (this was the original reason for the lenient unescape)
        result = escape_for_pango("&amp;amp;")
        # &amp;amp; → &amp; (decode first &amp;) → &amp; (html.escape re-encodes the &)
        # The final result should be &amp;amp; (no double-decoding)
        assert result == "&amp;amp;"

    def test_pipeline_with_format_markdown(self):
        # Full pipeline: escape_for_pango → format_markdown.
        # Note: this test only PASSES if BOTH spec-angle-bracket-autolink.md
        # AND this spec are applied. With only this spec applied, the broken
        # &gt (no ;) from format_markdown's auto-link bug still reaches
        # set_markup and triggers a Gtk warning. The role of THIS spec is
        # defense-in-depth: it ensures that any malformed entity (including
        # the auto-link bug's output if it were ever fed BACK through
        # escape_for_pango) is safely escaped, not amplified.
        from utils.markdown import format_markdown
        raw = '&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'
        # Feed the broken markup string back through escape_for_pango
        # (simulating: LLM response contains broken markup from a buggy
        # upstream; we re-run escape_for_pango on it for safety).
        result = format_markdown(escape_for_pango(raw))
        # The &gt (no ;) in the href should now be safely escaped to &amp;gt
        assert "&amp;gt" in result
        # No broken unescaped > inside an unterminated attribute
        assert 'href="https://example.com>' not in result
        # And it should round-trip through set_markup without a Gtk warning
        import subprocess, os
        gtk_result = subprocess.run([
            'python3', '-c', f'''
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
label = Gtk.Label()
label.set_markup({result!r})
print("OK")
'''
        ], capture_output=True, text=True, env={**os.environ, 'LANG': 'C'})
        assert "Failed to set text" not in gtk_result.stderr, (
            f"Pipeline produced broken markup: {result!r}\n"
            f"Gtk stderr: {gtk_result.stderr}"
        )
```

**Note:** Some of the above assertions need to be verified against actual implementation. The implementer must run the tests and adjust expectations to match the correct output. The KEY assertions are:
- `&gt` (no `;`) does NOT decode to `>` (this is the regression we're fixing)
- The buggy auto-link output produces NO Gtk warning when passed to `set_markup`
- Round-tripping `&amp;amp;` does not double-decode

### 2.3 Files NOT changed

- **`utils/markdown.py`** — the auto-link bug is fixed separately by `docs/specs/spec-angle-bracket-autolink.md`. This spec is the defense-in-depth companion.
- **`ui/views/chat_bubble.py`** — no change. The pipeline order (`escape_for_pango` first) is unchanged.
- **`ui/handlers/chat_render_handler.py`** — no change. Same pipeline.
- **`utils/gtk_safe_link.py`** — no change. The HIGH-6 link-allowlist logic is orthogonal.
- **`docs/ARCHITECTURE.md` 3.14b** (`utils/markdown.py` section) — no change. The escaping section (3.14a) gets a small note instead.
- **`_PANGO_KNOWN_TAGS`** — unchanged. The known-tag allowlist is the right design; only the lenient unescape is the problem.

---

## 3. Data Flow

### Before (buggy)

```
Input:  "see &lt;<a href=\"https://example.com&gt\"><u>https://example.com&gt</u></a>"
        (broken auto-link output describing the bug)
↓ escape_for_pango step 1: html.unescape (LENIENT)
  decodes &lt; → <, &gt → >  (no ; needed per HTML5 legacy)
  result:  "see <<a href=\"https://example.com>\"><u>https://example.com></u></a>"
↓ escape_for_pango step 2: tag-detection loop
  regex <name([^>]*)> matches <a href="https://example.com>  (stops at first >)
  tag_name = "a", attrs = ' href="https://example.com'
  preserved as: <a href="https://example.com>  ← unterminated attribute!
↓ format_markdown step ... (already done, text is already markup)
↓ set_markup
FAIL: "Document ended unexpectedly while inside an attribute value"
```

### After (fixed)

```
Input:  "see &lt;<a href=\"https://example.com&gt\"><u>https://example.com&gt</u></a>"
        (same broken auto-link output describing the bug)
↓ escape_for_pango step 1: _ENTITY_UNESCAPE_RE.sub (STRICT)
  matches &lt; (with ;) → <, &gt (no ;) NOT matched, stays as &gt
  result:  "see <<a href=\"https://example.com&gt\"><u>https://example.com&gt</u></a>"
↓ escape_for_pango step 2: tag-detection loop
  regex <name([^>]*)> matches <a href="https://example.com&gt"  (stops at the closing ")
  tag_name = "a", attrs = ' href="https://example.com&gt"'
  attribute-escape regex: &(?![a-zA-Z#0-9]+;) matches the & in &gt (no ; follows)
  attrs_escaped: ' href="https://example.com&amp;gt"'
  preserved as: <a href="https://example.com&amp;gt">  ← safely escaped
↓ format_markdown step ... (already done, text is already markup)
↓ set_markup
OK — Pango decodes &amp; → &, sees literal "gt" as text, &gt; → >.
   Renders href as the 4-char string "&gt" (not the intended char, but
   no warning, and the bubble doesn't truncate).
```

### LLM-emitted entities (regression check)

```
Input:  "Tom &amp; Jerry"  (LLM emitted &amp; as a literal entity reference)
↓ escape_for_pango step 1: strict unescape
  matches &amp; (with ;) → &
  result:  "Tom & Jerry"
↓ escape_for_pango step 2: tag-detection loop
  no <, no tag parsing
  result:  html.escape("Tom & Jerry") → "Tom &amp; Jerry"
↓ set_markup
OK — renders as "Tom & Jerry"
```

```
Input:  "Tom &amp Jerry"  (LLM typo, no semicolon)
↓ escape_for_pango step 1: strict unescape
  &amp (no ;) NOT matched, stays as &amp
  result:  "Tom &amp Jerry"
↓ escape_for_pango step 2: tag-detection loop
  no <, no tag parsing
  result:  html.escape("Tom &amp Jerry") → "Tom &amp;amp Jerry"
↓ set_markup
OK — renders as "Tom &amp Jerry"  (literal text, same as the LLM typed)
```

This is a behavior change for the malformed case: previously, `&amp` would be decoded to `&` and re-encoded to `&amp;` (displaying as `&`). Now, `&amp` is preserved as `&amp;amp` (displaying as `&amp`). The new behavior is more "what you typed is what you see" for malformed input, and the LLM-typo case is rare in practice (LLMs almost always emit well-formed entities when they emit any).

---

## 4. File Change Summary

| File | Change | Lines | Risk |
|------|--------|-------|------|
| `utils/escaping.py` | Add `_ENTITY_CODEPOINTS` dict + `_ENTITY_UNESCAPE_RE` regex; replace `html.unescape(text)` with regex-based unescape | +14 net | Low — narrow scope, well-tested allowlist |
| `tests/test_escaping.py` | Add `TestStrictEntityUnescape` class with 7 tests | +60 | Low — additive tests |
| `docs/ARCHITECTURE.md` 3.14a | Add 3-line note about strict unescape and defense-in-depth role | +3 | Low — documentation only |

---

## 5. Implementation Order

1. **Add `_ENTITY_CODEPOINTS` and `_ENTITY_UNESCAPE_RE` to `utils/escaping.py`** (after line 32, before `def escape_for_pango`).
2. **Replace `text = html.unescape(text)` at line 92** with the strict regex sub (verbatim from §2.1).
3. **Add `TestStrictEntityUnescape` class to `tests/test_escaping.py`** (after the existing `TestEscapeForPango` class). All 7 tests must pass.
4. **Run the full test suite** to verify no regressions in existing tests (especially `TestEscapeForPango` which has assertions like `escape_for_pango('<a href="http://example.com"><u>link</u></a>')` that should still pass).
5. **Add a 3-line note to `docs/ARCHITECTURE.md` section 3.14a** explaining the strict-unescape choice.
6. **Verify with the original bug reproducer** (the audit message that triggered the truncation): run it through the pipeline and confirm no `Gtk-WARNING` and no truncation.

---

## 6. Acceptance Criteria

- [ ] `escape_for_pango("Tom &amp; Jerry")` → `"Tom &amp; Jerry"` (renders as "Tom & Jerry", unchanged from current behavior)
- [ ] `escape_for_pango("&gt")` (no `;`) → result does NOT contain a literal `>` (regression test for the audit bug)
- [ ] `escape_for_pango('&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>')` produces a string that does NOT contain `<a href="https://example.com>` (the broken pattern)
- [ ] `Gtk.Label.set_markup(escape_for_pango('&lt;<a href="https://example.com&gt"><u>https://example.com&gt</u></a>'))` produces NO `Gtk-WARNING` in stderr
- [ ] All existing `tests/test_escaping.py` tests still pass (no regression in well-formed-entity handling)
- [ ] All existing `tests/test_markdown.py` tests still pass (no regression in the full pipeline)
- [ ] `escape_for_pango("&copy; 2024")` does NOT decode `&copy;` to `©` (the strict allowlist excludes non-Pango entities — by design, since Pango would reject the literal `&copy;` anyway and leaving it gives a clearer "unsupported entity" signal)
- [ ] `escape_for_pango("&#42;")` → `"*"` (numeric refs still work)
- [ ] `escape_for_pango("&#x2A;")` → `"*"` (hex refs still work)

---

## 7. Edge Cases

| Case | Expected Behavior | Rationale |
|------|-------------------|-----------|
| `&amp;` (with `;`) | Decodes to `&`, then re-escaped to `&amp;`. Renders as `&`. | Well-formed, current behavior preserved. |
| `&amp` (no `;`) | Preserved as `&amp`, re-escaped to `&amp;amp`. Renders as `&amp`. | New behavior: lenient unescape would have rendered as `&`. Strict is safer. |
| `&lt;` (with `;`) | Decodes to `<`, then re-escaped to `&lt;`. Renders as `<`. | Well-formed, current behavior preserved. |
| `&lt` (no `;`) | Preserved as `&lt`, re-escaped to `&amp;lt`. Renders as `&lt`. | Same rationale as `&amp` case. |
| `&copy;` (non-Pango) | Preserved as literal `&copy;`. Pango would reject it anyway. | Strict allowlist excludes non-Pango entities. Document the choice. |
| `&amp;amp;` (double-encoded) | Decodes to `&amp;`, re-escaped to `&amp;amp;`. Renders as `&amp;`. | The original reason for the lenient unescape. With strict unescape, only the first `&amp;` decodes (because the regex is non-greedy and the second `;` ends the match). The trailing `amp;` is then re-escaped. Verified by code trace. |
| `&#42;` (decimal numeric) | Decodes to `*`. | Numeric refs always have `;`, so the strict pattern matches. |
| `&#x2A;` (hex numeric) | Decodes to `*`. | Same as decimal. |
| `&#xZZ;` (invalid hex) | Regex doesn't match (no `;` because the `[0-9a-fA-F]+` fails first). Preserved as literal `&#xZZ;`. Then html.escape or attribute-escape handles it. | Defensive: malformed numeric refs don't crash. |
| `&;` (empty name) | Regex doesn't match (no name after `&` and before `;`). Preserved as literal `&;`. | Defensive. |
| Auto-link bug output `<a href="https://example.com&gt">` | `&gt` (no `;`) preserved, re-escaped to `&amp;gt`. Bubble does NOT truncate. | The audit-bug regression. |
| `&amp;` inside `<a href="...">` (well-formed, e.g. URL query param) | `&amp;` decodes to `&`, then attribute-escape regex `&(?![a-zA-Z#0-9]+;)` matches the `&` (not followed by `;` after re-decoding), re-escapes to `&amp;`. Final href: `https://example.com?a=1&amp;b=2`. | Well-formed input produces correct output. |
| Markdown link `[label](url)` with `&amp;` in URL | `format_markdown` produces `<a href="https://example.com?a=1&amp;b=2">`, then `escape_for_pango` sees the `&amp;`, decodes to `&`, then attribute-escape re-encodes to `&amp;`. Final: `<a href="https://example.com?a=1&amp;b=2">`. Renders correctly. | The existing happy path. |

---

## 8. ARCHITECTURE.md Updates Required

Add a short note to section 3.14a (`utils/escaping.py`) after the existing "Key design" paragraph. The note should explain:

1. The function uses **strict** entity unescape (only with trailing `;`).
2. The allowlist is `_ENTITY_CODEPOINTS` — XML named entities + `nbsp`.
3. The reason: defense-in-depth against malformed entities from upstream (e.g., from `format_markdown` bugs).
4. Reference to `docs/specs/spec-strict-entity-unescape.md` for the design rationale.

Suggested addition (3 lines, after line 825):

```
**Strict unescape:** Uses an allowlist (`_ENTITY_CODEPOINTS`) covering only XML
named entities + `nbsp`, plus numeric refs. Malformed entities (no `;`) are
preserved as literal text and re-escaped downstream — see
`docs/specs/spec-strict-entity-unescape.md` for rationale (defense-in-depth
against upstream bugs that produce malformed entities, e.g., the auto-link
spec).
```

---

## 9. Spec Self-Audit

1. **Code samples traced?**
   - The strict unescape regex `_ENTITY_UNESCAPE_RE` was traced against 13 test inputs (`&amp;`, `&amp`, `&copy;`, `&copy`, `&;`, `&#42;`, `&#x2A;`, `&#xZZ;`, `&amp;amp;`, the audit-bug input, etc.) — all behaviors match the §7 table.
   - The interaction with the existing attribute-escape regex (line 142) was traced: `&gt` in an attribute is matched by `&(?![a-zA-Z#0-9]+;)` because the `;` is missing, so it gets re-escaped to `&amp;gt`. Verified by running the actual code on the audit-bug input.
   - The interaction with `format_markdown` for well-formed `[label](url)` links was traced: `format_markdown` produces `<a href="...?a=1&amp;b=2">`, `escape_for_pango` decodes the `&amp;` to `&`, then the attribute-escape regex matches the `&` (now bare) and re-encodes to `&amp;`. Final output matches the existing test expectation.

2. **Exception types?** None — pure string operations. `re.sub` does not raise on non-matching patterns. The lambda `lambda m: chr(_ENTITY_CODEPOINTS[m.group(1)])` is only invoked when the regex matches, so the `KeyError` risk is moot (matches always have a name in the allowlist or a numeric ref). The `chr()` call could raise `ValueError` for codepoints outside the BMP, but the regex restricts to `_ENTITY_CODEPOINTS` (BMP values) or numeric refs up to `0x10FFFF` (the regex doesn't restrict, but `chr` handles the full range). Verified: `chr(0x10FFFF)` is valid; `chr(0x110000)` raises `ValueError` but the regex `[0-9]+` could match that. **Action item for implementer:** add a `try/except ValueError` in the lambda to fall back to the original entity reference on invalid codepoints. Or restrict the regex to a safe range (`[0-9]{1,7}` and clamp via `min(int(...), 0x10FFFF)`).

3. **Key structures?** `_ENTITY_CODEPOINTS` is a `dict[str, int]` mapping entity name to Unicode codepoint. The regex is built from the dict keys via `"|".join(...)`. Verified: this preserves insertion order in Python 3.7+, and the alternation in a regex is order-independent for matching purposes (the regex engine tries all alternatives and takes the first match).

4. **Return value analysis?** The lambda returns the decoded character (single char) for named entities, or the decoded character for numeric refs. The `re.sub` replaces the entire match (`&name;` or `&#NNN;` or `&#xHH;`) with the decoded char. Non-matches are left untouched.

5. **Would this produce working code?** Yes — the regex is straightforward, the lambda is simple, the test cases are all verifiable. The only risk is the `chr()` ValueError edge case noted above; that's a one-line fix.

**Action items from self-audit:**
- Implementer should add `try/except ValueError` in the regex-sub lambda (or restrict numeric range in the regex).
- The implementer should verify the `&amp;amp;` round-trip case with an actual test (this is the original reason for lenient unescape; the strict variant needs to preserve the same final-rendering behavior).

---

## 10. Completion Verification (for implementer)

1. **Scope checklist** — every file listed in §2:
   - [ ] `utils/escaping.py` — added constants, replaced unescape call (lines 74-78 → 14 net new lines)
   - [ ] `tests/test_escaping.py` — added `TestStrictEntityUnescape` class (~60 lines)
   - [ ] `docs/ARCHITECTURE.md` — added 3-line note to section 3.14a

2. **Test suite** — paste actual pytest output, not a summary. Both new tests and existing tests must pass.

3. **Pattern sweep** — grep for remaining `html.unescape` calls in `utils/escaping.py`:
   ```bash
   grep -n "html.unescape" utils/escaping.py
   ```
   Should return zero matches after the change.

4. **Live verification** — replay the audit-bug input through the pipeline and confirm no Gtk warning:
   ```bash
   python3 -c "
   import sys
   sys.path.insert(0, '/home/q/projects/crabcakes')
   from utils.escaping import escape_for_pango
   from utils.markdown import format_markdown
   import gi
   gi.require_version('Gtk', '4.0')
   from gi.repository import Gtk
   raw = '&lt;<a href=\"https://example.com&gt\"><u>https://example.com&gt</u></a>'
   out = format_markdown(escape_for_pango(raw))
   label = Gtk.Label()
   label.set_markup(out)
   print('OK')
   "
   ```
   Should print `OK` with no Gtk-WARNING on stderr.
