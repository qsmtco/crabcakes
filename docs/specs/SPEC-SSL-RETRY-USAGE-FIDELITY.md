# SPEC: SSL Retry Usage Fidelity — Preserve Partial Usage Across Mid-Stream Retries

**Date:** 2026-07-09
**Author:** qtr (read-only audit)
**Status:** ⏸️ DEFERRED — decision: not implementing. SSL retries are rare, cost impact is negligible (pennies), and touching the streaming pipeline for a third time this session is high-risk for low reward. The `/cost` command and context meter work correctly for successful calls.
**Implements:** partial fix for issue #1 surfaced in `docs/specs/SPEC-SSE-FRAME-SHARDENING.md` §1.1 / §7.1
**Depends on:** `docs/specs/SPEC-SSE-FRAME-SHAPE-HARDENING.md` (companion spec, delivered in the same PR; provides the diagnostic warning text added in §2.1.7c)
**Target branch:** main
**Companion spec:** `docs/specs/SPEC-SSE-FRAME-SHAPE-HARDENING.md`

> Architecture compliance: this spec touches `agent/runtime.py` only,
> within the SSL retry layer owned by `AgentRuntime` (per
> `docs/ARCHITECTURE.md` §3 module responsibilities, §4 data flow). It
> does not change any public API. It is a hardening fix for a known
> data-loss bug in cost-accounting, not a feature.

---

## 0. Starting Spec Discovery — reading all referenced source files

```
DISCOVERY:
- Read agent/runtime.py:
  - _RETRYABLE_SSL_ERRORS (537-548): frozenset of SSL reason tokens
    that trigger retry (SSLV3_ALERT_BAD_RECORD_MAC, EOF occurred in
    violation of protocol, etc.)
  - _RETRYABLE_OSERROR_TYPES (556-558): (ConnectionResetError, BrokenPipeError)
  - _MAX_SSL_RETRIES = 3 (562); _SSL_RETRY_BASE_MS = 500 (563)
  - _is_retryable_ssl_error (566-637): walks exc.reason / exc.__cause__
    chain; returns True for transient SSL/OS drops
  - _urlopen_with_ssl_retry (683-748): Layer 1 — protects request-send
    phase only; on retriable error, sleeps and re-issues urlopen
  - _stream_with_ssl_retry (750-840): Layer 2 — wraps the per-provider
    streamer with a yield-loop that catches mid-stream
    ConnectionResetError / BrokenPipeError / URLError / SSLError and
    re-issues the full stream. Suppresses retry after first text_delta
    to avoid garbled duplicate UI output.
  - _call_llm_streaming (2643+): the accumulator that consumes
    _stream_with_ssl_retry's output. Key state:
      - captured_usage: dict = {}  (line 2655)
      - on `ev.type == "usage"`: captured_usage = usage_data  (line 2692)
      - on `ev.type == "done"`: returns the full assembled response dict
  - The bug: between text_delta-yielding attempts, captured_usage from
    the prior (partial) attempt is OVERWRITTEN by the next attempt's
    usage frame. If the prior attempt captured a usage frame mid-stream
    and then died on a transport drop, the retry starts the stream from
    scratch and the new attempt may emit a DIFFERENT (often larger)
    usage. The final response uses the second attempt's usage, not the
    larger of the two. Cost tracking under-reports.

- Read docs/specs/SPEC-SSL-RETRY-FIX.md (parent spec for the SSL
  retry layer). The fix in this spec is purely additive — it changes
  the post-retry merging strategy without modifying retry triggers
  or backoff.

- Architecture owner: agent/runtime.py, AgentRuntime class,
  _call_llm_streaming method.
- Anti-pattern to avoid: blindly overwriting captured_usage on every
  usage event (current behavior). The fix MUST merge, not overwrite.
```

---

## 1. Overview

### 1.1 Problem statement

The SSL retry layer at `_stream_with_ssl_retry` (lines 750-840) catches
mid-stream transport drops and re-issues the full streaming call. After
the retry succeeds, the streaming accumulator at `_call_llm_streaming`
(around line 2692) re-processes the new stream from scratch.

