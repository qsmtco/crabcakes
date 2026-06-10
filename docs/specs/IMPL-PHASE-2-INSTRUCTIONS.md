# Agent Builder Provider Dropdown — Full Implementation Plan

**Spec:** `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md`
**Status:** Implementation in progress

---

## Phase Map

| Phase | File(s) | What | Status |
|-------|---------|------|--------|
| 1 | ui/wiring.py | Add `agent_builder_factory` param + new block in `_on_providers_changed` | ✅ DONE + audited |
| 2 | ui/views/agent_builder.py | Fix `set_provider_options` type mismatch: accept both `list[ProviderConfig]` and `list[dict]` | NEXT |
| 3 | ui/window.py | Wire `agent_builder_factory` + remove dead `_on_providers_changed` | pending |
| 4 | ui/views/agent_builder.py | Call `set_provider_options(handler.get_provider_options())` at end of `__init__` | pending |
| 5 | ui/views/agent_builder.py | Remove Model dropdown + Manual entry + API key field + all related dead code | pending |
| 6 | ui/views/agent_builder.py | Update `_update_save_button()` + `get_values()` (remove model/API key requirements) | pending |
| 7 | ui/window.py | Remove dead `_on_providers_changed` method (its logic moved to wiring) | pending |
| 8 | tests/ | New + revised tests | pending |
| 9 | docs/ + full suite | ARCHITECTURE.md updates + final test run | pending |

---

## Phase 2 — Fix `set_provider_options` Type Mismatch

**File to change:** `ui/views/agent_builder.py`

**Bug (from adversarial audit of Phase 1):**
`set_provider_options()` is called from TWO different call sites that pass DIFFERENT types:
- Call site A: `_on_providers_changed` in wiring → passes `list[ProviderConfig]` (dataclass with `.name`, `.default_model` attributes) ✅
- Call site B: `AgentBuilderDialog.__init__` → passes `handler.get_provider_options()` → returns `list[dict]` with keys `"name"`, `"base_url"`, `"default_model"` ❌

`set_provider_options()` uses attribute access (`.name`, `.default_model`). Dicts don't support attribute access. When Call site B is connected in Phase 4, the app will crash with `AttributeError: 'dict' object has no attribute 'name'`.

**Fix:** `set_provider_options()` must normalize its input. Accept both `list[ProviderConfig]` and `list[dict]`. Use `isinstance(p, dict)` to branch.

**Current code (lines 301-308):**
```python
def set_provider_options(self, providers) -> None:
    """Replace the provider list with the given providers.
    Called by the window when the Settings dialog fires on_providers_changed.
    Each provider's default_model becomes the only entry in its model dropdown.
    """
    self._providers = list(providers) if providers else []
    self._provider_models = {
        p.name: [(p.default_model, p.default_model)]
        for p in self._providers
        if p.default_model
    }
    self._rebuild_provider_dropdown()
```

**After fix:**
```python
def set_provider_options(self, providers) -> None:
    """Replace the provider list with the given providers.
    Called by the window when the Settings dialog fires on_providers_changed,
    and by __init__ with handler.get_provider_options().
    Accepts list[ProviderConfig] (from _on_providers_changed) or list[dict]
    (from handler.get_provider_options()).
    Each provider's default_model becomes the only entry in its model dropdown.
    """
    if not providers:
        self._providers = []
    else:
        # Normalize: accept both list[ProviderConfig] and list[dict]
        self._providers = []
        for p in providers:
            if isinstance(p, dict):
                self._providers.append(p)  # keep as dict
            else:
                self._providers.append(p)  # ProviderConfig — keep as-is
    self._provider_models = {}
    for p in self._providers:
        name = p["name"] if isinstance(p, dict) else p.name
        default_model = p.get("default_model") if isinstance(p, dict) else getattr(p, "default_model", None)
        if default_model:
            self._provider_models[name] = [(default_model, default_model)]
    self._rebuild_provider_dropdown()
```

**Rules:**
- Use the steelFramedCodeWriter prompt at `prompts/steelFramedCodeWriter.md`
- Follow it exactly with no deviation
- Run: `python3 -m pytest tests/test_window_settings_wiring.py tests/test_agent_builder_handler.py -v --tb=short` and paste the output
- Run: `python3 -c "from ui.views.agent_builder import AgentBuilderDialog; print('import ok')"` and paste the output
- At the end, include the COMPLETENESS checklist

**COMPLETENESS checklist for Phase 2:**
- [x/not done] Fix: set_provider_options accepts both list[ProviderConfig] and list[dict] — evidence: paste the new method
- [x/not done] Fix: isinstance(p, dict) branch returns p["name"] and p.get("default_model") — evidence: grep line
- [x/not done] Fix: non-dict branch uses p.name and getattr(p, "default_model", None) — evidence: grep line
- [x/not done] Fix: no AttributeError when providers is list[dict] — evidence: python3 -c test output
- [x/not done] Tests: existing tests pass — evidence: pytest output