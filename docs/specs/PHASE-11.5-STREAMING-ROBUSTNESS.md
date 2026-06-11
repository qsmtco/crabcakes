# PHASE 11.5 — Streaming robustness + ARCHITECTURE.md doc fix

## Background

The PHASE-11 adversarial audit found two issues:

1. **BUG-1:** `_call_llm_streaming` raises `KeyError: 'index'` if a streamer yields a `tool_call_delta` event without an `'index'` key. Some provider streaming formats (notably Anthropic's) omit `'index'` for single-tool responses. The fix is one line: use `ev.data.get("index", 0)` instead of `ev.data["index"]`.

2. **DOC-1:** `docs/ARCHITECTURE.md` §3.21m still lists only 3 providers (OpenAI, MiniMax, Anthropic). PHASE-10 added OpenRouter and ZAI, and introduced the explicit `caller` field. The doc is stale.

## What this phase does

1. Fix BUG-1 in `agent/runtime.py` (1-line code change)
2. Add a regression test that yields a `tool_call_delta` without `'index'` and asserts it defaults to 0
3. Update §3.21m to mention all 5 providers and the explicit-caller resolution
4. Verify the full test suite still passes (13 failed, 1385 passed baseline)

## Files to change

1. `agent/runtime.py` — 1 line (line 1360: `ev.data["index"]` → `ev.data.get("index", 0)`)
2. `tests/test_agent_runtime.py` — add 1 new test method to `TestStreaming` class
3. `docs/ARCHITECTURE.md` — update §3.21m "Providers" line

## Verification

```bash
cd /home/q/projects/crabcakes
timeout 240 python3 -m pytest tests/ -q --no-header --tb=no 2>&1 | tail -3
```

Expect: 13 failed, 1385 passed, 1 skipped (+1 from new regression test, 0 regressions).

## Out of scope

- The PHASE-11 audit also flagged design smells (module-level registries, 9-param signature, stringly-typed test). These are deferred.
- The 13 pre-existing test failures are still debt, not in scope.
