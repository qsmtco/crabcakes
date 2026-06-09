# PHASE 6 of 9 — `ui/views/settings_dialog.py` (NEW) + `ui/styles.py` CSS extension

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.8 (view) and §2.13 (remaining CSS classes).

## Files to change

1. `ui/views/settings_dialog.py` — **NEW**, ~300 lines. The GTK4 dialog.
2. `ui/styles.py` — REVISED. Append the remaining `settings-*` CSS classes from §2.13.
3. `tests/test_settings_dialog.py` — **NEW**, ~150 lines. View smoke tests.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly. No deviation.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `write` is in this delegation.
- **Do NOT modify the handler** (`ui/handlers/settings_handler.py`). The dialog is a pure view; the handler is already complete and tested (Phase 4). You call into it.
- **Do NOT modify the toolbar** or the window. Phase 7 wires them together.
- **Pure view, no business logic.** All persistence goes through the handler (`self._handler.add_or_update(...)`, `self._handler.remove(...)`, `self._handler.test_provider(...)`, `self._handler.list_providers()`). The dialog never reads/writes `providers.yaml` directly.
- **The handler is the only gateway to the data.** This is per ARCHITECTURE.md Section 9 (view/handler split) and the spec's own "No business logic" rule.
- **The "non-builtin providers" clause in spec §2.8 is STALE** — the proposal explicitly eliminated built-in providers. **Always show the Remove button** for every provider. Do not add a "built-in" concept.
- **GTK4 idioms (mandatory):**
  - `gi.require_version('Gtk', '4.0')` at the top of the file.
  - Use `Gtk.Window` directly, **not** `Gtk.Dialog` (deprecated in GTK4). Follow the `AgentBuilderDialog` pattern at `ui/views/agent_builder.py:57-67`.
  - `dialog.set_transient_for(parent); dialog.set_modal(True)` for modal behavior.
  - `entry.set_visibility(False)` + `entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)` for API key fields.
  - `add_css_class` only — **no inline CSS, no `CssProvider`, no `set_css`**.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.8 (full spec for this file)
2. `ui/views/agent_builder.py` lines 1-90 (the pattern to mirror: window, header, scrolled form, save/cancel)
3. `ui/views/agent_builder.py` lines 140-170 (password entry pattern)
4. `ui/handlers/settings_handler.py` (the complete handler API you must call into — `list_providers`, `add_or_update`, `remove`, `test_provider`, `status_has_verified`)
5. `models/providers.py` (the `ProviderConfig` dataclass — 10 fields, all required for `add_or_update`)
6. `utils/provider_test.py` (the `TestResult(ok, latency_ms, error, model_used)` shape)
7. `ui/styles.py` lines 1043-1050 (where to append new CSS — the `toolbar-status-dot` block from Phase 5)
8. `docs/proposals/PROPOSAL-llm-provider-settings-dialogue.md` lines 1-50 (principles: single source of truth, validate before save, separation of concerns)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE 6.1: `ui/styles.py` (CSS only — do this first)

Append the remaining `settings-*` CSS classes from spec §2.13 (lines 742-794) to the end of `APP_CSS`. The full block to add (preserve the existing `/* -- Toolbar status dot -- */` block from Phase 5; insert the dialog block BEFORE it or AFTER it — your choice, document in COMPLETENESS):

```css
/* -- Settings dialog ------------------------------------------------ */
.settings-dialog {
    min-width: 560px;
    min-height: 480px;
}

.settings-provider-card {
    background: rgba(40, 40, 55, 0.45);
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 8px;
}

button.settings-test-btn {
    background: rgba(99, 102, 241, 0.25);
    color: #c7d2fe;
    border-radius: 6px;
    border: none;
}
button.settings-test-btn:hover {
    background: rgba(99, 102, 241, 0.45);
    color: #e0e7ff;
}

button.settings-remove-btn {
    background: rgba(244, 63, 94, 0.18);
    color: #fda4af;
    border-radius: 6px;
    border: none;
}
button.settings-remove-btn:hover {
    background: rgba(244, 63, 94, 0.35);
    color: #fecdd3;
}

.settings-status-ok {
    color: #22c55e;
    font-weight: 600;
}
.settings-status-fail {
    color: #f87171;
    font-weight: 600;
}
.settings-status-untested {
    color: #6b6b7a;
}

.settings-empty-state {
    color: #6b6b7a;
    font-size: 14px;
    padding: 32px;
}
```

