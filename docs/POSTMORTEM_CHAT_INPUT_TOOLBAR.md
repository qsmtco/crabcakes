# Post-Mortem: Chat Input Toolbar Implementation

**Date:** 2026-05-29
**Spec:** `docs/SPEC_CHAT_INPUT_TOOLBAR.md`
**Builder:** QTR
**Supervisor/Auditor:** Qaster

---

## Summary

Implemented a full Chat Input Toolbar for CrabCakes, replacing the dead `ChatControlBar` stub with a working toolbar featuring file I/O, find/replace, spell check, keyboard shortcuts, and word count.

## Files Changed

| File | Action | Lines | Commit |
|------|--------|-------|--------|
| `utils/spellcheck.py` | NEW | 100 | (prior session) |
| `ui/handlers/input_toolbar_handler.py` | NEW | 359 | `eda1bdb` |
| `ui/views/chat_input_toolbar.py` | NEW | 510 | `eda1bdb` |
| `ui/views/main_content.py` | MODIFIED | net ~0 | `eda1bdb` |
| `ui/window.py` | MODIFIED | +120 | `eda1bdb` |
| `ui/handlers/activity_handler.py` | MODIFIED | -4 | `eda1bdb` |
| `ui/styles.py` | MODIFIED | +40 | `eda1bdb` |
| `docs/ARCHITECTURE.md` | MODIFIED | +30 | `ba56e1e` |
| `ui/views/chat_control_bar.py` | DELETED | -60 | `4987d7d` |

## Commits (chronological)

1. `eda1bdb` — feat: add chat input toolbar (handler + view + wiring)
2. `b025ecd` — fix: add gi.require_version('Gdk', '4.0')
3. `ba56e1e` — docs: update ARCHITECTURE.md
4. `24d19ec` — feat: keyboard shortcuts + spell suggestion popover
5. `a4f2a7f` — fix: remove unused tag_table vars + position spell popup correctly
6. `4987d7d` — fix: path traversal in save_as_prompt + delete dead file

## Bugs Found in Audit

| # | Severity | Description | Found By | Fixed In |
|---|----------|-------------|----------|----------|
| 1 | MEDIUM | Path traversal in `save_as_prompt()` — no filename sanitization | Qaster (adversarial audit) | `4987d7d` |
| 2 | LOW | Dead file `chat_control_bar.py` still on disk | Qaster (audit) | `4987d7d` |
| 3 | LOW | Unused `tag_table` variable in `_apply_spell_tags` | QTR (self-review) | `a4f2a7f` |
| 4 | LOW | Spell popup anchored at (0,0) instead of click position | QTR (self-review) | `a4f2a7f` |
| 5 | LOW | Missing `gi.require_version('Gdk', '4.0')` → PyGIWarning | Qaster (Phase 3 audit) | `b025ecd` |

## Architecture Compliance

- ✅ `utils/spellcheck.py` — pure Python, no GTK, no network
- ✅ `ui/handlers/input_toolbar_handler.py` — no `Gtk.*` widget imports, Pango/Gdk data types only
- ✅ `ui/views/chat_input_toolbar.py` — pure view, emits callbacks, no business logic
- ✅ All CSS classes in `ui/styles.py`, no inline CSS
- ✅ `window.py` wires handler to view via callbacks
- ✅ Follows MediaHandler + STTEngine pattern

## Test Suite

Baseline: 24 failed, 1634 passed, 22 errors (all pre-existing)
Post-implementation: identical — no regressions.

## Lessons Learned

1. **QTR moves fast but needs specific direction.** When told to fix specific bugs, she found her own bugs instead. Both sets were real, but the delegation wasn't precise enough. Future: enumerate exact line numbers and show the vulnerable code.

2. **`git add -A` is dangerous.** I accidentally committed workspace files (AGENTS.md, SOUL.md, etc.) into the project repo. Had to reset and redo. Future: always `git add` specific files, never `-A`.

3. **QTR builds ahead of the plan.** She implemented Phases 3-5 proactively without being asked. Good initiative, but made supervision harder — I was delegating Phase 3 while she was already done with Phase 5. Future: ask for status before delegating.

4. **Adversarial audit caught real security bugs.** The path traversal in `save_as_prompt` was a genuine vulnerability that could write to arbitrary paths. The steelFramedCodeWriter + adversarialDebugger prompt combination is effective.

5. **Phase plan file was useful.** Writing `docs/IMPLEMENTATION_PHASES_TOOLBAR.md` gave QTR a reference point even though she didn't follow the exact phase numbering.

## What's Left

- [ ] Manual end-to-end test (launch CrabCakes, test each feature)
- [ ] Spell check right-click suggestion popover — verify it works visually
- [ ] Find/Replace with Unicode text (emoji, CJK characters)
- [ ] Update SPEC status from "Draft" to "Implemented"
