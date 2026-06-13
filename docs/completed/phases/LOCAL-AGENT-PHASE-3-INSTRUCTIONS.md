# PHASE 3 — Detect Empty-Content Responses (Class A, part 2)

**Spec:** `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` (see §2.3 and Phase 3 of §5)
**Phase:** 3 of 6
**Risk:** Low (defensive, additive; the load-bearing fix is Phase 2)
**Files changed:** 2 (1 prod, 1 test)

---

## STEP 0 — Read first (mandatory)

1. `prompts/steelFramedCodeWriter.md` — follow EXACTLY, no deviation
2. `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` — sections 2.3, 3 (Flow A)
3. `agent/runtime.py:_run_loop` (line ~960) — specifically the text-only branch (line ~1059)
4. `agent/runtime.py:_on_error` callback signature
5. `tests/test_agent_runtime.py` — existing test patterns (read TestToolLoop, TestStreaming)
6. **Context:** Phase 2 fixed the load-bearing case (MiniMax HTTP-200 body error raises RuntimeError). Phase 3 is defense-in-depth for OTHER failure modes where the LLM response is empty/malformed but doesn't raise.

---

## STEP 1 — Edit 1 of 1: `agent/runtime.py:_run_loop` (line ~1059)

**Find the text-only branch.** It looks like this:

```python
if not tool_calls_raw:
    # Text-only response — done
    logger.debug("[tool-loop] sk=%s text-only response, dispatching on_response_complete len=%d",
                 session_key, len(text_content or ""))
    conv.add_assistant_message(text_content, [])
    self._dispatch(self._on_response_complete, session_key, text_content)
    self._check_and_stop_on_limit(session_key, conv)
    self._auto_save(session_key, conv)
    return
```

**Replace with the version that detects empty-content responses:**

```python
if not tool_calls_raw:
    # No tool calls. Distinguish empty-content responses from normal text-only.
    # An empty response with no `choices` at all usually means the provider
    # returned a malformed/empty payload. Surface it as an error so the user
    # sees something instead of silence.
    if not text_content and not response.get("choices"):
        # Provider returned nothing usable — dispatch _on_error
        logger.warning("[tool-loop] sk=%s LLM returned no choices and no content — treating as error",
                       session_key)
        conv.add_assistant_message("", [])
        self._dispatch(self._on_error, session_key,
                        "Agent returned no content. This may indicate a configuration error "
                        "or an issue with the LLM provider.")
        self._auto_save(session_key, conv)
        return

    # Normal text-only path (unchanged)
    logger.debug("[tool-loop] sk=%s text-only response, dispatching on_response_complete len=%d",
                 session_key, len(text_content or ""))
    conv.add_assistant_message(text_content, [])
    self._dispatch(self._on_response_complete, session_key, text_content)
    self._check_and_stop_on_limit(session_key, conv)
    self._auto_save(session_key, conv)
    return
```

**Variable `loop_provider`:** already defined earlier in `_run_loop` (around line 1031, where `model.split("/")[0] if "/" in model else model` is computed). If you need to verify, grep for it: `grep -n "loop_provider" agent/runtime.py`.

**Verification:** The new branch is reached only when BOTH conditions are true:
- `text_content` is empty/falsy (no `choices[0].message.content`)
- `response.get("choices")` is missing or empty

When triggered, `_on_error` is dispatched (which routes through the callback chain → `agent_runtime_handler._on_error` → `_do_error` → renders `[Error] <message>` bubble). The user sees a visible error message instead of silence.

This branch does NOT fire for:
- Normal text-only responses (`text_content` truthy) — existing path
- Tool-calls responses (`tool_calls_raw` truthy) — enters tool execution branch

---

## STEP 2 — Edit 2: Add 1 test in `tests/test_agent_runtime.py`

**Location:** Append a new test class at the END of `tests/test_agent_runtime.py`. Do not modify any existing test.

**New class name:** `TestEmptyChoicesResponse`

**Test: `test_empty_choices_response_dispatches_on_error`:**
- Build a minimal `AgentRuntime` instance using `_make_cfg()` (helper already in the file).
- Patch `rt._call_llm` so the LLM call returns `{"usage": {}}` (no `choices` key at all).
- Wire `rt._on_error = lambda sk, msg: errors.append(msg)`.
- Call `rt._run_loop(sk, "hello")` (in a thread if needed, since `_run_loop` is the tool loop body).
- Assert: `errors` is non-empty and contains "no content" or "configuration error" in the message.

```python
def test_empty_choices_response_dispatches_on_error(self):
    """LLM response with no 'choices' key at all should dispatch _on_error."""
    cfg = _make_cfg()
    rt = AgentRuntime(cfg)
    rt.start()
    sk = _uniq()
    rt.create_conversation("Coder", sk, "/tmp")

    errors = []
    rt._on_error = lambda sk2, msg: errors.append(msg)

    def mock_caller(sk, msgs, tools):
        return {"usage": {}}  # No 'choices' key

    with unittest.mock.patch.object(rt, "_call_llm", mock_caller):
        rt._run_loop(sk, "hello")

    assert len(errors) >= 1, f"Expected error, got: {errors}"
    assert "no content" in errors[0].lower() or "configuration error" in errors[0].lower(), (
        f"Got: {errors[0]}"
    )
    rt.stop()
```

If `_make_cfg` and `_uniq` are not defined in your test file, you can copy the pattern from `TestToolLoop.test_text_response_callback` (around line 238 in tests/test_agent_runtime.py).

---

## STEP 3 — Run tests, paste output, grep sweep

**Step 3a — Run the new test class:**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py::TestEmptyChoicesResponse -v 2>&1
```

**Step 3b — Run full test_agent_runtime.py (regression check):**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py -v -k "not test_exec_with_approval" 2>&1
```

**Step 3c — Pattern sweep:**
```bash
cd /home/q/projects/crabcakes && grep -n "LLM returned no choices" agent/runtime.py
```
Expected: 1 match.

```bash
cd /home/q/projects/crabcakes && grep -c "response.get..choices" agent/runtime.py
```
Expected: at least 1 match.

---

## STEP 4 — Report back with COMPLETENESS checklist

```
COMPLETENESS:
- [ ] Edit 1: _run_loop empty-content dispatch — evidence: <paste the new line range>
- [ ] Edit 2: TestEmptyChoicesResponse with 1 test — evidence: <paste test definition>
- [ ] Step 3a: new test passes — evidence: <paste pytest output>
- [ ] Step 3b: 0 regressions in test_agent_runtime.py — evidence: <paste pytest summary line>
- [ ] Step 3c-1: exactly 1 match for "LLM returned no choices" — evidence: <paste grep -c output>
- [ ] Step 3c-2: at least 1 match for "response.get..choices" — evidence: <paste grep -c output>
```

---

## RULES — NO DEVIATION

1. Use `prompts/steelFramedCodeWriter.md` — follow EXACTLY.
2. Do NOT modify any file other than `agent/runtime.py` and `tests/test_agent_runtime.py`.
3. Do NOT modify any existing test.
4. Do NOT touch `_call_minimax` or `_stream_minimax_events` (Phase 2's territory).
5. The new branch must dispatch `_on_error`, NOT `_on_response_complete`. The fix is "surface empty responses as errors," not "render an empty bubble."
6. Do NOT change the existing `if not tool_calls_raw:` logic except by adding the new check at the top.

---

**End of Phase 3 instructions. Begin work.**
