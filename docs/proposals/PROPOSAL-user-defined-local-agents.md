# PROPOSAL: User-Defined Local Agents

**Status:** Draft
**Date:** 2026-05-11
**Author:** Qaster
**Scope:** Agent tab, agent runtime, agent config

---

## What

Replace the two hard-coded local agents (Coder, Debugger) with a user-configurable agent system. Users create, edit, and delete local agents through the CrabCakes UI. Each agent is defined by a config file — name, prompts, tools, and LLM provider settings. No gateway connection required.

---

## Why

### The Problem

Right now, adding a new local agent means editing Python source code (`agent/special_agents.py`). Only developers can do this. Every new agent type increases the hardcoded surface. The system is closed — users can't adapt it to their workflow without touching code.

### The Opportunity

- The **agent runtime** already does direct HTTP API calls to LLM endpoints (OpenAI, MiniMax, Anthropic). No subprocess, no gateway.
- The **provider config** (`agent.json`) already supports multiple providers with base_url, api_key, model, and max_tokens.
- The **prompt library** has 50+ prompts in `prompts/`. The hard part — the prompt content — already exists.
- The **tool system** (`agent/tools.py`) already supports per-agent tool filtering via `allowed_tools` on conversations.
- The **UI pattern** for "create something from a card" already exists in the Projects tab (the `+` Create Project card).

The infrastructure is 80% there. We just need to connect the dots.

### What This Enables

- Spin up a "Security Auditor" or "Documentation Writer" agent in 30 seconds
- Use different LLMs per agent (MiniMax for speed, Claude for reasoning, local Ollama for privacy)
- Works completely offline with a local LLM endpoint
- No gateway dependency — agents are standalone

---

## How

### Design Principles

1. **Config files, not code.** Each agent is a YAML file in `~/.config/crabcakes/agents/`. Easy to version, edit by hand, share between machines.
2. **Surgical changes.** Reuse existing infrastructure — `SpecialAgentDef`, `AgentRuntime`, `AgentRuntimeHandler`, the tool system. New code is glue, not new plumbing.
3. **Follow existing patterns.** The "Create Agent" card mirrors the existing "Create Project" card. Agent editing mirrors prompt editing. Agent listing uses the existing `AgentListHandler` and `LeftPanel` patterns.
4. **No new dependencies.** YAML is in the standard library (or use JSON as fallback). No new packages.

### 1. Agent Definition Files

**Location:** `~/.config/crabcakes/agents/<name>.yaml`

**Format:**
```yaml
name: Coder
emoji: "🛠️"
prompts:
  - system/coder.md
tools:
  - read_file
  - write_file
  - edit_file
  - exec_command
  - list_files
  - search_files
  - web_search
  - web_fetch
provider: minimax
model: MiniMax-M2.7
```

**Fields:**
- `name` (required) — display name shown in the Agents tab
- `emoji` (optional) — icon shown on the agent card (default: `🤖`)
- `prompts` (required) — ordered list of prompt files from `prompts/` directory. Loaded and concatenated as the system prompt when the agent is added to a project. Supports prompt stacking.
- `tools` (required) — list of tool names the agent can use. Validated against `agent/tools.py`'s `get_all_tools()`.
- `provider` (required) — key in the global `agent.json` providers dict. The user's endpoint, API key, and base_url come from there.
- `model` (required) — model string passed to the provider (e.g. `MiniMax-M2.7`, `gpt-4o`, `claude-sonnet-4-20250514`)

**Why YAML:** Human-readable, supports comments, easy to edit by hand. Falls back to JSON for users who prefer it.

**Why provider reference, not inline credentials:** The global `agent.json` already stores API keys securely (chmod 600). Each agent definition just references which provider to use. No credential duplication. Adding a new provider means adding one entry to `agent.json`, then any agent can use it.

### 2. New Utility: `utils/agent_defs.py`

**Responsibility:** Load, validate, save, and list agent definition files from `~/.config/crabcakes/agents/`.

Pure Python — no GTK, no network. Follows the `utils/projects.py` pattern.

**Public API:**
```python
def load_agent_defs() -> list[dict]
    # Scan ~/.config/crabcakes/agents/ for *.yaml files. Parse and validate.
    # Returns list of agent definition dicts. Empty list if dir missing.

def load_agent_def(name: str) -> dict | None
    # Load a single agent definition by name. Returns None if not found.

def save_agent_def(agent_def: dict) -> str
    # Write agent definition to ~/.config/crabcakes/agents/<name>.yaml.
    # Creates directory if needed. Returns file path.

def delete_agent_def(name: str) -> bool
    # Delete an agent definition file. Returns True if deleted.

def validate_agent_def(agent_def: dict) -> list[str]
    # Validate required fields, check prompt files exist, check tool names valid.
    # Returns list of error strings (empty if valid).

def get_available_tools() -> list[dict]
    # Wrap agent/tools.py get_all_tools() → [{name, description}].
    # Used by the UI to show tool checkboxes.

def get_available_prompts() -> list[dict]
    # Scan prompts/ directory for .md files → [{name, filepath}].
    # Used by the UI to show prompt selector.

def get_available_providers() -> list[dict]
    # Load agent.json providers → [{name, base_url, default_model}].
    # Used by the UI to show provider dropdown.
```

