# SPEC: Compaction Orphans Multi-Tool-Call Results

**Date:** 2026-07-04
**Author:** qaster (OC Tech Supervisor)
**Status:** Draft — for implementation
**Implements:** `docs/bugs/BUG-compaction-multi-tool-result-orphan.md`
**Depends on:** None (prior SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY already landed)
**Target branch:** main

> Architecture compliance: This fix is internal to `DefaultContextStrategy.compact()` in `agent/context_strategy.py`. It does not change the `ContextStrategy` protocol, `Conversation` data model, or any handler. Per ARCHITECTURE.md §3.21l, compaction logic lives in the strategy class, not in `Conversation`.

---

## 1. Overview

### Problem

When an assistant message issues **multiple tool calls** (e.g. `c1`, `c2`, `c3`), the conversation stores three separate `TOOL_RESULT` messages — one per call ID. The trim loop in `DefaultContextStrategy.compact()` only pops **one** `TOOL_RESULT` when removing the parent `ASSISTANT-with-tool-calls`. The remaining tool results become **orphans**: their `tool_call_id` references a parent that no longer exists in the message list. Any strict API provider (OpenAI, Cohere, MiniMax, Anthropic) rejects the payload with HTTP 400.

### Reproduction (verified deterministically)

```python
conv = Conversation(agent_name="test", model="test/x", system_prompt="S" * 200)
conv.add_user_message("u1" + " x" * 100)
conv.add_assistant_message("a1" + " x" * 100, [])
conv.add_assistant_message("plan", [
    ToolCall(call_id="c1", tool_name="x", arguments={}),
    ToolCall(call_id="c2", tool_name="y", arguments={}),
    ToolCall(call_id="c3", tool_name="z", arguments={}),
])
conv.add_tool_result("c1", "result1 " + "X " * 400)
conv.add_tool_result("c2", "result2 " + "X " * 400)
conv.add_tool_result("c3", "result3 " + "X " * 400)
conv.add_user_message("u2" + " x" * 100)
conv.add_assistant_message("a2" + " x" * 100, [])
conv.add_user_message("u3" + " x" * 100)
conv.add_assistant_message("a3" + " x" * 100, [])

DefaultContextStrategy().compact(conv, token_budget=1518, keep_first=2)
# Result: 8 messages, 2 orphaned TOOL_RESULTs (c2, c3)
```

**Root cause line:** `agent/context_strategy.py:193-202` — the ASSISTANT-with-tool-calls branch pops only the immediately following `TOOL_RESULT`:

```python
# Lines 193-202 (current, buggy)
elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
    trimmable_end = len(conv.messages) - tail_preserve
    if (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
        and (idx + 1) < trimmable_end
    ):
        conv.messages.pop(idx + 1)   # ← pops ONE tool result
        conv.messages.pop(idx)       # ← pops the assistant
```

### Solution

Two-part fix, both in `agent/context_strategy.py`:

1. **Trim loop fix** (lines 193-218): Replace the single-pop with a `while` loop that pops **all** consecutive `TOOL_RESULT` messages whose `tool_call_id` matches one of the assistant's `tool_calls[].call_id`, followed by the assistant itself. Includes the same tail_preserve-zone safety check as the existing code.

2. **Post-trim orphan sweep**: A defensive one-pass filter that removes any `TOOL_RESULT` whose parent `ASSISTANT-with-tool-calls` has been removed by any prior trim-loop iteration. Runs after the trim loop exits and before summary injection. Catches orphans from all code paths (including the TOOL_RESULT branch and the budget-met-mid-cleanup edge case).

### Scope

| Area | In scope | Out of scope |
|------|----------|--------------|
| `compact()` trim loop | ✅ Fix ASSISTANT branch multi-TR handling | |
| `compact()` TOOL_RESULT branch | ✅ Fix same multi-TR orphan when TR is selected first | |
| `compact()` post-trim sweep | ✅ Add orphan sweep before summary injection | |
| `to_api_messages()` | | ❌ Already correct (serializes whatever is in `conv.messages`) |
| `_select_prune_candidate()` | | ❌ Already correct (returns the right index; the pop logic is the bug) |
| `_find_split_index()` | | ❌ Already handles multi-TR CB-6 (Phase 9 hardening) |
| `Conversation` data model | | ❌ No changes |
| `ContextStrategy` protocol | | ❌ No changes |

---

## 2. Changes by File

