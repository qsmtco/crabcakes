---
status: DONE
---
# SPEC: LLM Provider Settings Dialogue

**Date:** 2026-06-07
**Author:** Qaster (following `docs/proposals/PROPOSAL-llm-provider-settings-dialogue.md`)
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-llm-provider-settings-dialogue.md` (QTR, 2026-06-07)
**Depends on:** None
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **Composition root** (window.py) is the only owner of new handler construction; handlers receive their dependencies via setters. The new `SettingsHandler` is constructed in `window._build()` and injected.
> - **`utils/` rule** (no GTK, no network, no UI imports) — `utils/providers_store.py` follows the `feed_store.py` / `projects.py` pattern: pure functions on a `ProviderConfig` dataclass from `models/`. No GTK, no urllib, no event loop.
> - **`ui/handlers/` rule** — `SettingsHandler` is logic + data with GLib dispatch only; no widget construction. The view `ui/views/settings_dialog.py` is pure widget code, no business logic, emits `on_save` / `on_test` / `on_cancel` callbacks upward.
> - **CSS rule** (ARCHITECTURE §9) — new selectors (`settings-*`, `settings-status-*`, `toolbar-status-dot`) live in `ui/styles.py`; views use `add_css_class()`, never inline `CssProvider`.
> - **Manifests** — every new module declares its reads, writes, network, and dependencies in its top docstring (matches `agent/config.py`, `utils/feed_store.py`).
> - **`app_title` remains per-agent.** Per §8.1.1 of the proposal and the existing `SpecialAgentDef.app_title` field, the `X-Title` header is an OpenRouter attribution concern tied to the agent, not the provider. The Settings dialog does **not** touch `app_title`. The Agent Builder keeps it.
> - **No `provider_keys` in agent YAMLs.** Per §5 of the proposal: agent YAMLs (and `SpecialAgentDef` field) lose `provider_keys` and `api_key`; API keys are read only from `providers.yaml`.

---

## 0. Summary

| # | Symptom | Fix |
|---|---------|-----|
| 1 | `agent.json` is misnamed (it's app-level infra, not agent config) | Rename the runtime role of that file: keep its on-disk path (`agent.json`) but treat it as the legacy fallback. New canonical store is `~/.config/crabcakes/providers.yaml`. |
| 2 | Hardcoded provider/model dropdowns in `ui/views/agent_builder.py:183-194` | Drop the `_PROVIDERS` and `_PROVIDER_MODELS` constants; fetch from `SettingsHandler.list_providers()`. |
| 3 | No validation at config time — "silent fail" first message | New Settings dialog with **Test Connection** button on every provider card. |
| 4 | Two-layer key confusion (`agent.json` + per-agent `provider_keys`) | Single source of truth: `providers.yaml`. Agents lose `api_key` and `provider_keys`. |
| 5 | Status discovery — no way to know "my keys are bad" before sending a message | Red status dot on the ⚙ toolbar button, cleared by a successful Test Connection. |

---

## 1. Overview

### 1.1 Problem statement (verbatim from proposal §1)

`agent.json` is misnamed. It contains `providers` and `enforcement` config — application-level
infra, not agent-specific configuration. The file is hardcoded with a small set of providers
and a small set of models per provider, with no UI to add, edit, or remove them, no validation
at config time, and no way to know whether a configured provider actually accepts your API
key until you send a message.

### 1.2 Solution summary

A new top-right **⚙ Settings** button in the toolbar opens a GTK4 dialog that lists every
provider, lets the user add/edit/delete providers, and validates each with a **Test
Connection** action. Provider credentials live in a new canonical file
`~/.config/crabcakes/providers.yaml`. Agent YAMLs lose `provider_keys` and `api_key` —
the runtime resolves keys from `providers.yaml` keyed by the model's `provider/` prefix.

A red status dot on the toolbar ⚙ button disappears when at least one provider passes
Test Connection, and never reappears unless the user removes the last known-good provider.

### 1.3 Scope

| In scope | Out of scope (explicit, per proposal §9) |
|----------|------------------------------------------|
| New `models/providers.py` dataclass | Per-agent API key overrides (rejected by proposal §3.1) |
| New `utils/providers_store.py` (pure functions) | OAuth, encrypted storage, keychain integration |
| New `ui/views/settings_dialog.py` (pure view) | Auto-discovery of providers from running LLM processes |
| New `ui/handlers/settings_handler.py` (logic) | Migration shims from `agent.json` to `providers.yaml` |
| New toolbar ⚙ button + red status dot | User-facing installer (no .deb/.AppImage work) |
| `SpecialAgentDef` field removals (`api_key`, `provider_keys`) | |
| `ui/views/agent_builder.py` simplification (Phase C) | |
| Red status dot on ⚙ button | |
| First-run greeting if `providers.yaml` is empty | |
| `app_title` STAYS per-agent (not provider-level) | |
| `agent.json` for the **enforcement** section survives; **providers** section is read but ignored if `providers.yaml` exists | |

### 1.4 Architecture principles that apply (per `ARCHITECTURE.md`)

- **§3.21d (handlers)**: logic only, no widgets; GLib dispatch only.
- **§3.22d (`utils/feed_store.py` pattern)**: pure functions on a dataclass, file I/O, no GTK.
- **§3.31 (`utils/review_log.py` pattern)**: append/retrieve with `get_…` and `add_…` named functions.
- **§4 (Data Flow)**: every user action has a one-line data flow traceable to the file & function.
- **§9 (CSS)**: all new CSS classes in `ui/styles.py`; views use `add_css_class()`.

---

## 2. Changes by File

### 2.1 `models/providers.py` — NEW

**Responsibility:** plain dataclass for a single LLM provider. No GTK, no network, no file I/O.

**Public API (verified against `models/agent.py` / `agent/config.py:23-31`):**

```python
from dataclasses import dataclass, field

@dataclass
class ProviderConfig:
    name: str                          # primary key, e.g. "openrouter"
    base_url: str                      # e.g. "https://openrouter.ai/api/v1"
    api_key: str                       # plaintext; file is chmod 600
    default_model: str                 # bare model id, e.g. "deepseek/deepseek-v4-pro"
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    # Last successful Test Connection timestamp (ISO 8601, UTC) — drives red dot.
    # None means "never tested" — counts as unverified for status dot purposes.
    last_verified_at: str | None = None
    # Last failure message (any string) — surfaced in the Settings card.
    last_error: str | None = None
