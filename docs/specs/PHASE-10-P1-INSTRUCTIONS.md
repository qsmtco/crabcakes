# PHASE 10 — P1: Schema Additions

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.1 + 2.2 of the master spec

---

## Files to change

1. `agent/config.py` — add `caller: str = ""` field to `LLMProviderConfig` (line 29-40)
2. `models/providers.py` — add `caller: str = ""` field to `ProviderConfig` (line 14-22)

## What to do

**In `agent/config.py`:**

Add the `caller` field to the `LLMProviderConfig` dataclass. Place it AFTER `default_model` and BEFORE `supports_tools`, matching the spec's exact ordering:

```python
@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""                    # NEW: API caller key (openai|minimax|anthropic|openrouter|zai)
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000          # context window size
    enabled: bool = True
    last_verified_at: str | None = None
    last_error: str | None = None
```

Do NOT modify `_to_llm_provider` (line 127) in this phase — that's handled later when the field has actual values to map.

**In `models/providers.py`:**

Add the same field at the same position (after `default_model`):

```python
class ProviderConfig:
    """A single LLM provider card's configuration."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""                    # NEW: API caller key (openai|minimax|anthropic|openrouter|zai)
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    last_verified_at: str | None = None
    last_error: str | None = None
```

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read both files COMPLETELY before editing (Rule 1)
- Make ONLY the two field additions; do not touch any other code in either file (Rule 8)
- Preserve exact field ordering: `name, base_url, api_key, default_model, caller, supports_tools, ...`
- Do not modify any docstrings beyond the existing ones
- Do not touch `_to_llm_provider` (it will be updated in a later phase)
- Do not modify imports
- Do not run any tests other than the two verification commands below

## Verification (mandatory — paste full output)

Run BOTH and paste full output:

```bash
cd /home/q/projects/crabcakes
python3 -c "from agent.config import LLMProviderConfig; c = LLMProviderConfig(name='x', base_url='', api_key=*** default_model=''); assert c.caller == ''; print('LLMProviderConfig.caller default OK:', c.caller)"
python3 -c "from models.providers import ProviderConfig; c = ProviderConfig(name='x', base_url='', api_key=*** default_model=''); assert c.caller == ''; print('ProviderConfig.caller default OK:', c.caller)"
```

## Grep proof

```bash
cd /home/q/projects/crabcakes
grep -n "caller" agent/config.py
grep -n "caller" models/providers.py
```

Each file should show EXACTLY one match (the new field declaration) in addition to any existing matches — paste the full output.

## Report

- Files changed with line numbers
- Full verification command output
- Grep output
- A COMPLETENESS checklist (mandatory — see steelFramedCodeWriter Step 6.5)

## Known-good word marker

Please proceed.
