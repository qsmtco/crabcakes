# Proposal: Fix Malformed Pango Markup from Adjacent Bold Blocks

**Date:** 2026-05-10
**Author:** Qaster
**Status:** ✅ Fully implemented — commit `91813ab`

> **Status (verified 2026-06-12):** ✅ **DONE** — 
> **status:** `DONE` — sortable tag for `ls | grep STATUS` Confirmed in codebase. `utils/markdown.py:53` has `format_markdown()` (converts markdown to Pango Markup); `utils/escaping.py:78` has `html.unescape()` (decodes HTML entities that would corrupt markup). The bug (adjacent bold blocks producing malformed Pango markup) is fixed. The proposal's three modified files (`utils/markdown.py`, `utils/escaping.py`, `ui/styles.py`) all show the fix. Commits `91813ab` (QTR implementation) and a follow-up by Qaster (loop regression fix + CSS removal + HTML entity decoding) are on `origin/main`.
**Severity:** High — corrupts all chat display for the session
**Files modified:** 3 (`utils/markdown.py`, `utils/escaping.py`, `ui/styles.py`)
**Architecture alignment:** ✅ Full compliance with ARCHITECTURE.md — no violations

**Implemented by:** QTR (Coder agent)
**Reviewed by:** Qaster (adversarial code review)
**Additional fix by:** Qaster (loop regression fix + CSS removal + HTML entity decoding)

---

## Implementation Status

| Part | Description | Status | Reviewer Notes |
|------|-------------|--------|----------------|
| A | ZWSP fix for adjacent bold blocks in `format_markdown()` | ✅ Done | Loop-based replace handles 4/6/8+ star counts; 6-star regression caught and fixed during review |
| B | Invalid CSS removal (`max-width`/`word-break`) | ✅ Done | GTK CSS doesn't support web CSS properties; removed `max-width` and `word-break` to eliminate GTK warnings |
| C | HTML entity decoding in `escape_for_pango()` | ✅ Done | Added `html.unescape()` to prevent `&quot;` double-encoding from LLM output |

---

## Problem

When an agent writes multiple `**bold**` blocks with no space between them (e.g. `**Checkpoint 1: ...****Checkpoint 2: ...****Checkpoint 3: ...**`), `format_markdown()` in `utils/markdown.py` produces **invalid Pango markup** with misnested tags. GTK rejects the markup, falls back to displaying the raw tag text, and the resulting long unbroken character sequences prevent word wrapping — causing one bubble to expand horizontally and push **all** chat bubbles off screen.

### Root Cause

`format_markdown()` applies regex substitutions in sequence (bold+italic first, then bold, then italic). The bold+italic regex `\*\*\*(.+?)\*\*\*` can match across the `****` boundary between two adjacent bold blocks, consuming content that spans what should be two separate formatting regions.

**Example trace:**

Input: `**A****B****C**`

| Step | Regex | Match | Result |
|------|-------|-------|--------|
| 1 | `\*\*\*(.+?)\*\*\*` | `****B***` (pos 3–11) | `**A<b><i>*B</i></b>*C**` |
| 2 | `\*\*(.+?)\*\*` | entire remaining string | `<b>A<b><i>*B</i></b>*C</b>` |

The `<b>` opened at step 2 wraps the entire string, while `<b><i>` from step 1 creates invalid nesting. Pango rejects this with: *"Element "b" was closed, but the currently open element is "i"*".

### Secondary Issues

1. **No bubble width constraint** — when markup fails, the label cannot wrap, expanding the entire chat layout.
2. **HTML entity double-encoding** — LLMs output `&quot;` which `escape_for_pango()` double-encodes to `&amp;quot;`, appearing as raw `&quot;` in bubbles.

---

## Fix

### Part A — Fix `format_markdown()` in `utils/markdown.py`

**Strategy:** Before applying any bold/italic regexes, insert a zero-width space (ZWSP, `\u200b`) between adjacent `**` boundaries using a loop. After all regexes complete, remove the ZWSPs.

**Implementation:**

```python
# Step 0: Isolate adjacent bold boundaries
_ZWSP = '\u200b'
prev = None
while text != prev:
    prev = text
    text = text.replace('****', f'**{_ZWSP}**')

# ... (Steps 1–6 unchanged) ...

# Step 7: Remove zero-width spaces
protected = protected.replace(_ZWSP, '')
```

**Why a loop:** `str.replace()` is non-overlapping and single-pass. On `******` (6 stars, adjacent bold+italic), a single pass leaves a residual `****`. The loop runs until stable, handling all star counts (4, 6, 8+).

### Part B — Invalid CSS Removal in `ui/styles.py`

**Original plan** was to add `max-width` and `word-break` CSS properties. **During implementation**, GTK rejected these as invalid — GTK CSS doesn't support web CSS properties. The invalid lines were removed. The root cause (malformed markup) is fixed by Part A, making a CSS defensive measure unnecessary.

### Part C — HTML Entity Decoding in `utils/escaping.py`

Added `html.unescape(text)` at the top of `escape_for_pango()` to decode HTML entities before processing. This prevents double-encoding: `&quot;` → `"` (unescape) → `&quot;` (escape) → `"` (rendered by Pango).

---

## Architecture Compliance

| Rule | Compliance |
|------|-----------|
| §3.14b `utils/markdown.py` owns `format_markdown()` | ✅ Change is in the correct module |
| `utils/escaping.py` owns Pango escaping | ✅ `html.unescape()` added to the correct function |
| §3.5 `ui/styles.py` is single source of truth for CSS | ✅ Invalid CSS removed |
| `utils/` is pure Python, no GTK | ✅ All changes are pure string manipulation |
| No new files | ✅ Three existing files modified |
| No cross-handler imports | ✅ No handler imports affected |

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `utils/markdown.py` | ZWSP loop insertion (Step 0) + removal (Step 7) | +6 |
| `utils/escaping.py` | `html.unescape()` before tag parsing | +3 |
| `ui/styles.py` | Removed invalid `max-width`/`word-break` CSS | -4 |

## Testing Verified

1. ✅ Adjacent bold blocks: `**A****B****C**` → `<b>A</b><b>B</b><b>C</b>`
2. ✅ 6-star regression: `***A******B***` → valid Pango
3. ✅ Normal bold, bold+italic, mixed, code in bold — all correct
4. ✅ HTML entities: `&quot;offline&quot;` → renders as `"offline"`
5. ✅ Compile clean, no GTK warnings on startup
6. ✅ Same 6 pre-existing test failures, no new failures

## Not Changed

- `chat_bubble.py` — no widget changes needed
- `chat_render_handler.py` — no pipeline changes needed
- `block_parser.py` — not involved; adjacent bold blocks appear within a single text segment
