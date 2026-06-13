# Phase 4 — Refactor `ui/views/agent_builder.py` per SPEC §2.1

**Spec:** `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` §2.1

## Context

Phases 1–3 connected the wiring and fixed `set_provider_options` type normalization. The agent builder dialog still shows:
- A Model dropdown (no longer needed — model is resolved at runtime from `providers.yaml`)
- A Manual entry mode (no longer needed — Settings is the only place to add a provider)
- An API key entry field (no longer needed — keys live in `providers.yaml`)

Phase 4 removes all of this dead code AND populates the provider dropdown at construction (so opening the dialog shows real providers, not "(loading...)").

## Files to change

1. `ui/views/agent_builder.py` only (no other file)

## Rules

- Use the steelFramedCodeWriter prompt at `prompts/steelFramedCodeWriter.md` exactly
- Follow `docs/ARCHITECTURE.md` — this is a UI view; no business logic should leak in
- Do NOT touch any other file
- Do NOT change the public API of `AgentBuilderDialog` (the constructor signature and method names are stable)
- Do NOT change `set_provider_options()`, `_rebuild_provider_dropdown()`, or `_build_provider_dropdown()` — Phase 2 already fixed them

## Change 1: Remove dead instance variables from `__init__`

In `ui/views/agent_builder.py` around lines 44-53, REMOVE these lines:
```python
self._provider_keys: dict[str, str] = {}  # provider_id → api_key (legacy, unused in Phase C)
self._manual_mode: bool = False  # True when manual provider/model entry is active
```

KEEP the other instance variables (`_handler`, `_on_save`, `_on_cancel`, `_is_edit`, `_original_si`, `_tool_checks`, `_tool_count_label`, `_mcp_checks`, `_providers`, `_provider_models`).

## Change 2: Populate the dropdown at construction

At the END of `__init__` (after `self._window.set_child(content)` and the `if agent_def:` block — specifically, the last line of `__init__`), add ONE line:
```python
# Populate provider dropdown from handler (reads providers.yaml)
self.set_provider_options(handler.get_provider_options())
```

This is the SPEC §2.1 change #1.

## Change 3: Remove the Model column from the Provider/Model row

In the form builder section (around lines 109-138), REMOVE these lines (and only these — be careful with indentation):
```python
        self._model_dropdown = self._build_model_dropdown()
        self._model_labeled = self._labeled_box("Model", self._model_dropdown)
        provider_model_row.append(self._model_labeled)
```

Also rename `provider_model_row` to `provider_row` (the variable only holds the provider dropdown now). This is SPEC §2.1 change #2.

## Change 4: Remove the Manual entry widgets (entire block)

REMOVE this entire block (around lines 121-138):
```python
        # Manual entry widgets (hidden by default)
        self._manual_provider_entry = Gtk.Entry()
        self._manual_provider_entry.set_placeholder_text("e.g. openrouter")
        self._manual_provider_entry.set_hexpand(True)
        self._manual_provider_entry.connect("changed", lambda *_: self._update_save_button())
        self._manual_provider_labeled = self._labeled_box("Provider", self._manual_provider_entry)
        self._manual_provider_labeled.set_visible(False)
        provider_model_row.append(self._manual_provider_labeled)

        self._manual_model_entry = Gtk.Entry()
        self._manual_model_entry.set_placeholder_text("e.g. qwen/qwen3.7-max")
        self._manual_model_entry.set_hexpand(True)
        self._manual_model_entry.connect("changed", lambda *_: self._update_save_button())
        self._manual_model_labeled = self._labeled_box("Model", self._manual_model_entry)
        self._manual_model_labeled.set_visible(False)
        provider_model_row.append(self._manual_model_labeled)

        # Manual toggle button
        self._manual_toggle = Gtk.ToggleButton(label="Manual")
        self._manual_toggle.add_css_class("flat")
        self._manual_toggle.set_valign(Gtk.Align.END)
        self._manual_toggle.set_margin_bottom(0)
        self._manual_toggle.connect("toggled", self._on_manual_toggled)
        provider_model_row.append(self._manual_toggle)
```

