# PHASE 5 of 9 — `ui/toolbar.py` + `ui/styles.py` (Toolbar ⚙ button + CSS)

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.9 (toolbar) and §2.13 (CSS).

## Files to change

1. `ui/toolbar.py` — REVISED. Add ⚙ Settings button + red status dot, plus a new constructor arg.
2. `ui/styles.py` — REVISED. Add new CSS classes for the toolbar button + dot.
3. `tests/test_toolbar.py` — NEW. Behavior tests (no GTK window required — widget construction is enough).

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly. No deviation.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Do NOT create the SettingsDialog view** (`ui/views/settings_dialog.py`). That's Phase 6. The toolbar's `_on_settings_clicked` callback will simply be `None` in tests; the window (Phase 7) will wire it to open the dialog.
- **Do NOT modify `ui/window.py`** — that's Phase 7.
- **Do NOT add a new top-level import to `ui/toolbar.py`.** Use `gi.require_version` and the existing `from gi.repository import Gtk` pattern.
- **Preserve all existing toolbar behavior.** The Connect button, status label, Stream toggle, and the `update_connection_state()` public method must keep working exactly as before. The new ⚙ button sits between `status_label` and `connect_btn` per spec §2.9.
- **`on_settings_clicked` is a keyword-only arg** (after `on_connect_clicked`). Default `None`. Tests pass `on_settings_clicked=lambda: ...` to verify wiring.
- **`set_settings_status(has_verified_provider)` inverts the boolean for visibility** — dot is VISIBLE when `has_verified_provider` is FALSE (i.e. no verified provider → red dot shown). This matches spec §2.9: "Show/hide the red dot. Window calls this on startup and after providers change." (Re-read §2.9 carefully: spec says "dot is hidden until needed" in the comment above the constructor block, then "Show/hide the red dot" in the docstring. The status logic is: red dot = warning that no provider is verified yet. **Invert the boolean** when calling `set_visible`.)
- **CSS additions go at the end of `APP_CSS`** in `ui/styles.py`. Do not reformat or move existing CSS.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.9 (toolbar spec) and §2.13 (CSS spec, lines 791-808 for the toolbar-related bits)
2. `ui/toolbar.py` (full file) — current layout, constructor pattern, callback style
3. `ui/styles.py` lines 1-55 and 1050-1060 (APP_CSS structure, where to insert new CSS, apply_styles function)
4. `tests/test_window.py` or any existing toolbar/window test — confirm the project's pattern for testing GTK widgets (likely `Gtk.init()`-free construction, just calling `Toolbar()` and inspecting properties)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 5.1: `ui/toolbar.py` revision

**Spec §2.9.** Apply these changes:

1. **Add `on_settings_clicked` keyword-only arg** to `__init__`, default `None`. Store on `self._on_settings_clicked`.
2. **Insert the settings button** between `status_label` and `connect_btn` in `right_box`. The exact construction from the spec, copied faithfully:

```python
# Settings button + red status dot
self._settings_btn = Gtk.Button(label="⚙ Settings")
self._settings_btn.add_css_class("settings-toolbar-btn")
self._settings_btn.set_size_request(110, -1)
self._settings_btn.connect("clicked", self._on_settings_click)
```

3. **Wrap the settings button in a `Gtk.Overlay`** with the red status dot as an overlay child:

```python
# Wrap settings button in an overlay to show a red dot
overlay = Gtk.Overlay()
overlay.set_child(self._settings_btn)
self._status_dot = Gtk.Label(label="●")
self._status_dot.add_css_class("toolbar-status-dot")
self._status_dot.set_halign(Gtk.Align.END)
self._status_dot.set_valign(Gtk.Align.START)
self._status_dot.set_visible(False)
overlay.add_overlay(self._status_dot)
right_box.append(overlay)
```

4. **Add `_on_settings_click` private method** that delegates to the callback:

```python
def _on_settings_click(self, *args):
    if self._on_settings_clicked is not None:
        self._on_settings_clicked()
```

5. **Add `set_settings_status(self, has_verified_provider: bool)` public method**:

```python
def set_settings_status(self, has_verified_provider: bool) -> None:
    """Show/hide the red dot. Window calls this on startup and after providers change."""
    self._status_dot.set_visible(not has_verified_provider)
```

6. **Initial state on construction**: dot hidden (default in widget), button always visible. Window will call `set_settings_status()` on startup based on the actual state.

**Order in `right_box.append(...)`:** the spec says "insert a settings button between them" (between `status_label` and `connect_btn`). The final order in `right_box` is therefore: `status_label` → `settings_btn` (inside overlay) → `connect_btn`.

## SUB-PHASE 5.2: `ui/styles.py` revision (CSS only)