```

**No `app_title` here.** Per the proposal's explicit note and `SpecialAgentDef.app_title`'s
existing role, app attribution is agent-level. This model has no such field.

**Manifest (top docstring):**
- Reads: nothing
- Writes: nothing
- Network: none
- Imports: only stdlib `dataclasses`

### 2.2 `utils/providers_store.py` — NEW

**Responsibility:** YAML persistence for `ProviderConfig` list. Pure functions — no GTK, no
state, no logging beyond stdlib. Mirrors `utils/feed_store.py` and `utils/review_log.py`.

**Public API:**

```python
from models.providers import ProviderConfig

def get_providers_path() -> str:
    """Return absolute path to providers.yaml under utils.config.get_config_dir().
    Does NOT create the file."""

def load_providers() -> list[ProviderConfig]:
    """Read providers.yaml → list[ProviderConfig]. Empty list if missing.
    Tolerates malformed lines (logs warning, skips)."""

def save_providers(providers: list[ProviderConfig]) -> None:
    """Write list[ProviderConfig] → providers.yaml. Creates parent dir.
    File is written with mode 0o600 (owner-only — contains API keys).
    Parent dir is chmod 0o700 if it didn't already exist."""

def add_provider(providers: list[ProviderConfig], p: ProviderConfig) -> None:
    """Append-and-save. Replaces existing entry with the same name."""

def remove_provider(providers: list[ProviderConfig], name: str) -> None:
    """Remove-by-name-and-save. No-op if not found."""

def update_provider(providers: list[ProviderConfig], p: ProviderConfig) -> None:
    """Replace existing entry with same name. Adds if new."""

def has_any_verified_provider(providers: list[ProviderConfig]) -> bool:
    """True if at least one provider has last_verified_at set. Drives the red dot."""
```

**Verified signature (from `utils/config.py:14-23`):** `get_config_dir() -> str` — returns
`$XDG_CONFIG_HOME/crabcakes` or `~/.config/crabcakes`.

**File format (YAML, with JSON fallback if `pyyaml` is missing — same pattern as
`utils/agent_defs.py:64-103`):**

```yaml
- name: openrouter
  base_url: https://openrouter.ai/api/v1
  api_key: sk-or-...
  default_model: deepseek/deepseek-v4-pro
  enabled: true
  supports_tools: true
  supports_streaming: true
  max_tokens: 128000
  last_verified_at: 2026-06-07T20:30:00Z
  last_error: null
- name: minimax
  base_url: https://api.minimax.chat/v1
  api_key: ...
  ...
```

**Permission tightening:** `save_providers` does `os.chmod(path, 0o600)` after writing.
The parent dir is `0o700` (matches `agent/config.py:107-110`).

**No migration from `agent.json`.** Per proposal §5.2.3 ("hard cutover"), users must
re-enter keys in the Settings dialog. We **read** `agent.json`'s `providers` section as a
fallback if `providers.yaml` is missing — see §2.4 below for the resolution order.

### 2.3 `utils/provider_test.py` — NEW

**Responsibility:** Hit a provider's `/models` endpoint (or one cheap chat completion) to
verify the key works. Pure network I/O — no GTK, no logging, returns a result dataclass.

**Public API:**

```python
from dataclasses import dataclass

@dataclass
class TestResult:
    ok: bool
    latency_ms: int                # round-trip time; 0 on failure
    error: str | None              # provider's error message; None on success
    model_used: str                # the model that was used for the test

def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
) -> TestResult:
    """
    Send a 1-token completion to the provider. Returns TestResult.

    Resolves the right HTTP caller the same way agent.runtime does
    (openai-compatible vs anthropic), so behavior matches what the runtime
    will actually do at send-time.

    On MiniMax, a body-level error (HTTP 200 with base_resp.status_code != 0)
    is treated as failure with the decoded status_msg in `error` — mirroring
    agent.runtime._call_minimax (lines 145-160).
    """
```

**Implementation notes (verified against `agent/runtime.py:68-200`):**
- Provider detection: `model.split("/")[0]` if `/` in model, else default.
- OpenAI-compatible (openai, openrouter, zai, minimax): POST `{base_url}/chat/completions`
  with `{"model": <bare>, "messages": [{"role":"user","content":"hi"}], "max_tokens": 1}`.
  Headers: `Authorization: Bearer <api_key>`; `HTTP-Referer` + `X-Title` if `app_title`
  is supplied (we don't supply it here — that's an agent concern).
- Anthropic: POST `{base_url}/messages` with `{"model": <bare>, "messages": [...], "max_tokens": 1}`.
  Headers: `x-api-key`, `anthropic-version: 2023-06-01`.
- Body-level MiniMax error: parse JSON, check `base_resp.status_code != 0` → return
  `TestResult(ok=False, error=f"status_code={n}: {msg}")`.

**Manifest (top docstring):**
- Reads: nothing
- Writes: nothing
- Network: yes (HTTPS POST to provider)
- Imports: stdlib `urllib`, `json`, `time`; `models.providers`

**No reuse of `agent/runtime._call_openai`** — that function is a non-streaming body-return
and would pull in the whole `agent.runtime` import chain (config, conversation, tools). Keep
this module dependency-free so the Settings dialog can be tested without bringing up the
runtime.

### 2.4 `agent/config.py` — REVISED

**What changes:** add a new `load_providers_from_yaml()` and make `LLMProviderConfig` map
transparently to `ProviderConfig`. Keep `agent.json` as a **fallback** for one release
(not the migration shim the proposal rejects — just a safety net so a user with a populated
`agent.json` and no `providers.yaml` still works).

**Verified existing API (lines 86-196):**

```python
def load_agent_config(config_path: str | None = None) -> AgentConfig: ...
def get_api_key(provider_name: str) -> str | None: ...
```

**New behavior of `load_agent_config()` (precedence order, top-down):**
1. If `providers.yaml` exists and has entries → use it.
2. Else if `agent.json` exists with `providers` → use those, with a one-time warning
   log: `agent.json: providers section is deprecated; will be ignored once providers.yaml is created.`
3. Else: write a default `providers.yaml` with no providers, return empty.

**Concretely**, the change is in the `for name, prov in raw.get("providers", {}).items():`
loop (verified around line 175 of `agent/config.py`). The new logic is:
- If `_load_providers_from_yaml_or_fallback()` returns a non-empty list, use it.
- Otherwise, fall through to the existing `raw.get("providers", {})` path (which keeps
  working for users who haven't migrated).
- The return value of `AgentConfig` is unchanged in shape.

**New function added:**

```python
def _load_providers_from_yaml_or_fallback() -> list[dict]:
    """Read providers.yaml if present, else fall back to agent.json providers."""
    from utils.providers_store import load_providers
    yaml_providers = load_providers()
    if yaml_providers:
        return [_provider_to_dict(p) for p in yaml_providers]
    # Fallback — agent.json
    if os.path.isfile(_get_agent_json_path()):
        try:
            with open(_get_agent_json_path()) as f:
                raw = json.load(f)
            providers = raw.get("providers", {})
            logger.warning(
                "agent.json: providers section is deprecated and will be ignored "
                "once providers.yaml is created. Use Settings → Providers to migrate."
            )
            return [
                {"name": n, "base_url": p.get("base_url",""),
                 "api_key": p.get("api_key",""), "default_model": p.get("default_model",""),
                 "supports_tools": p.get("supports_tools", True),
                 "supports_streaming": p.get("supports_streaming", True),
                 "max_tokens": p.get("max_tokens", 128_000),
                 "last_verified_at": None, "last_error": None}
                for n, p in providers.items()
            ]
        except (OSError, json.JSONDecodeError):
            pass
    return []
