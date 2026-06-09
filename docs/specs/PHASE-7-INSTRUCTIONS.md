# PHASE 7 of 9 — `ui/window.py` wiring (Settings integration) + test

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.12 (`ui/window.py` revision).

## Files to change

1. `ui/window.py` — REVISED. Insert 3 wiring changes: (a) construct `SettingsHandler` with callbacks, (b) pass `on_settings_clicked=self._open_settings` to the toolbar, (c) add `_open_settings` and `_on_providers_changed` private methods. Plus add the import of `SettingsHandler` and the imports from `utils.providers_store`.
2. `tests/test_window_settings_wiring.py` — NEW. Tests that the wiring helper (extracted into a standalone function) correctly connects handler callbacks to the toolbar and the settings dialog.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly. No deviation.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Do NOT modify `ui/handlers/settings_handler.py`** — Phase 4's handler is complete. You call into it.
- **Do NOT modify `ui/views/settings_dialog.py`** — Phase 6's view is complete.
- **Do NOT modify `ui/toolbar.py`** — Phase 5's toolbar is complete.
- **Do NOT modify `ui/styles.py`** — Phases 5/6 CSS is complete.
- **Follow the `_open_agent_builder` pattern** at `ui/window.py:687-707` exactly — same lazy construction, same `self._settings_dialog` attribute, same `show()` call.
- **The Settings dialog is created lazily on first click of the ⚙ button** — mirror the agent builder pattern. Do not construct it in `_build()`.
- **The SettingsHandler IS constructed in `_build()`** — it must be alive before the toolbar button is clicked.
- **Extract a testable wiring helper.** Phase 6's audit flagged that `_on_providers_changed` is the canonical handler→UI callback. To make this testable without spinning up a 500-line window, extract a small standalone function `wire_settings_handler(handler, toolbar, *, settings_dialog_factory=None)` in a new module `ui/wiring.py` (or at the top of `ui/window.py` if you prefer — your call, document the choice). The function:
  - Sets `handler._on_status_changed` to `toolbar.set_settings_status`
  - Sets `handler._on_providers_changed` to a callback that calls `settings_dialog_factory().refresh_providers(providers)` (or `lambda providers: None` if no factory)
  - Sets the initial toolbar status via `toolbar.set_settings_status(handler.status_has_verified())`
  - Returns the wired handler

  The factory pattern lets the test inject a stub dialog without spinning up GTK4 widgets.

- **The `_open_settings` method in `ui/window.py`** calls the factory (which constructs the real `SettingsDialog` lazily), then `show()`s it.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.12 (full spec for this phase)
2. `ui/window.py` lines 93-110 (where the toolbar is constructed in `_build`)
3. `ui/window.py` lines 192-220 (where `AgentBuilderHandler` is constructed — the pattern to mirror for `SettingsHandler`)
4. `ui/window.py` lines 685-715 (the `_open_agent_builder` method — the pattern to mirror for `_open_settings`)
5. `ui/handlers/settings_handler.py` (full file — the `__init__` signature, the `status_has_verified()` method, the private `_on_providers_changed`/`_on_status_changed` attribute names)
6. `ui/toolbar.py` (the `set_settings_status` method signature and behavior)
7. `utils/providers_store.py` (the `load_providers()` and `has_any_verified_provider()` functions for the initial status check)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 7.1: `ui/wiring.py` (NEW, testable wiring helper)

This is the small helper that captures the wiring logic. Defining it here (rather than inline in `ui/window.py`) makes it unit-testable without spinning up the full window.

```python
# ui/wiring.py
# Small wiring helpers for the Settings integration.
# Extracted from ui/window.py to make the SettingsHandler ↔ Toolbar ↔ SettingsDialog
# callback wiring testable in isolation (without constructing the full window).

from __future__ import annotations

from typing import Callable

from ui.handlers.settings_handler import SettingsHandler
from utils.providers_store import has_any_verified_provider, load_providers


def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable | None = None,
) -> SettingsHandler:
    """Wire the SettingsHandler's callbacks to the toolbar and (optionally) the dialog.

    - on_status_changed  → toolbar.set_settings_status(verified)
    - on_providers_changed → settings_dialog_factory().refresh_providers(providers)
      (no-op if no factory is provided — e.g. in tests where the dialog isn't open)
    - Sets initial toolbar status from the current state of providers.yaml.

    Returns the (now-wired) handler, so callers can keep a reference.
    """
    def _on_status_changed(verified: bool) -> None:
        toolbar.set_settings_status(verified)

    def _on_providers_changed(providers) -> None:
        if settings_dialog_factory is not None:
            try:
                dialog = settings_dialog_factory()
                if dialog is not None:
                    dialog.refresh_providers(providers)
            except Exception:
                pass  # dialog may not be open / already destroyed

    # Mutate the handler's private callback slots (per the handler's __init__ API)
    handler._on_status_changed = _on_status_changed
    handler._on_providers_changed = _on_providers_changed

    # Initial status — drives the red dot on the ⚙ button at startup.
    toolbar.set_settings_status(has_any_verified_provider(load_providers()))

    return handler
```

