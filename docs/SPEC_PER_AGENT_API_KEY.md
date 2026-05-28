# SPEC: Per-Agent, Per-Provider API Key Enforcement

**Date:** 2026-05-28
**Author:** Qaster
**Status:** Draft — for implementation
**Depends on:** None (builds on existing provider/model dropdown work)
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md §3.21s): View (`agent_builder.py`) is a **pure view** — receives data from `AgentBuilderHandler`, emits user actions via callbacks. No validation logic in the view. Handler (`agent_builder_handler.py`) owns validation/logic with no GTK imports. `agent_defs.py` owns persistence. The Save button sensitivity is widget state management (permitted); data validity decisions are in validation (required).

---

## 1. Overview

### Problem
The agent edit dialog saves an `api_key` to the agent YAML, but there is no enforcement that the key matches the selected provider. If a user switches Coder from OpenRouter to MiniMax, the OpenRouter key travels with it and gets sent to MiniMax's API. Additionally, there is no requirement that an API key is present before saving — a user can save an agent with no key at all, causing runtime failures.

### Solution
- API keys are stored **per-agent, per-provider** in the agent YAML file using a `provider_keys` dict instead of a flat `api_key` string
- When the user changes the provider dropdown, the Access Token field updates to show the key for that provider (if one exists) or empties (if none)
- The Save button is **disabled by default** and only enables when all required fields AND an API key for the selected provider are present (widget state management, not validation)
- Validation in `validate_agent_def()` requires an API key for the selected provider before allowing save
- The view's `_do_save()` remains a pure callback emitter — no validation logic

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| Change `api_key` field → `provider_keys` dict in agent YAML | Changing how agent.json stores provider-level keys |
| Save button enable/disable (widget state) | Adding new providers or models |
| Provider change → update API key field | Runtime changes (already wired) |
| Validation in `agent_defs.py`: API key required for selected provider | ZAI provider (no key available, will remain unusable until key provided) |
| Pre-fill API key from provider_keys on edit | |

---

## 2. Changes by File

### 2.1 `ui/views/agent_builder.py`

**What changes:**
1. Store `self._save_btn` instead of local variable so it can be toggled
2. Add `self._provider_keys: dict[str, str]` instance variable
3. Add `_update_save_button()` — widget state check, sets button sensitivity
4. Wire change notifications on: name entry, API key entry, prompts toggled, tools toggled
5. `_on_provider_changed()` clears API key field, then pre-fills from `provider_keys` if key exists for new provider
6. `_fill_form()` reads from `provider_keys` instead of `api_key`
7. `get_values()` outputs `provider_keys` dict instead of flat `api_key`
8. `_do_save()` stays **unchanged** — pure callback emitter, no validation

**Method signatures:**

```python
def _update_save_button(self) -> None:
    """Enable Save only when all required fields + API key are present."""
```

**Code — Store save button as instance variable:**

In `_build_header()` (lines 209-212), change from:
```python
        save_btn = Gtk.Button(label=save_label)
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda *_: self._do_save())
        header.append(save_btn)
```
to:
```python
        self._save_btn = Gtk.Button(label=save_label)
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.connect("clicked", lambda *_: self._do_save())
        self._save_btn.set_sensitive(False)
        header.append(self._save_btn)
```

Verified against source: `save_btn` appears exactly 4 times in `_build_header()` — lines 209, 210, 211, 212. All become `self._save_btn`.

**Code — New instance variable in `__init__`:**

After line 51 (`self._mcp_checks`), add:
```python
        self._provider_keys: dict[str, str] = {}  # provider_id → api_key (loaded from agent def)
```

**Code — _update_save_button:**

Add as a new method:
```python
    def _update_save_button(self) -> None:
        """Enable Save only when: name, prompts, tools, AND api_key are present.

        This is widget state management (is the form complete?), NOT validation.
        Actual validation lives in validate_agent_def().
        """
        has_name = bool(self._name_entry.get_text().strip())
        has_api_key = bool(self._api_key_entry.get_text().strip())
        has_prompts = any(c.get_active() for c in self._prompt_checks.values())
        has_tools = any(c.get_active() for c in self._tool_checks.values())

        self._save_btn.set_sensitive(has_name and has_api_key and has_prompts and has_tools)
```

