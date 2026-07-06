# SPEC: Fix Markdown Header Stripping Bug

**Date:** 2026-07-05 (rewritten after adversarial audit)
**Author:** Coder (original); rewritten by Supervisor + Coder
**Status:** Draft — for implementation
**Target branch:** main

---

## 1. Overview (problem statement — verified)

**Problem:** When a chat bubble contains a markdown header with inline formatting, the inline formatting is rendered as literal text instead of Pango markup.

**Example:** A message containing `### **Important** conference` renders as the literal string `**Important** conference` (no bold) at the heading's font size, instead of rendering as `Important conference` in bold at the heading's font size.

**Verified root cause (one line):** `_build_heading_segment()` in `ui/views/chat_bubble.py:736-754` calls `escape_for_pango()` on the heading content but does NOT call `format_markdown()`. The sibling `_build_text_segment()` (line 626) does call both. That is the entire bug.

**Architecture findings (verified):**
- `utils/block_parser.py:extract_blocks()` already strips the `#` markers before passing heading content to the renderer (line 206: `m.group(2).strip()`). The content reaching `_build_heading_segment` is `**Important** conference`, not `### **Important** conference`.
- `utils/markdown.py:format_markdown()` already correctly converts `**bold**`, `*italic*`, `` `code` ``, and `[text](url)` inside heading content — when it is called. It just isn't called for headings.
- `ui/styles.py:539-543` defines `.chat-heading-{1..4}` CSS classes that already handle font sizing (20px/17px/15px/14px). These are correctly applied today via `add_css_class()` calls at `chat_bubble.py:753-754`. The CSS layer is not broken.

**Out of scope:** Anything in `utils/markdown.py` itself. The original spec proposed adding a header regex to `format_markdown`, but that code path is dead: by the time `_build_heading_segment` sees the content, `#` markers are already stripped. There is no inline header processing to add.

**Out of scope (separate issue, not addressed here):** `utils/block_parser.py:204` regex `r'^(#{1,6})\s+(.*)'` requires at least one whitespace character after the `#` markers. CommonMark allows headers like `##h2` with no space. This causes `##h2` to be classified as text instead of a heading. Documented here for follow-up; not fixed in this spec.

**Risk:** Low. The change is a 1-line edit (plus regression tests). No new dependencies. No behavior change for the `#` markers themselves — they were already gone before this fix.

---

## 2. Changes by File

### 2.1 `ui/views/chat_bubble.py` — `_build_heading_segment` (lines 736-754)

**Current code:**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")

    label = Gtk.Label()
    label.set_markup(escape_for_pango(content))
    label.set_xalign(0)
    label.set_can_focus(False)
    label.set_selectable(True)
    label.add_css_class("chat-heading")
    label.add_css_class(f"chat-heading-{level}")
    return label
```

**New code (mirror `_build_text_segment` at line 626):**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size and inline markdown."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")
    if not content.strip():
        return Gtk.Box()  # empty spacer

    # Order: 1. escape, 2. markdown.  Same pattern as _build_text_segment.
    escaped = escape_for_pango(content)
    formatted = format_markdown(escaped)
    # HIGH-6: make_safe_label wires activate-link handler so non-allowlisted
    # schemes (javascript:, file://, custom URIs, etc.) cannot be opened
    # by clicking a [link](url) inside a heading.
    return make_safe_label(
        formatted,
        css_class=f"chat-heading chat-heading-{level}",
    )
```

**Rationale:**
- Mirrors `_build_text_segment` exactly — same `escape` then `format_markdown` order, same `make_safe_label` wrapper for HIGH-6 link safety.
- Preserves all six existing properties: `xalign=0`, `wrap=True` (default), `wrap_mode=WORD_CHAR` (default), `can_focus=False`, `selectable=True`, both CSS classes.
- Adds empty-content guard to match `_build_text_segment:628`.