```

**Keep `agent.json` for the `enforcement` section.** Only its `providers` field is deprecated.
`enforcement`, `default_provider`, `max_tool_iterations`, `cost_limit`, `step_limit` remain
in `agent.json` (and are read by the existing `load_agent_config` lines 175-194 unchanged).

**Verified existing field** (line 24-32 of `agent/config.py`):
`LLMProviderConfig.name, base_url, api_key, default_model, supports_tools, supports_streaming, max_tokens`
— these are the fields that map directly. We add `enabled`, `last_verified_at`, `last_error`
as new optional fields on `LLMProviderConfig` (default `True`, `None`, `None`).

### 2.5 `agent/special_agents.py` — REVISED

**What changes:** drop `api_key` and `provider_keys` from `SpecialAgentDef` resolution. Keep
`app_title`. Use `app_title` in the X-Title header at runtime (unchanged).

**Verified current field (line 28-44):**
```python
api_key: str | None = None
app_title: str | None = None
```

**Change at line 125** (`agent/special_agents.py`):

Before:
```python
api_key=agent_def.get("provider_keys", {}).get(agent_def.get("provider", ""), "") or agent_def.get("api_key"),
```

After:
```python
# Per Phase B: keys are resolved from providers.yaml at runtime, not stored on the agent.
api_key=None,
```

**Verified line 126 (app_title) is unchanged.**

**Backward compatibility:** if the YAML file has legacy `provider_keys` or `api_key` keys,
they're simply ignored (the dataclass fields aren't read). No migration warning — the proposal
rejects migration shims, and the Settings dialog is the user-facing migration path.

**`app_title` flow is unchanged.** Lines 41 (field), 117 (`agent_def.get("app_title")`),
and the runtime's `x_title` argument (agent/runtime.py:131, 178) all stay the same.

### 2.6 `agent/runtime.py` — REVISED

**What changes:** the per-conversation `api_key` resolution must look at `providers.yaml` when
`conv.api_key` is empty, using the `provider/` prefix from `conv.model`.

**Verified location** — `_call_llm` is at line 1281. The relevant block is:

- Line 1301: `provider_cfg = config.providers.get(provider_name)`
- Line 1302-1314: existing `if provider_cfg is None` branch
- Line 1320: `effective_api_key = conv.api_key or provider_cfg.api_key` ← patch target

**Replace line 1320 with:**

Before:
```python
effective_api_key = conv.api_key or provider_cfg.api_key
```

After:
```python
effective_api_key = conv.api_key or provider_cfg.api_key
if not effective_api_key:
    # Phase B: providers.yaml is the canonical store for API keys.
    try:
        from utils.providers_store import load_providers
        for p in load_providers():
            if p.name == provider_name and p.api_key:
                effective_api_key = p.api_key
                break
    except Exception as e:
        logger.warning("Cannot load providers.yaml fallback for %s: %s", provider_name, e)
```

**Imports:** add at the top of the function body or module level. The function is
`_call_llm` — only the import-once change is needed at the top of the file.

### 2.7 `ui/handlers/settings_handler.py` — NEW

**Responsibility:** Settings dialog logic. Owns the list of providers, save/delete/test
operations, and the red-dot status check. Wires Test Connection to `utils/provider_test`.

**Public API:**

```python
import logging
from typing import Callable
from models.providers import ProviderConfig
from utils.providers_store import (
    load_providers, save_providers, has_any_verified_provider,
)

class SettingsHandler:
    def __init__(self, *, GLib_module=None, parent_window=None,
                 on_providers_changed: Callable[[list[ProviderConfig]], None] | None = None,
                 on_status_changed: Callable[[bool], None] | None = None):
        """
        Args:
            GLib_module: gi.repository.GLib — for idle_add dispatch of test results.
            parent_window: Gtk.Window — for transient_for on confirmations.
            on_providers_changed: Called with the new list when providers are
                added/removed/edited. UI uses this to re-render.
            on_status_changed: Called with True if any provider is verified.
                Window uses this to update the toolbar red dot.
        """
        self._GLib = GLib_module
        self._parent_window = parent_window
        self._on_providers_changed = on_providers_changed
        self._on_status_changed = on_status_changed

    def list_providers(self) -> list[ProviderConfig]:
        """Load from providers.yaml. Pure read — no I/O beyond yaml."""
        return load_providers()

    def add_or_update(self, provider: ProviderConfig) -> None:
        """Validate fields non-empty, then save. Fires on_providers_changed."""

    def remove(self, name: str) -> None:
        """Remove by name. Fires on_providers_changed and on_status_changed
        if the last verified provider was removed."""

    def test_provider(self, provider: ProviderConfig,
                      on_result: Callable[[TestResult], None]) -> None:
        """
        Run test_connection in a daemon thread; dispatch result to on_result
        via GLib.idle_add if available. On success: stamps last_verified_at and
        clears last_error, then saves. On failure: stamps last_error, saves.
        Always fires on_status_changed after.
        """

    def status_has_verified(self) -> bool:
        """Return True if any provider is verified (drives the red dot)."""
