# Phase 1 — Bug Fixes from Adversarial Audit

**Source:** adversarialDebugger audit of QTR's Phase 1 commit (`ui/wiring.py` — `agent_builder_factory` addition)
**File to change:** `ui/wiring.py` only

## BUG #[1] (CRITICAL) — Unprotected initial toolbar status call

**Problem:** Line 62 of `ui/wiring.py`:
```python
toolbar.set_settings_status(has_any_verified_provider(load_providers()))
```
is not wrapped in try/except. If `toolbar.set_settings_status` raises (toolbar destroyed, mock with side_effect, GTK widget disposed), the exception propagates out of `wire_settings_handler` and breaks the wiring. The handler's callback slots ARE set before this line, but the caller may not catch the exception.

**Fix:** Wrap the initial call in try/except. Mirror the pattern used elsewhere in the file.

Replace line 62:
```python
toolbar.set_settings_status(has_any_verified_provider(load_providers()))
```

With:
```python
try:
    toolbar.set_settings_status(has_any_verified_provider(load_providers()))
except Exception as e:
    logger.warning("Initial toolbar status set failed: %s", e)
```

## BUG #[2] (HIGH) — No type guard on `providers` arg

**Problem:** `_on_providers_changed(providers)` has no type annotation. Whatever is passed goes directly to `set_provider_options(providers)` and `refresh_providers(providers)`. Phase 2's `set_provider_options` raises `TypeError` for non-list input, but the wiring's try/except swallows it as a warning. Result: silent dropdown staleness.

**Fix:** Add an `isinstance` guard at the top of `_on_providers_changed`. The contract is `list[ProviderConfig]`.

At the top of `_on_providers_changed(providers)` (before the existing `if settings_dialog_factory is not None:` block):
```python
if not isinstance(providers, list):
    logger.warning(
        "on_providers_changed called with non-list (type=%s); ignoring",
        type(providers).__name__,
    )
    return
```

## BUG #[3] (MEDIUM) — Truthiness check accepts any non-None value

**Problem:** `if builder is not None:` passes for any truthy non-None value (True, 1, "openai", [1,2,3]). Calling `.set_provider_options` on these crashes with AttributeError, caught and logged. The user sees stale dropdown with no visible error.

**Fix:** Add a `hasattr` check.

Replace in the new agent_builder_factory block:
```python
if builder is not None:
    builder.set_provider_options(providers)
```

With:
```python
if builder is not None and hasattr(builder, "set_provider_options"):
    builder.set_provider_options(providers)
else:
    logger.debug("Agent builder factory returned non-dialog: %r", builder)
```

Apply the same fix to the existing settings_dialog_factory block (replace `if dialog is not None:` with `if dialog is not None and hasattr(dialog, "refresh_providers"):` and add the same else branch).

## BUG #[4] (MEDIUM) — Double-wiring silently overwrites first wiring

**Problem:** If `wire_settings_handler` is called twice on the same handler, the second call's closures overwrite the first's. The first call's dialog references become dead. Not a bug today, but a footgun for future refactors.

**Fix:** Make the function idempotent.

At the top of `wire_settings_handler` (after the docstring):
```python
if getattr(handler, "_wired", False):
    logger.debug("Handler already wired; skipping re-wire")
    return handler
handler._wired = True
```

## Verification

After the fix, run:
```bash
cd /home/q/projects/crabcakes

# BUG #1 verify: toolbar crash is now caught
python3 -c "
import logging
logging.basicConfig(level=logging.WARNING)
from unittest.mock import MagicMock
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler
handler = SettingsHandler()
broken = MagicMock()
broken.set_settings_status.side_effect = RuntimeError('toolbar down')
wire_settings_handler(handler, broken)
print('OK — wire_settings_handler did not crash')
" 2>&1 | tail -5
# Expected: 'OK — wire_settings_handler did not crash'

# BUG #2 verify: non-list providers is rejected with warning (not silent TypeError)
python3 -c "
import logging
logging.basicConfig(level=logging.WARNING)
from unittest.mock import MagicMock
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler
handler = SettingsHandler()
t = MagicMock()
b = MagicMock()
wire_settings_handler(handler, t, agent_builder_factory=lambda: b)
handler._on_providers_changed(None)
print('builder.set_provider_options called?:', b.set_provider_options.called)
" 2>&1 | tail -5
# Expected: 'builder.set_provider_options called?: False'

# BUG #3 verify: factory returning True is rejected silently
python3 -c "
import logging
logging.basicConfig(level=logging.WARNING)
from unittest.mock import MagicMock
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler
handler = SettingsHandler()
t = MagicMock()
wire_settings_handler(handler, t, agent_builder_factory=lambda: True)
handler._on_providers_changed([{'name': 'r'}])
print('OK — no crash on truthy non-dialog return')
" 2>&1 | tail -5
# Expected: 'OK — no crash on truthy non-dialog return'

# BUG #4 verify: double-wiring is idempotent
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
from unittest.mock import MagicMock
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler
handler = SettingsHandler()
t = MagicMock()
b1 = MagicMock()
b2 = MagicMock()
wire_settings_handler(handler, t, agent_builder_factory=lambda: b1)
wire_settings_handler(handler, t, agent_builder_factory=lambda: b2)
handler._on_providers_changed([{'name': 'r'}])
print('b1 calls:', b1.set_provider_options.call_count)
print('b2 calls:', b2.set_provider_options.call_count)
print('handler._wired:', handler._wired)
" 2>&1 | tail -5
# Expected: 'b1 calls: 1, b2 calls: 0, handler._wired: True'

# Existing tests should still pass
python3 -m pytest tests/test_window_settings_wiring.py -v --tb=short 2>&1 | tail -10
# Expected: same count passing as before
```

## COMPLETENESS Checklist

- [ ] BUG #1: wrap initial toolbar.set_settings_status in try/except — evidence: grep line
- [ ] BUG #2: isinstance(providers, list) guard in _on_providers_changed — evidence: grep line
- [ ] BUG #3: hasattr check on builder, same fix for dialog — evidence: grep line
- [ ] BUG #4: _wired flag for idempotency — evidence: grep line
- [ ] Tests: existing tests still pass — evidence: pytest tail
- [ ] Verification script 1 (BUG #1): wire_settings_handler survives toolbar crash — evidence: output
- [ ] Verification script 2 (BUG #2): builder.set_provider_options not called for None — evidence: output
- [ ] Verification script 3 (BUG #3): truthy non-dialog return is rejected — evidence: output
- [ ] Verification script 4 (BUG #4): double-wiring is a no-op — evidence: output