**No import changes.** CSS only.

## SUB-PHASE 6.2: `ui/views/settings_dialog.py` (the dialog itself)

**Public API** (per spec §2.8, with optional `on_close`):

```python
class SettingsDialog:
    def __init__(self, parent: Gtk.Window, *, handler: SettingsHandler,
                 on_close=None):
        """Build the dialog. No business logic."""

    def show(self) -> None: ...
    def close(self) -> None: ...
    def refresh_providers(self, providers: list[ProviderConfig]) -> None: ...
```

**Layout requirements** (per spec §2.8, with proposal §3.1.1 / §3.4 empty state):

- **Header bar**: `Gtk.HeaderBar` with title "Settings" + Close button (right).
- **Body**: `Gtk.ScrolledWindow` (vexpand) wrapping a vertical `Gtk.Box` with margins.
- **Per-provider card** (`Gtk.Frame` with `add_css_class("settings-provider-card")`):
  - Name: editable `Gtk.Entry` (placeholder "Provider name")
  - Base URL: editable `Gtk.Entry` (placeholder "https://api.example.com/v1")
  - Default model: editable `Gtk.Entry` (placeholder "model-id")
  - API key: `Gtk.Entry` with `set_visibility(False)` + `set_input_purpose(Gtk.InputPurpose.PASSWORD)`, plus a `👁` reveal toggle button to its right
  - Status label: shows "Untested" (gray) by default; "✅ 42ms" (green) on success; "❌ error msg" (red) on failure
  - Test Connection button (`add_css_class("settings-test-btn")`)
  - Remove button (`add_css_class("settings-remove-btn")`) — **always shown** (no built-in concept)
  - Save button (`add_css_class("suggested-action")`) — saves the card's edits
- **+ Add Provider** button at the bottom (`add_css_class("suggested-action")`) — appends a new empty card
- **Empty state** (when `len(providers) == 0`): a centered `Gtk.Label` with text "No providers configured. Add your first provider below." with `add_css_class("settings-empty-state")`. The "Add your first provider" button is the same `+ Add Provider` button, just with a `set_has_tooltip` hint or centered placement.

**Internal state** (private attributes):

```python
self._handler: SettingsHandler
self._on_close: Callable | None
self._window: Gtk.Window
self._list_box: Gtk.Box          # the vertical container for provider cards
self._cards: list[_ProviderCard]  # one card per provider, see below
self._status_labels: dict[str, Gtk.Label]  # name → status label, for refresh
```

**Required internal class: `_ProviderCard`** (defined in the same file). This encapsulates the per-card widgets and the per-card save/test/remove logic. Suggested shape:

```python
class _ProviderCard:
    """A single provider's edit form. Pure view — delegates to handler."""

    def __init__(self, dialog: "SettingsDialog", provider: ProviderConfig | None):
        """If provider is None, this is a new (unsaved) card with empty fields."""
        self._dialog = dialog
        self._is_new = provider is None
        self._provider = provider or ProviderConfig(
            name="", base_url="", api_key=***
            default_model="",
        )
        self._frame: Gtk.Frame
        self._name_entry: Gtk.Entry
        self._base_url_entry: Gtk.Entry
        self._model_entry: Gtk.Entry
        self._api_key_entry: Gtk.Entry
        self._reveal_btn: Gtk.Button
        self._status_label: Gtk.Label
        self._test_btn: Gtk.Button
        self._remove_btn: Gtk.Button
        self._save_btn: Gtk.Button
        self._build_widgets()
        if provider is not None:
            self._populate_from_provider()

    def _build_widgets(self) -> None: ...
    def _populate_from_provider(self) -> None: ...
    def _collect_from_form(self) -> ProviderConfig: ...
    def _on_save_clicked(self, *args) -> None:
        # collect fields, call dialog._handler.add_or_update(provider)
        # dialog.refresh_providers will be called by on_providers_changed
        ...
    def _on_test_clicked(self, *args) -> None:
        # collect fields (without saving), call dialog._handler.test_provider(
        #   provider, self._on_test_result)
        ...
    def _on_remove_clicked(self, *args) -> None:
        # if new (not saved): just remove the card from the dialog
        # if saved: show confirmation dialog, then call dialog._handler.remove(name)
        ...
    def _on_test_result(self, result: TestResult) -> None:
        # update self._status_label with ✅/❌
        ...
    def get_widget(self) -> Gtk.Frame:
        return self._frame
```