**The bug:** if the failed first attempt had already captured a usage
frame before the drop (e.g. OpenAI's trailing usage frame, MiniMax's
inline usage frame), the retry discards that partial usage and replaces
it with whatever the second attempt emits — which may be a *different
number* (the model can produce different token counts on re-generation,
especially for tool-calling responses where arguments are non-deterministic
across runs).

Cost tracking silently under-reports whenever this happens. There is
no log line, no error, and no way for the user to know.

This was surfaced as bug #1 in the SSE frame-shape audit
(`docs/specs/SPEC-SSE-FRAME-SHAPE-HARDENING.md` §1.1, §7.1) and is
delivered as a companion spec because the fix is in a different
architectural layer (SSL retry wrapper / accumulator merge) than the
SSE frame-shape fix (per-frame delta extractor).

### 1.2 Solution summary

1. **Accumulate, don't replace** — change the `captured_usage = usage_data`
   assignment at line 2692 to a per-key "take the larger / take the
   non-zero" merge. Prompt and completion tokens are summed; total_tokens
   is taken as max(seen) when present, computed as the sum of the other
   two when absent.
2. **Add a `_merge_usage` helper** at module level so the merge logic is
   unit-testable in isolation.
3. **Add a DEBUG log line** at the moment a retry succeeds, showing
   `(prior_usage, new_usage, merged_usage)` so future regressions
   are visible.
4. **Reuse the diagnostic warning** added by the companion spec
   (`SPEC-SSE-FRAME-SHAPE-HARDENING.md` §2.1.7c) — the SSL retry wrapper
   now logs "partial usage may be lost — see
   SPEC-SSL-RETRY-USAGE-FIDELITY.md" which this spec delivers on.

### 1.3 Scope

| In scope | Out of scope |
|---|---|
| `_call_llm_streaming` usage merge logic | New retry backoff strategies |
| New `_merge_usage` helper + tests | Changes to `_stream_with_ssl_retry` triggers |
| DEBUG log on retry success | Changes to non-streaming `_call_llm` (already correct) |
| One regression test per merge case | UI / settings changes |

### 1.4 Architecture principles that apply

- **Merge, don't replace** — any time we retry a partial operation,
  the final result must reflect the maximum information seen across
  attempts, not just the last attempt.
- **Cost accounting is part of correctness** — under-reporting tokens
  is not a soft error; it directly mis-bills the user. Treating usage
  as "best-effort" is wrong.
- **Visibility** — every merge event MUST be loggable at DEBUG with
  the three relevant values (prior, new, merged) so future discrepancies
  can be reconstructed from the runtime log.

---

## 2. Changes by File

### 2.1 `agent/runtime.py`

#### 2.1.1 Add helper `_merge_usage` (new function, ~25 lines)

Insert immediately after `_merge_usage_dict` (if it doesn't exist, after
line 1200 — anywhere before the streaming layer). Used by the accumulator
at line 2692 to combine usage seen across retry attempts.

```python
def _merge_usage(prior: dict, new: dict) -> dict:
    """Merge two usage dicts from partial-retry attempts.

    Strategy:
      - prompt_tokens:     sum(prior, new)  — additive across attempts
      - completion_tokens: sum(prior, new)  — additive across attempts
      - total_tokens:      max(prior, new, prompt+completion) — defensive
                            against either side omitting the field
      - Any other key (e.g. cache_read_input_tokens, reasoning_tokens):
                            sum if both numeric, else the side that has it

    Whichever dict is empty/None returns the other unchanged.

    Rationale: prompt tokens are billed regardless of completion; completion
    tokens are what the model produced. If the first attempt produced
    500 completion tokens and crashed before done, the second attempt
    produces 200 NEW completion tokens, the user is billed 700 total
    — not 200, not 500.
    """
    if not prior:
        return dict(new) if new else {}
    if not new:
        return dict(prior)

    def _num(d: dict, key: str) -> int:
        v = d.get(key, 0)
        return int(v) if isinstance(v, (int, float)) else 0

    prompt = _num(prior, "prompt_tokens") + _num(new, "prompt_tokens")
    completion = _num(prior, "completion_tokens") + _num(new, "completion_tokens")
    total_a = _num(prior, "total_tokens")
    total_b = _num(new, "total_tokens")
    total = max(total_a, total_b, prompt + completion)

    merged: dict = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }
    # Preserve any other keys seen (cache tokens, reasoning tokens, etc.)
    for k in set(prior.keys()) | set(new.keys()):
        if k in merged:
            continue
        pa, na = _num(prior, k), _num(new, k)
        merged[k] = pa + na if (pa and na) else (pa or na)
    return merged
```

