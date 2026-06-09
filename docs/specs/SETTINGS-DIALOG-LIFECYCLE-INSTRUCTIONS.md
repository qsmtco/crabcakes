# SETTINGS-DIALOG-LIFECYCLE — Fix stale-cache-after-destroy bug

## Master spec

`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.8 (Settings dialog view) and §2.12 (window composition root).

## Bug being fixed (verbatim from audit)

`ui/window.py:744-752` caches the `SettingsDialog` on `self._settings_dialog` after first construction, but the cache is never invalidated when the underlying `Gtk.Window` is destroyed. Repro: open Settings → click **Close** → click ⚙ again → `present()` is called on a destroyed window → GTK warning + dialog non-responsive. User-fills-and-save then wedges the app.

## Files to change

1. `ui/window.py` — REVISED. Connect a destroy hook that clears `self._settings_dialog` when the underlying `Gtk.Window` is destroyed.
2. `ui/views/settings_dialog.py` — REVISED (if needed). Make the destruction observable to the window. The cleanest fix may live entirely in `ui/window.py`; only touch this file if the window-only fix is impossible.
3. `tests/test_window_settings_wiring.py` — REVISED. Add a regression test that exercises the real GTK destroy path: open → close → reopen must construct a fresh dialog and not warn.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `proceed` is in this delegation.
- **Do NOT modify any other file.** This is a focused lifecycle fix in 1-2 files plus the test.
- **Do NOT change the public API of `SettingsDialog`.** `__init__(parent, *, handler, on_close)`, `show()`, `close()`, `refresh_providers(providers)` all stay the same.
- **Do NOT change the public API of `SettingsHandler`.** This is a view/wiring fix, not a handler fix.
- **The fix must not introduce a regression in tests/test_settings_dialog.py or tests/test_settings_handler.py.** Run them after the change.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `ui/window.py:740-755` — `_open_settings` and the cache pattern.
2. `ui/views/settings_dialog.py:259-377` — `SettingsDialog.__init__` and `_on_close_request`.
3. `ui/views/settings_dialog.py:370-377` — the current `close-request` handler (returns `False` to allow close, but does nothing else).
4. `tests/test_window_settings_wiring.py` — existing wiring tests; the new regression test will live here.
5. `tests/test_settings_dialog.py` — to confirm your fix doesn't break view-level tests.
6. `docs/ARCHITECTURE.md §3.6` — composition root rules (window.py is the only place that constructs handlers/views).

Output a `DISCOVERY:` block listing each file read and what you learned.

## Change plan

### Change 1: Clear the cache when the dialog window is destroyed

In `ui/window.py:744-752`, after constructing the `SettingsDialog`, connect a callback that clears `self._settings_dialog` when the underlying `Gtk.Window` is destroyed. Use the `destroy` signal on the `Gtk.Window` (not the Python wrapper — that lives forever).

**Approach (preferred — no `ui/views/settings_dialog.py` change):** connect to the `destroy` signal on `self._settings_dialog._window`. Place this in `_open_settings` immediately after constructing the dialog:

```python
def _open_settings(self) -> None:
    from ui.views.settings_dialog import SettingsDialog
    if not hasattr(self, "_settings_dialog") or self._settings_dialog is None:
        self._settings_dialog = SettingsDialog(
            parent=self,
            handler=self._settings_handler,
            on_close=lambda: None,
        )
        # Lifecycle: clear the cache when GTK destroys the window. The
        # close-request handler in SettingsDialog returns False (allow close),
        # so the window really does destroy when the user clicks Close / X.
        self._settings_dialog._window.connect(
            "destroy", lambda *_args: setattr(self, "_settings_dialog", None)
        )
    self._settings_dialog.show()
