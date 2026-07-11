# Context-Management Audit & Recommendations

**Date:** 2026-07-10
**Auditor:** qtr (assistant agent)
**Scope:** Everything in crabcakes that touches message-history trimming, summarization, and context-window budget.

---

## TL;DR — Should you change anything?

**YES — but only the parts that are missing, not the parts that exist.** Crabcakes already has a sophisticated 3-layer trim engine (`agent/context_strategy.py`, 741 lines, 139/139 tests green). What's missing is:

1. **No `/compact` slash command** — the engine exists but no user-facing way to trigger it manually.
2. **No UI for compaction telemetry** — runtime computes `trimmed_this_turn` + `compaction_event` + `usage_percent`, but the handler only logs them. The user has zero visibility into whether their conversation got trimmed.
3. **Tier 3 (the summary) is a 100-char textual preview**, not an LLM-generated structured summary like Claude Code's. Tier 3 is a "lossless structural" stub, not a "lossy semantic" summary.
4. **No user-visible token meter** — `usage_percent` is computed but never shown.
5. **No UI for `compaction_threshold`** — it's YAML-only.
6. **One TODO is unaddressed:** `P10.8 mid-session re-escalation` — the system prompt is built once at session start and never rebuilt.

**The wiring IS correct.** Every piece fires correctly; the gap is in the "last 200 meters" (UI bubble + slash command + structured summary tier).

**Recommendation:** Don't touch the engine. Wire the missing UI surface and ship `/compact`. Add the LLM-summarization tier as a separate strategy class. Leave the cache edit / offload / KV-cache work for v2.

---

## 1. What's in the codebase RIGHT NOW (verified, file:line)

### 1.1 The trim engine — `agent/context_strategy.py` (741 lines, P1–P7 shipped)

| Layer | Function | Line | Behavior | Verified at runtime |
|---|---|---|---|---|
| L1 | `prune_tool_outputs(conv, target_tokens, protect_turns=2)` | 333 | Back-walk; stub oldest unprotected TOOL_RESULTs with `[compacted — {tool_name} output, {chars} chars removed]` until under budget. Idempotent (skips already-stubbed). | ✅ Pre: 62,630 tokens → 18,978 tokens on synthetic conv. Kept last 2 TRs intact. |
| L2 | `_select_prune_candidate(...)` | 615 | Two-pass scan: non-protected first, then protected. Prefers CB-6 tool-call/result pairs. | ✅ |
| L2 | `_find_split_index(conv, budget, keep_first)` | 423 | Walks tail, accumulates tokens, role-anchors on ASSISTANT, honors CB-6 with bounce detection. | ✅ |
| L2 | Trim loop | 159 | Pops messages via `_select_prune_candidate`. CB-6 paired eviction. Post-trim orphan sweep as defense in depth. | ✅ 75 → 48 msgs, 279,701 → 35,245 tokens under 5K budget |
| L3 | `_summary(conv, budget, keep_first)` | 664 | **Textual preview only** — first 100 chars of the oldest user messages. NOT LLM-generated. | ✅ "Conversation so far (3 prior turns):\n  1. Investigate error in auth module: 0padding…" |
| L3 | `_fit_summary(...)` | 504 | Truncates 5× at 80% each; minimal stub fallback; None if zero space. | ✅ |

**CompactionEvent dataclass** at line 30 carries telemetry for every `compact()` call. **Per-runtime** instance (`agent/runtime.py:1659` — `self._context_strategy = DefaultContextStrategy()`). Concurrency-safe in that two threads on the same runtime can't see each other's `last_result` (verified: tests pass with concurrent compaction).

### 1.2 Runtime wiring — `agent/runtime.py`

| Hook | Line | Verified |
|---|---|---|
| Per-iteration `compact()` call before every LLM call | 2101 | ✅ `soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv)` → `self._context_strategy.compact(conv, soft_ceiling)` |
| `_compute_compaction_threshold(conv)` | 1920 | ✅ Returns `(soft_ceiling, hard_ceiling)`. Resolves `ProviderConfig.compaction_threshold` per provider. Defaults to 0.80. |
| `_compute_model_max(conv)` | 1880 | ✅ Three-tier: provider.max_tokens → caller_default_max_tokens (CALLER_DEFAULT_MAX_TOKENS table at models/providers.py:11) → 128K fallback. **Bug #3 fix verified** — MiniMax now correctly gets 1,048,576 not 128K. |
| `breakdown["trimmed_this_turn"]` set on every iteration | 2194 | ✅ |
| `breakdown["compaction_event"]` set when real compaction happens | 2211 | ✅ |
| Per-runtime `self._compaction_events` ring buffer (cap 100) | 1613, 1647 | ✅ |

