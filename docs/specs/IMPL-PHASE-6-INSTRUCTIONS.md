# Phase 6 — Update `docs/ARCHITECTURE.md` per SPEC §8

**Spec:** `docs/specs/SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN.md` §8

## Context

Phases 1–5 implemented the spec. ARCHITECTURE.md has three sections that need updating to reflect the new architecture:
- §3.21t `ui/views/agent_builder.py` — describe the simplified form
- (new section) `ui/wiring.py` — document the `agent_builder_factory` parameter
- (new data flow) — User adds provider in Settings while Agent Builder is open

## Files to change

1. `docs/ARCHITECTURE.md` only

## Rules

- Use the steelFramedCodeWriter prompt at `prompts/steelFramedCodeWriter.md` exactly
- Match the existing prose style — concise, sectioned with `**Bold**:` markers
- Do NOT touch any other file
- Do NOT add a new section number — append to the end of the file or use the next available number suffix (e.g., `### 3.21v`)

## Change 1: Update §3.21t `ui/views/agent_builder.py`

The current section (lines 1412-1422 of `docs/ARCHITECTURE.md`):
```
### 3.21t `ui/views/agent_builder.py` — Agent Builder Dialog (User-Defined Agents)

**Responsibility:** GTK4 modal dialog for creating and editing agents. Pure view — receives data from `AgentBuilderHandler`, emits user actions via callbacks.

**Layout:** Name, Emoji, Role, Provider dropdown, Model, Prompts multi-select, Tools checkboxes with presets (Full Access / Read Only / Custom).

**Public API:**
```python
class AgentBuilderDialog:
    def __init__(parent, *, handler, agent_def=None, on_save=None, on_cancel=None)
    def get_values() -> dict
    def show() -> None
    def close() -> None
    def show_errors(errors: list[str]) -> None
```
```

Replace with:
```
### 3.21t `ui/views/agent_builder.py` — Agent Builder Dialog (User-Defined Agents)

**Responsibility:** GTK4 modal dialog for creating and editing agents. Pure view — receives data from `AgentBuilderHandler`, emits user actions via callbacks.

**Layout:** Name, Emoji, Role, **Provider dropdown (populated from `handler.get_provider_options()` at construction)**, Prompts multi-select, Tools checkboxes with presets (Full Access / Read Only / Custom).

**Simplifications (Phase 4 of SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN):**
- **No Model dropdown** — the agent's model is resolved at runtime from `providers.yaml` using the provider's `default_model`. The runtime in `agent/runtime.py` handles this.
- **No Manual entry mode** — the user adds providers only via the Settings dialog.
- **No API key field** — API keys live in `providers.yaml`, never in agent definitions.

**Save button enables when:** name (non-empty) AND prompts (≥1 selected) AND tools (≥1 selected) AND provider (selected in dropdown).

**`get_values()` returns:** `{"name", "emoji", "role", "prompts", "tools", "provider", "model": "", "mcp_servers", "self_improvement"}`. The `model` field is always empty string for new agents; the runtime resolves it from the provider's `default_model`.

**Public API:**
```python
class AgentBuilderDialog:
    def __init__(parent, *, handler, agent_def=None, on_save=None, on_cancel=None)
    def get_values() -> dict
    def set_provider_options(providers: list[ProviderConfig]) -> None
    def show() -> None
    def close() -> None
    def show_errors(errors: list[str]) -> None
```

**Live updates:** When providers change in Settings while the dialog is open, the wiring (`ui/wiring.py`) calls `set_provider_options()` on this dialog. The dropdown rebuilds. The handler resolves the new model from `providers.yaml` at save time, not at dialog open time.
```

## Change 2: Add a new section for `ui/wiring.py`

Find the right place to insert (after §3.21t is the natural location — both are UI composition concerns). Use the next available number suffix, or create §3.21u-prime. Check the existing numbering — pick a non-conflicting identifier like `### 3.21u.a` or just use `### 3.21u`.

Actually, looking at the file, the next available section is §3.21u (Agent Enforcement). Use `### 3.21u.a` or a unique number. Verify by running `grep -E "^### 3\.21[a-z]+" docs/ARCHITECTURE.md | sort | uniq` and pick the next letter.

Add this content (between the updated §3.21t and the existing §3.21u):

