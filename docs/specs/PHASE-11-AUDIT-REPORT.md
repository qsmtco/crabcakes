# PHASE-11 Audit Report — AdversarialDebugger + ARCHITECTURE.md

**Scope:** PHASE-10, PHASE-10.5, PHASE-11 (the 3 phases completed in this session)
**Method:** 12 attack scenarios on `_resolve_caller_key` + 10 attack scenarios on `_call_llm_streaming` + cross-reference against `docs/ARCHITECTURE.md` §3.21m and §12
**Scripts:** `scripts/audit_attack_scenarios.py` (resolution), `scripts/audit_streaming_scenarios.py` (streaming)

---

## Part 1: AdversarialDebugger Audit

### A. `_resolve_caller_key` — 12 scenarios

| # | Scenario | Result | Severity |
|---|----------|--------|----------|
| 1 | Unknown caller (`'gpt-future'`) | PASS — fails loudly at caller lookup | OK |
| 2 | Empty string caller (`''`) | PASS — falls through to derivation | OK |
| 3 | None caller | PASS — falls through to derivation | OK |
| 4 | provider_cfg=None, model slashed | PASS — legacy fallback works | OK |
| 5 | provider_cfg=None, model no slash | PASS — returns model as-is | OK |
| 6 | Mixed-case caller (`'OpenAI'`) | PASS — lowercased correctly | OK |
| 7 | Multi-slash default_model | PASS — takes first segment | OK |
| 8 | Whitespace-padded caller | PASS — fails loudly (whitespace not stripped) | OK |
| 9 | provider_cfg=None, model=empty | PASS — returns empty string, fails at lookup | OK |
| 10 | Slash in caller (`'openai/v2'`) | PASS — fails loudly | OK |
| 11 | All 5 known callers round-trip | PASS — all resolve to themselves | OK |
| 12 | `_PROVIDER_STREAMERS.get('')` and `.get(None)` | PASS — both return None | OK |

**Summary: 12/12 scenarios pass.** The resolution logic is robust against all the attack vectors I could think of. The priority order (explicit > derivation > legacy) works correctly, the fallbacks are correct, and the lowercasing prevents the mixed-case bug that was caught in P8. **No real bugs found.**

**One observation:** The lowercasing happens in `_resolve_caller_key`, not at the storage site. This means the dialog shows the user's input verbatim (`"OpenRouter"`) but the resolver returns lowercase. The asymmetry is documented in the PHASE-10.5 post-mortem as a design smell, not a bug. The P10.5b spec corrections note flags this for future reference.

### B. `_call_llm_streaming` — 10 scenarios

| # | Scenario | Result | Severity |
|---|----------|--------|----------|
| 1 | Streamer raises mid-iteration | PASS — exception propagates, partial state visible | OK |
| 2 | Streamer yields zero events | PASS — returns empty response | OK |
| 3 | `tool_call_delta` missing `'index'` key | **FAIL** — KeyError, crashes runtime | **BUG** |
| 4 | `text_delta` with `content=None` | PASS — None coerced to empty string | OK |
| 5 | `on_text_delta` callback raises | PASS — `_dispatch` catches and logs | OK |
| 6 | `_dispatch` source review | PASS — catches exceptions, logs via `logger.exception` | OK |
| 7 | Two concurrent calls (shared `_on_text_delta`) | NOTE — race condition exists, not exploitable in practice | INFO |
| 8 | Unknown event type from streamer | PASS — silently skipped | OK |
| 9 | `done` event with no prior events | PASS — returns empty content + tool_calls | OK |
| 10 | Invalid JSON in tool arguments | PASS — stored verbatim, validated at execution | OK |

**Summary: 9/10 pass, 1 real bug, 1 informational note.**

#### BUG-1: KeyError on missing `'index'` in tool_call_delta

**Location:** `agent/runtime.py` line 1361 (inside `_call_llm_streaming`):
```python
elif ev.type == "tool_call_delta":
    idx = ev.data["index"]   # ← KeyError if 'index' is missing
```

**Trigger:** Any streamer that yields a `tool_call_delta` event without an `'index'` key. Anthropic's streaming format, for example, does not always include `index` for single-tool responses — it implicitly assumes index 0.

**Impact:** Runtime crashes with `KeyError: 'index'`. The error propagates to `_call_llm` (line 1283), which propagates to `send_message` (the agent loop), which fires `on_error` and the session dies. The user sees the chat freeze mid-response.

**Fix:**
```python
idx = ev.data.get("index", 0)
```

