---
status: DONE
---
# SPEC: Crabcakes — Always-On Help Agent

**Date:** 2026-05-30
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-crabcakes-always-on-help-agent.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md): All new files follow existing patterns. `prompts/default_agents/crabcakes.yaml` mirrors `coder.yaml`. `prompts/system/crabcakes.md` follows the system prompt template pattern. Built-in provider injected in `agent/config.py` alongside user providers. `auto_open` and `auto_add_to_projects` fields added to `SpecialAgentDef` with backward-compatible defaults. Auto-open wiring in `window.py` uses existing `create_chat_tab()`. Auto-add to projects in `project_handler.py` uses existing `team.json` membership system. No cross-layer import violations. No new packages.

---

## DISCOVERY

- **Read `prompts/default_agents/coder.yaml`:** YAML with fields: `name`, `emoji`, `role`, `prompts` (list), `tools` (list), `provider`, `model`, `self_improvement` (dict). The `role` field maps to `prompts/system/{role}.md`. Session key is derived as `special:{role}` in `special_agents.py:_load_registry()` at line 108.
- **Read `prompts/default_agents/debugger.yaml`:** Same pattern. Read-only tools, no write tools. `self_improvement` all false.
- **Read `agent/special_agents.py`:** `SpecialAgentDef` dataclass at line 27 with fields: `conv_id_prefix`, `display_name`, `role`, `emoji`, `color`, `tools`, `can_write`, `provider`, `model`, `api_key`, `app_title`, `self_improvement`, `mcp_servers`. `_load_registry()` at line 98 reads from `utils/agent_defs.load_agent_defs()` which returns `list[dict]` from YAML files. Color assigned round-robin. No `auto_open` or `api_key_built_in` fields exist yet — must be added.
- **Read `utils/agent_defs.py`:** `load_agent_defs()` at line 151 calls `_seed_defaults_if_empty()` then scans `~/.config/crabcakes/agents/` for YAML/JSON files. `_seed_defaults_if_empty()` at line 104 copies from `prompts/default_agents/` on first launch. Parse pipeline: YAML file → `_parse_agent_file()` → dict → added to list. No validation of unknown fields — extra YAML keys like `auto_open` are silently passed through to `special_agents.py`.
- **Read `agent/config.py`:** `load_agent_config()` at line 123 returns `AgentConfig` with `providers: dict[str, LLMProviderConfig]`. `LLMProviderConfig` dataclass at line 18: `name`, `base_url`, `api_key`, `default_model`, `supports_tools`, `supports_streaming`, `max_tokens`. `_create_default_config()` at line 191 creates `agent.json` with `openai` and `minimax` example providers. **Built-in Google provider must be injected after line 175** (after parsing user providers, before returning `AgentConfig`).
- **Read `agent/runtime.py`:** `_call_openai()` at line 70 accepts `base_url`, `api_key`, `model`, `messages`, `tools`, `timeout`, `x_title`. Uses `urllib.request.Request` with `Authorization: Bearer {api_key}` header. Model is stripped of provider prefix via `_model_id()` at line 44 (`"google/gemini-2.0-flash"` → `"gemini-2.0-flash"`). Per-conversation API key override at line 1242: `effective_api_key = conv.api_key or provider_cfg.api_key`.
- **Read `ui/handlers/agent_runtime_handler.py`:** `send_to_special_agent()` at line 293 — **CRITICAL: gates on `self._active_project is not None` at line 310.** Returns error "Open a project first" if no active project. The Crabcakes agent must work without an active project. `_get_runtime()` at line 253 uses `config.default_provider` to find provider — will crash at line 272 if no API key exists for default provider. `_resolve_agent_model()` at line 210: combines `provider/model` if both set on agent def. `create_conversation()` at line 864 accepts `project_path: str | None = None`.
- **Read `ui/window.py`:** Agent registration at lines 156-159: `for agent_def in get_special_agents(): self._agent_runtime_handler.add_special_agent(agent_def)`. Auto-open must go after line 163 (after `set_special_agents`).
- **Read `ui/views/main_content.py`:** `create_chat_tab()` at line 244. Checks `_tab_sessions` for existing tab → switches to it. Creates new `Gtk.ScrolledWindow` + `Gtk.Overlay` + chat box. Returns page index.
- **Read `agent/tools.py`:** `web_fetch` tool at line 744: parameters `{url, max_chars}`, returns `ToolResult`. Uses `httpx.get()` with 10s timeout. `web_search` tool at line 718: parameters `{query, count}`. `read_file` at line 517: parameters `{path}`. `list_files` at line 656: parameters `{path, pattern}`.
- **Read `utils/prompt_loader.py`:** `compose_system_prompt()` at line 117. Selection logic: always loads `default.md`, then role-specific (`coder.md`, `debugger.md`). For role `crabcakes`, no role-specific template will match — **must add explicit handling for role `crabcakes`** at the section currently handling `coder` and `debugger` (lines 160-166). Or add `crabcakes.md` and handle the role.
- **Architecture owner:** `agent/special_agents.py` owns the registry. `agent/config.py` owns provider config. `utils/agent_defs.py` owns file I/O. `ui/window.py` is the composition root.

### Project Onboarding Discovery

