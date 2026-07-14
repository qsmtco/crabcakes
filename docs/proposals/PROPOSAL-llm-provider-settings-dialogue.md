# PROPOSAL: LLM Provider Settings Dialogue

**Date:** 2026-06-07
**Author:** QTR
**Status:** ✅ DONE — spec written (`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md`, 52K) and implementation shipped. Key files: `ui/views/settings_dialog.py` (17K), `ui/wiring.py` (3.6K), `utils/providers_store.py`. Providers load from `~/.config/crabcakes/providers.yaml`.
**Related:** SPEC-LOCAL-AGENT-NO-RESPONSE-FIX (Phases 1–4), `docs/ARCHITECTURE.md`

> **Status (verified 2026-06-12):** ✅ **DONE** — 
> **status:** `DONE` — sortable tag for `ls | grep STATUS` Spec written (`docs/specs/SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md`, 52K, 2026-06-07) and implementation shipped. Key files: `ui/views/settings_dialog.py` (17K), `ui/wiring.py` (3.6K — the wiring helpers for SettingsHandler ↔ Toolbar ↔ SettingsDialog), `utils/providers_store.py` (canonical provider storage). `_PROVIDERS` / `_PROVIDER_MODELS` hardcoded dicts in `agent_builder.py` were removed — providers now load from `~/.config/crabcakes/providers.yaml` (per `agent/runtime.py:1353-1359` "providers.yaml is the canonical store for API keys"). The two-layer key confusion was resolved by the spec's app-level provider config model.

---

## 0. Problem Statement

CrabCakes local agents (Coder, Debugger, Crabcakes, and user-defined agents) need LLM provider credentials to function. Today, these credentials are stored in `~/.config/crabcakes/agent.json` — a JSON file whose name implies it is agent-level configuration, when in fact it is **application-level infrastructure** (provider endpoints, API keys, model catalogs).

The current setup has these concrete failures:

1. **Hardcoded dropdowns.** The agent edit dialogue (`ui/views/agent_builder.py` lines 310–330) hardcodes `_PROVIDERS` and `_PROVIDER_MODELS` as Python dicts. Adding a new provider or model requires editing source code and restarting the app. New models added to the config file never appear in the dropdown.

2. **No validation at configuration time.** Users can enter an incorrect `base_url` or API key and receive no feedback until they send a message to an agent — at which point they get a cryptic error or (pre-Phase-2 fix) complete silence. The user discovered `api.minimax.chat` vs `api.minimax.io` only after manual terminal investigation.

3. **Two-layer key confusion.** Agent YAML files can specify `provider_keys` (per-agent API key overrides), while `agent.json` also stores provider-level keys. This creates ambiguity about which key is actually used, and the per-agent override makes it easy to paste the wrong key for the wrong provider (as happened with the OpenRouter key on the MiniMax provider slot).

4. **Naming confusion.** `agent.json` contains LLM provider credentials, not agent definitions. Agent definitions live in `~/.config/crabcakes/agents/*.yaml`. The name `agent.json` misleads both users and developers about its purpose.

---

## 1. Proposal Overview

Introduce a dedicated **Settings dialogue** accessible from the main toolbar that provides a single, validated, app-level configuration surface for LLM providers, models, and API keys.

Key principles:

- **Single source of truth.** All provider credentials (base_url, API key, model list) live in one YAML file. No per-agent key overrides. No hardcoded Python lists.
- **Validate before you save.** A "Test Connection" button on every provider entry lets users verify their configuration immediately, without sending a message to an agent.
- **Separation of concerns.** Provider infrastructure (Settings dialogue) is separate from agent definition (agent edit dialogue). The agent edit dialogue keeps a **model dropdown only** — populated dynamically from whatever models the Settings dialogue has configured.
- **Architecture compliance.** Follows existing patterns: modal dialog (`AgentBuilderDialog` pattern), handler/view split, `utils/` for pure I/O, `agent/config.py` for runtime config loading, `ui/toolbar.py` for toolbar integration, composition root in `window.py`.

---

## 2. File Storage

### 2.1 New config file: `~/.config/crabcakes/providers.yaml`

Replaces `~/.config/crabcakes/agent.json` for provider credentials. YAML format (human-readable, supports comments, matches the `.yaml` convention already used for agent definitions).

**Example structure:**