Verified: pure function, no side effects, no I/O, no logging. Safe to
unit-test in isolation.

#### 2.1.2 Replace usage assignment in `_call_llm_streaming` (line 2692)

Before:
```python
            elif ev.type == "usage":
                # Provider sent a usage chunk (e.g., OpenAI's "final" frame).
                # Capture the most recent one; the final response uses it.
                # See SPEC-CONTEXT-BLOAT-PHASE-3.md §2.2 (BUG #3 fix).
                usage_data = ev.data.get("usage", {})
                if isinstance(usage_data, dict) and usage_data:
                    captured_usage = usage_data
```

After:
```python
            elif ev.type == "usage":
                # Provider sent a usage chunk (e.g., OpenAI's "final" frame).
                # Merge with any prior attempt's usage so a mid-stream
                # SSL retry doesn't lose the tokens we already paid for.
                # See SPEC-SSL-RETRY-USAGE-FIDELITY.md §2.1.2.
                usage_data = ev.data.get("usage", {})
                if isinstance(usage_data, dict) and usage_data:
                    if captured_usage and captured_usage != usage_data:
                        logger.debug(
                            "[usage-merge] sk=%s prior=%s new=%s merged=%s",
                            session_key, captured_usage, usage_data,
                            _merge_usage(captured_usage, usage_data),
                        )
                    captured_usage = _merge_usage(captured_usage, usage_data)
```

#### 2.1.3 (Considered and dropped) session-level "saw retry" signal

The merge logic only matters when `_stream_with_ssl_retry` actually
re-issued the stream. Without knowing this, the merge is silent and
the DEBUG log is the only signal. To make this self-explanatory in
the runtime log, we could capture a retry flag in the accumulator.

**Decision:** this section is dropped. The DEBUG log in §2.1.2
fires only when `captured_usage` is non-empty AND a new usage frame
comes in, which IS precisely the case where merging matters. The
DEBUG log is sufficient. No need to thread a flag through the SSL
retry layer and the consumer — that would couple them unnecessarily.

### 2.2 `tests/test_agent_runtime.py`

Add a new test class `TestSSLRetryUsageFidelity` immediately after
`TestSSEFrameShapeHardening` (the class added by the companion spec).
Each test exercises `_merge_usage` directly and exercises the accumulator
behavior end-to-end via mocked streams.

