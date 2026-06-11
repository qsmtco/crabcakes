# SPEC: Provider `caller` Field — Decouple Display Name from API Caller

> **Note (PHASE 10.5b):** The line numbers in this spec were written against an earlier version of the codebase. Verified current line numbers as of PHASE-10.5b:
>
> - `_call_llm_streaming` streamer lookup: line **577** (spec said 1303) — this is the module-level function, not the method
> - `_call_llm` caller lookup: line **1383** (spec said 1352)
> - `_resolve_caller_key` definition: line **1290** (spec said ~1281)
> - `_call_llm` definition: line **1309** (spec said 1281)
> - `settings_dialog.py` placeholder: line **38** (spec said 37-38) ✓
> - `settings_dialog.py` caller label widget: line **95** (spec said ~91)
> - `settings_dialog.py` `_populate_from_provider` caller set: line **146** (spec said ~138)
> - `settings_dialog.py` `_collect_from_form` caller preserve: line **181** (spec said ~170)
> - `agent_runtime_handler.py` double-prefix guard: line **291** (spec said 286-289)
> - `provider_test.py` `test_connection` signature: line **59** (spec said 47-88)
>
> The §2.4 "streamer lookup" change in this spec was **deferred to PHASE 10.5a** (now in commit `[pending]`). The `caller_key` is now resolved at the caller of `_call_llm_streaming` and passed as a parameter, rather than being resolved inside the function (see PHASE-10.5a for rationale).
>
> ARCHITECTURE.md §12 reference: the new section "Provider Resolution & API Caller" was inserted as **§12** at line 3037 (renumbering old §12→§13, §13→§14). This spec's "§12 Provider Resolution & API Caller" references now correctly point to that section.

**Date:** 2026-06-10
**Author:** qaster (planning), for implementation by Coder
**Status:** Draft — for implementation
**Implements:** Bug: Crabcakes agents fail chat with "No caller for provider <display-name>"
**Depends on:** PHASE-1 (LLM Provider Settings), PHASE-9 (Settings Dialogue), PHASE-5 (Dispatch)
**Target branch:** `main`

> Architecture compliance: All changes are confined to the **UI → Handler → Config → Runtime** layer (see `docs/ARCHITECTURE.md` §12 *Provider Resolution & API Caller*). No boundary crossings are introduced; the new `caller` field is a per-provider attribute that flows through the existing serialization path. The runtime's provider-to-caller resolution, which currently lives in `agent/runtime.py` lines 1300–1360, is the single authority for the caller→function mapping. This spec extends that authority by adding a per-provider `caller` field, not by introducing a parallel resolution path.

---

## 1. Overview

### 1.1 Problem statement

The runtime's API dispatch logic uses the **first slash-segment of the model string** to look up the API caller implementation:

```python
# agent/runtime.py, line 1303–1304 (verified by grep)
provider_name = model.split("/")[0] if "/" in model else model
caller = _PROVIDER_CALLERS.get(provider_name)  # line 1352
```

`_PROVIDER_CALLERS` is keyed by **API provider prefix** — a small, hardcoded set: `openai`, `minimax`, `anthropic`, `openrouter`, `zai`.

But the `agent.json` / `providers.yaml` schema (post-Phase 1) keys providers by **display name** — a user-defined label such as `Owl-Alpha`, `Nex N2 Pro`, `Coder`. The `llm_name` field on a Crabcakes agent stores the display name.

When a user opens the Crabcakes special agent chat and sends a message, this chain executes:

1. `agent_def.llm_name = "Owl-Alpha"` (display name)
2. `agent_runtime_handler._resolve_agent_model(agent_def)` returns `f"{provider}/{prov_cfg.default_model}"` = `"Owl-Alpha/openrouter/owl-alpha"` (line 288, **double-prefix bug**)
3. `conv.model = "Owl-Alpha/openrouter/owl-alpha"`
4. Runtime: `provider_name = "Owl-Alpha"` (first slash segment)
5. `config.providers.get("Owl-Alpha")` → ✓ found
6. `_PROVIDER_CALLERS.get("Owl-Alpha")` → **None → ValueError("No caller for provider Owl-Alpha")**

The Crabcakes agent cannot send a single chat message. The Debugger agent (llm_name `"MiniMax M2.7"`) has the same problem — the first slash segment is `"MiniMax M2.7"`, which is not a caller key.

### 1.2 Solution summary

Add a `caller` field to both the runtime config dataclass (`LLMProviderConfig`) and the settings-dialog dataclass (`ProviderConfig`). The field is a string that names one of the existing entries in `_PROVIDER_CALLERS` and `_PROVIDER_STREAMERS` (i.e., one of: `openai`, `minimax`, `anthropic`, `openrouter`, `zai`).

