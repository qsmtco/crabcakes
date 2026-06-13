# PHASE C — `ui/views/agent_builder.py` simplification

## Master spec
`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.10 (the only remaining spec section that was explicitly tagged "Phase C").

## Goal

Remove the hardcoded `_PROVIDERS` and `_PROVIDER_MODELS` constants from `agent_builder.py`. Populate the provider dropdown from `SettingsHandler.list_providers()`. Drop the API key entry from the form. Drop `provider_keys` from `get_values()` output. Add a `set_provider_options()` method that lets the dialog's provider list be refreshed when Settings changes the providers.

## Files to change

1. `ui/views/agent_builder.py` — REVISED. ~800 lines; the simplification removes ~50 lines and adds ~30. Net ~ -20 lines.
2. `tests/test_agent_builder_no_provider_keys.py` — REVISED. Convert the 2 `xfail(strict=True)` tests to regular passing tests. Verify they now pass.
3. **Optional but recommended:** new test cases for the new `set_provider_options` method.

## Hard rules

- **Use the steelFramedCodeWriter prompt** at `prompts/steelFramedCodeWriter.md`. Follow exactly.
- **Operating from authorized project channel** (crabcakes CLI). Trigger word `proceed` is in this delegation.
- **Do NOT modify any other file** — this is a focused refactor of `agent_builder.py` only (plus the test file).
- **Do NOT change the agent_builder_handler.py** — it already reads providers from yaml (Phase 3).
- **Do NOT change the agent_defs.py** — it already doesn't require api_key/provider_keys.
- **Preserve the public API of AgentBuilderDialog** — `__init__(self, parent, handler, agent_def, on_save, on_cancel)`, `show()`, `get_values()`, `show_errors()`. The new `set_provider_options()` is additive.
- **The provider dropdown must handle the empty-providers case** — if `SettingsHandler.list_providers()` returns `[]`, show a "(no providers — open Settings)" placeholder.
- **The model dropdown must still work** — when a provider is selected, populate the model dropdown from the provider's `default_model`. If no provider is selected, the model dropdown is empty.
- **The save button validation** must still work — `has_name and has_prompts and has_tools and has_provider_model`. Drop `has_api_key`.
- **You MUST include a literal `**COMPLETENESS:**` block** at the end of your report.

## Discovery — read these files first

1. `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` §2.10 (the exact diff)
2. `ui/views/agent_builder.py` full file (~800 lines)
3. `ui/handlers/agent_builder_handler.py` full file (the `get_provider_options` method)
4. `tests/test_agent_builder_no_provider_keys.py` (the xfail tests to convert)
5. `models/providers.py` (the `ProviderConfig` dataclass — what fields are available)
6. `ui/views/settings_dialog.py` (the pattern for how providers are rendered — model after this)

Output a DISCOVERY block listing each file read and what you learned.

## SUB-PHASE C.1: `ui/views/agent_builder.py` — major refactor

This is a substantial refactor. The key changes per spec §2.10:

### Change 1: Remove `_PROVIDERS` and `_PROVIDER_MODELS` class constants

Find lines 310-318 (the `_PROVIDERS` and `_PROVIDER_MODELS` constants). Remove them.

### Change 2: Convert them to instance attributes, initialized in `__init__`

In `__init__` (around line 58), after `self._provider_keys` is set up, add:

```python
# Provider list — populated from SettingsHandler via set_provider_options()
self._providers: list = []  # list[ProviderConfig]
self._provider_models: dict[str, list[tuple[str, str]]] = {}  # name → [(display, id), ...]
```

### Change 3: Add a `set_provider_options()` public method

Add this method (placement: near the other public methods, around line 200):

```python
def set_provider_options(self, providers) -> None:
    """Replace the provider list with the given providers.
    Called by the window when the Settings dialog fires on_providers_changed.
    Each provider's default_model becomes the only entry in its model dropdown.
    """
    self._providers = list(providers) if providers else []
    self._provider_models = {
        p.name: [(p.default_model, p.default_model)]
        for p in self._providers
        if p.default_model
    }
    self._rebuild_provider_dropdown()