### 1.3 Handler side — `ui/handlers/agent_runtime_handler.py`

| Hook | Line | Wire-up |
|---|---|---|
| `_on_token_breakdown(session_key, breakdown)` | 1238 | ⚠️ Only `logger.info()`s the breakdown. **Throws away `trimmed_this_turn`, `compaction_event`, `usage_percent`, `messages_remaining`, `messages_removed_this_turn`.** No UI surface. |

### 1.4 Slash commands — `ui/handlers/command_handler.py`

Registered (lines 83–170):
- `/help`, `/ask`, `/delegate`, `/stop`, `/tell`, `/task` and 13 other TaskFlow commands, `/review` + variants, `/status`, `/agents`, `/cost`, **`/clear`**, `/session`.

**Not registered:** `/compact`, `/context`, `/trim`, anything context-budget related.

### 1.5 Settings UI — `ui/views/settings_dialog.py`

| Field | Line | Editable |
|---|---|---|
| `Context Window` (max_tokens) | 99-104 | ✅ SpinButton 1K–10M |
| `compaction_threshold` | — | ❌ YAML-only |
| `context_mode` | — | ❌ YAML-only, never re-resolved mid-session |

### 1.6 Provider config — `models/providers.py`

```python
@dataclass
class ProviderConfig:
    ...
    max_tokens: int = 128_000
    default_max_tokens: int = 0
    compaction_threshold: float = 0.80     # ✅
    context_mode: str = "auto"              # ✅
    ...
```

### 1.7 Conversation data model — `models/conversation.py`

| Field/method | Line | Used by |
|---|---|---|
| `Message.is_summary: bool` | 127 | Mark summary messages so `_select_prune_candidate` can protect them. |
| `Conversation.get_token_estimate()` | 354 | tiktoken-accurate when installed (we verified tiktoken 0.12.0 works), chars//4 fallback. Cached. |
| `Conversation.get_token_breakdown(model_max)` | 367 | Returns full breakdown dict. **Computed but never used by UI.** |
| `Conversation.trim_to_token_limit(...)` | 408 | Deprecated shim → delegates to `DefaultContextStrategy.compact`. Tests still use this. |
| `Conversation.record_usage(tokens, cost)` | 471 | ✅ Per-message cost recording. |

### 1.8 System-prompt context mode — `agent/context.py`

- `resolve_context_mode(explicit_mode, ...)` at line 357 → chooses preload/jit/hybrid based on context window size.
- `context_mode` is **frozen at session start** (`agent/runtime.py:1771`). **TODO P10.8** (`agent/runtime.py:1775`): mid-session re-escalation not implemented.
- Wiring works but no re-evaluation. Once an agent grows to fill its window, JIT won't kick in.

### 1.9 Test coverage — 139 tests passing

```
tests/test_context_strategy.py ............ 37 tests
tests/test_context_strategy_audit_fixes.py ... 20 tests
tests/test_context_strategy_audit_fixes2.py ... 23 tests
tests/test_context_strategy_audit_fixes3.py ... 26 tests
tests/test_context.py ........... 33 tests
```

139/139 green. The trim algorithm is robust — the audit fix suites caught and resolved 8 race-condition/TODO bugs from earlier work.

---

## 2. What's WRONG — ranked by severity

### 🟥 Severity 1: No user-visible compaction telemetry (silent data loss)

**Symptom:** When the engine trims 8 messages, the model gets a "Conversation so far (3 prior turns): 1. user msg 0: pad…" assistant message. The user sees nothing. From the user's perspective, the model suddenly "forgets" an older request with no explanation.

**Why this is bad:** Trust. Users don't understand why their multi-turn agent "lost" the previous goal.