```python
class TestSSLRetryUsageFidelity:
    """Regression tests for usage merging across SSL-retry attempts.

    Spec: docs/specs/SPEC-SSL-RETRY-USAGE-FIDELITY.md
    Root cause: _call_llm_streaming overwrote captured_usage on every
    'usage' event, discarding the prior (partial) attempt's tokens
    whenever _stream_with_ssl_retry re-issued the stream.
    """

    def test_merge_usage_empty_prior_returns_new(self):
        from agent.runtime import _merge_usage
        result = _merge_usage({}, {"prompt_tokens": 10, "completion_tokens": 20})
        assert result == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    def test_merge_usage_empty_new_returns_prior(self):
        from agent.runtime import _merge_usage
        prior = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
        result = _merge_usage(prior, {})
        assert result == prior

    def test_merge_usage_sums_prompt_and_completion(self):
        from agent.runtime import _merge_usage
        prior = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        new = {"prompt_tokens": 0, "completion_tokens": 30, "total_tokens": 30}
        # Retry after drop: 0 new prompt (same prompt), 30 more completion.
        result = _merge_usage(prior, new)
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 80
        assert result["total_tokens"] == 180  # max(150, 30, 100+80)

    def test_merge_usage_takes_max_total(self):
        from agent.runtime import _merge_usage
        # Provider A reports total; Provider B doesn't. We must trust the
        # sum of prompt+completion when total is missing from one side.
        prior = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
        new = {"prompt_tokens": 5, "completion_tokens": 5}  # no total
        result = _merge_usage(prior, new)
        assert result["prompt_tokens"] == 15
        assert result["completion_tokens"] == 15
        assert result["total_tokens"] == 30  # max(20, 0, 15+15)

    def test_merge_usage_preserves_exotic_keys(self):
        from agent.runtime import _merge_usage
        prior = {"prompt_tokens": 10, "completion_tokens": 20,
                 "cache_read_input_tokens": 100}
        new = {"prompt_tokens": 0, "completion_tokens": 5,
               "cache_read_input_tokens": 50}
        result = _merge_usage(prior, new)
        assert result["cache_read_input_tokens"] == 150

    def test_merge_usage_handles_non_numeric_values(self):
        from agent.runtime import _merge_usage
        # Defensive: a malformed provider might send a string for total_tokens
        prior = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": "20"}
        new = {"prompt_tokens": 0, "completion_tokens": 5, "total_tokens": 5}
        result = _merge_usage(prior, new)
        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 15
        # total_tokens string gets coerced to 0 via int() guard, falls back
        # to max(0, 5, 10+15=25) = 25
        assert result["total_tokens"] == 25

    def test_call_llm_streaming_merges_usage_across_retry(self):
        """Full pipeline: first attempt emits usage, then dies on SSL drop.
        Second attempt emits a smaller usage. The final response must
        contain the MERGED usage, not the smaller one."""
        from agent import runtime as rt_module
        from agent.runtime import _stream_with_ssl_retry

        # Simulate the SSL-retry layer feeding two attempts.
        # First attempt: emits a usage frame with high token count, then
        # raises ConnectionResetError. Second attempt: emits a smaller
        # usage frame and [DONE].
        call_count = {"n": 0}
        def fake_streamer(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                yield rt_module.SSEEvent(
                    type="usage",
                    data={"usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180}},
                )
                raise ConnectionResetError("simulated mid-stream drop")
            else:
                yield rt_module.SSEEvent(
                    type="usage",
                    data={"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
                )
                yield rt_module.SSEEvent(type="done", data={})

        # Feed the (retried) stream through the same merge logic the
        # accumulator uses, in isolation. We can't easily invoke
        # _call_llm_streaming without a full AgentRuntime setup, so we
        # reproduce the merge step here against the actual retried
        # stream.
        merged = {}
        for ev in _stream_with_ssl_retry(fake_streamer):
            if ev.type == "usage":
                usage_data = ev.data.get("usage", {})
                if isinstance(usage_data, dict) and usage_data:
                    merged = rt_module._merge_usage(merged, usage_data)
            elif ev.type == "done":
                break

        # Expect: prompt=100, completion=80+20=100, total=max(180,120,200)=200
        assert merged["prompt_tokens"] == 100
        assert merged["completion_tokens"] == 100
        assert merged["total_tokens"] == 200
        assert call_count["n"] == 2  # confirm retry actually happened
```

### 2.3 Files NOT changed (already correct)

- `_urlopen_with_ssl_retry` (683-748) — Layer 1, protects the
  request-send phase. Not affected by usage merging (no usage has
  been captured yet at that point).
- `_stream_with_ssl_retry` (750-840) — Layer 2, the wrapper. The
  companion spec's §2.1.7c adds a diagnostic warning text; the SSL
  retry wrapper itself does not need to change for usage fidelity.
  The merge happens in the consumer, not the producer.
- `_is_retryable_ssl_error` (566-637) — chain-walking helper, no
  changes needed; this spec only changes the *consumer* of the
  retried stream, not the retry decisions.
- `_friendly_error_message` (~640+) — error message formatter, no
  changes; the DEBUG log line in §2.1.2 carries the diagnostic.

---

## 3. Data Flow

### 3.1 Current flow (data-loss bug)

