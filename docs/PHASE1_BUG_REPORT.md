# Phase 1 Bug Report — Chat Formatting

**Reviewer:** Qaster  
**Date:** 2026-04-12  
**Tests:** 234/234 pass (but tests don't catch these bugs)

---

## BUG #1: Auto-Link Regex Double-Wraps Markdown Links (CRITICAL)

**TYPE:** Logic

**LOCATION:** `utils/markdown.py:117-124` (auto-link regex runs after markdown link processing)

**REPRODUCTION:**
```python
from utils.markdown import format_markdown
format_markdown('[click](http://example.com)')
# Expected:  '<a href="http://example.com"><u>click</u></a>'
# Actual:    '<a href="<a href="http://example.com"><u>http://example.com</u></a>"><u>click</u></a>'
```

**ROOT CAUSE:**
The processing order is:
1. Line 112: Markdown link regex converts `[text](url)` → `<a href="url"><u>text</u></a>` ✅
2. Line 124: Auto-link regex scans the RESULT and finds the bare URL inside `href="..."` 
3. It wraps it in ANOTHER `<a>` tag → broken nested Pango markup

This affects **every markdown link** — not just edge cases. A simple `[click](http://example.com)` produces invalid Pango that `Gtk.Label.set_markup()` may reject or render incorrectly.

**FIX:**
The auto-link regex must skip URLs that are already inside an `<a>` tag. Options:
1. Add a negative lookbehind for `href="` before matching
2. Protect markdown link URLs with placeholders (like code spans) before auto-linking
3. Run auto-link BEFORE markdown links, then protect auto-linked URLs from markdown link processing

Recommended: Option 2 — placeholder approach is consistent with how code spans are already handled.

```python
# Before auto-link step, replace all <a href="..."> with placeholders
# Then auto-link bare URLs
# Then restore <a href="..."> placeholders
```

**VERIFIED:** NO (fix not yet applied)

---

## BUG #2: Double Backtick Code Spans Produce Wrong Output (MEDIUM)

**TYPE:** Logic

**LOCATION:** `utils/markdown.py:85-90` (code span regex)

**REPRODUCTION:**
```python
from utils.markdown import format_markdown
format_markdown('``nested``')
# Expected:  '<tt>`nested`</tt>' (GFM standard: double backticks allow single backtick inside)
# Actual:    '<tt></tt>nested<tt></tt>'
```

**ROOT CAUSE:**
The regex `r'\`([^\`\n]*)\`'` matches each pair of backticks independently. For ```` ``nested`` ````:
- First match: `` ` `` (empty content between first two backticks) → `<tt></tt>`
- Second match: `` ``nested`` → `nested<tt></tt>` (remaining text gets mangled)

The regex doesn't handle multi-backtick delimiters (`` ` `` vs ``` `` ```). GFM allows `` ``code`` `` for code spans containing single backticks. This is a minor spec compliance issue.

**FIX:**
Either:
1. Match longest backtick run first (`` `` `` before `` ` ``), or  
2. Accept this as "won't fix" for Phase 1 and document the limitation

**VERIFIED:** NO (fix not yet applied)

---

## BUG #3: `append_message_to_tab()` Is Dead Code With Old Rendering (LOW)

**TYPE:** Wiring

**LOCATION:** `ui/views/main_content.py:419-432`

**REPRODUCTION:**
```bash
grep -rn 'append_message_to_tab[^_]' ui/ --include='*.py'
# Only match is the definition itself — never called
```

**ROOT CAUSE:**
`append_message_to_tab()` still uses the old plain-label rendering (`Gtk.Label` with `<b>Role:</b> text`). Meanwhile, `append_message_to_current_tab()` was updated to use `ChatRenderHandler.render_sync()`. 

If any code path ever calls `append_message_to_tab()` in the future (or if it was supposed to be used for routing to non-current tabs), it would bypass the formatting pipeline entirely.

**FIX:**
Either:
1. Update `append_message_to_tab()` to use the render handler (same as `append_message_to_current_tab`)
2. Remove it entirely if it's truly unused

Note: `chat_handler.py` currently switches tabs THEN calls `append_message_to_current_tab()`, which is why `append_message_to_tab()` is never needed. But this is fragile — if the switch fails silently, the message appears in the wrong tab.

**VERIFIED:** NO (fix not yet applied)

---

## BUG #4: `markdown.py` Docstring Describes Wrong Pipeline Order (LOW)

**TYPE:** Documentation (but could cause future bugs)

**LOCATION:** `utils/markdown.py:59` 

**REPRODUCTION:**
```python
# Docstring says:
# "5. Return — caller should call escape_for_pango() on the result"
# But the actual pipeline in chat_render_handler.py does:
#   safe = escape_for_pango(text)   # escape FIRST
#   formatted = format_markdown(safe)  # markdown SECOND
```

**ROOT CAUSE:**
The docstring implies the caller should escape AFTER markdown conversion. The actual usage escapes BEFORE. A future developer reading the docstring will implement the pipeline backwards, which would:
- Double-escape `&` → `&amp;amp;` 
- Not protect against XSS (`<script>` tags would pass through)
- Break markdown inside existing Pango tags

**FIX:**
Update the docstring to say:
```
Receives already-escaped text (caller runs escape_for_pango first).
Output is Pango Markup ready for Gtk.Label.set_markup().
```

**VERIFIED:** NO (fix not yet applied)

---

## Summary

| # | Bug | Severity | Impact |
|---|-----|----------|--------|
| 1 | Auto-link double-wraps markdown links | **CRITICAL** | Every `[text](url)` renders broken |
| 2 | Double backtick code spans | MEDIUM | Edge case, wrong output |
| 3 | Dead code `append_message_to_tab()` | LOW | Unused but confusing |
| 4 | Docstring wrong pipeline order | LOW | Could cause future bugs |

**Bug #1 is the showstopper.** Every markdown link an agent sends will render with broken nested `<a>` tags. The fix is straightforward — protect already-processed links before running the auto-link regex.
