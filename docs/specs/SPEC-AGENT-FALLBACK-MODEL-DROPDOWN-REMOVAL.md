# SPEC: Fallback Model Dropdown Removal — Unify Fallback UX with Primary Provider

**Date:** 2026-06-15
**Author:** Qaster (drafted for QTR implementation)
**Status:** Draft — for implementation
**Implements:** User clarification (2026-06-15): "I think the fallback provider should work the same way as the primary provider. That way the user experience is consistent. And also that way we know that the fallback provider is just a provider that has been set up in the settings. It has been tested and we know that it works."
**Depends on:**
- `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` (primary provider dropdown contract)
- `docs/specs/SPEC-KB-PROVIDER-PHASES.md` (per-agent fallback fields)
- `docs/ARCHITECTURE.md` §3.6 (composition root), §3.14, §9 (CSS)
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§3.6 (Composition root)** — `ui/window.py` owns dialog wiring. The fallback row visibility is toggled in `AgentBuilderDialog._update_fallback_visibility()`, which is called from `_on_provider_changed()`. No composition-root changes needed.
> - **§3.14 (Chat handler)** — unaffected. Chat rendering doesn't depend on the agent builder.
> - **§8 (utils/ rule)** — `utils/agent_defs.py` may drop `fallback_model` from `_normalize_fallback_fields()` after migration. `utils/providers_store.py` is unchanged.
> - **§9 (CSS)** — no new CSS classes. Existing dropdown styles are sufficient.
> - **No dead code** — this spec explicitly removes the fallback model dropdown widget, its state, its signal handler, and its serialization. After implementation, `grep` for the removed symbols returns zero matches.
> - **One provider card = one vetted model** — design principle carried over from SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md. The agent YAML stores provider names; the runtime resolves the model from `providers.yaml`.

---

## 0. Summary

| # | Symptom / Goal | Fix |
|---|----------------|-----|
| 1 | The Fallback Provider dropdown has a sibling Fallback Model dropdown that the primary Provider dropdown does not. The two providers behave differently even though they're both provider cards from `providers.yaml`. | Remove the Fallback Model dropdown. The Fallback Provider dropdown mirrors the primary's contract: select a provider card; runtime resolves the model from that card's `default_model`. |
| 2 | The agent YAML stores `fallback_model` as a free-form model string. This bypasses the "tested and vetted" guarantee of `providers.yaml`. | Drop `fallback_model` from the agent YAML schema. `fallback_provider` alone is stored. The runtime derives the model string the same way the primary path does. |
| 3 | Runtime resolution is asymmetric: primary uses `_resolve_agent_model()` (derives `f"{llm_name}/{default_model}"`), fallback uses `conv.fallback_model or conv.fallback_provider`. | Unify both paths on the primary's derivation. The fallback model's source of truth becomes the provider card, not the agent YAML. |
| 4 | Dead code: `_fallback_model_dropdown`, `_fallback_model_labeled`, the model-population branch in `_on_fallback_provider_changed`, the model-restoration loop in `_fill_form`, `_get_selected_fallback_model`, `fallback_model` in `get_values()`. | Remove all of it. `grep` returns zero matches after implementation. |

---

## 1. Overview

### 1.1 Problem statement

The Agent Builder dialog (`ui/views/agent_builder.py`) has two provider-selection widgets that behave inconsistently:

- **Primary Provider** (`_provider_dropdown`, line 334): selects a provider card. The model is implicit — resolved at runtime from the card's `default_model` via `AgentRuntimeHandler._resolve_agent_model()` (line 272-298).
- **Fallback Provider** (`_fallback_dropdown`, line 363) **+ Fallback Model** (`_fallback_model_dropdown`, line 369): selects a provider card AND a specific model string from that card.

The user has clarified (2026-06-15) the desired design:

> "If you just have to go to the settings and create a card for your fallback model, say your fallback model is Minimax M2.7. Your primary is Minimax M3. You just have to go create a card for the M2.7 and then test it so you know that it works and then you go back and just select the M2.7 in the fallback dropdown. ... If there's a reason for it to be different, I don't know what that is but I think we'll be able to redesign if we ever do come up and figure out what that reason is."

The framing is: **one provider card = one vetted model**. Selecting a card IS selecting a model. The "test connection" flow in Settings is the guarantee that the model works. The agent YAML should hold **identifiers** (provider names) — never model strings — so renaming or re-pointing a card in Settings propagates to all agents automatically.

### 1.2 Solution summary

1. Remove the Fallback Model dropdown widget and all its plumbing from `ui/views/agent_builder.py`.
2. Drop `fallback_model` from the agent YAML schema. On read, ignore it (no error). On write, never emit it. `_normalize_fallback_fields()` reduces to a single-line check.
3. Unify runtime fallback model resolution with the primary's derivation: `f"{conv.fallback_provider}/{default_model}"` from the provider card.
4. Update tests: drop `fallback_model` assertions from the new tests, keep the existing round-trip test updated to verify `fallback_model` is **not** serialized.

### 1.3 Scope

| In scope | Out of scope |
|---|---|
| Remove `_fallback_model_dropdown` widget and all references in `ui/views/agent_builder.py` | Settings dialog UI changes (already lets the user create one-card-per-model) |
| Remove `fallback_model` from `AgentBuilderDialog.get_values()` | `Conversation.fallback_model` dataclass field (kept for backward compat on disk; ignored on read) |
| Remove `fallback_model` from `AgentBuilderHandler.create_new()` template | `AgentConfig.fallback_model` global field (kept; only per-agent path is changed) |
| Drop `fallback_model` from `_normalize_fallback_fields()` (keep it as a no-op read for old YAML) | Per-agent API key handling (out of scope per SPEC-LLM-PROVIDER-SETTINGS-DIALOGUE.md) |
| Update `agent/runtime.py:_run_loop()` to derive fallback model from provider card | `kb_lookup` pre-fetch logic (unchanged) |
| Update `tests/test_agent_builder_fallback.py` to assert `fallback_model` is not stored | Synthesis prompt in `prompts/system/auxilium.md` (unchanged — model is opaque to the LLM) |
| Update `docs/ARCHITECTURE.md` §1370, §1485-1510 to drop `fallback_model` references | Migration script for old agent YAMLs (none needed — read path is tolerant) |

