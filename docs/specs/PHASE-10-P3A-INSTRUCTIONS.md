# PHASE 10 — P3a: Add `_resolve_caller_key` Static Helper

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.4 of the master spec (the new helper method only; the wiring is P3b)

---

## Files to change

1. `agent/runtime.py` — add `_resolve_caller_key` static method to the `AgentRuntime` class. Add `LLMProviderConfig` to the TYPE_CHECKING import block.

## What to do

**In `agent/runtime.py`:**

1. Add `LLMProviderConfig` to the TYPE_CHECKING import block (around line 27-28). The current block is:

```python
if TYPE_CHECKING:
    from models.conversation import Conversation
```

Change to:

```python
if TYPE_CHECKING:
    from models.conversation import Conversation
    from agent.config import LLMProviderConfig
```

2. Add the `_resolve_caller_key` static method to the `AgentRuntime` class. Place it directly above `_call_llm` (line 1281) — i.e., as a private helper visible to `_call_llm`. The class `AgentRuntime` starts at line 820. Find a good spot just above `_call_llm` (between `_dispatch_approval` at line 1239 and `_call_llm` at line 1281).

Use exactly this implementation (matches the spec §2.4):

```python
    @staticmethod
    def _resolve_caller_key(provider_cfg: "LLMProviderConfig | None", model: str) -> str:
        """Return the API caller key for a provider.

        Resolution order:
        1. provider_cfg.caller (explicit, persisted in providers.yaml)
        2. default_model prefix (e.g. "openrouter/owl-alpha" → "openrouter")
        3. First slash segment of model (legacy behavior)

        Returns the empty string if none of the above yields a non-empty key —
        the caller will then fail with a clear "no caller" error.
        """
        if provider_cfg is not None and provider_cfg.caller:
            return provider_cfg.caller
        # Derive from provider's default_model if present
        if provider_cfg is not None and provider_cfg.default_model:
            return provider_cfg.default_model.split("/")[0]
        # Last resort: model prefix
        return model.split("/")[0] if "/" in model else model
```

**Note on the type hint:** Use the string-quoted forward reference `"LLMProviderConfig | None"` because `LLMProviderConfig` is only imported under `TYPE_CHECKING` (it's a runtime cost to import). This avoids a circular import risk.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `agent/runtime.py` lines 1280–1360 (the `_call_llm` method) and the TYPE_CHECKING block (lines 27–28) COMPLETELY before editing
- Make ONLY the two changes: TYPE_CHECKING import addition + new static method. Do NOT modify `_call_llm` yet — that's P3b.
- Do NOT touch `_PROVIDER_CALLERS`, `_PROVIDER_STREAMERS`, or any other code
- Do NOT run the full test suite — run only the verification commands below and `tests/test_agent_runtime.py`

## Verification (mandatory — paste full output)

Run ALL of these and paste full output:

```bash
cd /home/q/projects/crabcakes
python3 -c "
from agent.config import LLMProviderConfig
from agent.runtime import AgentRuntime

# Test 1: explicit caller wins
pcfg = LLMProviderConfig(name='Owl-Alpha', base_url='', api_key='k', default_model='openrouter/owl-alpha', caller='openrouter')
assert AgentRuntime._resolve_caller_key(pcfg, 'Owl-Alpha/openrouter/owl-alpha') == 'openrouter'
print('Test 1 OK: explicit caller returned')

# Test 2: derivation from default_model when caller is empty
pcfg2 = LLMProviderConfig(name='MiniMax', base_url='', api_key='k', default_model='minimax/MiniMax-M2.7', caller='')
assert AgentRuntime._resolve_caller_key(pcfg2, 'MiniMax') == 'minimax'
print('Test 2 OK: derivation from default_model works')

# Test 3: legacy fallback to model prefix
pcfg3 = LLMProviderConfig(name='Owl', base_url='', api_key='k', default_model='', caller='')
assert AgentRuntime._resolve_caller_key(pcfg3, 'openrouter/owl-alpha') == 'openrouter'
print('Test 3 OK: model prefix fallback works')

# Test 4: None provider_cfg falls through to model
assert AgentRuntime._resolve_caller_key(None, 'openrouter/owl-alpha') == 'openrouter'
print('Test 4 OK: None provider_cfg uses model prefix')

# Test 5: None provider_cfg + no slash in model → returns the model
assert AgentRuntime._resolve_caller_key(None, 'MiniMax-M2.7') == 'MiniMax-M2.7'
print('Test 5 OK: None provider_cfg + no slash returns model as-is')
"
```

```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_agent_runtime.py -q 2>&1 | tail -6
```

## Grep proof

```bash
cd /home/q/projects/crabcakes
grep -n "_resolve_caller_key\|LLMProviderConfig" agent/runtime.py
```

Should show 3 matches: TYPE_CHECKING import (line ~28), method definition (1), and the static method decorator `@staticmethod` (1) — actually that's 2 grep hits for the method + 1 for the import = 3 total. Paste the full output.

## Report

- Files changed with line numbers
- Full verification output (all 5 tests)
- Pytest output
- Grep output
- A COMPLETENESS checklist (mandatory)
- Related-bug scan: are there any other places in `agent/runtime.py` that derive caller from `model.split("/")[0]` that we should consider? (Don't fix them — just report them in the checklist as "related issue found, not fixed in this phase".)

## Known-good word marker

Please proceed.
