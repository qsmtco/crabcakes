# PHASE 3 of 9 — `utils/agent_defs.py` (Drop api_key/provider_keys validation, switch provider source)

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.14, §2.16
(Implementation Order step 7: "drop `api_key`/`provider_keys` validation, change `get_available_providers` source.")

## Files to change (1 file)

1. `utils/agent_defs.py` — two focused edits:
   - **Edit 1 (lines 383-388):** remove the `api_key` / `provider_keys` validation block in `validate_agent_def`.
   - **Edit 2 (lines 471-487):** rewire `get_available_providers` to read from `utils.providers_store.load_providers()` instead of `agent.config.load_agent_config()`.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly. No deviation.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Single file, two sub-phases.** Do `validate_agent_def` first, verify, then `get_available_providers`. Both are tiny — but keeping them separate makes regression analysis easier.
- **Do NOT touch `save_provider` or `delete_provider` (lines 500-560).** These are the legacy agent.json mutators. They will be removed in a later phase, but for now they must stay so any code that still imports them doesn't break. (Verified: `ui/handlers/agent_builder_handler.py:191-198` still calls them; tests/test_bug_fixes.py:171-198 still uses them.) Just don't add new callers.
- **Do NOT touch `validate_agent_def`'s other checks** (required fields, type checks, tool-name checks, prompt-file existence, provider-existence, default-model check, filename-collision check). Only the api_key/provider_keys block at lines 383-388 is removed.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report. Format is mandatory.

## Discovery — read these files first

1. `utils/agent_defs.py` lines 1-30 (imports), 300-400 (validate_agent_def), 460-510 (get_available_providers), 500-560 (save_provider / delete_provider — read only, do not modify)
2. `models/providers.py` (Phase 1 deliverable) — confirm `ProviderConfig` has `name`, `base_url`, `default_model`, `api_key`
3. `utils/providers_store.py` (Phase 1 deliverable) — confirm `load_providers() -> list[ProviderConfig]` and that it returns `[]` on missing file
4. `tests/test_agent_defs.py` lines 200-250 (existing `test_valid_agent_no_errors` and friends — should still pass after the validation change)
5. `tests/test_bug_fixes.py` lines 165-200 (the `save_provider` / `delete_provider` round-trip test — must still pass; do not touch those functions)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 3.1: `validate_agent_def` — drop the api_key/provider_keys check

**Spec §2.14.** The block at lines 383-388 of `utils/agent_defs.py` is the only validation that requires API-key material on the agent. Phase B moves that responsibility to "Test Connection in Settings" — the YAML only stores `provider` + `model`.

**Patch (lines 383-388):**

Before:
```python
    # Validate API key for selected provider (skip if built-in)
    if not agent_def.get("api_key_built_in"):
        provider_keys = agent_def.get("provider_keys", {})
        if provider and not provider_keys.get(provider):
            # Check legacy api_key as fallback
            if not agent_def.get("api_key"):
                errors.append(f"API key required for provider '{provider}'")
```

After:
```python
    # Per Phase B: API keys are validated at config time (Test Connection in Settings),
    # not at agent-def-save time. The agent YAML stores provider+model only.
```

Replace the entire 6-line block with the 2-line comment above. No other changes to `validate_agent_def`.