This is SPEC §2.1 change #3. The `provider_model_row` rename from Change 3 covers the references that pointed here.

## Change 5: Remove dead methods

REMOVE these method definitions (they become orphans after Changes 1, 3, 4):
- `_build_model_dropdown` (around line 375)
- `_rebuild_model_dropdown` (around line 381)
- `_get_selected_model` (around line 394)
- `_on_manual_toggled` (around line 405)

These are SPEC §2.1 change #5.

## Change 6: Simplify `get_values()`

Replace the current `get_values()` method body with:
```python
def get_values(self) -> dict:
    """Extract current form values into an agent_def dict.
    The model field is left empty — the runtime resolves the model
    from providers.yaml using the provider name.
    """
    name = self._name_entry.get_text().strip()
    emoji = self._emoji_entry.get_text().strip() or "🤖"
    role = self._role_entry.get_text().strip() or name.lower().replace(" ", "-")
    provider = self._get_selected_provider_id()

    prompts = self._get_selected_prompts()
    tools = self._get_selected_tools()

    return {
        "name": name,
        "emoji": emoji,
        "role": role,
        "prompts": prompts,
        "tools": tools,
        "provider": provider,
        "model": "",  # resolved at runtime from providers.yaml
        "mcp_servers": self._get_selected_mcp_servers(),
        "self_improvement": self._get_si_config(tools),
    }
```

This is SPEC §2.1 change #8.

## Change 7: Update `_update_save_button()`

Replace the method body with:
```python
def _update_save_button(self) -> None:
    """Enable Save only when: name, prompts, tools, AND provider are set.

    This is widget state management (is the form complete?), NOT validation.
    Actual validation lives in validate_agent_def().
    """
    has_name = bool(self._name_entry.get_text().strip())
    has_prompts = any(c.get_active() for c in self._prompt_checks.values())
    has_tools = any(c.get_active() for c in self._tool_checks.values())
    has_provider = bool(self._get_selected_provider_id())

    self._save_btn.set_sensitive(
        has_name and has_prompts and has_tools and has_provider
    )
```

This is SPEC §2.1 change #7.

## Change 8: Update `_on_provider_changed()`

The current method calls `self._rebuild_model_dropdown()` which is being removed. Update the method body to:
```python
def _on_provider_changed(self, dropdown, _param) -> None:
    """When provider changes, refresh save button state."""
    self._update_save_button()
```

## Change 9: Update `_fill_form()` (if it references removed widgets)

Search `_fill_form` for any reference to `_model_dropdown`, `_manual_*`, `_api_key_entry`, `_provider_keys`. If any are found, remove those lines. The form-filling logic should:
- Set the provider dropdown selection by provider name
- Set the manual entry text fields (now removed) — REMOVE these lines
- Set the API key entry text (now removed) — REMOVE these lines

Specifically: lines 741-770 of the current file have a `_select_model` helper and `_model_dropdown.set_selected(...)` calls. These must be removed.

**Important:** The edit path should still work — `_fill_form` is called when `agent_def` is provided. The agent_def has `provider` and `model` fields. The model field is now ignored (the runtime resolves it). The provider field selects the dropdown.

## Verification

After the fix, run:

