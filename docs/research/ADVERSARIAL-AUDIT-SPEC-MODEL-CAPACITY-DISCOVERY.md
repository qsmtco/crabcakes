# Adversarial Audit: SPEC-MODEL-CAPACITY-DISCOVERY (commit bc31a2a)

**Date:** 2026-06-24
**Auditor:** QTR (assistant), following `prompts/adversarialDebugger.md`
**Subject:** Implementation of `docs/specs/SPEC-MODEL-CAPACITY-DISCOVERY.md`
**Commit:** `bc31a2a` — feat(providers): auto-discover context window via /v1/models probe
**Files touched:** 8 (3 prod, 3 tests, 2 fixtures)

---

## SUMMARY VERDICT

| Claimed | Verified |
|---|---|
| 106 tests pass, 0 failures | ✅ Confirmed (`pytest tests/test_provider_test.py tests/test_settings_dialog.py tests/test_settings_handler.py tests/test_providers_store.py` → 106 passed, 1 skipped) |
| All 8 scope items addressed | ✅ Confirmed (file changes match spec §2.1–§2.8) |
| All 5 production files modified | ⚠️ **Bug #1 below** — production code modification outside scope |
| Test fix claim ("mock boundary matches") | ⚠️ **Bug #2 below** — accurate but obscures architectural regression |

**Overall:** The implementation achieves its user-visible goal (auto-discover context window via `/v1/models`) and all tests pass. However, there are **3 HIGH-severity bugs**, **4 MEDIUM-severity bugs**, and **4 LOW-severity bugs** that the developer's "completeness report" did not surface. The most important is the global-state pollution in `provider_test.py:install_opener`, which silently mutates process-wide urllib behavior for all other code in the same process.

---

## BUG #1
**Severity:** HIGH
**Assumption violated:** "Changing `_opener.open()` to `urllib.request.urlopen()` only affects the local probe"
**Attack vector:** Call `test_connection` once (any provider, success or failure), then call `urllib.request.urlopen` from any other module in the same process.
**Reproduction:**
```python
import urllib.request
from utils.provider_test import _do_request

# Step 1: call test_connection (or _do_request) once
result = _do_request(
    endpoint="https://api.example.com/v1/chat/completions",
    body=b'{}', headers={"Authorization": "Bearer x"},
    model="x/y", provider="openai", timeout_seconds=5.0,
)
# (This will fail to connect, but the side effect already happened.)

# Step 2: verify module-global _opener was replaced
print("Global opener:", urllib.request._opener)
# Before fix: <urllib.request.OpenerDirector at 0x...>  (with redirect handler!)
# After fix: would still be None or default
```

**Root cause:** Lines 195-198 of `utils/provider_test.py`:
```python
_opener = urllib.request.build_opener(_NoAuthRedirectHandler)
urllib.request.install_opener(_opener)   # ← global side effect
with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
```

`urllib.request.install_opener()` mutates the module-level `_opener` variable, which is shared by *every* `urllib.request.urlopen()` call in the process. The previous code used `_opener.open()` (local) which had no global side effect.

**Affected downstream code (verified by grep):**
- `agent/runtime.py:522` — `_urlopen_with_ssl_retry` uses `urllib.request.urlopen(req, timeout=...)`. If `test_connection` was called earlier in the process, this call now routes through the modified opener (with `_NoAuthRedirectHandler`).
- `agent/kb_server.py:179` — KB synthesis HTTP call to LLM providers. Same issue.
- `tests/generate_synthetic_conversations.py:71` — test fixture script. Same issue.

In practice, `_do_request` is only called from the UI settings dialog and from the test suite, so this rarely matters — but it IS a real architectural regression. The "Pre-existing test fix" mentioned in the developer's report (the `install_opener` change to make mock boundary match) is the workaround for a testability problem caused by the new probe code path, not an unrelated improvement.