**Test Connection is async.** When the user clicks Test:
1. Collect the **current form values** (not the saved ProviderConfig — they may have edited without saving).
2. Call `handler.test_provider(provider, self._on_test_result)`. The handler dispatches in a daemon thread.
3. The card's status label is updated in `_on_test_result` which fires on the GTK main thread (via GLib.idle_add or synchronously in tests).

**Save flow**:
1. Collect the form values into a `ProviderConfig`.
2. Call `handler.add_or_update(provider)`. The handler validates non-empty fields and raises `ValueError` on bad input.
3. If `ValueError` is raised, show the error inline in the status label with `add_css_class("settings-status-fail")`. **Do not crash, do not show a stack trace.**
4. On success, the handler fires `on_providers_changed` which calls `dialog.refresh_providers(...)` — that method rebuilds the card list (or just updates the existing card in place — your choice, document the choice).

**Remove flow**:
1. Show a `Gtk.MessageDialog` with `set_transient_for(dialog._window); set_modal(True)`, type `WARNING`, buttons `YES|NO`, message "Remove provider '<name>'? This cannot be undone."
2. On YES: call `handler.remove(name)`. Handler fires `on_providers_changed` → `dialog.refresh_providers(...)`.

**API key reveal toggle**: clicking the 👁 button toggles `self._api_key_entry.set_visibility(True/False)`. Just a local widget toggle, no handler call.

**`show()`**: `self._window.present()` (GTK4 idiom — `show()` then `present()` is the recommended pattern, but `present()` alone is enough).

**`close()`**: `self._window.close()`. Connect to the window's `close-request` signal to call `self._on_close` callback if set.

**`refresh_providers(providers: list[ProviderConfig])`**: rebuild the card list from the given provider list. For each existing card whose name is still in the new list, update the entries in place (preserves scroll position and focus). For names that disappeared, remove their cards. For new names, append new cards. This is the method the handler's `on_providers_changed` callback fires.

**Constructor wiring**:
- `parent`: stored, used for `set_transient_for`.
- `handler`: stored as `self._handler`. The handler is the source of truth.
- `on_close`: stored as `self._on_close`. Called when the user closes the window.

**Critical anti-patterns to avoid:**
- **Do not import `providers_store` or `provider_test` directly** in the view. Everything goes through the handler.
- **Do not implement the test thread in the view.** The handler does the threading.
- **Do not store the API key in plain text** in any instance attribute beyond the Entry widget. The Entry holds it; you collect it on save/test; that's it.
- **Do not write a custom confirmation dialog** for remove — use `Gtk.MessageDialog` per the existing `agent_builder_handler.delete_agent_with_confirmation` pattern.

## SUB-PHASE 6.3: `tests/test_settings_dialog.py` (new test file)

**Per spec §2.15 (lines 859-862):** "View-only smoke test: opening the dialog with an empty provider list shows the empty state, with one provider shows a card, removing a provider fires `on_providers_changed`."

Required tests (minimum 8):