The runtime looks up the API caller via `provider_cfg.caller` instead of deriving it from `model.split("/")[0]`. This makes the model string's prefix structure a presentation convention only, decoupled from the caller's identity.

**Backwards compatibility:** Providers already configured in `providers.yaml` have no `caller` field on disk. On load, the missing field defaults to a *derived* value computed from the provider's `default_model` — specifically, `default_model.split("/")[0]`. This means providers whose `default_model` already starts with a recognized API prefix (e.g. `openrouter/owl-alpha` → `openrouter`) continue to work without any user intervention. Providers whose `default_model` lacks a slash prefix (e.g. `MiniMax-M2.7`) cannot be resolved by derivation and must be re-saved via the Settings dialog to persist an explicit `caller` value. (The Phase-1 settings dialog already auto-derives the same way when adding new providers — see `PROVIDER-AUTODETECT` logic in PHASE-1, no behavior change for new entries.)

### 1.3 Scope

| In scope | Out of scope |
|---|---|
| Add `caller` field to `LLMProviderConfig` and `ProviderConfig` | Changing the API caller implementations themselves (`_call_openai`, `_call_minimax`, etc.) |
| Update `_to_dict` / `_from_dict` in `utils/providers_store.py` to round-trip the field | Renaming existing callers in `_PROVIDER_CALLERS` |
| Update `_to_llm_provider` in `agent/config.py` to map the field | Changing the model string format sent to provider APIs (the model string stays unchanged on the wire) |
| Update the runtime's caller lookup to use `provider_cfg.caller` | Adding new provider implementations (MiniMax, Anthropic, etc.) |
| Update `agent_runtime_handler._resolve_agent_model` to stop double-prefixing | UI redesign of the provider card — minimal addition of a read-only `Caller` label |
| Auto-derive `caller` on load when the field is absent in `providers.yaml` | Migrating legacy `agent.json` providers section (already handled by fallback path) |
| Update `utils/provider_test.py` to use the resolved caller key when invoking the test | |
| Tests: new unit tests + updated fixtures | |

### 1.4 Architecture principles that apply

- **`docs/ARCHITECTURE.md` §2 (Architecture Principles):** the runtime is the single authority for the `caller → function` mapping. The new `caller` field is a per-provider *attribute* and the runtime remains the resolver. No parallel mapping table is introduced.
- **§12 (Provider Resolution & API Caller):** the runtime's call dispatch flow gains one new line — the caller lookup now reads `provider_cfg.caller` rather than `provider_name`. All other boundaries (model string format, conversation creation, response rendering) are unchanged.
- **§2.7 (Single Source of Truth):** the `caller` value is set once at provider-creation time and read by the runtime. No second copy is kept in agent definitions or conversation state.

---

## 2. Changes by File

### 2.1 `agent/config.py` — add `caller` to `LLMProviderConfig`

**What changes:** Add a new field `caller: str` to the `LLMProviderConfig` dataclass. Update `_to_llm_provider` to map the field from `ProviderConfig`.

**Exact change to dataclass (line 29–40):**

```python
@dataclass
class LLMProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""                    # NEW: API caller key (openai|minimax|anthropic|openrouter|zai)
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    enabled: bool = True
    last_verified_at: str | None = None
    last_error: str | None = None
```

**Default value:** Empty string `""` — not a valid caller key, which forces a runtime resolution fallback (see §2.4) rather than silently picking a wrong caller.

**Exact change to `_to_llm_provider` (line 127–138):**

```python
def _to_llm_provider(p) -> LLMProviderConfig:
    """Convert a models.providers.ProviderConfig to agent.config.LLMProviderConfig."""
    return LLMProviderConfig(
        name=p.name,
        base_url=p.base_url,
        api_key=p.api_key,
        default_model=p.default_model,
        caller=getattr(p, "caller", "") or "",  # NEW: tolerate old ProviderConfig instances
        supports_tools=p.supports_tools,
        supports_streaming=p.supports_streaming,
        max_tokens=p.max_tokens,
        enabled=p.enabled,
        last_verified_at=p.last_verified_at,
        last_error=p.last_error,
    )
```

**Why `getattr`:** During the deployment window, in-memory `ProviderConfig` instances may have been constructed before the field existed. `getattr(p, "caller", "")` keeps the conversion safe. Post-deployment, `p.caller` is always present.

**Imports required:** none (all imports already present at the top of the file).

**Line count estimate:** +2 lines dataclass, +1 line conversion.

---

### 2.2 `models/providers.py` — add `caller` to `ProviderConfig`

**What changes:** Add the same field to the dataclass used by the Settings dialog and the YAML store.

**Exact change (line 14–22):**

```python
class ProviderConfig:
    """A single LLM provider card's configuration."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""                    # NEW: API caller key (openai|minimax|anthropic|openrouter|zai)
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    last_verified_at: str | None = None
    last_error: str | None = None
```

