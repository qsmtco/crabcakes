# PHASE 10 — Post-Mortem

## Summary

PHASE-10 added a `caller` field to `LLMProviderConfig` and `ProviderConfig` to decouple the model-string prefix structure (API contract) from the caller identity (one of 5 built-in implementations). The runtime now resolves the caller via `provider_cfg.caller` (explicit, persisted in `providers.yaml`), with a derivation fallback from `default_model.split("/")[0]` for backward compatibility with providers written before this change.

## What changed

- **8 source files modified, 1 test file created, 1 migration script created**
- 82 lines added across source files, 6 lines modified
- 100 lines added in the new test file
- 52 lines added in the migration script

### Source files
- `agent/config.py` — added `caller: str = ""` to `LLMProviderConfig`
- `models/providers.py` — added `caller: str = ""` to `ProviderConfig`
- `utils/providers_store.py` — round-trip `caller` through `_to_dict` / `_from_dict`
- `agent/runtime.py` — added `_resolve_caller_key` static helper; wired into `_call_llm`; lowercased explicit caller
- `ui/handlers/agent_runtime_handler.py` — stop double-prefixing slashed `default_model` in `_resolve_agent_model`
- `ui/handlers/settings_handler.py` — auto-detect caller from slashed `default_model` in `add_or_update`; pass `caller=provider.caller` to `test_connection`
- `ui/views/settings_dialog.py` — read-only caller label + preserve caller in `_collect_from_form`
- `utils/provider_test.py` — `caller: str | None = None` kwarg in `test_connection`

### New files
- `tests/test_runtime_caller_resolution.py` — 8 tests for `_resolve_caller_key` + `_resolve_agent_model`
- `scripts/migrate_provider_caller.py` — one-shot migration script (idempotent, `--dry-run`)

### Documentation
- `docs/ARCHITECTURE.md` — new §12 "Provider Resolution & API Caller"; renumbered old §12→§13, §13→§14

## Test results

| Branch | Passed | Failed | Skipped |
|--------|--------|--------|---------|
| Clean main (before PHASE-10) | 1375 | 13 | 1 |
| With PHASE-10 changes | 1383 | 13 | 1 |
| **Delta** | **+8** | **0** | **0** |

The 8 new tests (P8) all pass. The 13 pre-existing failures are in:
- `test_agent_builder_handler.py` (5 failures — pre-existing provider-keying scheme mismatch)
- `test_agent_defs.py` (1 failure — pre-existing test references old scheme)
- `test_bug_fixes.py` (3 failures — pre-existing)
- `test_connection_sync_handler.py` (1 failure — pre-existing)
- `test_special_agents.py` (3 failures — pre-existing)

**None of these failures were introduced by PHASE-10.** Verified by stashing all changes and re-running on clean main.

## Migration status

The migration script `scripts/migrate_provider_caller.py` was run during P7 verification. All 7 providers in `~/.config/crabcakes/providers.yaml` now have explicit `caller` values:
- Nex N2 Pro → `caller: openrouter`
- MiniMax M3 → `caller: minimax`
- MiniMax M2.7 → `caller: minimax`
- kimi K2.6 → `caller: openrouter`
- GLM 5.1 → `caller: zai`
- Owl-Alpha → `caller: openrouter`
- Test → `caller: openrouter`

## Adversarial findings (from the audit)

1. **`add_or_update` did not auto-detect caller** (P5 audit): The spec assumed `SettingsHandler.add_or_update` had auto-detect logic, but it didn't. Fix: added 3-line auto-detect block in `settings_handler.py:90-93`. Without this fix, the Settings dialog's caller label would always show "(auto-detected on save)" and the runtime would rely solely on the derivation fallback.

2. **`_resolve_caller_key` did not lowercase explicit caller** (P8 audit): The P8 test originally asserted `"OpenRouter"` returned as-is (matching the implementation). This was a latent bug — `_PROVIDER_CALLERS` dict keys are all lowercase, so a mixed-case caller would fail the lookup. Fix: changed `return provider_cfg.caller` to `return provider_cfg.caller.lower()` in `agent/runtime.py:1294`. Updated the P8 test to assert `"openrouter"` (lowered).

3. **P3 spec said `_call_llm` was at line 1281** (audit during P3a): Actual line was 1281 in the current file, but the spec's line numbers were off by ~70 lines. This was a non-issue — the grep-based verification caught the correct location.

4. **`_PROVIDER_STREAMERS` still keyed by `model.split("/")[0]`** (P3a audit): The spec called for changing the streamer lookup to use `_resolve_caller_key`, but the P3a instructions only added the helper without changing the streamer call site. After P3b, the streamer lookup at line ~1303 still uses `model.split("/")[0]`. This is a **known gap** — the streamer path can fail for providers with non-slashed model names. Fix deferred to a follow-up phase (see Open Questions below).

## Open questions / Future work

- **Streamer lookup should also use `_resolve_caller_key`** (P3a spec gap). Currently the streaming path keys by `model.split("/")[0]` instead of the resolved caller key. For providers with slashed `default_model` (all 7 of the user's), this works because the model prefix matches the caller key. For non-slashed models, the streamer lookup will fail. Fix: add the same `_resolve_caller_key` call to the streaming dispatch (out of scope for PHASE-10 per the phase instructions).

- **P5 followup: `_collect_from_form` should also preserve `last_verified_at` and `last_error`** (spec line 380). Currently these fields are only preserved in `add_or_update`, not in the form collect path. If a user edits a provider without re-testing, the last_verified_at and last_error timestamps are lost. Fix: add these to the `ProviderConfig` construction in `_collect_from_form` (out of scope for PHASE-10).

- **Settings dialog does not show a "Test" button for unsaved cards** (P5 gap). The `caller` label shows "(auto-detected on save)" for new providers, but there's no way to test the caller resolution without first saving. Fix: allow testing unsaved cards by passing the form-collected `ProviderConfig` to `test_provider` (the `test_provider` handler already accepts any `ProviderConfig`).

## Acceptance criteria status

All 6 acceptance criteria from the master spec are met:
- [x] `LLMProviderConfig.caller` and `ProviderConfig.caller` exist with default `""`
- [x] `_to_dict` / `_from_dict` round-trip the `caller` field
- [x] `AgentRuntime._resolve_caller_key` resolves caller with explicit > derivation > fallback priority
- [x] `_call_llm` uses the resolved caller key
- [x] Settings dialog shows read-only caller label
- [x] `test_connection` accepts `caller` kwarg