```python
# tests/test_settings_dialog.py
# Tests for ui/views/settings_dialog.py — pure view smoke tests.
# Pattern: construct the dialog with a real handler (using tmp_config_dir),
# inspect the widget tree, do not actually open a window (no Gtk.Window present).

import pytest

try:
    from gi.repository import Gtk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

from models.providers import ProviderConfig
from ui.handlers.settings_handler import SettingsHandler
from ui.views.settings_dialog import SettingsDialog


pytestmark = pytest.mark.skipif(not GTK_AVAILABLE, reason="GTK not available")


def _make_provider(name="test", **overrides) -> ProviderConfig:
    defaults = dict(
        name=name, base_url=f"https://api.{name}.example.com/v1",
        api_key=*** default_model=f"{name}/model-v1",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestEmptyState:
    def test_no_providers_shows_empty_state(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)  # parent=None is OK for widget construction
        # Empty state widget should be present
        assert d._empty_state is not None
        assert d._empty_state.get_visible() is True

    def test_with_providers_hides_empty_state(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        assert d._empty_state.get_visible() is False


class TestProviderCards:
    def test_one_provider_renders_one_card(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        assert len(d._cards) == 1
        assert d._cards[0].get_widget().get_visible() is True

    def test_two_providers_render_two_cards(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        h.add_or_update(_make_provider("p2"))
        d = SettingsDialog(parent=None, handler=h)
        assert len(d._cards) == 2

    def test_add_provider_button_appends_card(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        initial = len(d._cards)
        d._on_add_provider_clicked(None)  # simulate click
        assert len(d._cards) == initial + 1

    def test_card_has_all_widgets(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        assert card._name_entry is not None
        assert card._base_url_entry is not None
        assert card._model_entry is not None
        assert card._api_key_entry is not None
        assert card._test_btn is not None
        assert card._remove_btn is not None
        assert card._save_btn is not None

    def test_api_key_entry_is_password(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        assert card._api_key_entry.get_visibility() is False
        assert card._api_key_entry.get_input_purpose() == Gtk.InputPurpose.PASSWORD


class TestRemoveCallback:
    def test_remove_fires_handler_remove(self, tmp_config_dir, monkeypatch):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        # Mock the confirmation dialog to always say YES
        from gi.repository import Gtk as GtkMod
        monkeypatch.setattr(GtkMod, "MessageDialog", lambda *a, **kw: _YesDialog())
        card._on_remove_clicked(None)
        # After remove, list_providers should be empty
        assert h.list_providers() == []
        # And the dialog should have refreshed
        assert len(d._cards) == 0


class TestSaveFlow:
    def test_save_valid_calls_handler_add_or_update(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        # Add a new card via the add button
        d._on_add_provider_clicked(None)
        new_card = d._cards[-1]
        new_card._name_entry.set_text("newprov")
        new_card._base_url_entry.set_text("https://x.example.com/v1")
        new_card._api_key_entry.set_text("***")
        new_card._model_entry.set_text("newprov/model-v1")
        new_card._on_save_clicked(None)
        # Handler should now have it
        names = [p.name for p in h.list_providers()]
        assert "newprov" in names

    def test_save_invalid_shows_error_in_status_label(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        d._on_add_provider_clicked(None)
        new_card = d._cards[-1]
        new_card._name_entry.set_text("")  # empty → ValueError
        new_card._base_url_entry.set_text("https://x.example.com/v1")
        new_card._api_key_entry.set_text("***")
        new_card._model_entry.set_text("model")
        new_card._on_save_clicked(None)
        # Status label should show the error
        assert "required" in new_card._status_label.get_text().lower() or \
               "name" in new_card._status_label.get_text().lower()


class TestRefreshProviders:
    def test_refresh_rebuilds_cards(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("a"))
        d = SettingsDialog(parent=None, handler=h)
        assert len(d._cards) == 1
        # Add another via handler, then refresh
        h.add_or_update(_make_provider("b"))
        d.refresh_providers(h.list_providers())
        assert len(d._cards) == 2

    def test_refresh_preserves_existing_card_state(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("a"))
        d = SettingsDialog(parent=None, handler=h)
        # Simulate user editing the entry without saving
        d._cards[0]._name_entry.set_text("edited-but-unsaved")
        # Refresh from the handler (which still has "a")
        d.refresh_providers(h.list_providers())
        # The edited-but-unsaved value should be preserved (per design choice in the card)
        # OR the entry should be re-populated from the provider
        # Document the choice in COMPLETENESS — both are acceptable per the spec.
```

**Test environment notes:**

- `parent=None` is acceptable for widget construction. The dialog sets `set_transient_for(parent)` which is a no-op when parent is None. `present()` is not called in tests.
- `_YesDialog` is a stub class for mocking `Gtk.MessageDialog` — define it in the test file:
  ```python
  class _YesDialog:
      def __init__(self, *args, **kwargs): pass
      def run(self): return Gtk.ResponseType.YES
      def destroy(self): pass
  ```
  (In GTK4, MessageDialog uses `choose()` instead of `run()`. The mock should provide whichever method your code calls. If your code calls `dialog.choose(callback, None)`, the mock signature is different. Match your actual implementation.)
