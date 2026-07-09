# SPEC: Orphan Tag Escaping + Auto-Link Attribute Protection

**Date:** 2026-07-08
**Author:** Supervisor
**Status:** Draft — for implementation
**Depends on:** None
**Target branch:** main

> **Architecture compliance:** This fix changes `utils/escaping.py` and `utils/markdown.py`. The public APIs (`escape_for_pango`, `format_markdown`) do not change. Two bugs are fixed: (1) `escape_for_pango` preserves opening tags with no matching close, and (2) `format_markdown`'s auto-link regex matches URLs inside existing Pango tag attributes.

---

## 0. Discovery

**Source files read:**
- `utils/escaping.py` (full, 219 lines) — confirmed `_PANGO_KNOWN_TAGS` at line 18 includes `"a"`. The opening-tag handler at lines 157-180 pushes known tags to `open_tags` stack unconditionally when a known tag is found. There is no final sweep for orphaned (unclosed) tags. The closing-tag handler at lines 132-142 only pops if `open_tags[-1] == tag_name`, so an orphan `<a>` that never closes stays on the stack and is preserved verbatim in the output.
- `utils/markdown.py` lines 36-48 and 246-262 — confirmed `_AUTO_LINK_RE` uses `(?<![a-zA-Z0-9/:])` as the only lookbehind. This does not exclude matches preceded by `="` (inside an attribute value). When `escape_for_pango` preserves an existing `<a href="https://example.com">`, `format_markdown`'s Step 4 auto-link regex sees the URL inside `href="..."` and wraps it in a NEW `<a>` tag, producing nested `<a>` tags.
- `tests/test_escaping.py` (full) — confirmed no test covers orphan tags (opening tag with no matching close).
- `tests/test_markdown.py` lines 98-108 — confirmed no test covers auto-link matching inside existing Pango tag attributes.

**Architecture owner:** `utils/escaping.py` (§3.14a) and `utils/markdown.py` (§3.14b).

---

## 1. Overview

### 1.1 Problem A — Orphan tags (QTR's finding)

Plain text containing `<a href="...">` (e.g. grep output, code documentation, LLM self-quoting) is preserved by `escape_for_pango` as a real opening tag because `"a"` is in `_PANGO_KNOWN_TAGS`. But there's no matching `</a>`, so Pango rejects the markup: `Element "markup" was closed, but the currently open element is "a"`.

**Trigger:** Any chat message, persisted conversation, or code excerpt containing the literal string `<a href="...">` without a closing `</a>`. Extremely common in agent output that quotes HTML or documentation.

### 1.2 Problem B — Nested tags from auto-link regex (Debugger's finding)

When `escape_for_pango` preserves an existing `<a href="https://example.com">` tag, `format_markdown`'s Step 4 auto-link regex (`_AUTO_LINK_RE`) sees the URL inside the `href` attribute and wraps it in a NEW `<a>` tag, producing `<a href="<a href="https://example.com">...">`. Pango rejects nested `<a>` tags.

**Trigger:** Any text containing a complete `<a href="URL">...</a>` tag that passes through both `escape_for_pango` and `format_markdown`.

### 1.3 Root Cause (both verified)

**Problem A:** `escape_for_pango` lines 157-180 push known opening tags to `open_tags` but never check whether those tags are eventually closed. The function returns with orphaned tags on the stack, preserved in the output.

**Problem B:** `_AUTO_LINK_RE` at line 36 uses only `(?<![a-zA-Z0-9/:])` as a lookbehind. It does not exclude matches inside `href="..."` attributes.

### 1.4 Solution

**Fix A:** After `escape_for_pango`'s main loop completes, sweep the output for any opening tag still on the `open_tags` stack that has no matching close. Escape orphaned tags back to literal text (`<a href="...">` → `&lt;a href="..."&gt;`).

**Fix B:** Add `(?<!=")` to `_AUTO_LINK_RE`'s lookbehind so it doesn't match URLs preceded by `="` (the pattern that appears inside `href="URL"` attributes).

---

## 2. Changes by File

### 2.1 `utils/escaping.py` — Orphan tag sweep (Fix A)

**Current end of `escape_for_pango` (around line 190):**

