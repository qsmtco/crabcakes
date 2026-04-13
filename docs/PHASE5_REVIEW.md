# Phase 5 Review — Polish: Copy/Forward Buttons, Auto-Scroll, Message Grouping

**Reviewer:** Qaster
**Date:** 2026-04-12
**Tests:** 288 pass (no Phase 5 tests added)

---

## ✅ What's Correct

- **Copy button** — copies bubble text to clipboard via `_copy_to_clipboard()`
- **Forward button** — calls `on_forward_click()` callback when set, logs stub when not
- **Hover reveal** — CSS `opacity: 0 → 1` on `.chat-bubble-actions` when hovering `.chat-bubble-agent`
- **Agent only** — buttons only on agent bubbles, not user bubbles
- **Scroll-to-bottom floating button** — shows when scrolled >80px from bottom, hides when near bottom
- **Auto-scroll** — already implemented in Phase 4, scroll button supplements it
- **`end_streaming()` resets `_last_message_key`** — ensures session switches don't carry grouping state across sessions
- **Views don't import handlers** — ✅ (copy/forward is CSS-hover only, no handler wiring in view)
- **ARCHITECTURE.md updated** — Section 3.14e, 3.14f, 4.7 added with full Phase 5 detail
- **288 tests pass** — no regressions

---

## ❌ Missing Tests (Plan Violation)

The plan specified tests for:
- Consecutive messages from same agent → second has no header (message grouping)
- Message from different agent → header shown
- Session switch → header shown again

**None exist.** No `TestPhase5` tests in `test_chat_render_handler.py`. This is a deviation from the plan.

---

## ❌ ARCHITECTURE.md — Missing Forward Callback Documentation

**LOCATION:** `docs/ARCHITECTURE.md`

The plan (Section 3.14) shows:
```
build_role_bubble(role, text, on_forward_click=None, tight=False)
```

ARCHITECTURE.md documents the `on_forward_click` parameter and that it wires to a popover in `window.py`. ✅

But the **wiring chain** is not documented:
> How `on_forward_click` gets from `window.py → ChatHandler → ChatRenderHandler.render_sync → build_role_bubble`

The `ChatHandler` has no `on_forward_click` parameter in its current API. The forward callback is passed directly from `window.py` to the bubble via `ChatRenderHandler.render_sync`. This is fine architecturally (composition root wires it), but the data flow is not described.

---

## Summary

| # | Issue | Severity | Type |
|---|-------|----------|------|
| 1 | No Phase 5 tests (message grouping, copy/forward) | MEDIUM | Missing tests |
| 2 | Forward callback wiring chain not in ARCHITECTURE.md | LOW | Documentation |

**Overall:** Phase 5 is well-implemented. The code is clean, CSS-only hover behavior avoids handler complexity, the scroll button is well-designed, and message grouping via `tight` margin is elegant. The two issues above are minor. Qrusher's work is good.