```

**Verified existing pattern** (from `ui/handlers/agent_builder_handler.py:96-128`):
`AgentBuilderHandler.delete_agent_with_confirmation` shows the GLib.idle_add + transient_for
pattern we'll mirror for confirmations.

**Test Connection threading:** run the test in a `threading.Thread(daemon=True)` — the
existing `agent.runtime` does the same (line 779). Don't block the GTK main thread.

**Imports:** `from utils.provider_test import test_connection, TestResult`.

### 2.8 `ui/views/settings_dialog.py` — NEW

**Responsibility:** GTK4 dialog, pure view. Emits callbacks for add/edit/remove/test/save.

**Public API:**

```python
class SettingsDialog:
    def __init__(self, parent: Gtk.Window, *, handler: SettingsHandler,
                 on_close=None):
        """Build the dialog. No business logic."""

    def show(self) -> None: ...
    def close(self) -> None: ...

    # Used by handler.on_providers_changed to keep the list in sync after edits.
    def refresh_providers(self, providers: list[ProviderConfig]) -> None: ...
```

**Layout (per proposal §3.2, verified against `ui/views/agent_builder.py` for
GTK4 idioms — `Gtk.DropDown` is `Gtk.DropDown(model=Gtk.StringList.new(...))`,
`add_css_class` for theming, `set_vexpand`/`set_hexpand` for sizing):**

- Header bar: title "Settings" + Close button (right).
- Body: `Gtk.ScrolledWindow` (vexpand) wrapping a vertical `Gtk.Box`.
- **Providers section:**
  - Per-provider `Gtk.Frame` (or styled `Gtk.Box`) with:
    - Provider name (read-only label, or editable entry if creating)
    - Base URL entry
    - Default model entry
    - API key entry (`set_visibility(False)`, with reveal toggle `Gtk.Button` 👁)
    - **Test Connection** button (`add_css_class("settings-test-btn")`) with inline status label
      (✅/❌ + latency or error)
    - Remove button (`add_css_class("settings-remove-btn")`) for non-builtin providers
  - "+ Add Provider" button at the bottom (`add_css_class("suggested-action")`).
- **First-run empty state:** if no providers, render a centered greeting with a single
  "Add your first provider" call-to-action (per proposal §3.1.1 / §3.4).

**Verified GTK4 idioms** (from `agent_builder.py`):
- `gi.require_version('Gtk', '4.0')` at top of file.
- Dropdowns: `Gtk.DropDown(model=Gtk.StringList.new([...]))` (lines 333-336).
- Password fields: `entry.set_visibility(False)` + `entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)` (lines 144-146).
- Modal transient: `dialog.set_transient_for(parent); dialog.set_modal(True)` (lines 65-66).
- No inline CSS — `add_css_class` only.

**CSS classes used** (defined in `ui/styles.py` §2.13 below):
- `settings-dialog`, `settings-provider-card`, `settings-test-btn`, `settings-remove-btn`,
  `settings-status-ok`, `settings-status-fail`, `settings-status-untested`, `settings-empty-state`.

**Files NOT changed** (already correct, proposal §3.4.2):
- `ui/views/agent_builder.py` will be simplified in Phase C (§2.10 below) — not in this
  initial commit.

### 2.9 `ui/toolbar.py` — REVISED

**What changes:** add a ⚙ Settings button to the right_box, with an optional red status dot.

**Verified current layout** (`ui/toolbar.py:50-66`): horizontal `right_box` containing
`status_label` + `connect_btn`. We'll insert a settings button between them, with a
status dot as a child widget.

**New widget construction (inside `__init__`, after `right_box` is created):**

```python
# Settings button + red status dot
self._settings_btn = Gtk.Button(label="⚙ Settings")
self._settings_btn.add_css_class("settings-toolbar-btn")
self._settings_btn.set_size_request(110, -1)
self._settings_btn.connect("clicked", self._on_settings_click)
right_box.append(self._settings_btn)
```

**Status dot:** a child `Gtk.Label` styled with `toolbar-status-dot` (red, hidden by
default) overlaid on the button. Easiest: use a `Gtk.Overlay` wrapper around the button —
or simply set the button's label conditionally. Per the proposal's design ("the red dot
sits at the top-right of the ⚙ button"), a `Gtk.Overlay` is the right call.

```python
# Wrap settings button in an overlay to show a red dot
overlay = Gtk.Overlay()
overlay.set_child(self._settings_btn)
self._status_dot = Gtk.Label(label="●")
self._status_dot.add_css_class("toolbar-status-dot")  # defined in styles.py §2.13
self._status_dot.set_halign(Gtk.Align.END)
self._status_dot.set_valign(Gtk.Align.START)
self._status_dot.set_visible(False)  # hidden until needed
overlay.add_overlay(self._status_dot)
right_box.append(overlay)
```

**New public method:**

```python
def set_settings_status(self, has_verified_provider: bool) -> None:
    """Show/hide the red dot. Window calls this on startup and after providers change."""
    self._status_dot.set_visible(not has_verified_provider)
```

**New private method:**

```python
def _on_settings_click(self, *args) -> None:
    if self._on_settings_clicked is not None:
        self._on_settings_clicked()
```

**New constructor arg:**
```python
def __init__(self, on_connect_clicked=None, on_settings_clicked=None):
    ...
    self._on_settings_clicked = on_settings_clicked