Verified: `self._name_entry` (line 89), `self._api_key_entry` (line 104), `self._prompt_checks` (line 338), `self._tool_checks` (line 49) — all exist as instance variables.

**Code — Wire change notifications:**

After line 90 (`self._name_entry = Gtk.Entry()` ... `set_placeholder_text`), add:
```python
        self._name_entry.connect("changed", lambda *_: self._update_save_button())
```

After line 106 (`self._api_key_entry.set_visibility(False)`), add:
```python
        self._api_key_entry.connect("changed", lambda *_: self._update_save_button())
```

In `_build_prompts_list()`, after line 345 (`self._prompt_checks[p["filepath"]] = check`), add:
```python
                check.connect("toggled", lambda *_: self._update_save_button())
```

In `_build_tools_section()`, after line 449 (`check.connect("toggled", lambda *_: self._update_tool_count())`), add:
```python
                check.connect("toggled", lambda *_: self._update_save_button())
```

Verified: GTK CheckButton supports multiple `toggled` handlers (tested: both fire in order).

**Code — _on_provider_changed update:**

Change from:
```python
    def _on_provider_changed(self, dropdown, _param) -> None:
        """When provider changes, rebuild model dropdown with that provider's models."""
        self._rebuild_model_dropdown()
```
to:
```python
    def _on_provider_changed(self, dropdown, _param) -> None:
        """When provider changes, rebuild model dropdown + update API key field."""
        self._rebuild_model_dropdown()
        # Update API key field for the new provider
        provider_id = self._get_selected_provider_id()
        key = self._provider_keys.get(provider_id, "")
        self._api_key_entry.set_text(key)
        self._update_save_button()
```

Verified: `self._get_selected_provider_id()` exists (line 269). `self._api_key_entry` exists. `self._provider_keys` will be added.

**Code — get_values update:**

Change from (lines 153-155):
```python
        provider = self._get_selected_provider_id()
        model = self._get_selected_model()
        api_key = self._api_key_entry.get_text().strip()
```
and in the return dict (line 161):
```python
            "api_key": api_key,
```

to:
```python
        provider = self._get_selected_provider_id()
        model = self._get_selected_model()
        api_key = self._api_key_entry.get_text().strip()

        # Build per-provider keys dict: preserve existing, update current provider
        provider_keys = dict(self._provider_keys)
        if api_key:
            provider_keys[provider] = api_key
```
and in the return dict:
```python
            "provider_keys": provider_keys,
```

Remove the `"api_key": api_key,` line entirely.

**Code — _fill_form update:**

Change from (lines 595-608):
```python
        # Parse model string (format: provider/model_id)
        ...
        GLib.idle_add(_select_model)

        # Pre-fill API key
        api_key = agent_def.get("api_key", "")
        if api_key:
            self._api_key_entry.set_text(api_key)
```

to:
```python
        # Parse model string (format: provider/model_id)
        ...
        GLib.idle_add(_select_model)

        # Load per-provider keys (new format) with fallback to legacy api_key
        self._provider_keys = dict(agent_def.get("provider_keys", {}))
        legacy_key = agent_def.get("api_key", "")
        if legacy_key and provider_id not in self._provider_keys:
            self._provider_keys[provider_id] = legacy_key

        # Pre-fill API key for current provider
        key = self._provider_keys.get(provider_id, "")
        if key:
            self._api_key_entry.set_text(key)
```

This handles backward compat: if YAML has `api_key` but no `provider_keys`, it migrates on load.

**Code — _do_save: NO CHANGE.**

The current code is already correct:
```python
    def _do_save(self) -> None:
        """User clicked Save/Create."""
        self._clear_errors()
        values = self.get_values()
        if self._on_save:
            self._on_save(values)
```

This is a pure callback emitter. Validation happens in `validate_agent_def()` via the handler. Errors flow back through `dialog.show_errors()`.

**Imports:** No new imports needed.

**CSS classes:** No new CSS classes.

**Line count estimate:** ~30 lines added/changed.

---

### 2.2 `utils/agent_defs.py`

**What changes:**
1. `validate_agent_def()` — add check: if `provider` is set, `provider_keys[provider]` must be non-empty (or legacy `api_key` must be non-empty)

**Code — validation addition in `validate_agent_def()`:**

After the model validation block (after line 383 `break`), before the filename collision check (line 386), insert:

