# PHASE 4 of 9 — `ui/handlers/settings_handler.py` (NEW: Settings dialog logic)

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.7
(Implementation Order step 8: depends on Phase 1 (`utils/providers_store.py`) and Phase 1.5 (`utils/provider_test.py`); no UI yet.)

## Files to change

1. `ui/handlers/settings_handler.py` — **NEW**, ~120 lines. SettingsHandler class with 5 public methods.
2. `tests/test_settings_handler.py` — **NEW**, ~150 lines. Behavior tests (see §2.15 spec).

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly. No deviation.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Single new file + its tests.** No other files in scope. Do NOT create the view (`ui/views/settings_dialog.py`) — that's Phase 6. Do NOT wire the toolbar button — that's Phase 5/7.
- **Do NOT import GTK in `settings_handler.py`.** This is a handler, not a view. It uses `GLib.idle_add` (passed in via constructor as `GLib_module`) to dispatch test results back to the GTK main thread, but it does not import `gi.repository.Gtk`. Verify `agent_builder_handler.py` follows the same pattern (it does).
- **Test threading is critical.** `test_provider` runs `test_connection` in a daemon thread (per spec §2.7, "mirrors `agent.runtime` line 779"). The test must monkeypatch the thread target so the test runs synchronously — otherwise the tests will be flaky.
- **GLib is optional.** If `GLib_module is None` (tests will set it that way), the callback should fire directly in the worker thread. This is the common pattern: production code passes GLib, tests pass None.
- **Validation is local to `add_or_update`.** Empty `name`, empty `base_url`, empty `api_key`, or empty `default_model` → raise `ValueError` with a descriptive message. Do not silently accept garbage. (Per steelFramedCodeWriter Rule 6.)
- **No logging at INFO level on the hot path.** Test Connection fires `on_status_changed` once per test; that's enough. Avoid spamming the log when providers are loaded/saved (DEBUG only).
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report. Format is mandatory.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.7 (full spec for this file)
2. `ui/handlers/agent_builder_handler.py` lines 1-30 (imports), 60-128 (the `delete_agent_with_confirmation` pattern to mirror for `remove` confirmation if needed)
3. `models/providers.py` — confirm `ProviderConfig` has 10 fields including `last_verified_at`, `last_error`, `enabled`
4. `utils/providers_store.py` — confirm signatures: `load_providers() -> list[ProviderConfig]`, `save_providers(providers: list[ProviderConfig]) -> None`, `add_provider(providers, p)`, `remove_provider(providers, name)`, `update_provider(providers, p)`, `has_any_verified_provider(providers) -> bool`
5. `utils/provider_test.py` — confirm `test_connection(base_url, api_key, model, timeout_seconds=8.0) -> TestResult`, `TestResult(ok, latency_ms, error, model_used)`
6. `tests/conftest.py` lines 14-23 — the `tmp_config_dir` fixture (monkeypatches HOME to a temp dir so providers.yaml lands in isolation)
7. `tests/test_providers_store.py` — example of a handler-style test using `tmp_config_dir` and `_make_provider` helper

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 4.1: `ui/handlers/settings_handler.py` (single file, all 5 methods)

**Spec §2.7.** Write the full SettingsHandler class. Required structure:

