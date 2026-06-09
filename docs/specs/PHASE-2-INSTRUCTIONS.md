# PHASE 2 of 9 — Agent Config Wiring

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.4, §2.5, §2.6

## Files to change (3 files)

1. `agent/config.py` — wire `providers.yaml` as canonical, fall back to `agent.json` providers
2. `agent/special_agents.py` — drop `api_key` resolution from `agent_def.get("provider_keys", ...)`
3. `agent/runtime.py` — add `providers.yaml` fallback when `conv.api_key` and `provider_cfg.api_key` are both empty

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly. No deviation.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Sub-phase each file.** Each of the 3 file edits is its own sub-phase. Do them in this order: `agent/config.py` → `agent/special_agents.py` → `agent/runtime.py`. Verify with tests between sub-phases.
- **`app_title` is sacred.** Do NOT touch `app_title` in `special_agents.py:126`. The proposal is explicit that app_title remains per-agent. Only line 125 (the `api_key=...` line) changes.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report. Format is mandatory.

## Discovery — read these files first

1. `agent/config.py` lines 1-100 (imports, dataclasses) and 124-220 (load_agent_config, the `for name, prov in raw.get("providers", {}).items():` loop)
2. `agent/special_agents.py` lines 1-60 (imports, dataclass fields) and 100-140 (where `SpecialAgentDef` is constructed from an `agent_def` dict)
3. `agent/runtime.py` lines 1281-1360 (`_call_llm` function — the patch target is line 1320 `effective_api_key = conv.api_key or provider_cfg.api_key`)
4. `models/providers.py` (from Phase 1) — the new `ProviderConfig` dataclass
5. `utils/providers_store.py` (from Phase 1) — the `load_providers()` function

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 2.1: `agent/config.py` (single focused change)

**Spec §2.4.** Goal: when loading providers, prefer `providers.yaml`; fall back to `agent.json`'s `providers` section; log a one-time warning if falling back. The `enforcement` section in `agent.json` is **unchanged** — keep it as-is.

**Step 1:** Add 3 new optional fields to `LLMProviderConfig` (line 29-37):

Before:
```python
@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
```

After:
```python
@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000          # context window size
    enabled: bool = True
    last_verified_at: str | None = None
    last_error: str | None = None
```

**Step 2:** Add a new private function `_load_providers_from_yaml_or_fallback()` near the top of the file (after imports, before `load_agent_config`). It should:

1. Try `from utils.providers_store import load_providers` and call it.
2. If non-empty list returned: convert each `ProviderConfig` to `LLMProviderConfig` and return the dict.
3. If empty (file missing or empty list): read `agent.json` directly via `json.load(open(config_path))` and return its `providers` section, converted to `LLMProviderConfig`. Log a warning: `"agent.json: providers section is deprecated and will be ignored once providers.yaml is created. Use Settings → Providers to migrate."`
4. If both unavailable: return `{}` (empty dict — runtime will use defaults).

The conversion function `_to_llm_provider(p: ProviderConfig) -> LLMProviderConfig` must copy all 10 fields (7 original + 3 new).

**Step 3:** Modify the `for name, prov in raw.get("providers", {}).items():` loop in `load_agent_config` (line 163). Replace it with:

Before (lines 162-175):
```python
    # Parse providers
    providers: dict[str, LLMProviderConfig] = {}
    for name, prov in raw.get("providers", {}).items():
        if not isinstance(prov, dict):
            continue
        providers[name] = LLMProviderConfig(
            name=name,
            base_url=prov.get("base_url", ""),
            api_key=prov.get("api_key", ""),
            default_model=prov.get("default_model", ""),
            supports_tools=prov.get("supports_tools", True),
            supports_streaming=prov.get("supports_streaming", True),
            max_tokens=prov.get("max_tokens", 128_000),
        )
```

After:
```python
    # Parse providers — prefer providers.yaml (canonical) over agent.json providers
    providers = _load_providers_from_yaml_or_fallback(config_path, raw)
```

Note: `config_path` is in scope (line 138), and `raw` is the already-parsed `agent.json` dict. Pass both to the helper so it can read the agent.json fallback without re-opening the file.

## SUB-PHASE 2.2: `agent/special_agents.py` (single line change)

**Spec §2.5.** Replace line 125 only. Do NOT touch line 126 (`app_title`).

Before (line 125):
```python
            api_key=agent_…ys", {}).get(agent_def.get("provider", ""), "") or agent_def.get("api_key"),
```

After (line 125):
```python
            # Per Phase B: keys are resolved from providers.yaml at runtime, not stored on the agent.
            api_key=agent_def.get("api_key_built_in") and agent_def.get("api_key", "") or "",
```

**Rationale:** Built-in agents (e.g. Coder, Debugger with `api_key_built_in: true`) still need their key sent. User-defined agents have `api_key_built_in=False` and should rely on `providers.yaml`. This preserves the built-in path while dropping the per-agent `provider_keys` resolution for user agents.

**Do NOT delete `api_key` field from `SpecialAgentDef` (line 28).** It's still used for built-in agents.

## SUB-PHASE 2.3: `agent/runtime.py` (add fallback after line 1320)

**Spec §2.6.** The patch is at `agent/runtime.py:1320`. Verify the line is exactly:

```python
        effective_api_key = conv.api_key or provider_cfg.api_key
```

Replace with:

