---
status: DONE
---
# SPEC: Agent Builder Provider Dropdown

**Date:** 2026-06-09
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** User clarification (2026-06-09): "Just a drop down of the name. In this case, if you look at providers.yaml, what you would see in the create agent window would be. persist-test, live-sync-test. And you would just select from those two that were set up in the settings."
**Depends on:** `docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md` (the Settings dialog that writes providers.yaml)
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **Composition root** (window.py) is the only owner of new handler construction; handlers receive their dependencies via setters. `AgentBuilderHandler` is constructed in `window._build()` and its `get_available_providers()` method (inherited from `agent_builder_handler.py:187`) is used to populate the dropdown.
> - **`utils/` rule** (no GTK, no network, no UI imports) — no new utils modules needed for this fix.
> - **`ui/handlers/` rule** — no handler changes needed; the existing `AgentBuilderHandler.get_provider_options()` already returns provider dicts from providers.yaml.
> - **CSS rule** (ARCHITECTURE §9) — no new CSS classes needed; existing dropdown styles are sufficient.
> - **No dead code** — this spec explicitly removes unused fields, methods, and dropdowns. After implementation, `grep` for the removed symbols returns zero matches.
> - **`set_provider_options()`** (the method that already exists on `AgentBuilderDialog` at `ui/views/agent_builder.py:301`) is the canonical API for updating the provider dropdown. It must be called at the right times.

---

## 0. Summary

| # | Symptom | Fix |
|---|---------|-----|
| 1 | Agent Builder's Provider dropdown is stuck on "(loading...)" — Save button stays disabled because no provider is selected | Call the existing `set_provider_options()` method from `ui/window.py` to populate the dropdown from providers.yaml at dialog open and when providers change. |
| 2 | User asked: "remove the Provider and Model dropdowns from the Agent Builder entirely. The agent should just use whatever name you gave the provider when you set it up in Settings." | Remove the Model dropdown and the Manual Provider/Model entry fields. The Provider dropdown shows provider names from providers.yaml. The agent references the provider by name; the system looks up the rest (base_url, model, key) from providers.yaml at runtime. |
| 3 | Dead code: `_PROVIDER_MODELS`, `_rebuild_model_dropdown`, `_get_selected_model`, manual mode toggle, API key entry | Remove all dead code. `grep` for these symbols returns zero matches after implementation. |

---

## 1. Overview

### 1.1 Problem statement

The Agent Builder dialog (`ui/views/agent_builder.py`) has a Provider dropdown that is permanently stuck on "(loading...)". The dropdown is constructed with `["(loading...)"]` as a placeholder (line 326), and the method that would replace it — `set_provider_options()` (line 301) — is defined but never called. The result: the user cannot select a provider, the Save button stays disabled, and the agent cannot be created or edited.

The user has confirmed the desired design (2026-06-09):

> "Just a drop down of the name. In this case, if you look at providers.yaml, what you would see in the create agent window would be. persist-test, live-sync-test. And you would just select from those two that were set up in the settings."

In other words: the Agent Builder has a single Provider dropdown showing the names of providers from providers.yaml. The user picks one. The system uses that provider's full config (base_url, default_model, api_key) from providers.yaml at runtime. No Model dropdown, no API key field, no manual entry mode.

### 1.2 Solution summary

1. Call `set_provider_options()` at the right times to populate the dropdown:
   - When the Agent Builder dialog is constructed (from `handler.get_provider_options()`)
   - When the Settings dialog fires `on_providers_changed` (providers added/removed/edited)
2. Remove the Model dropdown, the Manual Provider/Model entry fields, and the API key field. The Provider dropdown is the only provider-related input.
3. Remove all dead code: `_PROVIDER_MODELS`, `_rebuild_model_dropdown`, `_get_selected_model`, `_on_manual_toggled`, `_build_model_dropdown`, manual mode toggle, API key entry, `provider_keys` field in `get_values()`.

### 1.3 Scope