```yaml
# CrabCakes LLM Provider Configuration
# This file stores API keys — chmod 600 recommended.

providers:
  minimax:
    base_url: https://api.minimax.io/v1
    api_key: sk-cp-your-key-here
    models:
      - id: MiniMax-M2.7
        name: MiniMax M2.7
        context_window: 1048576
        max_tokens: 262144
      - id: MiniMax-M3
        name: MiniMax M3
        context_window: 1048576
        max_tokens: 262144

  openrouter:
    base_url: https://openrouter.ai/api/v1
    api_key: sk-or-your-key-here
    models:
      - id: moonshotai/kimi-k2.6:free
        name: Kimi K2.6 Free
        context_window: 128000
        max_tokens: 32768
      - id: openrouter/owl-alpha
        name: Owl Alpha
        context_window: 1048576
        max_tokens: 262144

  zai:
    base_url: https://api.z.ai/api/coding/paas/v4
    api_key: your-zai-key-here
    models:
      - id: glm-5.1
        name: GLM 5.1
        context_window: 200000
        max_tokens: 131072

# Which provider/model to use when an agent doesn't specify one
default_model: minimax/MiniMax-M2.7

# Runtime limits
max_tool_iterations: 50
tool_timeout_seconds: 120
cost_limit: 5.0
step_limit: 100
```

**Key design decisions:**

- Each provider has its own `models` list. The runtime resolves a model ID to a provider by scanning all providers' model lists.
- Model IDs are stored **without** the provider prefix (e.g. `MiniMax-M2.7`, not `minimax/MiniMax-M2.7`). The prefix is implied by which provider section the model is under. The agent YAML stores the fully-qualified form `minimax/MiniMax-M2.7`; the runtime strips the prefix to find the provider.
- `default_model` uses the fully-qualified `provider/model_id` form for consistency with agent YAMLs.
- File permissions: `chmod 600` (contains API keys in plaintext). Same security model as current `agent.json`.

### 2.2 Migration from `agent.json`

On first load, if `providers.yaml` does not exist but `agent.json` does, the app migrates the data:

1. Read `agent.json` providers
2. Write `providers.yaml` with the migrated data
3. Rename `agent.json` to `agent.json.deprecated`
4. Log a one-time info message about the migration

The runtime (`agent/config.py`) is updated to read from `providers.yaml` instead of `agent.json`. The `load_agent_config()` function becomes `load_provider_config()` (or adapts internally).

### 2.3 Agent YAML changes

The `provider_keys` field is **removed** from agent YAMLs. Agents reference a model by its fully-qualified ID (e.g. `minimax/MiniMax-M2.7`). The runtime resolves the provider from the prefix and uses the provider's API key from `providers.yaml`.

**`app_title` stays per-agent.** The OpenRouter X-Title header (e.g., `"Coder:Crabcakes"`) is an agent-level concern (which LLM is acting as which agent), not a model-level concern. It remains in the agent YAML and is passed to the runtime by `agent_builder.py`. It is not migrated to `providers.yaml`.

Agent YAML before:
```yaml
provider: minimax
model: minimax/MiniMax-M2.7
provider_keys:
  minimax: sk-cp-some-key
app_title: Coder:Crabcakes
```

Agent YAML after:
```yaml
model: minimax/MiniMax-M2.7
app_title: Coder:Crabcakes
```

No `provider` field needed — the provider is implied by the model prefix. No `provider_keys` — keys live in `providers.yaml`. `app_title` unchanged.

---

## 3. UI Design

### 3.1 Toolbar Integration

Add a **Settings** button (gear icon ⚙️) to the main toolbar (`ui/toolbar.py`), positioned in the right-aligned box between the status label and the Connect button.

```
[Stream: OFF]          [● Connected] [⚙ Settings] [Connect]
```

The button opens the Settings dialogue as a modal window. Callback wired through `window.py` (composition root) following the same pattern as the agent builder.

### 3.1.1 Settings Discoverability (Killer Feature)

**This is the most important UX section in the proposal.** Today's debugging session revealed the failure mode: a user configured the agent edit dialog, sent a message, and got a cryptic MiniMax error. They had no in-app path to discover the Settings dialog, and the runtime surfaced the error as a `[Error] ...` bubble far from where the configuration actually lives. The user shouldn't have to debug the runtime to find the config.

The Settings dialog must be **discoverable from four different surfaces** so a user always finds it:

**Surface 1 — Toolbar button (always visible).** The ⚙️ button on the main toolbar is the primary entry point. When the user opens the app for the first time, the button is visible. No hidden menu, no obscure keybinding.