```

### 2.10 `ui/views/agent_builder.py` — REVISED (Phase C)

**What changes:** remove `_PROVIDERS` and `_PROVIDER_MODELS` constants (lines 183-194).
The provider dropdown is now populated from `SettingsHandler.list_providers()`.

**Verified current code (lines 182-194):**
```python
_PROVIDERS = [
    ("MiniMax",     "minimax"),
    ("ZAI",         "zai"),
    ("OpenRouter",  "openrouter"),
]
_PROVIDER_MODELS = {
    "minimax": [("MiniMax-M2.7", "MiniMax-M2.7")],
    "zai": [("GLM-5.1", "glm-5.1"), ("GLM-5V-Turbo (vision)", "glm-5v-turbo")],
    "openrouter": [
        ("Qwen3.7 Max",     "qwen/qwen3.7-max"),
        ("DeepSeek V4 Pro", "deepseek/deepseek-v4-pro"),
        ("CoBuddy (free)",  "baidu/cobuddy:free"),
    ],
}
```

**Replace with:** the dropdown is built from a new method on the view:

```python
def set_provider_options(self, providers: list) -> None:
    """Replace the hardcoded _PROVIDERS with providers from SettingsHandler.
    Each provider's default_model becomes the dropdown's first entry."""
    self._PROVIDERS = [(p.name, p.name) for p in providers]
    self._PROVIDER_MODELS = {p.name: [(p.default_model, p.default_model)] for p in providers if p.default_model}
    # Rebuild the dropdown
    names = Gtk.StringList.new([p[0] for p in self._PROVIDERS] or ["(no providers)"])
    ...
```

**Drop `provider_keys`** from `get_values()` (verified: lines 199-214). After this change:

Before (verified lines 199-214):
```python
provider_keys = dict(self._provider_keys)
if api_key:
    provider_keys[provider] = api_key
...
return {
    ...
    "provider_keys": provider_keys,   # ← remove this line
    ...
}
```

After:
```python
return {
    ...
    # No provider_keys — keys live in providers.yaml
    ...
}
```

Also drop the API Key entry from the form entirely. Per proposal §3.4, the agent edit
dialog should not ask for a key. Provider selection still works because `provider` and
`model` are still written to the agent YAML.

**Remove `_on_provider_changed` and the API key field** (lines 144-148, 345-353). The
section becomes:
- Provider dropdown (populated from `SettingsHandler.list_providers()`)
- Model dropdown (populated from the selected provider's `default_model`)
- No API key field.

**Verified `_update_save_button` location** (lines 762-779). Remove the `has_api_key` clause:

Before (verified lines 765, 779):
```python
has_api_key = bool(self._api_key_entry.get_text().strip())
...
self._save_btn.set_sensitive(has_name and has_api_key and has_prompts and has_tools and has_provider_model)
```

After:
```python
# Per Phase B: no API key entry in the agent edit form — keys live in providers.yaml.
self._save_btn.set_sensitive(has_name and has_prompts and has_tools and has_provider_model)
```

### 2.11 `ui/handlers/agent_builder_handler.py` — REVISED

**What changes:** `save_provider` and `delete_provider` methods (lines 153-160) are no
longer used by the agent edit dialog. They're preserved (not deleted) for the Settings
dialog's use — SettingsHandler uses them. No signature change.

**No code change in this file** other than verifying that `save_provider` is still callable
from `SettingsHandler` (verified line 153: `def save_provider(self, name: str, config: dict) -> bool`).

### 2.12 `ui/window.py` — REVISED

**What changes:**
1. Construct `SettingsHandler` in `_build()` and inject its callbacks.
2. Construct `SettingsDialog` on first click of the toolbar ⚙ button (lazy, like
   `AgentBuilderDialog` at line 687-707).
3. Wire `Toolbar(on_settings_clicked=...)`.
4. On startup, call `toolbar.set_settings_status(has_any_verified_provider)`.

**Verified existing pattern** (lines 687-707 — `_open_agent_builder`):

```python
def _open_agent_builder(self, edit_name: str | None = None) -> None:
    from ui.views.agent_builder import AgentBuilderDialog
    if edit_name is not None:
        agent_def = self._agent_builder_handler.load_for_edit(edit_name)
        if agent_def is None:
            return
    else:
        agent_def = self._agent_builder_handler.create_new()
    self._builder_dialog = AgentBuilderDialog(
        parent=self,
        handler=self._agent_builder_handler,
        agent_def=agent_def,
        on_save=lambda values: self._on_builder_save(values),
        on_cancel=lambda: self._on_builder_cancel(),
    )
    self._builder_dialog.show()
```

**New code (mirror this pattern in `_open_settings`):**

```python
def _open_settings(self) -> None:
    from ui.views.settings_dialog import SettingsDialog
    self._settings_dialog = SettingsDialog(
        parent=self,
        handler=self._settings_handler,
        on_close=lambda: None,
    )
    self._settings_dialog.show()
```

**New constructor in `_build()` (after line 195, after AgentBuilderHandler):**

```python
from ui.handlers.settings_handler import SettingsHandler
self._settings_handler = SettingsHandler(
    GLib_module=GLib,
    parent_window=self,
    on_providers_changed=lambda providers: self._on_providers_changed(providers),
    on_status_changed=lambda verified: self._toolbar.set_settings_status(verified),
)
# Set initial status (red dot if no verified providers)
from utils.providers_store import has_any_verified_provider
self._toolbar.set_settings_status(has_any_verified_provider(load_providers()))
# (need to also import load_providers)
```

**Toolbar wiring (line 108):**

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

**New callback:**

```python
def _on_providers_changed(self, providers: list) -> None:
    """Refresh the agent builder's provider dropdown after Settings edits."""
    if hasattr(self, '_builder_dialog') and self._builder_dialog is not None:
        try:
            self._builder_dialog.set_provider_options(providers)
        except Exception:
            pass  # dialog may be closed
```

### 2.13 `ui/styles.py` — REVISED

**What changes:** add new CSS classes. All additions follow the `add_css_class` rule
(ARCHITECTURE §9).

**New CSS to add (placed in `APP_CSS` near the existing button styles):**

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

/* -- Toolbar status dot -------------------------------------------- */
.toolbar-status-dot {
    color: #ef4444;
    font-size: 14px;
    font-weight: 700;
    margin: -4px -4px 0 0;  /* hug the top-right corner */
    text-shadow: 0 0 4px rgba(0, 0, 0, 0.5);  /* readable on any bg */
}
```

