# PHASE 10 — P2: YAML Round-Trip

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.3 of the master spec

---

## Files to change

1. `utils/providers_store.py` — update `_to_dict` (line 35-47) and `_from_dict` (line 51-63) to round-trip the new `caller` field

## What to do

**In `utils/providers_store.py`:**

Update `_to_dict` to include `caller` (place it after `default_model` for readability):

```python
def _to_dict(p: ProviderConfig) -> dict[str, Any]:
    """Convert a ProviderConfig to a plain dict for serialization."""
    return {
        "name": p.name,
        "base_url": p.base_url,
        "api_key": p.api_key,
        "default_model": p.default_model,
        "caller": p.caller,
        "enabled": p.enabled,
        "supports_tools": p.supports_tools,
        "supports_streaming": p.supports_streaming,
        "max_tokens": p.max_tokens,
        "last_verified_at": p.last_verified_at,
        "last_error": p.last_error,
    }
```

Update `_from_dict` to read `caller` (tolerate missing key for legacy entries):

```python
def _from_dict(d: dict[str, Any]) -> ProviderConfig:
    """Convert a plain dict to a ProviderConfig. Tolerates missing optional fields."""
    return ProviderConfig(
        name=d.get("name", ""),
        base_url=d.get("base_url", ""),
        api_key=*** ""),
        default_model=d.get("default_model", ""),
        caller=d.get("caller", ""),
        enabled=d.get("enabled", True),
        supports_tools=d.get("supports_tools", True),
        supports_streaming=d.get("supports_streaming", True),
        max_tokens=d.get("max_tokens", 128_000),
        last_verified_at=d.get("last_verified_at"),
        last_error=d.get("last_error"),
    )
```

**IMPORTANT:** The field-order in `ProviderConfig.__init__` (the dataclass `__init__` generated from the field order) is: `name, base_url, api_key, default_model, caller, enabled, supports_tools, supports_streaming, max_tokens, last_verified_at, last_error`. You must pass `caller` as the 5th positional/kwarg in `_from_dict`, between `default_model` and `enabled`.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `utils/providers_store.py` COMPLETELY before editing
- Make ONLY the two function updates; do not touch any other code
- Preserve existing docstrings, comments, and behavior for all other fields
- Do not modify the import block
- Do not add new helpers
- Do not run the full test suite — run only the verification commands below and `tests/test_providers_store.py`

## Verification (mandatory — paste full output)

Run BOTH and paste full output:

```bash
cd /home/q/projects/crabcakes
python3 -c "
from utils.providers_store import _to_dict, _from_dict
from models.providers import ProviderConfig
p = ProviderConfig(name='X', base_url='u', api_key=*** default_model='m', caller='openrouter')
d = _to_dict(p)
assert d['caller'] == 'openrouter', d
p2 = _from_dict(d)
assert p2.caller == 'openrouter', p2.caller
# Legacy entry without caller key
p3 = _from_dict({'name': 'Y', 'base_url': 'u', 'api_key': 'k', 'default_model': 'm'})
assert p3.caller == '', p3.caller
print('OK')
"
```

```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_providers_store.py -q 2>&1 | tail -8
```

## Grep proof

```bash
cd /home/q/projects/crabcakes
grep -n "caller" utils/providers_store.py
```

Should show EXACTLY 2 matches (one in `_to_dict`, one in `_from_dict`).

## Report

- Files changed with line numbers
- Full verification command output
- Grep output
- Pytest output
- A COMPLETENESS checklist (mandatory — see steelFramedCodeWriter Step 6.5)
- Related-bug scan: any other YAML/JSON serialization in this file that touches providers? (Check the rest of `utils/providers_store.py` for completeness.)

## Known-good word marker

Please proceed.