**Rationale (per spec §2.14 + §6.2 acceptance criteria):**
- `validate_agent_def` MUST NOT reject an agent for missing `api_key` / `provider_keys`.
- Legacy `api_key` / `provider_keys` keys in agent YAMLs are silently ignored (the dataclass fields aren't read; see spec §2.5 backward-compat note).

## SUB-PHASE 3.2: `get_available_providers` — read from providers.yaml

**Spec §2.14.** `get_available_providers` currently calls `agent.config.load_agent_config()` and reads `config.providers` (which is the `LLMProviderConfig` map). After Phase 1/2, the canonical source is `utils.providers_store.load_providers()` (returns `list[ProviderConfig]`). The UI dropdown needs the same shape it always did (`[{"name", "base_url", "default_model"}]`), so the function signature and return shape are unchanged.

**Patch (lines 471-487 of current file):**

Before:
```python
def get_available_providers() -> list[dict]:
    """Load agent.json providers → [{name, base_url, default_model}].

    Used by the UI to show provider dropdown.
    """
    try:
        from agent.config import load_agent_config
        config = load_agent_config()
        return [
            {
                "name": name,
                "base_url": prov.base_url,
                "default_model": prov.default_model,
            }
            for name, prov in config.providers.items()
        ]
    except Exception as e:
        logger.debug("Cannot load agent config for providers: %s", e)
        return []
```

After:
```python
def get_available_providers() -> list[dict]:
    """Load providers from providers.yaml → [{name, base_url, default_model}].

    Used by the UI to show provider dropdown. Returns empty list when no
    providers.yaml exists or it's empty (first-run state).
    """
    try:
        from utils.providers_store import load_providers
        return [
            {
                "name": p.name,
                "base_url": p.base_url,
                "default_model": p.default_model,
            }
            for p in load_providers()
        ]
    except Exception as e:
        logger.debug("Cannot load providers.yaml: %s", e)
        return []
```

**Do NOT add new imports at the top of the file** — the `from utils.providers_store import load_providers` lives inside the function (deferred import) to match the pattern in `save_provider` / `delete_provider` (lines 503, 545) and avoid pulling in yaml at module-import time. The spec's verified-imports note (lines 1-15: `os, json, logging, shutil, typing.Any`) confirms no top-level changes are needed.

## Verification commands (run between sub-phases AND at the end)

```bash
cd /home/q/projects/crabcakes

# 3.1: validation no longer rejects missing api_key
python3 -c "
from utils.agent_defs import validate_agent_def
agent = {
    'name': 'NoKeyAgent',
    'prompts': ['system/coder.md'],
    'tools': ['read_file'],
    'provider': 'minimax',
    'model': 'MiniMax-M2.7',
    # NOTE: no api_key, no provider_keys, no api_key_built_in
}
errs = validate_agent_def(agent)
print('errors:', errs)
assert not any('API key' in e for e in errs), 'validate_agent_def still requires api_key'
print('OK: validate_agent_def no longer requires api_key')
"
echo "---"

# 3.1: agent with legacy provider_keys in YAML is accepted (silently ignored)
python3 -c "
from utils.agent_defs import validate_agent_def
agent = {
    'name': 'LegacyAgent',
    'prompts': ['system/coder.md'],
    'tools': ['read_file'],
    'provider': 'minimax',
    'model': 'MiniMax-M2.7',
    'api_key': 'sk-legacy',
    'provider_keys': {'minimax': 'sk-legacy-2'},
}
errs = validate_agent_def(agent)
print('errors (legacy):', errs)
assert not any('API key' in e for e in errs), 'legacy keys should be silently ignored'
print('OK: legacy api_key/provider_keys silently ignored')
"
echo "---"

# 3.2: get_available_providers reads from providers.yaml
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from utils.config import get_config_dir
os.makedirs(get_config_dir(), exist_ok=True)
from utils.providers_store import save_providers
from models.providers import ProviderConfig
save_providers([
    ProviderConfig(name='openrouter', base_url='https://openrouter.ai/api/v1',
                   api_key='sk-or-xxx', default_model='deepseek/deepseek-v4-pro'),
    ProviderConfig(name='minimax', base_url='https://api.minimax.chat/v1',
                   api_key='sk-mm-xxx', default_model='MiniMax-M2.7'),
])
from utils.agent_defs import get_available_providers
provs = get_available_providers()
print('providers from yaml:', [p['name'] for p in provs])
assert {p['name'] for p in provs} == {'openrouter', 'minimax'}, 'get_available_providers not reading yaml'
assert all('base_url' in p and 'default_model' in p for p in provs), 'shape changed'
print('OK: get_available_providers reads from providers.yaml')
" 2>&1 | tail -5
echo "---"

# 3.2: get_available_providers returns [] when no yaml exists
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from utils.config import get_config_dir
os.makedirs(get_config_dir(), exist_ok=True)
# no providers.yaml created
from utils.agent_defs import get_available_providers
provs = get_available_providers()
print('providers (empty home):', provs)
assert provs == [], f'expected empty list, got {provs}'
print('OK: get_available_providers returns [] when no yaml')
"
echo "---"

# compile check
python3 -m py_compile utils/agent_defs.py
echo "compile exit: $?"
echo "---"

# regression: save_provider and delete_provider are untouched
grep -n "^def save_provider\|^def delete_provider\|^def get_available_providers\|^def validate_agent_def" utils/agent_defs.py
echo "---"

# full test suite — no regressions
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -20
```

## Acceptance criteria for this phase

- [ ] `validate_agent_def` no longer adds `"API key required for provider 'X'"` to errors
- [ ] An agent def with **no** `api_key`, **no** `provider_keys`, **no** `api_key_built_in` validates cleanly (modulo other unrelated errors)
- [ ] An agent def with legacy `api_key` + `provider_keys` validates cleanly (keys silently ignored)
- [ ] `get_available_providers` returns `[{name, base_url, default_model}, ...]` from `providers.yaml`
- [ ] `get_available_providers` returns `[]` when no `providers.yaml` exists
- [ ] Return shape unchanged: same dict keys, same dict values, same order semantics (yaml order)
- [ ] `save_provider` and `delete_provider` are UNCHANGED (still mutate `agent.json` — to be removed in a later phase)
- [ ] All other `validate_agent_def` checks UNCHANGED (required fields, type checks, tool names, prompt files, provider existence, default-model fallback, filename collision)
- [ ] Full test suite passes (no regressions; the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 3 of 9 — COMPLETE

Files changed:
- utils/agent_defs.py — +N / -M lines (paste git diff stats)

Verification (paste outputs of every command listed above):
- 3.1 validate_agent_def no api_key check: ...
- 3.1 legacy keys ignored: ...
- 3.2 get_available_providers reads yaml: ...
- 3.2 get_available_providers empty when no yaml: ...
- compile: ...
- save_provider / delete_provider / get_available_providers / validate_agent_def still defined: ...
- full test suite: ...

**COMPLETENESS:**
- [x] Sub-phase 3.1: validate_agent_def lines 383-388 replaced with comment — evidence: <grep + diff>
- [x] Sub-phase 3.1: no-api_key agent validates cleanly — evidence: <paste errors list>
- [x] Sub-phase 3.1: legacy keys silently ignored — evidence: <paste errors list>
- [x] Sub-phase 3.1: other validate_agent_def checks UNCHANGED — evidence: <grep output of required/prompts/tools/provider checks>
- [x] Sub-phase 3.2: get_available_providers reads from providers.yaml — evidence: <paste provider names>
- [x] Sub-phase 3.2: get_available_providers returns [] when no yaml — evidence: <paste>
- [x] Sub-phase 3.2: return shape unchanged (name/base_url/default_model) — evidence: <paste dict>
- [x] save_provider and delete_provider UNCHANGED — evidence: <git diff of lines 500-560 = empty>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (list any adjacent bugs you noticed but did not touch)

**Implementation choices made:**
- (list any non-obvious design choices with one-sentence rationale)
```

When done, please write: `Phase 3 complete — ready for audit.`
