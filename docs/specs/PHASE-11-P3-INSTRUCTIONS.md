# PHASE 11.3 — Add regression test for streaming method signature + full suite + commit

**Master spec:** `docs/specs/PHASE-11-STREAMING-CLASS-METHOD.md`
**Depends on:** P11.1, P11.2 (streaming is now a method, test patches call it directly)

---

## Files to change

1. `tests/test_agent_runtime.py` — add ONE new test class with ONE new test method: `TestStreamingSignature::test_streaming_method_signature_matches_caller_interface`

## What to do

**Edit 1 — Add a new test class at the end of `TestStreaming` (just before `class TestSSEParsing:`):**

Find `class TestStreamingSignature:` in `tests/test_agent_runtime.py`. Insert the new test class before it. (If `TestStreamingSignature` doesn't exist yet, find `class TestSSEParsing:` and insert the new class before that.)

Insert this new test class between them:

```python
class TestStreamingSignature:
    """
    PHASE-11 regression test: ensures that the streaming test patches and the
    production caller use a parameter list that is compatible with the actual
    `_call_llm_streaming` method signature.

    Catches: future signature changes to `_call_llm_streaming` that would break
    either the production caller (`_call_llm` in agent/runtime.py) or the 4
    `TestStreaming` test patches.
    """

    def test_streaming_method_signature_matches_caller_interface(self):
        """
        The streaming method's parameter list (after `self`) should match the
        keyword arguments used by the production caller AND by the 4 TestStreaming
        test patches. If any of them drifts, this test fails with a clear
        "signature mismatch" message.
        """
        import inspect
        from agent.runtime import AgentRuntime

        # 1. Get the actual method signature
        sig = inspect.signature(AgentRuntime._call_llm_streaming)
        method_params = [name for name in sig.parameters.keys() if name != "self"]

        # 2. The expected parameter list — derived from StreamingCallKwargs so that
        # changing the TypedDict automatically updates this test. This is the single
        # source of truth for the streaming call interface (PHASE-FOLLOWUP-1).
        from agent.runtime import StreamingCallKwargs
        expected_params = list(StreamingCallKwargs.__annotations__.keys())

        assert method_params == expected_params, (
            f"_call_llm_streaming signature changed.\n"
            f"  Expected: {expected_params}\n"
            f"  Actual:   {method_params}\n"
            f"  If you changed the signature intentionally, update the production\n"
            f"  caller (agent/runtime.py:_call_llm) and the TestStreaming test\n"
            f"  patches (tests/test_agent_runtime.py) to match."
        )

        # 3. Verify the production caller passes all required parameters
        with open("/home/q/projects/crabcakes/agent/runtime.py") as f:
            runtime_source = f.read()
        # Find the call site: `self._call_llm_streaming(`
        call_site_match = runtime_source.find("self._call_llm_streaming(")
        assert call_site_match != -1, "Production caller to self._call_llm_streaming not found"
        # Extract the call (rough — just check for key kwargs)
        call_chunk = runtime_source[call_site_match:call_site_match + 800]
        for required_kw in ["session_key=", "base_url=", "api_key=", "model=", "caller_key=", "messages=", "tools=", "timeout="]:
            assert required_kw in call_chunk, (
                f"Production caller is missing required kwarg {required_kw!r}.\n"
                f"Call site: {call_chunk[:200]}"
            )

        # 4. Verify the 4 TestStreaming patches all use the method on `rt`, not the module
        with open("/home/q/projects/crabcakes/tests/test_agent_runtime.py") as f:
            test_source = f.read()
        rt_module_calls = test_source.count("rt_module._call_llm_streaming(")
        rt_method_calls = test_source.count("rt._call_llm_streaming(")
        assert rt_module_calls == 0, (
            f"Found {rt_module_calls} test patches still calling rt_module._call_llm_streaming.\n"
            f"All 4 TestStreaming patches should call rt._call_llm_streaming() (PHASE-11)."
        )
        assert rt_method_calls >= 4, (
            f"Expected at least 4 test patches calling rt._call_llm_streaming, found {rt_method_calls}."
        )
```

**Edit 2 — Run the full test suite and commit:**

After adding the test, run the full suite. Then commit all Phase 11 changes (1 source file: `agent/runtime.py`, 1 test file: `tests/test_agent_runtime.py`).

## Rules

- Use the adversarialDebugger prompt at `/home/q/projects/crabcakes/prompts/adversarialDebugger.md` to find weak spots in the new test before committing. The test should be adversarial: it should fail if the signature drifts, if the production caller drifts, or if the test patches drift back to the old pattern.
- Read `tests/test_agent_runtime.py` lines 740-760 to find the insertion point
- Do NOT change the existing 4 `TestStreaming` tests
- Do NOT change `agent/runtime.py` (no more code changes — P11.1 and P11.2 already landed)
- The new test class goes AFTER `TestStreaming` and BEFORE `TestSSEParsing`
- The test is intentionally "stringly-typed" (it reads the source files) — this is fine for a regression test that wants to catch coupling between files

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
# Verify the new test class exists
grep -n "class TestStreamingSignature\|def test_streaming_method_signature_matches_caller_interface" tests/test_agent_runtime.py
```

Expect: exactly 1 match for the class, 1 match for the method.

```bash
cd /home/q/projects/crabcakes
# Verify the new test passes
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreamingSignature -v 2>&1 | tail -10
```

Expect: 1 passed.

```bash
cd /home/q/projects/crabcakes
# Verify the new test actually fails when the signature drifts
python3 -c "
import re
with open('tests/test_agent_runtime.py') as f:
    content = f.read()
# Break the test temporarily by removing one param from the expected list
broken = content.replace(
    '\"x_title\",\n        ]',
    ']\n        # Note: x_title removed temporarily for adversarial test'
)
with open('/tmp/broken_test.py', 'w') as f:
    f.write(broken)
print('Wrote broken test to /tmp/broken_test.py')
"
# Now temporarily replace the test file with the broken version, run the test, then restore
cp tests/test_agent_runtime.py /tmp/saved_test.py
cp /tmp/broken_test.py tests/test_agent_runtime.py
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreamingSignature -v 2>&1 | tail -10
cp /tmp/saved_test.py tests/test_agent_runtime.py
echo "Restored original test file"
```

Expect: the adversarial run shows 1 FAILED (with "signature mismatch" message). After restore, the test passes again.

```bash
cd /home/q/projects/crabcakes
# Full test suite
timeout 240 python3 -m pytest tests/ -q --no-header --tb=no 2>&1 | tail -3
```

Expect: 13 failed, 1384 passed, 1 skipped (+1 from the new test, 0 regressions).

## Commit

Stage and commit all changes:

```bash
cd /home/q/projects/crabcakes
git add agent/runtime.py tests/test_agent_runtime.py
git commit -m "refactor: PHASE-11 promote _call_llm_streaming to AgentRuntime method

Move _call_llm_streaming from module-level function to method on
AgentRuntime. The function was already a method in everything but name:
it took 'runtime' as a hidden first arg and accessed runtime._on_text_delta
and runtime._dispatch. Promoting it to a proper method:

- Eliminates the runtime= self kwarg from the call site
- Eliminates the 4-patches-broke pattern (tests can call rt._call_llm_streaming
  instead of rt_module._call_llm_streaming(runtime=rt, ...))
- Eliminates the duplicate _resolve_caller_key call in the streaming path
- Eliminates the forward-reference risk of calling a class method from a
  module-level function defined earlier in the same file

Adds TestStreamingSignature::test_streaming_method_signature_matches_caller_interface
regression test that catches future signature drift in three places:
the method itself, the production caller, and the test patches.

Test results: 13 failed, 1384 passed, 1 skipped (zero regressions)."
```

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- Pytest output (including the adversarial "test fails when signature drifts" run)
- Commit hash
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.