```python
    # Validate API key for selected provider
    provider_keys = agent_def.get("provider_keys", {})
    if provider and not provider_keys.get(provider):
        # Check legacy api_key as fallback
        if not agent_def.get("api_key"):
            errors.append(f"API key required for provider '{provider}'")
```

Verified insertion point: line 383 ends the model validation `for` loop. Line 386 starts `# Check for filename collision`. Insert between them.

**Exception types:** `validate_agent_def` only raises no exceptions — it returns a list. `get_available_providers()` can raise from `load_agent_config()` which can raise `OSError` or `json.JSONDecodeError`, but the call is inside a `try/except` that returns `[]` on failure. No new exception paths introduced.

**Line count estimate:** ~5 lines added.

---

### 2.3 `agent/special_agents.py`

**What changes:**
1. `_load_registry()` — read `provider_keys` from YAML, extract key for the agent's provider, fall back to legacy `api_key`

**Code — in `_load_registry()`, line 118:**

Change from:
```python
            api_key=agent_def.get("api_key"),
```
to:
```python
            api_key=agent_def.get("provider_keys", {}).get(agent_def.get("provider", ""), "") or agent_def.get("api_key"),
```

Logic: Try `provider_keys[provider]` first. If empty/missing, fall back to legacy `api_key` field. If both empty, result is `None`.

Verified: `agent_def` is a dict from `_parse_agent_file()`. `.get()` returns `None` for missing keys. `"" or None` evaluates to `None`. `None or "sk-..."` evaluates to `"sk-..."`. Correct fallback chain.

**Line count estimate:** ~1 line changed.

---

### 2.4 `agent/runtime.py`

**No changes.** Already reads `conv.api_key` and falls back to `provider_cfg.api_key` (line 1219: `effective_api_key = conv.api_key or provider_cfg.api_key`). The wiring is correct — `api_key` flows from `SpecialAgentDef.api_key` → `create_conversation(api_key=...)` → `Conversation.api_key` → `_call_llm()`.

---

### 2.5 `models/conversation.py`

**No changes.** Already has `api_key: str | None = None`.

---

### 2.6 `ui/handlers/agent_builder_handler.py`

**No changes.** `handler.save(agent_def)` calls `validate_agent_def(agent_def)` then `save_agent_def(agent_def)`. The new `provider_keys` field flows through naturally — both functions are dict-based and accept arbitrary keys.

---

### 2.7 `ui/window.py`

**No changes.** `_on_builder_save()` calls `handler.save(values)` which calls `validate_agent_def()`. Error messages (including the new "API key required" message) flow back through `dialog.show_errors()`. Already correct.

---

### 2.8 Existing agent YAML files (migration)

**Backward compatibility:** The code in `special_agents.py` falls back to `agent_def.get("api_key")` if `provider_keys` is not present or empty. Existing agent YAML files with `api_key: sk-...` will continue to work.

**Migration path:** When an agent is loaded and saved:
1. `_fill_form()` loads `provider_keys` from YAML. If missing but legacy `api_key` exists, copies it into `provider_keys[provider]`.
2. `get_values()` outputs `provider_keys` (no `api_key`).
3. `save_agent_def()` writes YAML with `provider_keys` dict. Legacy `api_key` field is no longer output.

Result:
```yaml
# Before (legacy):
provider: openrouter
model: openrouter/deepseek/deepseek-v4-pro
api_key: sk-or-...aab0

# After (migrated on next save):
provider: openrouter
model: openrouter/deepseek/deepseek-v4-pro
provider_keys:
  openrouter: sk-or-...aab0
```

---

## 3. Data Flow

### Edit existing agent:
1. User clicks edit on Coder → `window._open_agent_builder("Coder")`
2. `handler.load_for_edit("Coder")` → loads YAML → returns dict with `provider_keys: {openrouter: "sk-or-..."}` (or legacy `api_key: "sk-or-..."`)
3. `AgentBuilderDialog.__init__()` → `_fill_form(agent_def)`
4. `_fill_form()` sets `self._provider_keys = {"openrouter": "sk-or-..."}` (or migrates from legacy `api_key`)
5. Selects "OpenRouter" in provider dropdown → triggers `_on_provider_changed`
6. `_on_provider_changed()` rebuilds model dropdown, reads `self._provider_keys.get("openrouter")` → pre-fills API key field
7. `_update_save_button()` → all fields present → Save enabled
8. User clicks Save → `_do_save()` → pure callback → `on_save(values)`
9. `values["provider_keys"] = {"openrouter": "sk-or-..."}`
10. `handler.save(values)` → `validate_agent_def()` checks `provider_keys["openrouter"]` non-empty → passes
11. `save_agent_def(values)` → writes YAML with `provider_keys` dict (no `api_key`)

