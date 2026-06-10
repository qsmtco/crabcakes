# SPEC: Agent `llm_name` Field — Single Source of Truth

**Date:** 2026-06-10
**Author:** Qaster
**Status:** Draft — for implementation
**Depends on:** `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md`, `docs/specs/SPEC_PER_AGENT_API_KEY.md`
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
> - `utils/agent_defs.py` (§3.21r): pure Python, no GTK, owns persistence.
> - `ui/views/agent_builder.py` (§3.21t): pure view, no business logic.
> - `ui/handlers/agent_builder_handler.py` (§3.21s): no GTK imports, delegates to `agent_defs.py`.
> - `agent/special_agents.py` (§3.21q): lazy-loaded registry from config files.
> - `agent/enforcement.py` (§3.21u): no UI imports.
> - No new modules; no new CSS; no import cycles.

---

## 0. Summary

| # | Symptom | Fix |
|---|---------|-----|
| 1 | Agent YAMLs store both `provider` and `model` keys — two places to maintain model info | Replace `provider` key with `llm_name`. The user-entered provider card name is the single value. |
| 2 | Runtime resolves model via two-step `provider` → `providers.yaml` → `default_model` | `llm_name` names the provider card directly; runtime lookup is unchanged. |
| 3 | Legacy `provider` key on existing agent YAMLs breaks new code | Backward-compat: load path checks `llm_name` first, falls back to `provider` for existing agents. |

---

## 1. Overview

### 1.1 Problem statement

When a user creates an agent in the Agent Builder, they select a provider card by its display name (the `Name` field the user typed in the Settings dialog — e.g. `"MiniMax M3"`, `"Kimi K2.6"`). The system stores this as `provider` in the agent YAML, along with a separate `model` key (always empty for new agents, resolved at runtime from `providers.yaml`).

This dual-key storage is confusing: the user thinks in terms of *which model they want* (MiniMax M3, Kimi K2.6), not *which provider vendor* it came from. The `provider` key stores the provider's internal name (e.g. `"minimax"`), not the user-facing card name (e.g. `"MiniMax M3"`). The model is already resolved at runtime from `providers.yaml` using the provider name — so `model` in the YAML is redundant.

### 1.2 Solution summary

Rename `provider` to `llm_name` in the agent YAML. The value is the **user-entered display name** of the provider card (e.g. `"MiniMax M3"`), not an internal provider ID. At runtime, the system looks up `llm_name` in `providers.yaml` to get `base_url`, `default_model`, and `api_key`.

The `model` key is removed entirely from new agents. The runtime resolves the model from `providers.yaml` using the `llm_name` lookup.

### 1.3 Scope

| In scope | Out of scope |
|----------|--------------|
| Rename `provider` → `llm_name` in save path (`agent_builder.py`, `agent_defs.py`) | Changing the provider card schema in `providers.yaml` |
| Remove `model` key emission in save path | Multi-model-per-provider selection |
| Update load path for backward compat (`special_agents.py`, `agent_runtime_handler.py`) | Renaming provider cards in Settings (existing agents would break) |
| Update `validate_agent_def` to check `llm_name` | Agent deletion or migration of existing YAMLs |
| Update default agent YAMLs in `prompts/default_agents/` | Changing how the runtime resolves model at send-time |
| Update `SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` §2.1 and `SPEC_PER_AGENT_API_KEY.md` | |

---

## 2. Changes by File

### 2.1 `ui/views/agent_builder.py` — REVISED

**What changes:** `get_values()` emits `llm_name` instead of `provider`. The `model` key is not emitted.

**Current `get_values()` (lines 150–178):**

```python
def get_values(self) -> dict:
    name = self._name_entry.get_text().strip()
    role = self._role_entry.get_text().strip()
    emoji = self._emoji_entry.get_text().strip() or "🤖"
    provider = self._get_selected_provider_id()
    model = self._get_selected_model()
    prompts = self._get_selected_prompts()
    tools = self._get_selected_tools()
    mcp = self._get_selected_mcp_servers()
    si = self._get_self_improvement_config()
    return {
        "name": name,
        "role": role,
        "emoji": emoji,
        "provider": provider,      # → llm_name
        "model": model,            # → remove (empty anyway)
        "prompts": prompts,
        "tools": tools,
        "mcp_servers": mcp,
        "self_improvement": si,
    }
```