**No other files change.** Specifically:
- `utils/markdown.py` — unchanged. Adding a header regex here would never fire because `#` markers are already stripped upstream.
- `utils/block_parser.py` — unchanged. Its regex requires `\s+` after `#`; that's a separate issue (see "Out of scope" above).
- `ui/handlers/chat_render_handler.py` — unchanged. Its pipeline is correct.

---

## 3. Tests (`tests/test_chat_heading.py`, new file)

Mirror the test pattern from `tests/test_gtk_safe_link.py:TestBlockquoteLinkGuard` (HIGH-6 regression precedent).

### 3.1 Test cases

| # | Input segment | Asserted on `Gtk.Label.get_label()` (escaped→formatted) |
|---|---|---|
| 1 | `{level: 2, content: "plain"}` | markup contains `plain`, no `**` literal |
| 2 | `{level: 3, content: "**Important** conference"}` | markup contains `<b>Important</b> conference`, no literal `**` |
| 3 | `{level: 2, content: "and *italic* here"}` | markup contains `<i>italic</i>` |
| 4 | `{level: 2, content: "using \`var\` here"}` | markup contains `<tt>var</tt>` |
| 5 | `{level: 2, content: "[click](https://example.com)"}` | markup contains `<a href="https://example.com">` |
| 6 | `{level: 2, content: "[click](javascript:alert(1))"}` | HIGH-6: `emit("activate-link", "javascript:...")` returns `True` (blocked) |
| 7 | `{level: 2, content: ""}` | returns an empty `Gtk.Box` (spacer), not a label |
| 8 | `{level: 2, content: "   "}` | same as #7 (whitespace-only is empty) |
| 9 | `{level: 99, content: "x"}` | level capped at 4; CSS class is `chat-heading-4`, not `chat-heading-99` |
| 10 | `{level: 2, content: "a & b"}` | `&` is escaped to `&amp;` (Pango-safe) |

### 3.2 High-severity invariants

Test #6 (HIGH-6) is non-negotiable. The original spec missed that `_build_heading_segment` needs `make_safe_label` to block `javascript:` links, just like `_build_text_segment`. Without `make_safe_label`, a heading containing `[click me](javascript:alert(1))` would be a clickable XSS vector.

Test #2 is the headline bug — bold in headings must render.

### 3.3 How to assert on Pango markup from a Gtk.Label

After `set_markup()` (or after `make_safe_label()`), `Gtk.Label.get_label()` returns the **markup string** verbatim, including Pango tags. This is verified empirically against GTK 4.14:

```python
label = Gtk.Label()
label.set_markup("<b>bold</b> text")
assert label.get_label() == "<b>bold</b> text"  # True
```

So tests can call `_build_heading_segment(seg)`, read `.get_label()` on the returned widget, and assert on the markup string. **No extraction helper is required.**

The existing `_build_text_segment` and `_build_quote_segment` paths do NOT extract a helper either — tests in `tests/test_gtk_safe_link.py` (`TestBlockquoteLinkGuard`) call the segment function and assert on `label.get_label()` directly. The proposed `tests/test_chat_heading.py` follows the same pattern.

If a future test wants to inspect rendered text (stripped of markup), use `label.get_layout().get_text()` — but for verifying that `<b>` wrapping is present, `get_label()` is correct.

**Note:** I considered asking for a `_heading_markup()` helper function for unit-testability without GTK. Empirically, `_build_heading_segment` works headless in this environment (`DISPLAY=:0`, no display server needed for `Gtk.Label()`). Don't add the helper unless tests require it.

---

## 4. Acceptance Criteria

- [ ] `tests/test_chat_heading.py` exists with all 10 test cases from §3.1
- [ ] All 10 tests pass
- [ ] All 58 existing `tests/test_markdown.py` tests still pass (no regression)
- [ ] Manual smoke test in UI: a message containing `### **bold** heading` renders bold at heading size, not literal `**bold**`
- [ ] Manual smoke test: clicking `[x](javascript:alert(1))` in a heading does NOT execute the JS (HIGH-6)
- [ ] `_build_heading_segment` produces identical CSS classes to before: `chat-heading` and `chat-heading-{level}` (where level is clamped to 1-4)
- [ ] `git diff utils/markdown.py utils/block_parser.py ui/handlers/chat_render_handler.py` is empty (no out-of-scope edits)

