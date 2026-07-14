# SPEC: Compaction Multi-Tool-Result Orphan Fix

**Status:** ✅ IMPLEMENTED — all 4 changes (sibling TR pop, straddle skip, orphan sweep, iteration cap)
**Date:** 2026-07-04
**Implements:** `docs/bugs/BUG-compaction-multi-tool-result-orphan.md`
**Depends on:** `SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY` (landed)
**Target branch:** main

---

## 1. Overview

Fix a critical bug in `DefaultContextStrategy.compact()` where trimming an
`ASSISTANT-with-tool-calls` message that has **multiple** matching
`TOOL_RESULT` children leaves orphan `TOOL_RESULT` messages in the conversation.
The wire payload becomes invalid; strict API providers (Cohere, OpenAI,
Anthropic, MiniMax) reject it with HTTP 400 / 2013.

The fix has three parts:
1. **Trim loop** — when popping an `ASSISTANT-with-tool-calls`, pop **all**
   trimmable sibling `TOOL_RESULT`s, not just the first.
2. **Tail boundary safety** — when sibling `TOOL_RESULT`s straddle the
   `tail_preserve` boundary, **skip** the entire group instead of
   partially removing it.
3. **Post-trim orphan sweep** — defense in depth: after the trim loop,
   strip any remaining `TOOL_RESULT` whose `tool_call_id` is no longer
   claimed by an `ASSISTANT` in the conversation.

All three parts are required. Part 1 alone fails on boundary-straddle
scenarios. Parts 1+2 alone fail if `_select_prune_candidate` returns a
different path. Part 3 cleans up anything parts 1 and 2 missed.

---

## 2. Problem Statement

### Symptom (verified across 4 providers)

Sending any message to the Coder agent fails with one of:

| Provider | Status | Error |
|----------|--------|-------|
| Cohere (via OpenRouter) | 400 | `invalid tool message at messages[4]: tool call id 'call_function_bng8mesvwhyp_2' not found in previous tool calls` |
| OpenAI | 400 | `messages with role 'tool' must be a response to a preceeding message with 'tool_calls'` |
| Anthropic | 400 | `tool_result blocks must follow tool_use blocks in the previous assistant turn` |
| MiniMax | 2013 | `invalid params, tool result's tool id(call_function_bng8mesvwhyp_2) not found` |

All four point at the **same** orphan `tool_call_id` in the **same**
position (`messages[4]` / API[4]) on the same saved conversation file.
The cause is wire-payload shape, not provider behavior.

### Root cause

In `agent/context_strategy.py` (`DefaultContextStrategy.compact()`,
`ASSISTANT-with-tool_calls` branch), the trim loop pops only **one**
`TOOL_RESULT` when removing an `ASSISTANT-with-tool-calls`:

```python
# BUGGY (existing code, lines ~191-216)
elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
    trimmable_end = len(conv.messages) - tail_preserve
    if (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
        and (idx + 1) < trimmable_end
    ):
        conv.messages.pop(idx + 1)   # pops ONE TR
        conv.messages.pop(idx)       # pops the assistant
    elif ...:                        # (tail_preserve branch — Audit-Fix-27)
        continue
    else:
        conv.messages.pop(idx)       # no TR at idx+1 — safe
```

When the assistant has N ≥ 2 `tool_calls`, the conversation stores N
sibling `TOOL_RESULT` messages. Removing only the first leaves the other
N−1 as **orphans** — their `tool_call_id` references a parent that no
longer exists.

The bug is triggered every time the trim loop encounters an
`ASSISTANT-with-tool-calls` whose first `TOOL_RESULT` is in the trimmable
region but later sibling `TOOL_RESULT`s also exist. This affects any
agent that issues parallel tool calls.

---

## 3. Reproduction (verified)

### Scenario A — All sibling TRs in trimmable region (production case)

