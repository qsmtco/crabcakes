# PHASE FOLLOWUP 1 of N — Add TypedDict for Streaming Call Interface

**Task:** Add a `StreamingCallKwargs` TypedDict that defines the exact parameter list for `_call_llm_streaming`. Both the method signature and the PHASE-11 regression test's `expected_params` list should reference this TypedDict. Drift becomes impossible when both the definition and the consumer reference the same type.

**Reference:** PHASE-11 post-mortem, "Should do #3: Add a TypedDict for the streaming call interface."

## Files to change

1. `agent/runtime.py` — add `StreamingCallKwargs` TypedDict, update `_call_llm_streaming` signature to reference it
2. `tests/test_agent_runtime.py` — update `expected_params` in `TestStreamingSignature` to reference the TypedDict instead of hardcoded list

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read both files completely before writing any code
- The TypedDict should define all 9 parameters: `session_key`, `base_url`, `api_key`, `model`, `caller_key`, `messages`, `tools`, `timeout`, `x_title`
- Wire it up — the method signature should use `**kwargs: StreamingCallKwargs` or equivalent so the TypedDict is the single source of truth
- Run: `python3 -c "import agent.runtime; print('OK')"` and confirm no import errors
- Run: `python3 -m pytest tests/test_agent_runtime.py::TestStreamingSignature -v 2>&1 | tail -20` and paste the output
- Report: files changed with line numbers, test results, any issues
- At the end, include a completeness checklist:
  COMPLETENESS:
  - [x/not done] Edit 1: description — evidence
  - [x/not done] Edit 2: description — evidence

## Approach

The TypedDict should be defined near the top of `agent/runtime.py` (near the imports, after type imports). The `_call_llm_streaming` method signature should use `**kwargs` with the TypedDict as the type annotation so that:
1. The method body accesses parameters via `kwargs["param_name"]` (or unpacked)
2. The regression test's `expected_params` is derived from `list(StreamingCallKwargs.__annotations__.keys())`

This way, if someone adds a field to the TypedDict, both the method signature and the test fail automatically.

**Important:** The method must remain functionally identical — do not refactor the body, only the signature and parameter access style. The regression test must continue to pass without modification to its assertions.