### `agent/context_strategy.py`

#### Change 1: ASSISTANT-with-tool-calls trim branch (lines 193-218)

**Current code (lines 193-218):**

```python
elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
    trimmable_end = len(conv.messages) - tail_preserve
    if (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
        and (idx + 1) < trimmable_end
    ):
        # CB-6 safe: ASSISTANT+tc and TR both in trimmable region.
        conv.messages.pop(idx + 1)
        conv.messages.pop(idx)
    elif (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
    ):
        # Audit-Fix-27 (Bug #4): TR is in tail_preserve zone — ...
        continue
    else:
        # No TOOL_RESULT at idx+1 — safe to pop ASSISTANT alone.
        conv.messages.pop(idx)
```

**Replacement code:**

```python
elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
    # CB-6: this ASSISTANT's N tool_calls generate N matching
    # TOOL_RESULT messages. Pop ALL of them, not just the first.
    call_ids = {tc.call_id for tc in msg.tool_calls}
    trimmable_end = len(conv.messages) - tail_preserve

    # Pop all consecutive matching TRs that are in the trimmable region.
    while (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
        and (idx + 1) < trimmable_end
        and conv.messages[idx + 1].tool_call_id in call_ids
    ):
        conv.messages.pop(idx + 1)

    # Check if any matching TR landed in the tail_preserve zone.
    # If so, we cannot remove the ASSISTANT without orphaning that TR.
    # Skip this candidate (same logic as Audit-Fix-27 Bug #4).
    next_msg = (
        conv.messages[idx + 1]
        if idx + 1 < len(conv.messages)
        else None
    )
    if (
        next_msg is not None
        and next_msg.role == MessageRole.TOOL_RESULT
        and next_msg.tool_call_id in call_ids
    ):
        # A matching TR is in tail_preserve — bail out.
        continue

    # All matching TRs popped (or none existed). Safe to remove ASSISTANT.
    conv.messages.pop(idx)
```

**What changes:**
- Replaces single `pop(idx + 1)` with a `while` loop that pops all consecutive matching TRs.
- The `call_ids` set ensures we only pop TRs belonging to THIS assistant (not adjacent ones from a different assistant).
- The tail_preserve safety check is preserved: if any matching TR is in the tail, we `continue` without popping the assistant.
- The "no TR at idx+1" case is handled naturally: the while loop doesn't execute, the tail check passes (next_msg is not a matching TR), and the assistant is popped.

#### Change 2: TOOL_RESULT branch (lines 174-191)

**Current code (lines 174-191):**

```python
if msg.role == MessageRole.TOOL_RESULT:
    conv.messages.pop(idx)
    if (
        idx > 0
        and conv.messages[idx - 1].role == MessageRole.ASSISTANT
        and conv.messages[idx - 1].tool_calls
        and (idx - 1) >= keep_first
    ):
        conv.messages.pop(idx - 1)
    elif (
        idx > 0
        and conv.messages[idx - 1].role == MessageRole.ASSISTANT
        and conv.messages[idx - 1].tool_calls
    ):
        break
```

**Replacement code:**

```python
if msg.role == MessageRole.TOOL_RESULT:
    # CB-6: this TR's parent ASSISTANT may have multiple tool_calls.
    # If the parent is being removed, remove ALL its TRs, not just this one.
    conv.messages.pop(idx)
    if (
        idx > 0
        and conv.messages[idx - 1].role == MessageRole.ASSISTANT
        and conv.messages[idx - 1].tool_calls
        and (idx - 1) >= keep_first
    ):
        parent_call_ids = {
            tc.call_id for tc in conv.messages[idx - 1].tool_calls
        }
        conv.messages.pop(idx - 1)
        # Pop any remaining TRs from this same parent that are still
        # at the new idx-1 position (consecutive TRs shift down).
        new_idx = idx - 1
        while (
            new_idx < len(conv.messages)
            and conv.messages[new_idx].role == MessageRole.TOOL_RESULT
            and conv.messages[new_idx].tool_call_id in parent_call_ids
            and new_idx < (len(conv.messages) - tail_preserve)
        ):
            conv.messages.pop(new_idx)
    elif (
        idx > 0
        and conv.messages[idx - 1].role == MessageRole.ASSISTANT
        and conv.messages[idx - 1].tool_calls
    ):
        # Parent ASSISTANT is in keep_first region — can't remove.
        break
```

