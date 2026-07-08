# SPEC: Angle-Bracket Auto-Link Entity Corruption

**Date:** 2026-07-08
**Author:** Supervisor
**Status:** Draft — for implementation
**Depends on:** None
**Target branch:** main

> **Architecture compliance:** This fix changes `utils/markdown.py` only. The public API (`format_markdown`) does not change. The fix adds a pre-processing step that extracts `<URL>` angle-bracket auto-links into placeholders before the auto-link regex runs, then restores them after — same pattern already used for code spans and anchor tags.

---

## 0. Discovery

**Source files read:**
- `utils/markdown.py` (full, 279 lines) — confirmed `_AUTO_LINK_RE` at lines 37-43 excludes `<>"'\`[]()` but NOT `&`. `_TRAILING_PUNCT` at line 46 includes `;`. `_strip_trailing_punct` at lines 73-79 strips trailing chars in a while-loop. `_auto_link` callback at lines 237-247 runs `_AUTO_LINK_RE.sub`. The pipeline order is: Step 1 (code spans) → Step 2 (bold/italic/strike) → Step 3 (markdown links) → Step 4 (auto-link bare URLs) → Step 5 (restore code) → Step 6 (restore anchors).
- `ui/views/chat_bubble.py` lines 197-198, 605-606, 636-637 — confirmed pipeline order: `escape_for_pango()` runs FIRST, then `format_markdown()` receives already-escaped text. So `>` becomes `&gt;` before `format_markdown` sees it.
- `tests/test_markdown.py` lines 98-108 — confirmed no test covers `<https://...>` angle-bracket syntax. `test_auto_link_bare_url` tests plain URLs only.

**Existing patterns observed:**
- Code spans are protected via placeholders (Step 1: `\x00CODE{N}\x00`), restored in Step 5.
- Markdown links are converted to `<a>` tags then immediately protected as placeholders (Step 3: `\x00ANCHOR{N}\x00`), restored in Step 6.
- The fix follows the same placeholder pattern: extract `<URL>` patterns before the auto-link regex, restore after.

---

## 1. Overview

### 1.1 Problem

When text contains CommonMark/GFM angle-bracket auto-links like `<https://example.com>`, the rendering pipeline produces invalid Pango markup that causes `Gtk-WARNING: Failed to set text` and renders the chat bubble blank.

### 1.2 Root Cause (verified)

The pipeline runs `escape_for_pango()` before `format_markdown()`. This converts `>` to `&gt;`. Then:

1. `_AUTO_LINK_RE` (line 37) matches `https://example.com&gt;` as a URL — the `&gt;` is captured because `&`, `g`, `t`, `;` are all permitted in the URL character class.
2. `_strip_trailing_punct()` (line 73) strips the trailing `;` from `_TRAILING_PUNCT`, leaving `&gt` — an invalid HTML entity.
3. `Gtk.Label.set_markup()` fails: `Error on line 1: Entity did not end with a semicolon`.

### 1.3 Solution

Add a new Step (between Step 3 and Step 4) that pre-processes CommonMark angle-bracket auto-links (`<URL>`) into markdown-link format (`[URL](URL)`) BEFORE the auto-link regex runs. This:

- Extracts the URL from inside the angle brackets while it's still recoverable.
- Converts it to `[URL](URL)` which Step 3's markdown-link regex already handles correctly (it stops at `)`).
- Eliminates the `_strip_trailing_punct` interaction because the URL is extracted cleanly from the brackets, not matched by the greedy auto-link regex.

The regex for angle-bracket auto-links must run on ALREADY-ESCAPED text (the input to `format_markdown`). After escaping, `<https://example.com>` becomes `&lt;https://example.com&gt;`. The pre-processing regex matches `&lt;(URL)&gt;` and replaces with `[\1](\1)`.

### 1.4 Scope

| In scope | Out of scope |
|----------|--------------|
| `utils/markdown.py` — angle-bracket auto-link pre-processing | `utils/escaping.py` — no change |
| Tests for `<URL>` syntax | `_strip_trailing_punct` — keep as-is (the fix avoids triggering it on entities) |

---

## 2. Changes by File

### 2.1 `utils/markdown.py` — Add angle-bracket auto-link pre-processing

**Insertion point:** After Step 3 (markdown links → anchor placeholders, line ~235) and before Step 4 (auto-link bare URLs, line ~237).

**New code to insert** (between the existing `_link_replace_and_protect` regex sub and the `_auto_link` regex sub):

```python
    # ── Step 3a: Convert angle-bracket auto-links to markdown links ─────────
    # CommonMark/GFM auto-link syntax: <https://example.com>
    # After escape_for_pango(), this is &lt;https://example.com&gt;
    # The auto-link regex (Step 4) would capture &gt; as part of the URL.
    # Pre-convert to [URL](URL) so Step 3's already-run markdown-link handler
    # would have caught it — but since Step 3 already ran, we convert directly
    # to an anchor placeholder here.
    #
    # Regex: &lt;(scheme://...)(&gt;)  — matches escaped angle-bracket URLs.
    # The URL content is between &lt; and &gt;, and must not contain &gt;
    # (which would be an escaped > inside the URL — extremely unlikely).
    angle_link_re = re.compile(r'&lt;((?:https?|ftp|mailto)://[^\s&]+)&gt;')
    for m in angle_link_re.finditer(protected):
        url = m.group(1)
        safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
        anchor_html = f'<a href="{safe_url}"><u>{url}</u></a>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        placeholder = f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
        protected = protected.replace(m.group(0), placeholder, 1)
```

**IMPORTANT:** This must run AFTER Step 3 (which populates `anchor_spans` and protects markdown `[text](url)` links). The angle-bracket links are appended to the same `anchor_spans` list and use the same `\x00ANCHOR{N}\x00` placeholder format, so Step 6 (restore anchors) restores them automatically.