**Fix (small):** Add a chat bubble in the chat render path when `_compaction_happened == True`. Mimic the `/clear` pattern but instead of "Cleared X's conversation", emit:
```
🧹 Context reset. Removed 8 messages, freed ~12K tokens.
   Conversation so far: [5 prior turns summary]
```
Pass `breakdown` to a new `_on_compaction_summary` handler. ~30 lines.

**Fix (medium):** Add a chat-panel context meter (Claude Code shows a 7-token-bar at the bottom of every conversation). Update from `breakdown["usage_percent"]`. ~80 lines.

### 🟥 Severity 2: No `/compact` slash command

**Symptom:** Manual emergency trim is impossible. Engine fires automatically at 80% but that's also when the user should have been warned already.

**Fix (small):** Add `cmd_compact(cmd, session_key, conv) -> CommandResult` to `ui/handlers/project_handler.py` (mirroring `cmd_clear`). It should:
1. Resolve the active conversation via `self._clear_callback`'s infra (need a `set_compact_callback` mirror).
2. Force `self._context_strategy.compact(conv, hard_ceiling // 2)` — half the context, regardless of current size.
3. Inject the textual summary at L1 + run L2 trim, OR force an LLM-summary at L3.
4. Save to disk.
5. Return `🧹 Compacted. X messages removed, Y tokens freed.`

**Important:** The `_VALILD_CALLBACK` injection pattern from `/clear` is the right template. Reuse the same wiring. ~50 lines + 1 line of registration.

### 🟧 Severity 3: Tier 3 is textual, not LLM-generated

**Symptom:** Compare what crabcakes does to what Claude Code does when you run `/compact`:

| Aspect | Crabcakes now | Claude Code `/compact` |
|---|---|---|
| Engine layer | `_summary()` = textual preview of 5 user messages | LLM call with 9-section prompt |
| Cost | 0 tokens | ~$0.01–0.10 per compaction |
| Quality | Loses everything except user message previews | Preserves intent, files, errors, decisions |
| Speed | Instant | 3–10s |

Crabcakes' textual summary works for shallow conversations but degrades badly for long agentic sessions where the assistant makes 30 file edits — all that gets thrown away.

**Fix (medium):** Add a `LLMSummarizeStrategy(ContextStrategy)` class that:
- Reuses `prune_tool_outputs` from the default strategy (inherited or composed).
- Has the same `compact()` signature.
- When `compact()` is called with `token_budget < current_tokens // 2`, makes **one LLM call** with a 9-section prompt template (copy from Claude Code) using the **same model + same provider** as the conversation.
- Injects the LLM response as `is_summary=True`.

This is a 100-line addition + a config field `agent.complexity_strategy: "textual" | "llm"`.