**Spec §2.13 (lines 791-808).** Append the toolbar status dot CSS to the end of `APP_CSS`. The full block to add (copy from spec verbatim, including the `/* -- Toolbar status dot -- */` header comment so it groups nicely with the existing comment headers in `APP_CSS`):

```css
/* -- Toolbar status dot -------------------------------------------- */
.toolbar-status-dot {
    color: #ef4444;
    font-size: 14px;
    font-weight: 700;
}
```

That's it for this phase's CSS contribution. The other CSS classes (`settings-dialog`, `settings-provider-card`, `settings-test-btn`, etc.) belong to Phase 6 (the view) and are added then. **Do not pre-emptively add them in this phase** — keep the diff focused on the toolbar.

**Important:** the new button also uses `settings-toolbar-btn` CSS class. The spec only defines `toolbar-status-dot` and the `settings-*` dialog classes — it does **not** define `settings-toolbar-btn` anywhere I can see. The button will still be styled by GTK's default button rules, so this is fine. **If you want to make it match, add a minimal rule like `button.settings-toolbar-btn { border-radius: 6px; }` — but this is OPTIONAL and not required for the spec to pass.** Document your choice in the COMPLETENESS block.

## SUB-PHASE 5.3: `tests/test_toolbar.py` (new test file)

**Tests to write** (6 minimum, all without requiring a `Gtk.Window` parent):

```python
# tests/test_toolbar.py
# Tests for ui/toolbar.py — Settings button + red status dot.
#
# These tests construct the Toolbar widget directly. No window parent needed
# for construction; tests only inspect widget properties and click handlers.

import pytest

# gtk may not be importable on all CI environments — skip the module if not
try:
    from gi.repository import Gtk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

from ui.toolbar import Toolbar


pytestmark = pytest.mark.skipif(not GTK_AVAILABLE, reason="GTK not available")


class TestToolbarConstruction:
    def test_constructs_without_crash(self):
        t = Toolbar()
        assert t is not None

    def test_has_settings_button(self):
        t = Toolbar()
        assert hasattr(t, "_settings_btn")
        assert t._settings_btn.get_label() == "⚙ Settings"
        assert "settings-toolbar-btn" in t._settings_btn.get_css_classes()

    def test_status_dot_starts_hidden(self):
        t = Toolbar()
        assert hasattr(t, "_status_dot")
        assert t._status_dot.get_visible() is False


class TestSettingsClickCallback:
    def test_callback_fires_on_click(self):
        fired = []
        t = Toolbar(on_settings_clicked=lambda: fired.append(True))
        t._on_settings_click(None)  # simulate click
        assert fired == [True]

    def test_no_callback_no_crash(self):
        t = Toolbar()  # no on_settings_clicked
        t._on_settings_click(None)  # must not raise
        assert True


class TestSetSettingsStatus:
    def test_unverified_shows_dot(self):
        t = Toolbar()
        t.set_settings_status(False)
        assert t._status_dot.get_visible() is True

    def test_verified_hides_dot(self):
        t = Toolbar()
        t.set_settings_status(True)
        assert t._status_dot.get_visible() is False

    def test_toggle_back_and_forth(self):
        t = Toolbar()
        t.set_settings_status(False)  # show
        assert t._status_dot.get_visible() is True
        t.set_settings_status(True)   # hide
        assert t._status_dot.get_visible() is False
        t.set_settings_status(False)  # show again
        assert t._status_dot.get_visible() is True


class TestExistingBehaviorPreserved:
    """Make sure the new button didn't break the old ones."""

    def test_connect_button_still_present(self):
        t = Toolbar()
        assert t._connect_btn.get_label() == "Connect"

    def test_stream_button_still_present(self):
        t = Toolbar()
        assert hasattr(t, "_stream_btn")
        assert "Stream" in t._stream_btn.get_label()

    def test_status_label_still_present(self):
        t = Toolbar()
        assert hasattr(t, "_status_label")
```

**Test environment notes:**

- GTK4 is the runtime; tests need it imported. Wrap the import in a try/except so the test file can be collected even on CI without GTK.
- Don't call `Gtk.init()` — widget construction works without it in GTK4.
- `_on_settings_click(None)` simulates a click by calling the handler directly with `None` as the "button" arg (the handler signature is `*args`, so it accepts anything).
- `update_connection_state` is a public method that exists on the original toolbar — don't break it. (You don't need to test it in this phase — it's pre-existing behavior.)

## Verification commands (run between sub-phases AND at the end)