| In scope | Out of scope |
|----------|--------------|
| Call `set_provider_options()` at dialog construction and on `on_providers_changed` | Changing how `agent/runtime.py` resolves the provider config at send time (unchanged — already looks up by name from providers.yaml) |
| Remove Model dropdown, Manual entry fields, API key field | Changing the Settings dialog (already correct) |
| Remove dead code: `_PROVIDER_MODELS`, `_rebuild_model_dropdown`, `_get_selected_model`, `_on_manual_toggled`, manual mode toggle, API key entry, `provider_keys` in `get_values()` | Per-agent API key overrides (rejected by SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md §3.1) |
| Update `get_values()` to return only the provider name (no `provider/model` concatenation, no `provider_keys`) | Multi-model selection per agent (deferred — a provider has one `default_model` in providers.yaml) |
| Update `_update_save_button()` to require only name + prompts + tools + provider selection | Changing the toolbar red dot or the Settings dialog lifecycle |
| Update tests to match the new form | New providers or provider types |
| ARCHITECTURE.md updates per §3 of this spec | |

### 1.4 Architecture principles that apply (per `ARCHITECTURE.md`)

- **§3.6 (Composition root)**: `ui/window.py` is the only place that wires `on_providers_changed` to the agent builder. The wiring must call `set_provider_options()`.
- **§3.7 (Left panel)**: the left panel's `+ Agent` button already calls `window._open_agent_builder()` (verified). No change needed.
- **§3.14 (Chat handler)**: unaffected. Chat rendering doesn't depend on the agent builder.
- **§4 (Data flow)**: the flow is `Settings → providers.yaml → window._on_providers_changed → AgentBuilderDialog.set_provider_options() → dropdown rebuilt`. This must be traceable.
- **§9 (CSS)**: no new CSS classes. Existing dropdown styles (`Gtk.DropDown`) are used.

---

## 2. Changes by File

### 2.1 `ui/views/agent_builder.py` — REVISED