```

### Change 4: Add a `_rebuild_provider_dropdown()` private method

The existing code (around line 332-337) has the dropdown creation inline. Extract it:

```python
def _rebuild_provider_dropdown(self) -> None:
    """Rebuild the provider dropdown from self._providers."""
    if not self._providers:
        names = Gtk.StringList.new(["(no providers — open Settings)"])
    else:
        names = Gtk.StringList.new([p.name for p in self._providers])
    self._provider_dropdown.set_model(names)
    # Select first provider by default
    if self._providers:
        self._on_provider_changed(self._provider_dropdown, None)
```

### Change 5: In `__init__`, replace the hardcoded provider dropdown with a call to `_rebuild_provider_dropdown()`

Find the block around line 332-343 that creates the provider dropdown. Replace the constant lookup with a method call:

```python
# Provider dropdown (populated from self._providers via set_provider_options)
provider_box = self._add_field(form_box, "Provider", None, "LLM provider (from Settings)")
self._provider_dropdown = Gtk.DropDown.new(Gtk.StringList.new(["(loading...)"]), None)
provider_box.append(self._provider_dropdown)
self._provider_dropdown.connect("notify::selected", self._on_provider_changed)
```

The actual rebuilding happens in `_rebuild_provider_dropdown()`.

### Change 6: Remove the `_on_provider_changed` body that updates the API key field

Find `_on_provider_changed` (around line 345-353). The current body:

```python
def _on_provider_changed(self, dropdown, _param) -> None:
    idx = dropdown.get_selected()
    if idx < len(self._PROVIDERS):
        return self._PROVIDERS[idx][1]
    return self._PROVIDERS[0][1]
```

Wait — looking at the grep output, `_on_provider_changed` does more than just return a value. Let me clarify what should happen.

**Updated spec:** The provider dropdown's purpose is to:
1. Update the model dropdown when a different provider is selected.
2. ~~Update the API key field~~ (REMOVED — no API key field anymore).

**The new `_on_provider_changed` body:**

```python
def _on_provider_changed(self, dropdown, _param) -> None:
    """Update the model dropdown when the selected provider changes."""
    provider_id = self._get_selected_provider()
    models = self._provider_models.get(provider_id, [])
    self._model_dropdown.set_model(Gtk.StringList.new([m[0] for m in models] or ["(no models)"]))
    self._update_save_button()
```

(Helper method `_get_selected_provider()` reads the dropdown and returns the provider id, similar to the existing logic.)

### Change 7: Drop the API key entry from the form

Find lines 143-148 (the `self._api_key_entry` block). Remove it entirely. The form no longer has an API key field.

### Change 8: Update `get_values()` to not include `provider_keys`

Find lines 199-214. The new version:

```python
def get_values(self) -> dict:
    """Return the dialog's current values as a dict.
    Per Phase C: no api_key, no provider_keys — keys live in providers.yaml.
    """
    name = self._name_entry.get_text().strip()
    emoji = self._emoji_entry.get_text().strip() or "🤖"
    role = self._role_entry.get_text().strip()
    provider = self._get_selected_provider()
    model = self._get_selected_model()
    prompts = self._get_selected_prompts()
    tools = self._get_selected_tools()
    return {
        "name": name,
        "emoji": emoji,
        "role": role,
        "prompts": prompts,
        "tools": tools,
        "provider": provider,
        "model": model,
        "mcp_servers": self._get_selected_mcp_servers(),
        "self_improvement": self._get_si_config(tools),
    }