**After change:**

```python
def get_values(self) -> dict:
    name = self._name_entry.get_text().strip()
    role = self._role_entry.get_text().strip()
    emoji = self._emoji_entry.get_text().strip() or "🤖"
    llm_name = self._get_selected_provider_id()  # renamed — same value, semantically clearer
    prompts = self._get_selected_prompts()
    tools = self._get_selected_tools()
    mcp = self._get_selected_mcp_servers()
    si = self._get_self_improvement_config()
    return {
        "name": name,
        "role": role,
        "emoji": emoji,
        "llm_name": llm_name,
        "prompts": prompts,
        "tools": tools,
        "mcp_servers": mcp,
        "self_improvement": si,
    }
```

**Note:** `self._get_selected_provider_id()` is renamed to `self._get_selected_llm_name()` in the same change — same method body, only the name changes. This makes the view's public contract clearer.

**Verification grep (post-implementation):**

```bash
grep -n "provider_keys\|api_key" ui/views/agent_builder.py
# Expected: 0 matches (except in comments/docstrings)

grep -n "\.provider\b" ui/views/agent_builder.py
# Expected: 0 matches — no bare `.provider` reference in the view
```

### 2.2 `utils/agent_defs.py` — REVISED

**What changes:** `validate_agent_def()` checks `llm_name` instead of `provider`. `save_agent_def()` already strips `_`-prefixed keys — no change needed there.

**Current `validate_agent_def()` (lines 391–407):**

```python
def validate_agent_def(agent_def: dict) -> list[str]:
    errors = []
    if not agent_def.get("name"):
        errors.append("name is required")
    if not agent_def.get("provider"):
        errors.append("provider is required")
    # ... tool and prompt validation unchanged ...
    return errors
```

**After change:**

```python
def validate_agent_def(agent_def: dict) -> list[str]:
    errors = []
    if not agent_def.get("name"):
        errors.append("name is required")
    llm_name = agent_def.get("llm_name") or agent_def.get("provider")  # backward-compat
    if not llm_name:
        errors.append("llm_name is required")
    # ... tool and prompt validation unchanged ...
    return errors
```

**Backward-compat note:** The validation accepts either `llm_name` (new) or `provider` (legacy) so existing agent YAMLs on disk continue to validate during the transition. This is a temporary compat layer — new agents always write `llm_name`.

**Note on `load_agent_def_by_role()`:** Currently does `agent_def.get("provider")`. After change, check `llm_name` first, fall back to `provider`. Same pattern as `validate_agent_def`.

### 2.3 `agent/special_agents.py` — REVISED

**What changes:** `_load_registry()` reads `llm_name` from `agent_def`, falls back to `provider` for existing agents. `SpecialAgentDef.provider` field is replaced with `llm_name`.

**Current `SpecialAgentDef` dataclass (lines 58–74):**

```python
@dataclass SpecialAgentDef:
    conv_id_prefix, display_name, role, emoji, color, tools, can_write,
    provider: str | None, model: str | None,
    self_improvement: dict, mcp_servers: list[str],
    ...
```

**After change:**

```python
@dataclass SpecialAgentDef:
    conv_id_prefix, display_name, role, emoji, color, tools, can_write,
    llm_name: str | None,      # was: provider
    model: str | None,          # kept — runtime resolves at send-time
    self_improvement: dict, mcp_servers: list[str],
    ...
```

**Current `_load_registry()` (lines 100–137):**

```python
registry[session_key] = SpecialAgentDef(
    ...
    provider=agent_def.get("provider"),
    model=agent_def.get("model"),
    ...
)
```

**After change:**

```python
llm_name = agent_def.get("llm_name") or agent_def.get("provider")  # backward-compat

registry[session_key] = SpecialAgentDef(
    ...
    llm_name=llm_name,
    model=agent_def.get("model"),
    ...
)
```

**Why `model` is kept:** `SpecialAgentDef.model` is used by `agent_runtime_handler._resolve_agent_model()` to determine if an agent has a per-run override. New agents always have `model: ""` (empty), so the field is always empty in practice — but removing it requires changing `SpecialAgentDef`, which is a larger change. `model` is kept for now; the runtime lookup still works.