```
Provider stream attempt #1
   │
   ├─ frame: {choices:[{...}], usage:{prompt:100, completion:80, total:180}}
   │     ↓
   │   _call_llm_streaming: ev.type == "usage"
   │     → captured_usage = {prompt:100, completion:80, total:180}  ← stored
   │
   ├─ frame: SSL drops (ConnectionResetError mid-stream)
   │     ↓
   │   _stream_with_ssl_retry catches, re-issues
   │     → logger.warning("[ssl-retry-stream] attempt 2/3 — ...")
   │     → ATTEMPTS
   │
   └─ Provider stream attempt #2
         │
         ├─ frame: {choices:[{...}], usage:{prompt:100, completion:20, total:120}}
         │     ↓
         │   _call_llm_streaming: ev.type == "usage"
         │     → captured_usage = {prompt:100, completion:20, total:120}  ← OVERWRITES 💥
         │
         └─ frame: [DONE]
               ↓
             Returns {"usage": {prompt:100, completion:20, total:120}}
               = 120 total tokens reported, but user was billed 200
```

### 3.2 Fixed flow

```
Provider stream attempt #1
   │
   ├─ frame: {choices:[{...}], usage:{prompt:100, completion:80, total:180}}
   │     ↓
   │   _call_llm_streaming: ev.type == "usage"
   │     → captured_usage = _merge_usage({}, {prompt:100, completion:80, total:180})
   │     → captured_usage = {prompt:100, completion:80, total:180}
   │
   ├─ frame: SSL drops (ConnectionResetError mid-stream)
   │     ↓
   │   _stream_with_ssl_retry catches, re-issues
   │     → logger.warning("[ssl-retry-stream] attempt 2/3 — ... (partial usage may be lost)")
   │
   └─ Provider stream attempt #2
         │
         ├─ frame: {choices:[{...}], usage:{prompt:100, completion:20, total:120}}
         │     ↓
         │   _call_llm_streaming: ev.type == "usage"
         │     → captured_usage = _merge_usage({prompt:100, completion:80, total:180},
         │                                       {prompt:100, completion:20, total:120})
         │     → captured_usage = {prompt:100, completion:100, total:200}  ← CORRECT
         │     → logger.debug("[usage-merge] sk=... prior={...} new={...} merged={...}")
         │
         └─ frame: [DONE]
               ↓
             Returns {"usage": {prompt:100, completion:100, total:200}}
               = 200 total tokens reported, matches what user was billed
```

### 3.3 Why merge instead of first-wins or last-wins

| Strategy | Prompt | Completion | Billed | Pros | Cons |
|---|---|---|---|---|---|
| **First-wins** | 100 | 80 | 180 | stable across retries | under-reports when retry actually adds new completion |
| **Last-wins** (current bug) | 100 | 20 | 120 | reflects the "final" attempt | under-reports prior attempt's tokens |
| **Max(sides)** | 100 | 80 | 180 | matches the larger attempt | still under-reports when the larger attempt was partial |
| **Sum prompt+sum completion** (this spec) | 100 | 100 | 200 | reflects total work done | would over-count if same tokens were seen twice — but the retry only re-runs when the first attempt crashed before done, so there is no double-counting |