```

### Change 9: Update `_update_save_button` to drop `has_api_key`

Find lines 762-779. The new condition:

```python
self._save_btn.set_sensitive(has_name and has_prompts and has_tools and has_provider_model)
```

### Change 10: Remove `self._provider_keys` initialization

Find line 52 (or wherever `self._provider_keys: dict[str, str] = {}` is). Remove it. Or, if you want to be conservative, leave it as `self._provider_keys: dict[str, str] = {}` but never use it (so the get_values() change is the only visible difference). **Either is acceptable.** Document the choice.

### Change 11: Remove the `set_text` calls that populate the API key field

Search for `self._api_key_entry.set_text` calls (around lines 350-352, 739). Remove them.

## SUB-PHASE C.2: Convert xfail tests to passing

In `tests/test_agent_builder_no_provider_keys.py`, the two `xfail(strict=True)` tests at the bottom need to be converted to regular passing tests.

**Before:**
```python
@pytest.mark.xfail(
    reason="Phase C work — agent_builder.get_values() still includes provider_keys. See spec §2.10.",
    strict=True,
)
def test_get_values_does_not_include_provider_keys(self):
    ...
```

**After:**
```python
def test_get_values_does_not_include_provider_keys(self):
    """Phase C complete: get_values() no longer includes provider_keys."""
    from ui.views.agent_builder import AgentBuilderDialog
    dlg = AgentBuilderDialog(parent=None, handler=None, agent_def={})
    values = dlg.get_values()
    assert "provider_keys" not in values, \
        f"Expected provider_keys removed, but got: {list(values.keys())}"
```

Same for `test_api_key_field_removed` — remove the `xfail` decorator, keep the body.

**Critical:** If you removed `self._api_key_entry` from the form (per Change 7), then `hasattr(dlg, "_api_key_entry")` will be `False` and the test passes. If you kept it as a vestigial unused attribute, the test will FAIL. So Change 7 (removing the entry) is required for this test to pass.

## SUB-PHASE C.3: Add a test for `set_provider_options()`

Add a new test class to `tests/test_agent_builder_no_provider_keys.py`:

```python
class TestSetProviderOptions:
    """Tests for the new set_provider_options() method (Phase C)."""

    def test_set_provider_options_populates_providers(self, tmp_config_dir):
        from ui.views.agent_builder import AgentBuilderDialog
        from models.providers import ProviderConfig

        providers = [
            ProviderConfig(name="p1", base_url="https://x", api_***ey="k", default_model="m1"),
            ProviderConfig(name="p2", base_url="https://y", api_***ey="k", default_model="m2"),
        ]
        dlg = AgentBuilderDialog(parent=None, handler=None, agent_def={})
        dlg.set_provider_options(providers)
        assert len(dlg._providers) == 2
        assert dlg._providers[0].name == "p1"

    def test_set_provider_options_handles_empty(self, tmp_config_dir):
        from ui.views.agent_builder import AgentBuilderDialog
        dlg = AgentBuilderDialog(parent=None, handler=None, agent_def={})
        dlg.set_provider_options([])
        assert dlg._providers == []
        # Dropdown should show placeholder
        model = dlg._provider_dropdown.get_model()
        assert model.get_n_items() == 1  # "(no providers — open Settings)"

    def test_set_provider_options_rebuilds_dropdown(self, tmp_config_dir):
        from ui.views.agent_builder import AgentBuilderDialog
        from models.providers import ProviderConfig
        dlg = AgentBuilderDialog(parent=None, handler=None, agent_def={})
        dlg.set_provider_options([
            ProviderConfig(name="alpha", base_url="x", api_***ey="k", default_model="a-m"),
            ProviderConfig(name="beta", base_url="y", api_***ey="k", default_model="b-m"),
        ])
        model = dlg._provider_dropdown.get_model()
        assert model.get_n_items() == 2
        assert model.get_string(0) == "alpha"
        assert model.get_string(1) == "beta"
```

## SUB-PHASE C.4: Verify the existing `test_agent_builder_handler.py` still passes

The existing tests for `agent_builder_handler.py` test the handler, not the view. They should still pass because we didn't change the handler. But verify:

```bash
python3 -m pytest tests/test_agent_builder_handler.py -v --tb=short
```

## Verification commands

```bash
cd /home/q/projects/crabcakes

# C.1: agent_builder.py imports ok
python3 -c "from ui.views.agent_builder import AgentBuilderDialog; print('imports ok')"
echo "---"