```
### 3.21u.a `ui/wiring.py` — SettingsHandler Callback Wiring (Phase 1 of SPEC-AGENT-BUILDER-PROVIDER-DROPDOWN)

**Responsibility:** Wire the `SettingsHandler`'s `on_status_changed` and `on_providers_changed` callbacks to the toolbar and dialogs. Pure composition — no business logic, no GTK widget creation.

**Owns:** None — this is a stateless wiring function. The handler is owned by the window; the toolbar is owned by the window; the dialogs are owned by the window.

**Public API:**
```python
def wire_settings_handler(
    handler: SettingsHandler,
    toolbar,
    *,
    settings_dialog_factory: Callable[[], Any] | None = None,
    agent_builder_factory: Callable[[], Any] | None = None,
) -> SettingsHandler
```

**Idempotency:** The function is idempotent — calling it twice on the same handler is a no-op (uses a `_wired` flag on the handler). The composition root (`ui/window.py`) calls it exactly once during `_build()`.

**Factories:** Both `settings_dialog_factory` and `agent_builder_factory` are LAZY factories that return a dialog or `None` if the dialog is not open. This is critical — the dialogs may not exist when the wiring is set up (e.g., the agent builder is only created when the user clicks the `+ Agent` button). The factory is called only when `on_providers_changed` fires.

**Behavior:**
- Initial call: `toolbar.set_settings_status(has_any_verified_provider(load_providers()))` is invoked (wrapped in try/except so a toolbar failure doesn't break the wiring).
- On `on_status_changed`: forwards to `toolbar.set_settings_status(has_any_verified_provider(providers))`.
- On `on_providers_changed`: calls both factories, forwards the providers list to whichever returned non-None.

**Architecture compliance:**
- Composition root pattern: the wiring is a function, not a class. It has no state.
- Lazy factories: dialogs are constructed on demand, not at wiring time. This matches the "dialogs are not widgets, they're ephemeral UI" principle in §3.6.
- Idempotency: makes the wiring safe to call from tests (multiple wire_settings_handler calls in a test do not produce double-callbacks).
```

## Change 3: Add a new data flow section

In §4, add a new subsection. Find the existing §4.7 (Forward Callback Wiring Chain) and add §4.7a or a new §4.10 (whichever is cleaner — check the existing section numbering for the next free number). Use the next free number — verify with `grep -E "^### 4\." docs/ARCHITECTURE.md`.

Add:

```
### 4.X Provider Change → Open Agent Builder Refresh

User adds a provider in Settings while the Agent Builder is open
  → SettingsDialog._on_add_provider()
    → handler.add_or_update(ProviderConfig)
      → handler._on_providers_changed(providers)  (if handler is the SettingsHandler)
        → wire_settings_handler._on_providers_changed(providers)  (closure)
          → settings_dialog_factory() → None (or settings dialog) → refresh_providers(providers)
          → agent_builder_factory() → AgentBuilderDialog or None
            → dialog.set_provider_options(providers)  (rebuilds dropdown)

User removes a provider in Settings while the Agent Builder is open (with that provider selected)
  → same chain as above
    → agent_builder._providers updates
      → _rebuild_provider_dropdown() runs
        → if no providers left: dropdown shows "(no providers — open Settings)"
        → if providers remain: dropdown shows remaining names
        → _get_selected_provider_id() returns "" if the selected index is now invalid
          → _update_save_button() disables Save
```

Where §4.X is the next free number after 4.9 (currently 4.7 is Forward Callback, 4.8 is Scroll-to-Bottom, 4.9 is Project Membership Toggle). Pick the next number — verify with grep.

## Verification

```bash
cd /home/q/projects/crabcakes

# §3.21t should mention "No Model dropdown", "No API key field"
grep -n "No Model dropdown\|No API key field\|set_provider_options" docs/ARCHITECTURE.md
# Expected: 1+ matches in §3.21t area

# The new wiring section exists
grep -n "ui/wiring.py\|agent_builder_factory" docs/ARCHITECTURE.md
# Expected: matches

# The new data flow section exists
grep -n "Provider Change.*Agent Builder\|agent_builder_factory() → AgentBuilderDialog" docs/ARCHITECTURE.md
# Expected: 1+ matches

# The file still parses as valid markdown
python3 -c "
import re
with open('docs/ARCHITECTURE.md') as f:
    content = f.read()
# Count headings
h1 = len(re.findall(r'^# ', content, re.M))
h2 = len(re.findall(r'^## ', content, re.M))
h3 = len(re.findall(r'^### ', content, re.M))
print(f'H1: {h1}, H2: {h2}, H3: {h3}')
" 2>&1 | tail -3
# Expected: H1=0 (no top-level #), H2=12-13, H3=increased by 1-2

# Confirm no broken section numbering
grep -E "^### 3\." docs/ARCHITECTURE.md | sort -t. -k2,2n -k3,3 | head -10
# Expected: monotonically increasing (some letter suffixes are fine)
```

## COMPLETENESS Checklist

- [ ] Change 1: §3.21t updated — mentions "No Model dropdown", "No Manual entry mode", "No API key field" — evidence: grep
- [ ] Change 1: §3.21t `get_values()` doc updated to show `model: ""` — evidence: grep
- [ ] Change 1: §3.21t public API includes `set_provider_options` — evidence: grep
- [ ] Change 2: new section added for `ui/wiring.py` with `agent_builder_factory` parameter documented — evidence: grep
- [ ] Change 3: new data flow subsection added describing provider-change → open-builder refresh — evidence: grep
- [ ] All changes are in `docs/ARCHITECTURE.md` — evidence: git status
- [ ] No other file changed — evidence: git status (only ARCHITECTURE.md modified)