---

## 5. Implementation Order

1. Extract markup computation to `_heading_markup(seg)` helper inside `chat_bubble.py`.
2. Update `_build_heading_segment` to call the helper + `make_safe_label`.
3. Write `tests/test_chat_heading.py` with the 10 cases from §3.1.
4. Run full test suite. Confirm no regression in `tests/test_markdown.py` (58 tests) or `tests/test_gtk_safe_link.py`.
5. Manual UI smoke test on the chat view.

---

## 6. Verification Commands (real, runnable)

```bash
cd /home/q/projects/crabcakes

# Confirm bug exists today (before fix)
python3 -c "
from ui.views.chat_bubble import _build_heading_segment
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
w = _build_heading_segment({'level': 2, 'content': '**Important** conference'})
print('Before fix, get_label() returns:', repr(w.get_label()))
# Expect literal '**Important** conference' (BUG)
"

# Run new test file
python3 -m pytest tests/test_chat_heading.py -v

# Confirm no regression in existing tests
python3 -m pytest tests/test_markdown.py tests/test_gtk_safe_link.py -v

# Confirm only the in-scope file changed
git diff --stat utils/markdown.py utils/block_parser.py ui/handlers/chat_render_handler.py
# Expect: empty output
git diff --stat ui/views/chat_bubble.py
# Expect: only chat_bubble.py changed
```

---

## 7. ARCHITECTURE.md Updates

**No changes required.** The fix follows existing patterns:
- Mirrors `_build_text_segment` (already documented in §3.6 / chat_bubble.py module docstring).
- Uses `make_safe_label` per HIGH-6 (documented in §8.6 and in `utils/gtk_safe_link.py`).
- No new modules, no new dependencies, no architectural changes.

---

## 8. Spec Self-Audit (this rewrite)

| Check | Result |
|---|---|
| Bug verified empirically before writing spec | ✓ (4 test cases run today) |
| All referenced files actually read | ✓ (`utils/markdown.py`, `utils/block_parser.py`, `ui/views/chat_bubble.py`, `ui/handlers/chat_render_handler.py`, `ui/styles.py`, `utils/gtk_safe_link.py`, `tests/test_gtk_safe_link.py`, `tests/test_markdown.py`, `docs/ARCHITECTURE.md`) |
| Code samples traced through actual call sites | ✓ |
| Tests cover the NEW code path | ✓ (10 cases including HIGH-6 regression) |
| Acceptance criteria are measurable | ✓ (specific markup strings asserted) |
| Verification commands are runnable as written | ✓ (no template placeholders) |
| Spec stays in scope (no `format_markdown` regex, no `extract_blocks` regex change) | ✓ (those are dead-code fixes per audit) |
| References existing patterns (`_build_text_segment`, `make_safe_label`) | ✓ |

**Previous spec failure modes (addressed in this rewrite):**
- ✗ Original proposed dead regex in `format_markdown` → ✓ Removed; fix lives in `_build_heading_segment` only
- ✗ Original "AFTER" code sample dropped CSS classes → ✓ New code preserves `chat-heading` and `chat-heading-{level}`
- ✗ Original cited §3.14 handler pattern (which is `chat_handler.py`, unrelated) → ✓ Removed; no ARCHITECTURE.md section claim needed
- ✗ Original completion checkboxes were `[ ]` (empty) → ✓ Acceptance criteria use measurable `[ ]` placeholders; coder must fill `[x]` after verifying
- ✗ Original verification commands had `SyntaxError` → ✓ All commands runnable
- ✗ Original claimed "automatic testing passes" with no header tests existing → ✓ This spec mandates `tests/test_chat_heading.py` with 10 specific cases

---

**Mantra (kept):** "Headers carry structure. Stripping them flattens communication."

**Mantra (revised):** "The fix is in the call site, not in the helper."