### Save without API key:
1. User creates new agent, fills name/prompts/tools but leaves API key empty
2. `_update_save_button()` → `has_api_key = False` → Save button disabled
3. User cannot click Save (button is insensitive)
4. Even if bypassed (e.g. programmatic call), `_do_save()` emits `on_save(values)`
5. `handler.save(values)` → `validate_agent_def()` → `"API key required for provider 'openrouter'"` → returns `(False, [error])`
6. `window._on_builder_save()` → `dialog.show_errors(["API key required..."])` → error shown at bottom

### Switch provider:
1. User changes provider from OpenRouter to MiniMax
2. `_on_provider_changed()` fires
3. Rebuilds model dropdown with MiniMax models
4. Reads `self._provider_keys.get("minimax")` → empty string (no key stored for minimax)
5. Sets API key field to empty string → triggers `changed` signal → `_update_save_button()` → Save disabled
6. User enters MiniMax key → field changes → `_update_save_button()` → Save enabled
7. On save: `get_values()` builds `provider_keys = {"openrouter": "sk-or-...", "minimax": "sk-cp-..."}` — both keys preserved

### Runtime resolution (no changes needed):
1. `special_agents.py` reads `provider_keys[provider]` → sets `SpecialAgentDef.api_key`
2. Handler passes `agent_def.api_key` to `create_conversation(api_key=...)`
3. `Conversation.api_key` stored
4. `_call_llm()` → `effective_api_key = conv.api_key or provider_cfg.api_key`

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `ui/views/agent_builder.py` | Modified | ~30 | Medium — save button wiring, provider_keys flow |
| `utils/agent_defs.py` | Modified | ~5 | Low — one new validation check |
| `agent/special_agents.py` | Modified | ~1 | Low — read provider_keys with fallback |
| `agent/runtime.py` | No change | 0 | — |
| `models/conversation.py` | No change | 0 | — |
| `ui/handlers/agent_builder_handler.py` | No change | 0 | — |
| `ui/window.py` | No change | 0 | — |

**Files NOT changed** (already correct):
- `agent/runtime.py` — already reads `conv.api_key or provider_cfg.api_key`
- `models/conversation.py` — already has `api_key` field
- `ui/handlers/agent_builder_handler.py` — passes dict through, no changes needed
- `ui/window.py` — already wires save/cancel callbacks and shows errors from validation

---

## 5. Implementation Order

1. **Add `provider_keys` support to `agent_builder.py`** — new instance variable, update `_fill_form()`, `_on_provider_changed()`, `get_values()`
2. **Wire save button** — store as `self._save_btn`, start disabled, add `_update_save_button()`, connect change signals to name/api_key/prompts/tools
3. **Update `validate_agent_def()` in `agent_defs.py`** — check `provider_keys[provider]` with legacy fallback
4. **Update `_load_registry()` in `special_agents.py`** — read from `provider_keys` with legacy `api_key` fallback
5. **Test** — edit Coder, switch providers, verify key field updates, verify save blocked without key
6. **Verify existing agents still work** — agents without `provider_keys` should fall back to `agent.json` provider key

**Verification at each step:**
1. `python3 -c "from ui.views.agent_builder import AgentBuilderDialog"` → import OK
2. Save button visible and disabled in new dialog; enables when all fields filled
3. `python3 -c "from utils.agent_defs import validate_agent_def; print(validate_agent_def({'provider': 'openrouter', 'provider_keys': {}}))"` → returns error about API key
4. `python3 -c "from agent.special_agents import get_special_agents; print(get_special_agents())"` → agents load with backward compat
5. End-to-end test in CrabCakes: edit Coder, change provider, verify key field changes
6. MiniMax agents (Debugger, etc.) still work with `agent.json` key as fallback

---

## 6. Acceptance Criteria