**No change to `apply_styles()`** (line 47 area) — new CSS lives in the same `APP_CSS` string.

### 2.14 `utils/agent_defs.py` — REVISED

**What changes:** `validate_agent_def` no longer requires `api_key`/`provider_keys`. The
check at lines 383-388 becomes:

Before (lines 383-388):
```python
if not agent_def.get("api_key_built_in"):
    provider_keys = agent_def.get("provider_keys", {})
    if provider and not provider_keys.get(provider):
        if not agent_def.get("api_key"):
            errors.append(f"API key required for provider '{provider}'")
```

After:
```python
# Per Phase B: API keys are validated at config time (Test Connection in Settings),
# not at agent-def-save time. The agent YAML stores provider+model only.
```

**`get_available_providers`** (lines 471-487) — change to read from providers.yaml:

Before (lines 471-487): reads `agent.json` via `load_agent_config`.

After: read from `utils.providers_store.load_providers()`.

```python
def get_available_providers() -> list[dict]:
    try:
        from utils.providers_store import load_providers
        return [
            {"name": p.name, "base_url": p.base_url, "default_model": p.default_model}
            for p in load_providers()
        ]
    except Exception as e:
        logger.debug("Cannot load providers.yaml: %s", e)
        return []
```

**Verified existing import block** (lines 1-15): this file imports `os`, `json`, `logging`,
`shutil`, `typing.Any` — no new imports needed.

### 2.15 Tests — NEW

| File | What it covers |
|------|---------------|
| `tests/test_providers_store.py` | Load/save round-trip, missing-file empty list, malformed line skipping, file mode 0o600 enforcement. |
| `tests/test_provider_test.py` | Test Connection: 200 → ok, 401 → fail with body, MiniMax 200 with `base_resp.status_code != 0` → fail, network timeout → fail. Uses `monkeypatch` to stub `urllib.request.urlopen`. |
| `tests/test_settings_handler.py` | add_or_update persists to yaml, remove deletes, test_provider stamps `last_verified_at` on success, test_provider stamps `last_error` on failure, `status_has_verified` returns True/False correctly. |
| `tests/test_settings_dialog.py` | View-only smoke test: opening the dialog with an empty provider list shows the empty state, with one provider shows a card, removing a provider fires `on_providers_changed`. |
| `tests/test_agent_config_yaml_fallback.py` | `agent.config.load_agent_config()` uses providers.yaml when present, falls back to `agent.json` (with warning) when not, writes empty providers.yaml when neither exists. |
| `tests/test_agent_builder_no_provider_keys.py` | `agent_defs.validate_agent_def` no longer requires `api_key`/`provider_keys`. `agent_builder_dialog.get_values()` does not include `provider_keys` in output. |

**All tests use `tmp_config_dir` from `tests/conftest.py:14-23`** (monkeypatches
`HOME` to a temp dir, so providers.yaml lands in an isolated location).

### 2.16 Files NOT changed (verified)

- **`agent/enforcement.py`** — no settings involvement; reads `enforcement` from
  `agent.json` (which we keep).
- **`agent/context.py`** — no settings involvement; builds system prompts.
- **`agent/tools.py`** — no settings involvement; tool definitions only.
- **`gateway/`** — no settings involvement; gateway is separate concern.
- **`ui/views/left_panel.py`** — the existing `+ Agent` row is unchanged; the red dot
  lives on the toolbar, not the left panel.
- **`prompts/default_agents/*.yaml`** — built-in agent definitions are unchanged. They
  reference `provider: minimax` and `model: MiniMax-M2.7`, which is still valid (the
  model string is just the canonical lookup key).

---

## 3. Data Flow

### 3.1 Startup: status dot initial state

```
crabcakes.py starts
  → window.__init__ → window._build()
    → self._settings_handler = SettingsHandler(...)
    → load_providers() → list[ProviderConfig] (from utils.providers_store)
    → has_any_verified_provider(providers) → bool
    → toolbar.set_settings_status(bool) → status_dot.set_visible(not bool)
```

### 3.2 User opens Settings

```
User clicks ⚙ Settings in toolbar
  → toolbar._on_settings_click
    → window._open_settings
      → SettingsDialog(parent, handler, on_close)
        → handler.list_providers() → list[ProviderConfig]
        → Render provider cards
        → dialog.show()
```

### 3.3 User adds a new provider

```
User clicks "+ Add Provider"
  → SettingsDialog: add empty card inline
User fills name, base_url, default_model, api_key
User clicks Save
  → SettingsDialog._on_save(values) → handler.add_or_update(ProviderConfig)
    → handler validates non-empty fields
    → utils.providers_store.add_provider(list, p) → save_providers
    → chmod 0o600 the file
    → handler._on_providers_changed(list) → window._on_providers_changed
      → self._builder_dialog.set_provider_options(list)  [if open]
    → handler._on_status_changed(has_verified)
      → toolbar.set_settings_status(has_verified)
```

### 3.4 User clicks Test Connection

```
User clicks ⚡ Test Connection on a provider card
  → SettingsDialog._on_test_click(provider)
    → handler.test_provider(provider, on_result)
      → threading.Thread(daemon=True) starts
        → utils.provider_test.test_connection(base_url, api_key, model) → TestResult
        → on GLib.idle_add: handler._on_test_result(TestResult)
          → if ok: provider.last_verified_at = utcnow_iso, last_error = None
          → else:   provider.last_error = error
          → save_providers(list)
          → dialog.refresh_status_icon(provider, result)  [inline ✅/❌]
          → handler._on_status_changed(has_verified)
            → toolbar.set_settings_status(has_verified)
```

### 3.5 Special agent resolves its API key at runtime

(Per §2.6 — the runtime now looks at providers.yaml.)

```
AgentRuntime._call_llm(sk, msgs, tools)
  → provider_name = model.split("/")[0]
  → provider_cfg = config.providers.get(provider_name)
    [this dict came from providers.yaml via load_agent_config (§2.4)]
  → effective_api_key = conv.api_key or provider_cfg.api_key
  → if not effective_api_key:
      → load_providers() (from utils.providers_store)
      → find first provider with name == provider_name and api_key set
      → effective_api_key = that
  → caller(base_url, effective_api_key, model, msgs, tools, timeout, x_title)
```

