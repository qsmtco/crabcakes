# Phase 2 — Bug Fixes from Adversarial Audit

**Source:** adversarialDebugger audit of QTR's Phase 2 commit
**File to change:** `ui/views/agent_builder.py` — `set_provider_options` method (lines 301-330)

## BUG #[1] (MEDIUM) — Add type guard

**Problem:** `set_provider_options` crashes with `AttributeError` when:
- A list contains a `None` element: `set_provider_options([None])`
- A string is passed instead of a list: `set_provider_options("openai")` (iterates chars)
- A dict is passed instead of a list: `set_provider_options({"name": "x"})` (iterates keys)

**Fix:** Add explicit type checks at the top of the method.

Replace the current loop:
```python
for p in providers:
    if isinstance(p, dict):
        normalized.append(ProviderConfig(...))
    else:
        normalized.append(p)
```

With:
```python
for p in providers:
    if isinstance(p, dict):
        normalized.append(ProviderConfig(...))
    elif isinstance(p, ProviderConfig):
        normalized.append(p)
    else:
        raise TypeError(
            f"Each provider must be dict or ProviderConfig, got {type(p).__name__}"
        )
```

Also add at the top of the method (after `if not providers: self._providers = []`):
```python
if not isinstance(providers, list):
    raise TypeError(f"providers must be a list, got {type(providers).__name__}")
```

## BUG #[2] (MEDIUM) — Validate name is non-empty

**Problem:** A dict without a `name` key (or with `name=""`) is silently normalized to a `ProviderConfig(name="")`. The dropdown then shows an empty entry, indistinguishable from "(no providers — open Settings)".

**Fix:** In the dict branch, skip providers with empty name.

In the dict branch:
```python
if isinstance(p, dict):
    name = p.get("name", "").strip() if isinstance(p.get("name"), str) else ""
    if not name:
        continue  # skip providers without a name
    normalized.append(ProviderConfig(
        name=name,
        base_url=p.get("base_url", ""),
        api_key=p.get("api_key", ""),
        default_model=p.get("default_model", ""),
    ))
```

## BUG #[3] (LOW) — Style nit: local import

**Problem:** `from models.providers import ProviderConfig` is inside the method body. It works but is non-idiomatic and breaks IDE type-checking.

**Fix:** Move the import to the top of the file. Check existing imports first — `ProviderConfig` may already be imported.

Run `head -20 ui/views/agent_builder.py` to see the existing imports. If ProviderConfig is not imported, add it. If it is, just remove the local import.

## Verification

After the fix, run:
```bash
cd /home/q/projects/crabcakes

# Should crash with TypeError, not AttributeError
python3 -c "
from models.providers import ProviderConfig
import ui.views.agent_builder as ab
class F: pass
f = F()
ab.AgentBuilderDialog.set_provider_options(f, [None])
" 2>&1 | tail -3
# Expected: TypeError: Each provider must be dict or ProviderConfig, got NoneType

# Should crash with TypeError, not AttributeError
python3 -c "
from models.providers import ProviderConfig
import ui.views.agent_builder as ab
class F: pass
f = F()
ab.AgentBuilderDialog.set_provider_options(f, 'openai')
" 2>&1 | tail -3
# Expected: TypeError: providers must be a list, got str

# Should skip the provider, not crash
python3 -c "
from models.providers import ProviderConfig
import ui.views.agent_builder as ab
class F:
    def _rebuild_provider_dropdown(self):
        pass
f = F()
ab.AgentBuilderDialog.set_provider_options(f, [{'name': '', 'base_url': 'u', 'default_model': 'm'}])
print('OK, providers:', f._providers)
" 2>&1 | tail -3
# Expected: OK, providers: []

# Existing tests should still pass
python3 -m pytest tests/test_window_settings_wiring.py tests/test_agent_builder_handler.py -v --tb=short 2>&1 | tail -10
# Expected: same 18 passed, 5 pre-existing failed
```

## COMPLETENESS Checklist

- [x/not done] BUG #1: type guard for list — evidence: grep
- [x/not done] BUG #1: type guard for element — evidence: grep
- [x/not done] BUG #2: skip empty-name dicts — evidence: grep
- [x/not done] BUG #3: move import to top — evidence: grep
- [x/not done] Tests: existing tests still pass — evidence: pytest tail
- [x/not done] TypeError test for [None] — evidence: python output
- [x/not done] TypeError test for 'openai' — evidence: python output
- [x/not done] Empty-name dict skipped — evidence: python output