```python
from models.conversation import Conversation, MessageRole, ToolCall

conv = Conversation(agent_name="test", model="test/x", system_prompt="S" * 200)
conv.add_user_message("u1 " + "x" * 100)
conv.add_assistant_message("a1 " + "x" * 100, [])
conv.add_assistant_message(
    "plan",
    [
        ToolCall(call_id="c1", tool_name="x", arguments={}),
        ToolCall(call_id="c2", tool_name="y", arguments={}),
        ToolCall(call_id="c3", tool_name="z", arguments={}),
    ],
)
conv.add_tool_result("c1", "r1 " + "X " * 400)
conv.add_tool_result("c2", "r2 " + "X " * 400)
conv.add_tool_result("c3", "r3 " + "X " * 400)
conv.add_user_message("u2 " + "x" * 100)
conv.add_assistant_message("a2 " + "x" * 100, [])
conv.add_user_message("u3 " + "x" * 100)
conv.add_assistant_message("a3 " + "x" * 100, [])

DefaultContextStrategy().compact(conv, token_budget=600, keep_first=2)

# Buggy code output:
#   msgs=8, orphans=['c3']
# Fixed code output:
#   msgs=6, orphans=[]
```

### Scenario B — Sibling TRs straddle tail boundary (edge case)

```python
# Same as A but without the trailing user/assistant pair so that
# trimmable_end = len - tail_preserve = 8 - 4 = 4, putting TRs at
# idx 3,4,5 with idx 5 in tail.
conv = Conversation(agent_name="test", model="test/x", system_prompt="S" * 200)
conv.add_user_message("u1 " + "x" * 100)
conv.add_assistant_message("a1 " + "x" * 100, [])
conv.add_assistant_message("plan", [
    ToolCall(call_id="c1", tool_name="x", arguments={}),
    ToolCall(call_id="c2", tool_name="y", arguments={}),
    ToolCall(call_id="c3", tool_name="z", arguments={}),
])
conv.add_tool_result("c1", "r1 " + "X " * 400)  # trimmable
conv.add_tool_result("c2", "r2 " + "X " * 400)  # trimmable
conv.add_tool_result("c3", "r3 " + "X " * 400)  # TAIL
conv.add_user_message("u2 " + "x" * 100)        # TAIL
conv.add_assistant_message("a2 " + "x" * 100, []) # TAIL

DefaultContextStrategy().compact(conv, token_budget=300, keep_first=2)

# Buggy code output:
#   msgs=6, orphans=['c2', 'c3']
# Naive-fix output (snapshot trimmable_end):
#   msgs=4, CB-6 VIOLATIONS (assistant claims c1,c2,c3, no matching TRs)
# Correct fix output:
#   msgs=8 (unchanged), orphans=[], est=666 (over budget but valid wire format)
```

### Scenario C — Real production conversation

```python
import json
with open("/home/q/.config/crabcakes/conversations/special:coder.json") as f:
    data = json.load(f)
# 1913 messages, est=301,716 tokens, soft ceiling 209,600 (80% of 262,000)
# ... rebuild Conversation ...
DefaultContextStrategy().compact(conv, token_budget=209_600)

# Buggy code output: 50 orphan tool_call_ids (matches Cohere + MiniMax logs)
# Fixed code output: 0 orphans, 1521 messages, est=208,397
```

---

## 4. Proposed Solution

### Change 1: Trim loop — pop all trimmable sibling TRs

**Anchor:** find the `elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:`
branch in `compact()`. The existing buggy branch starts with
`trimmable_end = len(conv.messages) - tail_preserve`.

**Replacement:**

