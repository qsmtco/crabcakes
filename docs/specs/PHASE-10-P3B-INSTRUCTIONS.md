# PHASE 10 — P3b: Wire `_resolve_caller_key` into `_call_llm`

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.4 of the master spec — the two line edits inside `_call_llm` that replace `model.split("/")[0]` caller lookup with `_resolve_caller_key`

**Prerequisite:** P3a must be complete (helper method exists at line 1283).

---

## Files to change

1. `agent/runtime.py` — two targeted edits inside `_call_llm` (method starts at line 1281)

## What to do

**In `agent/runtime.py`, inside `_call_llm`:**

**Edit 1 — Fix the streaming path (the `_call_llm_streaming` call, around line 1346-1347):**

The current streaming code has a comment block and then calls `_call_llm_streaming`. The streaming path doesn't use `_PROVIDER_STREAMERS` directly in `_call_llm` — it passes `provider_cfg` to `_call_llm_streaming`. **No change needed for the streaming path** — the provider_cfg lookup at line 1316 is what matters, and that already uses the fallback path. The fix is at Edit 2.

**Edit 2 — Fix the caller lookup (around line 1352):**

Find this code in `_call_llm`:

```python
        caller = _PROVIDER_CALLERS.get(provider_name)
        if caller is None:
            raise ValueError(f"No caller for provider {provider_name}")
```

Replace with:

```python
        caller_key = self._resolve_caller_key(provider_cfg, model)
        caller = _PROVIDER_CALLERS.get(caller_key)
        if caller is None:
            raise ValueError(
                f"No caller for provider {provider_cfg.name if provider_cfg else provider_name} "
                f"(caller_key={caller_key!r}). "
                f"Set the 'caller' field in Settings → Providers."
            )
```

This replaces the old `model.split("/")[0]` derivation with `self._resolve_caller_key(provider_cfg, model)`, which prefers the explicit `provider_cfg.caller` field.

**Important:** Do NOT change line 1316 (`provider_cfg = config.providers.get(provider_name)`). That lookup still uses the old derivation to find the `provider_cfg`. The `_resolve_caller_key` call is called AFTER we've already found `provider_cfg` — it just refines the caller key from the found config.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `agent/runtime.py` lines 1281–1365 COMPLETELY before editing
- Make ONLY the two edits described above (the caller lookup fix is the main one; the streaming path requires no change)
- Do NOT modify `_PROVIDER_CALLERS`, `_PROVIDER_STREAMERS`, or any other code
- Do NOT touch the streaming `_call_llm_streaming` call or its arguments
- Do NOT run the full test suite — run only the verification commands below

## Verification (mandatory — paste full output)

Run the verification and paste full output:

```bash
cd /home/q/projects/crabcakes
python3 -c "
from agent.config import LLMProviderConfig
from agent.runtime import AgentRuntime

# Test: _resolve_caller_key is now used inside _call_llm caller lookup
# (The actual caller lookup happens after provider_cfg is found.)
# We verify the helper resolves correctly in the same context.
pcfg = LLMProviderConfig(name='Owl-Alpha', base_url='', api_key='', default_model='openrouter/owl-alpha', caller='openrouter')
key = AgentRuntime._resolve_caller_key(pcfg, 'Owl-Alpha/openrouter/owl-alpha')
assert key == 'openrouter', key

# Test: empty caller falls back to derivation
pcfg2 = LLMProviderConfig(name='MiniMax', base_url='', api_key='', default_model='minimax/MiniMax-M2.7', caller='')
key2 = AgentRuntime._resolve_caller_key(pcfg2, 'MiniMax')
assert key2 == 'minimax', key2

print('P3b helper verification: OK')
"
```

```bash
cd /home/q/projects/crabcakes
grep -n "_resolve_caller_key\|_PROVIDER_CALLERS\|No caller for provider" agent/runtime.py
```

Expected: `_resolve_caller_key` appears 1 time (the definition), `No caller for provider` shows the new error message.

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_agent_runtime.py -q 2>&1 | tail -6
```

## Report

- Files changed with line numbers
- Full verification output
- Grep output (3 lines expected for the grep target)
- Pytest output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.