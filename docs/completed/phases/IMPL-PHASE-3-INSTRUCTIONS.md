# Phase 3 — Wire `agent_builder_factory` in `ui/window.py`

**Spec:** `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` §2.2

## Context

Phase 1+2 added `agent_builder_factory` to `wire_settings_handler` and fixed `set_provider_options` type mismatch. But the call site in `ui/window.py:225` was NOT updated — it still passes only `settings_dialog_factory`. The `agent_builder_factory` parameter is therefore always `None` and the new wiring block never executes. Phase 3 connects the wiring.

## Files to change

1. `ui/window.py` (1 call site + 1 dead method)

## Rules

- Use the steelFramedCodeWriter prompt at `prompts/steelFramedCodeWriter.md`
- Follow it exactly with no deviation
- Reference `docs/ARCHITECTURE.md` for any architecture rules — this is the window composition root
- Do NOT touch any other file
- Do NOT change any public API

## Change 1: Pass `agent_builder_factory` to `wire_settings_handler`

In `ui/window.py` around line 225, the call is:
```python
self._settings_handler = wire_settings_handler(
    self._settings_handler,
    self._toolbar,
    settings_dialog_factory=lambda: None,
)
```

After this change:
```python
self._settings_handler = wire_settings_handler(
    self._settings_handler,
    self._toolbar,
    settings_dialog_factory=lambda: None,
    agent_builder_factory=lambda: getattr(self, "_builder_dialog", None),
)
```

The factory returns `self._builder_dialog` (the open Agent Builder dialog) if it exists, else `None`. The wiring already handles `None` correctly (no-op). This matches the spec at line 411 of `SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md`.

**Note:** `getattr(self, "_builder_dialog", None)` is used instead of `self._builder_dialog` because `_builder_dialog` is only set after the user clicks the `+ Agent` button. Before that, `getattr` returns `None` safely. The wiring's `is not None` check on the factory output (not the parameter) handles the case where the dialog hasn't been created yet.

## Change 2: Remove the dead `_on_providers_changed` method

In `ui/window.py` lines 753-764 (approximately), the method is:
```python
def _on_providers_changed(self, providers: list) -> None:
    """Refresh the agent builder's provider dropdown after Settings edits.

    NOTE: The spec §2.12 references `self._builder_dialog.set_provider_options(providers)`
    but no such method exists on AgentBuilderDialog. The current architecture builds
    the provider dropdown once at dialog construction from handler.get_provider_options().
    Adding a set_provider_options method is Phase C (spec §2.10) work. For now,
    we log and move on — the user can close/reopen the builder to see new providers.
    """
    if hasattr(self, "_builder_dialog") and self._builder_dialog is not None:
        logger.info("Settings changed; agent builder provider list may be stale until reopened")
```

This method is **dead code**. It is never called — `wire_settings_handler` overwrites `handler._on_providers_changed` with its own callback (which is what's wired into the handler's `add_or_update` and `remove` methods). The window's `_on_providers_changed` is never invoked.

**Delete the entire method** (the `# ── Settings integration ──...` section above it stays). After deletion, `grep -n "_on_providers_changed" ui/window.py` should return 0 matches.

## Verification

After the fix, run:

```bash
cd /home/q/projects/crabcakes

# Confirm agent_builder_factory is now passed
grep -n "agent_builder_factory" ui/window.py
# Expected: 1 match (the call site)

# Confirm dead method is gone
grep -n "_on_providers_changed" ui/window.py
# Expected: 0 matches

# Existing wiring tests still pass
python3 -m pytest tests/test_window_settings_wiring.py -v --tb=short 2>&1 | tail -10
# Expected: 10 passed

# Full chain smoke test: with the new factory, set_provider_options is called
python3 << 'PYEOF'
from unittest.mock import MagicMock
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler

handler = SettingsHandler()
toolbar = MagicMock()
builder = MagicMock()

# Mimic the new call from window.py
class FakeWindow:
    _builder_dialog = builder

fake_window = FakeWindow()

handler = wire_settings_handler(
    handler,
    toolbar,
    settings_dialog_factory=lambda: None,
    agent_builder_factory=lambda: getattr(fake_window, "_builder_dialog", None),
)

# Trigger on_providers_changed via the handler's add_or_update
from models.providers import ProviderConfig
pc = ProviderConfig(name='openai', base_url='u', api_***ey='k', default_model='gpt-4o', enabled=True)
handler.add_or_update(pc)

print('builder.set_provider_options called?:', builder.set_provider_options.called)
print('builder.set_provider_options call_args:', builder.set_provider_options.call_args)
PYEOF
# Expected: builder.set_provider_options called?: True
# Expected: builder.set_provider_options call_args: call([ProviderConfig(...)])

# If _builder_dialog doesn't exist on the window, factory returns None safely
python3 << 'PYEOF'
from unittest.mock import MagicMock
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler

handler = SettingsHandler()
toolbar = MagicMock()
handler = wire_settings_handler(
    handler,
    toolbar,
    settings_dialog_factory=lambda: None,
    agent_builder_factory=lambda: getattr(MagicMock(), "_builder_dialog", None),  # always None
)
from models.providers import ProviderConfig
pc = ProviderConfig(name='openai', base_url='u', api_***ey='k', default_model='gpt-4o', enabled=True)
handler.add_or_update(pc)
print('No crash when _builder_dialog does not exist — OK')
PYEOF
# Expected: No crash

# Architecture compliance: confirm the call is in the composition root (window.py)
grep -n "wire_settings_handler" ui/window.py
# Expected: 1 match (line ~225) — this is the ONLY place wire_settings_handler is called
```

## COMPLETENESS Checklist

- [ ] Change 1: pass `agent_builder_factory=lambda: getattr(self, "_builder_dialog", None)` — evidence: grep
- [ ] Change 2: delete dead `_on_providers_changed` method — evidence: grep returns 0
- [ ] Architecture: still the only wire_settings_handler call site — evidence: grep
- [ ] Tests: existing 10 tests pass — evidence: pytest tail
- [ ] Smoke test: builder.set_provider_options called with new providers — evidence: output
- [ ] Negative test: factory returning None does not crash — evidence: output
