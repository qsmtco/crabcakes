# Phase 1+2 Re-Verification — After Qrusher Fixes

**Reviewer:** Qaster  
**Date:** 2026-04-12 13:36 PDT  
**Tests:** 273/273 pass

---

## ✅ Bugs Fixed

| # | Bug | Status |
|---|-----|--------|
| Phase 1 #1 | Auto-link double-wraps markdown links | **FIXED** ✅ |
| Phase 2 #1 | Double processing — code blocks never render | **FIXED** ✅ |
| Phase 2 #3 | Terminal blocks require ALL lines to start with `$` | **FIXED** ✅ |
| Phase 1 #3 | Dead code `append_message_to_tab()` | **FIXED** ✅ (removed) |

---

## ❌ Still Unfixed

### BUG: Task list shows `[ ]` / `[x]` instead of ☐/☑ (LOW)

**LOCATION:** `utils/block_parser.py:119-128`

Task content preserves raw `[ ] Todo` / `[x] Done` text instead of converting to ☐/☑ characters per the plan. Cosmetic only.

---

## ❌ Architecture Violations Still Present

### 1. `ui/views/main_content.py` still imports handler (HIGH)

Line 12: `from ui.handlers.chat_render_handler import ChatRenderHandler`

Per Section 8.2: "Component **never** imports other UI components directly." The handler should be created in `window.py` and injected via setter.

### 2. `window.py` not wired (HIGH)

Zero mentions of `ChatRenderHandler`. Handler is instantiated inside `MainContent.__init__()` instead of being created and wired in `window.py`.

### 3. Processing logic in view (MEDIUM)

`chat_bubble.py` does block extraction, escaping, markdown conversion, and syntax highlighting — all processing logic that per the handler pattern belongs in `chat_render_handler.py`. The handler now just passes raw text through to the view. The view is doing the handler's job.

This is a philosophical split from the architecture: the plan says the view "only creates widgets. No logic, no state." But the view now contains the entire rendering pipeline.

---

## Summary

All critical bugs are fixed. Code blocks render, markdown links work, terminal blocks handle mixed output. The remaining issues are:
1. **Checkbox characters** — low priority cosmetic
2. **Architecture violations** — handler pattern not followed (view imports handler, logic in view, window.py not wired)

The architecture issues are the same ones from Phase 1 — they compound with each phase. Worth fixing before Phase 3 to prevent further drift.