**What changes:**
1. Call `set_provider_options(self._handler.get_provider_options())` at the end of `__init__` (after the form is built, before `self._window.set_child(content)`).
2. Remove the Model dropdown widget construction (line 112-115 area).
3. Remove the Manual Provider/Model entry widgets (lines 121-138 area).
4. Remove the API key entry widget (the `_api_key_entry` — verify exact lines).
5. Remove the methods: `_build_model_dropdown`, `_rebuild_model_dropdown`, `_get_selected_model`, `_on_manual_toggled`.
6. Remove the instance variables: `_PROVIDER_MODELS`, `_manual_mode`, `_provider_keys`, `_model_dropdown`, `_model_labeled`, `_manual_provider_entry`, `_manual_model_entry`, `_manual_provider_labeled`, `_manual_model_labeled`, `_api_key_entry`.
7. Update `_update_save_button()` to require: name + prompts + tools + provider selection (no API key, no model).
8. Update `get_values()` to return: `{"name", "prompts", "tools", "provider", "model", "emoji", "app_title", "si", ...}` — no `provider_keys`, no `api_key`, no `provider/model` concatenation (just the provider name; the system uses the provider's `default_model` from providers.yaml).
9. Keep `set_provider_options()` unchanged (it already does the right thing).
10. Keep `_rebuild_provider_dropdown()` unchanged.
11. Keep `_build_provider_dropdown()` unchanged.

**Verified current code (line 35-60, constructor signature and instance vars):**

```python
def __init__(
    self,
    parent: Gtk.Window,
    *,
    handler,
    agent_def: dict | None = None,
    on_save=None,
    on_cancel=None,
):
    self._handler = handler
    self._on_save = on_save
    self._on_cancel = on_cancel
    self._is_edit = agent_def is not None
    self._original_si = {}  # preserved SI overrides from edit source
    self._tool_checks: dict[str, Gtk.CheckButton] = {}
    self._tool_count_label: Gtk.Label | None = None
    self._mcp_checks: dict[str, Gtk.CheckButton] = {}
    self._provider_keys: dict[str, str] = {}  # provider_id → api_key (legacy, unused in Phase C)
    self._manual_mode: bool = False  # True when manual provider/model entry is active
    self._providers: list = []  # list[ProviderConfig] — populated via set_provider_options()
    self._provider_models: dict[str, list[tuple[str, str]]] = {}  # name → [(display, id), ...]
```

**After change (remove dead instance vars):**

```python
def __init__(
    self,
    parent: Gtk.Window,
    *,
    handler,
    agent_def: dict | None = None,
    on_save=None,
    on_cancel=None,
):
    self._handler = handler
    self._on_save = on_save
    self._on_cancel = on_cancel
    self._is_edit = agent_def is not None
    self._original_si = {}
    self._tool_checks: dict[str, Gtk.CheckButton] = {}
    self._tool_count_label: Gtk.Label | None = None
    self._mcp_checks: dict[str, Gtk.CheckButton] = {}
    self._providers: list = []  # populated via set_provider_options()
```

**Populate the dropdown at construction (add at the end of `__init__`, before `self._window.set_child(content)`):**

```python
# Populate provider dropdown from handler (reads providers.yaml)
self.set_provider_options(handler.get_provider_options())
```

**Verified current `get_values()` (lines 179-208):**

```python
def get_values(self) -> dict:
    """Extract current form values into an agent_def dict."""
    name = self._name_entry.get_text().strip()
    role = self._role_entry.get_text().strip()
    emoji = self._emoji_entry.get_text().strip() or "🤖"
    provider = self._get_selected_provider_id()
    model = self._get_selected_model()
    # ... etc
    return {
        "name": name,
        "role": role,
        "emoji": emoji,
        "provider": provider,
        "model": model,
        "prompts": prompts,
        "tools": tools,
        ...
    }
```

**After change (simplified — no model dropdown, no provider_keys):**

```python
def get_values(self) -> dict:
    """Extract current form values into an agent_def dict.
    The model field is left empty — the runtime resolves the model
    from providers.yaml using the provider name."""
    name = self._name_entry.get_text().strip()
    role = self._role_entry.get_text().strip()
    emoji = self._emoji_entry.get_text().strip() or "🤖"
    provider = self._get_selected_provider_id()
    prompts = self._get_selected_prompts()
    tools = self._get_selected_tools()
    # ... mcp, si, etc. (unchanged)
    return {
        "name": name,
        "role": role,
        "emoji": emoji,
        "provider": provider,
        "model": "",  # resolved at runtime from providers.yaml
        "prompts": prompts,
        "tools": tools,
        ...
    }
```

**Note on `model` field:** The agent YAML still has a `model` field (for backward compatibility with existing agents and with `agent/runtime.py`), but it's left empty when creating a new agent. The runtime looks up the model from providers.yaml. For existing agents with a `model` field, the runtime continues to work as before.

**Verified current `_update_save_button` (lines 762-779 area):**

The current implementation requires `has_api_key` and `has_provider_model`. Both must be removed.

**After change:**

```python
def _update_save_button(self) -> None:
    has_name = bool(self._name_entry.get_text().strip())
    has_prompts = len(self._get_selected_prompts()) > 0
    has_tools = len(self._get_selected_tools()) > 0
    has_provider = bool(self._get_selected_provider_id())
    self._save_btn.set_sensitive(
        has_name and has_prompts and has_tools and has_provider
    )
```

**Form layout — remove the Model column from the Provider/Model row:**

Current (lines 108-116):
```python
provider_model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
provider_model_row.set_hexpand(True)
self._provider_dropdown = self._build_provider_dropdown()
self._provider_labeled = self._labeled_box("Provider", self._provider_dropdown)
provider_model_row.append(self._provider_labeled)
self._model_dropdown = self._build_model_dropdown()
self._model_labeled = self._labeled_box("Model", self._model_dropdown)
provider_model_row.append(self._model_labeled)
```

After:
```python
provider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
provider_row.set_hexpand(True)
self._provider_dropdown = self._build_provider_dropdown()
self._provider_labeled = self._labeled_box("Provider", self._provider_dropdown)
provider_row.append(self._provider_labeled)
```

**Remove the Manual entry widgets (lines 121-138 area, all `self._manual_*` references):**

Delete entirely. The user no longer needs a manual entry fallback — the Settings dialog is the only place to add a provider.

**Remove the API key entry:**

Delete the `_api_key_entry` construction, the reveal toggle button, and all references in `get_values()` and `_update_save_button()`.

**Dead code to remove (verified by `grep`):**

| Symbol | Location | Action |
|--------|----------|--------|
| `_PROVIDER_MODELS` | `ui/views/agent_builder.py` (the old constant) | Verify it doesn't exist as a class attribute; if it does, remove |
| `_build_model_dropdown` | `ui/views/agent_builder.py:343` | Remove method |
| `_rebuild_model_dropdown` | `ui/views/agent_builder.py:349` | Remove method |
| `_get_selected_model` | `ui/views/agent_builder.py:362` | Remove method |
| `_on_manual_toggled` | `ui/views/agent_builder.py:373` | Remove method |
| `_manual_mode` | `ui/views/agent_builder.py:51` | Remove instance var |
| `_provider_keys` | `ui/views/agent_builder.py:50` | Remove instance var |
| `_model_dropdown` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `_model_labeled` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `_manual_provider_entry` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `_manual_model_entry` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `_manual_provider_labeled` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `_manual_model_labeled` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `_api_key_entry` | `ui/views/agent_builder.py` | Remove instance var + widget |
| `provider_keys` in `get_values()` | `ui/views/agent_builder.py:179-208` | Remove from return dict |
| `api_key` in `get_values()` | `ui/views/agent_builder.py:179-208` | Remove from return dict |

**Verified `grep` for these symbols (post-implementation, must return 0 matches):**

```bash
grep -n "_build_model_dropdown\|_rebuild_model_dropdown\|_get_selected_model\|_on_manual_toggled\|_manual_mode\|_provider_keys\|_api_key_entry\|_manual_provider\|_manual_model" ui/views/agent_builder.py
# Expected: 0 matches

grep -n "provider_keys\|api_key" ui/views/agent_builder.py
# Expected: 0 matches (except in comments/docstrings explaining the removal)
```

### 2.2 `ui/window.py` — REVISED

**What changes:** the `_on_providers_changed` callback must call `self._builder_dialog.set_provider_options(providers)` when the agent builder dialog is open.

**Verified current code (lines 752-765):**

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

**After change:**

```python
def _on_providers_changed(self, providers: list) -> None:
    """Refresh the agent builder's provider dropdown after Settings edits.
    Called when providers are added, removed, or edited in the Settings dialog.
    If the agent builder dialog is open, update its dropdown in place.
    Otherwise, the next open will read the current providers.yaml."""
    if hasattr(self, "_builder_dialog") and self._builder_dialog is not None:
        try:
            self._builder_dialog.set_provider_options(providers)
        except Exception as e:
            logger.warning("Failed to update agent builder provider list: %s", e)
```

**Note:** The wiring in `ui/wiring.py:35-42` currently uses `settings_dialog_factory` to deliver `on_providers_changed` to the **settings dialog** (via `dialog.refresh_providers()`). The wiring does **not** route `on_providers_changed` to the agent builder. The agent builder is updated via `window._on_providers_changed`, which is called directly from the SettingsHandler callback wired in `window._build()`.

**Verified wiring (lines 225-232):**

```python
self._settings_handler = wire_settings_handler(
    self._settings_handler,
    self._toolbar,
    settings_dialog_factory=lambda: None,  # No-cache fix from 2026-06-09
)
```

And the `on_status_changed` callback (red dot) goes to `toolbar.set_settings_status`. The `on_providers_changed` callback is set via `handler._on_providers_changed` (verified in `ui/wiring.py:48`).

**Wait — the `on_providers_changed` callback is overwritten by `wire_settings_handler`.** The window's `_on_providers_changed` is never called! Let me re-verify.

**Verified `ui/wiring.py:48`:**

```python
handler._on_providers_changed = _on_providers_changed
```

So `wire_settings_handler` replaces `handler._on_providers_changed` with its own version that only updates the settings dialog (via the factory). The window's `_on_providers_changed` method is never called.

**This is the actual bug.** The window's `_on_providers_changed` is dead code — it's never wired. The fix has two parts:

1. **In `ui/wiring.py`:** the `_on_providers_changed` callback must also notify the agent builder. Either:
   - (a) Call `window._on_providers_changed(providers)` in addition to `settings_dialog_factory().refresh_providers()`, OR
   - (b) Add a new callback `on_providers_changed_external` that the window can register to receive notifications.

2. **In `ui/window.py`:** the `_on_providers_changed` method must call `self._builder_dialog.set_provider_options(providers)`.

**Chosen approach: (a).** Modify `ui/wiring.py:_on_providers_changed` to also call the window's method.

**Verified `ui/wiring.py:35-48`:**

```python
def _on_providers_changed(providers) -> None:
    if settings_dialog_factory is not None:
        try:
            dialog = settings_dialog_factory()
            if dialog is not None:
                dialog.refresh_providers(providers)
        except Exception as e:
            logger.warning(
                "Settings dialog refresh failed (dialog may not be open): %s", e
            )

handler._on_status_changed = _on_status_changed
handler._on_providers_changed = _on_providers_changed
```

**After change:**

```python
def _on_providers_changed(providers) -> None:
    # Refresh the settings dialog (if open)
    if settings_dialog_factory is not None:
        try:
            dialog = settings_dialog_factory()
            if dialog is not None:
                dialog.refresh_providers(providers)
        except Exception as e:
            logger.warning(
                "Settings dialog refresh failed (dialog may not be open): %s", e
            )
    # Refresh the agent builder dialog (if open)
    if agent_builder_factory is not None:
        try:
            builder = agent_builder_factory()
            if builder is not None:
                builder.set_provider_options(providers)
        except Exception as e:
            logger.warning(
                "Agent builder refresh failed (dialog may not be open): %s", e
            )

handler._on_status_changed = _on_status_changed
handler._on_providers_changed = _on_providers_changed
```

**New parameter to `wire_settings_handler`:**

```python
def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable | None = None,
    agent_builder_factory: Callable | None = None,
) -> SettingsHandler:
```

**New wiring in `ui/window.py:225-232`:**

```python
self._settings_handler = wire_settings_handler(
    self._settings_handler,
    self._toolbar,
    settings_dialog_factory=lambda: None,
    agent_builder_factory=lambda: getattr(self, "_builder_dialog", None),
)
```

**After this change, the window's `_on_providers_changed` method (the dead code) can be removed** — its logic now lives in `ui/wiring.py`.

### 2.3 `ui/wiring.py` — REVISED

**What changes:** add `agent_builder_factory` parameter to `wire_settings_handler`. The `_on_providers_changed` callback calls `agent_builder_factory().set_provider_options(providers)` when the factory returns a non-None dialog.

**Verified current signature (line 17-22):**

```python
def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable | None = None,
) -> SettingsHandler:
```

**After change (add `agent_builder_factory`):**

```python
def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable | None = None,
    agent_builder_factory: Callable | None = None,
) -> SettingsHandler:
    """Wire the SettingsHandler callbacks to the toolbar and dialogs.
    ...
    - on_providers_changed → settings_dialog_factory().refresh_providers(providers)
      and agent_builder_factory().set_provider_options(providers)
      (both no-op if factory returns None)
    """
```

**The new parameter is optional** — existing tests that call `wire_settings_handler` without it continue to work.

### 2.4 `ui/handlers/agent_builder_handler.py` — VERIFIED (no change)

**Verified `get_provider_options()` (line 187-189):**

```python
def get_provider_options(self) -> list[dict]:
    """Available providers from agent.json. For UI dropdown."""
    return get_available_providers()
```

`get_available_providers()` is defined in `utils/agent_defs.py:471-487` and reads from `providers.yaml` (per SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md §2.14). No change needed — the data source is already correct.

### 2.5 Tests — REVISED + NEW

| File | What it covers |
|------|---------------|
| `tests/test_agent_builder_dialog.py` (NEW) | The dialog opens with providers from `handler.get_provider_options()`. The dropdown is populated with provider names. `get_values()` returns the selected provider name. |
| `tests/test_agent_builder_no_model_dropdown.py` (NEW) | The dialog has no Model dropdown, no Manual entry, no API key field. `_update_save_button` enables when name + prompts + tools + provider are set (no API key required). |
| `tests/test_window_settings_wiring.py` (REVISED) | The `on_providers_changed` callback in the wiring calls both the settings dialog and the agent builder. When the agent builder is open and providers change, its dropdown updates. |
| `tests/test_agent_builder_handler.py` (REVISED) | `get_provider_options()` returns provider dicts from providers.yaml. Existing tests continue to pass. |

**Test for the wiring (`test_window_settings_wiring.py`):**

```python
def test_on_providers_changed_updates_agent_builder(self, tmp_config_dir):
    """When providers change and the agent builder is open, its dropdown updates."""
    # Setup: create a harness with both dialogs
    # Trigger: call on_providers_changed with a new provider list
    # Assert: the agent builder's set_provider_options was called with the new list
```

**Test for the dialog (`test_agent_builder_dialog.py`):**

```python
def test_dialog_populates_provider_dropdown_from_handler(self, tmp_config_dir):
    """The dialog's provider dropdown shows providers from handler.get_provider_options()."""
    # Setup: create handler with two providers in providers.yaml
    # Open the dialog
    # Assert: dropdown has two items (not "(loading...)")
    # Assert: each item is a provider name from providers.yaml
```

**Test for the simplified form (`test_agent_builder_no_model_dropdown.py`):**

```python
def test_no_model_dropdown(self, tmp_config_dir):
    """The dialog has no Model dropdown widget."""
    # Open the dialog
    # Assert: self._builder_dialog._model_dropdown does not exist
    # (or: the form does not contain a Model label)

def test_no_api_key_field(self, tmp_config_dir):
    """The dialog has no API key entry."""
    # Open the dialog
    # Assert: self._builder_dialog._api_key_entry does not exist

def test_save_button_enables_without_api_key(self, tmp_config_dir):
    """The Save button enables when name + prompts + tools + provider are set."""
    # Fill in name, prompts, tools, select provider
    # Assert: Save button is sensitive
    # Do NOT enter an API key
```

### 2.6 Files NOT changed (verified)

- **`models/providers.py`** — no change. The `ProviderConfig` dataclass is already correct.
- **`utils/providers_store.py`** — no change. `load_providers()` already returns the right shape.
- **`utils/provider_test.py`** — no change.
- **`ui/handlers/settings_handler.py`** — no change. `on_providers_changed` already fires on add/edit/remove.
- **`ui/views/settings_dialog.py`** — no change. The Settings dialog is already correct.
- **`ui/toolbar.py`** — no change. Red dot logic is unchanged.
- **`agent/config.py`** — no change. `load_agent_config` already reads from providers.yaml.
- **`agent/runtime.py`** — no change. Runtime already resolves the model from providers.yaml.
- **`docs/ARCHITECTURE.md`** — update required (see §3 below).

---

## 3. Data Flow

### 3.1 Startup: Agent Builder opens with current providers

```
User clicks `+ Agent` in left panel
  → LeftPanel.on_agent_selected or similar
  → window._open_agent_builder()
    → AgentBuilderDialog(parent, handler, agent_def, on_save, on_cancel)
      → set_provider_options(handler.get_provider_options())
        → handler.get_provider_options() → utils.agent_defs.get_available_providers()
          → utils.providers_store.load_providers() → list[ProviderConfig]
        → self._providers = list(ProviderConfig)
        → self._rebuild_provider_dropdown()
          → Gtk.StringList.new([p.name for p in self._providers])
          → self._provider_dropdown.set_model(names)
      → dialog.show()
```

### 3.2 User adds a provider in Settings while Agent Builder is open

```
User in Settings dialog clicks `+ Add Provider`, fills fields, clicks Save
  → SettingsDialog._on_save → handler.add_or_update(ProviderConfig)
    → utils.providers_store.save_providers([...])
    → handler._on_providers_changed(providers)
      → wire_settings_handler._on_providers_changed(providers)
        → settings_dialog_factory() → None (no-cache) → no-op
        → agent_builder_factory() → self._builder_dialog (the open Agent Builder)
          → self._builder_dialog.set_provider_options(providers)
            → self._providers = list(providers)
            → self._rebuild_provider_dropdown()
              → dropdown rebuilt with new provider names
```

### 3.3 User removes the last provider while Agent Builder is open

```
Same as 3.2, but the new provider list is empty
  → agent_builder_factory() → self._builder_dialog
    → set_provider_options([])
      → self._providers = []
      → self._rebuild_provider_dropdown()
        → names = Gtk.StringList.new(["(no providers — open Settings)"])
        → self._provider_dropdown.set_model(names)
  → Save button disables (no provider selected)
```

### 3.4 User opens Agent Builder for the first time (no providers.yaml)

```
User clicks `+ Agent`
  → window._open_agent_builder()
    → AgentBuilderDialog(...)
      → set_provider_options(handler.get_provider_options())
        → get_provider_options() → get_available_providers() → [] (empty)
        → self._providers = []
        → self._rebuild_provider_dropdown()
          → names = Gtk.StringList.new(["(no providers — open Settings)"])
          → self._provider_dropdown.set_model(names)
  → Save button stays disabled (no provider)
  → User must open Settings and add a provider first
```

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|------|------------|--------------|------|
| `ui/views/agent_builder.py` | REVISED | -120 / +30 | Med (removes user-visible fields, must test all paths) |
| `ui/window.py` | REVISED | -8 / +2 | Low (remove dead code) |
| `ui/wiring.py` | REVISED | +15 | Low (add optional parameter) |
| `tests/test_agent_builder_dialog.py` | NEW | ~80 | — |
| `tests/test_agent_builder_no_model_dropdown.py` | NEW | ~60 | — |
| `tests/test_window_settings_wiring.py` | REVISED | +30 | Low (add test) |

**Total:** ~3 revised + ~2 new test files, ~200 lines net change.

---

## 5. Implementation Order

Numbered so each step leaves the app in a working state.

1. **`ui/wiring.py`** — add `agent_builder_factory` parameter. After this step, the wiring can route `on_providers_changed` to the agent builder. No behavior change yet (parameter is unused by default).
2. **`ui/window.py`** — wire `agent_builder_factory=lambda: getattr(self, "_builder_dialog", None)`. After this step, the wiring calls `self._builder_dialog.set_provider_options(providers)` when providers change. Verify the agent builder dropdown updates.
3. **`ui/views/agent_builder.py`** — populate the dropdown at construction. After this step, opening the agent builder shows the current providers (not "(loading...)").
4. **`ui/views/agent_builder.py`** — remove the Model dropdown, Manual entry, API key field. After this step, the form is simplified.
5. **`ui/views/agent_builder.py`** — update `_update_save_button()` and `get_values()`. After this step, Save works without an API key.
6. **`ui/window.py`** — remove the dead `_on_providers_changed` method (its logic now lives in `ui/wiring.py`).
7. **Tests** — add new tests, update existing tests.

**Verification gate at each step:**
- 1: existing tests pass.
- 2: agent builder dropdown updates when providers change in Settings.
- 3: agent builder opens with current providers from providers.yaml.
- 4: form has no Model dropdown, no Manual entry, no API key field.
- 5: Save enables without an API key.
- 6: no dead code remains (`grep` returns 0 matches).
- 7: all tests pass.

---

## 6. Acceptance Criteria

### 6.1 Functional

- [ ] Opening the Agent Builder dialog shows provider names from providers.yaml (not "(loading...)").
- [ ] If providers.yaml is empty, the dropdown shows "(no providers — open Settings)".
- [ ] Adding a provider in Settings while the Agent Builder is open updates the dropdown.
- [ ] Removing the last provider while the Agent Builder is open shows "(no providers — open Settings)".
- [ ] The Agent Builder form has no Model dropdown, no Manual entry, no API key field.
- [ ] The Save button enables when name + prompts + tools + provider are set (no API key required).
- [ ] `get_values()` returns the selected provider name. The `model` field is empty (resolved at runtime from providers.yaml).
- [ ] Selecting a provider in the Agent Builder and saving creates a valid agent that can authenticate using providers.yaml.

### 6.2 Negative (regression prevention)

- [ ] `grep -n "_build_model_dropdown\|_rebuild_model_dropdown\|_get_selected_model\|_on_manual_toggled\|_manual_mode\|_provider_keys\|_api_key_entry" ui/views/agent_builder.py` returns 0 matches.
- [ ] `grep -n "provider_keys\|api_key" ui/views/agent_builder.py` returns 0 matches (except in comments/docstrings).
- [ ] No dead code remains: the `_on_providers_changed` method in `ui/window.py` is removed (its logic moved to `ui/wiring.py`).
- [ ] Existing `tests/test_agent_builder_handler.py` tests pass.
- [ ] Existing `tests/test_window_settings_wiring.py` tests pass.

### 6.3 Non-functional

- [ ] No new CSS classes needed.
- [ ] No new files needed (only revisions to existing files).
- [ ] No import cycles introduced.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| providers.yaml is empty | Dropdown shows "(no providers — open Settings)". Save button stays disabled. |
| providers.yaml is malformed | `get_provider_options()` returns `[]` (per `load_providers()` tolerance). Dropdown shows empty state. |
| User opens Agent Builder, then opens Settings, adds a provider, closes Settings | Agent Builder dropdown updates. (Because `on_providers_changed` fires on add.) |
| User opens Agent Builder, then opens Settings, removes a provider, closes Settings | Agent Builder dropdown updates. If the removed provider was selected, the dropdown reverts to the first remaining provider. |
| User opens Agent Builder, then opens Settings, removes the selected provider, closes Settings | The dropdown's selection index is now invalid. The `_get_selected_provider_id()` method should handle this gracefully (return empty string or the first provider). |
| User opens two Agent Builder dialogs (edit + create) | The `agent_builder_factory` returns only the most recent `_builder_dialog`. The other dialog's dropdown is stale. (This is a pre-existing limitation — not addressed by this spec.) |
| Agent YAML has a legacy `model` field | The runtime continues to use the legacy `model` field if it's non-empty. New agents are created with `model: ""` and the runtime resolves from providers.yaml. |
| Agent YAML has a legacy `provider_keys` or `api_key` field | These are ignored (per SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md §2.5). The runtime looks up the API key from providers.yaml. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the following updates to `docs/ARCHITECTURE.md` are required:

### 8.1 Update section 3.X `ui/views/agent_builder.py`

Document the simplified form:
- Single Provider dropdown (populated from `handler.get_provider_options()`)
- No Model dropdown
- No Manual entry mode
- No API key field
- Save enables when name + prompts + tools + provider are set
- `get_values()` returns the provider name; `model` is empty (resolved at runtime)

### 8.2 Update section 3.X `ui/wiring.py`

Document the new `agent_builder_factory` parameter to `wire_settings_handler`.

### 8.3 Update section 4 (Data Flow)

Add a new flow: "User adds a provider in Settings while Agent Builder is open → `on_providers_changed` → `wire_settings_handler` → `agent_builder_factory().set_provider_options(providers)` → dropdown rebuilt."

---

## 9. Risk Register

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Existing agents with `model` field break | Low | Runtime already supports `model` field. New agents use `model: ""` and runtime resolves from providers.yaml. |
| User removes a provider that's currently selected in the Agent Builder | Med | Dropdown selection index becomes invalid. `_get_selected_provider_id()` should return empty string in that case, disabling Save. |
| User opens Agent Builder before connecting to gateway | Low | The dialog doesn't depend on the gateway. `get_provider_options()` reads from providers.yaml. |
| Race: Settings dialog and Agent Builder both open, user adds provider in Settings | Low | `on_providers_changed` fires on add; wiring routes to both dialogs. Both update. |
| Dead code in `ui/views/agent_builder.py` is missed | Med | `grep` checks in §6.2 verify zero matches. |
| The `_on_providers_changed` method in `ui/window.py` is removed but still referenced somewhere | Low | `grep` check for `_on_providers_changed` in `ui/window.py` must return 0 matches after removal. |
| Two Agent Builder dialogs open simultaneously | Low | Pre-existing limitation. Not addressed by this spec. |

---

**End of spec.**