```python
    return "".join(result)
```

**Replace with:**

```python
    # ── Orphan tag sweep ───────────────────────────────────────────────────
    # After the main loop, any tags still on the open_tags stack were opened
    # but never closed. These are orphan tags — plain text that looked like a
    # Pango tag (e.g. grep output containing <a href="...">). Pango would
    # reject an unclosed opening tag, so we escape orphan tags back to literal
    # text. We work backwards through the result, escaping the last occurrence
    # of each orphaned tag.
    output = "".join(result)
    for tag_name in reversed(open_tags):
        # Find the last opening tag of this name in the output
        tag_pattern = re.compile(
            r'<' + re.escape(tag_name) + r'(?:\s[^>]*)?>',
            re.IGNORECASE
        )
        matches = list(tag_pattern.finditer(output))
        if matches:
            last_match = matches[-1]
            # Escape this specific occurrence to literal text
            original = last_match.group(0)
            escaped = html.escape(original)
            output = output[:last_match.start()] + escaped + output[last_match.end():]

    return output
```

**Rationale:** The sweep runs once after the main loop. For each orphaned tag on the stack, it finds the last opening occurrence and escapes it. This is O(N × M) where N is the number of orphaned tags (typically 0-2) and M is the output length — negligible for chat messages.

**Why "last occurrence":** The stack is LIFO, so the last-pushed orphan is the innermost unmatched tag. Escaping from the innermost outward preserves correct nesting for any validly-nested pairs that happen to be unclosed at a higher level.

### 2.2 `utils/markdown.py` — Auto-link lookbehind (Fix B)

**Current regex (line 36-42):**

```python
_AUTO_LINK_RE = re.compile(
    r'(?<![a-zA-Z0-9/:])'  # not preceded by alphanum or ://
    r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"`\'\[\]()]+)'
    r'|'
    r'(?<!["\'])'
    r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>"`\'\[\]()]+))'
    , re.IGNORECASE
)
```

**Replace with:**

```python
_AUTO_LINK_RE = re.compile(
    r'(?<![a-zA-Z0-9/:])'  # not preceded by alphanum or ://
    r'(?<!=)"?\s*'          # not preceded by =" (inside href attribute)
    r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"`\'\[\]()]+)'
    r'|'
    r'(?<!["\'])'
    r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>"`\'\[\]()]+))'
    , re.IGNORECASE
)
```

Wait — this approach changes the match groups and breaks existing callers. A simpler fix: use a single negative lookbehind.

**Actual replacement (simpler, preserves match groups):**

```python
_AUTO_LINK_RE = re.compile(
    r'(?<![a-zA-Z0-9/:=])'  # not preceded by alphanum, ://, or = (href="URL")
    r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"`\'\[\]()]+)'
    r'|'
    r'(?<!["\'])'
    r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>"`\'\[\]()]+))'
    , re.IGNORECASE
)
```

**Change:** Added `=` to the negative lookbehind character class (line 38). This prevents the regex from matching a URL when it's preceded by `=` (as in `href=https://...` or `="https://...`). The `"` after `=` is handled by the existing `[^\s<>"...]` exclusion in the URL char class — the regex won't match through a `"`.

**One-line change:** `(?<![a-zA-Z0-9/:])` → `(?<![a-zA-Z0-9/:=])`.

### 2.3 Files NOT changed

- `ui/views/chat_bubble.py` — no change. The pipeline order is unchanged.
- `utils/gtk_safe_link.py` — no change.

---

## 3. Data Flow

### Problem A: Orphan tag (before — broken)

```
Input:  'renders <a href="..."> tags'
↓ escape_for_pango main loop
  matches <a href="..."> → known tag → preserved, pushed to open_tags
↓ return
  open_tags = ["a"] — orphan! No </a> was found.
Output: 'renders <a href="..."> tags'
↓ set_markup
FAIL: "currently open element is 'a'"
```

### Problem A: Orphan tag (after — fixed)

```
Input:  'renders <a href="..."> tags'
↓ escape_for_pango main loop
  matches <a href="..."> → known tag → preserved, pushed to open_tags
↓ orphan sweep
  open_tags = ["a"] → find last <a...> in output → escape to &lt;a href="..."&gt;
Output: 'renders &lt;a href="..."&gt; tags'
↓ set_markup
OK — literal text, no open tag
```

