# SPEC: BUG #22 — Empty Chat Bubble on Tool-Only Turns

**Date:** 2026-07-18
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** Fix for BUG #22 found in the Debugger fifth-pass (final ship-gate) audit
**Depends on:** `docs/specs/SPEC-ACTIVITY-DRAWER-BUGFIXES-ROUND4.md` (the BUG #21 fix that introduced this artifact)
**Target branch:** main

> **Architecture compliance:** The change is in `ui/handlers/agent_runtime_handler.py` (§3.21v) and `tests/test_agent_runtime.py`. No view or runtime changes. The fix is a guard in an existing handler method. Per §8.6 the handler owns response-completion logic; suppressing an empty bubble render is within its responsibility.

---

## DISCOVERY (read before writing any spec content)

- **Read `ui/handlers/agent_runtime_handler.py:1384-1435` (`_do_response_complete`):** confirmed the defect. Line 1419 calls `self._crh.end_streaming(session_key, agent_name=resolved_name)` unconditionally. The fallback at line 1422 (`if not was_streaming and not text:`) only catches the case where streaming was NEVER started. For a tool-only turn, the BUG #21 empty-delta started streaming (`was_streaming=True`), but no content arrived (`text=""`), so the fallback is skipped and `end_streaming` renders an empty bubble.
- **Read `ui/handlers/chat_render_handler.py:409-418` (`get_streaming_text`):** confirmed it returns `sb.plain_text if sb is not None else None`. After the empty delta, `sb.plain_text` is `""` (empty string appended to empty accumulator). So the check must handle both `""` and `None`.
- **Read `ui/handlers/chat_render_handler.py:544-610` (`end_streaming`):** confirmed it unconditionally calls `build_role_bubble(sb.role, full_text, ...)` at line 595 and appends the result (line 603). There is no empty-text guard — an empty `full_text` produces an empty container bubble (header only). The method DOES correctly clean up the streaming widget (line 589: removes the streaming bubble) and pops the `_streaming_bubbles` entry (line 577) regardless of text content.
- **Traced the two options:** Option A (guard in `_do_response_complete`) is surgical — only the caller created by the BUG #21 fix is affected. Option B (guard in `end_streaming`) is more generic but could mask legitimate empty-bubble cases from other callers. **Option A is correct** — the empty bubble is an artifact of the BUG #21 fix's empty-delta mechanism, not a general rendering concern.
- **Architecture owner:** `AgentRuntimeHandler._do_response_complete` (§3.21v) owns the response-completion logic for local agents. The guard belongs here.

---

## 1. Overview

### Problem
BUG #22: the BUG #21 fix dispatches `_on_text_delta(session_key, "")` at the top of `_run_loop` to guarantee a turn-start signal. For a tool-only turn (LLM streams zero text), this empty delta starts a streaming bubble that never receives content. At turn end, `_do_response_complete` calls `end_streaming` unconditionally, which renders an empty "Coder" header bubble (no body) in the chat. This is a cosmetic artifact, not a correctness bug — the activity drawer is correct.

### Solution
Add a guard in `_do_response_complete`: before calling `end_streaming`, check if the accumulated streaming text is empty. If empty, call `end_streaming` WITHOUT rendering a final bubble (the streaming widget is removed, but no empty header bubble is created). This requires `end_streaming` to support a "suppress render" mode, OR the handler skips `end_streaming` entirely and manually removes the streaming widget.

The cleanest approach: check `get_streaming_text` before calling `end_streaming`. If empty, skip `end_streaming` and instead cancel the streaming bubble (remove the widget without rendering). This avoids touching `end_streaming` (keeping it generic) and localizes the fix to `_do_response_complete`.

### Scope

| In | Out |
|----|-----|
| `ui/handlers/agent_runtime_handler.py` — guard in `_do_response_complete` | `ui/handlers/chat_render_handler.py` (no change — keeps `end_streaming` generic) |
| `tests/test_agent_runtime.py` — 1 regression test | `agent/runtime.py` (no change) |

---

## 2. Changes by File

### 2.1 `ui/handlers/agent_runtime_handler.py`

**Root cause location:** `_do_response_complete`, lines 1417-1419. The `end_streaming` call is unconditional.

**Fix:** Add a check for empty streaming text before the `end_streaming` call. If empty, cancel the streaming bubble (remove widget, no render) instead of finalizing it. Use `end_streaming`'s existing cleanup (it removes the widget and pops the entry) but suppress the final-bubble render by checking text first.

The challenge: `end_streaming` both cleans up AND renders in one call. To suppress the render while keeping the cleanup, we need to either (a) add a `render: bool = True` param to `end_streaming`, or (b) call a cleanup-only path. Reviewing `end_streaming` (lines 575-606): the cleanup (pop entry, remove widget) and the render (`build_role_bubble` + append) are both inside `_finalize` which is dispatched. The simplest surgical fix that doesn't touch `chat_render_handler.py`:

**Check `get_streaming_text` BEFORE calling `end_streaming`. If empty, call `end_streaming` anyway (it cleans up the widget) but the empty bubble it renders is unavoidable without a param.**

Wait — re-reading `end_streaming`, the `_finalize` closure always builds and appends a bubble. To truly suppress the empty bubble WITHOUT modifying `end_streaming`, we'd need a different method. Let me reconsider.

**Revised approach — add an optional `render` param to `end_streaming`:**

This is the cleanest. `end_streaming` already has optional params (`agent_name`). Adding `render: bool = True` is a backward-compatible extension. When `render=False`, the method does the cleanup (pop entry, remove widget) but skips the `build_role_bubble` + append.

This touches `chat_render_handler.py` (one param + one guard) but is minimal and generic-correct: "end streaming, optionally without rendering a final bubble" is a legitimate render API.

**Edit A — `ui/handlers/chat_render_handler.py:544` (signature):**
```python
# OLD:
    def end_streaming(self, session_key: str, agent_name: str = None):
# NEW:
    def end_streaming(self, session_key: str, agent_name: str = None, render: bool = True):
```

**Edit B — `ui/handlers/chat_render_handler.py:595-604` (inside `_finalize`, guard the render):**
```python
# OLD (lines 595-604):
            # Build and append final bubble
            final_bubble = build_role_bubble(
                sb.role, full_text,
                on_forward_click=self._on_forward_message,
                session_key=session_key,
                agent_name=resolved_name,
            )
            sb.container.append(final_bubble)
            if self._main_content is not None:
                self._main_content.scroll_chat_to_bottom()

# NEW:
            if render:
                # Build and append final bubble
                final_bubble = build_role_bubble(
                    sb.role, full_text,
                    on_forward_click=self._on_forward_message,
                    session_key=session_key,
                    agent_name=resolved_name,
                )
                sb.container.append(final_bubble)
                if self._main_content is not None:
                    self._main_content.scroll_chat_to_bottom()
```

**Edit C — `ui/handlers/agent_runtime_handler.py:1417-1419` (the guard in `_do_response_complete`):**
```python
# OLD (lines 1417-1419):
        # Phase B: end_streaming() finalizes the bubble (uses current sb.plain_text).
        # Pass resolved_name so local special agents get their header.
        self._crh.end_streaming(session_key, agent_name=resolved_name)

# NEW:
        # Phase B: end_streaming() finalizes the bubble (uses current sb.plain_text).
        # Pass resolved_name so local special agents get their header.
        # BUG #22: if the streaming text is empty (tool-only turn where the BUG #21
        # empty-delta started a bubble but no content arrived), suppress the final
        # bubble render — the streaming widget is cleaned up, but no empty header
        # bubble is created. end_streaming's render=False does the cleanup only.
        streaming_text = self._crh.get_streaming_text(session_key) or ""
        self._crh.end_streaming(
            session_key,
            agent_name=resolved_name,
            render=bool(streaming_text.strip()),
        )
```

**Traced verification:**
- **Normal text turn:** `streaming_text` is non-empty → `render=True` → `end_streaming` renders the final bubble as before. ✅ No behavior change.
- **Tool-only turn (BUG #22 case):** `streaming_text` is `""` → `render=False` → `end_streaming` cleans up (pops entry, removes widget) but skips `build_role_bubble` + append. No empty header bubble. ✅ Fixed.
- **Turn with whitespace-only text:** `streaming_text.strip()` is `""` → `render=False` → suppressed. This is correct — a whitespace-only bubble is also an artifact.
- **Non-streaming turn (was_streaming=False):** `get_streaming_text` returns `None` (no streaming bubble) → `streaming_text = ""` → `render=False`. BUT: line 1419 calls `end_streaming` which returns early at line 576 (`if session_key not in self._streaming_bubbles: return`). So `render=False` is harmless — the early return fires regardless. ✅ No behavior change for non-streaming turns.

**Files NOT changed:**
- `agent/runtime.py` — unchanged.
- `ui/handlers/activity_wiring_handler.py` — unchanged.

---

### 2.2 `tests/test_agent_runtime.py`

Add 1 regression test to `TestLocalAgentDrawerEmissions`:

**Test — `test_tool_only_turn_no_empty_chat_bubble` (regression for BUG #22):**

```python
def test_tool_only_turn_no_empty_chat_bubble(self):
    """Regression for BUG #22: a tool-only turn (empty streaming text) must
    not render an empty header bubble in the chat.

    The BUG #21 fix dispatches an empty _on_text_delta to clear _ended_sessions,
    which starts a streaming bubble. At turn end, end_streaming must suppress
    the final bubble render when the streaming text is empty.
    """
    handler, crh, mc = self._make_handler_with_agent()
    crh.is_streaming.return_value = False
    chat_box = MagicMock()
    handler._resolve_chat_box = MagicMock(return_value=chat_box)
    handler._crh = crh

    # Simulate the BUG #21 empty-delta turn-start (starts a streaming bubble)
    handler._do_text_delta("special:coder", "")
    # Simulate turn end with no text content (tool-only turn)
    handler._do_response_complete("special:coder", "")

    # end_streaming must have been called with render=False (empty text suppressed)
    crh.end_streaming.assert_called_once()
    call_kwargs = crh.end_streaming.call_args.kwargs
    assert call_kwargs.get("render") is False, (
        f"BUG #22: end_streaming should be called with render=False for empty text; "
        f"got kwargs={call_kwargs}"
    )
```

**Traced verification:** after the fix, `_do_response_complete` reads `get_streaming_text` → `""` → calls `end_streaming(render=False)`. The mock assertion passes. (Note: the mock `crh` returns a MagicMock for `get_streaming_text` by default, which is truthy — the test must stub `crh.get_streaming_text.return_value = ""`. Add that to the setup.)

**Revised test setup:**
```python
    handler._crh = crh
    crh.get_streaming_text.return_value = ""  # empty streaming text (tool-only turn)
```

---

## 3. Data Flow

```
Tool-only turn:
  _run_loop → _on_text_delta(sk, "") → _do_text_delta → start_streaming (empty bubble)
  → tools run (no text deltas)
  → _on_response_complete(sk, "") → _do_response_complete(sk, "")
    → get_streaming_text(sk) → "" → end_streaming(sk, render=False)
      → cleanup: pop _streaming_bubbles, remove widget
      → render=False → skip build_role_bubble + append
    → no empty header bubble rendered ✅
```

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|------------|-------|------|
| `ui/handlers/chat_render_handler.py` | +1 param, +2 indent (guard `if render:`) | ~4 | Low |
| `ui/handlers/agent_runtime_handler.py` | Guard: read streaming text, pass `render=` | ~6 | Low |
| `tests/test_agent_runtime.py` | +1 regression test | ~20 | Low |

## 5. Implementation Order

1. **Read** `ui/handlers/chat_render_handler.py:544-610` (`end_streaming`) to confirm the param insertion and guard location.
2. **Read** `ui/handlers/agent_runtime_handler.py:1417-1419` to confirm the call site.
3. **Edit A:** add `render: bool = True` param to `end_streaming` signature.
4. **Edit B:** guard the `build_role_bubble` + append block inside `_finalize` with `if render:`.
5. **Compile check:** `python3 -m py_compile ui/handlers/chat_render_handler.py`.
6. **Edit C:** add the guard in `_do_response_complete` — read streaming text, pass `render=bool(streaming_text.strip())`.
7. **Compile check:** `python3 -m py_compile ui/handlers/agent_runtime_handler.py`.
8. **Add** the regression test (with `crh.get_streaming_text.return_value = ""`).
9. **Run:** `pytest tests/test_agent_runtime.py::TestLocalAgentDrawerEmissions -v`.

## 6. Acceptance Criteria

- [ ] `end_streaming` signature includes `render: bool = True` (backward-compatible default).
- [ ] Inside `end_streaming._finalize`, the `build_role_bubble` + `sb.container.append` block is guarded by `if render:`.
- [ ] `_do_response_complete` reads `get_streaming_text` and passes `render=bool(streaming_text.strip())` to `end_streaming`.
- [ ] `test_tool_only_turn_no_empty_chat_bubble` passes.
- [ ] All 20 `TestLocalAgentDrawerEmissions` tests pass (19 existing + 1 new).
- [ ] `python3 -m py_compile` on both changed files succeeds.

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Normal text turn (non-empty streaming text) | `render=True` → final bubble rendered (no change) |
| Tool-only turn (empty streaming text) | `render=False` → streaming widget removed, no empty bubble |
| Whitespace-only text | `render=False` (`.strip()` is empty) → suppressed |
| Non-streaming turn (no streaming bubble) | `end_streaming` early-returns (not in `_streaming_bubbles`); `render` value irrelevant |
| Existing callers of `end_streaming` (no `render` arg) | Default `render=True` → no behavior change (backward compatible) |

## 8. ARCHITECTURE.md Updates Required

None. The `render` param is an internal API extension to an existing method; no structural change. §3.14d (ChatRenderHandler) description remains accurate.

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** Yes. `end_streaming` at line 544 confirmed; the `_finalize` closure at lines 583-604 confirmed; the `build_role_bubble` + append at 595-603 confirmed. The `get_streaming_text` return at line 413 confirmed (returns `sb.plain_text` or `None`).
2. **Did I catch all exception types?** N/A — no new exception handling. `get_streaming_text` returns `None` safely (the `or ""` handles it).
3. **Did I verify key structures?** Yes — `_streaming_bubbles` dict, `sb.plain_text` string, the `_finalize` closure structure.
4. **Did I trace the data flow end-to-end?** Yes — traced all five cases in §7 (normal, tool-only, whitespace, non-streaming, backward-compat).
5. **Would an implementer following this spec exactly produce working code?** Yes — three mechanical edits (1 param, 1 guard, 1 call-site change) with exact before/after blocks and line numbers.

The spec is complete.