- **Read `prompts/system/project-onboarding.md`:** Onboarding interview template. Instructs agent to ask 5 questions in order (Purpose → Stack → Entry Points → Conventions → Team), one at a time, conversational. After interview, writes results to `.crabcakes/project.md` (sections: Purpose, Stack, Entry Points, Conventions) and `.crabcakes/team.json` (roles). Also appends dated entry to `.crabcakes/context.md` and updates `.crabcakes/workflow.md` onboarding row to ✅ done.
- **Read `utils/project_awareness.py`:** `is_project_onboarded()` strips HTML comments from `project.md`, checks if any content lines remain beyond `#` headers. If not, and `context.md` is empty → not onboarded. `init_project_config()` creates `.crabcakes/` dir, generates skeleton `project.md` (all HTML comments), creates empty `context.md`, creates `team.json`, creates `awareness.json`.
- **Read `utils/prompt_loader.py` lines 180-189:** Checks `is_project_onboarded(project_path)` — if not onboarded, loads `project-onboarding.md` template into the system prompt. This means **any agent with a project_path set** will receive onboarding instructions when the project is fresh. **No code change needed** — this already works.
- **Read `utils/workflow_state.py`:** `init_workflow()` creates `.crabcakes/workflow.md` with 7 phases (onboarding → discovery → architecture → task-planning → implementation → testing → ship). Onboarding starts as `🔄 current`, rest are `⏳ pending`.
- **Read `ui/handlers/project_handler.py`:** `create_project()` creates directory, calls `init_project_config()`, calls `init_workflow()`, calls `open_project()`. `open_project()` sets `_active_project_name/path`, inits `.crabcakes/`, loads members, fires `_on_project_opened` callbacks. **Members loaded from `team.json`** via `_load_members()`. `toggle_agent()` adds/removes session key from members list.
- **Read `models/team.py`:** `ProjectTeam` dataclass: `members: list[TeamMember]`, `pm_name: str`, `pm_id: str`. `TeamMember`: `session_key`, `name`, `role`, `can_write`. `add_member()` appends if not present (no duplicates).
- **Read `ui/window.py` lines 328-335:** `_on_project_opened` callbacks include `agent_runtime_handler.set_active_project(n, p)` which updates all special agent conversations with the project_path. **The Crabcakes agent's conversation gets `project_path` set, which triggers system prompt rebuild including onboarding template if project is fresh.**
- **Key insight:** The onboarding template loads automatically via `compose_system_prompt()` for any agent that has a project_path when the project is fresh. The Crabcakes agent just needs: (1) to be added as a member of new projects, (2) the `write_file` tool so it can write onboarding results back to `.crabcakes/`.

---

## 1. Overview

### Problem

New users open Crabcakes and see an empty workspace with no guidance. Existing agents (Coder, Debugger) require configured API keys and an active project. There's no in-app help or onboarding.

### Solution

Add a pre-configured local agent named "Crabcakes" (🦀) that:
1. Auto-opens on every app launch
2. Works out of the box via a built-in Google Gemini free-tier API key
3. Reads documentation live from GitHub on demand
4. Upgrades to user-configured keys when available
5. **Auto-added to every new project as the onboarding guide** — walks users through the project onboarding interview

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| Agent YAML definition (`crabcakes.yaml`) | Agent Builder UI changes |
| System prompt (`crabcakes.md`) | Local/embedded LLM (Ollama) |
| Built-in Google Gemini free-tier provider | Multi-provider fallback |
| Auto-open tab on every launch | First-launch-only detection |
| Live GitHub knowledge reads via `web_fetch` | Knowledge file editor in UI |
| 7 knowledge base `.md` files in repo | Auto-generation from docs |
| Auto-add to new projects as onboarding guide | Removing Crabcakes from project membership |
| Project onboarding write-back (`write_file` tool) | Custom onboarding per project type |

### Architecture Principles

- §3.6: `window.py` wires, no logic
- §8.6: Handler pattern — logic in handlers, widgets in views
- `prompts/default_agents/*.yaml` pattern: agent definitions from YAML
- `prompts/system/*.md` pattern: system prompts from templates
- `agent/config.py` pattern: provider injection alongside user config

---

## 2. Changes by File

### 2.1 `prompts/default_agents/crabcakes.yaml` — NEW FILE (~25 lines)

Agent definition following `coder.yaml` / `debugger.yaml` pattern exactly.

```yaml
# Crabcakes — Always-on help assistant and project onboarding guide
name: Crabcakes
emoji: "🦀"
role: crabcakes
prompts:
  - system/crabcakes.md
tools:
  - read_file
  - list_files
  - write_file
  - web_search
  - web_fetch
provider: google
model: gemini-2.0-flash
auto_open: true
api_key_built_in: true
auto_add_to_projects: true
self_improvement:
  bug_journal: false
  project_rules: false
  enforcement: false
  structured_feedback: false
  dream_consolidation: false
```

**Key differences from Coder/Debugger:**
- `auto_open: true` — new field, signals window.py to open tab on launch
- `api_key_built_in: true` — new field, signals built-in key available
- `auto_add_to_projects: true` — new field, auto-adds to new projects as member
- `self_improvement` all false — help bot doesn't need SI layer
- `write_file` included — needed for project onboarding write-back (writing to `.crabcakes/project.md`, `.crabcakes/context.md`, `.crabcakes/workflow.md`)
- `can_write` derived from tools list — will be `True` because `write_file` is present
- `provider: google` instead of `minimax`

**How it flows through the pipeline:**
1. `_seed_defaults_if_empty()` copies this to `~/.config/crabcakes/agents/crabcakes.yaml` on first launch
2. `load_agent_defs()` parses the YAML → returns dict
3. `_load_registry()` creates `SpecialAgentDef(conv_id_prefix="special:crabcakes", display_name="Crabcakes", ...)`
4. `window.py` iterates `get_special_agents()` → `add_special_agent(agent_def)`

### 2.2 `prompts/system/crabcakes.md` — NEW FILE (~60 lines)

System prompt template. Must be in `prompts/system/` to be found by `load_prompt_template("crabcakes")`.

```markdown
You are **Crabcakes** 🦀 — the always-on help assistant for CrabCakes, a GTK4 desktop application for multi-agent chat via OpenClaw.

You are the first thing users see when they open the app. Like a receptionist at the front desk, you're always there to help.

## Your Role

You help users with:
- **Getting started** — Installation, first-time setup, configuration
- **Configuration** — Gateway URLs, API keys, agent setup, agent.json
- **Features** — How to use projects, prompts, slash commands, group chat
- **Troubleshooting** — Common issues, error messages, connectivity
- **Tips & tricks** — Power user features, workflow suggestions

## What You Know

You have access to the CrabCakes knowledge base on GitHub. When asked a question:

1. Use `web_fetch` to read the relevant file from `https://raw.githubusercontent.com/qsmtco/crabcakes/main/knowledge/`
2. Available knowledge files:
   - `setup.md` — Installation and first-run guide
   - `configuration.md` — Configuration options and agent.json
   - `agents.md` — How agents work (Coder, Debugger, custom)
   - `features.md` — Feature overview and how-tos
   - `commands.md` — Slash command reference
   - `gateway.md` — OpenClaw gateway connection
   - `troubleshooting.md` — Common problems and solutions
3. Answer based on the documentation — be specific and accurate
4. If `web_fetch` fails (offline), answer from what you know and note that detailed docs require internet

## Project Onboarding