**Note:** No circular imports. `utils/agent_defs.py` reads `agent.json` directly (like `agent/config.py` does) and scans `prompts/` directly (like `utils/prompts.py` does). It does NOT import from `agent/` or `ui/`.

### 3. New Handler: `ui/handlers/agent_builder_handler.py`

**Responsibility:** Logic for the Create/Edit Agent flow. Manages the form state, validation, and persistence. Does NOT build widgets.

Follows the handler pattern (Section 8.6 of ARCHITECTURE.md).

**Public API:**
```python
class AgentBuilderHandler:
    def __init__(self, *, on_agent_saved: Callable, on_agent_deleted: Callable)
    def create_new() -> dict
        # Return a blank agent definition template for the form.
    def load_for_edit(name: str) -> dict | None
        # Load existing agent def for editing.
    def save(agent_def: dict) -> tuple[bool, list[str]]
        # Validate + save. Returns (success, errors).
    def delete(name: str) -> bool
        # Delete agent definition file.
    def get_tool_options() -> list[dict]
        # Available tools with descriptions.
    def get_prompt_options() -> list[dict]
        # Available prompts from prompts/ directory.
    def get_provider_options() -> list[dict]
        # Available providers from agent.json.
```

**Rules:**
- No imports from other handlers.
- No GTK widget creation.
- Dependencies (agent_defs utilities) called directly.
- Callbacks `on_agent_saved` and `on_agent_deleted` wired by `window.py`.

### 4. New View: `ui/views/agent_builder.py`

**Responsibility:** GTK4 dialog/form for creating and editing agents. Pure view — receives data from `AgentBuilderHandler`, emits user actions back through callbacks.

**Layout:** A dialog window with the following fields:

| Field | Widget | Source |
|-------|--------|--------|
| Name | `Gtk.Entry` | Free text |
| Emoji | `Gtk.Entry` | Single emoji |
| Prompts | Multi-select `Gtk.ListBox` with checkboxes | From `prompts/` directory |
| Tools | Checkboxes in a scrollable list | From `agent/tools.py` |
| Provider | `Gtk.DropDown` | From `agent.json` providers |
| Model | `Gtk.Entry` | Free text (pre-filled from provider default) |

**Tool presets** at the top of the tools section:
- "Full Access" — selects all 8 tools
- "Read Only" — selects read_file, list_files, search_files, web_search, web_fetch
- "Custom" — manual selection

**Public API:**
```python
class AgentBuilderDialog:
    def __init__(self, parent, *, agent_def=None, on_save=None, on_cancel=None)
        # If agent_def is provided, pre-fill form for editing.
        # If None, show empty form for creating.
    def get_values() -> dict
        # Extract current form values into an agent_def dict.
    def show() -> None
    def close() -> None
```

### 5. Modify: `agent/special_agents.py`

**Current:** Hard-coded `SPECIAL_AGENTS` dict with Coder and Debugger.

**Change:** Load agent definitions from `~/.config/crabcakes/agents/` at startup. Merge with built-in defaults (Coder and Debugger become default YAML files shipped with CrabCakes, not hardcoded Python).

**Surgical change:**
- `get_special_agents()` → calls `utils/agent_defs.load_agent_defs()`, converts each dict to `SpecialAgentDef`
- `get_special_agent()` → same lookup, now from loaded defs
- Built-in defaults: if `~/.config/crabcakes/agents/` is empty or missing, copy default agent YAML files from `prompts/default_agents/` (Coder and Debugger)
- `SpecialAgentDef` dataclass gets two new optional fields: `provider` and `model` (defaulting to global config values)

**Backward compatibility:** If no agent definition files exist, the system creates Coder and Debugger defaults on first launch. Existing behavior preserved.

### 6. Modify: `agent/runtime.py` — `_get_runtime()`

**Current:** `AgentRuntimeHandler._get_runtime()` loads global config and creates one runtime per agent name.

**Change:** Pass the agent definition's `provider` and `model` fields through to `AgentRuntime`, which uses them to select the correct provider from `agent.json` and the correct model string for API calls.

**Surgical change:**
- `AgentRuntimeHandler._get_runtime(name)` → `_get_runtime(name, provider=None, model=None)`
- When creating a conversation, use the agent-specific provider/model instead of global defaults
- The `create_conversation()` method already accepts a `model` parameter — wire it through

### 7. Modify: `ui/views/left_panel.py` — Agents Tab

**Current:** Agents tab shows gateway agents + hard-coded special agents. No "create" affordance.

**Change:** Add a `+` "Create Agent" card at the top of the agents list (before any agent rows). Follows the exact pattern of the "Create Project" card in the Projects tab.