**Effort:** 1-line change. **Severity: Medium** — depends on whether Anthropic's streamer is exercised in practice. The P10.5a verification didn't catch this because the OpenAI mock streamer always includes `'index'`.

**Recommendation:** Fix in PHASE-11.5 (a quick follow-up). Also add a regression test.

#### NOTE-1: Concurrent calls to `_call_llm_streaming` share `_on_text_delta`

**Observation:** `_on_text_delta` is a single attribute on the runtime instance. If two threads call `_call_llm_streaming` simultaneously (unlikely but possible), the last writer wins.

**Mitigation already in place:** Each session has its own conversation and its own `_call_llm` invocation. In practice, `_call_llm_streaming` is called from a single thread per session. The `_dispatch` mechanism uses `GLib.idle_add` to marshal callbacks to the GTK main thread, so even if two streams were active, the callbacks would be serialized.

**Verdict:** Not a real issue, but the architecture would be cleaner if `_on_text_delta` were a per-session attribute (a dict keyed by `session_key`) rather than a single instance attribute. **Out of scope for the current phases.**

---

## Part 2: ARCHITECTURE.md Audit

### A. Compliance with §3.21m (Runtime)

§3.21m states:
> **Providers:** OpenAI (`openai/*`), MiniMax (`minimax/*`), Anthropic (`anthropic/*`) — selected by model prefix.

**PHASE-10 change:** Added 2 more callers (`openrouter`, `zai`) and introduced explicit `caller` field.

**Finding:** §3.21m is **stale**. It mentions 3 providers; the code now supports 5. The "selected by model prefix" mechanism is now a fallback, not the primary path.

**Fix:** Update §3.21m to read:
> **Providers:** OpenAI (`openai/*`), MiniMax (`minimax/*`), Anthropic (`anthropic/*`), OpenRouter (`openrouter/*`), ZAI (`zai/*`). Selected by explicit `caller` field on the provider config (persisted in `providers.yaml`); falls back to model-prefix derivation for legacy configs. See §12 for resolution details.

**Effort:** 1-line text update. **Severity: Low** — documentation drift, not a code bug.

### B. Compliance with §12 (Provider Resolution & API Caller)

§12 was added in PHASE-9 (P9 audit confirmed). It describes:
- The 3-tier resolution priority (explicit > derivation > legacy)
- The 5 built-in callers
- The streamer resolution (symmetric with caller resolution, post-PHASE-10.5a)
- The Test Connection override

**PHASE-10/10.5/11 compliance:** ✓ All changes conform to §12. The `_call_llm_streaming` method uses `_resolve_caller_key` (PHASE-10.5a), the 5 callers are all supported, the streamer dict mirrors the caller dict. No boundary crossings.

**Finding:** §12 is accurate. No update needed.

### C. Compliance with §14 (Principles to Preserve)

The 7 principles:

1. **Gateway is foundational.** — Not touched by PHASE-10/10.5/11. ✓
2. **Models are pure data.** — The `caller` field on `LLMProviderConfig` is pure data. ✓
3. **UI is composed, not inherited.** — Not touched. ✓
4. **Callbacks are the communication mechanism.** — Streaming still uses callbacks. ✓
5. **Checkpoints over shortcuts.** — PHASE-10.5b added spec corrections to preserve this. ✓
6. **Structure before features.** — The class-method refactor (PHASE-11) **enforces** this: streaming and blocking are now sibling methods, not a method and a function-that-takes-self. ✓
7. **Comments for humans.** — The PHASE-11 refactor added a comment explaining why the method exists in its current form. ✓

**Finding:** All 7 principles preserved. The PHASE-11 refactor actively strengthens principle #6 by removing the structural asymmetry.

### D. Internal consistency check

**§3.21m** mentions 3 providers (OpenAI, MiniMax, Anthropic).
**§12** mentions 5 providers (adds OpenRouter, ZAI).

**Finding:** §3.21m and §12 are **inconsistent**. §3.21m is the older text. §12 was added in PHASE-9 and is the current truth.

**Fix:** Update §3.21m to match §12. This is the same fix as Part 2.A above.

---

## Part 3: What's Solid

1. **The 3-tier resolution priority** (explicit > derivation > legacy) is well-designed and robust. All 12 attack scenarios pass. The priority is documented in both the code (docstring) and the architecture (§12).

2. **The streaming/blocking symmetry** is now complete. Both paths use `_resolve_caller_key`, both look up in caller-keyed dicts, both produce the same error style. A reader who understands one path understands the other.