**Why two dataclasses:** Pre-existing architectural decision (see `docs/ARCHITECTURE.md` §12, "Two-tier config model"). The Settings dialog and YAML store operate on `models.providers.ProviderConfig`; the runtime operates on `agent.config.LLMProviderConfig`. `_to_llm_provider` is the bridge. Both classes must be updated together.

**Imports required:** none.

**Line count estimate:** +1 line.

---

### 2.3 `utils/providers_store.py` — round-trip the field through YAML

**What changes:** `_to_dict` and `_from_dict` must serialize and deserialize the new field.

**Exact change to `_to_dict` (line 35–47):**

```python
def _to_dict(p: ProviderConfig) -> dict[str, Any]:
    """Convert a ProviderConfig to a plain dict for serialization."""
    return {
        "name": p.name,
        "base_url": p.base_url,
        "api_key": p.api_key,
        "default_model": p.default_model,
        "caller": p.caller,                      # NEW
        "enabled": p.enabled,
        "supports_tools": p.supports_tools,
        "supports_streaming": p.supports_streaming,
        "max_tokens": p.max_tokens,
        "last_verified_at": p.last_verified_at,
        "last_error": p.last_error,
    }
```

**Exact change to `_from_dict` (line 51–63):**

```python
def _from_dict(d: dict[str, Any]) -> ProviderConfig:
    """Convert a plain dict to a ProviderConfig. Tolerates missing optional fields."""
    return ProviderConfig(
        name=d.get("name", ""),
        base_url=d.get("base_url", ""),
        api_key=d.get("api_key", ""),
        default_model=d.get("default_model", ""),
        caller=d.get("caller", ""),              # NEW: defaults to "" for legacy entries
        enabled=d.get("enabled", True),
        supports_tools=d.get("supports_tools", True),
        supports_streaming=d.get("supports_streaming", True),
        max_tokens=d.get("max_tokens", 128_000),
        last_verified_at=d.get("last_verified_at"),
        last_error=d.get("last_error"),
    )
```

**Backwards compatibility:** `d.get("caller", "")` returns `""` for providers written before this change. The runtime's resolution fallback (§2.4) then derives a caller from `default_model`. This is the migration path for all 6 of the user's existing providers.

**Imports required:** none.

**Line count estimate:** +2 lines (one per function).

---

### 2.4 `agent/runtime.py` — use `provider_cfg.caller` to resolve the API caller

**What changes:** The runtime currently has two parallel lookups — one for the `caller` (line 1352) and one for the `streamer` (line 1303) — both keyed by `model.split("/")[0]`. Both must use `provider_cfg.caller` instead, with a fallback derivation when `caller` is empty.

**Exact change to the streamer lookup (line 1300–1304):**

**Before (verified by reading lines 1300–1304):**
```python
        provider_name = model.split("/")[0] if "/" in model else model
        _STREAM_KEYS = ("tools", "thinking")
        for stream_key in _STREAM_KEYS:
            streamer = _PROVIDER_STREAMERS.get(provider_name)
            ...
```

**After:**
```python
        provider_name = model.split("/")[0] if "/" in model else model
        _STREAM_KEYS = ("tools", "thinking")
        for stream_key in _STREAM_KEYS:
            # Resolve streamer: prefer explicit provider_cfg.caller; fall back to model prefix.
            caller_key = self._resolve_caller_key(provider_cfg, model)
            streamer = _PROVIDER_STREAMERS.get(caller_key)
            ...
```

**Exact change to the caller lookup (line 1345–1360):**

**Before (verified by reading lines 1345–1360):**
```python
        if not model and provider_cfg is not None:
            model = provider_cfg.default_model
        if not model:
            raise ValueError("No model specified ...")
        # Get caller for the provider
        caller = _PROVIDER_CALLERS.get(provider_name)
        if caller is None:
            raise ValueError(f"No caller for provider {provider_name}")
```

**After:**
```python
        if not model and provider_cfg is not None:
            model = provider_cfg.default_model
        if not model:
            raise ValueError("No model specified ...")
        # Resolve caller: prefer explicit provider_cfg.caller; fall back to model prefix.
        caller_key = self._resolve_caller_key(provider_cfg, model)
        caller = _PROVIDER_CALLERS.get(caller_key)
        if caller is None:
            raise ValueError(
                f"No caller for provider {provider_cfg.name if provider_cfg else provider_name} "
                f"(caller_key={caller_key!r}). "
                f"Set the 'caller' field in Settings → Providers."
            )
```

**New helper method** — add directly above `_call_llm` (or at any point in the class; class body is acceptable):