### 1.4 Architecture principles that apply (per `docs/ARCHITECTURE.md`)

- **§3.6 (Composition root)**: `ui/window.py` is the only place that wires `on_providers_changed` to the agent builder. The wiring already calls `set_provider_options()` on the dialog (verified at `ui/wiring.py:65-75`). No change needed.
- **§4 (Data flow)**: `Settings → providers.yaml → window._on_providers_changed → AgentBuilderDialog.set_provider_options() → fallback provider dropdown rebuilt`. Must remain traceable after the change.
- **§9 (CSS)**: no new CSS classes. Existing `agent-builder-*` styles apply to the remaining row.
- **No dead code**: this spec explicitly enumerates every removed symbol (see §6 Acceptance Criteria #8).
- **Migration safety**: the read path tolerates `fallback_model` in old YAML by ignoring it. No data loss. Old agents that relied on a specific `fallback_model` string will start using the provider card's `default_model` instead — this is the intended behavior and matches the new design.

---

## 2. Changes by File

### 2.1 `ui/views/agent_builder.py` — REVISED

**What changes:** Remove the Fallback Model dropdown widget, its label, the population branch in `_on_fallback_provider_changed`, the restoration loop in `_fill_form`, the `_get_selected_fallback_model` accessor, and the `fallback_model` field in `get_values()`.

**Symbols removed:**
- `_fallback_model_dropdown` (attribute, line 369)
- `_fallback_model_labeled` (attribute, line 371)
- The model-population block in `_on_fallback_provider_changed` (lines 405-414)
- `_get_selected_fallback_model` method (lines 434-447)
- The model-restoration loop in `_fill_form` (lines 748-753)
- `"fallback_model": self._get_selected_fallback_model() or None,` line in `get_values()` (line 180)

**Symbols kept (with new comment):**
- `_fallback_dropdown` (line 363) — unchanged
- `_fallback_labeled` (line 365) — unchanged
- `_fallback_providers` parallel list (line 385) — unchanged
- `_populate_fallback_provider_dropdown` (line 379) — unchanged
- `_on_fallback_provider_changed` (line 396) — **body simplified**: drop the model-population block. New body:

```python
def _on_fallback_provider_changed(self, dropdown, _param) -> None:
    """When fallback provider changes, refresh save button state.

    Model is resolved at runtime from the selected provider's default_model,
    matching the primary provider dropdown's contract. No sibling model
    dropdown is shown — one provider card = one vetted model.
    """
    self._update_save_button()
```

- `_get_selected_fallback_provider` (line 424) — unchanged
- `_build_fallback_provider_row` (line 353) — remove the model dropdown block (lines 368-372). New body:

```python
def _build_fallback_provider_row(self) -> Gtk.Box:
    """Build the fallback provider row.

    Visible only when the primary provider is local-kb.
    Includes a 'None' option (default). Model is resolved at runtime from
    the selected provider's default_model — no sibling model dropdown.
    """
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.set_hexpand(True)

    # Fallback provider dropdown
    self._fallback_dropdown = Gtk.DropDown(model=Gtk.StringList.new(["None"]))
    self._fallback_dropdown.connect("notify::selected", self._on_fallback_provider_changed)
    self._fallback_labeled = self._labeled_box("Fallback Provider", self._fallback_dropdown)
    row.append(self._fallback_labeled)

    # Initially hidden
    row.set_visible(False)

    return row
```

- `_update_fallback_visibility` (line 416) — unchanged
- `_fill_form` (line 710+): the **fallback provider restoration** stays (lines 738-746). The **fallback model restoration** is removed (lines 748-753). New restoration block:

```python
# Restore fallback provider if present
fb_provider = agent_def.get("fallback_provider")
if fb_provider:
    self._update_fallback_visibility()  # populates dropdown
    for i, p in enumerate(getattr(self, "_fallback_providers", [])):
        if p.name == fb_provider:
            self._fallback_dropdown.set_selected(i + 1)  # +1 for None offset
            break
```

- `get_values()` (line 165+): drop `"fallback_model"` from the returned dict. New dict (relevant fields only):

```python
return {
    "name": name,
    "emoji": emoji,
    "role": role,
    "prompts": prompts,
    "tools": tools,
    "llm_name": llm_name,
    "mcp_servers": self._get_selected_mcp_servers(),
    "self_improvement": self._get_si_config(tools),
    "fallback_provider": self._get_selected_fallback_provider() or None,
}
```

**`_provider_models` (line 311)**: this dict was built solely to feed the fallback model dropdown. After removal, it is unused. **Remove the assignment**:

```python
# REMOVE these lines from set_provider_options():
self._provider_models = {
    p.name: [(p.default_model, p.default_model)]
    for p in self._providers
    if p.default_model
}
```

Also remove the `__init__` initializer (line 54):
```python
self._provider_models: dict[str, list[tuple[str, str]]] = {}  # name → [(display, id), ...]
```

**Imports required:** none added; none removed.

**CSS classes:** none added; none removed.

**Line count estimate:** −60 lines (widget, signal handler, accessor, restoration loop, dict initialization, get_values field).

**CSS class verification:** `grep -n "agent-builder-fallback-model" /home/q/projects/crabcakes/ui/styles.py` should return zero matches. If any CSS rules exist for the model dropdown, remove them.

---

### 2.2 `ui/handlers/agent_builder_handler.py` — REVISED

**What changes:** Drop `fallback_model` from the `create_new()` template (line 71).

**New template (relevant fields only):**

```python
def create_new(self) -> dict:
    return {
        "name": "",
        "emoji": "🤖",
        "role": "",
        "prompts": [],
        "tools": ["read_file", "list_files", "search_files"],
        "provider": "",
        "model": "",
        "fallback_provider": None,
        "self_improvement": get_default_si_config(can_write=False),
    }
```

**Imports required:** none changed.

**Line count estimate:** −1 line.

**`save()` and `load_for_edit()`:** unchanged. They pass through whatever fields the dict contains.

---

### 2.3 `utils/agent_defs.py` — REVISED

**What changes:** Simplify `_normalize_fallback_fields()` to a no-op for `fallback_model` (kept for backward-read compat) or remove the line entirely. **Recommendation: remove the `fallback_model` line** — the agent YAML schema no longer includes it. Old YAMLs with `fallback_model` will have the key present in the loaded dict but it will be ignored by the consumer (`agent/runtime.py`).

**New `_normalize_fallback_fields()` (utils/agent_defs.py:33-42):**

```python
def _normalize_fallback_fields(data: dict) -> None:
    """Ensure fallback_provider key exists in the agent def dict.

    Reads from YAML/JSON if present, defaults to None if absent.
    Called after parsing every agent definition file.
    Note: fallback_model was removed in 2026-06-15 (see SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md).
    Old YAMLs with fallback_model retain the key in the loaded dict, but it is
    ignored by the runtime.
    """
    if "fallback_provider" not in data:
        data["fallback_provider"] = None
```

**`validate_agent_def()`:** unchanged. The function does not validate `fallback_model`.

**`save_agent_def()`:** unchanged. It writes whatever fields are in the dict. Since `get_values()` no longer emits `fallback_model`, the field is not written. (If a future caller adds `fallback_model` to the dict, it would be written — that's the existing behavior and acceptable.)

**`load_agent_def()` / `load_agent_defs()`:** unchanged. They call `_normalize_fallback_fields()` which now only checks `fallback_provider`. Old YAMLs with `fallback_model` will have the key in the returned dict, but no consumer reads it.

**`get_available_providers()`:** unchanged.

**Line count estimate:** −3 lines.

---

### 2.4 `agent/runtime.py` — REVISED

**What changes:** Update the fallback chain in `_run_loop()` to derive the model from the provider card, matching the primary path's derivation in `AgentRuntimeHandler._resolve_agent_model()`.

**Current code (line 1192):**
```python
fallback_model = conv.fallback_model or conv.fallback_provider
```

**New code (line 1192):**
```python
# Resolve fallback model the same way the primary path does:
#   f"{provider_name}/{provider.default_model}"
# See AgentRuntimeHandler._resolve_agent_model() at ui/handlers/agent_runtime_handler.py:272.
fallback_provider_name = conv.fallback_provider
fallback_provider_cfg = self._config.providers.get(fallback_provider_name) if fallback_provider_name else None
if fallback_provider_cfg and fallback_provider_cfg.default_model:
    default_model = fallback_provider_cfg.default_model
    if "/" in default_model:
        fallback_model = default_model
    else:
        fallback_model = f"{fallback_provider_name}/{default_model}"
else:
    # Provider not configured — fall back to provider name (runtime will error clearly)
    fallback_model = fallback_provider_name
```

**Why not just `conv.fallback_provider`:** because if the provider card's `default_model` already contains a `/` (e.g. `"minimax/MiniMax-M2.7"`), the resolved model should be that string, not `f"{provider}/{default_model}"` which would produce `"minimax/minimax/MiniMax-M2.7"`. This matches `_resolve_agent_model()`'s logic exactly (verified at `ui/handlers/agent_runtime_handler.py:289-295`).

**Imports required:** `LLMProviderConfig` is already imported via `self._config.providers` dict access. No new imports.

**Line count estimate:** +9 lines (replaces 1 line with 9 lines including comments).

**Backward compat for `conv.fallback_model`:** the `Conversation` dataclass field (`models/conversation.py:108`) is **kept** for disk-read tolerance. If a stale in-memory conversation has `fallback_model` set, the new derivation ignores it and uses the provider card instead. This is the intended behavior — the field is vestigial.

**`create_conversation()` (line 1014-1015):** the line `fallback_model=fallback_model or self._config.fallback_model,` is kept for now. It is a passthrough — if a future caller passes `fallback_model`, it lands on the `Conversation` but is ignored. The `fallback_model` **parameter** to `create_conversation()` is a candidate for removal in a follow-up spec; out of scope here to avoid scope creep.

---

### 2.5 `models/conversation.py` — UNCHANGED

**Why:** the `fallback_model` field stays on the dataclass. The new runtime code doesn't read it. Removing it would be a separate deprecation cycle and risks breaking in-flight conversations loaded from disk that have the field populated. **Defer field removal to a future spec** (when the field is provably unread everywhere).

**Note for follow-up:** `grep -n "fallback_model" /home/q/projects/crabcakes/agent/ /home/q/projects/crabcakes/ui/ /home/q/projects/crabcakes/models/ -r --include="*.py"` should return:
- `agent/runtime.py:1015` (the passthrough in `create_conversation`) — keep
- `models/conversation.py:108` (the field declaration) — keep
- All other matches should be zero after this spec lands.

---

### 2.6 `agent/special_agents.py` — UNCHANGED

**Why:** the `fallback_model` field on `SpecialAgentDef` (line 39) is loaded from the agent YAML by `_load_registry()` (line 124). After this spec, agent YAMLs no longer have `fallback_model`, so the field will always be `None` on the dataclass. The field is kept for backward-read tolerance. The runtime derivation ignores it. **Defer field removal to a future spec.**

**Note for follow-up:** `grep -n "fallback_model" /home/q/projects/crabcakes/agent/special_agents.py` should return one match (the field declaration) after this spec lands. The `_load_registry` line that copies it should be removed when the field is dropped.

---

### 2.7 `ui/handlers/agent_runtime_handler.py` — REVISED

**What changes:** Drop the `fallback_model` passthrough in the two call sites that pass it to `create_conversation()` and assign it on the in-memory `Conversation`.

**Current code (line 415-416, 432-433):**
```python
fallback_provider=agent_def.fallback_provider,
fallback_model=agent_def.fallback_model,
```

**New code (line 415-416):**
```python
fallback_provider=agent_def.fallback_provider,
# fallback_model removed in 2026-06-15 — runtime derives from provider card.
# See SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md.
```

**Current code (line 432-433):**
```python
conv.fallback_provider = agent_def.fallback_provider
conv.fallback_model = agent_def.fallback_model
```

**New code (line 432-433):**
```python
conv.fallback_provider = agent_def.fallback_provider
# conv.fallback_model assignment removed — see above.
```

**Line count estimate:** −2 lines (one each at the two sites), with comments explaining the removal.

**Why not also drop the `SpecialAgentDef.fallback_model` field:** out of scope. See §2.6.

---

### 2.8 `tests/test_agent_builder_fallback.py` — REVISED

**What changes:** Drop `fallback_model` assertions. Add a new test asserting `fallback_model` is **not** in the agent YAML after save.

**`TestHandlerCreateNew::test_create_new_includes_fallback_fields` (line 38-46):** rename and update to assert only `fallback_provider`:

```python
def test_create_new_includes_fallback_provider(self):
    """create_new() returns dict with fallback_provider (and no fallback_model)."""
    handler = AgentBuilderHandler()
    template = handler.create_new()
    assert "fallback_provider" in template
    assert template["fallback_provider"] is None
    assert "fallback_model" not in template
```

**`TestNormalizeFallbackFields` (line 49-62):** drop `test_preserves_existing_keys` (it asserts `fallback_model`). Add `test_ignores_fallback_model`:

```python
def test_adds_missing_provider_key(self):
    """_normalize_fallback_fields adds fallback_provider if missing."""
    d = {"name": "TestAgent"}
    _normalize_fallback_fields(d)
    assert "fallback_provider" in d
    assert d["fallback_provider"] is None


def test_preserves_existing_provider(self):
    """_normalize_fallback_fields preserves existing fallback_provider value."""
    d = {"name": "TestAgent", "fallback_provider": "openrouter"}
    _normalize_fallback_fields(d)
    assert d["fallback_provider"] == "openrouter"


def test_does_not_add_fallback_model(self):
    """_normalize_fallback_fields does not add fallback_model (removed in 2026-06-15)."""
    d = {"name": "TestAgent"}
    _normalize_fallback_fields(d)
    assert "fallback_model" not in d
```

**`TestYamlRoundTrip` (line 65-118):** drop all `fallback_model` assertions. Add `test_save_does_not_emit_fallback_model`:

```python
def test_save_does_not_emit_fallback_model(self, temp_config_dir):
    """save_agent_def() never writes fallback_model to the YAML file."""
    agent_def = {
        "name": "NoModel",
        "emoji": "🤖",
        "role": "nomodel",
        "prompts": ["system/auxilium.md"],
        "tools": ["read_file"],
        "llm_name": "openrouter",
        "fallback_provider": "openrouter",
        # NOTE: deliberately omitting fallback_model to verify it isn't auto-added
        "self_improvement": {},
    }

    filepath = save_agent_def(agent_def)

    # Read the raw file and assert fallback_model is not a key
    with open(filepath, encoding="utf-8") as f:
        raw = f.read()
    assert "fallback_model" not in raw
```

**`TestHandlerSaveLoad` (line 121-148):** drop `fallback_model` assertion. Keep the round-trip on `fallback_provider`.

**Backward-compat test (NEW):** verify that an old YAML with `fallback_model` still loads (the field is ignored, not errored on):

```python
def test_old_yaml_with_fallback_model_loads(self, temp_config_dir):
    """Old agent YAMLs with fallback_model load without error (field is ignored)."""
    import yaml
    agents_dir = temp_config_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    legacy_path = agents_dir / "legacy-agent.yaml"
    legacy_path.write_text("""
name: LegacyAgent
emoji: 🤖
role: legacy
prompts: [system/auxilium.md]
tools: [read_file]
llm_name: local-kb
fallback_provider: openrouter
fallback_model: openrouter/owl-alpha
self_improvement: {}
""")
    loaded = load_agent_def("LegacyAgent")
    assert loaded is not None
    assert loaded.get("fallback_provider") == "openrouter"
    # fallback_model is present in the dict but is now ignored by the runtime.
    # We don't assert on its presence/absence — the schema is tolerant on read.
```

---

### 2.9 `tests/test_runtime_fallback.py` — REVISED

**What changes:** Update `_make_runtime()` and `_setup_conversation()` to no longer pass `fallback_model` as a parameter to `AgentConfig` and `Conversation`. Update `TestFallbackOnOutOfScope` to assert the new derivation produces the expected model string.

**`_make_runtime()` (line 66-83):** drop the `fallback_model` parameter:

```python
def _make_runtime(fallback_provider=None):
    """Create an AgentRuntime with KB + optional fallback config."""
    providers = {
        "local-kb": _make_kb_provider_cfg(),
        "openrouter": _make_provider_cfg(),  # default_model = "openrouter/test-model"
    }
    config = AgentConfig(
        providers=providers,
        default_provider="local-kb",
        default_model="local-kb/local-kb",
        fallback_provider=fallback_provider,
        # fallback_model removed — runtime derives from provider card.
    )
    rt = AgentRuntime(config)
    rt.start()
    return rt
```

**`_setup_conversation()` (line 86-105):** drop the `fallback_model` assignment:

```python
def _setup_conversation(rt, session_key="test-session"):
    from models.conversation import Conversation
    conv = Conversation(
        agent_name="TestAgent",
        model="local-kb/local-kb",
        system_prompt="You are a test agent.",
        fallback_provider=rt._config.fallback_provider,
        # fallback_model removed — runtime derives from provider card.
    )
    rt._conversations[session_key] = conv
    return conv
```

**`TestFallbackOnOutOfScope` (line 110-133):** update to pass only `fallback_provider`:

```python
def test_fallback_on_out_of_scope(self):
    rt = _make_runtime(fallback_provider="openrouter")
    conv = _setup_conversation(rt)
    # ... rest unchanged
```

**NEW test — verify the runtime derives the model from the provider card, not from a stored string:**

```python
class TestFallbackModelDerivation:
    """The runtime derives the fallback model from the provider card's default_model."""

    def test_derives_from_provider_default_model(self):
        """When fallback_provider is set, the runtime uses that provider's default_model."""
        # openrouter provider has default_model="openrouter/test-model" (see _make_provider_cfg)
        rt = _make_runtime(fallback_provider="openrouter")
        conv = _setup_conversation(rt)

        captured_model = {"value": None}

        def mock_call_llm(session_key, messages, tools):
            captured_model["value"] = conv.model  # capture during the call
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _make_oob_response()
            return _make_normal_response("Fallback answer.")

        # ... exercise the fallback, assert captured_model["value"] == "openrouter/test-model"
```

**Line count estimate:** −4 lines (parameter removal at two sites), +20 lines (new derivation test).

---

### 2.10 `docs/ARCHITECTURE.md` — REVISED

**What changes:** Update four references to drop `fallback_model`.

**Line 1233** (Conversation dataclass summary):
```diff
- @dataclass Conversation: agent_name, project_path, system_prompt, messages, model, fallback_provider, fallback_model, created_at, total_tokens, total_cost, step_count
+ @dataclass Conversation: agent_name, project_path, system_prompt, messages, model, fallback_provider, created_at, total_tokens, total_cost, step_count
```

**Line 1323** (AgentConfig dataclass summary):
```diff
- @dataclass AgentConfig: providers, default_provider, default_model, max_tool_iterations, tool_timeout_seconds, auto_save_conversations, cost_limit, step_limit, enforcement, fallback_provider, fallback_model
+ @dataclass AgentConfig: providers, default_provider, default_model, max_tool_iterations, tool_timeout_seconds, auto_save_conversations, cost_limit, step_limit, enforcement, fallback_provider
```

**Line 1485-1486** (SpecialAgentDef summary):
```diff
-     fallback_provider: str | None,        # KB fallback provider (e.g. "openrouter")
-     fallback_model: str | None,           # KB fallback model (e.g. "openrouter/owl-alpha")
+     fallback_provider: str | None,        # KB fallback provider (e.g. "openrouter")
+     # fallback_model removed in 2026-06-15 — see SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md
```

**Line 1510** (per-agent model paragraph):
```diff
- **Per-agent model:** `llm_name` field specifies the provider card name for this agent (None → global default). `fallback_provider` and `fallback_model` specify the KB fallback — when the KB returns `[KB_OUT_OF_SCOPE]`, the runtime retries with this provider. Resolved in `AgentRuntimeHandler._resolve_agent_model()` and wired through `create_conversation()` → `Conversation` → runtime fallback chain.
+ **Per-agent model:** `llm_name` field specifies the provider card name for this agent (None → global default). `fallback_provider` specifies the KB fallback — when the KB returns `[KB_OUT_OF_SCOPE]`, the runtime retries with this provider. The model is derived from the selected provider card's `default_model` (same derivation as the primary path in `AgentRuntimeHandler._resolve_agent_model()`). Wired through `create_conversation()` → `Conversation` → runtime fallback chain. See `docs/specs/SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md`.
```

**Line 1370** (KB Provider integration paragraph): the sentence "per-agent `conv.fallback_provider`" stays. The reference to `conv.fallback_model` is implicit — no change needed because the sentence doesn't mention it.

**Line count estimate:** 4 small edits, no net line count change.

---

### 2.11 `prompts/default_agents/*.yaml` — UNCHANGED

**Why:** No default agents have `fallback_model` set (verified with `grep -l "fallback" prompts/default_agents/*.yaml` — zero matches). No migration needed.

---

### 2.12 Files NOT changed (already correct)

- `models/providers.py` — `ProviderConfig` dataclass is unchanged. The "one card = one model" principle is already encoded by the single `default_model` field.
- `utils/providers_store.py` — `load_providers()` and `save_providers()` are unchanged. They already round-trip a single `default_model` per card.
- `ui/wiring.py` — `on_providers_changed` already calls `set_provider_options()` on the agent builder. No change needed.
- `ui/handlers/settings_handler.py` — Settings dialog is unchanged. The "Add Provider" flow already creates one card per model.
- `agent/kb_lookup.py`, `agent/kb_server.py` — KB lookup is unchanged. The model is opaque to the LLM.
- `prompts/system/auxilium.md` — Synthesis prompt is unchanged. It only cares about the KB context, not the model identity.
- `models/conversation.py` — `fallback_model` field stays on the dataclass (backward-read tolerance). See §2.5.
- `agent/special_agents.py` — `fallback_model` field stays on the dataclass. See §2.6.

---

## 3. Data Flow

### 3.1 Agent creation (new agent, no fallback)

```
User clicks "+ Agent" in left panel
  → window._open_agent_builder(edit_name=None)
  → AgentBuilderHandler.create_new() returns dict with fallback_provider=None
  → AgentBuilderDialog(parent, handler, agent_def=template)
  → dialog.set_provider_options(handler.get_provider_options())
  → self._providers = [ProviderConfig("openai", ...), ProviderConfig("local-kb", ...), ...]
  → self._rebuild_provider_dropdown() → StringList of names
  → user picks "openai" (or whatever)
  → self._get_selected_llm_name() → "openai"
  → primary row visible, fallback row hidden (because primary != "local-kb")
  → user fills name/prompts/tools, clicks Save
  → self.get_values() returns:
      {
        "name": "...",
        "llm_name": "openai",
        "fallback_provider": None,
        "self_improvement": {...},
        ...
      }
  → AgentBuilderHandler.save(values) → save_agent_def(values) → YAML
```

**YAML output:**
```yaml
name: MyAgent
emoji: 🤖
role: myagent
prompts: [system/auxilium.md]
tools: [read_file, list_files, search_files]
llm_name: openai
fallback_provider: null
self_improvement: {}
```

Note: **no `fallback_model` key.**

### 3.2 Agent creation (KB agent with fallback)

```
User picks primary = "local-kb" in primary dropdown
  → self._on_provider_changed() fires
  → self._update_fallback_visibility() shows the fallback row
  → self._populate_fallback_provider_dropdown() builds the list (None + all non-KB providers)
  → user picks "openrouter" in fallback dropdown
  → self._on_fallback_provider_changed() fires
  → self._update_save_button() (no model-population branch anymore)
  → user clicks Save
  → self.get_values() returns:
      {
        ...
        "llm_name": "local-kb",
        "fallback_provider": "openrouter",
        ...
      }
  → save_agent_def(values) → YAML
```

**YAML output:**
```yaml
name: MyKBAgent
llm_name: local-kb
fallback_provider: openrouter
self_improvement: {}
```

### 3.3 Runtime fallback chain (when primary returns KB_OUT_OF_SCOPE)

```
AgentRuntime._run_loop(session_key, text) at agent/runtime.py:1100+
  → conv.to_api_messages() builds messages
  → kb_context = None; if conv.fallback_provider: kb_lookup(...)  [unchanged]
  → self._call_llm(session_key, messages, tools)  [primary call]
  → primary returns KB_OUT_OF_SCOPE
  → fallback chain at line 1183-1215 fires (conv._fallback_attempted guard)
  → original_model = conv.model  [save state]
  → NEW: derive fallback_model from provider card
      fallback_provider_name = conv.fallback_provider  # "openrouter"
      fallback_provider_cfg = self._config.providers.get("openrouter")
      if fallback_provider_cfg and fallback_provider_cfg.default_model:
          default_model = fallback_provider_cfg.default_model  # "openrouter/test-model"
          if "/" in default_model:
              fallback_model = default_model  # "openrouter/test-model"
          else:
              fallback_model = f"openrouter/{default_model}"
  → conv.model = fallback_model  [swap to fallback for the call]
  → self._call_llm(session_key, messages_with_context, tools)  [fallback call]
  → fallback response replaces text_content
  → finally: conv.model = original_model  [restore]
```

### 3.4 Edit existing agent (round-trip)

```
User clicks an agent in left panel → "Edit"
  → window._open_agent_builder(edit_name="LegacyAgent")
  → AgentBuilderHandler.load_for_edit("LegacyAgent") returns dict
  → AgentBuilderDialog(parent, handler, agent_def=loaded_dict)
  → dialog.set_provider_options(handler.get_provider_options())
  → self._fill_form(loaded_dict)
  → match loaded_dict["llm_name"] against self._providers, select in dropdown
  → match loaded_dict["fallback_provider"] (if present) against self._fallback_providers
  → (no model restoration — the field is gone)
  → user clicks Save
  → self.get_values() returns dict WITHOUT fallback_model
  → save_agent_def(values) overwrites the YAML
```

**Backward-compat behavior:** if the old YAML had `fallback_model: openrouter/owl-alpha`, the loaded dict will have that key, but it's ignored. The new YAML will not have it. Round-trip is lossy on the `fallback_model` field by design.

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `ui/views/agent_builder.py` | Remove model dropdown + plumbing | −60 | Low (UI only) |
| `ui/handlers/agent_builder_handler.py` | Remove from create_new template | −1 | Low |
| `utils/agent_defs.py` | Simplify _normalize_fallback_fields | −3 | Low (read-tolerant) |
| `agent/runtime.py` | New fallback model derivation | +9, −1 | Medium (touches the fallback chain) |
| `ui/handlers/agent_runtime_handler.py` | Drop fallback_model passthroughs | −2, +2 comments | Low |
| `tests/test_agent_builder_fallback.py` | Update assertions + new test | +20, −15 | Low |
| `tests/test_runtime_fallback.py` | Drop parameter + new derivation test | +20, −4 | Medium (validates runtime change) |
| `docs/ARCHITECTURE.md` | Update 4 references | ±0 | Low |
| **Total** | | **+23** | |

---

## 5. Implementation Order (Phases)

Each phase is independently testable. QTR's standard implementation loop applies (file-based instructions, sequential verification, see MEMORY.md for the delegation template).

### Phase 1: UI removal (`ui/views/agent_builder.py`)

**Files touched:** `ui/views/agent_builder.py`

**Tasks:**
1. Remove `_fallback_model_dropdown`, `_fallback_model_labeled` attributes (line 369, 371).
2. Remove the model-population block in `_on_fallback_provider_changed` (lines 405-414). Update the method's docstring to explain the unified contract.
3. Remove `_get_selected_fallback_model` method (lines 434-447).
4. Remove the model dropdown block in `_build_fallback_provider_row` (lines 368-372).
5. Remove the model-restoration loop in `_fill_form` (lines 748-753).
6. Remove `"fallback_model"` from `get_values()` (line 180).
7. Remove `self._provider_models` initialization in `__init__` (line 54).
8. Remove `self._provider_models` assignment in `set_provider_options` (line 311-314).
9. If `ui/styles.py` has any `agent-builder-fallback-model` CSS rules, remove them (`grep -n "fallback-model" /home/q/projects/crabcakes/ui/styles.py` first to confirm).

**Verification:**
```bash
grep -n "fallback_model\|_fallback_model_dropdown\|_fallback_model_labeled" ui/views/agent_builder.py
# Expected: zero matches
```

**Done when:** Agent Builder opens, primary dropdown works, fallback row appears when primary is `local-kb`, fallback dropdown shows providers, no model dropdown is visible, save produces YAML without `fallback_model`.

---

### Phase 2: Handler template + agent_defs simplification

**Files touched:** `ui/handlers/agent_builder_handler.py`, `utils/agent_defs.py`

**Tasks:**
1. Remove `"fallback_model": None,` from `create_new()` (line 71).
2. Simplify `_normalize_fallback_fields()` in `utils/agent_defs.py:33-42` to only check `fallback_provider`.
3. Add a comment in `_normalize_fallback_fields()` explaining that `fallback_model` was removed.

**Verification:**
```bash
grep -n "fallback_model" ui/handlers/agent_builder_handler.py utils/agent_defs.py
# Expected: zero matches
```

**Done when:** `create_new()` returns dict without `fallback_model` key. `_normalize_fallback_fields()` adds `fallback_provider` but not `fallback_model`.

---

### Phase 3: Runtime derivation

**Files touched:** `agent/runtime.py`, `ui/handlers/agent_runtime_handler.py`

**Tasks:**
1. Update `agent/runtime.py:1192` (the `fallback_model = conv.fallback_model or conv.fallback_provider` line) to derive from the provider card. See §2.4 for the exact code.
2. Drop the `fallback_model` passthrough in `ui/handlers/agent_runtime_handler.py:416` and `:433`.

**Verification:**
```bash
grep -n "fallback_model" agent/runtime.py ui/handlers/agent_runtime_handler.py
# Expected: zero matches in agent_runtime_handler.py
#           one match in agent/runtime.py at line 1015 (the create_conversation passthrough — out of scope)
```

**Done when:** `agent/runtime.py:_run_loop` derives `fallback_model` from `self._config.providers[conv.fallback_provider].default_model` (with the `/` handling). The `Conversation.fallback_model` field is no longer read.

---

### Phase 4: Tests

**Files touched:** `tests/test_agent_builder_fallback.py`, `tests/test_runtime_fallback.py`, `tests/test_kb_integration.py`

**Tasks:**
1. Update `tests/test_agent_builder_fallback.py` per §2.8.
2. Update `tests/test_runtime_fallback.py` per §2.9.
3. Update `tests/test_kb_integration.py::TestIntegrationRuntimeFallback::test_fallback_chain_end_to_end` — drop `fallback_model="openrouter/owl-alpha"` from the `AgentConfig` and `Conversation` constructors.

**Verification:**
```bash
cd /home/q/projects/crabcakes && python -m pytest tests/test_agent_builder_fallback.py tests/test_runtime_fallback.py tests/test_kb_integration.py -v 2>&1 | tail -60
# Expected: all tests pass, including the new derivation test
```

**Done when:** all targeted tests pass. New tests assert (a) `fallback_model` is not in `create_new()` output, (b) `fallback_model` is not written to YAML on save, (c) old YAMLs with `fallback_model` still load, (d) runtime derives fallback model from provider card.

---

### Phase 5: Documentation

**Files touched:** `docs/ARCHITECTURE.md`

**Tasks:**
1. Update line 1233 (Conversation summary).
2. Update line 1323 (AgentConfig summary).
3. Update line 1485-1486 (SpecialAgentDef summary).
4. Update line 1510 (per-agent model paragraph).

**Verification:**
```bash
grep -n "fallback_model" docs/ARCHITECTURE.md
# Expected: zero matches (or only in explicitly-commented "removed in 2026-06-15" notes)
```

**Done when:** ARCHITECTURE.md has no live references to `fallback_model` outside of historical deprecation notes.

---

### Phase 6: Final verification + post-mortem

**Tasks:**
1. Run the full test suite (or at least the agent + runtime + KB integration tests).
2. Run `git grep "fallback_model"` and confirm the remaining matches are only:
   - `models/conversation.py:108` (dataclass field, kept for backward-read)
   - `agent/special_agents.py:39` (dataclass field, kept for backward-read)
   - `agent/runtime.py:1015` (create_conversation passthrough, kept for caller compat)
   - `docs/specs/SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md` (this spec)
3. Write a post-mortem at `docs/post-mortems/2026-06-15-FALLBACK-MODEL-DROPDOWN-REMOVAL-POST-MORTEM.md` following the standard template (see `2026-06-14-KB-PROVIDER-PHASE-2-POST-MORTEM.md` for reference).

**Done when:** post-mortem is written, all targeted tests pass, `git grep` shows the expected remaining matches, and the spec is marked DONE in the frontmatter.

---

## 6. Acceptance Criteria

- [ ] **1.** Agent Builder dialog opens without a Fallback Model dropdown widget.
- [ ] **2.** Selecting `local-kb` as the primary provider shows the Fallback Provider dropdown (and only that).
- [ ] **3.** Saving an agent produces YAML without a `fallback_model` key (verified with `grep "fallback_model" <yaml-file>`).
- [ ] **4.** `AgentBuilderHandler.create_new()` returns a dict without a `fallback_model` key.
- [ ] **5.** `_normalize_fallback_fields()` adds `fallback_provider` but not `fallback_model` to a dict missing both.
- [ ] **6.** Old agent YAMLs containing `fallback_model: openrouter/owl-alpha` still load without error (the field is ignored).
- [ ] **7.** `agent/runtime.py:_run_loop` derives the fallback model from `self._config.providers[conv.fallback_provider].default_model` instead of from `conv.fallback_model`.
- [ ] **8.** `grep -rn "_fallback_model_dropdown\|_fallback_model_labeled\|_get_selected_fallback_model" /home/q/projects/crabcakes/` returns zero matches.
- [ ] **9.** `grep -rn "fallback_model" /home/q/projects/crabcakes/agent/ /home/q/projects/crabcakes/ui/ /home/q/projects/crabcakes/utils/agent_defs.py` returns only the kept sites (3 matches: `models/conversation.py:108`, `agent/special_agents.py:39`, `agent/runtime.py:1015`).
- [ ] **10.** `pytest tests/test_agent_builder_fallback.py tests/test_runtime_fallback.py tests/test_kb_integration.py` passes (paste full output in the post-mortem).
- [ ] **11.** `docs/ARCHITECTURE.md` has no live references to `fallback_model` outside of the kept dataclass fields and the deprecation note.
- [ ] **12.** No `agent-builder-fallback-model` CSS class remains in `ui/styles.py`.

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| User has an old agent YAML with `fallback_model: openrouter/owl-alpha` | Loads without error. `fallback_model` key is in the loaded dict but ignored. The runtime uses the `openrouter` provider card's `default_model` instead. |
| User has an old agent YAML with `fallback_model: <some-other-model>` that doesn't match the provider card's `default_model` | The stored `fallback_model` is ignored. The user sees the provider card's `default_model` as the fallback. If this differs from what the user expects, they should re-create the agent (or fix the provider card). |
| User has an agent YAML with only `fallback_provider` and no `fallback_model` | Works as before. The runtime derives the model from the provider card. |
| User picks `local-kb` as primary, no fallback provider selected | `fallback_provider` is `None` in the YAML. Runtime shows `KB_OUT_OF_SCOPE` sentinel (no fallback fires). |
| User picks `local-kb` as primary, `openrouter` as fallback, saves, then renames `openrouter` in Settings to `openrouter-prod` | On next fallback, the runtime looks up `openrouter` in `self._config.providers` and fails to find it. The derivation code at §2.4 falls through to `fallback_model = fallback_provider_name`, and the LLM call errors clearly. **Recommendation:** add a `WARNING` log when the provider lookup fails. **Implementation note:** defer the log addition to a follow-up; the spec's main concern is the derivation logic, not observability polish. |
| User picks `local-kb` as primary, then changes primary away from `local-kb` | Fallback row hides. Saved YAML still has the previous `fallback_provider` (if any). Next time primary becomes `local-kb` again, the row re-shows with the previous selection. |
| Two agents with the same `fallback_provider` pointing to different provider cards | Not possible — `fallback_provider` is a single string. If the user wants to share a fallback, they all reference the same card name. |
| `providers.yaml` has no `local-kb` card | Primary dropdown does not show `local-kb`. The fallback row's visibility logic is never triggered for non-KB primaries. No regression. |

---

## 8. ARCHITECTURE.md Updates Required

See §2.10. Four small edits, no structural changes.

---

## 9. Spec Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - The `_resolve_agent_model` reference at `ui/handlers/agent_runtime_handler.py:272-298` is verified — exact same derivation logic.
   - The `_on_fallback_provider_changed` body matches the current file at `ui/views/agent_builder.py:396-414`.
   - The `_build_fallback_provider_row` body matches `ui/views/agent_builder.py:353-374`.
   - The runtime derivation code at §2.4 is modeled on `_resolve_agent_model` and uses the same `/` handling.
   - The `Conversation` field at `models/conversation.py:108` is verified.
   - The `AgentConfig` field at `agent/config.py:82` is verified.
   - The `SpecialAgentDef` field at `agent/special_agents.py:39` is verified.

2. **Did I catch all exception types?**
   - `save_agent_def` raises `OSError` on file write — caught in `AgentBuilderHandler.save()` with a generic `Exception` handler.
   - `load_agent_def` returns `None` on parse failure (no exception).
   - `load_providers` returns `[]` on `OSError` and logs warning.
   - `_parse_agent_file` returns `None` on `json.JSONDecodeError` or `OSError` (or `ImportError` for yaml).
   - No new exception types introduced by this spec.

3. **Did I verify key structures?**
   - `Conversation` dataclass fields verified at `models/conversation.py:91-120`.
   - `AgentConfig` fields verified at `agent/config.py:65-83`.
   - `SpecialAgentDef` fields verified at `agent/special_agents.py:22-44`.
   - `LLMProviderConfig.default_model` field verified at `agent/config.py` (imported from models).
   - `ProviderConfig` fields verified at `models/providers.py:13-23`.

4. **Did I trace the data flow end-to-end?**
   - See §3 for the four main flows (create, create-with-fallback, runtime fallback, edit-roundtrip).
   - The runtime derivation at `agent/runtime.py:1192` is the only place the fallback model is computed; verified by reading the surrounding context.

5. **Would an implementer who follows this spec exactly produce working code?**
   - Yes, with the caveat that the implementer should run the verification commands at the end of each phase and paste the output in their report.
   - The spec references exact line numbers for the deletion sites — these are verified against the current `main` branch (commit `9a5505c`).

---

## 10. Risks and Follow-ups

### Risks

1. **Runtime regression risk** (Medium): the fallback chain at `agent/runtime.py:1183-1215` is the only consumer of `fallback_model`. Changing the derivation logic is a one-line behavioral change with broad implications. **Mitigation:** Phase 4's new derivation test catches regressions. The existing `test_fallback_chain_end_to_end` in `test_kb_integration.py` exercises the full path.

2. **Lost configuration on round-trip** (Low): users with old YAMLs containing `fallback_model` will see their `fallback_model` key disappear on the next save. The new behavior (use the provider card's `default_model`) is the intended design, but it's a behavior change. **Mitigation:** §7 documents the case. The KB Provider Phase 2 post-mortem noted that the `fallback_model` field was tested with the provider's `default_model` already (no users have a custom `fallback_model` set in their agents — verified by `grep -l "fallback" prompts/default_agents/*.yaml` returning zero matches).

3. **Inconsistent field retention** (Low): `models/conversation.py:108` and `agent/special_agents.py:39` still have `fallback_model` fields. They're never read by the new code, but they exist. **Mitigation:** the post-mortem flags this as a follow-up. Removing them is a separate deprecation cycle (1-2 phases) for the dataclasses only.

### Follow-ups (Tier 2+)

1. **Remove `Conversation.fallback_model` field** — requires a deprecation cycle for in-memory conversations that may have the field set. Defer to a future spec.
2. **Remove `SpecialAgentDef.fallback_model` field** — depends on #1. Also defer.
3. **Remove `create_conversation()` `fallback_model` parameter** — depends on #1. Also defer.
4. **Add a `WARNING` log when fallback provider card is not found in `self._config.providers`** — observability polish, not a correctness fix.
5. **Consider tightening the Settings dialog wording** — per the user's "tested and vetted" framing, the Settings dialog could add helper text like "Each card represents one tested model" to make the mental model explicit.
6. **Consider a "show only verified" filter on the provider dropdowns** — would make "tested and working" a hard guarantee rather than a convention. Not currently planned.

---

## 11. Sign-off

- [ ] Spec reviewed by Captain
- [ ] All 6 phases implemented and verified
- [ ] All acceptance criteria checked
- [ ] Post-mortem written
- [ ] Captain notified with summary
- [ ] Spec status updated to DONE in frontmatter