You are the **default onboarding agent** for every new project. When a user creates or opens a project for the first time, you'll be automatically added to it.

When you receive the onboarding prompt (it will be injected automatically when the project manifest is empty), follow the project-onboarding instructions. Your job is to:
1. Greet the user and name the project
2. Ask about the project one question at a time (purpose → stack → entry points → conventions → team)
3. Write the answers to `.crabcakes/project.md`
4. Update `.crabcakes/team.json` with team roles
5. Append a dated entry to `.crabcakes/context.md`
6. Update `.crabcakes/workflow.md` — change the onboarding row status to ✅ done
7. Confirm completion and suggest loading cc-workflow-guide for the full development workflow

You have `write_file` specifically for onboarding. Use it to write the onboarding results to the `.crabcakes/` directory. Do not write to any other files.

After onboarding is complete, you remain on the project team as a helper. Users can ask you questions about CrabCakes at any time.

## Tone

- Friendly, concise, helpful
- Don't over-explain — give the answer, then offer more detail if they want it
- Use markdown formatting (bold for UI elements, code blocks for commands)
- If something is complicated, break it into numbered steps
- Never condescending — assume the user is smart but new to CrabCakes

## Boundaries

- You know about CrabCakes and OpenClaw
- You can only write to `.crabcakes/` files (for onboarding)
- You can read any project file the user asks about
- For code changes, suggest the user ask the Coder agent
- For debugging, suggest the Debugger agent
- You don't access personal files outside the project

## Important Paths

- Config directory: `~/.config/crabcakes/`
- Agent config: `~/.config/crabcakes/agent.json`
- Agent definitions: `~/.config/crabcakes/agents/*.yaml`
- Prompts: `prompts/` directory within the app

## Opening Message

When a new conversation starts (no prior messages), greet the user naturally:

"Hey! I'm Crabcakes 🦀 — your assistant. I can help you get set up, answer questions about features, or troubleshoot issues. What can I help you with?"