### 2.4 `ui/handlers/agent_runtime_handler.py` — VERIFIED (no change)

**Current `_resolve_agent_model()` (lines 256–290):**

```python
def _resolve_agent_model(self, agent_def: Any) -> str | None:
    provider = getattr(agent_def, "provider", None)
    model = getattr(agent_def, "model", None)
    # ... resolution logic ...
```

**After change:** `provider` becomes `llm_name`. The resolution logic is unchanged — it looks up the provider config by name and uses `default_model`. Since `SpecialAgentDef.llm_name` is the new field name and `agent_def` is a `SpecialAgentDef` instance (not a raw dict), the getattr call changes to `getattr(agent_def, "llm_name", None)`.

**After change:**

```python
def _resolve_agent_model(self, agent_def: Any) -> str | None:
    llm_name = getattr(agent_def, "llm_name", None) or getattr(agent_def, "provider", None)  # compat
    model = getattr(agent_def, "model", None)
    # ... rest unchanged ...
```

**Note:** The `or getattr(agent_def, "provider", None)` fallback is needed because existing `SpecialAgentDef` instances in memory may have been loaded before this change. New instances always have `llm_name`.

### 2.5 `ui/handlers/agent_builder_handler.py` — VERIFIED (no change)

`get_provider_options()` already returns provider dicts from `providers.yaml`. No change needed — the data source is `providers.yaml`, not the agent YAML field name.

### 2.6 Default agent YAMLs — REVISED

**Files:** `prompts/default_agents/coder.yaml`, `prompts/default_agents/debugger.yaml`, `prompts/default_agents/crabcakes.yaml`

**Current in `coder.yaml`:**

```yaml
provider: minimax
model: MiniMax-M2.7
```

**After change:**

```yaml
llm_name: MiniMax M3
model: ""
```

**Rule:** For default agents, `llm_name` is set to the user-facing display name of the provider card they are pre-configured to use. `model` is `""` (empty string) — resolved at runtime from `providers.yaml`.

**Note:** The `provider` key is removed. The `model` key is set to `""` explicitly (not omitted), to make it clear to future readers that model resolution is deferred to runtime.

### 2.7 Docs — REVISED

**Files updated:**
- `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` §2.1: `get_values()` returns `llm_name` not `provider`, `model` not emitted.
- `docs/specs/SPEC_PER_AGENT_API_KEY.md`: update references to `provider` field to `llm_name`.

---

## 3. Data Flow

### 3.1 User creates a new agent

```
User fills Agent Builder form → clicks Save
  → AgentBuilderDialog.get_values()
      → {"name": "...", "llm_name": "MiniMax M3", ...}
  → AgentBuilderHandler.save(agent_def)
      → validate_agent_def(agent_def) — checks llm_name exists
      → save_agent_def(agent_def) — strips _* keys, dumps to agents/<name>.yaml
```

### 3.2 Runtime resolves model at send-time

```
AgentRuntime._send(agent_name)
  → _resolve_agent_model(special_agent_def)
      → llm_name = getattr(agent_def, "llm_name")  # e.g. "MiniMax M3"
      → lookup "MiniMax M3" in providers.yaml → ProviderConfig
      → return f"{provider}/{prov_cfg.default_model}"  # e.g. "minimax/MiniMax-M2.7"
```

### 3.3 Load existing agent (backward-compat)

```
load_agent_defs() → yaml.load()
  → validate_agent_def(agent_def) — llm_name or provider accepted
  → _load_registry() — llm_name = agent_def.get("llm_name") or agent_def.get("provider")
  → SpecialAgentDef.llm_name set
```

---

## 4. File Change Summary

| File | Change type | Risk |
|------|------------|------|
| `ui/views/agent_builder.py` | Rename `provider` → `llm_name` in `get_values()`, rename `_get_selected_provider_id()` | Low |
| `utils/agent_defs.py` | Update `validate_agent_def()` and `load_agent_def_by_role()` to check `llm_name` first | Low |
| `agent/special_agents.py` | Rename `SpecialAgentDef.provider` → `llm_name`, update `_load_registry()` | Med — dataclass field rename |
| `ui/handlers/agent_runtime_handler.py` | Update `_resolve_agent_model()` getattr to `llm_name` | Low |
| `prompts/default_agents/coder.yaml` | Replace `provider`/`model` with `llm_name`/`model: ""` | Low |
| `prompts/default_agents/debugger.yaml` | Same | Low |
| `prompts/default_agents/crabcakes.yaml` | Same | Low |
| `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` | Update field references | Low |
| `docs/specs/SPEC_PER_AGENT_API_KEY.md` | Update field references | Low |