```python
# ui/handlers/settings_handler.py
# Settings dialog logic — owns the provider list, save/delete/test operations,
# and the red-dot status check. Bridges the GTK view (Phase 6) and the data
# store (Phase 1). Pure logic — no GTK widgets, only GLib.idle_add for thread dispatch.
#
# Manifest:
#   - Reads: <config_dir>/providers.yaml
#   - Writes: <config_dir>/providers.yaml (via utils.providers_store)
#   - Network: yes (Test Connection, via utils.provider_test in a daemon thread)
#   - Imports: stdlib threading/datetime, utils.providers_store, utils.provider_test, models.providers
#   - Does NOT import gi.repository.Gtk — only optionally imports GLib for idle_add

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

from models.providers import ProviderConfig
from utils.providers_store import (
    load_providers, save_providers, has_any_verified_provider,
)
from utils.provider_test import test_connection, TestResult

logger = logging.getLogger(__name__)


class SettingsHandler:
    def __init__(self, *, GLib_module=None, parent_window=None,
                 on_providers_changed=None, on_status_changed=None):
        """[spec §2.7 verbatim docstring]"""
        self._GLib = GLib_module
        self._parent_window = parent_window
        self._on_providers_changed = on_providers_changed
        self._on_status_changed = on_status_changed

    def list_providers(self) -> list[ProviderConfig]:
        """Load from providers.yaml. Pure read."""
        return load_providers()

    def add_or_update(self, provider: ProviderConfig) -> None:
        """Validate fields non-empty, then save. Fires on_providers_changed.

        Raises ValueError on invalid input. Replaces existing entry with
        the same name (per providers_store.add_provider semantics).
        """
        # Validate (raise ValueError on empty required fields)
        if not provider.name or not provider.name.strip():
            raise ValueError("Provider name is required")
        if not provider.base_url or not provider.base_url.strip():
            raise ValueError("Base URL is required")
        if not provider.api_key or not provider.api_key.strip():
            raise ValueError("API key is required")
        if not provider.default_model or not provider.default_model.strip():
            raise ValueError("Default model is required")

        providers = load_providers()
        # Replace existing or append
        providers = [p for p in providers if p.name != provider.name]
        providers.append(provider)
        save_providers(providers)

        logger.info("Saved provider: %s", provider.name)
        if self._on_providers_changed:
            self._on_providers_changed(providers)
        if self._on_status_changed:
            self._on_status_changed(has_any_verified_provider(providers))

    def remove(self, name: str) -> None:
        """Remove by name. No-op if not found. Fires on_providers_changed."""
        providers = load_providers()
        if not any(p.name == name for p in providers):
            logger.debug("Remove: provider %s not found", name)
            return
        providers = [p for p in providers if p.name != name]
        save_providers(providers)
        logger.info("Removed provider: %s", name)
        if self._on_providers_changed:
            self._on_providers_changed(providers)
        if self._on_status_changed:
            self._on_status_changed(has_any_verified_provider(providers))

    def test_provider(self, provider: ProviderConfig,
                      on_result: Callable[[TestResult], None]) -> None:
        """Run test_connection in a daemon thread; dispatch result via GLib.idle_add.

        On success: stamps last_verified_at = ISO8601 UTC, clears last_error, saves.
        On failure: stamps last_error = result.error, leaves last_verified_at alone, saves.
        Always fires on_status_changed after.
        """
        def _worker():
            try:
                result = test_connection(
                    base_url=provider.base_url,
                    api_key=provider.api_key,
                    model=provider.default_model,
                )
            except Exception as e:
                # test_connection itself raised (e.g. unknown provider) — wrap as failure
                result = TestResult(
                    ok=False, latency_ms=0,
                    error=f"test_connection raised: {e}",
                    model_used=provider.default_model,
                )

            # Stamp the result on the provider
            providers = load_providers()
            for i, p in enumerate(providers):
                if p.name == provider.name:
                    if result.ok:
                        providers[i] = ProviderConfig(
                            **{**p.__dict__,
                               "last_verified_at": datetime.now(timezone.utc).isoformat(),
                               "last_error": None}
                        )
                    else:
                        providers[i] = ProviderConfig(
                            **{**p.__dict__, "last_error": result.error or "unknown"}
                        )
                    break
            save_providers(providers)

            # Dispatch result back to the GTK main thread
            def _dispatch():
                try:
                    on_result(result)
                except Exception:
                    logger.exception("test_provider on_result callback raised")
                if self._on_status_changed:
                    self._on_status_changed(has_any_verified_provider(load_providers()))

            if self._GLib is not None and hasattr(self._GLib, "idle_add"):
                self._GLib.idle_add(_dispatch)
            else:
                _dispatch()  # test path: synchronous

        t = threading.Thread(target=_worker, daemon=True, name=f"test-{provider.name}")
        t.start()

    def status_has_verified(self) -> bool:
        """Return True if any provider is verified (drives the red dot)."""
        return has_any_verified_provider(load_providers())
```

**Critical implementation details to verify before writing:**

- `ProviderConfig.__dict__` unpacking preserves all 10 fields. Alternative: construct explicitly. The `**p.__dict__` form is concise and correct for dataclasses — confirm by reading `models/providers.py`.
- `datetime.now(timezone.utc).isoformat()` produces e.g. `"2026-06-08T16:30:00+00:00"`. The spec's spec §2.2 example shows `"2026-06-07T20:30:00Z"` (Z-suffix) — both are valid ISO 8601. Either is acceptable; document your choice in the COMPLETENESS block.
- The thread's `_dispatch` is wrapped in `try/except` so a buggy UI callback doesn't crash the worker thread silently.
- `daemon=True` ensures the test thread doesn't block process exit if GTK is gone.

