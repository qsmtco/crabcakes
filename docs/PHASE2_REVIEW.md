# Phase 2 Review — Architecture & Bug Analysis

**Reviewer:** Qaster  
**Date:** 2026-04-12  
**Tests:** 271/271 pass (but tests don't catch the critical bug)

---

## ✅ What's Correct

- `utils/block_parser.py` — pure Python, no GTK imports, correct layer
- `utils/syntax_highlight.py` — pure Python, optional Pygments, graceful fallback
- ARCHITECTURE.md updated (Section 3, Section 12 file inventory) ✅
- CSS added to `styles.py` only (single source of truth) ✅
- 16+ language CSS variants per plan ✅
- Copy button uses GTK4 clipboard API per plan ✅
- Code block structure: header + content per plan ✅
- Blockquote, terminal, heading, task widgets all implemented ✅
- Tests for both new modules (37 tests total) ✅
- `_PYGMENTS_AVAILABLE` flag handles missing dependency ✅

---

## ❌ Bugs

### BUG #1: Double Processing — Code Blocks Never Render (CRITICAL)

**TYPE:** Logic / Wiring

**LOCATION:** `ui/handlers/chat_render_handler.py:86-88` → `ui/views/chat_bubble.py:70`

**REPRODUCTION:**
```python
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
from utils.block_parser import extract_blocks

raw = 'Code:\n```python\nprint("hello")\n```\nDone.'

# render_sync pipeline:
safe = escape_for_pango(raw)
formatted = format_markdown(safe)
# formatted = 'Code:\n<tt></tt>`python\nprint(&quot;hello&quot;)\n<tt></tt>`\nDone.'

# build_role_bubble receives formatted text, calls extract_blocks:
segments = extract_blocks(formatted)
# Result: 2 TEXT segments — code block is GONE
# The ``` was already consumed by markdown.py's code span regex
```

**ROOT CAUSE:**
Both `ChatRenderHandler.render_sync()` AND `build_role_bubble()` process the text:
1. `render_sync()`: `escape_for_pango(text)` → `format_markdown(safe)` → passes **Pango markup** to `build_role_bubble()`
2. `build_role_bubble()`: calls `extract_blocks(text)` on the **already-processed Pango markup**
3. `extract_blocks()` can't find ` ``` ` fenced blocks because they were converted to `<tt>` tags by `format_markdown()` in step 1
4. Each text segment then gets `escape_for_pango()` + `format_markdown()` applied AGAIN in `_build_text_segment()`

**Impact:**
- **Code blocks never render** — the most important Phase 2 feature is broken
- Any Pango tags from step 1 get double-escaped, showing raw `<b>`, `<i>` etc.
- Blockquotes, terminals, headings, tasks also can't be detected if inline markdown runs first

**FIX:**
The processing pipeline needs ONE owner, not two. Options:

**Option A (recommended):** `build_role_bubble()` receives RAW text, does ALL processing:
1. `render_sync()` passes raw text directly to `build_role_bubble()`
2. `build_role_bubble()` calls `extract_blocks(raw_text)` to split into segments
3. `_build_text_segment()` applies `escape_for_pango()` + `format_markdown()` per segment
4. `_build_code_segment()` applies `highlight()` (which handles its own escaping)
5. `render_sync()` does NOT call `escape_for_pango()` or `format_markdown()`

**Option B:** `render_sync()` does block extraction FIRST, then per-segment formatting:
1. `segments = extract_blocks(raw_text)`
2. For each segment, apply appropriate processing
3. Assemble into bubble

Either way, the current split where both layers process the same text is the root cause.

**VERIFIED:** NO

---

### BUG #2: Phase 1 Auto-Link Bug Still Present (CRITICAL — carried from Phase 1)

**TYPE:** Logic (pre-existing)

**LOCATION:** `utils/markdown.py:117-124`

**REPRODUCTION:**
```python
from utils.markdown import format_markdown
format_markdown('[click](http://example.com)')
# Expected:  '<a href="http://example.com"><u>click</u></a>'
# Actual:    '<a href="<a href="http://example.com">...</a>"><u>click</u></a>'
```

Every markdown link produces broken nested `<a>` tags. Not fixed from Phase 1.

**VERIFIED:** NO

---

### BUG #3: Terminal Block Requires ALL Lines to Start with `$` (MEDIUM)

**TYPE:** Logic

**LOCATION:** `utils/block_parser.py:107-114` (`_classify_paragraph`)

**REPRODUCTION:**
```python
from utils.block_parser import extract_blocks
extract_blocks('$ make build\nCompiling...\nDone')
# Expected: terminal segment with command + output
# Actual:   text segment (because "Compiling..." and "Done" don't start with $)
```

**ROOT CAUSE:** The classifier requires ALL non-empty lines to start with `$`. Real terminal output includes command output lines that don't start with `$`.

The plan says "consecutive terminal lines (`$ `)" — ambiguous. But real-world terminal blocks have mixed `$` prefix and output lines.

**FIX:** Allow terminal blocks where at least the FIRST line starts with `$`, and subsequent lines may or may not. Or use a threshold (e.g., >50% of lines start with `$`).

**VERIFIED:** NO

---

### BUG #4: Task List Shows `[ ]` / `[x]` Instead of ☐/☑ (LOW)

**TYPE:** Logic (plan deviation)

**LOCATION:** `utils/block_parser.py:119-128`, `ui/views/chat_bubble.py:_build_task_segment`

**REPRODUCTION:**
```python
from utils.block_parser import extract_blocks
result = extract_blocks('- [ ] Todo')
# content = "[ ] Todo"
# Plan says: Label with ☐/☑ checkbox character
# Implementation: preserves raw [ ]/[x] text, no conversion
```

**FIX:** In `_build_task_segment()`, replace `[ ]` with `☐` and `[x]` with `☑` before rendering.

**VERIFIED:** NO

---

## ❌ Architecture Violations

### VIOLATION #1: View Imports Handler (carried from Phase 1)

**LOCATION:** `ui/views/main_content.py:12`

Still imports `ChatRenderHandler` directly. Per Section 8.2: "Component **never** imports other UI components directly." Not fixed.

### VIOLATION #2: `window.py` Not Wired (carried from Phase 1)

`ChatRenderHandler` still instantiated inside `MainContent.__init__()`, not in `window.py`. Per Section 8.6, `window.py` should create and wire all handlers.

### VIOLATION #3: Processing Logic in View

**LOCATION:** `ui/views/chat_bubble.py`

The view now contains significant processing logic: `extract_blocks()`, `escape_for_pango()`, `format_markdown()`, `highlight()`. Per the handler pattern, text processing orchestration belongs in the handler (`chat_render_handler.py`), not in the view. The view should receive pre-built widgets or simple data, not do parsing.

The plan explicitly states:
- `chat_bubble.py` is a VIEW — "it only creates widgets. No logic, no state"
- `chat_render_handler.py` owns "rendering logic and state"

But the actual implementation has `chat_bubble.py` doing ALL the work: block extraction, escaping, markdown conversion, syntax highlighting. The handler just passes through.

### VIOLATION #4: `append_message_to_tab()` Still Dead Code (carried from Phase 1)

**LOCATION:** `ui/views/main_content.py:419-432`

Still uses old plain-label rendering. Still never called.

---

## Summary

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1 | Double processing — code blocks never render | **CRITICAL** | Bug |
| 2 | Auto-link double-wraps markdown links | **CRITICAL** | Bug (Phase 1) |
| 3 | Terminal blocks require all lines to start with $ | MEDIUM | Bug |
| 4 | Task lists show `[ ]` instead of ☐ | LOW | Plan deviation |
| 5 | View imports handler | HIGH | Architecture |
| 6 | window.py not wired | HIGH | Architecture |
| 7 | Processing logic in view | MEDIUM | Architecture |
| 8 | Dead code append_message_to_tab | LOW | Code quality |

**Bug #1 is the showstopper.** Phase 2's primary feature — code block rendering — is completely broken because the processing pipeline runs twice. The fix requires deciding which layer owns text processing (handler or view) and removing it from the other.