### 3.6 User edits a special agent after Settings change

```
User opens the agent edit dialog (left panel → pencil)
  → AgentBuilderDialog opens
  → set_provider_options(load_providers())  [populated from yaml]
  → user selects provider, model
  → user clicks Save
  → AgentBuilderHandler.save(agent_def)
    → validate_agent_def(agent_def)  [no api_key check anymore]
    → save_agent_def(agent_def)  [writes to agents/<name>.yaml, no provider_keys]
  → reload_agents_and_mcp(on_complete=...)
```

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|------|------------|--------------|------|
| `models/providers.py` | NEW | ~25 | Low (pure data) |
| `utils/providers_store.py` | NEW | ~80 | Low (mirrors feed_store pattern) |
| `utils/provider_test.py` | NEW | ~80 | Med (network IO) |
| `agent/config.py` | REVISED | +30 / -10 | Med (affects startup path) |
| `agent/special_agents.py` | REVISED | 1 line | Low (drop `api_key` resolution) |
| `agent/runtime.py` | REVISED | +8 | Med (per-conversation key resolution) |
| `ui/handlers/settings_handler.py` | NEW | ~120 | Low (mirrors agent_builder_handler) |
| `ui/views/settings_dialog.py` | NEW | ~280 | Med (most GTK widgets in one file) |
| `ui/toolbar.py` | REVISED | +30 | Low (additive) |
| `ui/views/agent_builder.py` | REVISED | -50 / +20 | Med (drops user-visible fields) |
| `ui/window.py` | REVISED | +25 | Med (composition changes) |
| `ui/styles.py` | REVISED | +60 | Low (additive CSS) |
| `utils/agent_defs.py` | REVISED | -10 / +5 | Med (validation change) |
| `tests/test_providers_store.py` | NEW | ~80 | — |
| `tests/test_provider_test.py` | NEW | ~100 | — |
| `tests/test_settings_handler.py` | NEW | ~120 | — |
| `tests/test_settings_dialog.py` | NEW | ~80 | — |
| `tests/test_agent_config_yaml_fallback.py` | NEW | ~60 | — |
| `tests/test_agent_builder_no_provider_keys.py` | NEW | ~60 | — |

**Total:** ~12 new + ~6 revised, ~1200 lines added.

---

## 5. Implementation Order

Numbered so each step leaves the app in a working state and is testable in isolation.

1. **`models/providers.py`** — pure data; no dependencies. Unit tests can target the dataclass.
2. **`utils/providers_store.py`** — depends on (1); can be tested without GTK.
3. **`utils/provider_test.py`** — independent of (2); test with `monkeypatch` on `urllib`.
4. **`agent/config.py`** — wire in (2) for `load_agent_config`. After this step,
   `from agent.config import load_agent_config` returns providers from yaml.
5. **`agent/special_agents.py`** — drop `api_key`/`provider_keys` resolution. Single-line change.
6. **`agent/runtime.py`** — fallback to providers.yaml when `conv.api_key` is empty.
7. **`utils/agent_defs.py`** — drop `api_key`/`provider_keys` validation, change `get_available_providers` source.
8. **`ui/handlers/settings_handler.py`** — depends on (2), (3); no UI yet.
9. **`ui/styles.py`** — add new CSS classes (parallelizable with 10/11).
10. **`ui/views/settings_dialog.py`** — depends on (8), (9); GTK view.
11. **`ui/toolbar.py`** — add ⚙ button + red dot.
12. **`ui/window.py`** — wire (8) and (10) and (11).
13. **`ui/views/agent_builder.py`** — Phase C simplification (drop hardcoded providers + API key).
14. **Tests** — write in parallel with the steps above; final pass after all 13 are done.

**Verification gate at each step:**
- 1-3: `pytest tests/test_providers_store.py tests/test_provider_test.py` passes.
- 4-7: existing `tests/test_agent_defs.py`, `tests/test_special_agents.py`, `tests/test_agent_runtime.py` still pass.
- 8-12: app starts, ⚙ button visible, dialog opens and saves round-trip, Test Connection
  hits a real provider end-to-end.
- 13: existing `tests/test_agent_builder_handler.py` still passes (no `provider_keys` in
  output).

---

## 6. Acceptance Criteria

Each is a testable, observable outcome.

### 6.1 Functional

- [ ] `~/.config/crabcakes/providers.yaml` is created with mode `0o600` after first save.
- [ ] The parent dir is `0o700`.
- [ ] `Settings → ⚙` opens a dialog with one card per provider.
- [ ] Adding a new provider writes a single YAML record and refreshes the agent edit
      dialog's provider dropdown.
- [ ] Removing the last verified provider makes the red dot reappear.
- [ ] A successful Test Connection shows ✅ with latency and clears the red dot.
- [ ] A failed Test Connection shows ❌ with the provider's error message and shows
      the red dot (if no other verified providers exist).
- [ ] MiniMax body-level errors (HTTP 200 with `base_resp.status_code != 0`) cause
      Test Connection to fail with the decoded `status_msg` (not silently succeed).
- [ ] Special agents can be sent a message and successfully authenticate using the
      key from `providers.yaml` (not `agent.json`).
- [ ] `agent.json`'s `providers` section is read as a fallback only when
      `providers.yaml` is missing.
- [ ] The `enforcement`, `default_provider`, `cost_limit`, `step_limit` fields in
      `agent.json` continue to work unchanged.

### 6.2 Negative (regression prevention)

- [ ] No agent YAML file contains `api_key` or `provider_keys` after a save.
- [ ] `validate_agent_def` does NOT reject an agent for missing API key.
- [ ] The agent edit dialog does not show an API key entry.
- [ ] Hardcoded `_PROVIDERS` and `_PROVIDER_MODELS` constants are gone from
      `ui/views/agent_builder.py`.
- [ ] `app_title` continues to flow into the OpenRouter `X-Title` header (regression
      test: `agent_def.app_title = "Coder:Crabcakes"` results in the header being sent).

### 6.3 Non-functional

- [ ] Test Connection completes within 8 seconds (timeout enforced in
      `utils/provider_test.py:18`).