**Surface 2 — Status indicator on the Settings button (the killer feature).** The ⚙️ button displays a small red dot (●) in its corner when **any** provider in `providers.yaml` has an unconfigured or invalid state. This includes:
- A provider with an empty `api_key`
- A provider with no `models` defined
- A provider whose last "Test Connection" failed
- A provider that has never been "Test Connection"-ed (untested = unverified)

The red dot disappears when the user opens the Settings dialog, fixes the issue, and either (a) saves with all fields filled, or (b) clicks "Test Connection" and gets a ✅. The dot is the visual signal that the configuration needs attention — it does not require the user to read logs or run a test message.

**Surface 3 — Agent edit dialog inline link.** When the user opens the agent edit dialog for an agent whose model references a provider that has a red-dot status, the dialog displays an inline warning at the top of the form:

> ⚠ The provider for this model (`minimax`) has not been configured or its credentials failed validation. [Open Settings →]

The link opens the Settings dialog with the relevant provider card pre-expanded and focused. This catches the case where the user is editing an agent and discovers the provider is misconfigured.

**Surface 4 — First-run hint.** On the very first launch of the app (or first launch after this feature lands), if `providers.yaml` doesn't exist, a one-time modal greeting explains:

> Welcome to CrabCakes. Before you can chat with agents, configure at least one LLM provider in Settings. [Open Settings →]

The hint fires once per user, not once per session.

**Why four surfaces and not one:** Users arrive at the configuration from different mental models. The toolbar button is for users who already know what they're looking for. The status indicator is for users who don't know something is wrong. The inline link is for users editing an agent. The first-run hint is for users who haven't configured anything yet. All four must exist. Missing any one of them reproduces today's debugging session for that user type.

### 3.2 Settings Dialogue (`ui/views/settings_dialog.py`)

A modal dialog following the existing `AgentBuilderDialog` pattern:

```
┌─────────────────────────────────────────────────────────┐
│  LLM Provider Settings                              [×] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─── Provider: MiniMax ────────────────────────────┐  │
│  │                                                   │  │
│  │  Base URL:  [https://api.minimax.io/v1        ]  │  │
│  │  API Key:   [••••••••••••••••••••••  ] [👁] [🔍]│  │
│  │                                                   │  │
│  │  Models:                                          │  │
│  │  ┌──────────────────────────────────────────┐    │  │
│  │  │ MiniMax-M2.7     [context: 1M]  [−]     │    │  │
│  │  │ MiniMax-M3       [context: 1M]  [−]     │    │  │
│  │  └──────────────────────────────────────────┘    │  │
│  │  [+ Add Model]                                    │  │
│  │                                                   │  │
│  │  [⚡ Test Connection]    Status: ✅ Connected     │  │
│  │                                                   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌─── Provider: OpenRouter ─────────────────────────┐  │
│  │  ...                                              │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  [+ Add Provider]                                       │
│                                                         │
│  ─── Defaults ─────────────────────────────────────     │
│  Default Model:  [minimax/MiniMax-M2.7    ▾]           │
│                                                         │
│                          [Cancel] [Save]                │
└─────────────────────────────────────────────────────────┘
```

**Components:**

- **Provider cards** — one expandable/collapsible card per provider. Each card contains:
  - **Provider name** — editable text field (used as the provider ID, lowercased)
  - **Base URL** — text field for the API endpoint
  - **API Key** — password-style text field with a reveal toggle (👁) and a **Test Connection** button (🔍)
  - **Model list** — scrollable list of models, each with ID and context window. `[−]` removes, `[+ Add Model]` adds a new entry
  - **Test Connection** button — sends a 1-token completion request to the configured endpoint using the configured key and the first model in the list. Displays inline result: ✅ connected (with latency) or ❌ error (with error message from the provider). This is the critical validation feature.

- **Add Provider** button — creates a new provider card with empty fields
- **Default Model dropdown** — lists all models from all providers in fully-qualified form (`provider/model-id`). Populated dynamically from the provider cards.
- **Save/Cancel** buttons — Save writes to `providers.yaml`. Cancel discards changes.

### 3.3 Test Connection Implementation

The Test Connection button calls a new utility function in `utils/`:

```python
def test_provider_connection(base_url: str, api_key: str, model_id: str) -> TestResult:
    """Send a 1-token completion request and return success/failure."""
```

