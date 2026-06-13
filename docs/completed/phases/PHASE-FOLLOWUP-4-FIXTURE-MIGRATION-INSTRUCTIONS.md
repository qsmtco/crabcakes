# PHASE FOLLOWUP 4 of N — Migrate TestStreaming Patches to Fixture-Based Pattern

**Task:** Replace the 4 hand-rolled lambda patches in `TestStreaming` tests with a reusable `_make_streaming_lambda()` fixture, eliminating duplication and making the test code more maintainable.

**Reference:** PHASE-11 post-mortem, "Nice to have #2: Migrate the 4 test patches to a fixture-based pattern."

## Files to change

1. `tests/test_agent_runtime.py` — add `_make_streaming_lambda()` helper function, update all 4 TestStreaming test patches to use it

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read the entire test file before writing any code
- The fixture should take `rt` (runtime instance) and return a lambda that calls `rt._call_llm_streaming(...)` with the correct kwargs
- Each test patch currently does:
  ```python
  with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt._call_llm_streaming(
      session_key=a[0], base_url="https://api.openai.com/v1",
      api_key="test", model="openai/gpt-4o",
      caller_key="openai",  # PHASE-11: method on AgentRuntime
      messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
  )):
  ```
- Replace with: `with unittest.mock.patch.object(rt, "_call_llm", _make_streaming_lambda(rt))`
- Run: `python3 -c "import tests.test_agent_runtime; print('OK')"` and confirm no import errors
- Run: `python3 -m pytest tests/test_agent_runtime.py::TestStreaming -v 2>&1 | tail -30` and paste the output
- At the end, include a completeness checklist:
  COMPLETENESS:
  - [x/not done] Edit 1: description — evidence
  - [x/not done] Edit 2: description — evidence

## Approach

Add a module-level helper `_make_streaming_lambda(rt)` that returns the lambda. The lambda captures `rt` and the boilerplate params (`base_url`, `api_key`, `model`, `caller_key`, `timeout`). It receives `session_key`, `messages`, `tools` from `_call_llm`'s positional arguments (`*a, **kw`).

This is a pure refactoring — no test assertions or mock streamers change. The only change is removing the inline lambda and calling the helper instead.

**Important:** Do not change any test assertions or mock streamer functions — only the patch setup code. The tests should pass with identical behavior.