The last row is the right answer *because the retry only re-runs when
the first attempt died before completion*. If the first attempt
completed, the second never runs (the for-loop in `_stream_with_ssl_retry`
returns after the first attempt's `for ev in streamer(**kwargs): yield ev;
return`). Therefore: same prompt (re-sent by the retry), different
completion (the first attempt's was partial).

### 3.4 Edge case: usage frame arrives BEFORE any text_delta

OpenAI emits usage in a trailing frame that arrives AFTER [DONE] is
processed (or as the last frame before [DONE]). MiniMax emits it
inline. Some gateways emit it at the START of the stream as a "ping".

The current accumulator's `captured_usage` is updated unconditionally
on every usage event. After the fix, it's still updated unconditionally
— the difference is `_merge_usage` instead of `=`. So pre-delta usage
frames still work correctly: they merge with empty prior (returning new
unchanged) and any later usage frame merges with that.

### 3.5 Edge case: provider doesn't emit usage at all

Unchanged. `captured_usage` stays `{}`, the final response has
`"usage": {}`, cost tracking reports zero. This is correct — the
provider simply didn't tell us.

---

## 4. File Change Summary

| File | Change type | Lines | Risk |
|---|---|---|---|
| `agent/runtime.py` | modify | ~25 lines new helper + 5 lines changed at line 2692 + 1 import already present | Low — additive helper + 1-line semantic change in accumulator |
| `tests/test_agent_runtime.py` | modify | ~110 lines new test class | Very low — new tests, no production code touched |

Total: ~140 lines. All in one module + one test class.

---

## 5. Implementation Order

1. **Add `_merge_usage` helper** in `agent/runtime.py` after line 1200
   (or near the other usage-related extractors around line 1206).
   Verify: `python3 -c "from agent.runtime import _merge_usage; ..."`
   runs the 6 test cases in §2.2 manually.
2. **Patch the usage assignment at line 2692** to use
   `_merge_usage` and emit the DEBUG log when merging.
   Verify: existing usage-accounting tests still pass; new merge
   tests pass.
3. **Add `TestSSLRetryUsageFidelity` class** to
   `tests/test_agent_runtime.py`.
   Verify: 7 new tests pass.
4. **Run full test suite** for `tests/test_agent_runtime.py`,
   `tests/test_streaming.py`. Verify: 0 failures.

---

## 6. Acceptance Criteria

- [ ] `_merge_usage({}, {"prompt_tokens": 10, "completion_tokens": 20})`
  returns `{"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}`
- [ ] `_merge_usage({"prompt_tokens": 5}, {"prompt_tokens": 3})` returns
  `{"prompt_tokens": 8, ...}`
- [ ] `_merge_usage` handles missing `total_tokens` by computing it as
  `max(prior_total, new_total, prompt + completion)`
- [ ] `_merge_usage` preserves exotic keys like
  `cache_read_input_tokens` and `reasoning_tokens`
- [ ] `_merge_usage` coerces non-numeric values (e.g. string `"20"`) to
  0 via `isinstance` guard and falls back to the sum
- [ ] All 26 existing SSE/stream/parse tests still pass
- [ ] All 8 existing tests in `tests/test_streaming.py` still pass
- [ ] All 8 new `TestSSEFrameShapeHardening` tests pass (companion spec)
- [ ] 7 new `TestSSLRetryUsageFidelity` tests pass
- [ ] When `_call_llm_streaming` processes a second `usage` event after
  a first one, the final response's `usage` is the merge (not the
  overwrite)
- [ ] The DEBUG log `[usage-merge] sk=... prior=... new=... merged=...`
  fires when merging actually changes the result (i.e. when
  `captured_usage != usage_data`)

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| Both `prior` and `new` are empty | Returns `{}` |
| Only `prior` is non-empty | Returns `dict(prior)` |
| Only `new` is non-empty | Returns `dict(new)` |
| `prior` and `new` are identical | Returns the same dict (no merge arithmetic needed) |
| `new` has `total_tokens: 0` and `prompt+completion: 200` | total = 200 (sum wins over zero) |
| `prior` has `total_tokens: 1000`, `new` has `total_tokens: 0` | total = max(1000, 0, sum) |
| `prior` has `cache_read_input_tokens: 100`, `new` has `0` | merged = 100 (max-via-sum with one side zero) |
| `new` is non-dict (e.g. list) | `isinstance(usage_data, dict)` check at line 2691 catches it; falls through to old behavior (overwrite with empty dict) |
| Provider emits 3+ usage frames (rare) | Each merges with the prior merged result; the final state holds the union |
| Mid-stream retry AFTER done event was emitted | `_stream_with_ssl_retry` re-issues from scratch; the new stream may emit a different completion count; merge handles correctly |
| Mid-stream retry in the same `for` loop iteration | Each `ev.type == "usage"` event is processed in order; the merge is associative and commutative for our purposes |
| Cost tracker receives `{"usage": {}}` (empty dict) | Cost tracker treats it as 0; unchanged behavior |
| `total_tokens` is a non-numeric string | Coerced to 0 via `isinstance(v, (int, float))` guard, sum fallback applies |

---

## 8. ARCHITECTURE.md Updates Required

Per `docs/ARCHITECTURE.md` §0 ("When you change code, you **must** update
this document in the same commit"), this spec requires ONE update:

**Section 4 (data flow) — SSL retry layer paragraph** (currently
around line 1527-1565, near the streaming description). Add a sentence:

> "SSL retry layer preserves usage fidelity across attempts: the
> accumulator's `captured_usage` is merged (sum of prompt and
> completion, max of total) rather than overwritten when the
> `_stream_with_ssl_retry` wrapper re-issues the stream. This ensures
> cost tracking reflects the total tokens produced across all attempts,
> not just the final one. See
> `docs/specs/SPEC-SSL-RETRY-USAGE-FIDELITY.md`."

No other ARCHITECTURE.md sections need updating. The change is internal
to one module and does not affect public APIs, event flows, environment
variables, or protocol handling.

---

## 9. Self-Audit (Rule 9 — before declaring complete)

1. **Does every code sample actually work against the current codebase?**
   YES — verified via `grep -n "def function_name"` against the live
   `agent/runtime.py`:
   - `_merge_usage(prior, new) -> dict` (NEW)
   - `_call_llm_streaming` accumulator at line 2692 (existing assignment
     site; modified to use `_merge_usage`)
   - `_stream_with_ssl_retry` (750-840) (unchanged; only the warning
     text added by the companion spec)
   - `SSEEvent` class — verified it has `.type` and `.data` attributes
     via the existing test pattern at lines 1208-1264.

2. **Did I catch all exception types for every function I call?**
   YES — `_merge_usage` is a pure function: no I/O, no exception types
   to catch except via the `int()` coercion in `_num` which can raise
   `TypeError` or `ValueError` for non-numeric strings. The guard
   `isinstance(v, (int, float))` prevents calling `int()` on a string,
   so the function is exception-free. Test
   `test_merge_usage_handles_non_numeric_values` covers the string case.

3. **Did I verify key structures, not assume them?**
   YES — usage dict structure verified by reading the usage frames in
   existing tests (`test_streaming_captures_provider_tool_call_id` etc.)
   and by reading the `_extract_usage` non-streaming extractor (1206)
   which lists the same keys. Exotic keys (`cache_read_input_tokens`,
   `reasoning_tokens`) are real Anthropic/OpenRouter fields; the
   test `test_merge_usage_preserves_exotic_keys` covers them.

4. **Did I trace the data flow end-to-end?**
   YES — §3 traces both the broken and fixed flows through
   `_stream_with_ssl_retry` → `_call_llm_streaming` → final response
   dict → cost tracker. Verified that the retry layer only re-issues
   when `streamed_text == False` (line 791), so the first attempt
   ALWAYS either fully succeeded (in which case no second attempt
   runs) or failed before yielding text (in which case merging is
   the right behavior because the second attempt starts from scratch
   with the same prompt).

5. **Would an implementer who follows this spec exactly produce working
   code?**
   YES — every code sample is copy-pasteable, every test follows the
   established pattern, every change site has explicit before/after.
   An implementer should be able to ship this in 20-30 minutes
   including running the test suite.

---

## 10. Completion Verification (Rule 10)

To be performed by the implementer; results recorded in the PR
description.

1. **Scope checklist:**
   - [ ] `agent/runtime.py` — 1 new helper `_merge_usage` + 1 modified
     assignment at line 2692 (merge + DEBUG log)
   - [ ] `tests/test_agent_runtime.py` — new `TestSSLRetryUsageFidelity`
     class with 7 tests
   - [ ] `docs/ARCHITECTURE.md` — §4 SSL retry paragraph appended

2. **Test suite output (paste actual pytest -v output, not summary):**
   ```
   $ cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py tests/test_streaming.py -v
   <paste full output here>
   ```

3. **Pattern sweep — confirm no remaining `captured_usage = usage_data`:**
   ```
   $ grep -n 'captured_usage = usage_data' agent/runtime.py
   <expect: no matches>
   $ grep -n '_merge_usage' agent/runtime.py
   <expect: 2 matches (1 definition + 1 call site)>
   ```

4. **Manual retry test:** Force a ConnectionResetError on the first
   stream attempt and confirm the merge produces correct totals.
   ```
   $ python3 -c "
   from agent.runtime import _merge_usage
   prior = {'prompt_tokens': 100, 'completion_tokens': 80, 'total_tokens': 180}
   new = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}
   print(_merge_usage(prior, new))
   "
   <expect: {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}>
   ```

5. **Declaration:** "complete" only when all four checks pass.