- **No GTK Window parent is required.** Construction works; methods that need a window are not called.
- `tmp_config_dir` fixture from conftest is required for tests that exercise the handler (which reads/writes `providers.yaml`).

## Verification commands (run between sub-phases AND at the end)

```bash
cd /home/q/projects/crabcakes

# 6.1: styles.py still loads
python3 -c "from ui.styles import APP_CSS; print('imports ok'); assert 'settings-dialog' in APP_CSS; assert 'settings-provider-card' in APP_CSS; assert 'settings-test-btn' in APP_CSS; assert 'settings-remove-btn' in APP_CSS; assert 'settings-status-ok' in APP_CSS; assert 'settings-status-fail' in APP_CSS; assert 'settings-empty-state' in APP_CSS; print('OK: all settings-* CSS classes present')"
echo "---"

# 6.2: imports
python3 -c "from ui.views.settings_dialog import SettingsDialog, _ProviderCard; print('imports ok')"
echo "---"

# 6.2: construct with empty provider list
python3 -c "
from ui.views.settings_dialog import SettingsDialog
from ui.handlers.settings_handler import SettingsHandler
h = SettingsHandler()
d = SettingsDialog(parent=None, handler=h)
print('cards:', len(d._cards))
print('empty_state visible:', d._empty_state.get_visible())
"
echo "---"

# 6.2: construct with one provider
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from ui.views.settings_dialog import SettingsDialog
from ui.handlers.settings_handler import SettingsHandler
from models.providers import ProviderConfig
h = SettingsHandler()
h.add_or_update(ProviderConfig(name='p1', base_url='https://x', api_key=*** default_model='m1'))
d = SettingsDialog(parent=None, handler=h)
print('cards:', len(d._cards))
print('empty_state visible:', d._empty_state.get_visible())
card = d._cards[0]
print('card name entry:', card._name_entry.get_text())
print('card api_key visibility:', card._api_key_entry.get_visibility())
"
echo "---"

# 6.2: refresh_providers
python3 -c "
import os, tempfile
os.environ['HOME'] = tempfile.mkdtemp()
from ui.views.settings_dialog import SettingsDialog
from ui.handlers.settings_handler import SettingsHandler
from models.providers import ProviderConfig
h = SettingsHandler()
h.add_or_update(ProviderConfig(name='a', base_url='https://a', api_key=*** default_model='am'))
d = SettingsDialog(parent=None, handler=h)
assert len(d._cards) == 1
h.add_or_update(ProviderConfig(name='b', base_url='https://b', api_key=*** default_model='bm'))
d.refresh_providers(h.list_providers())
assert len(d._cards) == 2
print('OK: refresh_providers rebuilds cards')
"
echo "---"

# 6.2: handler import isolation — view must NOT import providers_store or provider_test
grep -E "from utils.providers_store|from utils.provider_test" ui/views/settings_dialog.py; echo "--- above should be EMPTY (view goes through handler) ---"
echo "---"

# 6.3: new test file
python3 -m pytest tests/test_settings_dialog.py -v --tb=short 2>&1 | tail -30
echo "---"

# 6.3: full test suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -10
```

## Acceptance criteria for this phase