**What changes:**
- After popping the TR and the parent ASSISTANT, a `while` loop removes any remaining consecutive TRs from the same parent.
- The `new_idx < (len(conv.messages) - tail_preserve)` guard prevents popping TRs that have shifted into the tail_preserve zone (those are handled by the post-trim sweep if they become orphans).
- The keep_first safety `break` is preserved unchanged.

#### Change 3: Post-trim orphan sweep (new code, inserted after line 219)

**Insert between line 219** (`conv._token_estimate_cache = None` — end of trim loop) **and line 221** (the summary injection comment block):

```python
        # ── Post-trim orphan sweep ────────────────────────────────────────
        # Defensively remove any TOOL_RESULT whose parent ASSISTANT-with-
        # tool_calls was removed by the trim loop. This catches orphans
        # from all code paths: budget-met-mid-cleanup, edge cases in
        # _select_prune_candidate fallthrough, and any future trim logic.
        valid_call_ids: set[str] = set()
        for m in conv.messages:
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                for tc in m.tool_calls:
                    valid_call_ids.add(tc.call_id)
        conv.messages[:] = [
            m for m in conv.messages
            if m.role != MessageRole.TOOL_RESULT
            or (m.tool_call_id in valid_call_ids)
        ]
        conv._token_estimate_cache = None
```

**What it does:**
- Builds a set of all `call_id`s from surviving ASSISTANT-with-tool-calls messages.
- Removes any TOOL_RESULT whose `tool_call_id` is NOT in that set.
- This is O(N) in the number of messages — runs once per `compact()` call, after the trim loop exits.
- The cache invalidation is needed because message removal changes the token count.

**Why this is safe:**
- A well-formed conversation has zero orphans — the sweep is a no-op.
- A corrupted conversation (from the bug) gets cleaned up — the sweep removes only the orphans.
- The sweep runs BEFORE summary injection, so the summary reflects the post-orphan-cleanup message list.

---

## 3. Data Flow

```
User sends message
  → _run_loop() calls compact()
    → Layer 1: prune_tool_outputs() (stubs old TR content in-place)
    → Layer 2: trim loop
      → _select_prune_candidate() returns an index
      → If ASSISTANT-with-tool-calls:
         → NEW: while-loop pops ALL matching TRs (not just first)
         → If any TR is in tail_preserve → continue (skip candidate)
         → Pop the ASSISTANT
      → If TOOL_RESULT:
         → Pop the TR
         → If parent ASSISTANT in trimmable region:
            → NEW: pop ASSISTANT, then while-loop pops remaining sibling TRs
      → NEW: Post-trim orphan sweep (catches anything missed)
    → Layer 3: Summary injection (operates on cleaned message list)
  → to_api_messages() serializes orphan-free conversation
  → API call succeeds
```

---

## 4. File Change Summary

| File | Change type | Lines affected | Risk |
|------|-------------|----------------|------|
| `agent/context_strategy.py` | Modified | ~193-218 (ASSISTANT branch) | Medium — core compaction path |
| `agent/context_strategy.py` | Modified | ~174-191 (TOOL_RESULT branch) | Medium — less common path but same invariant |
| `agent/context_strategy.py` | Inserted | After ~219 (post-trim sweep) | Low — additive defensive filter |
| `tests/test_context_strategy.py` | Added | New test methods in existing class | None |

**Files NOT changed** (already correct):
- `models/conversation.py` — `to_api_messages()` serializes whatever is in `conv.messages`. No changes needed.
- `agent/runtime.py` — `_run_loop` calls `compact()` and then `to_api_messages()`. Already correct.
- `agent/context_strategy.py:_select_prune_candidate()` — Returns the right index. The bug is in the pop logic, not the selection.
- `agent/context_strategy.py:_find_split_index()` — Already handles multi-TR CB-6 (Phase 9 hardening with bounce detection).
- `agent/context_strategy.py:prune_tool_outputs()` — Stubs content in-place, doesn't remove messages. No orphan risk.

---

## 5. Implementation Order

1. **Add the test first** (TDD). Write the failing test in `tests/test_context_strategy.py` using the verified reproducer. Run it — it should fail with `assert 2 == 0` (2 orphans found).

2. **Fix Change 1** (ASSISTANT branch). Replace lines 193-218 with the multi-TR while-loop version. Run the test — it should pass.