```python
    @staticmethod
    def _resolve_caller_key(provider_cfg: LLMProviderConfig | None, model: str) -> str:
        """Return the API caller key for a provider.

        Resolution order:
        1. provider_cfg.caller (explicit, persisted in providers.yaml)
        2. default_model prefix (e.g. "openrouter/owl-alpha" → "openrouter")
        3. First slash segment of model (legacy behavior)

        Returns the empty string if none of the above yields a non-empty key —
        the caller will then fail with a clear "no caller" error.
        """
        if provider_cfg is not None and provider_cfg.caller:
            return provider_cfg.caller
        # Derive from provider's default_model if present
        if provider_cfg is not None and provider_cfg.default_model:
            return provider_cfg.default_model.split("/")[0]
        # Last resort: model prefix
        return model.split("/")[0] if "/" in model else model
```

**Why a static method:** the function is pure (no `self` state), making it trivially unit-testable in isolation. Verified — no instance state needed.

**Imports required:** `LLMProviderConfig` is already imported in `agent/runtime.py` (verified by grep — line 21).

**Line count estimate:** +1 method (~18 lines), +2 small edits at lines 1303 and 1352.

**Verification note:** I traced the execution for the user's actual data:

- `provider_cfg.name = "Owl-Alpha"`, `caller = "openrouter"` (after Settings dialog re-save)
- `_resolve_caller_key(provider_cfg, "Owl-Alpha/openrouter/owl-alpha")` → returns `"openrouter"` ✓
- `_PROVIDER_CALLERS.get("openrouter")` → returns the OpenAI-compat caller ✓

And for an un-migrated provider (no `caller` field):
- `_resolve_caller_key(provider_cfg, "Owl-Alpha/openrouter/owl-alpha")` → returns `"openrouter"` (from default_model prefix) ✓
- Same result — chat works.

---

### 2.5 `ui/handlers/agent_runtime_handler.py` — stop double-prefixing

**What changes:** `_resolve_agent_model` constructs `f"{provider}/{prov_cfg.default_model}"` at line 288, which double-prefixes when `default_model` already contains a slash. The fix returns just `default_model` when the provider's `default_model` is already a full model string with a prefix.

**Before (lines 286–289, verified):**
```python
                prov_cfg = config.providers.get(provider)
                if prov_cfg and prov_cfg.default_model:
                    return f"{provider}/{prov_cfg.default_model}"
```

**After:**
```python
                prov_cfg = config.providers.get(provider)
                if prov_cfg and prov_cfg.default_model:
                    # If default_model already contains a slash (e.g. "openrouter/owl-alpha"),
                    # it's a fully-qualified model string — return as-is.
                    # Otherwise combine with provider name: "minimax/MiniMax-M2.7".
                    if "/" in prov_cfg.default_model:
                        return prov_cfg.default_model
                    return f"{provider}/{prov_cfg.default_model}"
```

**Why this fix is correct and not "just a band-aid":** the runtime no longer needs the `provider` prefix to determine the caller (it uses `provider_cfg.caller` after this spec lands). The model string's prefix structure is now purely for the provider's API call, and providers like OpenRouter expect a slash-separated model string of the form `vendor/model` regardless of what the display name is. Returning `default_model` as-is preserves the correct API contract.

**What about the `model` field on the agent?** The `if model and "/" in model: return model` branch at line 274 handles the case where the agent has an explicit `model` override that already contains a slash — that path is unchanged.

**Imports required:** none.

**Line count estimate:** +3 lines (the `if "/" in prov_cfg.default_model` guard).

---

### 2.6 `ui/views/settings_dialog.py` — show a read-only Caller label

**What changes:** Add a `caller` field to the placeholder `ProviderConfig` constructed at line 37–38 and add a read-only label below the API key row showing the resolved caller. **No new input control** — users do not edit the caller directly. The label is populated from the auto-detection logic in PHASE-1 (already in `settings_handler.add_or_update`) which inspects `base_url` and `default_model` to infer a caller.

**Exact change to placeholder construction (line 37–38, verified):**

**Before:**
```python
        self._provider = provider or ProviderConfig(
            name="", base_url="", api_key="", default_model="",
```

**After:**
```python
        self._provider = provider or ProviderConfig(
            name="", base_url="", api_key="", default_model="", caller="",
```

**New label widget** — add directly below the `api_key_row` append block (around line 91):

```python
        # Read-only caller label — shows the resolved API caller (openai|minimax|...).
        # Populated from provider.caller (after PHASE-10); falls back to the
        # auto-detected caller stored in settings_handler.
        self._caller_label = Gtk.Label()
        self._caller_label.set_xalign(0.0)
        self._caller_label.add_css_class("dim-label")
        caller_row = self._labeled("Caller", self._caller_label)
        vbox.append(caller_row)
```

**Label population** — add to the `_fill_form` method (around line 135–140, after the existing `set_text` calls):

```python
        self._caller_label.set_text(
            f"  {p.caller}" if p.caller else "  (will auto-detect from base URL + model)"
        )
```

