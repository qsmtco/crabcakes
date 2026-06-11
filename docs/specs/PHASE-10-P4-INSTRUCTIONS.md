# PHASE 10 — P4: Stop Double-Prefixing in `_resolve_agent_model`

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.5 of the master spec

---

## Files to change

1. `ui/handlers/agent_runtime_handler.py` — add a guard against double-prefixing in `_resolve_agent_model` (around line 286-289)

## What to do

**In `ui/handlers/agent_runtime_handler.py`:**

Find this code inside `_resolve_agent_model` (around line 286-289):

```python
                prov_cfg = config.providers.get(provider)
                if prov_cfg and prov_cfg.default_model:
                    return f"{provider}/{prov_cfg.default_model}"
```

Replace with:

```python
                prov_cfg = config.providers.get(provider)
                if prov_cfg and prov_cfg.default_model:
                    # If default_model already contains a slash (e.g. "openrouter/owl-alpha"),
                    # it's a fully-qualified model string — return as-is.
                    # Otherwise combine with provider name: "minimax/MiniMax-M2.7".
                    if "/" in prov_cfg.default_model:
                        return prov_cfg.default_model
                    return f"{provider}/{prov_cfg.default_model}"
```

**Why this fix is correct and not "just a band-aid":** the runtime no longer needs the `provider` prefix to determine the caller (it uses `provider_cfg.caller` per P3b). The model string's prefix structure is now purely for the provider's API call. Providers like OpenRouter expect slash-separated model strings of the form `vendor/model` regardless of what the display name is. Returning `default_model` as-is preserves the correct API contract.

**Why we still need the `if "/" in prov_cfg.default_model: return ...` path:** when `default_model` is `"openrouter/owl-alpha"`, prepending the display name `"Owl-Alpha"` would produce `"Owl-Alpha/openrouter/owl-alpha"` — which is broken because:
1. The runtime's `_resolve_caller_key` falls through to the model prefix `"Owl-Alpha"` (not a valid caller key)
2. The model string sent to the API would be wrong (providers like OpenRouter expect just `vendor/model`, not `display_name/vendor/model`)

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `ui/handlers/agent_runtime_handler.py` lines 256-295 COMPLETELY before editing
- Make ONLY the edit described above
- Do NOT touch any other code in the file
- Do NOT modify the import block
- Do NOT modify the docstring above the function

## Verification (mandatory — paste full output)

Run this verification (paste full output):

```bash
cd /home/q/projects/crabcakes
python3 -c "
# Test: _resolve_agent_model should not double-prefix when default_model has a slash
# We verify the logic by examining the function's source code
import inspect
from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
src = inspect.getsource(AgentRuntimeHandler._resolve_agent_model)
# The new guard must be present
assert 'if \"/\" in prov_cfg.default_model:' in src, 'guard not found in source'
# The new branch must return prov_cfg.default_model as-is
assert 'return prov_cfg.default_model' in src, 'return prov_cfg.default_model not found'
print('P4 source check: guard present and returns default_model as-is')
"
```

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_agent_runtime_handler.py -q 2>&1 | tail -6
```

If `tests/test_agent_runtime_handler.py` does not exist, run instead:
```bash
ls /home/q/projects/crabcakes/tests/ | grep -i runtime
```

and run the closest test file.

```bash
cd /home/q/projects/crabcakes
grep -n 'return prov_cfg.default_model' ui/handlers/agent_runtime_handler.py
```

Expected: 2 matches (the new guard's `return prov_cfg.default_model` and the original `return f"{provider}/{prov_cfg.default_model}"`).

## Report

- Files changed with line numbers
- Full verification output
- Pytest output (or the test files you found)
- Grep output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.