3. **Fix Change 2** (TOOL_RESULT branch). Replace lines 174-191 with the multi-TR sibling-pop version. The test from step 2 still passes (it exercises the ASSISTANT branch). Add a second test that exercises the TR-first code path.

4. **Add Change 3** (post-trim orphan sweep). Insert after the trim loop. Run all tests — existing tests still pass, and the sweep is a no-op on well-formed conversations.

5. **Run full test suite.** `python -m pytest tests/test_context_strategy.py -v` — all tests must pass.

6. **Pattern sweep.** `grep -n "pop(idx + 1)" agent/context_strategy.py` — confirm no single-pop patterns remain in the trim loop. The only pops should be inside while-loops or the `else: pop(idx)` fallback.

---

## 6. Acceptance Criteria

- [ ] `test_compact_does_not_orphan_remaining_tool_results` passes — the deterministic reproducer (budget=1518, 3 tool calls) produces zero orphans after `compact()`.
- [ ] `test_compact_tr_result_branch_multi_tool` passes — same invariant when `_select_prune_candidate` returns a TOOL_RESULT index.
- [ ] `test_post_trim_orphan_sweep_cleans_existing_orphans` passes — a pre-corrupted conversation with orphans gets cleaned up by the sweep even if the trim loop doesn't fire.
- [ ] All existing tests in `tests/test_context_strategy.py` pass unchanged.
- [ ] `grep -n "pop(idx + 1)" agent/context_strategy.py` returns zero matches inside the trim loop (lines 170-220).
- [ ] No new orphan TOOL_RESULTs in any test conversation after compaction.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Single tool call (1 TC + 1 TR) | Identical to current behavior — while-loop pops one TR, then the assistant |
| Three tool calls, all TRs in trimmable region | While-loop pops all 3 TRs, then the assistant |
| Three tool calls, TR #3 in tail_preserve | `continue` — assistant is NOT removed (protects tail TR from orphaning) |
| Three tool calls, TR #1 in trimmable, TR #2-3 in tail | `continue` — same as above, the tail check fires on TR #2 |
| Zero tool calls on assistant | Falls through to `else: conv.messages.pop(idx)` — unchanged |
| Budget met after removing ASSISTANT + TRs | Post-trim sweep removes any straggler orphans from earlier iterations |
| Pre-corrupted conversation with orphans | Post-trim sweep cleans them, even if trim loop is a no-op |
| `_select_prune_candidate` returns TR index (not assistant) | TOOL_RESULT branch pops the TR, the parent ASSISTANT, and all sibling TRs |
| Parent ASSISTANT in keep_first region | `break` — same as current behavior (preserves CB-6 at boundary) |
| Duplicate `tool_call_id` in conversation (malformed) | `call_ids` set deduplicates; sweep uses set membership, so all matching TRs are handled |

---

## 8. Test Code

### Test 1: Multi-tool-call ASSISTANT branch

```python
def test_compact_does_not_orphan_remaining_tool_results(self):
    """BUG: when an assistant has multiple tool_calls, compact() must
    remove ALL matching TRs, not just the first.

    Reproducer: budget calibrated so the trim loop exits immediately
    after removing the ASSISTANT + first TR, before the remaining
    TRs can be cleaned up individually.
    """
    conv = Conversation(
        agent_name="test", model="test/x",
        system_prompt="S" * 200,
    )
    conv.add_user_message("u1" + " x" * 100)
    conv.add_assistant_message("a1" + " x" * 100, [])
    conv.add_assistant_message("plan", [
        ToolCall(call_id="c1", tool_name="x", arguments={}),
        ToolCall(call_id="c2", tool_name="y", arguments={}),
        ToolCall(call_id="c3", tool_name="z", arguments={}),
    ])
    conv.add_tool_result("c1", "result1 " + "X " * 400)
    conv.add_tool_result("c2", "result2 " + "X " * 400)
    conv.add_tool_result("c3", "result3 " + "X " * 400)
    conv.add_user_message("u2" + " x" * 100)
    conv.add_assistant_message("a2" + " x" * 100, [])
    conv.add_user_message("u3" + " x" * 100)
    conv.add_assistant_message("a3" + " x" * 100, [])

    DefaultContextStrategy().compact(conv, token_budget=1518, keep_first=2)

    # Verify NO orphan TRs remain
    valid_ids: set[str] = set()
    for m in conv.messages:
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            valid_ids.update(tc.call_id for tc in m.tool_calls)
    for m in conv.messages:
        if m.role == MessageRole.TOOL_RESULT:
            assert m.tool_call_id in valid_ids, (
                f"orphan TR: {m.tool_call_id}"
            )
```

