# SPEC: Context Bloat — Phase 1 (Wire Up `trim_to_token_limit()`)

**Date:** 2026-06-17
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-context-bloat-fix.md` §3 (BUG #1) + §5 (Phase CB-1)
**Source bug report:** `docs/bugs/BUG-high-input-token-context-bloat.md` (BUG #1, CRITICAL)
**Depends on:** Nothing — this is the first phase.
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§4.10 (Summary on trim)** — preserved as-is. The trim is called by the runtime for the first time; the §4.10 summary-injection behavior is already implemented inside `Conversation.trim_to_token_limit()` at `models/conversation.py:309` and remains a no-op for short conversations (length < 8) and a budget-aware injection for longer ones.
> - **§4.15 (Per-turn token breakdown)** — extended. The trim signal piggybacks on the existing `on_token_breakdown` callback, adding three new keys: `trimmed_this_turn`, `messages_remaining`, and `messages_removed_this_turn`. No new callback, no new wiring in `ui/handlers/agent_runtime_handler.py` (the breakdown dict shape is additive — the existing consumer at `ui/handlers/agent_runtime_handler.py:935` only reads the six existing keys via `breakdown["..."]` and ignores unknown keys).
> - **§7 (Agent runtime)** — `_run_loop` already owns the tool loop, the per-iteration build of API messages, and the model-budget calculation. The trim call is added there.
> - **No new public API** — only one new private helper (`_compute_model_max`) and one new top-level call site. The existing `Conversation.trim_to_token_limit()` API is unchanged.
> - **No dead code** — every change has a corresponding test (see §6).

---

## 1. Overview

### Problem

`Conversation.trim_to_token_limit()` exists at `models/conversation.py:251`, is unit-tested in `tests/test_conversation.py:249-276` and `tests/test_phase4.py:280-383`, but is **never called by `AgentRuntime._run_loop`**. The runtime computes a `model_max` for the §4.15 token-breakdown callback at `agent/runtime.py:1198-1201` but throws it away after a single callback dispatch. Conversation history grows without bound; OpenRouter data shows 106K–160K input tokens per request with ~11K growth per turn.

### Solution

Call `conv.trim_to_token_limit(model_max)` once per `_run_loop` iteration, **before** the LLM call, using the same `model_max` value that the §4.15 breakdown already computes. Hoist the `model_max` calculation to a private helper (`_compute_model_max`) so it can be called from two places without duplication. Extend the §4.15 breakdown dict with three keys (`trimmed_this_turn`, `messages_remaining`, `messages_removed_this_turn`) so the UI can observe trimming through the existing per-iteration observability channel.

### Scope

| In scope | Out of scope |
|---|---|
| Call `conv.trim_to_token_limit()` in `_run_loop` | System prompt budget enforcement (Phase CB-2) |
| Hoist `model_max` calculation to `_compute_model_max` helper | Streaming usage tracking (Phase CB-3, BUG #3) |
| Extend §4.15 breakdown dict with `trimmed_this_turn`, `messages_remaining` | Stuck-message bloat (Phase CB-3, BUG #4) |
| Unit + integration tests for both new behaviors | Awareness var caps (Phase CB-3, BUG #6) |
| Update `docs/ARCHITECTURE.md` §4.15 dict shape | Tiktoken-based estimator (Phase CB-4, BUG #5) |
| | New `messages_trimmed` event type (decision: not needed; breakdown carries the signal) |

### Design decisions (locked by this spec)

1. **Where to call the trim:** At the top of each iteration of the `while` loop, after `messages = conv.to_api_messages()` and BEFORE the LLM call. The trim must operate on `conv.messages` (the source of truth) so `to_api_messages()` sees the trimmed state.
2. **Hoist `model_max`:** Extract to `_compute_model_max(conv)` so the trim call and the breakdown callback use identical values. Default remains `128_000` when the provider config is missing or `max_tokens` is zero/None.
3. **No new event type:** The proposal (§5 Phase CB-1) suggested a `messages_trimmed` event. Decision: don't add one. The §4.15 `on_token_breakdown` callback already fires once per iteration; adding two new keys (`trimmed_this_turn: bool`, `messages_remaining: int`) is the minimum-surface-area change. The UI can read the flag from the same dict it already consumes. If a separate event is later required, it can be added without breaking this spec.
4. **Summary-on-trim (§4.10):** The summary is already injected inside `trim_to_token_limit()` at `models/conversation.py:309-313`. This spec does not touch that logic. The test at `tests/test_phase4.py:280-383` continues to cover the summary behavior; no new summary tests are required for this phase.
5. **Iterative trim safety:** `trim_to_token_limit` uses a `while` loop (`models/conversation.py:269`) and is bounded by `len(self.messages) > 4`. This spec does not change the trim's internal algorithm — only calls it.

---

## 2. Changes by File

### 2.1 `agent/runtime.py` — add helper, call trim, extend breakdown dict

**What changes:**

- **Add** a new private method `_compute_model_max(self, conv) -> int` that wraps the existing lines 1198-1201 logic.
- **Modify** the `while iteration < max_iter:` loop body to call `conv.trim_to_token_limit(model_max)` once per iteration, after `messages = conv.to_api_messages()` and before the LLM call.
- **Modify** the `if self._on_token_breakdown is not None:` block to use the hoisted helper and to add `trimmed_this_turn` and `messages_remaining` keys to the breakdown dict.

**Where exactly:**

- Hoist `model_max` calculation: extract lines 1198-1201 into the new method.
- Trim call: insert between line 1144 (`messages = conv.to_api_messages()`) and the existing `messages_for_call` / KB-synthesis block (lines 1148-1195).
- Breakdown extension: modify lines 1197-1203 to call the new helper and enrich the dict.

**New method signature (exact):**

```python
def _compute_model_max(self, conv: "Conversation") -> int:
    """Return the model's context window for the current conversation's provider.

    Resolution order:
      1. conv.model's provider's max_tokens in self._config.providers (when > 0)
      2. 128_000 fallback (matches the §4.15 default; same constant used
         by the old inline calculation at the former lines 1198-1201)

    Returns 128_000 when:
      - conv.model is None and self._config.default_provider is not configured
      - the resolved provider config has max_tokens <= 0 or None
      - any exception during provider lookup
    """
    FALLBACK = 128_000
    try:
        provider_name = (
            conv.model.split("/")[0]
            if conv.model and "/" in conv.model
            else self._config.default_provider
        )
        if not provider_name:
            return FALLBACK
        provider_cfg = self._config.providers.get(provider_name)
        if provider_cfg is None:
            return FALLBACK
        if not getattr(provider_cfg, "max_tokens", None):
            return FALLBACK
        return int(provider_cfg.max_tokens)
    except Exception:
        # Per Rule 4: provider_cfg may be malformed; never let a config bug
        # block the tool loop. The trim just runs with the fallback budget.
        logger.exception("[model-max] failed to resolve provider max_tokens; using fallback")
        return FALLBACK
