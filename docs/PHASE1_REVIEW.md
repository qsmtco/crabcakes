# Phase 1 Review — Architecture Violations

**Reviewer:** Qaster  
**Date:** 2026-04-12  
**Status:** 6 violations found — code works, but does not comply with ARCHITECTURE.md

---

## ✅ What's Correct

- `utils/escaping.py` — pure Python, no GTK imports (layer rules respected)
- `utils/markdown.py` — pure Python, no GTK imports (layer rules respected)
- `ui/views/chat_bubble.py` — stateless GTK widget factory, no logic or state
- `ui/handlers/chat_render_handler.py` — follows handler pattern, thread-safe GLib dispatch
- All 71 tests passing (test_escaping, test_markdown, test_chat_render_handler)
- CSS lives in `ui/styles.py` only (single source of truth)
- Bubble rendering pipeline order is correct: escape → markdown → widget

---

## ❌ Violations

### 1. ARCHITECTURE.md Not Updated (MAJOR)

**Rule:** Section 0 — "If the diff of your code change doesn't have a corresponding update to this file, the change is incomplete."

**What happened:** ARCHITECTURE.md has zero mentions of:
- `utils/escaping.py`
- `utils/markdown.py`
- `ui/views/chat_bubble.py`
- `ui/handlers/chat_render_handler.py`
- `tests/test_escaping.py`
- `tests/test_markdown.py`

**What needs updating:**
- Section 3 (Module Responsibilities) — add entries for all 4 new modules
- Section 12 (File Inventory) — add all 6 new files with line counts
- Section 2 (Directory Structure) — add new files to the tree
- Section 11 (if applicable) — any protocol/event changes

ARCHITECTURE.md literally says: "Violations require discussion with the team before the code is merged."

---

### 2. `ui/views/main_content.py` Imports a Handler (LAYER VIOLATION)

**Rule:** Section 8.2, rule 3 — "Component **never** imports other UI components directly." Section 3.9 describes MainContent as a view, not a handler owner.

**What happened:**
```python
# main_content.py line 12
from ui.handlers.chat_render_handler import ChatRenderHandler

# main_content.py line 51
self._chat_render_handler = ChatRenderHandler(GLib_module=GLib)
```

**What should happen:** `ChatRenderHandler` should be created in `window.py` and injected into `MainContent` via a setter (e.g., `main_content.set_chat_render_handler(handler)`). Views receive dependencies — they don't import handler modules.

---

### 3. `window.py` Not Wired (HANDLER PATTERN VIOLATION)

**Rule:** Section 8.6 — "Wire the handler in `window.py` (`_build()` method)." The handler pattern requires `window.py` to be the single place where all handlers are created and connected.

**What happened:** `window.py` has zero mentions of `ChatRenderHandler`. The handler is instantiated inside `MainContent.__init__()` instead.

**What should happen:**
1. `ChatRenderHandler` created in `window.py._build()`
2. Injected into `MainContent` via setter
3. Also injected into `ChatHandler` so it can route messages through the render pipeline
4. `window.py` wires the callbacks between handlers

---

### 4. `chat_handler.py` Not Wired to Render Handler (INCOMPLETE INTEGRATION)

**Rule:** The plan specifies: "`chat_handler.py` does NOT render — it routes events to the render handler."

**What happened:** `chat_handler.py` still calls:
```python
self._mc.append_message_to_current_tab("Agent", final_text)
```

This means `MainContent` is both the rendering coordinator AND the view. The plan's architecture is:
- `ChatHandler` → calls `ChatRenderHandler.render_message()` → renders bubble → appends to container
- Instead we have: `ChatHandler` → calls `MainContent.append_message_to_current_tab()` → which internally calls `ChatRenderHandler.render_sync()`

`MainContent` should not own rendering logic. It should own the container (ScrolledWindow + ListBox/Box) and expose methods to append widgets. The *choice* of what widget to create belongs to the render handler.

---

### 5. `markdown.py` Docstring Contradicts Actual Pipeline

**Rule:** Section 7 — "Comments for humans. Every non-obvious decision documented."

**What happened:** `utils/markdown.py` docstring says:
```
5. Return — caller should call escape_for_pango() on the result
```

This implies the pipeline is: `format_markdown()` → then `escape_for_pango()`. But the actual pipeline (correctly) does the reverse: `escape_for_pango()` → then `format_markdown()`.

**Why this matters:** A future contributor reading the docstring will get the order backwards, potentially introducing double-escaping or raw markup injection bugs.

**Fix:** Update the docstring to clarify that `format_markdown()` receives *already-escaped* text and its output is ready for Pango.

---

### 6. CSS Class Names Deviate from Plan

**Plan specifies:**
- `.bubble-mine` — indigo gradient, user messages
- `.bubble-theirs` — dark gradient, agent messages
- `.msg-header` — small muted text

**Implementation uses:**
- `.chat-bubble-you`
- `.chat-bubble-agent`
- `.chat-role-label`
- `.chat-msg-label`

**Severity:** Low — the names are arguably better (more descriptive). But if Phase 2-5 code references the plan's naming convention, there will be confusion. Update the plan to match reality, or rename to match the plan.

---

## Summary

| # | Violation | Severity | Section |
|---|-----------|----------|---------|
| 1 | ARCHITECTURE.md not updated | MAJOR | Section 0 |
| 2 | View imports handler | HIGH | Section 8.2 |
| 3 | window.py not wired | HIGH | Section 8.6 |
| 4 | ChatHandler bypasses render handler | MEDIUM | Plan spec |
| 5 | Docstring contradicts pipeline | MEDIUM | Section 7 |
| 6 | CSS naming mismatch | LOW | Plan spec |

**Bottom line:** The code works, the tests pass, the formatting pipeline is correct. But the wiring violates the handler pattern — `window.py` is supposed to be the orchestrator, and right now `MainContent` has absorbed rendering responsibilities that belong to the handler layer. The fix is mostly moving code around, not rewriting.