```

This is the **minimum diff** that fixes the bug. The cache is cleared on the destroy signal; the next ⚙ click constructs a fresh dialog.

**Note:** this reaches into `self._settings_dialog._window` (a private attr of the view). If you would rather not reach across the boundary, the alternative is to add a `get_window()` accessor to `SettingsDialog` — but that is a larger diff. The reach-in is acceptable here because `ui/window.py` is the composition root and is allowed to know about widget internals (per `docs/ARCHITECTURE.md §3.6`).

**If the reach-in bothers you and you'd rather do it in the view:** an alternative is to make `SettingsDialog._on_close_request` actually call `self._on_close` with a stronger contract — e.g. signal that the wrapper is now invalid — and then have the window pass a callback that clears the cache. Either approach is acceptable. **Pick one and document your choice in the COMPLETENESS block.**

### Change 2: Regression test in `tests/test_window_settings_wiring.py`

Add a new test class `TestSettingsDialogLifecycle` (or extend an existing class) with at least one test that exercises the real destroy path:

```python
class TestSettingsDialogLifecycle:
    """Regression: closing the dialog must invalidate the cache so the
    next open constructs a fresh dialog, not reuse a destroyed one."""

    def test_close_then_reopen_constructs_fresh_dialog(
        self, monkeypatch, capfd
    ):
        """Open → close (real GTK close) → reopen must not warn
        'A window is shown after it has been destroyed'."""
        from gi.repository import Gtk
        # Construct the real window with real GTK so destroy propagates
        win = CrabcakesApp()  # or a minimal harness — see existing tests
        try:
            # First open
            win._open_settings()
            dlg1 = win._settings_dialog
            assert dlg1 is not None

            # Real close — this is what triggers the destroy path
            dlg1._window.close()
            # Process pending events so the destroy signal fires
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

            # Cache should now be cleared
            assert getattr(win, "_settings_dialog", None) is None, (
                "Cache was not cleared after close — bug not fixed"
            )

            # Reopen — must construct fresh, must not warn
            win._open_settings()
            dlg2 = win._settings_dialog
            assert dlg2 is not None
            assert dlg2 is not dlg1, "Reopen reused the destroyed dialog"

            # Capture stderr — must not contain the GTK warning
            err = capfd.readouterr().err
            assert "A window is shown after it has been destroyed" not in err, (
                f"GTK warning fired on reopen: {err}"
            )
        finally:
            # Cleanup so the test doesn't leak windows
            try:
                if getattr(win, "_settings_dialog", None) is not None:
                    win._settings_dialog._window.close()
                    while Gtk.events_pending():
                        Gtk.main_iteration_do(False)
            except Exception:
                pass
            try:
                win.close()
            except Exception:
                pass
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
```

**Important:** adapt the construction of `win` to whatever the existing tests in `tests/test_window_settings_wiring.py` already use. Look at how the existing wiring tests instantiate the window or a stub. Do not invent a new harness if one already exists in that file. If a full `CrabcakesApp` is too heavy, build a minimal stub with the same `_open_settings` shape (you can extract the function or test it in isolation by directly calling it on a small harness object that has the right attributes).

**The test must exercise the real GTK close path** (call `self._window.close()` and let the destroy signal fire via `Gtk.main_iteration_do`). It must NOT just set `self._settings_dialog = None` manually — that would pass the test even if the fix is wrong.

### Change 3 (optional but recommended): sanity-check the existing tests

Run `tests/test_settings_dialog.py` and `tests/test_settings_handler.py` after the change. They should still pass. If they break, your fix is too aggressive.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# New regression test passes
python3 -m pytest tests/test_window_settings_wiring.py -v --tb=short 2>&1 | tail -20
echo "---"

# Existing settings tests still pass
python3 -m pytest tests/test_settings_dialog.py tests/test_settings_handler.py -v --tb=short 2>&1 | tail -15
echo "---"

# Full suite — pre-existing test_connection_sync_handler failure is OK, document it
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5
echo "---"

# Grep proof: cache-clearing hook is present
grep -n "destroy.*_settings_dialog\|destroy.*setattr" ui/window.py
echo "---"

# Grep proof: the new regression test exists
grep -n "def test_close_then_reopen" tests/test_window_settings_wiring.py
```

## Acceptance criteria

- [ ] The regression test `test_close_then_reopen_constructs_fresh_dialog` (or similarly named) exists and passes
- [ ] It uses the real GTK close path (`self._window.close()` + `Gtk.main_iteration_do`), not a manual cache reset
- [ ] It asserts no `Gtk-WARNING: A window is shown after it has been destroyed` message in stderr on reopen
- [ ] It asserts `self._settings_dialog is None` after the close
- [ ] It asserts the second open constructs a *different* `SettingsDialog` object than the first
- [ ] `tests/test_settings_dialog.py` and `tests/test_settings_handler.py` still pass
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py::TestActivityHandlerWiring` failure is pre-existing — attribute it correctly)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
SETTINGS-DIALOG-LIFECYCLE — COMPLETE

Files changed:
- ui/window.py — REVISED, +N / -M lines (paste git diff --stat)
- tests/test_window_settings_wiring.py — REVISED, +N / -M lines (paste git diff --stat)
- (list any other files you touched)

Verification (paste outputs):
- new regression test: ...
- existing settings tests: ...
- full suite: ...
- grep proof: ...
- new test grep: ...

**COMPLETENESS:**
- [x] Change 1: cache cleared on destroy — evidence: <grep + line number>
- [x] Change 2: regression test added — evidence: <pytest tail>
- [x] Change 2: test uses real GTK close path — evidence: <paste the relevant 3-4 lines from the test>
- [x] Change 2: test asserts no Gtk-WARNING — evidence: <pytest tail>
- [x] Existing tests still pass — evidence: <pytest tail>
- [x] Full suite passes (pre-existing failure attributed) — evidence: <pytest tail>

**Implementation choices made:**
- (e.g. "chose the reach-in to self._settings_dialog._window over adding a get_window() accessor — minimum diff, composition root is allowed to know internals per ARCHITECTURE §3.6")
- (list other non-obvious choices with one-sentence rationale)

**Notes for the spec maintainer:**
- (any deviation from this spec and the reason)

When done, please write: `Settings-dialog-lifecycle complete — all checks pass.`
```

When done, please write: `Settings-dialog-lifecycle complete — all checks pass.`