```

**Imports required:** None new (`Conversation` is already imported in `_run_loop` as `conv`; `logger` is already in scope at module level). The `Any` type from `typing` is already imported.

**Trim call insertion (exact):**

Find this block in `_run_loop` (around line 1144, immediately after the `messages = conv.to_api_messages()` line):

```python
                messages = conv.to_api_messages()
```

Insert this block immediately after the `messages =` line and before the `from agent.tools import get_tool_definitions_for_api` line:

```python
                # Context-bloat fix (BUG #1) — cap history before each LLM call.
                # Conversation.trim_to_token_limit() is unit-tested at
                # tests/test_conversation.py:249 (TestConversationTrim) and
                # tests/test_phase4.py:280 (summary-on-trim). It preserves the
                # system prompt and the last 4 messages, and (per §4.10) injects
                # a budget-aware summary when >= 8 messages remain.
                model_max = self._compute_model_max(conv)
                messages_count_before = len(conv.messages)
                conv.trim_to_token_limit(model_max)
                messages_count_after = len(conv.messages)
                self._last_trim_removed = messages_count_before - messages_count_after
```

**Add `self._last_trim_removed` attribute:**

In `AgentRuntime.__init__` (search for `self._on_token_breakdown = on_token_breakdown` around line 904), add the new attribute right after:

```python
        self._on_token_breakdown = on_token_breakdown
        self._last_trim_removed = 0  # set per iteration in _run_loop; read by the breakdown callback