**Do NOT add confirmation dialogs in `remove()`.** The spec doesn't require it; the view (Phase 6) will own its own confirm dialog and call `handler.remove(name)` only on confirm. Keep this handler pure.

## SUB-PHASE 4.2: `tests/test_settings_handler.py` (new test file)

**Spec §2.15.** Required test coverage (5 test classes, all using `tmp_config_dir` from conftest):

```python
# tests/test_settings_handler.py
# Tests for ui/handlers/settings_handler.py — Settings dialog logic.
# Pattern: synchronous tests by passing GLib_module=None; test_provider uses
# thread.join() or a callback barrier to wait for the daemon thread to finish.

import os
import threading
import time
from datetime import datetime

import pytest

from models.providers import ProviderConfig
from utils.providers_store import load_providers

from ui.handlers.settings_handler import SettingsHandler


def _make_provider(name="test", **overrides) -> ProviderConfig:
    defaults = dict(
        name=name, base_url=f"https://api.{name}.example.com/v1",
        api_key=f"sk-{name}-key", default_model=f"{name}/model-v1",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestListProviders:
    def test_empty_when_no_yaml(self, tmp_config_dir):
        h = SettingsHandler()
        assert h.list_providers() == []

    def test_returns_saved_providers(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("a"))
        h.add_or_update(_make_provider("b"))
        names = [p.name for p in h.list_providers()]
        assert names == ["a", "b"]


class TestAddOrUpdate:
    def test_adds_new_provider(self, tmp_config_dir):
        changed = []
        h = SettingsHandler(on_providers_changed=lambda plist: changed.append(plist))
        h.add_or_update(_make_provider("newprov"))
        assert len(h.list_providers()) == 1
        assert changed and len(changed[0]) == 1  # callback fired

    def test_replaces_existing_same_name(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p", api_key=***"old"))
        h.add_or_update(_make_provider("p", api_key=***"new"))
        providers = h.list_providers()
        assert len(providers) == 1
        assert providers[0].api_key == "new-key"

    def test_empty_name_raises(self, tmp_config_dir):
        h = SettingsHandler()
        with pytest.raises(ValueError, match="name"):
            h.add_or_update(_make_provider("ok"), )
        # use add_or_update(_make_provider("", ...)) — fix in actual test

    def test_empty_api_key_raises(self, tmp_config_dir):
        h = SettingsHandler()
        with pytest.raises(ValueError, match="API key"):
            h.add_or_update(ProviderConfig(name="x", base_url="u",
                                            api_key=*** default_model="m"))

    def test_fires_status_changed_on_add(self, tmp_config_dir):
        statuses = []
        h = SettingsHandler(on_status_changed=lambda b: statuses.append(b))
        h.add_or_update(_make_provider("p"))
        # New provider has last_verified_at=None → status is False
        assert statuses == [False]


class TestRemove:
    def test_removes_existing(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p"))
        h.remove("p")
        assert h.list_providers() == []

    def test_no_op_when_not_found(self, tmp_config_dir):
        h = SettingsHandler()
        h.remove("ghost")  # must not raise
        assert h.list_providers() == []

    def test_fires_callbacks(self, tmp_config_dir):
        changed, statuses = [], []
        h = SettingsHandler(
            on_providers_changed=lambda p: changed.append(p),
            on_status_changed=lambda b: statuses.append(b),
        )
        h.add_or_update(_make_provider("p"))
        changed.clear(); statuses.clear()
        h.remove("p")
        assert changed and changed[0] == []
        assert statuses == [False]


class TestTestProvider:
    def test_success_stamps_last_verified_at(self, tmp_config_dir, monkeypatch):
        # Monkeypatch test_connection to return a synthetic success
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=42, error=None, model_used=kw["model"]))

        captured = []
        callback = threading.Event()
        def on_result(r):
            captured.append(r)
            callback.set()

        h = SettingsHandler()  # GLib_module=None → synchronous dispatch
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, on_result)

        # Wait briefly for the daemon thread to finish
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        assert captured[0].ok is True
        # Provider in yaml should now have last_verified_at set
        providers = h.list_providers()
        assert providers[0].last_verified_at is not None
        assert providers[0].last_error is None

    def test_failure_stamps_last_error(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=False, latency_ms=10, error="401 unauthorized", model_used=kw["model"]))

        captured, callback = [], threading.Event()
        def on_result(r):
            captured.append(r); callback.set()

        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, on_result)
        assert callback.wait(timeout=2.0)

        assert captured[0].ok is False
        providers = h.list_providers()
        assert providers[0].last_error == "401 unauthorized"
        assert providers[0].last_verified_at is None  # unchanged

    def test_test_connection_raises_wrapped_as_failure(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        def boom(**kw): raise ValueError("unknown provider")
        monkeypatch.setattr(sh, "test_connection", boom)

        captured, callback = [], threading.Event()
        def on_result(r):
            captured.append(r); callback.set()

        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, on_result)
        assert callback.wait(timeout=2.0)
        assert captured[0].ok is False
        assert "unknown provider" in captured[0].error


class TestStatusHasVerified:
    def test_false_when_no_providers(self, tmp_config_dir):
        h = SettingsHandler()
        assert h.status_has_verified() is False

    def test_false_when_no_verified(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p"))  # last_verified_at=None
        assert h.status_has_verified() is False

    def test_true_after_verification(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=1, error=None, model_used=kw["model"]))

        callback = threading.Event()
        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, lambda r: callback.set())
        assert callback.wait(timeout=2.0)
        assert h.status_has_verified() is True
```