**Design notes:**

- The `_on_providers_changed` is forgiving: if the factory returns `None` (e.g. dialog not yet open) or the call raises (e.g. dialog already destroyed), the toolbar status still updates correctly.
- The factory is a `Callable` that returns the dialog (or `None`). The window's factory creates a `SettingsDialog` and caches it; the test's factory returns a stub.
- The initial status uses `has_any_verified_provider(load_providers())` which is the spec's recommended initial check.
- We mutate `handler._on_providers_changed` directly because the handler exposes them as private attributes. This is the same pattern the spec §2.12 example uses: `on_providers_changed=lambda providers: ...` is passed to the constructor, but the handler only stores it as a private attribute and fires it later. The wiring helper bypasses the constructor and sets the private attributes directly — this is the **only** way to wire the callback for a handler that was already constructed with `None` callbacks (e.g. in the window's `_build()`).

## SUB-PHASE 7.2: `ui/window.py` (3 small insertions)

Apply the following changes:

### Insertion A — imports (top of file, near other handler imports)

After the existing handler imports, add:

```python
from ui.handlers.settings_handler import SettingsHandler
from utils.providers_store import load_providers
```

If `load_providers` is already imported, do not duplicate. If `has_any_verified_provider` is already imported, do not duplicate. **Use the `wire_settings_handler` helper from `ui/wiring.py` for the callback wiring** — do not write a giant lambda chain in `_build()`.

### Insertion B — `_build()` (after `AgentBuilderHandler` construction, around line 207)

```python
# Settings handler — manages provider list, save/delete/test operations
self._settings_handler = SettingsHandler(
    GLib_module=GLib,
    parent_window=self,
    on_providers_changed=None,  # wired via wire_settings_handler below
    on_status_changed=None,
)
```

And import + call the wiring helper (immediately after the `SettingsHandler` construction, before the toolbar construction is fine, or after the toolbar is created — your call, but the wiring needs both `self._settings_handler` and `self._toolbar` to exist). The cleanest place is **immediately after the `Toolbar` is created and stored on `self._toolbar`** (so the wiring has access to it):

```python
# Wire the SettingsHandler callbacks to the toolbar (and lazily to the settings dialog)
from ui.wiring import wire_settings_handler
self._settings_handler = wire_settings_handler(
    self._settings_handler,
    self._toolbar,
    settings_dialog_factory=lambda: getattr(self, "_settings_dialog", None),
)
```

**Note:** We use `getattr(self, "_settings_dialog", None)` for the factory because the dialog is constructed lazily — it may not exist yet on startup. The lambda returns `None` until the first ⚙ click, and the real dialog after.

### Insertion C — toolbar constructor (line 108)

Before:
```python
toolbar = Toolbar(on_connect_clicked=self._on_connect_clicked)
```

After:
```python
toolbar = Toolbar(
    on_connect_clicked=self._on_connect_clicked,
    on_settings_clicked=self._open_settings,
)
```

### Insertion D — `_open_settings` method (add near `_open_agent_builder` at line 687)

Mirror the existing pattern exactly:

```python
def _open_settings(self) -> None:
    """Open the Settings dialog (constructed lazily on first click)."""
    from ui.views.settings_dialog import SettingsDialog
    if not hasattr(self, "_settings_dialog") or self._settings_dialog is None:
        self._settings_dialog = SettingsDialog(
            parent=self,
            handler=self._settings_handler,
            on_close=lambda: None,
        )
    self._settings_dialog.show()
```

### Insertion E — `_on_providers_changed` method (NEW)

Per spec §2.12, the handler's `on_providers_changed` callback (set via the wiring helper) calls this method to refresh the agent builder's provider dropdown after Settings edits:

```python
def _on_providers_changed(self, providers: list) -> None:
    """Refresh the agent builder's provider dropdown after Settings edits.
    The dialog may not be open — guard with hasattr and a try/except.
    """
    if hasattr(self, "_builder_dialog") and self._builder_dialog is not None:
        try:
            # AgentBuilderDialog's provider dropdown is built from
            # agent_builder_handler.get_provider_options() — which now reads from
            # providers.yaml (per Phase 3). The dialog does not need an explicit
            # refresh method; closing and re-opening picks up the new options.
            # For an open dialog, we log and skip — the user can close/reopen.
            logger.info("Settings changed; agent builder provider list may be stale until reopened")
        except Exception:
            logger.exception("Failed to handle providers-changed event")
```

**NOTE on the `set_provider_options` issue:** the spec §2.12 references `self._builder_dialog.set_provider_options(providers)`, but **no such method exists on `AgentBuilderDialog`** (verified via grep). The current architecture builds the provider dropdown once at dialog construction from `handler.get_provider_options()`. Adding a `set_provider_options` method is **out of scope for Phase 7** — that's a Phase C (spec §2.10) simplification. For now, we log and move on. **Document this design choice in the COMPLETENESS block.**

## SUB-PHASE 7.3: `tests/test_window_settings_wiring.py` (new test file)

Test the `wire_settings_handler` helper directly — no GTK4 widgets required. Use a stub toolbar and a stub dialog.

```python
# tests/test_window_settings_wiring.py
# Tests for ui/wiring.py — verifies that the SettingsHandler's callbacks
# are correctly wired to the toolbar and the settings dialog factory.
# No GTK widgets required — we use simple stubs.

import pytest

from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler
from utils.providers_store import load_providers

from models.providers import ProviderConfig


class StubToolbar:
    """Captures set_settings_status calls."""
    def __init__(self):
        self.status_calls: list[bool] = []
    def set_settings_status(self, has_verified: bool) -> None:
        self.status_calls.append(has_verified)


class StubDialog:
    """Captures refresh_providers calls."""
    def __init__(self):
        self.refresh_calls: list[list] = []
    def refresh_providers(self, providers: list) -> None:
        self.refresh_calls.append(list(providers))


def _make_provider(name="test", **overrides) -> ProviderConfig:
    defaults = dict(
        name=name, base_url=f"https://api.{name}.example.com/v1",
        api_key=*** default_model=f"{name}/model-v1",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestWireSettingsHandler:
    def test_returns_the_handler(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        result = wire_settings_handler(h, t)
        assert result is h

    def test_sets_initial_toolbar_status(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        wire_settings_handler(h, t)
        # No providers → status is False
        assert t.status_calls == [False]

    def test_initial_status_true_when_verified_provider_exists(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            __import__("utils.provider_test", fromlist=["TestResult"]).TestResult(
                ok=True, latency_ms=1, error=None, model_used=kw["model"]))
        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        # Now test the provider to set last_verified_at
        import threading
        event = threading.Event()
        h.test_provider(p, lambda r: event.set())
        assert event.wait(timeout=2.0)
        t = StubToolbar()
        wire_settings_handler(h, t)
        assert t.status_calls == [True]


class TestOnStatusChanged:
    def test_add_fires_status_changed(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        wire_settings_handler(h, t)
        t.status_calls.clear()
        h.add_or_update(_make_provider("p"))
        # After add, status should be False (no verified yet)
        assert t.status_calls[-1] is False

    def test_remove_fires_status_changed(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p"))
        t = StubToolbar()
        wire_settings_handler(h, t)
        t.status_calls.clear()
        h.remove("p")
        assert t.status_calls[-1] is False


class TestOnProvidersChanged:
    def test_add_fires_providers_changed_with_factory(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        dlg = StubDialog()
        factory = lambda: dlg
        wire_settings_handler(h, t, settings_dialog_factory=factory)
        h.add_or_update(_make_provider("p1"))
        # StubDialog should have received the new list
        assert len(dlg.refresh_calls) == 1
        assert len(dlg.refresh_calls[0]) == 1
        assert dlg.refresh_calls[0][0].name == "p1"

    def test_remove_fires_providers_changed_with_factory(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        t = StubToolbar()
        dlg = StubDialog()
        factory = lambda: dlg
        wire_settings_handler(h, t, settings_dialog_factory=factory)
        h.remove("p1")
        assert len(dlg.refresh_calls) >= 1
        # Last refresh should have empty list
        assert dlg.refresh_calls[-1] == []

    def test_no_factory_is_safe(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        wire_settings_handler(h, t, settings_dialog_factory=None)
        # Adding a provider should not crash even with no dialog factory
        h.add_or_update(_make_provider("p"))
        # Status callback should still fire
        assert t.status_calls[-1] is False

    def test_factory_returning_none_is_safe(self, tmp_config_dir):
        h = SettingsHandler()
        t = StubToolbar()
        factory = lambda: None  # dialog not open
        wire_settings_handler(h, t, settings_dialog_factory=factory)
        h.add_or_update(_make_provider("p"))
        # Should not crash; status callback should still fire
        assert t.status_calls[-1] is False
```

## Verification commands

```bash
cd /home/q/projects/crabcakes

# 7.1: wiring helper imports
python3 -c "from ui.wiring import wire_settings_handler; print('imports ok')"
echo "---"

# 7.1: wire_settings_handler works end-to-end
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from ui.handlers.settings_handler import SettingsHandler
from ui.wiring import wire_settings_handler
from models.providers import ProviderConfig

class StubToolbar:
    def __init__(self): self.calls = []
    def set_settings_status(self, v): self.calls.append(v)

class StubDialog:
    def __init__(self): self.refreshes = []
    def refresh_providers(self, ps): self.refreshes.append(list(ps))

h = SettingsHandler()
t = StubToolbar()
d = StubDialog()
wire_settings_handler(h, t, settings_dialog_factory=lambda: d)
print('initial status calls:', t.calls)
h.add_or_update(ProviderConfig(name='p', base_url='https://x', api_key=*** default_model='m'))
print('after add status calls:', t.calls)
print('after add dialog refreshes:', len(d.refreshes))
assert t.calls == [False, False], f'expected [False, False], got {t.calls}'
assert len(d.refreshes) == 1, f'expected 1 refresh, got {len(d.refreshes)}'
print('OK: wiring works end-to-end')
"
echo "---"

# 7.2: window.py still imports
python3 -c "import ui.window; print('imports ok')"
echo "---"

# 7.2: window.py has the new methods
grep -nE "def _open_settings|def _on_providers_changed|wire_settings_handler" ui/window.py | head -10
echo "---"

# 7.2: window.py toolbar constructor passes on_settings_clicked
grep -A2 "on_settings_clicked=" ui/window.py | head -10
echo "---"

# 7.3: new test file
python3 -m pytest tests/test_window_settings_wiring.py -v --tb=short 2>&1 | tail -25
echo "---"

# 7.3: full test suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

## Acceptance criteria for this phase

- [ ] `ui/wiring.py` exists with `wire_settings_handler(handler, toolbar, *, settings_dialog_factory=None)` function
- [ ] The helper sets `handler._on_status_changed` to a callback that calls `toolbar.set_settings_status(verified)`
- [ ] The helper sets `handler._on_providers_changed` to a callback that calls `settings_dialog_factory().refresh_providers(providers)` (or no-op if factory is None / returns None)
- [ ] The helper sets the initial toolbar status from the current providers.yaml state
- [ ] The helper returns the (now-wired) handler
- [ ] `ui/window.py` constructs `SettingsHandler` in `_build()` with `on_providers_changed=None, on_status_changed=None` (will be wired immediately after by the helper)
- [ ] `ui/window.py` calls `wire_settings_handler(...)` after the toolbar is created
- [ ] `ui/window.py` passes `on_settings_clicked=self._open_settings` to the `Toolbar` constructor
- [ ] `ui/window.py` defines `_open_settings(self)` that constructs the dialog lazily and calls `show()`
- [ ] `ui/window.py` defines `_on_providers_changed(self, providers)` that handles the agent builder refresh
- [ ] **The `set_provider_options` spec reference is documented as out-of-scope** (no such method exists; Phase C work)
- [ ] `tests/test_window_settings_wiring.py` exists with at least 7 tests across 2+ classes
- [ ] All new tests pass
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 7 of 9 — COMPLETE

Files changed:
- ui/wiring.py — NEW, +N / -M lines (paste wc -l)
- ui/window.py — REVISED, +N / -M lines (paste git diff --stat)
- tests/test_window_settings_wiring.py — NEW, +N / -M lines (paste wc -l)

Verification (paste outputs of every command listed above):
- 7.1 imports ok: ...
- 7.1 wiring works end-to-end: ...
- 7.2 window.py imports: ...
- 7.2 _open_settings and _on_providers_changed present: ...
- 7.2 toolbar constructor passes on_settings_clicked: ...
- 7.3 test file passes: ...
- full test suite: ...

**COMPLETENESS:**
- [x] 7.1 wire_settings_handler exists — evidence: <grep>
- [x] 7.1 sets on_status_changed to toolbar callback — evidence: <test output>
- [x] 7.1 sets on_providers_changed to factory callback — evidence: <test output>
- [x] 7.1 initial toolbar status set — evidence: <test output>
- [x] 7.1 returns handler — evidence: <test output>
- [x] 7.2 SettingsHandler constructed in _build — evidence: <grep>
- [x] 7.2 wire_settings_handler called after toolbar — evidence: <grep>
- [x] 7.2 Toolbar receives on_settings_clicked — evidence: <grep>
- [x] 7.2 _open_settings method — evidence: <grep>
- [x] 7.2 _on_providers_changed method — evidence: <grep>
- [x] 7.2 set_provider_options out-of-scope note — evidence: <in-source comment>
- [x] 7.3 test file has 2+ classes / 7+ tests — evidence: <pytest --collect-only>
- [x] 7.3 all new tests pass — evidence: <pytest tail>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (list any adjacent bugs)

**Implementation choices made:**
- (e.g. "wiring helper extracted to ui/wiring.py for testability" — already documented, but list any other choices)
```

When done, please write: `Phase 7 complete — ready for audit.`