---

## 5. Implementation Order

Each step leaves the app in a working state.

1. **`agent/special_agents.py`** — add `llm_name` field to `SpecialAgentDef`, update `_load_registry()` with backward-compat. After: registry loads existing agents.
2. **`utils/agent_defs.py`** — update `validate_agent_def()` and `load_agent_def_by_role()` with backward-compat. After: validation accepts both keys.
3. **`ui/handlers/agent_runtime_handler.py`** — update `_resolve_agent_model()` to use `llm_name` with fallback. After: runtime resolves correctly.
4. **`ui/views/agent_builder.py`** — rename in `get_values()`, rename `_get_selected_provider_id()` → `_get_selected_llm_name()`. After: new agents save with `llm_name`.
5. **`prompts/default_agents/*.yaml`** — update default agents. After: fresh installs use new format.
6. **Docs** — update SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md and SPEC_PER_AGENT_API_KEY.md.

**Verification gate at each step:**
- 1: existing agent YAMLs load without validation error
- 2: `validate_agent_def({"name": "test", "llm_name": "x"})` passes; `{"name": "test", "provider": "x"}` also passes (backward-compat)
- 3: `_resolve_agent_model` resolves correctly for agents with `llm_name`
- 4: `get_values()` returns `llm_name` key, not `provider`
- 5: default agent YAMLs in new install use `llm_name`
- 6: spec docs match implementation

---

## 6. Acceptance Criteria

### 6.1 Functional

- [ ] `get_values()` returns `llm_name`, not `provider`. `model` key is not emitted.
- [ ] `validate_agent_def()` accepts agents with `llm_name` (new format) and with `provider` (legacy format).
- [ ] `load_agent_def_by_role()` resolves `llm_name` from the agent def (backward-compat: falls back to `provider`).
- [ ] `_resolve_agent_model()` uses `llm_name` to look up the provider in `providers.yaml`.
- [ ] Default agents (`coder.yaml`, `debugger.yaml`, `crabcakes.yaml`) use `llm_name` and `model: ""`.
- [ ] Existing agent YAMLs with `provider` key continue to load and function (backward-compat).
- [ ] Agent Builder Save enables when name + prompts + tools + provider (llm_name) are set.

### 6.2 Negative (regression prevention)

- [ ] `grep -n '"provider"' ui/views/agent_builder.py` returns 0 matches.
- [ ] `grep -n '"provider"' utils/agent_defs.py` returns 0 matches (except backward-compat `or agent_def.get("provider")`).
- [ ] `grep -n "provider: str" agent/special_agents.py` returns 0 matches.
- [ ] Existing `tests/test_agent_builder_dialog.py` and `tests/test_agent_builder_handler.py` pass.
- [ ] No new import cycles introduced.

### 6.3 Non-functional

- [ ] No new files created.
- [ ] No new CSS classes.
- [ ] No GTK imports added to `utils/` or `agent/` modules.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Agent YAML has neither `llm_name` nor `provider` | `validate_agent_def()` returns error: "llm_name is required" |
| Agent YAML has both `llm_name` and `provider` | `llm_name` takes precedence (new format wins) |
| Provider card named in `llm_name` was deleted from Settings | Runtime lookup fails; agent send fails with clear error. (Renames not in scope.) |
| `providers.yaml` is empty | Agent Builder dropdown shows "(no providers — open Settings)". Save disabled. |
| Existing agent YAML with `provider: "minimax"` loaded after change | `_load_registry()` reads `provider` via fallback, sets `llm_name` from it. Works. |

---

## 8. Relationship to Legacy Removal

This spec is independent of the `agent.json` `providers` fallback removal. That work targets `agent/config.py` and does not touch agent definition files. This spec only changes the field name within agent definition YAMLs (`agents/<name>.yaml`) and the code that reads/writes them.

Both specs can be implemented in either order without conflict.

---

**End of spec.**