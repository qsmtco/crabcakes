# PHASE 4 — Defensive Empty-Response Bubble (Class A, part 3)

**Spec:** `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` (see §2.4 and Phase 4 of §5)
**Phase:** 4 of 6
**Risk:** Low (additive defensive render; doesn't change existing happy path)
**Files changed:** 2 (1 prod, 1 test)

---

## STEP 0 — Read first (mandatory)

1. `prompts/steelFramedCodeWriter.md` — follow EXACTLY, no deviation
2. `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` — sections 2.4, 3 (Flow A)
3. `ui/handlers/agent_runtime_handler.py:_do_response_complete` (line 795)
4. `ui/handlers/chat_render_handler.py` — `render_sync` signature (line 326)
5. `tests/test_agent_runtime.py` — existing test patterns (TestStreaming for the streaming path)
6. **Context:** Phases 2-3 made the runtime SURFACE empty/error responses via `_on_error`. Phase 4 is a separate defense-in-depth in the UI: if `_on_response_complete` is somehow called with empty text and no prior streaming bubble was active, render a fallback bubble so the user sees SOMETHING instead of silence.

---

## STEP 1 — Edit 1 of 1: `ui/handlers/agent_runtime_handler.py:_do_response_complete` (line 795)

**Add a new branch BEFORE the existing `if not was_streaming and text:` block** to handle the case where text is empty AND no streaming bubble was active:

```python
# Non-streaming fallback: render from text argument with crabcard extraction
# Defensive: if response completed with empty text and no streaming bubble,
# render a fallback message so the user sees feedback instead of silence.
if not was_streaming and not text:
    chat_box = self._resolve_chat_box(session_key)
    if chat_box is not None:
        fallback_text = "⚠️ Agent returned no content. This may indicate a configuration error or an issue with the LLM provider."
        bubble = self._crh.render_sync(
            "System", fallback_text, session_key, agent_name="System"
        )
        if bubble is not None:
            chat_box.append(bubble)
        self._mc.scroll_chat_to_bottom()

if not was_streaming and text:
    # ... existing rendering block unchanged ...
```

**Verification:** The new branch is reached only when:
- `was_streaming` is False (no streaming bubble was finalized)
- `text` is empty (response came back with no content)

When triggered, a fallback bubble is rendered. The user sees a visible message instead of silence.

This branch does NOT fire for:
- Streaming path (`was_streaming=True`) — `end_streaming()` handles the final render
- Normal text responses (`text` truthy) — existing path

---

## STEP 2 — Edit 2: Add 2 tests in `tests/test_agent_runtime.py`

**Location:** Append a new test class at the END of `tests/test_agent_runtime.py`. Do not modify any existing test.

**New class name:** `TestEmptyResponseFallbackBubble`

**Test 1: `test_empty_response_renders_fallback_bubble`:**
- Build a minimal `AgentRuntimeHandler` setup with `MagicMock` for `crh` (chat render handler) and `mc` (main content).
- Wire `crh.is_streaming.return_value = False`.
- Call `handler._do_response_complete("special:test", "")`.
- Assert: `crh.render_sync` was called with a text argument containing "no content" or "configuration error".

```python
def test_empty_response_renders_fallback_bubble(self):
    """When _on_response_complete fires with empty text and no streaming bubble,
    a fallback bubble is rendered so the user sees feedback."""
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
    crh = unittest.mock.MagicMock()
    crh.is_streaming.return_value = False
    crh.render_sync.return_value = unittest.mock.MagicMock(name="bubble")
    crh.end_streaming = unittest.mock.MagicMock()

    fake_chat_box = unittest.mock.MagicMock()
    mc = unittest.mock.MagicMock()
    mc.get_chat_box_for_session.return_value = fake_chat_box

    handler = AgentRuntimeHandler(main_content=mc, chat_render_handler=crh, GLib_module=None)
    handler._resolve_chat_box = lambda sk: fake_chat_box
    handler._mc = mc
    handler._active_project = ("test_proj", "/tmp/test_proj")

    handler._do_response_complete("special:test", "")

    crh.render_sync.assert_called_once()
    args, kwargs = crh.render_sync.call_args
    fallback = args[1] if len(args) > 1 else kwargs.get("text", "")
    assert "no content" in fallback.lower() or "configuration error" in fallback.lower(), (
        f"Expected fallback message, got: {fallback!r}"
    )
    fake_chat_box.append.assert_called_once()
```

**Test 2: `test_empty_response_with_streaming_does_not_render_extra_bubble`:**
- Same setup as Test 1 but `crh.is_streaming.return_value = True`.
- Call `handler._do_response_complete("special:test", "")`.
- Assert: `crh.render_sync` was NOT called (the streaming path handles its own finalization via `end_streaming`).

```python
def test_empty_response_with_streaming_does_not_render_extra_bubble(self):
    """When streaming is active, end_streaming() handles the final bubble.
    _do_response_complete must NOT render an extra bubble for empty text."""
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
    crh = unittest.mock.MagicMock()
    crh.is_streaming.return_value = True
    crh.end_streaming = unittest.mock.MagicMock()
    crh.render_sync = unittest.mock.MagicMock()  # should NOT be called

    fake_chat_box = unittest.mock.MagicMock()
    mc = unittest.mock.MagicMock()
    mc.get_chat_box_for_session.return_value = fake_chat_box

    handler = AgentRuntimeHandler(main_content=mc, chat_render_handler=crh, GLib_module=None)
    handler._resolve_chat_box = lambda sk: fake_chat_box
    handler._mc = mc
    handler._active_project = ("test_proj", "/tmp/test_proj")

    handler._do_response_complete("special:test", "")

    crh.render_sync.assert_not_called()
    fake_chat_box.append.assert_not_called()
```

---

## STEP 3 — Run tests, paste output, grep sweep

**Step 3a — Run the new test class:**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py::TestEmptyResponseFallbackBubble -v 2>&1
```

**Step 3b — Run full test_agent_runtime.py (regression check):**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py -v -k "not test_exec_with_approval" 2>&1
```

**Step 3c — Pattern sweep:**
```bash
cd /home/q/projects/crabcakes && grep -c "Agent returned no content" ui/handlers/agent_runtime_handler.py
```
Expected: 1.

```bash
cd /home/q/projects/crabcakes && grep -c "if not was_streaming and" ui/handlers/agent_runtime_handler.py
```
Expected: 2 (the new branch and the existing elif).

---

## STEP 4 — Report back with COMPLETENESS checklist

```
COMPLETENESS:
- [ ] Edit 1: _do_response_complete empty-response fallback branch — evidence: <paste the new line range>
- [ ] Edit 2: 2 new tests in TestEmptyResponseFallbackBubble — evidence: <paste test names>
- [ ] Step 3a: new tests pass — evidence: <paste pytest output>
- [ ] Step 3b: 0 regressions in test_agent_runtime.py — evidence: <paste pytest summary line>
- [ ] Step 3c-1: exactly 1 match for "Agent returned no content" — evidence: <paste grep -c output>
- [ ] Step 3c-2: exactly 2 matches for "if not was_streaming and" — evidence: <paste grep -c output>
```

---

## RULES — NO DEVIATION

1. Use `prompts/steelFramedCodeWriter.md` — follow EXACTLY.
2. Do NOT modify any file other than `ui/handlers/agent_runtime_handler.py` and `tests/test_agent_runtime.py`.
3. Do NOT modify any existing test.
4. Do NOT change the existing `if not was_streaming and text:` block — add the new branch BEFORE it.
5. The new branch must render a fallback bubble (visible message), not just log a warning.
6. The new branch must NOT fire when `was_streaming=True` (streaming path handles itself).

---

**End of Phase 4 instructions. Begin work.**
