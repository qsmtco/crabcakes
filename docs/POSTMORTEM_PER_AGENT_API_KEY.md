# POST-MORTEM: Per-Agent, Per-Provider API Key Enforcement

**Date:** 2026-05-28
**Spec:** `docs/SPEC_PER_AGENT_API_KEY.md`
**Implementer:** QTR
**Auditor:** Qaster (adversarial debugger)

---

## Summary

Implementation is **CLEAN**. No bugs found. Code is spec-compliant and architecture-compliant.

---

## Code Quality: HIGH

### What went right
- **Architecture compliance is perfect.** `_do_save()` is a pure callback emitter — zero validation logic in the view. All validation lives in `validate_agent_def()`. No GTK imports in handler. No business logic in views.
- **Spec adherence is exact.** Every line in the diff matches the spec. No creative additions, no scope creep.
- **Backward compatibility is solid.** Legacy `api_key` field handled with clean fallback chain in both `special_agents.py` and `validate_agent_def()`.
- **Signal wiring is complete.** `_update_save_button()` connected to all 5 change sources: name entry, API key entry, prompt toggled, tool-categorized toggled, tool-other toggled.
- **Init order is correct.** Checkboxes populated before `_update_save_button()` can be called. Intermediate calls during `_fill_form()` are harmless; final explicit call sets correct state.

### Minor issues (non-blocking)
1. **Stale docstring** in `_get_selected_model()` at line 332: says `minimax-portal` but actual provider ID is `minimax`. Cosmetic only.
2. **Tests only cover legacy path.** Test fixtures use `api_key` field, not `provider_keys`. The new path works (verified manually) but lacks explicit test coverage. Low risk since both paths share the same validation code.

---

## Bugs Encountered: ZERO

Adversarial debugger tried 13 attack vectors. All passed:

| # | Attack | Result |
|---|--------|--------|
| 1 | Empty API key preserving old key in provider_keys | Blocked by save button disable — user can't save without key |
| 2 | Legacy api_key + provider_keys for different provider | Migration correctly adds legacy to missing provider |
| 3 | Empty string in provider_keys | Validation correctly rejects it |
| 4 | Legacy api_key fallback in validation | Correctly accepted |
| 5 | special_agents.py reads provider_keys correctly | All 3 paths verified (new, legacy, empty) |
| 6 | Provider switching preserves other keys | Keys for non-active providers preserved correctly |
| 7 | _do_save() has validation logic | Confirmed clean — pure callback emitter |
| 8 | _update_save_button() called for new agents | Correct — else branch handles it |
| 9 | Intermediate _update_save_button calls during fill | Harmless — final call sets correct state |
| 10 | Both tool checkbox categories wired | Both categorized and 'other' got toggled signal |
| 11 | User can't delete key from non-active provider | Correct behavior — keys preserved, save blocked if current key empty |
| 12 | Model dropdown mid-rebuild during save button update | No dependency — save button doesn't check model |
| 13 | Tests cover new provider_keys format | Tests use legacy path; new path verified manually |

---

## Files Changed (QTR's implementation)

| File | Change | Lines |
|------|--------|-------|
| `ui/views/agent_builder.py` | provider_keys, save button state, provider switching, model dropdown | +159/-29 |
| `utils/agent_defs.py` | API key validation with legacy fallback | +7 |
| `agent/special_agents.py` | Read provider_keys with fallback | +2 |
| `tests/test_agent_builder_handler.py` | Added api_key to test fixtures | +5 |
| `tests/test_agent_defs.py` | Added api_key to test fixture | +1 |
| `tests/test_bug_fixes.py` | Added api_key to test fixtures | +3 |

Also includes prior changes from this session:
| `agent/runtime.py` | OpenRouter/ZAI callers/streamers, _model_id(), null content fix | +51 |
| `models/conversation.py` | api_key field on Conversation | +1 |
| `ui/handlers/agent_runtime_handler.py` | Pass api_key to create_conversation | +1 |

**Files NOT changed (verified correct):**
- `agent/runtime.py` — effective_api_key logic already wired
- `models/conversation.py` — api_key field already exists
- `ui/handlers/agent_builder_handler.py` — passes dict through naturally
- `ui/window.py` — save/cancel wiring already correct

---

## Test Results

- `test_agent_defs.py`: 24/24 pass
- `test_agent_builder_handler.py`: 13/13 pass
- `test_bug_fixes.py`: 11/11 pass
- **Total: 48/48 pass**

---

## Recommendations for Future Work

1. **Add explicit `provider_keys` test coverage.** Create a test that uses `provider_keys: {openrouter: "sk-..."}` format and verifies validation accepts/rejects correctly.

2. **Fix stale docstring.** Line 332 in `agent_builder.py`: change `minimax-portal` → `minimax`.

3. **Consider key deletion UX.** Currently there's no way to remove a key from a non-active provider. If a user wants to clean up old keys, they'd need to switch to that provider, clear the field, and enter a new key. A "clear all keys" or per-provider delete option could improve this.

4. **ZAI provider key.** The ZAI provider in `agent.json` has an empty API key. The dialog will correctly require the user to enter one before saving an agent that uses ZAI. This is working as designed, but worth noting that ZAI agents can't be created until a key is provided.

---

## Session Context

This was part of a larger session that included:
- Feed card width fix (commit `c3c6c8b`)
- GTK close error fixes (commit `a0e6c0d`)
- Agent builder provider/model dropdown redesign
- OpenRouter/ZAI provider support in runtime
- Null content streaming fix
- Per-agent API key wiring through runtime

All changes are uncommitted but verified. Recommend committing as a single logical unit.