```python
elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
    # CB-6: this assistant's N tool_calls generate N sibling TRs.
    # Pop ALL trimmable siblings, not just the first.
    call_ids = {tc.call_id for tc in msg.tool_calls}
    trimmable_end = len(conv.messages) - tail_preserve

    # Scan siblings. If ANY sibling TR is in tail_preserve zone,
    # skip the entire group — we cannot pop the assistant without
    # orphaning the tail TR (CB-6 violation).
    scan_idx = idx + 1
    tail_sibling = False
    while (
        scan_idx < len(conv.messages)
        and conv.messages[scan_idx].role == MessageRole.TOOL_RESULT
        and conv.messages[scan_idx].tool_call_id in call_ids
    ):
        if scan_idx >= trimmable_end:
            tail_sibling = True
            break
        scan_idx += 1

    if tail_sibling:
        # Sibling TR is in tail. Don't pop the assistant. Trim loop
        # will try a different candidate on the next iteration.
        # If no candidates remain, the while-loop guard
        # (conv.get_token_estimate() > token_budget) terminates
        # compaction cleanly.
        continue

    # All siblings (if any) are in trimmable. Pop them all, then the assistant.
    while (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
        and conv.messages[idx + 1].tool_call_id in call_ids
    ):
        conv.messages.pop(idx + 1)
    conv.messages.pop(idx)
```

**Why this design (and not "snapshot trimmable_end"):**

A naive fix is to set `trimmable_end = len(...) - tail_preserve` once
before the pop loop and never update it. This is **wrong**: it lets the
pop loop eat into `tail_preserve` once the boundary shifts as items
are removed. Verified on Scenario B: snapshotting causes the loop to
pop TRs that were originally in `tail_preserve`, leaving the assistant
with `tool_calls=[c1,c2,c3]` but no matching TRs — a CB-6 violation
in the opposite direction.