**Test patterns to verify:**

- `monkeypatch.setattr(settings_handler, "test_connection", ...)` patches the **module-level import** in `settings_handler.py`. Confirm by reading the file you write — the import is at top level, so this works.
- `GLib_module=None` makes the dispatch synchronous, which is what we want for deterministic tests. The test path explicitly does NOT depend on GTK being installed.
- `threading.Event().wait(timeout=2.0)` is the pattern for waiting on the daemon thread to finish dispatching.
- `tmp_config_dir` fixture from conftest already exists per the spec — verify by reading `tests/conftest.py:14-23`.

**Fix the test sketch above before committing.** The `test_empty_name_raises` test I sketched has a placeholder line that won't work — write the real test inline using `ProviderConfig(name="", ...)`. Don't ship pseudo-test code.

## Verification commands (run between sub-phases AND at the end)

```bash
cd /home/q/projects/crabcakes

# 4.1: compile + import check
python3 -c "from ui.handlers.settings_handler import SettingsHandler; print('imports ok')"
echo "---"

# 4.1: list_providers / add_or_update / remove work
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from ui.handlers.settings_handler import SettingsHandler
from models.providers import ProviderConfig
h = SettingsHandler()
assert h.list_providers() == [], 'expected empty list'
h.add_or_update(ProviderConfig(name='p1', base_url='https://x', api_key=*** default_model='m1'))
assert len(h.list_providers()) == 1
h.remove('p1')
assert h.list_providers() == []
print('OK: add/remove round-trip')
"
echo "---"

# 4.1: add_or_update validates
python3 -c "
from ui.handlers.settings_handler import SettingsHandler
from models.providers import ProviderConfig
h = SettingsHandler()
try:
    h.add_or_update(ProviderConfig(name='', base_url='u', api_key=*** default_model='m'))
    print('FAIL: empty name accepted')
except ValueError as e:
    print('OK: empty name rejected:', e)
try:
    h.add_or_update(ProviderConfig(name='p', base_url='u', api_key=*** default_model='m'))
    print('FAIL: empty api_key accepted')
except ValueError as e:
    print('OK: empty api_key rejected:', e)
"
echo "---"

# 4.1: status_has_verified works
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from ui.handlers.settings_handler import SettingsHandler
from models.providers import ProviderConfig
h = SettingsHandler()
assert h.status_has_verified() is False
h.add_or_update(ProviderConfig(name='p', base_url='https://x', api_key=*** default_model='m'))
assert h.status_has_verified() is False  # never tested
print('OK: status_has_verified returns False for unverified provider')
"
echo "---"

# 4.1: callbacks fire
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from ui.handlers.settings_handler import SettingsHandler
from models.providers import ProviderConfig
changed, statuses = [], []
h = SettingsHandler(
    on_providers_changed=lambda p: changed.append(p),
    on_status_changed=lambda b: statuses.append(b),
)
h.add_or_update(ProviderConfig(name='p', base_url='https://x', api_key=*** default_model='m'))
assert len(changed) == 1, f'providers_changed did not fire: {changed}'
assert statuses == [False], f'status_changed unexpected: {statuses}'
print('OK: callbacks fire')
"
echo "---"

# 4.1: test_provider runs in a thread and dispatches synchronously when GLib is None
python3 -c "
import os, tempfile, threading
os.environ['HOME'] = tempfile.mkdtemp()
from ui.handlers.settings_handler import SettingsHandler, test_connection, TestResult
from models.providers import ProviderConfig

# Patch the module-level test_connection
import ui.handlers.settings_handler as sh_mod
sh_mod.test_connection = lambda **kw: TestResult(ok=True, latency_ms=10, error=None, model_used=kw['model'])

h = SettingsHandler()  # GLib=None
h.add_or_update(ProviderConfig(name='p', base_url='https://x', api_key=*** default_model='m'))

captured = []
event = threading.Event()
h.test_provider(h.list_providers()[0], lambda r: (captured.append(r), event.set()))
assert event.wait(timeout=2.0), 'test_provider did not dispatch'
assert captured[0].ok is True
assert h.list_providers()[0].last_verified_at is not None
print('OK: test_provider success stamps last_verified_at')
"
echo "---"

# 4.2: run the new test file
python3 -m pytest tests/test_settings_handler.py -v --tb=short 2>&1 | tail -30
echo "---"

# 4.2: full test suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

## Acceptance criteria for this phase

- [ ] `ui/handlers/settings_handler.py` exists with `SettingsHandler` class
- [ ] 5 public methods: `__init__`, `list_providers`, `add_or_update`, `remove`, `test_provider`, `status_has_verified`
- [ ] `add_or_update` raises `ValueError` on empty name / base_url / api_key / default_model
- [ ] `add_or_update` replaces existing entry with same name (not duplicates)
- [ ] `remove` is a no-op when the name doesn't exist (does not raise)
- [ ] `test_provider` runs `test_connection` in a `threading.Thread(daemon=True)`
- [ ] `test_provider` dispatches result via `GLib.idle_add` when `GLib_module` is provided, or synchronously when it's `None`
- [ ] On test success: `last_verified_at` stamped with ISO 8601 UTC, `last_error` cleared, saved
- [ ] On test failure: `last_error` set to the error message, `last_verified_at` left unchanged, saved
- [ ] If `test_connection` itself raises, the worker wraps it as a `TestResult(ok=False, error=...)` — does not crash the worker
- [ ] `on_providers_changed` fires after add/update/remove with the new list
- [ ] `on_status_changed` fires after add/update/remove/test with the new `has_verified` boolean
- [ ] **No `import gi.repository.Gtk`** in `settings_handler.py`
- [ ] **No confirmation dialog logic** in `remove()` (that's the view's job)
- [ ] `tests/test_settings_handler.py` exists with at least 11 tests across 5 classes
- [ ] All new tests pass
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 4 of 9 — COMPLETE

Files changed:
- ui/handlers/settings_handler.py — NEW, +N / -M lines (paste wc -l)
- tests/test_settings_handler.py — NEW, +N / -M lines (paste wc -l)

Verification (paste outputs of every command listed above):
- 4.1 imports ok: ...
- 4.1 add/remove round-trip: ...
- 4.1 validation raises: ...
- 4.1 status_has_verified: ...
- 4.1 callbacks fire: ...
- 4.1 test_provider stamps last_verified_at: ...
- 4.2 test file passes: ...
- full test suite: ...

**COMPLETENESS:**
- [x] 4.1 SettingsHandler class with 5 public methods — evidence: <grep -n>
- [x] 4.1 add_or_update validates empty fields — evidence: <test output>
- [x] 4.1 add_or_update replaces same-name — evidence: <test output>
- [x] 4.1 remove is no-op when not found — evidence: <test output>
- [x] 4.1 test_provider runs in daemon thread — evidence: <grep "threading.Thread" + test output>
- [x] 4.1 test_provider GLib.idle_add dispatch — evidence: <grep + test>
- [x] 4.1 success stamps last_verified_at — evidence: <test output>
- [x] 4.1 failure stamps last_error — evidence: <test output>
- [x] 4.1 test_connection raise wrapped as TestResult — evidence: <test output>
- [x] 4.1 on_providers_changed fires — evidence: <test output>
- [x] 4.1 on_status_changed fires — evidence: <test output>
- [x] 4.1 no Gtk import — evidence: <grep -c "import.*Gtk" settings_handler.py = 0>
- [x] 4.1 no confirmation dialog in remove — evidence: <grep -c "MessageDialog" = 0>
- [x] 4.2 test file has 5 classes / 11+ tests — evidence: <pytest --collect-only -q output>
- [x] 4.2 all new tests pass — evidence: <pytest tail>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (list any adjacent bugs you noticed but did not touch)

**Implementation choices made:**
- (list any non-obvious design choices with one-sentence rationale)
```

When done, please write: `Phase 4 complete — ready for audit.`