### Test 2: Post-trim orphan sweep on pre-corrupted conversation

```python
def test_post_trim_orphan_sweep_cleans_existing_orphans(self):
    """The orphan sweep must clean up TRs whose parent was removed,
    even if the trim loop itself is a no-op (budget already met)."""
    conv = Conversation(
        agent_name="test", model="test/x",
        system_prompt="S" * 200,
    )
    conv.add_user_message("u1")
    conv.add_assistant_message("a1", [])
    # Orphan TRs — no parent ASSISTANT in the conversation
    conv.messages.append(Message(
        role=MessageRole.TOOL_RESULT,
        content="orphan1",
        tool_call_id="ghost_call_1",
    ))
    conv.messages.append(Message(
        role=MessageRole.TOOL_RESULT,
        content="orphan2",
        tool_call_id="ghost_call_2",
    ))
    conv.add_user_message("u2")
    conv.add_assistant_message("a2", [])
    conv.add_user_message("u3")
    conv.add_assistant_message("a3", [])

    # Budget is high enough that trim loop is a no-op.
    # The orphan sweep should still fire and remove the ghost TRs.
    tokens = conv.get_token_estimate()
    DefaultContextStrategy().compact(conv, token_budget=tokens + 1000, keep_first=2)

    valid_ids: set[str] = set()
    for m in conv.messages:
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            valid_ids.update(tc.call_id for tc in m.tool_calls)
    for m in conv.messages:
        if m.role == MessageRole.TOOL_RESULT:
            assert m.tool_call_id in valid_ids, (
                f"orphan TR survived sweep: {m.tool_call_id}"
            )
```

### Test 3: TR-first code path

```python
def test_compact_tr_branch_handles_multi_tool(self):
    """When _select_prune_candidate returns a TOOL_RESULT index
    (TR-first path), the trim loop must also clean up sibling TRs
    from the same parent ASSISTANT."""
    conv = Conversation(
        agent_name="test", model="test/x",
        system_prompt="S" * 200,
    )
    conv.add_user_message("u1" + " x" * 100)
    conv.add_assistant_message("a1" + " x" * 100, [])
    # A filler message so the ASSISTANT is not the first candidate
    conv.add_user_message("filler" + " x" * 100)
    # Assistant with 2 tool calls
    conv.add_assistant_message("plan", [
        ToolCall(call_id="c1", tool_name="x", arguments={}),
        ToolCall(call_id="c2", tool_name="y", arguments={}),
    ])
    conv.add_tool_result("c1", "result1 " + "X " * 400)
    conv.add_tool_result("c2", "result2 " + "X " * 400)
    conv.add_user_message("u2" + " x" * 100)
    conv.add_assistant_message("a2" + " x" * 100, [])
    conv.add_user_message("u3" + " x" * 100)
    conv.add_assistant_message("a3" + " x" * 100, [])

    # Calibrate budget so trim loop removes the multi-tool group
    # but not everything else.
    s = DefaultContextStrategy()
    s.prune_tool_outputs(conv, target_tokens=1, protect_turns=2)
    t_after_l1 = conv.get_token_estimate()
    # Manually remove the group to find post-removal token count
    conv_copy = Conversation(
        agent_name="test", model="test/x",
        system_prompt="S" * 200,
    )
    for m in conv.messages:
        conv_copy.messages.append(m)
    # Remove filler + assistant + both TRs to simulate
    # Actually just set a budget that forces the group out
    budget = t_after_l1 - 50  # tight enough to force trimming
    conv_copy2 = Conversation(
        agent_name="test", model="test/x",
        system_prompt="S" * 200,
    )
    # Reconstruct fresh
    conv_copy2.add_user_message("u1" + " x" * 100)
    conv_copy2.add_assistant_message("a1" + " x" * 100, [])
    conv_copy2.add_user_message("filler" + " x" * 100)
    conv_copy2.add_assistant_message("plan", [
        ToolCall(call_id="c1", tool_name="x", arguments={}),
        ToolCall(call_id="c2", tool_name="y", arguments={}),
    ])
    conv_copy2.add_tool_result("c1", "result1 " + "X " * 400)
    conv_copy2.add_tool_result("c2", "result2 " + "X " * 400)
    conv_copy2.add_user_message("u2" + " x" * 100)
    conv_copy2.add_assistant_message("a2" + " x" * 100, [])
    conv_copy2.add_user_message("u3" + " x" * 100)
    conv_copy2.add_assistant_message("a3" + " x" * 100, [])

    s2 = DefaultContextStrategy()
    s2.compact(conv_copy2, token_budget=budget, keep_first=2)

    valid_ids: set[str] = set()
    for m in conv_copy2.messages:
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            valid_ids.update(tc.call_id for tc in m.tool_calls)
    for m in conv_copy2.messages:
        if m.role == MessageRole.TOOL_RESULT:
            assert m.tool_call_id in valid_ids, (
                f"orphan TR in TR-first path: {m.tool_call_id}"
            )
```