3. **The regression test** (`TestStreamingSignature`) is genuinely adversarial. It caught the `-1`/`-2` count adjustments correctly, and it would catch any future signature drift across three places (method, production caller, test patches).

4. **The class-method refactor** (PHASE-11) actively strengthens architecture principle #6 ("Structure before features"). The streaming and blocking paths are now structurally symmetric, not just behaviorally symmetric.

5. **Spec corrections** (PHASE-10.5b) are a cheap insurance policy. Future implementers won't land in the wrong lines.

6. **The error messages** are actionable. They include the offending value (with `!r` formatting for visibility), the model name, and a pointer to the Settings dialog. A user hitting these errors has enough context to fix the issue.

---

## Part 4: What's Shaky

1. **§3.21m is stale** (mentions 3 providers, not 5). Documentation drift. Low severity, but it's a one-line fix and the doc is supposed to be the law.

2. **BUG-1: KeyError on missing `'index'` in tool_call_delta.** Medium severity. A real bug in `_call_llm_streaming` that wasn't caught by the existing tests. The OpenAI mock always includes `'index'`, so the test suite never exercised the missing-key path. Fix: `ev.data.get("index", 0)`.

3. **The regression test reads source files as strings.** This works but is fragile. A future refactor that renames the method or restructures the production caller could break the test in confusing ways. The test's `expected_params` list duplicates the method signature, creating two sources of truth.

4. **The `_call_llm_streaming` method has a 9-parameter signature.** This is on the edge of "too many parameters" territory. Future additions would push it over. A `StreamingCallKwargs` TypedDict would help.

5. **The `_PROVIDER_CALLERS` and `_PROVIDER_STREAMERS` dicts are still module-level globals.** The PHASE-11 refactor moved the function to a class method but left the registries as module-level dicts. This means a test that patches `_PROVIDER_STREAMERS` affects all `AgentRuntime` instances globally. The class-method refactor was incomplete — the registries should arguably be class attributes, so each `AgentRuntime` subclass (or test fixture) can override them.

---

## Part 5: What Needs a Follow-up Phase

### Should do (high value, low cost)

1. **PHASE-11.5: Fix BUG-1 (KeyError on missing 'index').** 1-line code change + 1 new regression test. ~15 minutes. Closes the only real bug found in this audit.

2. **Update §3.21m** to mention all 5 providers and the explicit-caller resolution. 1-line doc change. ~5 minutes.

### Nice to have

3. **PHASE-12 candidate: Refactor `_PROVIDER_CALLERS` and `_PROVIDER_STREAMERS` to class attributes.** This would let tests patch streamers on a per-instance basis without `unittest.mock.patch`. ~2 hours.

4. **Add a `StreamingCallKwargs` TypedDict.** Reduces the 9-parameter signature to 1 kwargs dict. ~30 minutes.

5. **Add an `__all__` to `agent/runtime.py`.** Makes the public surface explicit. Prevents future "is this public?" ambiguity. ~10 minutes.

### Out of scope (debt, not bugs)

6. **The 13 pre-existing test failures** in `test_agent_builder_handler.py` and `test_special_agents.py` are still debt. A "Phase 0" sweep is high-leverage. Not blocking.

7. **The 4 `TestStreaming` tests could be parameterized** with `pytest.mark.parametrize`. Same pattern, 4 different mock streamers. Test-readability improvement.

8. **The `expected_params` list in the regression test duplicates the method signature.** A `Literal` type or TypedDict would prevent drift.

---

## Part 6: Summary

| Category | Count | Details |
|----------|-------|---------|
| Real bugs found | 1 | BUG-1: KeyError on missing `'index'` |
| Stale docs | 1 | §3.21m mentions 3 providers, not 5 |
| Test coverage gaps | 1 | Missing-key path for `tool_call_delta` not exercised |
| Design smells | 3 | Module-level registries, 9-param signature, stringly-typed test |
| Principles preserved | 7/7 | All ARCHITECTURE.md §14 principles intact |

**Overall verdict: The 3 phases are in good shape.** One real bug (BUG-1), one stale doc (§3.21m), and a few design smells. The structural changes are clean, the tests are adversarial, and the architecture principles are preserved.

**Recommended next step:** PHASE-11.5 — fix BUG-1 + update §3.21m. ~20 minutes total. Closes the only real issue found in this audit.

If the user wants to stop here, the app is in a working state. The 13 pre-existing test failures are debt, not regressions. The BUG-1 is latent (only triggered by streamers that omit `'index'`, which the current test suite doesn't exercise).