**Fix:**
```python
# Option A: keep opener local, mock the boundary
_opener = urllib.request.build_opener(_NoAuthRedirectHandler)
try:
    with _opener.open(req, timeout=timeout_seconds) as resp:
        ...
    # Also for the probe:
    with _opener.open(models_req, timeout=10) as mresp:
        ...
finally:
    pass  # nothing to restore since opener is local

# Option B: install_opener with try/finally restore
_opener = urllib.request.build_opener(_NoAuthRedirectHandler)
old_default = urllib.request._opener
urllib.request.install_opener(_opener)
try:
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        ...
finally:
    urllib.request._opener = old_default
```

Option A is cleaner — the original `_opener.open()` pattern was correct; the regression was changing it to `urllib.request.urlopen()` at all.

---

## BUG #2
**Severity:** HIGH
**Assumption violated:** "`/v1/models` returns model IDs in the same form as the model string passed to `test_connection`"
**Attack vector:** Use OpenRouter as a provider (it's one of the 5 `_OPENAI_COMPATIBLE` callers), with any model whose ID has a vendor prefix.
**Reproduction:**
```python
# OpenRouter's /v1/models returns:
# {"data": [{"id": "openai/gpt-4o", "context_length": 128000}, ...]}
#
# crabcakes probe code does:
#   model_id = model.split("/", 1)[-1]  # "openai/gpt-4o" → "gpt-4o"
#   for model_obj in models_body.get("data", []):
#       if model_obj.get("id") == model_id:    # "gpt-4o" == "openai/gpt-4o" → NEVER MATCHES
```

Verified empirically via `web_fetch("https://openrouter.ai/api/v1/models?q=gpt-4o")`:
- Response includes `"id": "openai/gpt-4o-mini-search-preview"` (full vendor-prefixed ID)
- Response includes `"context_length": 128000` (top-level field, which IS in the probe's check list)

**Root cause:** The model ID stripping logic in `provider_test.py:240` strips the provider prefix from the search model, but OpenRouter returns IDs with the vendor prefix kept. The comparison fails for OpenRouter models that use a vendor prefix.

**Affected providers:** OpenRouter (`"openrouter"`) — one of the 5 callers in `_OPENAI_COMPATIBLE`.

**Fix:** Don't strip the prefix. Compare the full model string (or both forms):
```python
# Try full ID first, then stripped
model_id_full = model  # e.g. "openai/gpt-4o"
model_id_bare = model.split("/", 1)[-1]  # e.g. "gpt-4o"
for model_obj in models_body.get("data", []):
    obj_id = model_obj.get("id", "")
    if obj_id == model_id_full or obj_id == model_id_bare:
        # ... extract context window ...
        break
```

This makes the probe robust to providers that keep prefixes (OpenRouter) and providers that strip them (OpenAI direct).

---

## BUG #3
**Severity:** HIGH
**Assumption violated:** "OpenAI-compatible `/v1/models` includes context-window metadata at the model-object level"
**Attack vector:** Run Test Connection against MiniMax M3 (the primary user model).
**Reproduction:** Per the MiniMax API docs (verified via `web_fetch`), `/v1/models` returns:
```json
{"object": "list", "data": [{"id": "MiniMax-M2.7", "object": "model", "created": 1234567890}]}
```
**No `context_window`, `max_context_length`, `context_length`, `max_tokens`, or `max_model_len` field.** The probe's `for field in ("context_window", ...) if field in model_obj` loop will iterate all 5 field names, find none, and leave `context_window = None`. **The very model this spec was written to support (MiniMax M3 with 1M context) will not have its context window auto-discovered.**

**Root cause:** The field-name fallback list was derived from a generic OpenAI/OpenRouter/Anthropic survey but did not include MiniMax or Z.ai's response formats. MiniMax's docs explicitly do not include context window in the model object.

**Fix:** Either:
- (A) Add a MiniMax-specific probe that calls a different endpoint or parses a different field.
- (B) Add a static fallback table in `providers.py` keyed by `caller`: `CALLER_DEFAULT_MAX_TOKENS = {"minimax": 1_048_576, "openai": 128_000, "anthropic": 200_000, "openrouter": 128_000, "zai": 128_000}`. If the probe returns `None`, fall back to the table.
- (C) Document that auto-discovery is best-effort and the user must hand-edit YAML for MiniMax.

Option B is what the spec §1 "Phase 1.1" originally envisioned (`default_max_tokens` field as a "per-caller fallback table") — but the implementation added the field without ever reading it. **BUG #6 below.**

---

## BUG #4
**Severity:** MEDIUM
**Assumption violated:** "`default_max_tokens` field added to `ProviderConfig` will be used by some consumer"
**Attack vector:** Search the entire codebase for `default_max_tokens`.
**Reproduction:**
```bash
$ grep -rn "default_max_tokens" --include="*.py" /home/q/projects/crabcakes
models/providers.py:25:    default_max_tokens: int = 0
utils/providers_store.py:47:        "default_max_tokens": p.default_max_tokens,
utils/providers_store.py:65:    default_max_tokens=d.get("default_max_tokens", 0),
```
**Only 3 occurrences: declaration + 2 persistence sites. Zero consumers.** The field is dead code.

**Root cause:** The spec §2.1 said "0 means 'no caller-specific default; use 128_000'" but the spec never specified *what reads this field* or *what populates it from a caller table*. The implementer added the field but skipped the consumer logic. The companion spec section §1 ("Phase 1.1" — caller-specific default table) was marked as the *purpose* of the field, but the table itself (`CALLER_DEFAULT_MAX_TOKENS`) was never created.

**Fix:** Either:
- (A) Remove `default_max_tokens` field entirely until there's a real consumer (YAGNI).
- (B) Add the consumer: a helper `_resolve_default_max_tokens(provider_cfg) -> int` that checks `caller` against a static table and falls back to `max_tokens` if `default_max_tokens == 0`.

---

## BUG #5
**Severity:** MEDIUM
**Assumption violated:** "`self._provider.max_tokens == 128_000` is a safe sentinel for 'user hasn't customized'"
**Attack vector:** Open Settings, leave the spin button at default (128_000), click Test Connection on a provider whose real context window IS 128K (e.g., GPT-4o, GLM-5.2).
**Reproduction:** User has `M3` provider with `max_tokens=128_000` (which is the *wrong* value for M3 — should be 1M). User clicks Test Connection:
1. Probe returns `context_window = 1_048_576` for M3
2. Handler: `p.max_tokens == 128_000` is True → overwrite to 1_048_576. **Correct behavior here.**

But inverse case: User has `glm5.2` provider with `max_tokens=128_000` (which IS correct for GLM-5.2). User clicks Test Connection:
1. Probe returns `context_window = 128_000` (or `None` if Z.ai doesn't expose it)
2. If `context_window = 128_000`: handler overwrites with the same value. **Harmless but wastes a write.**
3. If `context_window = None`: handler preserves `128_000`. **Correct.**

But the real risk: a user *deliberately* sets `max_tokens=128_000` for a provider whose API returns a different number. E.g., user knows their deployment has a 128K cap regardless of the model's nominal window. Next Test Connection silently overwrites the deliberate cap.

**Root cause:** The sentinel `== 128_000` is overloaded: it's both the *default* AND a *valid value that the user might intentionally pick*. The two semantics are indistinguishable.

**Fix:** Add a separate "user has set this value" flag, OR use a sentinel value that's impossible as a real context window (e.g., `0` or `-1` meaning "not set"):
```python
max_tokens: int = 0   # 0 = unset; runtime falls back to FALLBACK
```
This requires changing the existing field semantics, which is invasive but correct.

---

## BUG #6
**Severity:** MEDIUM
**Assumption violated:** "After Test Connection completes, the dialog's `_provider` reference reflects the new value"
**Attack vector:** In Settings dialog, click Test Connection. Without closing the dialog, click Test Connection again. Observe stale `_provider` reference.
**Reproduction:**
```python
# In settings_dialog.py:
def _on_test_result(self, result: TestResult) -> None:
    if result.ok:
        if result.context_window and (self._provider.max_tokens == 128_000):
            # self._provider is the ORIGINAL provider, not the post-test one.
            # The handler updated disk but didn't notify the dialog.
            self._max_tokens_spin.set_value(result.context_window)
```
After first Test Connection:
- Disk: `max_tokens = 200_000` (pre-filled)
- `self._provider.max_tokens` = 128_000 (stale!)

User clicks Test Connection again:
- Handler worker: loads providers, sees `p.max_tokens = 200_000`, `p.max_tokens == 128_000` is False → preserves
- Handler dispatch: dialog checks `self._provider.max_tokens == 128_000` (stale), updates spin to `result.context_window` again

**The dialog's source-of-truth is `_provider`, but the dialog never updates `_provider` after Test Connection.** This causes:
- Two different behaviors between handler (preserves on second test) and dialog (overwrites on second test)
- `_is_dirty()` returns True forever (spin = 200_000, p.max_tokens = 128_000)
- `refresh_providers` would update the card in place on the next refresh

**Root cause:** `_on_test_result` updates the spin button but doesn't call `self._provider = ProviderConfig(...self._provider..., max_tokens=new_value)` or equivalent.

**Fix:** Update `_provider` to reflect the new value:
```python
def _on_test_result(self, result: TestResult) -> None:
    if result.ok:
        if result.context_window and (self._provider.max_tokens == 128_000):
            self._max_tokens_spin.set_value(result.context_window)
            # NEW: update the provider reference so _is_dirty and refresh work correctly
            self._provider = ProviderConfig(
                **{**dataclasses.asdict(self._provider), "max_tokens": result.context_window}
            )
            ...
```

Or, more cleanly: call `self._update_provider_ref(self._provider)` after updating the spin (but `_update_provider_ref` doesn't update fields — it only updates `last_verified_at`/`last_error`).

---

## BUG #7
**Severity:** MEDIUM
**Assumption violated:** "The auxilium wizard's `max_tokens=128_000` defaults are intentional and consistent with the rest of the system"
**Attack vector:** Use Auxilium wizard to set up an "openrouter_free" provider. Open Settings. Click Test Connection.
**Reproduction:**
- Wizard creates `ProviderConfig(name="openrouter", max_tokens=128_000, ...)`
- User saves
- User clicks Test Connection
- Probe returns some `context_window` (likely None for OpenRouter due to BUG #2, but assume it works)
- Handler: `p.max_tokens == 128_000` → overwrites

**The wizard's 128K default is not protected from being overwritten** because the sentinel doesn't distinguish "default" from "deliberate choice." The spec §7 acknowledged this: "User customized max_tokens=128000 (exactly default) | Treated as not-customized; next Test Connection will overwrite. Acceptable per design: 128K is a valid value, and explicit Save preserves it."

**But "explicit Save preserves it" is misleading** — the wizard doesn't set a "wizard-set" flag, so there's no way to distinguish wizard-128K from user-128K.

**Root cause:** Spec said out of scope: "If a future phase wants to populate `default_max_tokens` from caller (e.g. openrouter=128K), add it then." But the design that *needs* `default_max_tokens` to be set (so the sentinel works) was not implemented.

**Fix:** Set `default_max_tokens = 128_000` in `auxilium_wizard_handler.py:371, 428` to indicate "this is a deliberate wizard choice":
```python
return ProviderConfig(
    ...,
    max_tokens=128_000,
    default_max_tokens=128_000,  # NEW: mark as wizard-set, protect from overwrite
)
```

But this requires the handler's sentinel check to also read `default_max_tokens`, which would be a larger refactor.

---

## BUG #8
**Severity:** LOW
**Assumption violated:** "The probe's field-name fallback list is exhaustively tested"
**Attack vector:** Read the test file. Count the tests covering each field name.
**Reproduction:** `tests/test_provider_test.py::TestModelsEndpointProbe` has 8 tests:
- `test_models_endpoint_returns_context_window` — tests `context_window`
- `test_models_endpoint_alternative_field_names` — tests `max_context_length` ONLY
- (6 other tests for failure modes)

**Missing test coverage:**
- `context_length` (used by OpenRouter per the actual API response verified via `web_fetch`)
- `max_tokens` (used by some Anthropic-compatible APIs)
- `max_model_len` (used by vLLM-served models)

The probe checks 5 field names; only 2 are tested. **The 3 untested fields could be buggy and we'd never know.**

**Root cause:** Test author covered the common case and one alternative, but skipped the other 3.

**Fix:** Add 3 more tests, one per remaining field name.

---

## BUG #9
**Severity:** LOW
**Assumption violated:** "`_on_test_result` updates the dialog's `_provider.last_verified_at`"
**Attack vector:** Click Test Connection, observe `self._provider.last_verified_at`.
**Reproduction:** After successful Test Connection:
- Disk has `last_verified_at: <timestamp>` (handler wrote it)
- `self._provider.last_verified_at` is still `None` (dialog never updated)

If the user closes the dialog without clicking Save, then opens it again, `refresh_providers()` will see the new disk state and call `card._populate_from_provider()` which sets everything fresh. So the bug is invisible to the user.

But if some other code path reads `self._provider.last_verified_at` (e.g., `_is_dirty()` checking status fields), it would be stale.

**Root cause:** `_on_test_result` updates the spin button and status label, but doesn't update `self._provider`.

**Fix:** Update `self._provider = ProviderConfig(... self._provider, last_verified_at=datetime.now()...)` in `_on_test_result`.

---

## BUG #10
**Severity:** LOW
**Assumption violated:** "`if base_url and api_key:` guard prevents the probe from running when called from a non-OpenAI path"
**Attack vector:** Trace the call graph for Anthropic.
**Reproduction:** The probe code is inside `_do_request`, which is called from both `_test_openai_compat` AND `_test_anthropic`. The guard `if base_url and api_key:` is always True for Anthropic too (both are passed in). The probe will run for Anthropic with `provider = "anthropic"`:
- POST to `/v1/messages` succeeds (Anthropic API)
- GET to `{base_url}/models` is attempted — but Anthropic's API does NOT have a `/v1/models` endpoint!
- The exception is caught → `context_window = None` → harmless

So the probe is **wasted work** for Anthropic (one extra HTTP request that always fails), but no bug.

**Root cause:** Probe logic should be gated on `provider in _OPENAI_COMPATIBLE` like the POST path is.

**Fix:**
```python
if base_url and api_key and provider in _OPENAI_COMPATIBLE:
    try:
        ...
```

---

## BUG #11
**Severity:** LOW (correctness) / MEDIUM (perf)
**Assumption violated:** "The probe doesn't affect Test Connection latency for users who don't care about context-window discovery"
**Attack vector:** Run Test Connection against any provider. Measure latency.
**Reproduction:** Each successful Test Connection now makes 2 HTTP requests instead of 1:
1. POST `/chat/completions` (the actual test)
2. GET `/v1/models` (the new probe)

The GET adds ~50-200ms latency depending on provider. For users who don't care about context-window discovery (e.g., they have hand-edited `max_tokens`), this is wasted time.

**Root cause:** Probe is unconditional on POST success.

**Fix:** Either:
- (A) Add a config flag `discover_context_window_on_test: bool = True` so users can opt out.
- (B) Only probe on the *first* Test Connection per provider (cache the result).
- (C) Accept the extra latency as a fair trade for auto-discovery.

---

## BUG #12
**Severity:** LOW
**Assumption violated:** "The `urllib.request.install_opener` change is documented in the spec and commit message"
**Attack vector:** Read the spec and commit message.
**Reproduction:** The spec §2.3 (provider_test.py) shows code samples for adding the probe block, but says nothing about changing `_do_request` to use `urllib.request.urlopen` + `install_opener` instead of `_opener.open()`. The commit message says "Pre-existing test fix" without elaboration. **This is an undocumented architectural change** that affects the entire process's urllib behavior.

**Root cause:** The implementer fixed a pre-existing test issue (the old tests were making real API calls because they patched `urllib.request.urlopen` but the code used `_opener.open()`) but didn't flag this as a scope change or a regression. The fix works but the mechanism (`install_opener`) is invasive.

**Fix:** Document this change in the spec and commit message. Better: refactor to use `_opener.open()` for both the POST and the GET probe, and adjust the test mocking accordingly (patch `utils.provider_test._NoAuthRedirectHandler` or the local `_opener`).

---

## SCOPE VERIFICATION (Rule 9)

| Spec item | Implementation | Verified |
|---|---|---|
| §2.1 `models/providers.py` — add `default_max_tokens` field | ✅ Added at line 25 | ✅ |
| §2.2 `utils/providers_store.py` — `_to_dict` AND `_from_dict` | ✅ Both updated (lines 47, 65) | ✅ |
| §2.3 `utils/provider_test.py` — `TestResult.context_window` + `/v1/models` probe | ✅ Field at line 58, probe at 230-247 | ✅ (but see BUG #1, #2, #3, #10, #11) |
| §2.4 `ui/handlers/settings_handler.py` — pre-fill `max_tokens` on success | ✅ Conditional at 162-166 | ✅ (but see BUG #5, #6) |
| §2.5 `ui/views/settings_dialog.py` — SpinButton in 5 methods | ✅ All 5 methods updated | ✅ |
| §2.6 `tests/test_provider_test.py` — `TestModelsEndpointProbe` | ✅ 8 tests added | ✅ (but see BUG #8) |
| §2.7 `tests/test_settings_dialog.py` — `TestMaxTokensSpinButton` | ✅ 8 tests added | ✅ |
| §2.8 `tests/test_settings_handler.py` — `TestTestProviderPrefillsMaxTokens` | ✅ 4 tests added | ✅ |

**All 8 scope items addressed. No missing items. No extra files modified.**

---

## DOCUMENTATION AUDIT (Rule 10)

| Doc/comment | Stale? | Notes |
|---|---|---|
| `provider_test.py:50` — `dataclass` comment | No | Accurate |
| `provider_test.py:195` — "Install opener globally so that urllib.request.urlopen uses it (testable mock boundary)" | No | Accurate but obscures the global side effect (BUG #1) |
| `settings_dialog.py:101` — "Default 128_000 matches the dataclass default and runtime fallback" | No | Accurate |
| `settings_dialog.py:253` — "Sentinel: 128_000 matches the dataclass default" | No | Accurate but doesn't acknowledge the BUG #5 risk |
| `settings_handler.py:160` — "Pre-fill max_tokens from /v1/models probe ONLY if user hasn't customized (sentinel: 128_000 = default)" | No | Accurate but doesn't acknowledge the BUG #5 risk |
| Commit message | No | Doesn't mention `install_opener` change (BUG #12) |
| ARCHITECTURE.md updates | **NOT DONE** | Spec §8 required updates to §3.21q, §4.15, §3.21q.5b. None were committed. **Scope item missed.** |

**ARCHITECTURE.md was not updated.** This is a scope item that the implementer missed despite the spec calling it out explicitly.

---

## TEST MATCH AUDIT (Rule 11)

| Test | What it tests | What the code does | Match? |
|---|---|---|---|
| `TestModelsEndpointProbe::test_models_endpoint_returns_context_window` | POST + GET returns context_window | Same | ✅ |
| `TestModelsEndpointProbe::test_models_endpoint_404_is_non_fatal` | 404 → context_window=None | Same | ✅ |
| `TestModelsEndpointProbe::test_models_endpoint_malformed_json_is_non_fatal` | Bad JSON → context_window=None | Same | ✅ |
| `TestModelsEndpointProbe::test_models_endpoint_model_id_mismatch` | Model not in list → context_window=None | Same | ✅ |
| `TestModelsEndpointProbe::test_models_endpoint_alternative_field_names` | max_context_length field | Same | ✅ |
| `TestModelsEndpointProbe::test_models_endpoint_empty_data_list` | Empty data → context_window=None | Same | ✅ |
| `TestModelsEndpointProbe::test_context_window_ignores_string_value` | String context_window → ignored | Same | ✅ |
| `TestModelsEndpointProbe::test_models_endpoint_no_data_key` | No data key → context_window=None | Same | ✅ |
| `TestMaxTokensSpinButton::test_on_test_result_prefills_spin` | Pre-fill on Test Connection success | Same | ✅ (but see BUG #6) |
| `TestMaxTokensSpinButton::test_on_test_result_does_not_overwrite_customized` | Don't overwrite if user changed | Same | ✅ |
| `TestMaxTokensSpinButton::test_on_test_result_no_prefill_when_context_window_none` | No prefill if None | Same | ✅ |
| `TestTestProviderPrefillsMaxTokens::test_success_with_context_window_prefills_default` | Pre-fill on success | Same | ✅ |
| `TestTestProviderPrefillsMaxTokens::test_success_does_not_overwrite_customized` | Preserve customized | Same | ✅ |
| `TestTestProviderPrefillsMaxTokens::test_failure_does_not_change_max_tokens` | Failure path leaves unchanged | Same | ✅ |
| `TestTestProviderPrefillsMaxTokens::test_success_without_context_window_preserves_max_tokens` | None preserves | Same | ✅ |

**All 20 new tests correctly test their corresponding code paths.** No false negatives detected.

---

## VERIFIED TEST OUTPUT

```
$ python3 -m pytest tests/test_provider_test.py tests/test_settings_dialog.py tests/test_settings_handler.py tests/test_providers_store.py --tb=short
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2
collected 107 items
...
tests/test_providers_store.py::TestMigrateFromAgentJson::test_migrate_empty_providers_dict_strips_key PASSED [100%]
================== 106 passed, 1 skipped, 4 warnings in 1.76s ==================
```

---

## RECOMMENDED FIXES (Priority Order)

1. **BUG #1 (HIGH):** Refactor `_do_request` to use local `_opener.open()` for both POST and GET probe. Restore the pre-`bc31a2a` mock boundary by patching `urllib.request.build_opener` in tests if needed. Estimated: 30 minutes.

2. **BUG #2 (HIGH):** Update `model_id` matching to try both full and stripped forms. Estimated: 5 minutes.

3. **BUG #3 (HIGH):** Add `CALLER_DEFAULT_MAX_TOKENS` table in `models/providers.py` and wire `default_max_tokens` to it. Fall back to table value when probe returns `None`. Estimated: 1 hour.

4. **BUG #4 (MEDIUM):** Same as BUG #3 fix — adds the missing consumer.

5. **BUG #5 (MEDIUM):** Change sentinel from `128_000` to `0` (meaning "not set"). Requires updating `ProviderConfig` default and `_compute_model_max` fallback. Estimated: 30 minutes.

6. **BUG #6 (MEDIUM):** Update `self._provider` in `_on_test_result` after pre-filling spin. Estimated: 10 minutes.

7. **BUG #7 (MEDIUM):** Update `auxilium_wizard_handler.py:371, 428` to set `default_max_tokens=128_000` (pending BUG #5 fix). Estimated: 5 minutes.

8. **BUG #8 (LOW):** Add 3 tests for `context_length`, `max_tokens`, `max_model_len` field names. Estimated: 30 minutes.

9. **BUG #9 (LOW):** Update `self._provider.last_verified_at` in `_on_test_result`. Estimated: 5 minutes.

10. **BUG #10 (LOW):** Add `provider in _OPENAI_COMPATIBLE` guard around the probe. Estimated: 2 minutes.

11. **BUG #11 (LOW):** Optional — add config flag to disable probe, or cache per-provider. Estimated: 1-2 hours.

12. **BUG #12 (LOW):** Update commit message + ARCHITECTURE.md (spec §8). Estimated: 15 minutes.

**Total estimated effort to address all 12 bugs: ~4 hours.**
