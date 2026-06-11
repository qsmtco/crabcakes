# PHASE 10.5a — Wire `_resolve_caller_key` into `_call_llm_streaming`

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` §2.4 (deferred from P3a)
**Adversarial finding:** Post-mortem item #1 — `_PROVIDER_STREAMERS` lookup still keyed by `model.split("/")[0]`, not the resolved caller key. Streaming path can fail for providers with non-slashed `default_model` while non-streaming path works fine.

---

## Files to change

1. `agent/runtime.py` — two edits: add `caller_key` parameter to `_call_llm_streaming`; update the streaming call site at line 1361

## What to do

**Edit 1 — Add `caller_key` parameter to `_call_llm_streaming` (line 553):**

Find the function signature (lines 553-563):
```python
def _call_llm_streaming(
    runtime,  # AgentRuntime instance — for GLib dispatch
    session_key: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
```

Replace with:
```python
def _call_llm_streaming(
    runtime,  # AgentRuntime instance — for GLib dispatch
    session_key: str,
    base_url: str,
    api_key: str,
    model: str,
    caller_key: str,  # PHASE-10.5a: resolved via AgentRuntime._resolve_caller_key
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
```

**Edit 2 — Replace the streamer lookup in `_call_llm_streaming` (line 572-575):**

Find:
```python
    provider_name = model.split("/")[0] if "/" in model else model
    streamer = _PROVIDER_STREAMERS.get(provider_name)
    if streamer is None:
        raise ValueError(f"No streaming caller for provider {provider_name}")
```

Replace with:
```python
    # PHASE-10.5a: use the caller_key resolved by AgentRuntime._resolve_caller_key
    # (explicit caller > default_model prefix > model prefix). This is symmetric with
    # the non-streaming path and fixes the gap where providers with non-slashed
    # default_model would fail streaming but succeed blocking.
    streamer = _PROVIDER_STREAMERS.get(caller_key)
    if streamer is None:
        raise ValueError(
            f"No streaming caller for caller_key={caller_key!r} "
            f"(model={model!r}). Check provider's 'caller' field in Settings → Providers."
        )
```

**Edit 3 — Pass `caller_key` at the streaming call site (around line 1361):**

Find the `_call_llm_streaming` call:
```python
            return _call_llm_streaming(
                runtime=self,
                session_key=session_key,
                base_url=provider_cfg.base_url,
                api_key=effective_api_key,
                model=model,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
                x_title=x_title,
            )
```

Add `caller_key=caller_key` (the `caller_key` variable is already in scope from the P3b edit at line 1373):
```python
            return _call_llm_streaming(
                runtime=self,
                session_key=session_key,
                base_url=provider_cfg.base_url,
                api_key=effective_api_key,
                model=model,
                caller_key=caller_key,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
                x_title=x_title,
            )
```

**Why pass `caller_key` as a parameter (not look it up inside the function):** the streaming function takes `model` and `base_url` and `api_key` as primitives. It does NOT have `provider_cfg` because by the time the streaming function is called, the runtime has already flattened everything. The caller (`_call_llm`) has both `provider_cfg` and `caller_key` in scope, so it's the natural place to resolve the key once and pass it down. This mirrors how `model` is passed — resolved by `_resolve_agent_model` upstream, used as-is downstream.

**Symmetry argument:** the non-streaming path resolves `caller_key` via `self._resolve_caller_key(provider_cfg, model)` at line 1373 (P3b). The streaming path should use the same key. This edit makes the two paths symmetric.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `agent/runtime.py` lines 553-580, 1355-1380 COMPLETELY before editing
- Make ONLY the 3 edits described above
- Do NOT add a `provider_cfg` parameter to `_call_llm_streaming` (would require more callers to update)
- Do NOT call `AgentRuntime._resolve_caller_key` from inside `_call_llm_streaming` (would create a circular import path: function → static method on class defined later in the same file)
- Do NOT touch the `_PROVIDER_CALLERS` lookup at line 1374 (that's already correct from P3b)
- Do NOT touch `_PROVIDER_STREAMERS` dict definition (line 544)

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
python3 -c "
import inspect
from agent.runtime import _call_llm_streaming
sig = inspect.signature(_call_llm_streaming)
assert 'caller_key' in sig.parameters, 'caller_key parameter missing from _call_llm_streaming'
assert 'model' in sig.parameters, 'model parameter missing'
# caller_key should be positioned after model (between model and messages)
params = list(sig.parameters.keys())
assert params.index('caller_key') == params.index('model') + 1, 'caller_key should come right after model'
print('P10.5a source check: caller_key parameter added in correct position')
"
```

```bash
cd /home/q/projects/crabcakes
# Verify the call site passes caller_key
grep -A 1 "_call_llm_streaming(" agent/runtime.py | head -15
```

Expect: the call site shows `caller_key=caller_key,` (or similar) as a keyword argument.

```bash
cd /home/q/projects/crabcakes
# Verify the streamer lookup uses caller_key
grep -n "_PROVIDER_STREAMERS.get" agent/runtime.py
```

Expect: exactly 1 match, using `caller_key` (not `provider_name`).

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_agent_runtime.py -q 2>&1 | tail -5
```

Expect: 53 passed (no regressions to the existing tests).

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_runtime_caller_resolution.py -v 2>&1 | tail -12
```

Expect: 8 passed (P8 tests still pass).

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- Pytest output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.