- [ ] Settings dialog opens within 100ms (no network calls on open).
- [ ] File writes are atomic (write to `providers.yaml.tmp`, rename).
- [ ] No import cycle: `utils/providers_store.py` does not import any UI/GTK module;
      `ui/views/settings_dialog.py` does not import any `agent/` or `utils/`-except-store module
      directly (goes through handler).

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| `providers.yaml` is empty (`[]`) | Settings shows the empty state greeting; red dot visible. |
| `providers.yaml` is malformed YAML | `load_providers()` returns `[]`; logs a warning; Settings shows empty state. (Per `utils/agent_defs.py:64-103` precedent — tolerate, don't crash.) |
| `providers.yaml` is read-only | `save_providers` raises `OSError`; Settings dialog shows a save-failed error; providers list is unchanged in memory. |
| User adds a provider with empty API key | `add_or_update` rejects; Settings shows inline error. |
| Test Connection timeout (no network) | `TestResult(ok=False, error="timeout")`; provider's `last_error` set; status dot stays red. |
| Two Test Connections clicked rapidly for the same provider | The second test runs in a parallel thread; whichever finishes last writes the result. The dialog updates with each completion. (No de-dupe — the test is fast enough that this is a non-issue in practice.) |
| User has `agent.json` with providers but no `providers.yaml` | First call to `load_agent_config()` returns those providers with a one-time `logger.warning`. After the user opens Settings and adds a provider, `providers.yaml` is created; `agent.json` providers are no longer used. |
| User edits an agent while Settings is open | The agent dialog's provider list updates via `on_providers_changed` callback; no restart needed. |
| User removes a provider that an active conversation is using | The conversation's `model` is preserved; the next `send_message` raises `ValueError("Provider 'X' is not configured…")` (existing error path in `agent/runtime.py:1018-1024`); the UI shows the existing error bubble. |
| First-run greeting fires | When `providers.yaml` is missing/empty AND the app has never shown the greeting, show a one-time centered welcome in the main chat area. (Stored at `~/.config/crabcakes/.greeting-shown`. Not in scope for V1 — defer to a follow-up spec; V1 shows the red dot + empty state in Settings.) |
| `app_title` regression | The Agent Builder still has an `app_title` field on the agent form (per `SpecialAgentDef` design). Test: opening an agent, setting `app_title`, sending a message — the runtime sends the `X-Title` header. (Existing test path: `agent/runtime.py:131, 178, 192`.) |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the following additions to `docs/ARCHITECTURE.md` are required:

### 8.1 New section 3.X `models/providers.py` — Provider Data

Insert after `models/conversation_snapshot.py` (section 3.25 area). Document:
- `ProviderConfig` dataclass
- Manifest: pure data, no I/O, no network
- Used by: `utils/providers_store.py`, `ui/handlers/settings_handler.py`

### 8.2 New section 3.X `utils/providers_store.py` — Provider Persistence

Insert after `utils/feedback_processor.py` (section 3.30 area). Document:
- Public API: `get_providers_path`, `load_providers`, `save_providers`, `add_provider`,
  `remove_provider`, `update_provider`, `has_any_verified_provider`
- Architecture rules: pure Python, no GTK, no network, chmod 0o600 on save

### 8.3 New section 3.X `utils/provider_test.py` — Test Connection Engine

Insert after `utils/providers_store.py`. Document:
- `TestResult` dataclass + `test_connection()` function
- Architecture rules: pure network, no GTK, no UI imports

### 8.4 New section 3.X `ui/handlers/settings_handler.py` — Settings Logic

Insert after `ui/handlers/agent_builder_handler.py`. Document:
- Public API: `list_providers`, `add_or_update`, `remove`, `test_provider`, `status_has_verified`
- Threading: `test_provider` uses daemon thread + GLib.idle_add

### 8.5 New section 3.X `ui/views/settings_dialog.py` — Settings View

Insert after `ui/views/agent_builder.py`. Document:
- Public API: `__init__`, `show`, `close`, `refresh_providers`
- CSS classes used
- Pure view — no business logic

### 8.6 Update section 3.22 `agent/config.py`

Add note: "Providers section is deprecated in favor of `utils/providers_store.py` /
`providers.yaml`. The `enforcement`, `default_provider`, `cost_limit`, `step_limit` sections
remain in `agent.json`."

### 8.7 Update section 3.21d `agent/special_agents.py`

Add note: "`api_key` field is preserved for backward-compat reading but no longer
written. API keys are resolved at runtime from `providers.yaml` keyed by the model's
`provider/` prefix. `app_title` continues to be an agent-level concern."

### 8.8 Update section 4 (Data Flow)

Add a new flow diagram: "User opens Settings → SettingsDialog → SettingsHandler →
providers_store → yaml file" (mirrors the existing flows in §4.1-4.10).

---

## 9. Risk Register

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Existing `agent.json` users lose their keys on upgrade | Med | Read `agent.json` providers as fallback; log one-time warning. Keys are preserved on disk; user can re-save via Settings. |
| Special agent breaks because `conv.api_key` is None and providers.yaml is empty | Low | Existing `agent/runtime.py:1018-1024` raises `ValueError` with a clear message; `_on_error` renders the error bubble. |
| `urllib.request` blocks the GTK main thread on Test Connection | Med | `settings_handler.test_provider` uses `threading.Thread(daemon=True)` + `GLib.idle_add`. |
| Race: two Save clicks write to providers.yaml concurrently | Low | `save_providers` is fast (YAML is tiny); GIL serializes Python file writes. If concerned, add a `threading.Lock` in `SettingsHandler` for v1.1. |
| New Settings dialog has a focus-grab problem on transient-for | Low | Mirror `agent_builder.py:65-66` pattern. |
| `os.chmod(0o600)` fails on Windows / non-POSIX filesystems | Med | Wrap in try/except, log warning, continue. Doesn't affect functionality. |

---

## 10. Out-of-Scope (Explicit, mirrors proposal §9)

- Per-agent API key overrides
- OAuth / device-code flows
- Encrypted key storage (keychain / libsecret)
- Auto-discovery of running local LLMs
- Migration shim that imports from `agent.json` → `providers.yaml`
- New built-in providers beyond the existing three (minimax, zai, openrouter)
- A first-run greeting card in the chat area (deferred to follow-up)

---

**End of spec.**