This function:
1. Sends `POST <base_url>/chat/completions` (or the provider-specific path) with `{"model": model_id, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}`
2. Returns a `TestResult` dataclass with: `success: bool`, `latency_ms: int`, `error_message: str | None`
3. Handles MiniMax body-level errors (checks `base_resp.status_code`)
4. Handles HTTP errors (4xx, 5xx)
5. Handles network errors (timeout, DNS failure, connection refused)
6. Runs on a background thread, dispatches result to GLib main thread (same pattern as gateway connect)

### 3.4 Agent Edit Dialogue Changes

The existing `AgentBuilderDialog` (`ui/views/agent_builder.py`) is simplified:

- **Remove:** `_PROVIDERS` hardcoded list (line 310–314)
- **Remove:** `_PROVIDER_MODELS` hardcoded dict (line 316–330)
- **Remove:** `_build_provider_dropdown()` method
- **Remove:** `_on_provider_changed()` handler
- **Remove:** API key field from the agent edit form
- **Remove:** `provider_keys` from the save/load logic
- **Keep:** Model dropdown, but now populated dynamically by reading all models from `providers.yaml` via `load_provider_config()`. The dropdown shows fully-qualified model IDs: `minimax/MiniMax-M2.7`, `zai/glm-5.1`, `openrouter/moonshotai/kimi-k2.6:free`, etc.
- **Keep:** All other agent fields (name, emoji, role, prompts, tools, MCP servers) unchanged

Agent YAML output changes:
```yaml
# Before (current)
provider: minimax
model: minimax/MiniMax-M2.7
provider_keys:
  minimax: sk-cp-...

# After (proposed)
model: minimax/MiniMax-M2.7
```

---

## 4. Architecture Compliance

All changes follow the patterns defined in `docs/ARCHITECTURE.md`:

### 4.1 New files

| File | Type | Responsibility |
|------|------|---------------|
| `utils/provider_config.py` | Pure Python (no GTK) | Load/save `providers.yaml`, `test_provider_connection()`, `TestResult` dataclass |
| `ui/views/settings_dialog.py` | GTK4 view | Modal dialog widget — Settings UI |
| `ui/handlers/settings_handler.py` | Handler | Settings dialog logic — save, load, test, validation |

### 4.2 Modified files

| File | Change |
|------|--------|
| `agent/config.py` | `load_agent_config()` reads `providers.yaml` instead of `agent.json`. `LLMProviderConfig` gains `models` field. |
| `agent/runtime.py` | `_call_llm()` resolves provider from model prefix → looks up in loaded config. No more `provider_keys` from agent YAML. |
| `agent/special_agents.py` | Remove `api_key` from `SpecialAgentDef`. Remove `provider_keys` from agent YAML loading. |
| `ui/toolbar.py` | Add Settings button (gear icon) to right-aligned box |
| `ui/views/agent_builder.py` | Remove hardcoded `_PROVIDERS`/`_PROVIDER_MODELS`. Replace with dynamic model dropdown from `providers.yaml`. Remove API key field. |
| `ui/handlers/agent_builder_handler.py` | Remove `get_provider_options()`, `save_provider()`, `delete_provider()`. Model options come from `provider_config.py`. |
| `ui/window.py` | Wire Settings button → create `SettingsHandler` → open `SettingsDialog`. Follow existing composition-root pattern. |
| `utils/agent_defs.py` | Remove `save_provider()`, `delete_provider()`. Agent YAML save/load drops `provider_keys`. |

### 4.3 Dependency graph (obeys ARCHITECTURE.md layer rules)

```
gateway/           (no changes)
models/            (no changes — no provider config models needed)
utils/
  provider_config.py  ← NEW: pure Python, no GTK, no network
                       (test_provider_connection uses urllib, which is fine —
                        utils/ can do file I/O and pure computation)
agent/
  config.py           ← MODIFIED: reads providers.yaml
  runtime.py          ← MODIFIED: uses provider config for LLM calls
  special_agents.py   ← MODIFIED: removes per-agent keys
ui/
  toolbar.py          ← MODIFIED: adds Settings button
  handlers/
    settings_handler.py  ← NEW: dialog logic
    agent_builder_handler.py ← MODIFIED: simplified
  views/
    settings_dialog.py    ← NEW: GTK4 modal dialog
    agent_builder.py      ← MODIFIED: simplified model dropdown
```

`gateway/` and `models/` are untouched. `utils/provider_config.py` has no GTK dependencies. Handler/view split maintained. Composition root in `window.py` wires everything.