```bash
cd /home/q/projects/crabcakes

# Confirm dead code is gone
grep -n "_build_model_dropdown\|_rebuild_model_dropdown\|_get_selected_model\|_on_manual_toggled\|_manual_mode\|_provider_keys\|_api_key_entry\|_manual_provider\|_manual_model" ui/views/agent_builder.py
# Expected: 0 matches (except possibly in comments — should be 0 in code)

grep -n "provider_keys\|api_key" ui/views/agent_builder.py
# Expected: 0 matches in code (comments are fine)

# Confirm the dropdown is populated at construction
grep -n "set_provider_options(handler.get_provider_options())" ui/views/agent_builder.py
# Expected: 1 match in __init__

# Confirm model field is empty in get_values
grep -n '"model": ""' ui/views/agent_builder.py
# Expected: 1 match in get_values

# Existing tests still pass (some may fail due to removed fields — see Phase 5 for fix)
python3 -m pytest tests/test_agent_builder_handler.py -v --tb=short 2>&1 | tail -10
# Expected: 18 passed (the 5 pre-existing failures are unrelated to this change)

# Smoke test: dialog opens with providers from handler
python3 << 'PYEOF'
import tempfile, os
import yaml
from unittest.mock import MagicMock
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from models.providers import ProviderConfig

# Create a temp providers.yaml
tmpdir = tempfile.mkdtemp()
providers_yaml = os.path.join(tmpdir, 'providers.yaml')
with open(providers_yaml, 'w') as f:
    yaml.safe_dump({
        'providers': [
            {'name': 'openai', 'base_url': 'u', 'default_model': 'gpt-4o', 'enabled': True, 'api_key': 'k'},
            {'name': 'anthropic', 'base_url': 'u', 'default_model': 'c', 'enabled': True, 'api_key': 'k'},
        ]
    }, f)

import ui.handlers.agent_builder_handler as h
orig_load = h._PROVIDER_LOAD_FN if hasattr(h, '_PROVIDER_LOAD_FN') else None

# Use the real handler with patched load_providers
import utils.providers_store as ps
orig = ps.load_providers
ps.load_providers = lambda: [
    ProviderConfig('openai', 'u', 'k', 'gpt-4o', True),
    ProviderConfig('anthropic', 'u', 'k', 'c', True),
]
try:
    handler = h.AgentBuilderHandler()
    from ui.views.agent_builder import AgentBuilderDialog
    parent = MagicMock()
    parent.get_application = MagicMock()
    dialog = AgentBuilderDialog(parent, handler=handler)
    
    # Check dropdown has 2 items, not "(loading...)"
    model = dialog._provider_dropdown.get_model()
    print(f'dropdown item count: {model.get_n_items()} (expect 2)')
    print(f'item 0: {model.get_string(0)} (expect openai)')
    print(f'item 1: {model.get_string(1)} (expect anthropic)')
    
    # Check no _model_dropdown, no _api_key_entry
    print(f'has _model_dropdown? {hasattr(dialog, "_model_dropdown")} (expect False)')
    print(f'has _api_key_entry? {hasattr(dialog, "_api_key_entry")} (expect False)')
    print(f'has _manual_provider_entry? {hasattr(dialog, "_manual_provider_entry")} (expect False)')
    
    # Check get_values
    dialog._name_entry.set_text('test-agent')
    dialog._get_selected_provider_id = lambda: 'openai'  # mock since GTK4 needs display
    values = dialog.get_values()
    print(f'values["provider"]: {values["provider"]} (expect openai)')
    print(f'values["model"]: {values["model"]!r} (expect "")')
    print(f'has "provider_keys" in values? {"provider_keys" in values} (expect False)')
    print(f'has "api_key" in values? {"api_key" in values} (expect False)')
finally:
    ps.load_providers = orig
PYEOF
```

## COMPLETENESS Checklist

- [ ] Change 1: removed `_provider_keys` and `_manual_mode` instance vars — evidence: grep
- [ ] Change 2: `set_provider_options(handler.get_provider_options())` at end of `__init__` — evidence: grep
- [ ] Change 3: removed Model column from Provider/Model row — evidence: grep
- [ ] Change 4: removed Manual entry widgets — evidence: grep
- [ ] Change 5: removed `_build_model_dropdown`, `_rebuild_model_dropdown`, `_get_selected_model`, `_on_manual_toggled` — evidence: grep
- [ ] Change 6: simplified `get_values()` — model is `""` — evidence: grep
- [ ] Change 7: simplified `_update_save_button()` — has_provider instead of has_provider_model — evidence: grep
- [ ] Change 8: simplified `_on_provider_changed()` — no longer calls `_rebuild_model_dropdown` — evidence: grep
- [ ] Change 9: cleaned up `_fill_form()` — no references to removed widgets — evidence: grep
- [ ] No dead code remains: grep returns 0 matches for all removed symbols — evidence: grep
- [ ] Dialog opens with providers from handler — evidence: smoke test output
- [ ] get_values returns clean dict — evidence: smoke test output
