# PHASE FOLLOWUP 5 of N — Add `__all__` to `agent/runtime.py`

**Task:** Add `__all__` to `agent/runtime.py` to make the public surface explicit. This prevents future "is this public?" ambiguity.

**Reference:** PHASE-11 post-mortem, "Nice to have #5: Add `__all__` to agent/runtime.py to make the public surface explicit."

## Files to change

1. `agent/runtime.py` — add `__all__` list after `StreamingCallKwargs` definition

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read both files completely before writing any code
- The `__all__` list should include symbols that are imported by other modules:
  - `AgentRuntime` (the main class)
  - `SSEEvent` (namedtuple, used in tests and streaming)
  - `_extract_tool_calls`, `_extract_text_content`, `_extract_usage`, `_cost_for_model` (used in tests)
  - `_PROVIDER_CALLERS`, `_PROVIDER_STREAMERS` (used in audit scripts)
- Keep private/unused functions (like `_model_id`, `_cost_for_model`) exported for test/backward compatibility
- Run: `python3 -c "import agent.runtime; print('OK')"` and confirm no import errors
- Run: `python3 -c "from agent.runtime import AgentRuntime, SSEEvent, StreamingCallKwargs; print('OK')"` and confirm all public symbols import
- Run: `python3 -m pytest tests/test_agent_runtime.py -q --tb=short 2>&1 | tail -10` and paste output
- At the end, include a completeness checklist:
  COMPLETENESS:
  - [x/not done] Edit 1: description — evidence

## Approach

Add `__all__` after the `StreamingCallKwargs` TypedDict definition (line ~54) to explicitly declare the public API. This is purely additive — no behavior changes.