- [ ] Save button disabled when dialog opens (new agent)
- [ ] Save button enables only when: name + API key + prompts + tools all present
- [ ] Switching provider updates API key field (pre-fills if key exists, empties if not)
- [ ] Saving without API key shows "API key required for provider '...'" error from validation
- [ ] Agent YAML stores `provider_keys` dict (not flat `api_key`)
- [ ] Multiple providers can have keys stored: `provider_keys: {openrouter: "sk-1", minimax: "sk-2"}`
- [ ] Existing agents with old `api_key` field still load (backward compat)
- [ ] Runtime uses per-agent key for the selected provider
- [ ] When `provider_keys[provider]` is empty and no legacy key, runtime falls back to `agent.json` provider key
- [ ] Editing Coder (currently using openrouter) works end-to-end
- [ ] `_do_save()` remains a pure callback emitter with no validation logic

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| New agent, no key entered | Save disabled (widget). If bypassed, validation error from `agent_defs.py` |
| Edit agent, switch to provider with no stored key | Key field empties, Save disables |
| Edit agent, switch to provider WITH stored key | Key field pre-fills, Save enables |
| Edit agent, switch provider, enter key, switch back | Original provider's key still in `provider_keys` (preserved in memory) |
| Legacy agent with `api_key` but no `provider_keys` | `_fill_form()` migrates to `provider_keys`. `special_agents.py` falls back to `api_key`. Both paths work. |
| Agent YAML has both `api_key` and `provider_keys` | `provider_keys` takes priority. Legacy `api_key` ignored. |
| User clears all text from API key field | `changed` signal fires → `_update_save_button()` → Save disables |
| Provider has empty string in `provider_keys` | `_update_save_button()`: `bool("") = False` → Save disables. `validate_agent_def()`: `not ""` → adds error |
| `provider_keys` exists but current provider not in it | Key field empty, Save disabled |

---

## 8. ARCHITECTURE.md Updates Required

- Section 3.21s (agent_builder.py layout): add Access Token field and Save button behavior
- Section 3.21r (agent_builder_handler.py validation): note `provider_keys` validation
- Section 11 (agent YAML schema): document `provider_keys` field, deprecate `api_key`

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `_update_save_button()` uses `self._name_entry` (line 89), `self._api_key_entry` (line 104), `self._prompt_checks` (line 338), `self._tool_checks` (line 49) — all verified exist as instance variables
   - `_build_header()` save button local variable `save_btn` verified at lines 209-212 — all 4 references identified
   - `_on_provider_changed` uses `self._rebuild_model_dropdown()` (line 283), `self._get_selected_provider_id()` (line 269), `self._api_key_entry` — all verified
   - `get_values()` verified at lines 132-166 — `provider` at line 153, `api_key` at line 155
   - `validate_agent_def` insertion point verified: after line 383, before line 386
   - `special_agents.py` line 118 verified: `api_key=agent_def.get("api_key"),`
   - Multiple `toggled` handlers on CheckButton verified working via live test

2. **Did I catch all exception types?**
   - No new exception paths. `validate_agent_def` returns errors, never raises. `save_agent_def` handles `ImportError` and `OSError`. No new exception types introduced.

3. **Did I verify key structures?**
   - `provider_keys` is `{str: str}` — provider_id → api_key. Simple dict. Insertion order preserved by Python 3.7+ dict. Verified.

4. **Did I trace the data flow end-to-end?**
   - Dialog → `get_values()` → `on_save(values)` → `handler.save(values)` → `validate_agent_def(values)` → error or `save_agent_def(values)` → YAML → `_load_registry()` → `SpecialAgentDef.api_key` → `create_conversation(api_key=...)` → `Conversation.api_key` → `_call_llm()`. Full path traced and verified at each step.

5. **Would an implementer produce working code?**
   - Yes. All method signatures, variable names, line numbers, and signal connections verified against current source. No invented APIs or assumed behavior.

6. **Architecture compliance verified?**
   - `_do_save()` remains a pure callback emitter — no validation logic in the view ✓
   - `_update_save_button()` is widget state management (button sensitivity) — permitted for views ✓
   - All validation logic lives in `validate_agent_def()` in `utils/agent_defs.py` ✓
   - Handler has no GTK imports ✓
   - View has no business logic ✓