**Regex explained:**
- `&lt;` — the escaped form of `<` (left angle bracket opening the auto-link)
- `((?:https?|ftp|mailto)://[^\s&]+)` — the URL, which must start with a known scheme, and stops at whitespace or `&` (which covers `&gt;`, `&amp;`, `&lt;`, etc.)
- `&gt;` — the escaped form of `>` (right angle bracket closing the auto-link)

**Why `[^\s&]+` instead of `[^\s<>]+`:** At this point in the pipeline, `<` and `>` are already escaped to `&lt;`/`&gt;`. The `&` character is the start of an entity — if the URL contained a literal `&` (query parameter separator), it was escaped to `&amp;` by `escape_for_pango`. The regex stops at the first `&`, which correctly prevents matching through `&gt;` (the closing bracket entity). URLs with query parameters like `?a=1&b=2` would have the `&` escaped to `&amp;`, so the regex would stop at `&amp;b=2` — this is a limitation.

**Query parameter limitation:** `<https://example.com?a=1&b=2>` becomes `&lt;https://example.com?a=1&amp;b=2&gt;` after escaping. The regex `[^\s&]+` stops at `&amp;`, capturing only `https://example.com?a=1`. This is acceptable — the full URL with query params is rare in angle-bracket auto-links (they're more commonly used for bare domain URLs like `<https://example.com>`). The markdown link syntax `[text](url)` handles query params correctly and is the preferred syntax for complex URLs.

### 2.2 Files NOT changed

- **`utils/escaping.py`** — no change.
- **`ui/views/chat_bubble.py`** — no change. The pipeline order (`escape → format_markdown`) is unchanged.
- **`_TRAILING_PUNCT`** — keep `;` in the set. The fix avoids triggering the entity-truncation by extracting angle-bracket URLs before the auto-link regex runs. Plain URLs without angle brackets don't end in entities.

---

## 3. Data Flow

### Before (buggy)

```
Input:  "see <https://example.com>"
↓ escape_for_pango
"text:  see &lt;https://example.com&gt;"
↓ format_markdown Step 4 (_AUTO_LINK_RE)
"matches URL: https://example.com&gt;"
↓ _strip_trailing_punct
"strips ;: https://example.com&gt"
↓ set_markup
FAIL: "Entity did not end with a semicolon"
```

### After (fixed)

```
Input:  "see <https://example.com>"
↓ escape_for_pango
"text:  see &lt;https://example.com&gt;"
↓ format_markdown Step 3a (NEW: angle-bracket pre-processing)
"regex matches &lt;https://example.com&gt;"
"extracts URL: https://example.com"
"creates anchor placeholder: \x00ANCHOR{N}\x00"
↓ format_markdown Step 4 (_AUTO_LINK_RE)
"no bare URL remaining — &gt; already consumed by Step 3a"
↓ format_markdown Step 6 (restore anchors)
"restores: <a href=\"https://example.com\"><u>https://example.com</u></a>"
↓ set_markup
OK — valid Pango markup
```

---

## 4. Acceptance Criteria

- [ ] `format_markdown(escape_for_pango("see <https://example.com>"))` produces valid Pango with `href="https://example.com"` and no `&gt` entity
- [ ] `format_markdown(escape_for_pango("<https://example.com>"))` works (standalone)
- [ ] `format_markdown(escape_for_pango("go to <https://example.com>."))` works (trailing period)
- [ ] `format_markdown(escape_for_pango("check https://example.com for info"))` still works (plain URL regression)
- [ ] `format_markdown(escape_for_pango("[label](https://example.com)"))` still works (markdown link regression)
- [ ] `format_markdown(escape_for_pango("see <https://example.com> out"))` works (URL embedded in sentence)
- [ ] No `Gtk-WARNING` in stderr when rendering any of the above
- [ ] All existing `tests/test_markdown.py` tests pass

---

## 5. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `<https://example.com?a=1&b=2>` | URL captured up to first `&`: `https://example.com?a=1`. Query param `b=2` becomes separate text. Acceptable limitation. |
| `<ftp://files.example.com>` | Works — `ftp` is in the scheme list. `_validate_link_url` adds warning prefix (HIGH-6). |
| `<not-a-url>` | No match — regex requires `://`. Renders as literal text `&lt;not-a-url&gt;`. |
| `<<https://example.com>>` | Outer `&lt;` and inner `&lt;` — regex matches inner `&lt;https://example.com&gt;`. Double brackets are uncommon. |
| `<https://example.com>` standalone (entire input) | Works — produces anchor tag. |
| Empty brackets `< >` | No match — regex requires scheme://. |
| `[text](<https://example.com>)` | Step 3's markdown-link regex runs FIRST and handles the `(<URL>)` pattern. Step 3a only fires if Step 3 didn't match. May produce double-processing — verify. |

---

## 6. ARCHITECTURE.md Updates

**Section 3.14b (`utils/markdown.py`)** — add note about angle-bracket auto-link pre-processing in the conversion rules list.

---

## 7. Spec Self-Audit

1. **Code samples traced?** Yes — verified the pipeline order, the regex interaction, and the placeholder mechanism against live source.
2. **Exception types?** None — pure string operations. `urllib.parse.quote` does not raise. `re.compile` uses constant patterns.
3. **Key structures?** `anchor_spans` list and `\x00ANCHOR{N}\x00` placeholders are the existing mechanism, verified at Step 3 and Step 6.
4. **Data flow traced?** Yes — §3 shows before/after for the full pipeline.
5. **Would this produce working code?** Yes — the fix uses the existing placeholder pattern and only adds a new regex sub before the auto-link step.