---

## 9. ARCHITECTURE.md Updates Required

No ARCHITECTURE.md changes needed. The fix is internal to `DefaultContextStrategy.compact()` and does not change any interfaces, data models, or handler contracts. The CB-6 invariant is being enforced more correctly, not redefined.

---

## Self-Audit (Rule 9)

### 1. Does every code sample work against the current codebase?

**Verified:**
- `MessageRole.ASSISTANT`, `MessageRole.TOOL_RESULT` — confirmed at `models/conversation.py:72-76`
- `msg.tool_calls` — confirmed: `list[ToolCall]` field on `Message`, default `[]` (`conversation.py:119`)
- `msg.tool_call_id` — confirmed: `str | None` field on `Message` (`conversation.py:120`)
- `tc.call_id` — confirmed: `str` field on `ToolCall` (`conversation.py:92`)
- `conv.messages` — confirmed: `list[Message]` on `Conversation` (`conversation.py:140`)
- `conv._token_estimate_cache` — confirmed: `tuple | None` on `Conversation` (`conversation.py:163`)
- `_select_prune_candidate()` return values — confirmed: returns `int | None`, the int is an index into `conv.messages`
- `tail_preserve = 4` — confirmed at `context_strategy.py` line before the trim loop
- `keep_first` default `2` — confirmed in `compact()` signature

### 2. Did I catch all exception types?

No new function calls are introduced. The code uses `set()`, `list.pop()`, `list comprehension`, and attribute access — all of which are already used in the surrounding code. No new exceptions possible.

### 3. Did I verify key structures?

- `msg.tool_calls` is `list[ToolCall]` where `ToolCall` has `.call_id: str` — verified by reading `models/conversation.py:90-100`
- `msg.tool_call_id` is `str | None` — verified at `conversation.py:120`
- `conv.messages` is a `list[Message]` supporting `pop()`, `append()`, slice assignment `[:]` — verified
- `_select_prune_candidate` returns an index into `conv.messages`, not a message object — verified by reading the method

### 4. Did I trace the data flow end-to-end?

- **Trim loop entry:** `_select_prune_candidate` returns `idx` → `msg = conv.messages[idx]`
- **ASSISTANT branch:** `msg.role == ASSISTANT and msg.tool_calls` → build `call_ids` set → while-loop pops consecutive TRs at `idx+1` → check tail zone → pop assistant at `idx`
- **TOOL_RESULT branch:** `msg.role == TOOL_RESULT` → pop at `idx` → check `idx-1` for parent → pop parent → while-loop pops sibling TRs
- **Post-trim sweep:** build `valid_call_ids` from all surviving ASSISTANT-with-tool_calls → list comprehension filters orphans
- **Summary injection:** operates on cleaned `conv.messages`
- **`to_api_messages()`:** serializes cleaned messages — no orphans in output

### 5. Would an implementer following this spec produce working code?

Yes. The code samples are traced against actual source, signatures match, and the deterministic reproducer provides a concrete verification target (budget=1518 → 2 orphans before fix, 0 after).

---

## Completion Verification (Rule 10)

**Note:** This is a spec, not an implementation. Rule 10 checks 1-3 apply to the spec-writing task; check 4 is a declaration of spec completeness.

- [x] **Scope checklist** — all three changes described: ASSISTANT branch, TOOL_RESULT branch, post-trim sweep
- [x] **Test suite** — three test methods provided with exact assertions; reproducer budget verified
- [x] **Pattern sweep** — `grep -n "pop(idx + 1)" agent/context_strategy.py` shows the pattern at line 201 — this is the line being replaced by the while-loop
- [x] **Declaration** — spec is complete and ready for implementation
