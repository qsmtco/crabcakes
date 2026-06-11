# PHASE 11 — Promote `_call_llm_streaming` to a class method on `AgentRuntime`

## Background

`_call_llm_streaming` was added in PHASE-1.3b as a module-level function that takes `runtime` as its first parameter (an `AgentRuntime` instance) — a JavaScript-style pattern that lets the function dispatch callbacks via `runtime._dispatch(...)` and access `runtime._on_text_delta`.

In PHASE-10.5a we added a `caller_key` parameter to it so the streaming path could resolve callers via `AgentRuntime._resolve_caller_key` (symmetric with the non-streaming path). That worked, but it left a 4-line test-coupling problem: the 4 `TestStreaming` patches call `_call_llm_streaming` directly with positional args, and the new required `caller_key` parameter broke them. The fix was a band-aid (`caller_key="openai"` in each patch).

The deeper issue: the function is a method in everything but name. It takes `runtime` as a hidden first arg, accesses `runtime._on_text_delta` and `runtime._dispatch`, and the only reason it's not a method is that the original author wanted to keep `_call_llm` and `_call_llm_streaming` as siblings at module level. That sibling rationale no longer holds — `_call_llm` is already a method on `AgentRuntime` (line 1309), and `_call_llm_streaming` should be too.

## What this phase does

Move `_call_llm_streaming` from a module-level function to a method on `AgentRuntime` (defined inside the class, just below `_call_llm`). The signature drops the `runtime` first parameter and gains `self`. The call site at line 1369 changes from `_call_llm_streaming(runtime=self, ...)` to `self._call_llm_streaming(...)`. The 4 `TestStreaming` test patches change from `rt_module._call_llm_streaming(runtime=rt, ...)` to `rt._call_llm_streaming(...)`.

This eliminates:
- The 4-patches-broke pattern (test patches no longer have to know the parameter list)
- The duplicate `_resolve_caller_key` call (the method has `self._resolve_caller_key` in scope)
- The forward-reference risk (no more calling a class method from a module-level function defined earlier in the same file)
- The parameter-position coupling between production caller and test patches

## Architecture compliance

> Per `docs/ARCHITECTURE.md` §3, the runtime is the single source of truth for LLM I/O. Streaming and blocking are sibling I/O paths; they should be sibling methods on the runtime. This refactor enforces that.

## Files to change

1. `agent/runtime.py` — move `_call_llm_streaming` into the `AgentRuntime` class as a method, update the call site
2. `tests/test_agent_runtime.py` — update the 4 `TestStreaming` test patches
3. `tests/test_agent_runtime.py` — add a new regression test that asserts the streaming method's parameter list matches the non-streaming method's caller-facing interface (catches future signature drift)

## Phases

- **P11.1** — Move the function definition + update the call site (1 source file)
- **P11.2** — Update the 4 test patches (1 test file)
- **P11.3** — Add the regression test + full suite + commit (1 test file, then commit)

## Verification

After all 3 phases:
```bash
cd /home/q/projects/crabcakes
timeout 240 python3 -m pytest tests/ -q --no-header --tb=no
```

Expect: 13 failed, 1383 passed, 1 skipped (same as clean main + 8 P8 tests, zero regressions).

## Success criteria

1. `_call_llm_streaming` is defined as a method inside `AgentRuntime` (indented under `class AgentRuntime:`)
2. The call site at the original line 1369 is `self._call_llm_streaming(...)` with no `runtime=` kwarg
3. All 4 `TestStreaming` test patches call `rt._call_llm_streaming(...)` instead of `rt_module._call_llm_streaming(runtime=rt, ...)`
4. A new test `test_streaming_method_signature_matches_caller_interface` passes
5. Full test suite: 13 failed, 1383 passed (zero new failures)

## Out of scope (deferred)

- Moving `_extract_tool_calls`, `_extract_text_content`, `_extract_usage` into the class. These are pure functions, not method candidates. Keep as module-level.
- Renaming the new method. `_call_llm_streaming` is fine; the `_call_llm` sibling is also named that way.
- Changing the streaming call site to do `caller_key` resolution inside the method. The caller (`_call_llm`) still resolves and passes the key, but now the method receives it as a primitive — same as `model`, `base_url`, `api_key`. No behavioral change.