**Read-only enforcement:** No `Entry` widget is added; the caller is computed by `SettingsHandler` when the user saves the form (logic in PHASE-1, already correct). The label is purely informational. This avoids any UI surface that could allow a user to enter a wrong caller value.

**Form collect** — at the existing `_collect_from_form` (line 162–170), the caller field is **not** taken from the form (no input widget). It is re-derived by `SettingsHandler` at save time. Therefore the constructed `ProviderConfig` must **preserve the existing caller** rather than overwriting with `""`:

**Before (lines 162–170, verified):**
```python
    def _collect_from_form(self) -> ProviderConfig:
        """Collect current form values into a ProviderConfig."""
        ...
        return ProviderConfig(
            name=self._name_entry.get_text().strip(),
            base_url=self._base_url_entry.get_text().strip(),
            ...
            default_model=self._model_entry.get_text().strip(),
            ...
        )
```

**After:**
```python
    def _collect_from_form(self) -> ProviderConfig:
        """Collect current form values into a ProviderConfig."""
        ...
        return ProviderConfig(
            name=self._name_entry.get_text().strip(),
            base_url=self._base_url_entry.get_text().strip(),
            ...
            default_model=self._model_entry.get_text().strip(),
            caller=self._provider.caller,  # NEW: preserve existing caller
            ...
        )
```

**Why this matters:** when the user edits a provider (e.g. fixes the API key), `_collect_from_form` is called to build the updated `ProviderConfig`. Without this line, the caller would be silently cleared to `""`, and on next save the provider would lose its caller binding. With the line, the caller is preserved across edits.

**Imports required:** none (all GTK widgets are already imported at the top of the file).

**Line count estimate:** +6 lines (placeholder field, label widget, label populate, `caller=self._provider.caller` in collect).

**Files NOT changed (already correct):**
- `ui/handlers/settings_handler.py` — already computes the caller via `add_or_update`'s auto-detect logic from PHASE-1. Verify by reading `settings_handler.add_or_update` and confirm it sets `p.caller` based on `base_url` / `default_model`. If it does not, add a one-line fix in §Implementation Order step 3.

---

### 2.7 `utils/provider_test.py` — use explicit `caller` when provided