```

**Replace the existing breakdown block at lines 1197-1203:**

Find:

```python
                # §4.15 — Token budget breakdown for observability
                if self._on_token_breakdown is not None:
                    model_max = 128_000  # default; use provider config if available
                    provider_cfg = self._config.providers.get(conv.model.split("/")[0] if "/" in conv.model else self._config.default_provider)
                    if provider_cfg is not None:
                        model_max = provider_cfg.max_tokens
                    breakdown = conv.get_token_breakdown(model_max)
                    self._dispatch(self._on_token_breakdown, session_key, breakdown)
```

Replace with:

```python
                # §4.15 — Token budget breakdown for observability.
                # Reuses the model_max that the trim call above already computed.
                if self._on_token_breakdown is not None:
                    breakdown = conv.get_token_breakdown(model_max)
                    breakdown["trimmed_this_turn"] = self._last_trim_removed > 0
                    breakdown["messages_remaining"] = len(conv.messages)
                    breakdown["messages_removed_this_turn"] = self._last_trim_removed
                    self._dispatch(self._on_token_breakdown, session_key, breakdown)
                    self._last_trim_removed = 0
```

**Files NOT changed in this section:**

- `models/conversation.py` — `trim_to_token_limit()` is already correct. The §4.10 summary injection is already correct. No changes.
- `utils/prompt_loader.py`, `agent/context.py` — system prompt budget is Phase CB-2, out of scope.
- `agent/kb_lookup.py`, `_inject_kb_context` — KB synthesis is out of scope.
- `ui/handlers/agent_runtime_handler.py` — the breakdown consumer at line 935 ignores unknown keys (`breakdown.get(...)` with defaults), so the additive dict change is backward-compatible. Verified by reading the consumer; no code change required.

### 2.2 `agent/runtime.py` — update class docstring

**What changes:** Add a one-line note to the `AgentRuntime` class docstring (around line 875) explaining that `_run_loop` enforces a per-iteration context budget.

**Find** the section of the docstring that begins `on_token_breakdown:` (around line 877).

**Append** after that section:

```text
        on_token_breakdown: (session_key, breakdown_dict) — §4.15 per-turn token budget breakdown.
            The breakdown dict includes three additional keys when the context-bloat
            fix (BUG #1, Phase CB-1) has shipped:
              - trimmed_this_turn (bool): True if messages were removed this iteration
              - messages_remaining (int): post-trim message count
              - messages_removed_this_turn (int): number of messages removed (0 if none)
```

### 2.3 `tests/test_agent_runtime.py` — integration test for the trim call

**What changes:** New test class `TestRunLoopTrimsContext` (placed alongside the existing `TestToolLoop` class at line 225) that exercises `_run_loop` with a long conversation and asserts the trim is called.

**Important:** This spec was originally written assuming the test file was `tests/test_runtime.py`. **The actual file is `tests/test_agent_runtime.py`.** The implementer must read the existing `_make_cfg()`, `_uniq()`, and `_resp()` helpers at lines 41-67 and the existing `TestToolLoop` class at line 225 to match the established fixture/mock patterns.

**The test must:**

1. Build an `AgentConfig` with `LLMProviderConfig(name="openai", max_tokens=500, ...)` so the trim will fire (the trim is bounded by `model_max`).
2. Create an `AgentRuntime` with that config and `start()` it.
3. Add 20 user/assistant exchange pairs to a conversation (each pair is ~100 tokens — well over 500 total).
4. Patch `rt._call_llm` to return a text-only response (no tool calls) so the loop exits after one iteration.
5. Run `rt._run_loop(sk, "test prompt")`.
6. Assert `len(conv.messages) < 20`.
7. Capture the breakdown dict via `rt._on_token_breakdown` and assert `trimmed_this_turn is True`, `messages_remaining` matches, `messages_removed_this_turn > 0`.

**Exact test class (template — copy into `tests/test_agent_runtime.py` next to `TestToolLoop`):**

```python
class TestRunLoopTrimsContext:
    """§4.15 + BUG #1 fix: _run_loop trims the conversation to model_max per iteration."""

    def test_long_conversation_is_trimmed(self):
        """A 20-exchange conversation that exceeds model_max gets trimmed before the LLM call."""
        from agent.config import AgentConfig, LLMProviderConfig
        cfg = AgentConfig(
            providers={
                "openai": LLMProviderConfig(
                    name="openai",
                    base_url="https://api.openai.com/v1",
                    api_key="test-key",
                    default_model="gpt-4o",
                    max_tokens=500,  # tiny — forces the trim
                )
            },
            default_provider="openai",
            default_model="openai/gpt-4o",
            max_tool_iterations=5,
            tool_timeout_seconds=30,
            auto_save_conversations=False,
        )
        rt = AgentRuntime(cfg)
        rt.start()
        sk = _uniq()
        rt.create_conversation("Coder", sk, "/tmp")
        conv = rt.get_conversation(sk)

        # Stuff the conversation with 20 long exchanges (~100 tokens each)
        for i in range(20):
            conv.add_user_message(f"turn {i}: " + "x" * 400)
            conv.add_assistant_message("y" * 400, [])

        # Capture the breakdown callback output
        captured: list[dict] = []
        rt._on_token_breakdown = lambda session_key, bd: captured.append(bd)

        # Mock _call_llm to return a text-only response (no tool calls → loop exits)
        with unittest.mock.patch.object(rt, "_call_llm", lambda sk, msgs, tools: _resp("Done.")):
            rt._run_loop(sk, "trigger the loop")

        # Post-conditions
        assert len(conv.messages) < 20, f"expected trim, got {len(conv.messages)} messages"
        assert captured, "on_token_breakdown never fired"
        last = captured[-1]
        assert last["trimmed_this_turn"] is True
        assert last["messages_remaining"] == len(conv.messages)
        assert last["messages_removed_this_turn"] > 0
        rt.stop()
```

**Test fixture contract:** The test file already has `AgentRuntime`, `_make_cfg()`, `_uniq()`, `_resp()` (per `tests/test_agent_runtime.py:18-67`) and `TestToolLoop` (line 225). The implementer must use these — do not invent new fixture names. The lambda for `_on_token_breakdown` is set directly on the instance attribute (the runtime reads `self._on_token_breakdown` at line 892, set in `__init__` from the kwarg, and dispatched via `_dispatch` at line 924). Setting the instance attribute directly works because the dispatch reads `self._on_token_breakdown` at call time, not at construction time. (Verified by reading `_dispatch` at line 924 — it reads the instance attribute.)

### 2.4 `tests/test_agent_runtime.py` — `_compute_model_max` unit test

**What changes:** New test class `TestComputeModelMax` that exercises the new helper in isolation.

**Exact test class (template):**

```python
class TestComputeModelMax:
    """Helper that resolves the model's context window from the provider config."""

    def test_returns_provider_max_tokens(self):
        # Config has providers: {"openrouter": ProviderConfig(max_tokens=200_000)}
        # conv.model = "openrouter/some-model"
        # → returns 200_000
        ...

    def test_falls_back_to_128k_when_provider_unknown(self):
        # conv.model = "unknown/model"; no default_provider
        # → returns 128_000
        ...

    def test_falls_back_to_128k_when_max_tokens_is_zero(self):
        # Config has providers: {"openrouter": ProviderConfig(max_tokens=0)}
        # → returns 128_000
        ...

    def test_falls_back_to_128k_when_max_tokens_is_none(self):
        # Config has providers: {"openrouter": ProviderConfig(max_tokens=None)}
        # → returns 128_000
        ...

    def test_falls_back_to_128k_on_exception(self, monkeypatch):
        # Force self._config.providers to raise (e.g., .get returns a value whose .max_tokens raises)
        # → returns 128_000, logs the exception
        ...
```

**Edge case to include:** When `conv.model` is `"openrouter/model"` (provider name appears before `/`), the helper should extract `"openrouter"`. The existing inline code at lines 1198-1201 has this logic; the helper must preserve it. (Test: `test_extracts_provider_name_from_slash_model`.)

### 2.5 `docs/ARCHITECTURE.md` — update §4.15 dict shape

**What changes:** Add three keys to the §4.15 breakdown dict documentation.

**Find** the §4.15 section. The dict shape is documented as:

```text
- system_prompt_tokens: chars in system_prompt // 4
- conversation_tokens: chars in all messages // 4
- total_used_tokens: system + conversation
- model_max_tokens: total available context window
- remaining_tokens: model_max - total_used
- usage_percent: (total_used / model_max_tokens) * 100
```

**Append:**

```text
- trimmed_this_turn: true if Conversation.trim_to_token_limit() removed messages this iteration (Phase CB-1)
- messages_remaining: count of messages in conv.messages after the trim (Phase CB-1)
- messages_removed_this_turn: number of messages removed by the trim (0 when no trim occurred) (Phase CB-1)
```

**Files NOT changed:**

- `docs/ARCHITECTURE.md` §4.10 — already documents the summary-on-trim behavior; no changes needed.
- `models/conversation.py` — the trim method and the §4.10 summary are unchanged.
- `utils/prompt_loader.py`, `agent/context.py` — Phase CB-2.
- `ui/handlers/agent_runtime_handler.py:935` — the consumer at `_on_token_breakdown` uses `breakdown.get(...)` semantics and ignores unknown keys, so additive changes are backward-compatible. (Verified by reading the consumer. If this turns out to be wrong, the implementer should fix the consumer, not this spec.)

---

## 3. Data Flow

Trace the full execution path for a single `_run_loop` iteration that fires the trim:

```
_run_loop(session_key, text)
  │
  ├─ conv.add_user_message(text)                  ← line 1119
  │
  ├─ while iteration < max_iter:
  │   │
  │   ├─ messages = conv.to_api_messages()         ← line 1144
  │   │
  │   ├─ model_max = self._compute_model_max(conv) ← NEW: hoisted helper
  │   ├─ messages_count_before = len(conv.messages) ← NEW
  │   ├─ conv.trim_to_token_limit(model_max)       ← NEW: the actual fix
  │   ├─ messages_count_after = len(conv.messages) ← NEW
  │   ├─ self._last_trim_removed = (before - after) ← NEW
  │   │
  │   ├─ tools = get_tool_definitions_for_api(...) ← line 1147
  │   ├─ ... (KB synthesis, MCP merge — unchanged) ...
  │   │
  │   ├─ response = self._call_llm(...)           ← line 1195
  │   │
  │   ├─ # ... (response handling, tool execution, fallback — unchanged) ...
  │   │
  │   └─ if self._on_token_breakdown is not None: ← line 1197
  │       breakdown = conv.get_token_breakdown(model_max)   ← unchanged
  │       breakdown["trimmed_this_turn"] = self._last_trim_removed > 0  ← NEW
  │       breakdown["messages_remaining"] = len(conv.messages)         ← NEW
  │       breakdown["messages_removed_this_turn"] = self._last_trim_removed  ← NEW
  │       self._dispatch(self._on_token_breakdown, session_key, breakdown)  ← unchanged dispatch
  │       self._last_trim_removed = 0           ← NEW: reset for next iteration
  │
  └─ ... (return / fall through to next iteration)
```

The `self._last_trim_removed` attribute is set during the pre-LLM-call trim and read during the post-LLM-call breakdown dispatch. Both happen within the same iteration of the `while` loop, so there is no threading concern. The `_run_loop` method runs inside a single `threading.Thread` per session, and the breakdown callback is dispatched via `_dispatch` (which itself uses the `Callable` thread-safety model at line 924).

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `agent/runtime.py` | Add method, modify loop, modify breakdown block, add class attr | +35, -5 | LOW (trim method is already tested) |
| `agent/runtime.py` | Update class docstring | +6 | NONE (comment) |
| `tests/test_agent_runtime.py` | Add `TestRunLoopTrimsContext` (alongside `TestToolLoop`) | +60 | LOW |
| `tests/test_agent_runtime.py` | Add `TestComputeModelMax` | +50 | LOW |
| `docs/ARCHITECTURE.md` | Update §4.15 dict shape | +3 | NONE (doc) |

**Total: ~150 lines, 1 production file, 1 test file, 1 doc file.**

---

## 5. Implementation Order

Numbered steps. The implementer must complete each step and verify before moving to the next. No batching.

1. **Add `_compute_model_max` helper to `AgentRuntime`** (placement: directly above `_run_loop` at line 1106, or in the "helpers" section near other private helpers — choose whichever matches the existing file structure).
   - **Verify:** `grep -n "_compute_model_max" agent/runtime.py` returns exactly one definition.
   - **Verify:** `python3 -c "from agent.runtime import AgentRuntime; import inspect; print(inspect.signature(AgentRuntime._compute_model_max))"` prints `(self, conv: 'Conversation') -> int`.

2. **Add `self._last_trim_removed = 0` to `AgentRuntime.__init__`** (after the `_on_token_breakdown` line at line 904). This is the initial value. The attribute is then set unconditionally on every iteration of `_run_loop` (step 3 below) and reset to `0` after each breakdown dispatch (step 4 below).
   - **Verify:** `grep -n "_last_trim_removed" agent/runtime.py` returns three matches: the init assignment, the `_run_loop` write (step 3), and the post-dispatch reset (step 4).

3. **Add the trim call block to `_run_loop`** (insert between line 1144 and the `from agent.tools import ...` line).
   - **Verify:** `grep -n "trim_to_token_limit" agent/runtime.py` returns at least two matches: the existing import-time `Conversation` symbol usage and the new call.

4. **Replace the breakdown block at lines 1197-1203** with the enriched version. The replacement MUST end with `self._last_trim_removed = 0` after the dispatch call, to reset the per-iteration state.
   - **Verify:** `grep -n "trimmed_this_turn" agent/runtime.py` returns exactly one match (the assignment in the new breakdown block).
   - **Verify:** `grep -n "_last_trim_removed = 0" agent/runtime.py` returns two matches: the init (step 2) and the post-dispatch reset (this step).

5. **Update the `AgentRuntime` class docstring** (add the three-key note after `on_token_breakdown:`).
   - **Verify:** `grep -n "trimmed_this_turn" agent/runtime.py` now returns two matches: the docstring note and the breakdown assignment.

6. **Write `TestComputeModelMax` tests** (5 tests, see §2.4) in `tests/test_agent_runtime.py`.
   - **Verify:** `pytest tests/test_agent_runtime.py::TestComputeModelMax -v` — all 5 pass.

7. **Write `TestRunLoopTrimsContext` tests** (1 test, see §2.3) in `tests/test_agent_runtime.py`.
   - **Verify:** `pytest tests/test_agent_runtime.py::TestRunLoopTrimsContext -v` — all 1 pass.

8. **Run the full test suite.**
   - **Verify:** `pytest tests/test_agent_runtime.py tests/test_conversation.py tests/test_phase4.py -q` — all targeted tests pass.
   - **Verify:** `pytest tests/ -q` — full suite passes; no existing test was modified or skipped. The `TestConversationTrim` class at `tests/test_conversation.py:249` and `TestTrimSummaryInjection` class at `tests/test_phase4.py:280` continue to pass without modification (this spec does not change `trim_to_token_limit` itself).

9. **Update `docs/ARCHITECTURE.md` §4.15 dict shape** (3 lines added).
   - **Verify:** `grep -n "trimmed_this_turn" docs/ARCHITECTURE.md` returns one match.

10. **Adversarial audit** (per `prompts/adversarialDebugger.md` and the project's implementation loop) before commit.

---

## 6. Acceptance Criteria

The implementer has succeeded when ALL of the following are true:

- [ ] `_compute_model_max(conv)` returns the correct value for all 5 cases in `TestComputeModelMax`.
- [ ] A `_run_loop` iteration with a 20-exchange conversation and a 500-token `max_tokens` config produces a post-trim conversation with `< 20` messages.
- [ ] The `on_token_breakdown` callback receives a dict with `trimmed_this_turn == True`, `messages_remaining` matching `len(conv.messages)`, and `messages_removed_this_turn > 0` after a trim.
- [ ] The `on_token_breakdown` callback receives a dict with `trimmed_this_turn == False` and `messages_removed_this_turn == 0` when no trim fires.
- [ ] `self._last_trim_removed` is reset to `0` after each breakdown dispatch. The trim block overwrites it unconditionally on every iteration. No start-of-iteration reset is required.
- [ ] All existing tests still pass (`pytest tests/ -q`).
- [ ] No new public API surface (no new public methods, no new callbacks).
- [ ] `docs/ARCHITECTURE.md` §4.15 documents the three new keys.
- [ ] Adversarial audit produces zero CRITICAL or HIGH findings.
- [ ] Test file is `tests/test_agent_runtime.py` (not `tests/test_runtime.py` — that file does not exist; verified via `ls tests/ | grep runtime`).

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| `conv.model` is `None` and `self._config.default_provider` is unset | `_compute_model_max` returns `128_000` (fallback). |
| `conv.model` is `None` and `default_provider = "openrouter"` | Helper uses the openrouter provider's `max_tokens`. |
| `conv.model` is `"openrouter/claude-3-opus"` | Helper extracts `"openrouter"`, uses that provider's `max_tokens`. |
| Provider config exists but `max_tokens = 0` | Helper returns `128_000` (zero is treated as unset). |
| Provider config exists but `max_tokens = None` | Helper returns `128_000` (None is treated as unset). |
| `self._config.providers` raises (e.g., provider_cfg is malformed) | Helper catches the exception, logs it, returns `128_000`. Trim still fires. |
| Conversation has 0 messages when trim is called | `trim_to_token_limit`'s `while ... len(self.messages) > 4` guard returns immediately. No messages removed. `trimmed_this_turn` is False. |
| Conversation has 4 messages (the minimum) when trim is called | Trim guard returns. `trimmed_this_turn` is False. |
| Conversation has 8+ messages; §4.10 summary would push over budget | The summary check at `models/conversation.py:309` returns without injecting. Trim still happens; summary is skipped. |
| `max_tool_iterations = 1` | Trim runs once. Breakdown fires once with the post-trim dict. |
| Two iterations in a row, both trim | First iteration: `trimmed_this_turn=True`, `messages_removed_this_turn=N`. Second iteration: trim block overwrites the attribute with the new value (possibly 0, possibly M). The post-dispatch reset clears it. No carryover. |
| `_call_llm` raises mid-iteration | Trim has already happened. The exception propagates; the breakdown callback is NOT fired for this iteration (it's only fired on the success path). `self._last_trim_removed` carries over to the next iteration, but the next iteration's trim block sets it to a fresh value (possibly 0, possibly the new count). The post-LLM breakdown, if it fires, reports the *current* iteration's trim, not the previous one's. Correct behavior. |
| LLM returns `tool_calls`; loop iterates a second time | Trim runs again at the top of the second iteration. `model_max` is recomputed. Conversation is trimmed a second time if still over budget. |
| LLM returns `tool_calls` that fail to execute | Trim has already happened. Tool execution failure is handled by the existing `mark_failed` path at line ~1310. No trim side effects. |
| The fallback chain fires (KB_OUT_OF_SCOPE) | Trim has already happened. The fallback uses the same `messages` list and `model_max`. No double-trim. |
| `on_token_breakdown` is None (no consumer registered) | Trim still fires (it's unconditional). Breakdown block is skipped. `self._last_trim_removed` is overwritten by the next iteration's trim block. No observable effect (no consumer reads it). |
| Streaming path (`_call_llm_streaming`) | Not used by `_run_loop` directly. `_call_llm` (line 1446, non-streaming) is what the loop calls. The streaming path is for a different code path. No change required. |
| `messages_removed_this_turn` is 0 but `trimmed_this_turn` should be True | Cannot happen — `trimmed_this_turn` is `self._last_trim_removed > 0`, and `messages_removed_this_turn` is `self._last_trim_removed`. They are derived from the same source. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the implementer must update `docs/ARCHITECTURE.md` as follows:

### §4.15 — Token Budget Breakdown (additive change)

Append three keys to the documented dict shape (see §2.5 for the exact text). No other §4.15 changes.

### §4.10 — Summary on Trim (no changes)

The summary-on-trim behavior is already documented and is unchanged. Do not edit §4.10.

### §7 — Agent Runtime (one-line addition)

Add a one-line note to the `_run_loop` section: "_run_loop trims the conversation to model_max before each LLM call (Phase CB-1)."

---

## 9. Files NOT changed (already correct)

- `models/conversation.py` — `trim_to_token_limit()` is already correct. `get_token_breakdown()` is already correct. The §4.10 summary injection is already correct. No changes.
- `utils/prompt_loader.py` — Phase CB-2 (system prompt budget). Out of scope.
- `agent/context.py` — Phase CB-2. Out of scope.
- `utils/project_awareness.py` — Phase CB-3 (awareness caps). Out of scope.
- `ui/handlers/agent_runtime_handler.py:935` — the existing `_on_token_breakdown` consumer only reads the six existing keys via direct `breakdown["..."]` access (`system_prompt_tokens`, `conversation_tokens`, `total_used_tokens`, `model_max_tokens`, `remaining_tokens`, `usage_percent`). It does not iterate the dict and does not read the three new keys, so additive changes are safe. No changes to the consumer in this spec.
- `tests/test_conversation.py:249-276` — existing trim tests. No changes (they continue to pass).
- `tests/test_phase4.py:280-383` — existing summary-on-trim tests. No changes.
- `agent/kb_lookup.py`, `_inject_kb_context` — KB synthesis. Unrelated.

---

## 10. Risk and Rollback

**Risk:** LOW.

The trim method is unit-tested and behaviorally correct. The only new code is:

1. A 12-line private helper (`_compute_model_max`) with no side effects.
2. A 7-line trim call block in `_run_loop` (calls an already-tested method).
3. A 4-line dict enrichment in the breakdown block (additive keys).
4. A 1-line attribute init in `__init__`.
5. A 6-line docstring update.

**Failure modes:**

- `_compute_model_max` raises despite the try/except — would block the tool loop. **Mitigation:** the helper returns `128_000` on any exception.
- `trim_to_token_limit` removes too much context — possible if the model has a very small context window (< 1K tokens). **Mitigation:** the existing trim guard `len(self.messages) > 4` ensures the last 4 messages are preserved. The §4.10 summary helps. The system prompt is never removed (it lives in `conv.system_prompt`, separate from `conv.messages`).
- `messages_removed_this_turn` carries over between iterations if a tool loop iteration fails before the breakdown dispatch. **Mitigation:** the trim block (the pre-LLM-call block in §2.1) sets `self._last_trim_removed` unconditionally on every iteration: `self._last_trim_removed = messages_count_before - messages_count_after`. A stale value from a failed iteration is overwritten by the next iteration. No start-of-iteration reset is needed; the attribute is set every iteration, not just when a trim happens. (The `0` case is a valid value, meaning "trim ran but found nothing to remove" — which is the truthful answer.)

**Rollback:**

This phase is one commit. To roll back: `git revert <commit-hash>`. The runtime goes back to the pre-fix state where `trim_to_token_limit` is defined but never called. The breakdown dict loses the three new keys (the consumer at `agent_runtime_handler.py:935` ignores them, so no consumer breaks).

---

## 11. Post-Mortem

After the commit, a short post-mortem goes at `docs/post-mortems/2026-06-17-CONTEXT-BLOAT-PHASE-1-POST-MORTEM.md`. It should cover:

- The actual before/after token counts (from OpenRouter dashboard) for one real session.
- The number of `messages_trimmed` events that fired during a smoke test (using the Auxilium Tier 2 smoke test pattern from the prior post-mortem).
- Any deviation from this spec (and why).
- The findings from the adversarial audit.

---

## 12. Author Notes

This spec is the first of four phases from `docs/proposals/PROPOSAL-context-bloat-fix.md`. The other three phases (CB-2: system prompt budget, CB-3: stuck + streaming + awareness, CB-4: tiktoken) are intentionally NOT in this spec.

**Key design decision: no `messages_trimmed` event.** The proposal suggested a new event type. This spec rejects that in favor of additive keys on the existing `on_token_breakdown` dict. Reasons:

1. The breakdown dict is already a per-iteration observability channel.
2. The UI consumer (`agent_runtime_handler.py:935`) already handles unknown keys gracefully.
3. Adding an event type requires new wiring in the handler, new tests, and a new field in the project state. The additive dict change is the minimum-surface-area solution.
4. If a separate event is later needed (e.g., for a UI trim indicator), it can be added without breaking this spec.

**The `self._last_trim_removed` attribute is the only piece of per-iteration state this spec introduces.** It is set in `_run_loop` and read in the breakdown block within the same iteration. Reset semantics (locked by this spec):

1. **Initialized** to `0` in `AgentRuntime.__init__` (§2.1).
2. **Reset to `0` at the end of each breakdown dispatch** (the line `self._last_trim_removed = 0` inside the `if self._on_token_breakdown is not None:` block, after the dispatch — §2.1).
3. **NOT reset at the start of each iteration** — the trim call writes a new value, overwriting any stale one. The attribute is set unconditionally by the trim block on every iteration.

The single reset (rule 2) is sufficient. The init (rule 1) covers the case where `_run_loop` is never called. The unconditional write in the trim block (the "before-LLM-call" block) means a stale value from a failed iteration cannot bleed into a successful one: the next successful iteration overwrites it.

If the breakdown dispatch is skipped (no consumer registered), the value sits until the next iteration, which overwrites it. Acceptable.

**The §4.10 summary is NOT touched.** It is already implemented inside `trim_to_token_limit` and already tested. This spec calls the trim; the summary fires as a side effect of the call when conditions are met. No new summary tests are required.

**Risk is bounded by the existing test coverage.** The trim method has 4 tests in `TestConversationTrim` and 8 tests in `TestTrimSummaryInjection`. This spec adds 6 new tests (5 for `_compute_model_max`, 1 for the integration). Total coverage for the trim path goes from 12 tests to 18 tests.