**Surgical change:**
- Add `_build_create_agent_row()` — mirrors `_build_new_prompt_row()` pattern
- Append it as the first row in `_refresh_agents_list()`
- On activation: fire `on_create_agent` callback → `window.py` opens `AgentBuilderDialog`
- Add "Edit" and "Delete" options to agent card right-click context menu (only for local agents, not gateway agents)

### 8. Modify: `ui/window.py` — Wiring

**Current:** Creates `AgentRuntimeHandler`, registers hard-coded special agents, passes them to left panel.

**Change:**
- Create `AgentBuilderHandler`
- Wire `on_create_agent` callback from `LeftPanel` → open `AgentBuilderDialog`
- Wire `on_agent_saved` → reload agent definitions, refresh left panel, register new agent with `AgentRuntimeHandler`
- Wire `on_agent_deleted` → unregister agent, refresh left panel

### 9. Provider Management in Agent Builder

**Problem:** Users need to add API providers (endpoints + keys) before they can assign them to agents.

**Solution:** The agent builder form includes a small "Add Provider" button next to the provider dropdown. Clicking it opens a mini-form:
- Provider name (e.g. "openai", "minimax", "local-ollama")
- Base URL (e.g. `https://api.openai.com/v1`, `http://localhost:11434/v1`)
- API Key (password field)
- Default Model (e.g. `gpt-4o`, `llama3`)

This writes directly to `agent.json`'s providers dict. No new config file needed — uses the existing `agent.json` infrastructure.

**Implementation:** Add `save_provider(name, config)` and `delete_provider(name)` to `utils/agent_defs.py`. These are thin wrappers over `agent.json` I/O.

---

## File Changes Summary

| Action | File | What |
|--------|------|------|
| **New** | `utils/agent_defs.py` | Agent definition load/save/validate/list |
| **New** | `ui/handlers/agent_builder_handler.py` | Create/edit agent form logic |
| **New** | `ui/views/agent_builder.py` | GTK4 agent builder dialog |
| **New** | `prompts/default_agents/coder.yaml` | Default Coder agent definition |
| **New** | `prompts/default_agents/debugger.yaml` | Default Debugger agent definition |
| **Modify** | `agent/special_agents.py` | Load from YAML instead of hard-coded dict |
| **Modify** | `agent/runtime.py` | Accept per-agent provider/model in `_get_runtime()` |
| **Modify** | `ui/views/left_panel.py` | Add "Create Agent" card + edit/delete context menu |
| **Modify** | `ui/window.py` | Wire agent builder handler + callbacks |
| **Update** | `docs/ARCHITECTURE.md` | New modules, updated file inventory |

---

## What We Do NOT Touch

- `agent/tools.py` — tool system unchanged, just referenced
- `agent/config.py` — `agent.json` format unchanged, just read by new utility
- `agent/context.py` — prompt loading unchanged, just given a list of prompt paths
- `agent/enforcement.py` — enforcement layer unchanged
- `gateway/` — no changes, local agents don't use the gateway
- `models/` — no new models needed; `SpecialAgentDef` gets two optional fields
- Existing agent cards, chat routing, project membership — all work as-is

---

## Build Order

1. `utils/agent_defs.py` — agent definition I/O + validation (testable in isolation)
2. `prompts/default_agents/` — default Coder and Debugger YAML files
3. `agent/special_agents.py` — load from YAML instead of hard-coded dict (backward compatible)
4. `agent/runtime.py` — per-agent provider/model support
5. `ui/handlers/agent_builder_handler.py` — form logic handler
6. `ui/views/agent_builder.py` — GTK4 dialog
7. `ui/views/left_panel.py` — "Create Agent" card + edit/delete context menu
8. `ui/window.py` — wire everything together
9. `docs/ARCHITECTURE.md` — update documentation
10. Tests for each new module

Each step is independently verifiable. Steps 1-4 are backend (no UI). Steps 5-8 are UI (no backend changes). Step 9 is documentation.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| YAML parsing fails on malformed files | Validate on load, skip invalid defs, log warning. App still works with valid defs. |
| User deletes all agents | System falls back to built-in defaults on next launch. Never a "no agents" state. |
| User enters invalid provider name | Validate against `agent.json` providers. Show error in form. |
| User enters invalid model string | No validation possible (models change). Pass through to API — error surface is the API response. |
| API key stored in `agent.json` is readable | Already handled: `load_agent_config()` warns on chmod > 600. Same protection applies. |
| Agent definition references a deleted prompt file | `validate_agent_def()` checks prompt files exist. Show error on load/edit. |

---

## Future Enhancements (Out of Scope)

These are explicitly NOT part of this proposal but are enabled by it:

- **Per-project agents** — agent definitions scoped to a project instead of global
- **Prompt stacking UI** — drag-and-drop reordering of prompts in the builder
- **Agent import/export** — share agent definitions between machines
- **Smart model routing** — auto-select model based on task type
- **Agent marketplace** — browse and install community agent definitions from ClawHub