---

## 5. Data Flow

### 5.1 Provider configuration flow

```
User clicks ⚙ Settings
  → window.py dispatches to SettingsHandler.open()
  → SettingsHandler loads providers.yaml via provider_config.load()
  → SettingsDialog displays provider cards
  → User edits/adds/removes providers and models
  → User clicks "Test Connection"
    → SettingsHandler.test_connection(provider)
    → Spawns background thread → provider_config.test_provider_connection()
    → Returns TestResult to GLib main thread
    → Dialog shows ✅ or ❌ inline
  → User clicks "Save"
    → SettingsHandler.save() → provider_config.save() → writes providers.yaml
    → Dialog closes
```

### 5.2 Runtime LLM call flow (after change)

```
AgentRuntime._call_llm(session_key, messages, tools)
  → model = conv.model  (e.g. "minimax/MiniMax-M2.7")
  → provider_name = model.split("/")[0]  (e.g. "minimax")
  → model_id = model.split("/")[1]  (e.g. "MiniMax-M2.7")
  → config = load_provider_config()  ← reads providers.yaml
  → provider_cfg = config.providers[provider_name]
  → base_url = provider_cfg.base_url  (e.g. "https://api.minimax.io/v1")
  → api_key = provider_cfg.api_key    (from providers.yaml, NOT agent YAML)
  → calls _call_llm_streaming(base_url, api_key, model_id, ...)
```

### 5.3 Agent edit dialogue flow (after change)

```
User opens agent edit dialogue for "Coder"
  → AgentBuilderDialog loads current agent YAML
  → Model dropdown populated from provider_config.load().all_models()
    → Returns ["minimax/MiniMax-M2.7", "minimax/MiniMax-M3", "zai/glm-5.1", ...]
  → User selects "minimax/MiniMax-M2.7"
  → Saves → writes to agents/coder.yaml:
      model: minimax/MiniMax-M2.7
    (no provider field, no provider_keys)
```

---

## 6. Test Connection Details

The `test_provider_connection()` function must handle provider-specific quirks:

| Provider | Endpoint path | Auth header | Body-level error check |
|----------|--------------|-------------|----------------------|
| MiniMax | `<base_url>/text/chatcompletion_v2` | `Authorization: Bearer <key>` | Check `base_resp.status_code != 0` |
| OpenRouter | `<base_url>/chat/completions` | `Authorization: Bearer <key>` | Standard HTTP errors |
| ZAI | `<base_url>/chat/completions` | `Authorization: Bearer <key>` | Standard HTTP errors |
| OpenAI | `<base_url>/chat/completions` | `Authorization: Bearer <key>` | Standard HTTP errors |
| Generic | `<base_url>/chat/completions` | `Authorization: Bearer <key>` | Standard HTTP errors |

The MiniMax body-level error check is the same fix from Phase 2 of SPEC-LOCAL-AGENT-NO-RESPONSE-FIX. The test function reuses that knowledge: after receiving HTTP 200, parse the JSON body and check for `base_resp.status_code != 0` before declaring success.

Request payload for testing:
```json
{
  "model": "<first-model-from-provider>",
  "messages": [{"role": "user", "content": "ping"}],
  "max_tokens": 1
}
```

---

## 7. Migration Plan

### Phase A: Create new infrastructure (no migration logic)

The new way replaces the old way. No data migration. No fallback to `agent.json`. If `providers.yaml` doesn't exist, it's empty; the user configures their providers fresh in the Settings dialog.

1. Create `utils/provider_config.py` with load/save/test functions
2. Create `ui/views/settings_dialog.py` and `ui/handlers/settings_handler.py`
3. Add Settings button to `ui/toolbar.py` with status-indicator dot (per §3.1.1)
4. Add inline-link warning in `ui/views/agent_builder.py` for misconfigured providers
5. Add first-run greeting in `ui/window.py` for users with no `providers.yaml`
6. Wire in `ui/window.py` (composition root)
7. Test: Settings dialogue opens, saves to `providers.yaml`, Test Connection works, status dot updates correctly

### Phase B: Switch runtime to new config (hard cutover)

The new way is the only way. The old `agent.json` is deleted, not migrated.