```python
        effective_api_key = conv.api_key or provider_cfg.api_key
        if not effective_api_key:
            # Phase B: providers.yaml is the canonical store for API keys.
            # Fall back to scanning the yaml file when neither conv.api_key nor
            # provider_cfg.api_key is set.
            try:
                from utils.providers_store import load_providers
                for p in load_providers():
                    if p.name == provider_name and p.api_key:
                        effective_api_key = p.api_key
                        break
            except Exception as e:
                logger.warning("Cannot load providers.yaml fallback for %s: %s", provider_name, e)
```

**Do NOT change anything else in `_call_llm`.** Do NOT touch lines 1301-1319 (the `provider_cfg is None` branch). Do NOT touch the Anthropic / OpenAI / MiniMax adapter functions.

## Verification commands (run between sub-phases AND at the end)

```bash
cd /home/q/projects/crabcakes

# 2.1: agent/config.py changes
python3 -c "from agent.config import LLMProviderConfig, load_agent_config; p = LLMProviderConfig(name='t', base_url='u', api_key='k', default_model='m'); print('enabled:', p.enabled, 'last_verified_at:', p.last_verified_at, 'last_error:', p.last_error)"
echo "---"
# Should show: enabled: True, last_verified_at: None, last_error: None

# 2.2: special_agents.py — built-in agents still work
python3 -c "from agent.special_agents import get_special_agents, SpecialAgentDef; agents = get_special_agents(); print(f'{len(agents)} special agents loaded'); [print(f'  {a.display_name}: api_key_built_in={a.api_key_built_in}, api_key_set={bool(a.api_key)}') for a in agents]"

# 2.3: runtime.py compiles
python3 -m py_compile agent/config.py agent/special_agents.py agent/runtime.py
echo "compile exit: $?"

# app_title is still flowing (regression check)
grep -n "app_title" agent/special_agents.py
# Should show line 41 (field) and line 126 (usage)

# full test suite — no regressions
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -15

# new: test that load_agent_config with providers.yaml present uses yaml
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from utils.config import get_config_dir
os.makedirs(get_config_dir(), exist_ok=True)
from utils.providers_store import save_providers
from models.providers import ProviderConfig
save_providers([ProviderConfig(name='testprov', base_url='https://test', api_key='tk', default_model='tm')])
from agent.config import load_agent_config
cfg = load_agent_config()
print('providers:', list(cfg.providers.keys()))
assert 'testprov' in cfg.providers, 'providers.yaml not picked up'
print('OK: providers.yaml is canonical')
" 2>&1 | tail -5

# new: test that load_agent_config falls back to agent.json providers when no yaml
python3 -c "
import os, tempfile, json
os.environ['HOME'] = tempfile.mkdtemp()
from utils.config import get_config_dir
os.makedirs(get_config_dir(), exist_ok=True)
from agent.config import load_agent_config
# Create agent.json with a provider
with open(os.path.join(get_config_dir(), 'agent.json'), 'w') as f:
    json.dump({'providers': {'fallback': {'base_url': 'u', 'api_key': 'k', 'default_model': 'm'}}, 'default_provider': 'fallback', 'default_model': 'fallback/m'}, f)
cfg = load_agent_config()
print('providers (fallback path):', list(cfg.providers.keys()))
assert 'fallback' in cfg.providers, 'agent.json fallback broken'
print('OK: agent.json providers used when no providers.yaml')
" 2>&1 | tail -5
```

## Acceptance criteria for this phase

- [ ] `LLMProviderConfig` has 3 new fields: `enabled`, `last_verified_at`, `last_error`
- [ ] `_load_providers_from_yaml_or_fallback` exists in `agent/config.py` and is called from `load_agent_config`
- [ ] When `providers.yaml` exists and has entries, `load_agent_config` returns those (not `agent.json`)
- [ ] When `providers.yaml` is missing, `load_agent_config` falls back to `agent.json` providers with a warning
- [ ] When neither exists, `load_agent_config` returns empty providers dict
- [ ] `agent/special_agents.py:125` is changed to the new formula; line 126 (`app_title`) is UNCHANGED
- [ ] Built-in special agents (Coder, Debugger, etc.) still get `api_key` set when `api_key_built_in=True`
- [ ] `agent/runtime.py:1320` has the providers.yaml fallback added; nothing else in `_call_llm` changed
- [ ] Full test suite passes (no regressions in any of the ~60+ existing test files)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 2 of 9 — COMPLETE

Files changed:
- agent/config.py — +N / -M lines (paste git diff stats)
- agent/special_agents.py — +N / -M lines
- agent/runtime.py — +N / -M lines

Verification (paste outputs of every command listed above):
- 2.1 LLMProviderConfig fields: ...
- 2.2 special_agents: ...
- 2.3 compile: ...
- app_title unchanged: ...
- full test suite: ...
- providers.yaml canonical: ...
- agent.json fallback: ...

**COMPLETENESS:**
- [x] Sub-phase 2.1: agent/config.py — evidence: <line numbers, test output>
- [x] Sub-phase 2.1: LLMProviderConfig has 3 new fields — evidence: <grep output>
- [x] Sub-phase 2.2: special_agents.py line 125 changed — evidence: <diff line>
- [x] Sub-phase 2.2: line 126 (app_title) UNCHANGED — evidence: <grep -n output>
- [x] Sub-phase 2.3: runtime.py fallback added — evidence: <line number, diff>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (none, or list)

**Implementation choices made:**
- (none, or list with rationale)
```

When done, please write: `Phase 2 complete — ready for audit.`