```bash
cd /home/q/projects/crabcakes

# 5.1: imports
python3 -c "from ui.toolbar import Toolbar; print('imports ok')"
echo "---"

# 5.1: widget construction (real GTK)
python3 -c "
from ui.toolbar import Toolbar
t = Toolbar()
print('settings_btn label:', t._settings_btn.get_label())
print('settings_btn css:', t._settings_btn.get_css_classes())
print('status_dot visible:', t._status_dot.get_visible())
print('connect_btn label:', t._connect_btn.get_label())
"
echo "---"

# 5.1: set_settings_status toggles dot
python3 -c "
from ui.toolbar import Toolbar
t = Toolbar()
t.set_settings_status(False)
assert t._status_dot.get_visible() is True, 'dot should show when unverified'
t.set_settings_status(True)
assert t._status_dot.get_visible() is False, 'dot should hide when verified'
print('OK: set_settings_status toggles dot')
"
echo "---"

# 5.1: click callback fires
python3 -c "
from ui.toolbar import Toolbar
fired = []
t = Toolbar(on_settings_clicked=lambda: fired.append(1))
t._on_settings_click(None)
assert fired == [1]
print('OK: click callback fires')
"
echo "---"

# 5.2: styles.py still loads (import doesn't crash)
python3 -c "from ui.styles import APP_CSS; assert 'toolbar-status-dot' in APP_CSS; print('OK: CSS contains toolbar-status-dot')"
echo "---"

# 5.3: new test file
python3 -m pytest tests/test_toolbar.py -v --tb=short 2>&1 | tail -25
echo "---"

# 5.3: full test suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

## Acceptance criteria for this phase

- [ ] `ui/toolbar.py` constructs the new `⚙ Settings` button with label "⚙ Settings" and css class `settings-toolbar-btn`
- [ ] The button is wrapped in a `Gtk.Overlay` containing a red status dot label
- [ ] Status dot starts hidden on construction
- [ ] New `on_settings_clicked` keyword-only arg added to `__init__`, default `None`
- [ ] `_on_settings_click` private method calls the callback when set, no-op when `None`
- [ ] New public method `set_settings_status(has_verified_provider: bool)` — dot visible when `False`, hidden when `True`
- [ ] Existing `Connect` button, `Stream` toggle, status label, `update_connection_state()` method all still work
- [ ] Button order in `right_box`: status_label → settings (in overlay) → connect_btn
- [ ] `ui/styles.py` `APP_CSS` contains a `toolbar-status-dot` rule with the spec's exact values (`color: #ef4444; font-size: 14px; font-weight: 700;`)
- [ ] **No import of Gtk/GLib added to `ui/styles.py`** (CSS-only change)
- [ ] **No other CSS classes pre-emptively added** (the `settings-*` dialog classes belong to Phase 6)
- [ ] `tests/test_toolbar.py` exists with at least 9 tests across 4 classes
- [ ] All new tests pass (or are skipped with a clear reason if GTK is unavailable)
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 5 of 9 — COMPLETE

Files changed:
- ui/toolbar.py — REVISED, N lines changed (paste git diff --stat)
- ui/styles.py — REVISED, N lines added (paste git diff --stat)
- tests/test_toolbar.py — NEW, +N / -M lines (paste wc -l)

Verification (paste outputs of every command listed above):
- 5.1 imports ok: ...
- 5.1 widget construction: ...
- 5.1 set_settings_status: ...
- 5.1 click callback: ...
- 5.2 CSS contains toolbar-status-dot: ...
- 5.3 test file passes: ...
- full test suite: ...

**COMPLETENESS:**
- [x] 5.1 settings button with ⚙ Settings label — evidence: <grep + output>
- [x] 5.1 button in Gtk.Overlay with status dot — evidence: <grep + output>
- [x] 5.1 status dot starts hidden — evidence: <test output>
- [x] 5.1 on_settings_clicked keyword arg — evidence: <grep + test>
- [x] 5.1 _on_settings_click private method — evidence: <grep>
- [x] 5.1 set_settings_status toggles dot — evidence: <test output>
- [x] 5.1 existing Connect/Stream/status preserved — evidence: <test output>
- [x] 5.1 button order: status → settings → connect — evidence: <grep>
- [x] 5.2 toolbar-status-dot CSS rule present — evidence: <grep APP_CSS>
- [x] 5.2 no Gtk/GLib import in styles.py — evidence: <grep>
- [x] 5.2 no pre-emptive settings-* classes — evidence: <grep APP_CSS>
- [x] 5.3 test file has 4 classes / 9+ tests — evidence: <pytest --collect-only>
- [x] 5.3 all new tests pass — evidence: <pytest tail>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (list any adjacent bugs)

**Implementation choices made:**
- (e.g. "Added optional `settings-toolbar-btn` CSS rule" or "did not, kept diff focused on toolbar-status-dot")
```

When done, please write: `Phase 5 complete — ready for audit.`