1. Update `agent/config.py` to read `providers.yaml` only. Delete the `agent.json` loader.
2. Update `agent/runtime.py` `_call_llm()` to use new config
3. Update `agent/special_agents.py` to remove `api_key` from `SpecialAgentDef` (keep `app_title` as a per-agent field)
4. Delete the file `~/.config/crabcakes/agent.json` on the user's machine (one-time cleanup, no data preserved — the user will re-enter keys in the new Settings dialog)
5. Test: agents still work end-to-end with the new `providers.yaml`-only config

### Phase C: Simplify agent edit dialogue

1. Remove hardcoded `_PROVIDERS`/`_PROVIDER_MODELS` from `agent_builder.py`
2. Replace with dynamic model dropdown from `provider_config.py`
3. Remove API key field and `provider_keys` from agent YAML handling
4. Remove `provider` field from agent YAML (model prefix implies provider)
5. **Keep `app_title` in the agent YAML** (per §2.3) and the corresponding form field in the agent edit dialog
6. Test: agent edit dialogue shows all models from `providers.yaml`, saves correct YAML, `app_title` preserved

---

## 8. Out of Scope

- **Agent-specific API key overrides.** All agents sharing a provider use the same key. If per-agent keys are needed in the future, it would be a separate feature.
- **OAuth flows.** The Settings dialogue handles API key entry only. OAuth (like MiniMax's Coding Plan OAuth) stays in OpenClaw's domain. Users paste the resulting access token as an API key.
- **Provider-specific UI.** No special forms per provider. All providers use the same generic fields (base_url, api_key, models).
- **Encrypted key storage.** Keys stored in plaintext in `providers.yaml` with `chmod 600`. Same security model as current `agent.json`. Keyring integration would be a separate proposal.
- **Auto-discovery of available models.** The model list is manually configured by the user via the Settings dialog when a new model ships from a provider. Auto-fetching from provider APIs would be a separate feature.
- **Per-agent API key overrides.** All agents sharing a provider use the same key from `providers.yaml`. If per-agent keys are needed in the future, it would be a separate feature.
- **Migration from `agent.json`.** The new config file `providers.yaml` is the only source of truth. There is no migration path from the old `agent.json` — users configure providers fresh in the new Settings dialog. The old file is deleted as part of Phase B.
- **`app_title` in `providers.yaml`.** Per-agent OpenRouter attribution headers remain in the agent YAML, not in the global provider config. `app_title` is an agent-level concern, not a model-level concern.

---

## 9. Acceptance Criteria

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | Settings button appears on toolbar | Visual: gear icon between status label and Connect button |
| 2 | Settings dialogue opens as modal | Click gear → dialog appears, main window blocked |
| 3 | Provider cards load from `providers.yaml` | Pre-populate file → open Settings → see providers |
| 4 | Add new provider via Settings | Click Add Provider → fill fields → Save → reload → provider persists |
| 5 | Remove provider via Settings | Click − on provider → Save → provider gone from file |
| 6 | Test Connection succeeds for valid config | Configure MiniMax with correct key → Test → ✅ shown |
| 7 | Test Connection fails for invalid config | Wrong key → Test → ❌ with error message |
| 8 | Test Connection catches MiniMax body-level errors | MiniMax key on wrong endpoint → Test → ❌ (not silent ✅) |
| 9 | Agent edit dialogue model dropdown populated from `providers.yaml` | Open agent edit → model dropdown shows all models from file |
| 10 | Agent YAML saves without `provider_keys` or `provider` field | Edit agent → save → YAML has only `model: provider/model-id` |
| 11 | Agent sends message using provider from `providers.yaml` | Send to Coder → uses key from `providers.yaml` → gets response |
| 12 | **`app_title` stays per-agent in agent YAML** | Edit agent → save → YAML still has `app_title: Coder:Crabcakes` |
| 13 | **Status indicator (red dot) on Settings button** | Configure a provider with empty key → open app → red dot visible on ⚙️ button |
| 14 | **Status dot disappears after valid Test Connection** | Click Test Connection with valid key → ✅ → red dot disappears |
| 15 | **Inline warning in agent edit dialog** | Open agent edit for an agent whose provider has no key → see "provider not configured" warning with link to Settings |
| 16 | **First-run greeting** | Delete `providers.yaml` → open app → one-time greeting modal appears with "Open Settings" button |
| 17 | **User-driven model addition** | New provider ships a new model → user opens Settings → clicks Add Model → enters ID → save → model appears in agent edit dropdown |
| 18 | No regressions in existing agent functionality | Full test suite passes |

---

**End of proposal.**