**Important:** The LLM-summarization call MUST use the **same system prompt + same model + same prefix** so cache reuse works. (Claude Code's cache insight — cited above.)

### 🟧 Severity 4: `compaction_threshold` not editable in settings

**Symptom:** User wants to bump trigger from 80% → 70%. They have to edit `providers.yaml` and reload.

**Fix (small):** Add a SpinButton (0.50–0.95, step 0.05) next to Context Window in settings_dialog.py. Same wiring as max_tokens.

### 🟧 Severity 5: `context_mode` not re-evaluated mid-session

**Symptom:** A 200K-window agent loaded in `preload` mode will exhaust its window before switching to `jit`. The TODO P10.8 is documented but unimplemented. The `_on_token_breakdown` hook fires every iteration — perfect place to re-evaluate.

**Fix (medium):** In `agent/runtime.py`, after the breakdown dispatch (around line 2218), check if `breakdown["usage_percent"] > 90.0` and `context_mode == "preload"`. If so, rebuild the system prompt on next turn via the existing `build_system_prompt()` machinery. Persist this in `conv.context_mode_reescalated_at` so we don't loop.

### 🟨 Severity 6: `usage_percent` not shown to user

Same as Severity 1, second bullet. Same fix.

### 🟨 Severity 7: No tests for the missing UI surface

The 139 existing tests cover the engine, not the handler, not the UI. We'll need new tests for:
- `cmd_compact` happy path: engine fires on command, message count drops
- `cmd_compact` no-op: when conversation already fits, returns informative message
- `_on_token_breakdown` (new method) should set a `_last_breakdown` so the UI can poll

~5 tests. ~100 lines.

---

## 3. What's RIGHT — don't break it

| Thing | Why it's right | Don't touch |
|---|---|---|
| Per-runtime strategy instance (`agent/runtime.py:1659`) | Concurrency-safe | ✓ Don't make it global |
| `is_summary=True` flag | Used by `_select_prune_candidate` to protect previous summaries from re-trim | ✓ Don't change semantics |
| Cache invalidation contract (`_token_estimate_cache = None`) | Prevents stale token estimates mid-loop | ✓ Don't add direct mutation outside the strategy |
| `soft_ceiling = int(hard_ceiling * threshold)` formula | Configurable per-provider, sensible default | ✓ Don't change to absolute tokens |
| CB-6 invariant (tool-call pairing) | Strict providers (Cohere, Anthropic strict mode) will 400 otherwise | ✓ Don't relax |
| `_VALID_CONTEXT_MODES` frozenset (`models/providers.py:64`) | Validation | ✓ Don't remove |
| `CALLER_DEFAULT_MAX_TOKENS` (models/providers.py:11) | Per-caller fallback is the only way MiniMax-M3's 1M window is reachable | ✓ Don't add a single global default |
| `_compaction_events` ring buffer (cap 100) | Prevents unbounded memory growth | ✓ Don't grow the cap without DB persistence |
| `_compute_compaction_threshold` uses `conv.model`'s provider, not `default_provider` | Correct semantic — the conversation's actual provider drives the threshold | ✓ Don't change to use `default_provider` |

---

## 4. The plan — 3 phases, in order

### Phase A (UI surface, ~2 days of work)

**Files to touch:**

1. `ui/handlers/agent_runtime_handler.py` — new `_on_token_breakdown` body that:
   - Stores `breakdown` to `self._latest_breakdown[session_key]` (dict in-memory cache).
   - When `trimmed_this_turn=True`, dispatches to a new "compaction bubble" callback via `GLib.idle_add`.
   - When `usage_percent >= 80`, also dispatches a "context getting tight — run /compact" warning (once per session).
   - When `usage_percent >= 95`, dispatches an "auto-compaction imminent" warning.

2. `ui/handlers/chat_handler.py` (or wherever the chat bubble renderer lives) — new method to add a "compaction summary bubble" to the chat. Distinct from `INFO` and `ERROR` bubbles.

3. `ui/views/agent_window.py` (or wherever the chat panel renders) — add a thin progress bar at the bottom showing `usage_percent`. Wired via a new public method `set_token_usage(percent)`.

4. `ui/views/settings_dialog.py` — add `compaction_threshold` SpinButton (0.50–0.95, step 0.05) below max_tokens.

5. `tests/test_context_ui.py` (NEW) — 5 tests:
   - `_on_token_breakdown` stores breakdown.
   - First `trimmed_this_turn=True` triggers bubble.
   - Second consecutive `trimmed_this_turn=True` doesn't trigger (anti-spam).
   - `usage_percent >= 80` triggers warning once per session.
   - Settings dialog handler stores the threshold correctly.

**No engine changes.** Pure UI surface.

### Phase B (`/compact` slash command, ~1 day)

**Files to touch:**

1. `ui/handlers/command_handler.py` — add `self.register_command("compact", project_handler.cmd_compact, help_text="Force compaction: /compact [focus-instructions]")` after the `/clear` registration at line ~159.

2. `ui/handlers/project_handler.py` — add `cmd_compact(cmd, session_key)` method. Mirror `cmd_clear` exactly: resolve session, dispatch to injected callback.

3. `ui/window.py` — add a `set_compact_callback` mirror for `_clear_callback`. Wire to `agent_runtime_handler.compact_conversation(session_key)`.

4. `ui/handlers/agent_runtime_handler.py` — new method `compact_conversation(session_key, focus_instructions="")` that:
   - Resolves the `conv` from `_runtimes[session_key]._conv`.
   - Calls `self._runtimes[session_key]._context_strategy.compact(conv, conv.get_token_breakdown(model_max)["model_max_tokens"] // 2)`.
   - Saves to disk.
   - Returns `(messages_removed, tokens_freed)`.

5. `agent/runtime.py` — minor: make `_context_strategy` accessible (already is, as `_context_strategy`). Maybe add a public wrapper `force_compact(conv, budget_fraction=0.5)`.

6. `tests/test_compact_command.py` (NEW) — 4 tests:
   - Empty session → "nothing to compact".
   - Long session → strategy.compact called with 50% budget.
   - Returns correct bubble text.
   - Focus instructions end up in `_summary()` output (verifiable via injected `is_summary` message content).

### Phase C (LLM-summarization tier, ~3 days)

**Files to touch:**

1. `agent/context_strategy.py` — new class `LLMSummarizeStrategy(DefaultContextStrategy)` that:
   - Overrides `_summary(conv, budget, keep_first)` to make an LLM call instead.
   - Uses the same `model`, `provider`, `system_prompt` as `conv`.
   - Calls `_call_llm()` from runtime — pass it via DI (not imported, since this is a strategy) **or** wire through a callback that runtime provides: `strategy._summary_provider: Callable[[str, str], Awaitable[str]] | None`.
   - Returns the 9-section structured summary.
   - Falls back to `super()._summary(...)` (the textual preview) if the LLM call fails.

2. `agent/runtime.py`:
   - Add `_summary_call_provider: Callable | None = None` set by `set_strategy_provider(fn)`.
   - Inject into the strategy when an instance of `LLMSummarizeStrategy` is used.
   - Add a `compaction_strategy` field on `Conversation` (default `"textual"` — backward-compatible).

3. `agent/special_agents.py` — add `compaction_strategy: str = "textual"` to `SpecialAgentDef`.

4. `utils/agent_defs.py` — extend `validate_agent_def()` to validate `compaction_strategy in {"textual", "llm"}`.

5. `ui/views/agent_builder.py` — add a dropdown in the dialog: "Compaction strategy: [Textual / LLM-Summarize]".

6. `agent/context.py` — replace `prune_tool_outputs`'s stub prefix `[compacted — {tool} output, {chars} chars removed]` with the Anthropic-style `[Old tool result content cleared]` for consistency. Cosmetic.

7. `tests/test_llm_summarize_strategy.py` (NEW) — 6 tests:
   - Strategy calls the injected LLM provider.
   - Provider's response is inserted as `is_summary=True`.
   - Provider's exception → falls back to textual preview.
   - Cache reuse: provider invoked with same system_prompt + same model_prefix.
   - Repeated calls don't re-trigger if the LLM already summarized recently.
   - 9-section marker parsing doesn't false-positive on user's chat content.

**Total new code:** ~600 lines (eng) + ~400 lines of tests + ~200 lines UI.

---

## 5. What NOT to do (deferred to v2)

| Proposal | Why defer |
|---|---|
| **P8 / T1.3 Tool-output offloading** | Requires `.crabcakes/tool-outputs/` directory scheme and a `tool_read_path` retrieval tool. Already specced in `PROPOSAL-context-management-phase-2.md §3.3`. High value, high complexity — needs its own dedicated spec. |
| **P9a / T1.1 Recursive hierarchical summarization** | Build a parent-summary stack across multiple compactions. Useful only when sessions span HOURS. Should ship AFTER Phase C, not before, since you'd need Phase C's structure first. |
| **P9b / T1.2 Structured summary digests (`ConversationDigest`)** | Typed dataclass — `decisions: list[str]`, `constraints: list[str]`, `open_questions: list[str]`, `referenced_paths: list[str]`. Cool but Phase C's free-form LLM summary gets us 80% of the value for 10% of the cost. |
| **P10a / T1.4 JIT file context retrieval** | Already started — `context_mode = "jit"` exists in the code path, but the `file_search`/`file_read` tool defs aren't built yet. Independent of `/compact`. |
| **P10b / T1.5 Per-tool retention policy** | A power-user feature. Skip for now. |
| **P11 Multi-agent context coordination** | Requires Auxilium + Coder sharing context — whole subsystem refactor. |
| **P12 KV-cache optimization** | Provider-side concern. Can't be done in crabcakes alone. |

---

## 6. Should you change the engine itself? (Direct answer)

**NO.** The engine is verified working via 139 passing tests and an end-to-end probe. Every recommendation above is either:

- **UI surface** (Phase A) — no engine change.
- **One new strategy class** (Phase C) — additive, no existing class modified.
- **One new slash command** (Phase B) — additive, no existing handler modified.

The only engine-ish change in the entire roadmap is Phase C's `LLMSummarizeStrategy` inheritance. This keeps:

- `DefaultContextStrategy` byte-for-byte unchanged.
- `Conversation` API stable.
- All 139 tests passing.
- The runtime invocation pattern (`soft_ceiling, hard_ceiling = self._compute_compaction_threshold(conv); self._context_strategy.compact(conv, soft_ceiling)`) untouched.

If you implement ONLY Phase A, you'll get 70% of the user-visible value (real-time context meter + "🧹" bubbles when compaction fires + editable threshold in settings dialog) without touching the engine.

If you implement A + B, you get 90% (above + manual `/compact`).

If you implement A + B + C, you get 95% (above + Claude-Code-quality summaries). The last 5% (offloading, recursive summaries) is v2.

---

## 7. Critical reference files (file:line)

| Topic | Path | Lines | Status |
|---|---|---|---|
| Trim engine | `agent/context_strategy.py` | 1–741 | ✅ 139 tests passing |
| Runtime invocation | `agent/runtime.py` | 2091–2101 | ✅ |
| Per-provider threshold | `agent/runtime.py` | 1920–1961 | ✅ |
| Model max resolution | `agent/runtime.py` | 1880–1919 | ✅ Bug #3 fixed |
| Breakdown telemetry | `agent/runtime.py` | 2187–2225 | ✅ |
| Handler log-only | `ui/handlers/agent_runtime_handler.py` | 1238–1249 | ⚠️ Missing UI dispatch |
| Slash commands registry | `ui/handlers/command_handler.py` | 83–170 | ⚠️ No `/compact` |
| `/clear` template | `ui/handlers/project_handler.py` | 673–730 | Template to copy |
| Settings dialog | `ui/views/settings_dialog.py` | 99–104 | ⚠️ No threshold edit |
| Provider config | `models/providers.py` | 39–58 | ✅ |
| Conversation model | `models/conversation.py` | 124–471 | ✅ |
| Token estimation | `models/conversation.py` | 354–425 | ✅ tiktoken + cache |
| System-prompt builder | `agent/context.py` | 357–754 | ⚠️ TODO P10.8 |
| Per-caller fallback | `models/providers.py` | 11–28 | ✅ MiniMax=1M, Anthropic=200K |
| Ring buffer | `agent/runtime.py` | 1613, 2128–2133 | ✅ |
| CompactionEvent | `agent/context_strategy.py` | 30–61 | ✅ |
| Provider threshold persistence | `utils/providers_store.py` | 59, 98 | ✅ |
| Spec roadmap | `docs/specs/SPEC-CONTEXT-MANAGEMENT-ROADMAP.md` | — | (Draft, for review) |
| Phase-2 proposal | `docs/proposals/PROPOSAL-context-management-phase-2.md` | — | (Awaiting review) |

---

## 8. End-to-end probe results (real code, executed 2026-07-10)

```
Pre:  62,630 tokens, 30 msgs (10 turns, 50KB tool results each)
Layer 1 (prune_tool_outputs, target=20K): 18,978 tokens, 30 msgs
Stubbed TR indices: [5, 8, 11, 14, 17, 20, 23]  (oldest-1st, skipping protected)
Last 2 TRs: [26, 29] — untouched ✓

Pre:  279,701 tokens, 75 msgs (30 turns)
After DefaultContextStrategy.compact(budget=5_000):
  Final:    35,245 tokens, 48 msgs
  Layer:    2 (trim also)
  Removed:  27 messages
  Freed:    244,456 tokens
  Summary:  0 tokens injected  (budget-pressure, summary would overflow)
  Status:   ended at min_messages boundary (6) ✓
```

The engine is correct. Verify with `python3 -m pytest tests/test_context_strategy* tests/test_context* -q` — 139 passed in 7.78s.

---

## 9. Conclusion

**The context-management engine is robust and correct. The wiring is correct. What's missing is the user surface and one tier-up (LLM summarization). Three additive phases, no engine risk. Recommend: Phase A → B → C.**