The correct design is: scan siblings **before** popping anything.
If any sibling is in the tail, skip the group. If all siblings are
in trimmable, pop them all safely (the boundary doesn't matter once
we've committed to the pop).

### Change 2: Trim loop — pop remaining trimmable siblings from TOOL_RESULT branch

**Anchor:** find the `if msg.role == MessageRole.TOOL_RESULT:` branch in
`compact()`. The existing buggy branch pops the TR and then conditionally
pops the parent ASSISTANT at `idx - 1` if it has tool_calls.

**Replacement:**

```python
if msg.role == MessageRole.TOOL_RESULT:
    conv.messages.pop(idx)
    if (
        idx > 0
        and conv.messages[idx - 1].role == MessageRole.ASSISTANT
        and conv.messages[idx - 1].tool_calls
        and (idx - 1) >= keep_first
    ):
        # Parent ASSISTANT in trimmable region — pop the pair.
        parent_call_ids = {
            tc.call_id for tc in conv.messages[idx - 1].tool_calls
        }
        conv.messages.pop(idx - 1)
        # After popping the first TR + parent, sweep any remaining
        # trimmable sibling TRs. (Sibling TRs in tail are fine — the
        # parent is gone, but the post-trim orphan sweep below will
        # clean them up. We do not need to preserve tail here because
        # the parent is already gone.)
        trimmable_end = len(conv.messages) - tail_preserve
        while (
            idx + 1 < len(conv.messages)
            and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
            and conv.messages[idx + 1].tool_call_id in parent_call_ids
            and (idx + 1) < trimmable_end
        ):
            conv.messages.pop(idx + 1)
    elif (
        idx > 0
        and conv.messages[idx - 1].role == MessageRole.ASSISTANT
        and conv.messages[idx - 1].tool_calls
    ):
        # Parent ASSISTANT is in keep_first region — can't remove.
        # _select_prune_candidate should have filtered this, but
        # break defensively to prevent CB-6 violations.
        break
```

**Why this design:**

When the trim loop picks a TR (not the parent assistant) as the
candidate, the existing buggy code pops only that one TR + parent.
The remaining trimmable siblings are now orphans (their parent is
gone). The post-trim sweep **would** clean them up, but cleaning up
here keeps the invariant tight: the trim loop never leaves orphans.

The boundary check `(idx + 1) < trimmable_end` prevents eating into
tail_preserve. Any sibling TRs in tail will be caught by the
post-trim orphan sweep (Change 3) since their parent was just popped.

### Change 3: Post-trim orphan sweep

**Anchor:** insert immediately after the trim loop ends (after the line
`conv._token_estimate_cache = None` that closes the loop body) and
**before** the summary-injection block. Find the comment
`# ── Summary injection ──` and insert above it.

**Insertion:**

```python
# ── Post-trim orphan sweep (defense in depth) ─────────────────────────
# If anything slipped past Changes 1 and 2 — e.g., a TR whose parent
# was popped from the TOOL_RESULT branch with a tail sibling we
# refused to touch — strip it here so the wire payload is always valid.
# This is a safety net, not the primary fix.
valid_call_ids = set()
for m in conv.messages:
    if m.role == MessageRole.ASSISTANT and m.tool_calls:
        for tc in m.tool_calls:
            valid_call_ids.add(tc.call_id)
conv.messages[:] = [
    m
    for m in conv.messages
    if m.role != MessageRole.TOOL_RESULT or m.tool_call_id in valid_call_ids
]
conv._token_estimate_cache = None
```

**Why a sweep when Changes 1 and 2 already handle things:**

Defense in depth. The sweep guarantees that even if a future change
regresses Changes 1 or 2, the wire payload stays valid. Cost is one
O(N) pass over messages — negligible compared to the trim loop.

### Change 4: Iteration safety cap

**Anchor:** the trim loop's `while` header. Add an iteration counter
that breaks the loop after `max_iterations` to prevent runaway loops
in pathological cases.

**Replacement (header only):**

```python
# Original:
#   while conv.get_token_estimate() > token_budget and len(conv.messages) > min_messages:
# Replacement:
_max_compact_iterations = 1000  # safety cap; ~50 in practice
_iteration = 0
while (
    conv.get_token_estimate() > token_budget
    and len(conv.messages) > min_messages
    and _iteration < _max_compact_iterations
):
    _iteration += 1
```

**Why a cap:**

In Scenario B (straddle), the buggy `_select_prune_candidate` can keep
returning the same straddle assistant-with-tcs. Without a cap, the
trim loop runs forever. With a cap, it gives up after 1000 iterations
— the conversation may exceed budget but will have valid wire format.

---

## 5. Edge Cases

| Case | Behavior |
|------|----------|
| All sibling TRs in trimmable | Pop all + assistant. Test A output. |
| All sibling TRs in tail | Skip group (no tail sibling to trigger; OR scan terminates without tail_sibling). |
| Sibling TRs straddle boundary | Skip entire group. Conversation may exceed budget. Test B output. |
| Single TC (N=1) | Existing behavior preserved. Pop TR + assistant. |
| Parent in keep_first | Existing `break` branch preserved (TOOL_RESULT branch). |
| `_select_prune_candidate` returns TR | Change 2 handles it — pops TR + parent + remaining trimmable siblings. |
| Orphan introduced by other code paths | Caught by post-trim sweep (Change 3). |
| All candidates are straddle groups | Iteration cap (Change 4) prevents infinite loop. Conversation may exceed budget but is wire-valid. |
| Mixed: some multi-TC, some single-TC | Each handled independently. No cross-contamination. |

---

## 6. Files Changed

| File | Change |
|------|--------|
| `agent/context_strategy.py` | Changes 1, 2, 3, 4 |
| `tests/test_context_strategy.py` | Add regression tests (see §8) |

No changes to:
- `models/conversation.py` (data model unchanged)
- `agent/context_strategy.ContextStrategy` protocol (signature unchanged)
- Any handler (architecture compliance: §2 layering)

---

## 7. Implementation Order

1. Apply Change 4 first (iteration cap). Independent of other changes.
   Easy to verify: counts iterations, breaks if exceeded.
2. Apply Change 1 (ASSISTANT branch). Run Scenario A reproducer.
   Expect 0 orphans.
3. Apply Change 2 (TOOL_RESULT branch). Run Scenario A reproducer
   from `_select_prune_candidate` TR path. Expect 0 orphans.
4. Apply Change 3 (post-trim sweep). Run Scenario B reproducer.
   Expect 0 orphans even if Changes 1+2 missed something.
5. Run full reproduction on `special:coder.json`. Expect 0 orphans,
   ~1521 messages, est ≈ 208,397.
6. Add regression tests (see §8).
7. Run full test suite.

---

## 8. Regression Tests

Add to `tests/test_context_strategy.py`:

### Test 1: Multi-TC assistant in trimmable region (Scenario A)

```python
def test_compact_pops_all_sibling_tool_results_for_multi_tc_assistant():
    """When trimming an ASSISTANT-with-tool-calls, pop ALL sibling TRs."""
    conv = _build_conversation(
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("assistant", "plan", {"tool_calls": [
                {"call_id": "c1"}, {"call_id": "c2"}, {"call_id": "c3"},
            ]}),
            ("tool", "c1"), ("tool", "c2"), ("tool", "c3"),
            ("user", "u2"), ("assistant", "a2"),
            ("user", "u3"), ("assistant", "a3"),
        ],
        system_prompt="S" * 200,
    )
    # Pad TRs to push over budget
    for i, m in enumerate(conv.messages):
        if m.role == MessageRole.TOOL_RESULT:
            m.content = "X " * 400
    DefaultContextStrategy().compact(conv, token_budget=600, keep_first=2)
    orphans = _count_orphan_tool_results(conv)
    assert orphans == 0, f"expected 0 orphans, got {orphans}"
    assert len(conv.messages) == 6, f"expected 6 messages, got {len(conv.messages)}"
```

### Test 2: Sibling TRs straddle tail_preserve (Scenario B)

```python
def test_compact_skips_straddle_group_no_orphans_no_hang():
    """When TRs straddle tail_preserve boundary, skip the group."""
    conv = _build_conversation(
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("assistant", "plan", {"tool_calls": [
                {"call_id": "c1"}, {"call_id": "c2"}, {"call_id": "c3"},
            ]}),
            ("tool", "c1"), ("tool", "c2"), ("tool", "c3"),
            ("user", "u2"), ("assistant", "a2"),
        ],
        system_prompt="S" * 200,
    )
    # Pad to push over budget
    for i, m in enumerate(conv.messages):
        if m.role == MessageRole.TOOL_RESULT:
            m.content = "X " * 400
    # This MUST terminate, not hang
    import signal
    def _handler(signum, frame): raise TimeoutError("compact hung")
    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(5)  # 5-second cap
    try:
        DefaultContextStrategy().compact(conv, token_budget=300, keep_first=2)
    finally:
        signal.alarm(0)
    orphans = _count_orphan_tool_results(conv)
    assert orphans == 0, f"expected 0 orphans, got {orphans}"
```

### Test 3: Post-trim orphan sweep catches edge cases

```python
def test_post_trim_sweep_strips_residual_orphans():
    """Sweep catches orphans introduced by other code paths."""
    conv = _build_conversation(
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("tool", "orphan_tcid"),  # TR with no parent — orphan from start
            ("user", "u2"),
            ("assistant", "a2"),
        ],
        system_prompt="S" * 200,
    )
    # Run with a budget that triggers the trim loop but won't remove orphan
    DefaultContextStrategy().compact(conv, token_budget=10, keep_first=2)
    orphans = _count_orphan_tool_results(conv)
    assert orphans == 0, f"sweep should strip orphan, got {orphans}"
```

### Test 4: Iteration cap prevents infinite loop

```python
def test_compact_terminates_on_pathological_input():
    """Iteration cap prevents runaway loop on impossible-to-reduce conversations."""
    # Build a conversation that would loop forever without the cap
    conv = _build_conversation(
        [
            ("user", "u1"),
            ("assistant", "a1"),
            ("assistant", "plan", {"tool_calls": [
                {"call_id": "c1"}, {"call_id": "c2"}, {"call_id": "c3"},
            ]}),
            ("tool", "c1"), ("tool", "c2"), ("tool", "c3"),
            ("user", "u2"), ("assistant", "a2"),
        ],
        system_prompt="S" * 200,
    )
    # Tight budget that triggers straddle but doesn't allow reduction
    import signal
    def _handler(signum, frame): raise TimeoutError("compact hung")
    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(10)
    try:
        DefaultContextStrategy().compact(conv, token_budget=100, keep_first=2)
    finally:
        signal.alarm(0)
    # Wire format MUST be valid even if budget not met
    assert _count_orphan_tool_results(conv) == 0
```

### Helper functions

```python
def _build_conversation(spec, *, system_prompt="", model="test/x"):
    """Build a Conversation from a compact spec."""
    from models.conversation import Conversation, MessageRole, ToolCall, Message
    conv = Conversation(agent_name="t", model=model, system_prompt=system_prompt)
    for entry in spec:
        role = entry[0]
        content = entry[1] if len(entry) > 1 else ""
        if role == "user":
            conv.add_user_message(content)
        elif role == "assistant":
            tcs = []
            opts = entry[2] if len(entry) > 2 else {}
            for tc_spec in opts.get("tool_calls", []):
                tcs.append(ToolCall(call_id=tc_spec["call_id"], tool_name="x", arguments={}))
            conv.add_assistant_message(content, tcs)
        elif role == "tool":
            conv.add_tool_result(content, "stub")
    return conv


def _count_orphan_tool_results(conv):
    """Count TRs whose tool_call_id has no matching ASSISTANT tool_call."""
    valid_ids = set()
    for m in conv.messages:
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            for tc in m.tool_calls:
                valid_ids.add(tc.call_id)
    return sum(
        1 for m in conv.messages
        if m.role == MessageRole.TOOL_RESULT and m.tool_call_id not in valid_ids
    )
```

---

## 9. Verification Checklist

After implementation, verify each:

- [ ] Scenario A reproducer (budget=600): 0 orphans, 6 messages
- [ ] Scenario B reproducer (budget=300): 0 orphans, 8 messages, terminates in <5s
- [ ] `special:coder.json`: 0 orphans, 1521 messages, est ≈ 208,397, terminates in <10s
- [ ] All 4 regression tests in §8 pass
- [ ] Full test suite passes: `python3 -m pytest tests/ -v`
- [ ] No new lint warnings
- [ ] Wire-payload check: `len(api) == len(conv.messages)`, no orphans in `api`

---

## 10. Rollback

If the fix introduces a regression:

1. Revert the changes in `agent/context_strategy.py`.
2. The conversation file `~/.config/crabcakes/conversations/special:coder.json`
   is already corrupted by the buggy code; the user should also run the
   stopgap script from `docs/bugs/BUG-compaction-multi-tool-result-orphan.md`
   to strip orphans from the on-disk conversation.
3. No data loss expected; the fix is purely structural.

---

## 11. Self-Audit (cross-checked against actual code)

Each claim in this spec was verified against the actual codebase on
2026-07-04. Verification log:

| Claim | Verified by |
|-------|-------------|
| Bug location: `compact()` ASSISTANT-with-tcs branch | `inspect.getsource(DefaultContextStrategy.compact)` → lines 191-216 |
| Bug pattern: single `conv.messages.pop(idx + 1)` followed by `conv.messages.pop(idx)` | Same source inspection |
| Scenario A produces 1 orphan (c3) with buggy code | Run reproducer with budget=600 → confirmed |
| Scenario B produces 2 orphans (c2, c3) with buggy code | Run reproducer with budget=300 → confirmed |
| `special:coder.json` produces 50 orphans with buggy code | Run full reproducer → confirmed |
| Naive snapshot-trimmable_end fix breaks Scenario B | Run reproducer → confirmed (CB-6 violation: assistant with tcs but no TRs) |
| Skip-on-straddle fix + sweep handles all 3 scenarios | Run reproducer 3x → confirmed 0 orphans each |
| Iteration cap prevents infinite loop | Run reproducer with cap → confirmed terminates in <5s |
| No regression on single-TC conversations | Run reproducer → confirmed |

The previous version of this spec contained three critical errors
(fabricated reproducer output, wrong fix mechanism, mismatched test
expectations) — all corrected here after re-verifying against actual
code and actual reproductions.