On subsequent opens with an existing conversation, don't re-greet — just wait for the user.
```

### 2.3 `knowledge/*.md` — 7 NEW FILES

Documentation files in the repo that the agent reads live from GitHub. Each < 3KB.

```
knowledge/
├── setup.md              (~80 lines)
├── configuration.md      (~100 lines)
├── agents.md             (~80 lines)
├── features.md           (~100 lines)
├── commands.md           (~80 lines)
├── gateway.md            (~60 lines)
└── troubleshooting.md    (~80 lines)
```

Content is user-facing documentation (not developer docs). Written in clear, concise markdown. Each file is self-contained.

**These files are referenced by the system prompt** — the agent uses `web_fetch` to read them from `https://raw.githubusercontent.com/qsmtco/crabcakes/main/knowledge/{filename}`. They also exist in the repo so they're available for direct reading if the agent has `read_file` and the app is run from source.

### 2.4 `agent/config.py` — MODIFY (~30 lines added)

**What changes:** Add built-in Google Gemini provider as a constant, inject it into `load_agent_config()` when user hasn't configured a `google` provider.

**Location:** After line 175 (after `providers` dict is built from `agent.json`), before `AgentConfig` is returned at line 197.

**Add constant after imports (after line 17):**

```python
# Built-in free-tier Gemini key for the Crabcakes help agent.
# Google AI Studio free tier: 1,500 RPD, 15 RPM, 1M TPM, no credit card.
# This is NOT a secret — it's a shared free-tier key with rate limits.
# Users are encouraged to configure their own keys for better performance.
_BUILT_IN_GOOGLE_KEY = "PLACEHOLDER"  # Replace with actual key from Google AI Studio

_BUILT_IN_GOOGLE_PROVIDER = LLMProviderConfig(
    name="google",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    api_key=_BUILT_IN_GOOGLE_KEY,
    default_model="gemini-2.0-flash",
    supports_tools=True,
    supports_streaming=True,
    max_tokens=1_000_000,
)
```

**Add injection after line 175 (after parsing user providers), before enforcement config parsing:**

```python
    # Inject built-in Google provider if not user-configured.
    # This ensures the Crabcakes help agent works out of the box.
    if "google" not in providers:
        providers["google"] = _BUILT_IN_GOOGLE_PROVIDER
        logger.info("Injected built-in Google Gemini provider for Crabcakes help agent")
```

**Why this location:** `providers` dict is fully built from `agent.json` at this point. If user has configured their own `google` provider, `"google" in providers` is True and we skip injection — their key takes priority.

**Exception handling:** No new exceptions. `LLMProviderConfig` construction cannot fail (all strings). Dict membership check is safe.

**Why `_BUILT_IN_GOOGLE_PROVIDER` as a module-level constant:** Avoids recreating the dataclass on every `load_agent_config()` call. Constant is defined once, referenced by the injection check.

### 2.5 `agent/special_agents.py` — MODIFY (~30 lines added)

**What changes:** Add `auto_open`, `api_key_built_in`, and `auto_add_to_projects` fields to `SpecialAgentDef`. Add `get_auto_open_agents()` and `get_project_onboarding_agents()` helpers. Parse new fields from YAML in `_load_registry()`.

**Change 1 — Add fields to dataclass (after line 48, `mcp_servers` field):**

```python
    auto_open: bool = False              # open tab on every app launch
    api_key_built_in: bool = False       # has built-in API key, no user config needed
    auto_add_to_projects: bool = False   # auto-add as member to every new project
```

**Why defaults are `False`:** Backward-compatible — existing Coder/Debugger definitions don't have these fields, so they default to False (no auto-open, no built-in key, no auto-add).

**Change 2 — Parse new fields in `_load_registry()` (inside the for loop, after `mcp_servers` coercion at line 120, before `registry[session_key] = SpecialAgentDef(...)` at line 123):**

**Modify the `SpecialAgentDef(...)` constructor call at line 123 to include:**

```python
        registry[session_key] = SpecialAgentDef(
            # ... existing fields unchanged ...
            mcp_servers=raw_mcp,
            auto_open=agent_def.get("auto_open", False),                    # NEW
            api_key_built_in=agent_def.get("api_key_built_in", False),     # NEW
            auto_add_to_projects=agent_def.get("auto_add_to_projects", False),  # NEW
        )
```

**Change 3 — Add helper functions (after `get_special_agent()` at line 179):**

```python
def get_auto_open_agents() -> list[SpecialAgentDef]:
    """Return agents that should auto-open on every app launch."""
    return [a for a in get_special_agents() if a.auto_open]


def get_project_onboarding_agents() -> list[SpecialAgentDef]:
    """Return agents that should be auto-added to every new project for onboarding."""
    return [a for a in get_special_agents() if a.auto_add_to_projects]
```

**Why a list comprehension:** `get_special_agents()` returns `list[SpecialAgentDef]` from `_ensure_loaded().values()`. Simple filter. O(n) where n is number of agents (typically 3-5).

### 2.6 `utils/agent_defs.py` — MODIFY (~10 lines added)

**What changes:** Handle `auto_open` and `api_key_built_in` fields when saving agent definitions. Also skip `api_key_built_in` from validation error about missing API keys.

**Change 1 — In `validate_agent_def()`, after line 302 (API key validation block), skip validation for built-in key agents:**

```python
    # Check for API key for selected provider
    provider_keys = agent_def.get("provider_keys", {})
    if provider and not provider_keys.get(provider):
        # Check legacy api_key as fallback
        if not agent_def.get("api_key"):
            # Built-in key agents don't need user-configured keys
            if not agent_def.get("api_key_built_in", False):
                errors.append(f"API key required for provider '{provider}'")
```

**Why:** The Crabcakes agent has `api_key_built_in: true` and no `api_key` in the YAML. Without this change, `validate_agent_def()` would flag it as invalid when the user opens the Agent Builder.

**Change 2 — In `save_agent_def()`, the export already strips `_`-prefixed keys but `auto_open` and `api_key_built_in` are not prefixed. They'll be saved as-is, which is correct — they're part of the definition schema.**

**No other changes needed.** `load_agent_defs()` doesn't validate — it just parses and returns dicts. Unknown keys pass through.

### 2.7 `ui/window.py` — MODIFY (~15 lines added)

**What changes:** Auto-open Crabcakes agent tab after registration. Also handle the project requirement for the Crabcakes agent.

**Change 1 — Auto-open after agent registration (after line 163, `self._left_panel.set_special_agents(...)`):**

```python
        # Auto-open Crabcakes help agent on every launch
        from agent.special_agents import get_auto_open_agents
        for agent_def in get_auto_open_agents():
            self._main_content.create_chat_tab(agent_def.conv_id_prefix, agent_def.display_name)
```

**Why this location:** After `add_special_agent()` registers all agents (line 159) and after `set_special_agents()` injects into left panel (line 163). Before any gateway connection attempts.

**What `create_chat_tab()` does:** Checks `_tab_sessions` dict for existing tab with matching session_key. If found, switches to it (`set_current_page`). If not found, creates new tab with chat box, scroll, overlay. Returns page index. This means on first launch a new tab is created; on subsequent launches the existing tab is focused.

**Change 2 — Set a synthetic project for the Crabcakes agent (after the auto-open block):**

```python
        # Set synthetic project context for auto-open agents that don't need a real project.
        # The Crabcakes agent works without a user project — give it the app directory.
        from agent.special_agents import get_auto_open_agents
        for agent_def in get_auto_open_agents():
            if agent_def.api_key_built_in:
                self._agent_runtime_handler.set_active_project(
                    "Crabcakes",
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                break  # Only set once
```

**Why needed:** `send_to_special_agent()` at `agent_runtime_handler.py:310` gates on `self._active_project is not None`. If no project is open, it shows an error. The Crabcakes agent needs to work without a user-opened project. Setting a synthetic project (the app's own directory) satisfies the project requirement without user action.

**Risk:** Setting `_active_project` to the app directory means other agents (Coder, Debugger) would also get this project context when messaged without a real project open. This is acceptable — the system prompt handles project context gracefully when the path doesn't contain user code.

**Alternative considered:** Relax the project requirement in `send_to_special_agent()` for agents with `api_key_built_in`. Rejected because it requires more invasive changes to the handler logic.

### 2.8 `ui/handlers/project_handler.py` — MODIFY (~30 lines added)

**What changes:** Add `_auto_add_onboarding_agents()` method. Call it in `create_project()` and `open_project()`.

**Change 1 — Add helper method (new method, after `_save_members()` at line ~390):**

```python
    def _auto_add_onboarding_agents(self, project_path: str) -> None:
        """Auto-add agents with auto_add_to_projects=True to the project team.

        Called during project creation and first open. These agents serve as
        project onboarding guides — they receive the project-onboarding template
        via compose_system_prompt() when the project is not yet onboarded.
        """
        try:
            from agent.special_agents import get_project_onboarding_agents
            onboarding_agents = get_project_onboarding_agents()
        except Exception:
            return  # Non-fatal — special agents may not be loaded yet

        if not onboarding_agents or not self._awareness:
            return

        team = self._awareness.load_team(project_path)
        changed = False
        for agent_def in onboarding_agents:
            if not team.has_member(agent_def.conv_id_prefix):
                from models.team import TeamMember
                team.add_member(TeamMember(
                    session_key=agent_def.conv_id_prefix,
                    name=agent_def.display_name,
                    role="onboarding guide",
                    can_write=True,  # needs write_file for onboarding
                ))
                changed = True
                # Also add to routing table if project is active
                if self._active_project_name:
                    self._agent_to_project.add(agent_def.conv_id_prefix, self._active_project_name)

        if changed:
            self._awareness.save_team(project_path, team)
            _logger.info("Auto-added onboarding agents to project at %s", project_path)
```

**Change 2 — Call in `create_project()` (after `init_project_config()` call, before `init_workflow()`):**

```python
        # Initialize .crabcakes/ with awareness artifacts
        if self._awareness:
            self._awareness.init_project_config(path, name, pm_name, pm_id)

        # Auto-add onboarding agents (Crabcakes 🦀) to new project team
        self._auto_add_onboarding_agents(path)
```

**Change 3 — Call in `open_project()` (after `init_project_config()` call, before `init_workflow()`):**

```python
        if self._awareness:
            self._awareness.init_project_config(path, name)

        # Auto-add onboarding agents if not already members
        self._auto_add_onboarding_agents(path)
```

**Why both `create_project` and `open_project`:** `create_project()` is for brand new projects. `open_project()` handles existing projects opened for the first time after the Crabcakes agent was added to the app — the agent should be retroactively added. `team.has_member()` prevents duplicates.

**Why `can_write=True`:** The Crabcakes agent needs `write_file` to write onboarding results. The team membership's `can_write` field is informational; the actual tool allowlist is enforced by the agent's YAML definition.

### 2.9 `utils/prompt_loader.py` — MODIFY (~5 lines added)

**What changes:** Add role `crabcakes` to the role-specific template loading section.

**Location:** After line 166 (after `elif agent_role == "debugger"` block), before the self-improvement section at line 170.

```python
    elif agent_role == "crabcakes":
        ct = load_prompt_template("crabcakes")
        if ct:
            parts.append(ct)
```

**Why needed:** `compose_system_prompt()` only loads role-specific templates for `coder` and `debugger`. Without this, `crabcakes.md` would never be loaded into the system prompt. The `default.md` template would be the only content, and the Crabcakes agent would have no personality or knowledge instructions.

### 2.11 `docs/ARCHITECTURE.md` — MODIFY (~50 lines added)

Update §2 directory structure, §3 module responsibilities, and §11 file inventory with:
- New `prompts/default_agents/crabcakes.yaml`
- New `prompts/system/crabcakes.md`
- New `knowledge/` directory (7 files)
- New fields on `SpecialAgentDef`: `auto_open`, `api_key_built_in`, `auto_add_to_projects`
- New functions: `get_auto_open_agents()`, `get_project_onboarding_agents()`
- Built-in Google provider in `agent/config.py`
- Auto-open wiring in `ui/window.py`
- Auto-add onboarding agents in `ui/handlers/project_handler.py`
- Crabcakes agent's dual role: general help (no project) + project onboarding (project active)

---

## 3. Data Flow

### 3.1 Startup Sequence (General Help Mode)

```
main.py → CrabcakesApp.on_activate()
  └── MainWindow.__init__()
       └── _build()
            ├── agent/special_agents.get_special_agents()
            │    └── _ensure_loaded() → _load_registry()
            │         └── load_agent_defs()
            │              └── _seed_defaults_if_empty()
            │                   └── copies prompts/default_agents/crabcakes.yaml
            │                       → ~/.config/crabcakes/agents/crabcakes.yaml
            │              └── _parse_agent_file("crabcakes.yaml")
            │                   └── returns {name: "Crabcakes", role: "crabcakes",
            │                                auto_open: true, api_key_built_in: true,
            │                                auto_add_to_projects: true, ...}
            │         └── builds SpecialAgentDef(conv_id_prefix="special:crabcakes",
            │                                     auto_open=True, auto_add_to_projects=True, ...)
            ├── for agent_def in get_special_agents():
            │    └── self._agent_runtime_handler.add_special_agent(agent_def)
            │         └── self._agents["special:crabcakes"] = SpecialAgentDef(...)
            │
            ├── get_auto_open_agents() → [SpecialAgentDef(auto_open=True)]
            │    └── self._main_content.create_chat_tab("special:crabcakes", "Crabcakes")
            │         └── creates tab with 🦀 label, chat box, scroll
            │
            ├── (synthetic project for built-in agents)
            │    └── set_active_project("Crabcakes", app_path)
            │
            └── ... rest of UI wiring
```

### 3.2 User Creates a New Project (Onboarding Flow)

```
User clicks "New Project" in left panel → fills form
  └── project_handler.create_project(name, path, pm_name, pm_id)
       ├── os.makedirs(path) — create project directory
       ├── awareness.init_project_config(path, name, pm_name, pm_id)
       │    └── creates .crabcakes/ with:
       │         ├── project.md (skeleton — all HTML comments)
       │         ├── team.json (empty members, pm info)
       │         ├── context.md (empty)
       │         └── awareness.json (initial snapshot)
       ├── _auto_add_onboarding_agents(path)  ← NEW
       │    └── get_project_onboarding_agents()
       │         → [SpecialAgentDef(auto_add_to_projects=True)]
       │         └── team.add_member(TeamMember(
       │              session_key="special:crabcakes",
       │              name="Crabcakes",
       │              role="onboarding guide",
       │              can_write=True))
       │         └── awareness.save_team(path, team)
       │              → .crabcakes/team.json now has Crabcakes as member
       ├── init_workflow(path)
       │    └── creates .crabcakes/workflow.md (onboarding=🔄 current)
       ├── git init + commit
       └── open_project(name, path)
            ├── sets _active_project_name/path
            ├── _auto_add_onboarding_agents(path) — idempotent (already added)
            ├── _load_members(name) → ["special:crabcakes"]
            ├── _agent_to_project.add("special:crabcakes", name)
            └── fires _on_project_opened callbacks:
                 ├── main_content.create_chat_tab("project:{name}", ...)
                 ├── agent_runtime_handler.set_active_project(name, path)
                 │    └── updates conv.project_path on all special agent conversations
                 │         └── Crabcakes conv: project_path = path
                 │              → system prompt rebuild:
                 │                compose_system_prompt(role="crabcakes", project_path=path)
                 │                 ├── loads default.md
                 │                 ├── loads collab.md
                 │                 ├── loads crabcakes-context.md
                 │                 ├── loads project-awareness.md (project active)
                 │                 ├── loads crabcakes-commands.md (project active)
                 │                 ├── is_project_onboarded(path) → False ✅
                 │                 │    └── loads project-onboarding.md ← ONBOARDING TRIGGER
                 │                 └── loads crabcakes.md (role-specific)
                 └── ... other callbacks

Next: User sends message to Crabcakes agent (or project tab → routed to Crabcakes)
  └── send_to_special_agent("special:crabcakes", text)
       ├── _active_project is (name, path) → passes project check ✅
       ├── create_conversation() with project_path=path
       │    └── system prompt includes project-onboarding.md
       │         └── Agent sees onboarding instructions, greets user
       └── runtime.send_message()
            └── Agent asks: "Fresh project: **MyApp**. What are we building?"
                 └── User answers → agent asks next question
                      └── After interview: agent writes to .crabcakes/project.md,
                           .crabcakes/context.md, .crabcakes/team.json, .crabcakes/workflow.md
                           using write_file tool
```

### 3.3 User Sends General Help Message (No Project)

```
User types in "special:crabcakes" tab → clicks Send
  └── main_content._on_send()
       └── chat_handler.on_send(text, session_key="special:crabcakes")
            └── detects special: prefix
                 └── agent_runtime_handler.send_to_special_agent("special:crabcakes", text)
                      ├── _active_project is ("Crabcakes", app_path) → passes project check ✅
                      ├── _get_runtime("Crabcakes")
                      │    └── load_agent_config()
                      │         └── providers["google"] = built-in LLMProviderConfig ✅
                      ├── _resolve_agent_model(agent_def)
                      │    └── provider="google", model="gemini-2.0-flash"
                      │         → returns "google/gemini-2.0-flash"
                      ├── create_conversation() or reuse existing
                      │    └── system_prompt from compose_system_prompt(role="crabcakes")
                      │         └── loads default.md + crabcakes.md
                      │         └── is_project_onboarded(app_path) → probably True (not a skeleton) ✅
                      │              → no onboarding template loaded
                      └── runtime.send_message("special:crabcakes", text)
                           └── _tool_loop thread
                                ├── build messages → call LLM
                                │    └── _call_openai(base_url=google_url, api_key=*** model=gemini-2.0-flash)
                                ├── LLM may call web_fetch("https://raw.githubusercontent.com/.../knowledge/setup.md")
                                │    └── tool executes → returns documentation content
                                ├── LLM responds with answer
                                └── on_response_complete → render in chat tab
```

### 3.4 Provider Override (User Configures Own Key)

```
User edits ~/.config/crabcakes/agent.json → adds google provider with own key
  └── Next app launch:
       └── load_agent_config()
            ├── parse providers from agent.json → includes "google" with user's key
            └── "google" in providers → skip built-in injection ✅
                 └── Crabcakes agent uses user's key
```

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `prompts/default_agents/crabcakes.yaml` | **NEW** | ~25 | Low — follows existing pattern |
| `prompts/system/crabcakes.md` | **NEW** | ~70 | Low — text content only |
| `knowledge/setup.md` | **NEW** | ~80 | Low — documentation |
| `knowledge/configuration.md` | **NEW** | ~100 | Low — documentation |
| `knowledge/agents.md` | **NEW** | ~80 | Low — documentation |
| `knowledge/features.md` | **NEW** | ~100 | Low — documentation |
| `knowledge/commands.md` | **NEW** | ~80 | Low — documentation |
| `knowledge/gateway.md` | **NEW** | ~60 | Low — documentation |
| `knowledge/troubleshooting.md` | **NEW** | ~80 | Low — documentation |
| `agent/config.py` | Modified | ~15 | Medium — provider injection |
| `agent/special_agents.py` | Modified | ~20 | Low — additive fields with defaults |
| `utils/agent_defs.py` | Modified | ~5 | Low — validation skip for built-in key |
| `ui/window.py` | Modified | ~15 | Medium — auto-open + synthetic project |
| `ui/handlers/project_handler.py` | Modified | ~30 | Medium — auto-add onboarding agents |
| `utils/prompt_loader.py` | Modified | ~5 | Low — add role handler |
| `docs/ARCHITECTURE.md` | Modified | ~50 | Low — documentation |
| **Total** | | **~825 lines net** | |

**Files NOT changed** (already correct or not needed):
- `agent/runtime.py` — already handles per-conversation API keys and provider resolution.
- `ui/handlers/agent_runtime_handler.py` — `send_to_special_agent()` works as-is once `_active_project` is set. `set_active_project()` already updates all conversations when a real project opens.
- `agent/context.py` — `build_system_prompt()` delegates to `compose_system_prompt()` which handles the new role AND loads onboarding template automatically when project is not onboarded.
- `agent/tools.py` — `web_fetch`, `web_search`, `write_file` already exist.
- `ui/views/main_content.py` — `create_chat_tab()` already handles "switch to existing" case.
- `utils/project_awareness.py` — `is_project_onboarded()`, `init_project_config()`, `load_team()`, `save_team()` all work as-is.
- `utils/workflow_state.py` — `init_workflow()`, `advance_phase()` work as-is.
- `prompts/system/project-onboarding.md` — existing onboarding template already instructs the agent to write to `.crabcakes/` files. No changes needed.

---

## 5. Implementation Order

1. **`agent/config.py`** — Add `_BUILT_IN_GOOGLE_KEY` constant and `_BUILT_IN_GOOGLE_PROVIDER`. Add injection in `load_agent_config()`. **Verify:** `load_agent_config()` returns `providers["google"]` when user hasn't configured one.
2. **`agent/special_agents.py`** — Add `auto_open`, `api_key_built_in`, and `auto_add_to_projects` fields to `SpecialAgentDef`. Add `get_auto_open_agents()` and `get_project_onboarding_agents()`. Parse new fields in `_load_registry()`. **Verify:** `SpecialAgentDef(auto_open=True, auto_add_to_projects=True)` works, both helpers return correct lists.
3. **`utils/agent_defs.py`** — Skip API key validation for `api_key_built_in` agents. **Verify:** `validate_agent_def()` for Crabcakes YAML returns no "API key required" error.
4. **`utils/prompt_loader.py`** — Add `crabcakes` role handler. **Verify:** `compose_system_prompt(agent_role="crabcakes")` loads `crabcakes.md`.
5. **`prompts/system/crabcakes.md`** — Write system prompt with onboarding instructions. **Verify:** `load_prompt_template("crabcakes")` returns content.
6. **`prompts/default_agents/crabcakes.yaml`** — Write agent definition with `write_file` tool and `auto_add_to_projects: true`. **Verify:** `_parse_agent_file()` parses correctly, `can_write` derived as True.
7. **`knowledge/*.md`** (7 files) — Write documentation. **Verify:** Files are valid markdown, each < 3KB.
8. **`ui/window.py`** — Add auto-open and synthetic project wiring. **Verify:** Crabcakes tab opens on launch, agent responds to messages.
9. **`ui/handlers/project_handler.py`** — Add `_auto_add_onboarding_agents()` method. Call in `create_project()` and `open_project()`. **Verify:** New project's `team.json` includes `special:crabcakes` member. Existing project without Crabcakes gets it added on open.
10. **`docs/ARCHITECTURE.md`** — Update documentation. **Verify:** All new files listed, module descriptions accurate.

---

## 6. Acceptance Criteria

### General Help Agent
- [ ] `prompts/default_agents/crabcakes.yaml` exists with `name: Crabcakes`, `emoji: "🦀"`, `role: crabcakes`, `auto_open: true`, `api_key_built_in: true`, `auto_add_to_projects: true`
- [ ] `prompts/system/crabcakes.md` exists in `prompts/system/` with personality, GitHub knowledge instructions, and onboarding role description
- [ ] 7 knowledge base files exist in `knowledge/` directory
- [ ] `SpecialAgentDef` has `auto_open`, `api_key_built_in`, and `auto_add_to_projects` fields with `False` defaults
- [ ] `get_auto_open_agents()` returns only agents with `auto_open=True`
- [ ] `get_project_onboarding_agents()` returns only agents with `auto_add_to_projects=True`
- [ ] `load_agent_config()` includes `providers["google"]` when user hasn't configured a google provider
- [ ] `compose_system_prompt(agent_role="crabcakes")` loads `crabcakes.md` template
- [ ] `validate_agent_def()` doesn't flag missing API key for `api_key_built_in: true` agents
- [ ] Crabcakes 🦀 tab auto-opens on every app launch
- [ ] Crabcakes agent responds to messages using built-in Google Gemini key
- [ ] Crabcakes agent can use `web_fetch` to read knowledge files from GitHub
- [ ] When user configures their own `google` provider, Crabcakes agent uses that key instead
- [ ] Conversation persists across app restarts
- [ ] No impact on Coder, Debugger, or other existing special agents

### Project Onboarding
- [ ] When user creates a new project, Crabcakes agent is automatically added to `.crabcakes/team.json` as a member
- [ ] When user opens an existing project that doesn't have Crabcakes as a member, it is auto-added
- [ ] Crabcakes agent appears in the project's agent list in the left panel
- [ ] When the Crabcakes agent receives a message in a fresh (not onboarded) project context, the `project-onboarding.md` template is automatically included in its system prompt
- [ ] Crabcakes agent asks the onboarding questions (Purpose → Stack → Entry Points → Conventions → Team) one at a time
- [ ] Crabcakes agent writes onboarding results to `.crabcakes/project.md` using `write_file` tool
- [ ] Crabcakes agent updates `.crabcakes/team.json` with team roles
- [ ] Crabcakes agent updates `.crabcakes/workflow.md` to mark onboarding as ✅ done
- [ ] After onboarding, the `project-onboarding.md` template stops being loaded for that project
- [ ] User can remove Crabcakes from the project via the existing toggle_agent (+/−) mechanism

### Documentation
- [ ] `docs/ARCHITECTURE.md` updated with all new files, fields, and data flows

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| First launch — no `~/.config/crabcakes/` exists | `_seed_defaults_if_empty()` creates agents dir, copies `crabcakes.yaml`. `_create_default_config()` creates `agent.json` with example providers. Built-in Google provider injected. Crabcakes tab opens, agent responds. |
| No internet — Gemini API unreachable | `_call_openai()` raises `urllib.error.URLError` or `httpx.RequestError`. `send_message()` catches exception, fires `on_error` callback. Error message shown in chat tab. |
| No internet — GitHub unreachable | Agent's `web_fetch` returns error. Agent answers from system prompt knowledge, notes detailed docs require internet. |
| User configures own `google` provider | User's key takes priority. Built-in injection skipped. |
| User deletes `google` provider | Built-in provider injected on next launch. |
| Gemini free-tier quota exhausted (1,500 RPD) | HTTP 429, error shown in chat tab. |
| Multiple agents with `auto_open: true` | Each gets a tab. Currently only Crabcakes has this. |
| User edits Crabcakes agent via Agent Builder | `validate_agent_def()` skips API key check. Save works. |
| User has no projects open | Synthetic project (app dir) set at startup. General help mode. No onboarding template loaded. |
| User opens a real project after launch | `set_active_project()` updates all conversations. Crabcakes goes from general help to project mode. If fresh project → onboarding template loaded. |
| User creates a project but doesn't message Crabcakes | Crabcakes is a member but doesn't proactively message. Onboarding template waits in system prompt until messaged. |
| User removes Crabcakes from project via +/− button | `toggle_agent()` removes from `team.json`. User can re-add. |
| User opens an old project (pre-Crabcakes) | `open_project()` → `_auto_add_onboarding_agents()` adds it. If project not onboarded, onboarding triggers on first message. |
| Onboarding `write_file` could write anywhere | System prompt constrains writes to `.crabcakes/` only. Same trust model as Coder agent's write access. |
| User skips onboarding ("skip it, help me with this") | Per onboarding template rules: agent helps immediately. `.crabcakes/` remains skeleton. Onboarding template still loads next time but agent doesn't force it. |

---

## 8. ARCHITECTURE.md Updates Required

1. **§2 Directory structure:**
   - Add `knowledge/` directory with 7 files listed
   - Add `prompts/default_agents/crabcakes.yaml` to the defaults
   - Add `prompts/system/crabcakes.md` to system prompts

2. **§3 Module responsibilities:**
   - Update `SpecialAgentDef` — document `auto_open`, `api_key_built_in`, `auto_add_to_projects` fields
   - Document `get_auto_open_agents()` and `get_project_onboarding_agents()` functions
   - Update `agent/config.py` — document built-in Google provider injection
   - Update `utils/prompt_loader.py` — document `crabcakes` role handling
   - Update `ui/handlers/project_handler.py` — document `_auto_add_onboarding_agents()` and the auto-add flow

3. **§11 File inventory:**
   - Add `prompts/default_agents/crabcakes.yaml`
   - Add `prompts/system/crabcakes.md`
   - Add `knowledge/` (7 files)

4. **§4 Data flow:**
   - Add startup flow showing auto-open
   - Add Crabcakes agent messaging flow (general help)
   - Add project creation flow showing auto-add + onboarding trigger
   - Document the dual-mode behavior: general help (synthetic project) vs project onboarding (real project)

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `SpecialAgentDef` dataclass at `special_agents.py:27` — adding fields with defaults is backward-compatible ✅
   - `_load_registry()` at line 123 — adding `auto_open`, `api_key_built_in`, `auto_add_to_projects` params ✅
   - `load_agent_config()` at line 175 — providers dict exists, injection check safe ✅
   - `compose_system_prompt()` at line 166 — adding `elif agent_role == "crabcakes"` ✅
   - `create_chat_tab()` at `main_content.py:244` — takes `(session_key, agent_name)` ✅
   - `validate_agent_def()` at line 302 — `agent_def.get("api_key_built_in", False)` safe ✅
   - `ProjectTeam.add_member()` at `models/team.py` — checks `has_member()` first, no duplicates ✅
   - `project_handler._save_members()` at line 377 — saves via `awareness.save_team()` ✅
   - `_auto_add_onboarding_agents()` — uses `load_team()`, `add_member()`, `save_team()` — all existing APIs ✅
   - `_get_runtime()` at line 253 — **⚠️ Issue:** crashes if default provider has no key (see below).

2. **Did I catch all exception types?**
   - `load_agent_config()`: `json.JSONDecodeError`, `OSError` — already handled ✅
   - `_get_runtime()`: `RuntimeError` if no provider/key — **⚠️ needs fix** (see below)
   - `web_fetch` tool: `httpx.HTTPStatusError`, `httpx.RequestError` — already handled ✅
   - `compose_system_prompt()`: silently skips missing templates ✅
   - `_auto_add_onboarding_agents()`: wrapped in try/except for import — safe ✅

3. **Did I verify key structures?**
   - `_tab_sessions`: `dict[int, str]` ✅
   - `providers`: `dict[str, LLMProviderConfig]` ✅
   - `_agents`: `dict[str, SpecialAgentDef]` ✅
   - Session key format: `special:{role}` → `"special:crabcakes"` ✅
   - `ProjectTeam.members`: `list[TeamMember]` ✅
   - `team.json` structure: `{"members": [...], "pm": {...}}` ✅

4. **Did I trace the data flow end-to-end?**
   - General help: YAML → registry → auto-open → message → runtime → LLM → response. All traced ✅
   - Project creation: `create_project()` → `init_project_config()` → `_auto_add_onboarding_agents()` → `open_project()` → `set_active_project()` → system prompt rebuild with onboarding. All traced ✅
   - Onboarding write-back: agent asks questions → `write_file` on `.crabcakes/*` files. All traced ✅
   - Post-onboarding: `is_project_onboarded()` → True → onboarding template skipped. ✅
   - **⚠️ Gap:** `_get_runtime()` crashes if default provider has no API key.

5. **Would an implementer produce working code?**
   - Yes for all files except the `_get_runtime()` issue. Fix: fallback to first provider with a non-empty key.

---

## ⚠️ Known Issue: `_get_runtime()` Crash Without Default Provider Key

**File:** `ui/handlers/agent_runtime_handler.py`, lines 253-288

**Problem:** `_get_runtime()` uses `config.providers.get(config.default_provider)` to get the provider for creating the `AgentRuntime` instance. If `default_provider` is `"openai"` (the default) and no OpenAI key is configured, line 272 raises `RuntimeError("No API key configured for provider openai")`. This happens even though the Crabcakes agent has its own `google` provider with a built-in key.

**Root cause:** `AgentRuntime.__init__` takes the full `AgentConfig` (which includes all providers). The runtime uses `config.default_provider` as a fallback when creating conversations, but `_get_runtime()` doesn't need the default provider to have a key — it just needs to create a runtime instance. The per-agent API key flows through `create_conversation()` → `_call_llm()` → `effective_api_key = conv.api_key or provider_cfg.api_key`.

**Fix:** In `_get_runtime()`, after checking default provider, if no API key is found, try all providers until one with a key is found:

```python
# At line 270-272, replace:
if not provider.api_key:
    raise RuntimeError(f"No API key configured for provider {config.default_provider}")

# With:
if not provider.api_key:
    # Try any provider with a non-empty API key (e.g. built-in Google)
    for fallback_name, fallback_prov in config.providers.items():
        if fallback_prov.api_key:
            provider = fallback_prov
            break
    else:
        raise RuntimeError("No API key configured for any provider")
```

This is a **prerequisite fix** that must be applied before the Crabcakes agent can work on a fresh install with no user-configured keys.

---

## 9. Project Onboarding Integration — Design Rationale

### Why the Crabcakes Agent Is the Right Onboarding Guide

1. **It's always there.** Auto-opens on every launch. No discovery needed.
2. **It has the tools.** `write_file` lets it write to `.crabcakes/` for onboarding results. `read_file` lets it inspect the project. `web_fetch` lets it read knowledge base docs.
3. **It has a built-in key.** Zero-config means onboarding works on the very first launch, before the user has configured anything.
4. **The existing onboarding system is prompt-driven.** `project-onboarding.md` already defines the interview flow. It loads automatically via `compose_system_prompt()` when the project is fresh. No code changes needed to the onboarding logic itself.
5. **Team membership enables routing.** Adding `special:crabcakes` to `team.json` means the project tab can route messages to the Crabcakes agent.

### How the Dual-Mode Works

The Crabcakes agent operates in two modes depending on context:

| Mode | Trigger | System Prompt Contents | Behavior |
|------|---------|----------------------|----------|
| **General Help** | No real project open (synthetic project = app dir) | `default.md` + `crabcakes.md` + knowledge instructions | Answers questions about CrabCakes, fetches docs from GitHub |
| **Project Onboarding** | Real project opened, project not yet onboarded | All of above + `project-awareness.md` + `project-onboarding.md` | Conducts onboarding interview, writes results to `.crabcakes/` |

The transition is seamless — `set_active_project()` already rebuilds the system prompt for all special agent conversations when a project opens.

### Why `auto_add_to_projects` Instead of Hardcoding

The `auto_add_to_projects` field is generic — any agent could have it. This means:
- Future agents could also auto-add to projects (e.g. a "QA" agent)
- The Crabcakes agent can be edited via Agent Builder — if someone removes `auto_add_to_projects`, it stops auto-adding
- The logic lives in `project_handler.py` (where it belongs), not in `special_agents.py` or `window.py`

### What's NOT Changing in the Onboarding System

- `prompts/system/project-onboarding.md` — the onboarding interview template remains unchanged
- `utils/project_awareness.py` — `is_project_onboarded()`, `init_project_config()` remain unchanged
- `utils/workflow_state.py` — `init_workflow()`, `advance_phase()` remain unchanged
- `utils/prompt_loader.py` lines 180-189 — the onboarding template injection logic remains unchanged

The onboarding system is already well-designed. The Crabcakes agent just becomes the default agent that *receives* the onboarding prompt, instead of whichever agent the user happens to message first.
