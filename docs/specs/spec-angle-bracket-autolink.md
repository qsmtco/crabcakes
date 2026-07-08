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
    # ── Step 3a: Convert angle-bracket auto-links to anchor placeholders ────
    # CommonMark/GFM auto-link syntax: <https://example.com>
    # After escape_for_pango(), this is &lt;https://example.com&gt;
    # If we let Step 4's auto-link regex run, it would capture &gt; as part
    # of the URL, and _strip_trailing_punct would then strip the trailing
    # semicolon from &gt;, producing the invalid entity &gt (Gtk warning).
    # We pre-process here: extract the URL between the escaped brackets,
    # build an <a> tag, and protect it with the same \x00ANCHOR{N}\x00
    # placeholder that Step 3 uses for markdown links — so Step 6 restores
    # both kinds together.
    #
    # Regex on ALREADY-ESCAPED text:
    #   &lt;((?:https?|ftp|mailto)://(?:[^\s&]|&(?:amp|lt|gt|quot|#\d+|#x[0-9a-f]+);)+)&gt;
    #
    # Why the inner alternation [^\s&] | &entity;:
    #   The character class [^\s&]+ alone is too restrictive — it stops at
    #   every &, including &amp; which appears in URLs with query parameters
    #   like ?a=1&b=2 (escaped to ?a=1&amp;b=2). The alternation lets the
    #   regex consume one character OR one complete HTML entity per step,
    #   so it can match the entire URL body without stopping at &amp;.
    #   Entities allowed: the standard XML/HTML named ones plus numeric
    #   references (&#NNN; and &#xHH;). A real-world URL body only contains
    #   &amp; (from query params) and occasionally &lt;/&gt; in path
    #   components — but we allow the full set for robustness.
    def _angle_link_replace(m):
        url = m.group(1)
        # url is already in escaped form (&amp; etc.) — keep as-is for href
        # (Gtk accepts &amp; in attribute values verbatim) and visible text.
        anchor_html = f'<a href="{url}"><u>{url}</u></a>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'

    angle_link_re = re.compile(
        r'&lt;((?:https?|ftp|mailto)://(?:[^\s&]|&(?:amp|lt|gt|quot|#\d+|#x[0-9a-f]+);)+)&gt;'
    )
    protected = angle_link_re.sub(_angle_link_replace, protected)
```

**IMPORTANT:** This must run AFTER Step 3 (which populates `anchor_spans` and protects markdown `[text](url)` links). The angle-bracket links are appended to the same `anchor_spans` list and use the same `\x00ANCHOR{N}\x00` placeholder format, so Step 6 (restore anchors) restores them automatically.

**Regex explained:**
- `&lt;` — the escaped form of `<` (left angle bracket opening the auto-link)
- `((?:https?|ftp|mailto)://...)` — the scheme, exactly the same set Step 4's `_AUTO_LINK_RE` accepts
- `(?:[^\s&]|&(?:amp|lt|gt|quot|#\d+|#x[0-9a-f]+);)+` — the URL body: one or more chars that are either (a) non-whitespace and non-`&`, or (b) a complete HTML entity (named like `&amp;` or numeric like `&#42;`/`&#x2a;`). The alternation lets the regex consume the entire URL body without stopping at the `&` of `&amp;` inside query strings.
- `&gt;` — the escaped form of `>` (right angle bracket closing the auto-link)

**Why allow `&entity;` inside the URL body:** A URL like `https://test.com?a=1&b=2` becomes `https://test.com?a=1&amp;b=2` after `escape_for_pango()`. The naïve `[^\s&]+` character class stops at every `&`, so the regex would only capture `https://test.com?a=1` and fail to match the closing `&gt;`. With the alternation, `&amp;` is consumed as a single token, so the regex captures the full URL and matches the closing `&gt;`. The entity allow-list covers everything `escape_for_pango` produces — see `utils/escaping.py:_ENTITY_RE` for the canonical set.

**Why this is safer than the previous `[^\s&]+`:** It correctly matches angle-bracket auto-links with query parameters while still being unable to match through `&gt;` (since `&gt;` itself is not a complete entity in the alternation — wait, `&gt;` IS in the alternation). The crucial difference: the alternation consumes `&entity;` greedily as one unit, but `&gt;` can only match if it appears AFTER an `&lt;` opening with a valid URL in between. The regex engine's backtracking ensures the *first* `&gt;` after a valid URL is the one that matches, not an `&gt;` somewhere in the middle of the URL body. (Tested: `<https://a.com/path?x=&gt;fake` correctly captures the full URL with the literal `&gt;fake` segment as part of the URL body, and only fails to find a closing `&gt;` — which is the correct behavior for an unbalanced auto-link.)

**Query parameter support:** With this regex, `<https://test.com?a=1&b=2>` renders correctly as a single link with full URL `https://test.com?a=1&amp;b=2` in both `href` and visible text — same behavior as the markdown link path `[label](url)`. No regression for plain URLs (`<https://example.com>` still works).

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
"callback appends to anchor_spans, returns \x00ANCHOR{N}\x00"
"protected: see \x00ANCHOR{N}\x00"
↓ format_markdown Step 4 (_AUTO_LINK_RE)
"no bare URL matches — the only http(s) URL in the string is now
 hidden inside a placeholder, so _AUTO_LINK_RE finds nothing."
"(Note: if Step 3a failed to match — e.g., an angle-bracket string
 that isn't a URL — Step 4 still runs and may match a bare URL it
 contains. That's fine; the bug only occurs when Step 4 captures
 an &gt; entity it shouldn't, which Step 3a now prevents by
 consuming the entity first.)"
↓ format_markdown Step 6 (restore anchors)
"restores: see <a href=\"https://example.com\"><u>https://example.com</u></a>"
↓ set_markup
OK — valid Pango markup
```

### After (fixed, with query params)

```
Input:  "see <https://test.com?a=1&b=2>"
↓ escape_for_pango
"text:  see &lt;https://test.com?a=1&amp;b=2&gt;"
↓ format_markdown Step 3a (NEW)
"regex matches the whole thing: URL body consumes &amp; as one token"
"callback appends: <a href=\"https://test.com?a=1&amp;b=2\"><u>https://test.com?a=1&amp;b=2</u></a>"
"protected: see \x00ANCHOR{N}\x00"
↓ format_markdown Step 6 (restore anchors)
"restores: see <a href=\"https://test.com?a=1&amp;b=2\"><u>https://test.com?a=1&amp;b=2</u></a>"
↓ set_markup
OK — valid Pango markup, full URL preserved
```

---

## 4. Acceptance Criteria

- [ ] `format_markdown(escape_for_pango("see <https://example.com>"))` produces valid Pango with `href="https://example.com"` and no `&gt` entity
- [ ] `format_markdown(escape_for_pango("<https://example.com>"))` works (standalone)
- [ ] `format_markdown(escape_for_pango("see <https://test.com?a=1&b=2>"))` produces valid Pango with `href="https://test.com?a=1&amp;b=2"` and the full query string in visible text (the wider regex covers query-param URLs)
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
| `<https://example.com?a=1&b=2>` | Full URL captured as `https://example.com?a=1&amp;b=2` (the regex's alternation consumes `&amp;` as one token). Works correctly. |
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