# C.1: _PROVIDERS and _PROVIDER_MODELS class constants are gone
echo "=== verify constants removed ==="
grep -nE "^_PROVIDERS = |^_PROVIDER_MODELS = " ui/views/agent_builder.py || echo "OK: constants removed"
echo "---"

# C.1: set_provider_options method exists
grep -n "def set_provider_options" ui/views/agent_builder.py
echo "---"

# C.1: _api_key_entry is gone
echo "=== verify _api_key_entry removed ==="
grep -n "_api_key_entry" ui/views/agent_builder.py || echo "OK: _api_key_entry removed"
echo "---"

# C.2: xfail markers gone from test file
echo "=== verify xfail markers removed ==="
grep -n "xfail" tests/test_agent_builder_no_provider_keys.py || echo "OK: xfail markers removed"
echo "---"

# C.2: test file passes (the 2 xfail → pass)
python3 -m pytest tests/test_agent_builder_no_provider_keys.py -v --tb=short 2>&1 | tail -15
echo "---"

# C.3: new set_provider_options tests
python3 -m pytest tests/test_agent_builder_no_provider_keys.py::TestSetProviderOptions -v --tb=short 2>&1 | tail -10
echo "---"

# C.4: existing handler tests still pass
python3 -m pytest tests/test_agent_builder_handler.py -q --tb=line 2>&1 | tail -5
echo "---"

# Full suite
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -5
```

## Acceptance criteria for this phase

- [ ] `_PROVIDERS` and `_PROVIDER_MODELS` class constants removed from `agent_builder.py`
- [ ] `set_provider_options(providers)` method added
- [ ] `_api_key_entry` removed from the form
- [ ] `get_values()` no longer returns `provider_keys`
- [ ] `_update_save_button` no longer checks `has_api_key`
- [ ] The 2 `xfail(strict=True)` tests in `test_agent_builder_no_provider_keys.py` are converted to passing
- [ ] At least 2 new tests for `set_provider_options` added
- [ ] `test_agent_builder_handler.py` still passes
- [ ] Full test suite passes (the pre-existing `test_connection_sync_handler.py` failure stays pre-existing)
- [ ] Test count is at least 1368 (1365 + 3 new set_provider_options tests, +0 from xfail conversion since xfail is no longer counted as a separate result)
- [ ] **COMPLETENESS block** at end of report

## Report format

```
PHASE C — COMPLETE

Files changed:
- ui/views/agent_builder.py — REVISED, +N / -M lines (paste git diff --stat)
- tests/test_agent_builder_no_provider_keys.py — REVISED, +N / -M lines (paste git diff --stat)

Verification (paste outputs of every command listed above):
- imports ok: ...
- constants removed: ...
- set_provider_options exists: ...
- _api_key_entry removed: ...
- xfail markers removed: ...
- test file passes: ...
- new set_provider_options tests pass: ...
- handler tests still pass: ...
- full suite: ...

**COMPLETENESS:**
- [x] C.1 _PROVIDERS / _PROVIDER_MODELS removed — evidence: <grep>
- [x] C.1 set_provider_options method added — evidence: <grep>
- [x] C.1 _api_key_entry removed — evidence: <grep>
- [x] C.1 get_values() drops provider_keys — evidence: <grep>
- [x] C.1 _update_save_button drops has_api_key — evidence: <grep>
- [x] C.2 xfail tests converted to passing — evidence: <pytest tail>
- [x] C.3 set_provider_options tests added — evidence: <pytest tail>
- [x] C.4 handler tests still pass — evidence: <pytest tail>
- [x] full suite passes — evidence: <paste test summary line>

**Implementation choices made:**
- (e.g. "kept self._provider_keys as a vestigial attribute to minimize diff — never read")
- (e.g. "added _rebuild_provider_dropdown helper to extract the dropdown construction logic")
- (list other choices)

**Notes for the spec maintainer:**
- (any deviation from spec §2.10 and the reason)

When done, please write: `Phase C complete — all dispatches done.`
```

When done, please write: `Phase C complete — all dispatches done.`