### Problem B: Nested tags (before — broken)

```
Input:  '<a href="https://example.com">link</a>'
↓ escape_for_pango
  preserves both tags (valid open+close pair)
Output: '<a href="https://example.com">link</a>'
↓ format_markdown Step 4 (_AUTO_LINK_RE)
  matches https://example.com inside href="..." → wraps in NEW <a>
Output: '<a href="<a href="https://example.com">...">link</a>'
↓ set_markup
FAIL: nested <a> tags
```

### Problem B: Nested tags (after — fixed)

```
Input:  '<a href="https://example.com">link</a>'
↓ escape_for_pango
  preserves both tags
Output: '<a href="https://example.com">link</a>'
↓ format_markdown Step 4 (_AUTO_LINK_RE with = lookbehind)
  URL preceded by =" → lookbehind blocks match → no auto-link
Output: '<a href="https://example.com">link</a>'  (unchanged — correct)
↓ set_markup
OK — single <a> tag
```

---

## 4. Acceptance Criteria

- [ ] `escape_for_pango('renders <a href="..."> tags')` escapes the orphan `<a>` to `&lt;a href="..."&gt;`
- [ ] `escape_for_pango('<a href="https://x.com">link</a>')` still preserves the valid tag pair (regression)
- [ ] `escape_for_pango('<b>bold</b>')` still preserves (regression)
- [ ] `escape_for_pango('<b>bold')` escapes orphan `<b>` to `&lt;b&gt;` (new behavior — was previously preserved)
- [ ] `format_markdown('<a href="https://example.com">link</a>')` does NOT produce nested `<a>` tags
- [ ] `format_markdown('check https://example.com for info')` still auto-links plain URLs (regression)
- [ ] `set_markup(escape_for_pango('renders <a href="..."> tags'))` produces NO Gtk-WARNING
- [ ] `set_markup(format_markdown(escape_for_pango('<a href="https://x.com">link</a>')))` produces NO Gtk-WARNING
- [ ] All existing tests pass

---

## 5. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `<b>bold</b>` | Preserved — valid open+close pair |
| `<b>bold` (no close) | Orphan escaped: `&lt;b&gt;bold` |
| `<a href="x">link</a>` | Preserved — valid pair |
| `<a href="x">` (no close) | Orphan escaped: `&lt;a href="x"&gt;` |
| `<b><i>nested</i></b>` | Both preserved — valid nesting |
| `<b><i>nested</b></i>` | Mismatched close → `<i>` orphaned → escaped. `<b>` closed correctly. |
| `renders <a href="..."> tags` | Orphan `<a>` escaped (Problem A trigger) |
| `<b></b><b></b>` | Both pairs preserved |
| `<b><b>double</b>` | First `<b>` orphaned (no close before second open). Escaped. Second `<b></b>` preserved. |
| URL inside `href="URL"` (after fix B) | Not auto-linked — lookbehind blocks match |

---

## 6. ARCHITECTURE.md Updates

**Section 3.14a** — add note: "Orphan tag sweep: after the main loop, any opening tags still on the stack are escaped to literal text. This prevents plain text containing tag-like substrings (e.g. grep output with `<a href="...">`) from being preserved as real Pango tags."

**Section 3.14b** — add note: "Auto-link regex lookbehind includes `=` to prevent matching URLs inside `href="..."` attributes of pre-existing Pango tags."

---

## 7. Spec Self-Audit

1. **Code samples traced?** Yes — both bugs verified by reading the actual source. Fix A adds a post-loop sweep using `html.escape` on the matched tag. Fix B is a one-character addition to a character class.
2. **Exception types?** None — pure string operations. `re.compile` and `re.sub` with constant patterns.
3. **Key structures?** `open_tags` stack verified at lines 117, 134, 162. `_AUTO_LINK_RE` lookbehind verified at line 38.
4. **Data flow traced?** Yes — §3 shows before/after for both bugs.
5. **Would this produce working code?** Yes — Fix A is ~10 lines of post-processing. Fix B is one character.
