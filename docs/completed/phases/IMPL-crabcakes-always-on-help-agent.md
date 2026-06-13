# IMPLEMENTATION PLAN: Crabcakes Always-On Help Agent

**Spec:** `docs/specs/SPEC-crabcakes-always-on-help-agent.md`
**Proposal:** `docs/proposals/PROPOSAL-crabcakes-always-on-help-agent.md`
**Status:** Planning — awaiting Captain approval to begin

---

## Phase 0 — Prerequisite Fix: `_get_runtime()` Crash
**Goal:** Fix the crash when default provider has no API key
**Files:** `ui/handlers/agent_runtime_handler.py`
**Risk:** Medium — touches runtime initialization path
**Verify:** App launches and creates AgentRuntime even with no configured API keys

**What:**
- In `_get_runtime()`, after checking default provider, fall back to first provider with a non-empty API key
- See spec §⚠️ Known Issue for exact fix

**Why first:** The Crabcakes agent can't work on a fresh install without this fix. Must land before anything else.

---

## Phase 1 — Data Model: New Fields on SpecialAgentDef
**Goal:** Add the three new fields so they can be read from YAML and used everywhere
**Files:** `agent/special_agents.py`
**Risk:** Low — additive dataclass fields with defaults, backward-compatible
**Verify:** `SpecialAgentDef(auto_open=True, api_key_built_in=True, auto_add_to_projects=True)` works. Coder/Debugger definitions still load without errors.

**What:**
- Add `auto_open: bool = False` field
- Add `api_key_built_in: bool = False` field
- Add `auto_add_to_projects: bool = False` field
- Parse all three from YAML dict in `_load_registry()`
- Add `get_auto_open_agents()` helper
- Add `get_project_onboarding_agents()` helper

---

## Phase 2 — Built-in Provider: Google Gemini Free Tier
**Goal:** Inject built-in Google provider so the Crabcakes agent works with zero config
**Files:** `agent/config.py`
**Risk:** Medium — touches provider loading, must not break user-configured providers
**Verify:** `load_agent_config()` returns `providers["google"]` when user hasn't configured one. User's own `google` provider takes priority.

**What:**
- Add `_BUILT_IN_GOOGLE_KEY` constant (placeholder until real key provisioned)
- Add `_BUILT_IN_GOOGLE_PROVIDER` constant (LLMProviderConfig)
- Add injection check in `load_agent_config()` after parsing user providers

---

## Phase 3 — Agent Definition: YAML + System Prompt + Role Handler
**Goal:** Create the Crabcakes agent definition and wire it into the prompt system
**Files:** `prompts/default_agents/crabcakes.yaml` (new), `prompts/system/crabcakes.md` (new), `utils/prompt_loader.py`, `utils/agent_defs.py`
**Risk:** Low — mostly new files, small edits to existing files
**Verify:** `_parse_agent_file("crabcakes.yaml")` parses correctly. `compose_system_prompt(agent_role="crabcakes")` loads `crabcakes.md`. `validate_agent_def()` doesn't flag missing API key.

**What:**
- Write `crabcakes.yaml` with all fields including `write_file` tool
- Write `crabcakes.md` system prompt with personality + onboarding instructions
- Add `elif agent_role == "crabcakes"` to `compose_system_prompt()`
- Add `api_key_built_in` skip to `validate_agent_def()`

---

## Phase 4 — Auto-Open: Tab Opens on Every Launch
**Goal:** Crabcakes tab is visible immediately when the app starts
**Files:** `ui/window.py`
**Risk:** Medium — touches startup sequence, synthetic project affects all special agents
**Verify:** App launches with Crabcakes 🦀 tab open and focused. Agent responds to messages. Switching to a real project works correctly.

**What:**
- Auto-open Crabcakes tab after agent registration using `get_auto_open_agents()`
- Set synthetic project (`set_active_project("Crabcakes", app_path)`) for built-in key agents
- Verify Coder/Debugger still work normally

---

## Phase 5 — Project Onboarding: Auto-Add to New Projects
**Goal:** Crabcakes agent is automatically a member of every new project and triggers onboarding
**Files:** `ui/handlers/project_handler.py`
**Risk:** Medium — touches project creation path, must not break existing project flow
**Verify:** Create a new project → `team.json` includes `special:crabcakes`. Open an old project → agent added retroactively. Message Crabcakes in fresh project → onboarding interview starts. After onboarding → `project.md` populated, `workflow.md` updated.

**What:**
- Add `_auto_add_onboarding_agents()` method
- Call in `create_project()` after `init_project_config()`
- Call in `open_project()` after `init_project_config()`
- Test full onboarding flow end-to-end

---

## Phase 6 — Knowledge Base: 7 Documentation Files
**Goal:** Write the documentation files that the agent reads from GitHub
**Files:** `knowledge/setup.md` (new), `knowledge/configuration.md` (new), `knowledge/agents.md` (new), `knowledge/features.md` (new), `knowledge/commands.md` (new), `knowledge/gateway.md` (new), `knowledge/troubleshooting.md` (new)
**Risk:** Low — new documentation files, no code changes
**Verify:** Each file is valid markdown, < 3KB, self-contained. Agent can `web_fetch` them from GitHub and answer questions based on content.

**What:**
- Write all 7 knowledge files with user-facing content
- Verify GitHub raw URLs return the files after push
- Test `web_fetch` from agent

---

## Phase 7 — Documentation: ARCHITECTURE.md Updates
**Goal:** Update architecture docs to reflect all changes
**Files:** `docs/ARCHITECTURE.md`
**Risk:** Low — documentation only
**Verify:** All new files, fields, functions, and data flows documented.

**What:**
- Update §2 directory structure
- Update §3 module responsibilities
- Update §4 data flow
- Update §11 file inventory

---

## Phase Dependencies

```
Phase 0 (prereq fix)
  └→ Phase 1 (data model)
       ├→ Phase 2 (provider)
       │    └→ Phase 3 (agent def)
       │         └→ Phase 4 (auto-open)
       │              └→ Phase 5 (onboarding)
       ├→ Phase 6 (knowledge) — independent, can run parallel with 3-5
       └→ Phase 7 (docs) — runs last
```

Phase 6 (knowledge files) is independent of phases 3-5 and can be done in parallel or at any point after phase 1.

Phase 7 (docs) runs last after all code is verified.

---

## Not Yet Addressed
- [ ] Provision actual Google AI Studio free-tier API key (replace `***` placeholder)
- [ ] Verify Google Gemini OpenAI-compatible endpoint supports `tools` parameter
- [ ] Check Google ToS on sharing free-tier keys in open source
- [ ] Push knowledge files to GitHub and verify raw URL access