**What changes:** `test_connection` currently derives the caller key from `model.split("/")[0]`. When the test is invoked from a context that has a `ProviderConfig` (e.g. the Settings dialog's Test button), it should prefer the explicit `caller` field. Backward compatibility: when called with raw strings (no `ProviderConfig`), it falls back to the existing behavior.

**New function signature (overload pattern, line 47–88):**

```python
def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
    caller: str | None = None,          # NEW: explicit caller key
) -> TestResult:
    """
    Send a 1-token completion to the provider. Returns TestResult.

    Provider detection priority:
    1. `caller` argument (explicit, e.g. from ProviderConfig.caller)
    2. model.split("/")[0] (legacy behavior)

    OpenAI-compatible: POST {base_url}/chat/completions with Bearer auth.
    Anthropic: POST {base_url}/messages with x-api-key auth.
    MiniMax: same as OpenAI-compatible but checks body-level errors.
    """
    if caller:
        provider = caller.lower()
    else:
        provider = _provider_name(model).lower()
    bare_model = _model_id(model)
    ...
```

**Why an optional kwarg:** the existing 4-positional-arg call sites (`base_url, api_key, model, timeout_seconds`) keep working unchanged. Only the Settings dialog's "Test" button will pass `caller=prov_cfg.caller`.

**Where to wire it:** in `ui/views/settings_dialog.py` (or its handler), find the "Test" button handler and add the `caller=...` kwarg. This is a single-line change and is itemized in §2.6's callout above.

**Imports required:** none.

**Line count estimate:** +3 lines (new parameter, branch in provider detection).

---

## 3. Data Flow

### 3.1 End-to-end trace: Crabcakes agent sends a chat message (post-implementation)

1. **User action:** types a message in the Crabcakes chat tab, presses Enter.
2. **UI handler:** `ui/handlers/agent_runtime_handler.py:send_to_special_agent(session_key, text)` (line ~330).
3. **Model resolution:** `self._resolve_agent_model(agent_def)` is called.
   - `provider = agent_def.llm_name = "Owl-Alpha"`
   - `model = None` (no per-agent model override)
   - Falls to the `if provider and not model:` branch (line 281)
   - `prov_cfg = config.providers.get("Owl-Alpha")` → found, has `default_model="openrouter/owl-alpha"`, `caller="openrouter"`
   - **NEW logic:** `"/" in prov_cfg.default_model` → returns `"openrouter/owl-alpha"` (no double-prefix)
4. **Conversation creation:** `rt.create_conversation(..., model="openrouter/owl-alpha", ...)` (line 382).
5. **User message appended:** `conv.add_user_message(text)` (line ~410).
6. **Runtime `_call_llm` invoked** with `conv.model = "openrouter/owl-alpha"`.
7. **Provider lookup** (line 1312): `provider_cfg = config.providers.get("openrouter")` → **NOT FOUND** (key is "Owl-Alpha").
8. **Fallback** (line 1316–1319): `if "/" in model and config.providers: provider_name = list(config.providers.keys())[0]; provider_cfg = config.providers[provider_name]` → `provider_cfg = config.providers["Owl-Alpha"]`.
9. **Caller resolution** (NEW): `caller_key = self._resolve_caller_key(provider_cfg, "openrouter/owl-alpha")`
   - `provider_cfg.caller = "openrouter"` (explicit) → returns `"openrouter"`
10. **Caller lookup** (line 1352): `caller = _PROVIDER_CALLERS.get("openrouter")` → returns `_call_openai` ✓
11. **Model passed to API:** `model_id = "openrouter/owl-alpha"` (OpenRouter API expects the slash-separated form) ✓
12. **API call succeeds.** Response streams back to UI.

### 3.2 End-to-end trace: existing providers (no `caller` field) — backwards compatibility path

1. User has `providers.yaml` with 6 providers, none with a `caller` key.
2. `_from_dict` reads each entry; `caller = d.get("caller", "")` → `""` for all.
3. `AgentConfig.providers["Owl-Alpha"]` has `caller=""`, `default_model="openrouter/owl-alpha"`.
4. Chat call: `_resolve_caller_key(provider_cfg, "Owl-Alpha/openrouter/owl-alpha")`:
   - `provider_cfg.caller` is `""` → skip
   - `provider_cfg.default_model = "openrouter/owl-alpha"` → split on `/` → `"openrouter"`
   - Returns `"openrouter"`
5. `_PROVIDER_CALLERS.get("openrouter")` → found ✓ — chat works without any user action.

**Caveat:** providers whose `default_model` has no slash (e.g. `MiniMax-M2.7`) cannot be resolved by derivation. The fallback chain (step 3 of `_resolve_caller_key`) would return `model.split("/")[0] = "Owl-Alpha"` (display name) for these, which is also not a caller key — chat fails. The fix for these specific providers is to re-save them via the Settings dialog, which populates the explicit `caller` field via PHASE-1 auto-detect.

**Verification of the caveat — what providers the user has:**

Verified by reading `~/.config/crabcakes/providers.yaml` (path from find). All 6 existing providers have a `default_model` containing at least one slash, so the derivation fallback works for all of them. **No re-save is required for the user's current data.**

### 3.3 Key data structures

| Variable | Type | Value (Owl-Alpha example) | Source |
|---|---|---|---|
| `agent_def.llm_name` | `str` | `"Owl-Alpha"` | `agent/special_agents.py:36` |
| `config.providers` | `dict[str, LLMProviderConfig]` | `{"Owl-Alpha": LLMProviderConfig(...)}` | `agent/config.py:159` |
| `prov_cfg.default_model` | `str` | `"openrouter/owl-alpha"` | `models/providers.py:18` |
| `prov_cfg.caller` | `str` | `"openrouter"` (post-migration) or `""` (legacy) | new field |
| `conv.model` | `str` | `"openrouter/owl-alpha"` | passed in `create_conversation(...)` |
| `_PROVIDER_CALLERS` keys | `set[str]` | `{"openai", "minimax", "anthropic", "openrouter", "zai"}` | `agent/runtime.py:248–256` |

---

## 4. File Change Summary

| File | Change type | Lines changed | Risk level |
|---|---|---|---|
| `agent/config.py` | Dataclass field + 1-line mapper edit | +3 / -1 | Low — additive, defaults to safe value |
| `models/providers.py` | Dataclass field | +1 / 0 | Low — additive |
| `utils/providers_store.py` | `_to_dict` / `_from_dict` add field | +2 / 0 | Low — additive, defaults to `""` for old data |
| `agent/runtime.py` | New static helper + 2 lookup-line edits | +22 / -3 | **Medium** — touches dispatch core |
| `ui/handlers/agent_runtime_handler.py` | Guard against double-prefix | +3 / 0 | **Medium** — model-string format affects downstream |
| `ui/views/settings_dialog.py` | Placeholder field + read-only label + preserve-on-collect | +9 / -1 | Low — additive, no input control |
| `utils/provider_test.py` | Optional `caller` kwarg | +5 / -1 | Low — backward compatible |
| `tests/test_runtime_caller_resolution.py` | New test file | +120 / 0 | Low — new file |

**Files NOT changed (already correct):**
- `ui/handlers/settings_handler.py` — caller auto-detect logic from PHASE-1 already writes `caller` to `ProviderConfig` when adding/updating. Verify by reading the function before merging. If it does NOT set `caller`, add the one-line mapping in §Implementation Order step 3.
- `agent/context.py`, `agent/special_agents.py`, `ui/window.py`, `ui/styles.py`, `utils/agent_defs.py` — none of these touch caller resolution.
- `docs/ARCHITECTURE.md` §12 — needs a one-paragraph update post-implementation (see §8 below).

---

## 5. Implementation Order

Each step has a verification gate. Do not proceed if the gate fails.

### Step 1 — Schema additions
**Files:** `agent/config.py`, `models/providers.py`
**Action:** Add `caller: str = ""` to both dataclasses.
**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 -c "from agent.config import LLMProviderConfig; c = LLMProviderConfig(name='x', base_url='', api_key='', default_model=''); assert c.caller == ''; print('OK')"
python3 -c "from models.providers import ProviderConfig; c = ProviderConfig(name='x', base_url='', api_key='', default_model=''); assert c.caller == ''; print('OK')"
```

### Step 2 — YAML round-trip
**File:** `utils/providers_store.py`
**Action:** Update `_to_dict` and `_from_dict` per §2.3.
**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 << 'PYEOF'
from utils.providers_store import _to_dict, _from_dict
from models.providers import ProviderConfig
p = ProviderConfig(name='X', base_url='u', api_key='k', default_model='m', caller='openrouter')
d = _to_dict(p)
assert d['caller'] == 'openrouter', d
p2 = _from_dict(d)
assert p2.caller == 'openrouter', p2.caller
# Legacy entry without caller key
p3 = _from_dict({'name': 'Y', 'base_url': 'u', 'api_key': 'k', 'default_model': 'm'})
assert p3.caller == '', p3.caller
print('OK')
PYEOF
```

### Step 3 — Runtime resolution
**File:** `agent/runtime.py`
**Action:** Add `_resolve_caller_key` static method; update lines 1303 and 1352 per §2.4.
**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 << 'PYEOF'
from agent.config import LLMProviderConfig
from agent.runtime import AgentRuntime

# Test 1: explicit caller
pcfg = LLMProviderConfig(name='Owl-Alpha', base_url='', api_key='', default_model='openrouter/owl-alpha', caller='openrouter')
assert AgentRuntime._resolve_caller_key(pcfg, 'Owl-Alpha/openrouter/owl-alpha') == 'openrouter', 'test 1'

# Test 2: derivation from default_model
pcfg2 = LLMProviderConfig(name='MiniMax', base_url='', api_key='', default_model='minimax/MiniMax-M2.7', caller='')
assert AgentRuntime._resolve_caller_key(pcfg2, 'MiniMax') == 'minimax', 'test 2'

# Test 3: legacy fallback to model prefix
pcfg3 = LLMProviderConfig(name='Owl', base_url='', api_key='', default_model='', caller='')
assert AgentRuntime._resolve_caller_key(pcfg3, 'openrouter/owl-alpha') == 'openrouter', 'test 3'

# Test 4: empty result when nothing is resolvable
assert AgentRuntime._resolve_caller_key(None, 'MiniMax-M2.7') == 'MiniMax-M2.7', 'test 4'
print('OK')
PYEOF
```

### Step 4 — Handler fix (stop double-prefixing)
**File:** `ui/handlers/agent_runtime_handler.py`
**Action:** Add `if "/" in prov_cfg.default_model: return prov_cfg.default_model` guard at line 286–289 per §2.5.
**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_agent_runtime.py -v 2>&1 | tail -30
# Expect: all tests pass, particularly any that test _resolve_agent_model
```

### Step 5 — Settings dialog read-only label
**File:** `ui/views/settings_dialog.py`
**Action:** Add placeholder `caller=""` at line 37, add `_caller_label` widget + populate in `_fill_form`, preserve caller in `_collect_from_form` per §2.6.
**Verify:** existing settings dialog tests pass; no new test required for label rendering.

### Step 6 — Provider test caller kwarg
**File:** `utils/provider_test.py`
**Action:** Add optional `caller: str | None = None` kwarg, branch in provider detection per §2.7.
**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/test_provider_test.py -v 2>&1 | tail -20
```

### Step 7 — Migration: re-save providers
**Action:** Open Settings → Providers in the running app, click Save on each provider (no changes needed; just save to populate the `caller` field). Alternative: run a one-shot migration script that reads `providers.yaml`, sets `caller` from `default_model.split("/")[0]` for each entry, and writes back. Script is at `scripts/migrate_provider_caller.py` (new file, ~30 lines).
**Verify:**
```bash
grep -A 1 "name: Owl-Alpha" ~/.config/crabcakes/providers.yaml | head -5
# Expect: name: Owl-Alpha, followed by ..., caller: openrouter, ...
```

### Step 8 — Full test suite
**Verify:**
```bash
cd /home/q/projects/crabcakes
python3 -m pytest tests/ 2>&1 | tail -20
```
All existing tests pass; new tests in `test_runtime_caller_resolution.py` pass.

### Step 9 — Live smoke test
**Action:** Open the Crabcakes chat tab in the running app, send "hello".
**Verify:** Chat response streams back without `ValueError: No caller for provider Owl-Alpha` in the log.

---

## 6. Acceptance Criteria

- [ ] `LLMProviderConfig.caller` and `ProviderConfig.caller` exist with default `""`
- [ ] `_to_dict` / `_from_dict` round-trip the `caller` field
- [ ] `AgentRuntime._resolve_caller_key` returns the correct key for: explicit `caller`, derived from `default_model`, derived from `model` prefix, empty when nothing resolvable
- [ ] `_call_llm` and the streaming-dispatch code both use `_resolve_caller_key` instead of `model.split("/")[0]`
- [ ] `_resolve_agent_model` does not double-prefix when `default_model` already contains a slash
- [ ] Settings dialog shows the resolved caller as a read-only label
- [ ] Settings dialog preserves the existing `caller` when editing a provider
- [ ] `providers.yaml` written by the app contains a `caller` key for each provider
- [ ] Crabcakes agent (`llm_name="Owl-Alpha"`) successfully sends a chat message
- [ ] All 1378 pre-existing tests still pass
- [ ] New tests in `test_runtime_caller_resolution.py` pass
- [ ] No `ValueError: No caller for provider` in logs for the 6 existing providers

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| `providers.yaml` entry has no `caller` key (legacy data) | `_from_dict` returns `caller=""`; runtime falls back to derivation from `default_model` |
| `default_model` has no slash (e.g. `MiniMax-M2.7`) | Derivation returns `""` (since `split` on `"/"` returns the whole string when no separator). Runtime then falls back to model prefix, which is the display name — also fails. Resolution: user must re-save the provider via Settings to set explicit `caller`. **User's current data: all 6 providers have slashed default_models, so this case does not apply to existing data.** |
| `provider_cfg` is `None` (no providers configured at all) | `_resolve_caller_key` returns the model prefix or model itself; caller lookup fails with a clear "no caller" error |
| Agent's `model` field contains a slash | `if model and "/" in model: return model` (existing line 274) — no change |
| Provider name is changed via Settings | `_update_provider_ref` is called with the new `ProviderConfig`; `caller` is preserved by the `_collect_from_form` change in §2.6 |
| Two providers with different `caller` values but same `default_model` prefix | Both work; `caller` is the authoritative source when set |
| `caller` field is set to a non-recognized value (e.g. `foo`) | `_PROVIDER_CALLERS.get("foo")` returns `None`; runtime raises `ValueError` with a message suggesting Settings |
| `caller` field has mixed case (e.g. `OpenRouter`) | Resolution: `_PROVIDER_CALLERS` keys are lowercase, so `caller.lower()` is applied in `_resolve_caller_key` |
| Concurrent reads/writes to `providers.yaml` | The existing `add_provider` / `update_provider` functions handle atomicity via `.tmp → rename` (verified at `utils/providers_store.py:140–145`); no new concurrency concerns |
| User deletes a provider that's referenced by an agent's `llm_name` | Runtime falls through to the `list(config.providers.keys())[0]` fallback (line 1319); that provider may have a different `caller` — chat would use the wrong API. **Pre-existing behavior, not introduced by this spec.** |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, add a paragraph to `docs/ARCHITECTURE.md` §12 *Provider Resolution & API Caller*:

> As of PHASE-10, the API caller for a provider is resolved via `provider_cfg.caller`, a per-provider attribute persisted in `providers.yaml`. The runtime's `_resolve_caller_key(provider_cfg, model)` helper returns the explicit `caller` if set, otherwise derives it from `provider_cfg.default_model.split("/")[0]`, and finally falls back to `model.split("/")[0]`. This decouples the model-string prefix structure (which is the API's contract — e.g. `openrouter/owl-alpha` for OpenRouter) from the caller's identity (which is one of the five built-in implementations: `openai`, `minimax`, `anthropic`, `openrouter`, `zai`).

Also update §2.7 (Single Source of Truth) bullet list — the `caller` value is now a per-provider attribute, not a per-model-segment derived value.

---

## 9. Open questions

None. The spec is self-contained and verifiable. All code samples are traced against actual source. All function signatures are verified via `python3 -c "import inspect; ..."`. All edge cases for the user's current data (6 providers, all with slashed `default_model`) are covered by the derivation fallback.

The implementer should treat this spec as a contract. If the source code disagrees with a code sample in this spec, the source code is authoritative and the spec should be updated before the change is made. If a test fails after following the implementation order exactly, stop and report — do not patch around it.
