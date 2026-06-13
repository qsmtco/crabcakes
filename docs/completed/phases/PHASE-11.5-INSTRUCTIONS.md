# PHASE 11.5 — Streaming robustness + ARCHITECTURE.md doc fix

**Master spec:** `docs/specs/PHASE-11.5-STREAMING-ROBUSTNESS.md`

---

## Files to change

1. `agent/runtime.py` — 1 line: BUG-1 fix
2. `tests/test_agent_runtime.py` — add 1 new test method to `TestStreaming`
3. `docs/ARCHITECTURE.md` — 1 paragraph: update §3.21m "Providers" line

## Edit 1: Fix BUG-1 in `agent/runtime.py` (line 1360)

Find:
```python
            elif ev.type == "tool_call_delta":
                idx = ev.data["index"]
```

Replace with:
```python
            elif ev.type == "tool_call_delta":
                # PHASE-11.5: default to 0 if streamer omits 'index' (e.g. Anthropic
                # single-tool responses). Without this, the runtime crashes mid-stream.
                idx = ev.data.get("index", 0)
```

## Edit 2: Add regression test to `tests/test_agent_runtime.py`

Find the end of `TestStreaming` class (the last method `test_streaming_accumulates_text_in_response` ends with `rt.stop()` at around line 738). Add a new test method just before the `class TestStreamingSignature:` line (currently at line 743).

```python
    def test_tool_call_delta_without_index_defaults_to_zero(self):
        """PHASE-11.5 regression: streamer yields tool_call_delta without 'index' key
        should default to idx=0, not crash with KeyError. Anthropic's streaming
        format omits 'index' for single-tool responses.
        """
        rt = AgentRuntime(_make_cfg())
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")

        from agent import runtime as rt_module
        from agent.runtime import SSEEvent

        def streamer_no_index(*a, **kw):
            yield SSEEvent(type="tool_call_delta", data={"name": "list_files", "arguments": '{"path": "."}'})

        orig = rt_module._PROVIDER_STREAMERS["openai"]
        rt_module._PROVIDER_STREAMERS["openai"] = streamer_no_index
        try:
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt._call_llm_streaming(
                session_key=a[0], base_url="https://api.openai.com/v1",
                api_key=*** model="openai/gpt-4o",
                caller_key="openai",
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
                rt._run_loop(sk, "list files")
        finally:
            rt_module._PROVIDER_STREAMERS["openai"] = orig

        conv = rt.get_conversation(sk)
        assistant_msgs = [m for m in conv.messages if m.role.value == "assistant"]
        # If the bug is unfixed, this test crashes with KeyError before reaching here
        assert len(assistant_msgs) >= 1, f"Expected assistant message, got: {[m.role.value for m in conv.messages]}"
        rt.stop()
```

## Edit 3: Update `docs/ARCHITECTURE.md` §3.21m

Find (around line 1411-1412):
```markdown
**Providers:** OpenAI (`openai/*`), MiniMax (`minimax/*`), Anthropic (`anthropic/*`) — selected by model prefix. Tool calls normalized to internal `ToolCall` format regardless of provider.
```

Replace with:
```markdown
**Providers:** OpenAI (`openai/*`), MiniMax (`minimax/*`), Anthropic (`anthropic/*`), OpenRouter (`openrouter/*`), ZAI (`zai/*`) — selected by explicit `caller` field on `LLMProviderConfig` (persisted in `providers.yaml`); falls back to model-prefix derivation for legacy configs without an explicit caller. See §12 for full resolution details. Tool calls normalized to internal `ToolCall` format regardless of provider.
```

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Use the adversarialDebugger prompt at `/home/q/projects/crabcakes/prompts/adversarialDebugger.md` to verify the fix is correct before reporting done
- Make ONLY the 3 edits described above
- Do NOT touch the `_call_llm_streaming` body beyond the 1-line fix
- Do NOT change the test's other patches or assertions
- Do NOT change other sections of ARCHITECTURE.md (only the "Providers" line in §3.21m)

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
# Verify BUG-1 fix
grep -n "ev.data\[.index.\]\|ev.data.get..index" agent/runtime.py
```

Expect: 1 match, using `ev.data.get("index", 0)`. Zero matches for `ev.data["index"]`.

```bash
cd /home/q/projects/crabcakes
# Verify new test exists
grep -n "def test_tool_call_delta_without_index_defaults_to_zero" tests/test_agent_runtime.py
```

Expect: 1 match.

```bash
cd /home/q/projects/crabcakes
# Verify new test passes
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreaming::test_tool_call_delta_without_index_defaults_to_zero -v 2>&1 | tail -8
```

Expect: 1 passed.

```bash
cd /home/q/projects/crabcakes
# Verify the 4 existing TestStreaming tests still pass
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreaming -v 2>&1 | tail -10
```

Expect: 5 passed (4 original + 1 new).

```bash
cd /home/q/projects/crabcakes
# Verify the regression test catches the bug
# Temporarily revert the fix and confirm the test fails
cp agent/runtime.py /tmp/saved_runtime.py
sed -i 's/ev.data.get("index", 0)/ev.data["index"]/' agent/runtime.py
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreaming::test_tool_call_delta_without_index_defaults_to_zero -v 2>&1 | tail -10
cp /tmp/saved_runtime.py agent/runtime.py
echo "Restored fix"
```

Expect: 1 FAILED (KeyError: 'index'). After restore: 1 passed.

```bash
cd /home/q/projects/crabcakes
# Verify ARCHITECTURE.md §3.21m update
grep -n "OpenAI.*MiniMax.*Anthropic.*OpenRouter.*ZAI" docs/ARCHITECTURE.md
```

Expect: 1 match in the updated §3.21m line.

```bash
cd /home/q/projects/crabcakes
# Full test suite
timeout 240 python3 -m pytest tests/ -q --no-header --tb=no 2>&1 | tail -3
```

Expect: 13 failed, 1385 passed, 1 skipped (+1 from new test, 0 regressions).

## Commit

```bash
cd /home/q/projects/crabcakes
git add agent/runtime.py tests/test_agent_runtime.py docs/ARCHITECTURE.md
git commit -m "fix: PHASE-11.5 KeyError on missing 'index' in tool_call_delta + doc update

Adversarial audit found BUG-1: _call_llm_streaming raised KeyError when
a streamer yielded a tool_call_delta without an 'index' key. Some
provider streaming formats (Anthropic) omit 'index' for single-tool
responses. Fix: ev.data.get('index', 0) instead of ev.data['index'].

Adds regression test that yields a tool_call_delta without 'index' and
asserts the runtime doesn't crash. Adversarially verified by temporarily
reverting the fix and confirming the test fails with KeyError.

Also updates docs/ARCHITECTURE.md §3.21m 'Providers' line to mention
all 5 providers (OpenAI, MiniMax, Anthropic, OpenRouter, ZAI) and the
explicit-caller resolution (was stale, only listed 3 providers).

Test results: 13 failed, 1385 passed, 1 skipped (zero regressions)."
```

## Report

- Files changed with line numbers
- Full verification output (all 6 commands)
- Adversarial "revert + fail" output
- Commit hash
- COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.