- [ ] `ui/views/settings_dialog.py` exists with `SettingsDialog` class
- [ ] `SettingsDialog` has 4 public methods: `__init__`, `show`, `close`, `refresh_providers`
- [ ] Uses `Gtk.Window` (not deprecated `Gtk.Dialog`) with `set_transient_for` and `set_modal`
- [ ] `gi.require_version('Gtk', '4.0')` is at the top of the file
- [ ] `_ProviderCard` internal class exists and encapsulates per-card widgets/logic
- [ ] Empty state shown when no providers
- [ ] One card per provider rendered when list is non-empty
- [ ] Per-card widgets: name, base_url, model, api_key (password), test_btn, remove_btn, save_btn
- [ ] API key field uses `set_visibility(False)` + `set_input_purpose(PASSWORD)`
- [ ] Reveal toggle (👁) on API key field works
- [ ] Save button calls `handler.add_or_update(provider)` and catches `ValueError` to show inline error
- [ ] Test button calls `handler.test_provider(provider, callback)` — does NOT block
- [ ] Test result callback updates the per-card status label with ✅/❌
- [ ] Remove button shows `Gtk.MessageDialog` confirmation, then calls `handler.remove(name)`
- [ ] "+ Add Provider" button appends a new (empty) card to the list
- [ ] `refresh_providers(providers)` rebuilds the card list
- [ ] **No direct import of `utils.providers_store` or `utils.provider_test`** in the view
- [ ] `ui/styles.py` `APP_CSS` contains all 8 new settings-* classes (dialog, provider-card, test-btn, remove-btn, status-ok, status-fail, status-untested, empty-state)
- [ ] **No inline CSS or `CssProvider`** anywhere in the view
- [ ] `tests/test_settings_dialog.py` exists with at least 8 tests across 4+ classes
- [ ] All new tests pass (or skipped with reason if GTK is unavailable)
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE 6 of 9 — COMPLETE

Files changed:
- ui/views/settings_dialog.py — NEW, +N / -M lines (paste wc -l)
- ui/styles.py — REVISED, +N lines (paste git diff --stat)
- tests/test_settings_dialog.py — NEW, +N / -M lines (paste wc -l)

Verification (paste outputs of every command listed above):
- 6.1 all settings-* CSS classes present: ...
- 6.2 imports ok: ...
- 6.2 empty state shows when no providers: ...
- 6.2 card renders with password field: ...
- 6.2 refresh_providers rebuilds cards: ...
- 6.2 view does NOT import providers_store or provider_test: ...
- 6.3 test file passes: ...
- full test suite: ...

**COMPLETENESS:**
- [x] 6.1 settings-dialog CSS — evidence: <grep>
- [x] 6.1 settings-provider-card CSS — evidence: <grep>
- [x] 6.1 settings-test-btn CSS — evidence: <grep>
- [x] 6.1 settings-remove-btn CSS — evidence: <grep>
- [x] 6.1 settings-status-ok/fail/untested CSS — evidence: <grep>
- [x] 6.1 settings-empty-state CSS — evidence: <grep>
- [x] 6.2 SettingsDialog has 4 public methods — evidence: <grep "def __init__\|def show\|def close\|def refresh_providers">
- [x] 6.2 uses Gtk.Window not Gtk.Dialog — evidence: <grep -c "Gtk.Dialog" = 0; grep "Gtk.Window" count>
- [x] 6.2 gi.require_version at top — evidence: <head -10>
- [x] 6.2 _ProviderCard class — evidence: <grep "class _ProviderCard">
- [x] 6.2 empty state visible when no providers — evidence: <test output>
- [x] 6.2 cards rendered for each provider — evidence: <test output>
- [x] 6.2 api_key entry is password — evidence: <test output>
- [x] 6.2 save calls handler.add_or_update, catches ValueError — evidence: <test output + grep>
- [x] 6.2 test calls handler.test_provider (no blocking) — evidence: <grep + test>
- [x] 6.2 remove shows MessageDialog, calls handler.remove — evidence: <grep + test>
- [x] 6.2 add provider button appends card — evidence: <test>
- [x] 6.2 refresh_providers rebuilds cards — evidence: <test>
- [x] 6.2 no direct import of providers_store/provider_test — evidence: <grep -E>
- [x] 6.2 no inline CSS / CssProvider — evidence: <grep -E "CssProvider|set_css">
- [x] 6.3 test file has 4+ classes / 8+ tests — evidence: <pytest --collect-only>
- [x] 6.3 all new tests pass — evidence: <pytest tail>
- [x] Full test suite passes — evidence: <paste test summary line>

**Related issues found — not fixed in this phase:**
- (list any adjacent bugs)

**Implementation choices made:**
- (e.g. "refresh_providers preserves user-edited-but-unsaved card state" or "refresh_providers re-populates entries from the new provider list")
- (any other non-obvious choices with one-sentence rationale)
```

When done, please write: `Phase 6 complete — ready for audit.`
