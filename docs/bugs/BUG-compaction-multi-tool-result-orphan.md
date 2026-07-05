# BUG: Compaction Orphans Tool Results When Assistant Has Multiple Tool Calls

**Date:** 2026-07-04
**File:** `agent/context_strategy.py` (`DefaultContextStrategy.compact()`, ~line 175-200)
**Severity:** CRITICAL (production failure: 24+ hours)
**Discovered while:** verifying the SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY implementation
**Implements:** the orphaned-tool-result class of bugs; *not* the same as the prior stale-messages fix

## Symptom

Sending any message to the Coder agent fails with:

```
HTTPError: HTTP Error 400: Bad Request
"invalid tool message at messages[4]: tool call id 'call_function_bng8mesvwhyp_2'
 not found in previous tool calls"
```

The error returns at Cohere (via OpenRouter) for `cohere/north-mini-code:free`. It also affects any provider that validates tool-call/tool-result pairing (OpenAI, Anthropic, Cohere all enforce this).

The HTTPError body — now correctly logged by the previous fix — is:

```json
{"error":{"message":"Provider returned error","code":400,
  "metadata":{"raw":"{\"message\":\"invalid tool message at messages[4]:
  tool call id 'call_function_bng8mesvwhyp_2' not found in previous tool calls\"}",
  "provider_name":"Cohere"}}}
```

## Root cause

`DefaultContextStrategy.compact()` (the trim-loop branch at line 175-200) implements a **pairwise CB-6 invariant**: when removing an `ASSISTANT-with-tool-calls` message, it only removes the **immediately following** `TOOL_RESULT` (line ~187):

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
```

When an assistant issues **multiple tool calls** in one response (e.g., `_1, _2, _3`), the API requires **all three** matching `tool` results to immediately follow. But the runtime conversation stores them as **three separate `TOOL_RESULT` messages**, one per tool call. The trim loop only pops the **first** of those (`_1`), leaving `_2` and `_3` as orphans whose parent `ASSISTANT` is now gone.

After the trim loop exits (because token budget is met), those orphans remain in `conv.messages`. They get serialized by `to_api_messages()` and sent to the API, which rejects them with 400.

## Reproduction (verified)

Loaded the real `special:coder.json` (1913 messages) and ran `compact()` with budget=209600 (80% of Cohere's 262K context):

```
BEFORE compact, messages[3..6]:
  [3] assistant tcs=['call_function_bng8mesvwhyp_1',
                     'call_function_bng8mesvwhyp_2',
                     'call_function_bng8mesvwhyp_3']
  [4] tool tcid='call_function_bng8mesvwhyp_1'
  [5] tool tcid='call_function_bng8mesvwhyp_2'
  [6] tool tcid='call_function_bng8mesvwhyp_3'

AFTER compact, messages[3..6]:
  [3] tool tcid='call_function_bng8mesvwhyp_2'      ← ORPHAN
  [4] tool tcid='call_function_bng8mesvwhyp_3'      ← ORPHAN
  [5] tool tcid='call_function_321xa7jitcgi_2'      ← ORPHAN
  [6] tool tcid='call_function_321xa7jitcgi_3'      ← ORPHAN
```

**50 orphans total** in the post-compact API payload. The first orphan (`call_function_bng8mesvwhyp_2`) lands at API index 4, matching the error.

The trim loop's `_select_prune_candidate()` correctly returns the ASSISTANT-with-tcs index, and the loop correctly pops that assistant + its first TR. But the **second and third TRs** of the same assistant's tool-call batch are never cleaned up.

## Why my prior analysis was wrong

The previous SPEC assumed the bug was "stale `messages` variable captured before compaction" — that fix (moving `conv.to_api_messages()` after `compact()`) is correct and necessary, but it does not address this compaction-level orphan. The same conversation that would have produced a context-overflow 400 before now produces a malformed-tool-sequence 400 after, because the conversation grew large enough to trigger compaction but compaction itself corrupts the wire payload.

The reproducer in `/tmp/repro/repro_real.py` (this session) loads the actual coder conversation and demonstrates the bug deterministically.

## Fix

Modify `compact()` in `agent/context_strategy.py` to handle multi-tool-call assistants. Replace the ASSISTANT-with-tcs branch (lines ~177-194) with code that pops **all** matching TRs:

```python
elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
    # CB-6: this assistant's tool_calls generate N matching TOOL_RESULTs.
    # Pop the assistant plus ALL of its TRs (not just the first).
    trimmable_end = len(conv.messages) - tail_preserve
    call_ids = {tc.call_id for tc in msg.tool_calls}
    # Pop TRs that follow immediately, all of them, as long as they're
    # in the trimmable region and match this assistant's tool_calls.
    while (
        idx + 1 < len(conv.messages)
        and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
        and (idx + 1) < trimmable_end
        and conv.messages[idx + 1].tool_call_id in call_ids
    ):
        conv.messages.pop(idx + 1)
    # If any TRs are in tail_preserve or don't match, bail out:
    # popping the assistant alone would orphan them.
    next_msg = conv.messages[idx + 1] if idx + 1 < len(conv.messages) else None
    if (
        next_msg is not None
        and next_msg.role == MessageRole.TOOL_RESULT
        and next_msg.tool_call_id in call_ids
    ):
        # Adjacent TR is in tail or unmatched — skip this candidate.
        continue
    conv.messages.pop(idx)
```

Additionally, add a **post-trim orphan sweep** before summary injection, to clean up any orphans the trim loop leaves behind (e.g., when budget is met mid-loop):

```python
# Post-trim orphan sweep — defensively remove any TOOL_RESULT whose
# parent ASSISTANT-with-tool-calls was popped earlier.
def _remove_orphan_tool_results(conv):
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
_remove_orphan_tool_results(conv)
```

## Verification

Add a test in `tests/test_context_strategy.py`:

```python
def test_compact_does_not_orphan_remaining_tool_results():
    """BUG: when an assistant has multiple tool_calls, compact() must
    remove ALL matching TRs, not just the first."""
    conv = Conversation(agent_name="Coder", system_prompt="S" * 50)
    conv.add_user_message("first")
    conv.add_assistant_message("hello")
    # Big trimmable middle
    for i in range(10):
        conv.add_user_message(f"bulk {i}")
        conv.add_assistant_message(f"a {i}")
    # Multi-tool-call assistant + 3 TRs
    conv.add_assistant_message("plan", [
        ToolCall(call_id="c1", tool_name="x", arguments={}),
        ToolCall(call_id="c2", tool_name="y", arguments={}),
        ToolCall(call_id="c3", tool_name="z", arguments={}),
    ])
    conv.add_tool_result("c1", "out1")
    conv.add_tool_result("c2", "out2")
    conv.add_tool_result("c3", "out3")
    conv.add_user_message("final")
    DefaultContextStrategy().compact(conv, token_budget=100)
    # Verify NO orphan TRs remain
    valid_ids = set()
    for m in conv.messages:
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            valid_ids.update(tc.call_id for tc in m.tool_calls)
    for m in conv.messages:
        if m.role == MessageRole.TOOL_RESULT:
            assert m.tool_call_id in valid_ids, f"orphan TR: {m.tool_call_id}"
```

## Files NOT changed

- `agent/runtime.py` — already correct (Bug #1 + #2 fixes from prior spec).
- `models/conversation.py` — already correct (CB-6 invariant at serialization).
- `agent/runtime.py:_call_llm` — already correct (stuck_prefix injection is role='user', doesn't break CB-6).

## Pattern tag

`orphan-after-multi-tool-trim` — fits the existing `orphan-message-after-trim` pattern in the coder bug journal, with the multi-tool-call-specific failure mode.

## Why this was missed

The existing CB-6 test suite covers:
- Single-tool-call assistant + single TR (covered)
- TOOL_RESULT orphan when parent is in `keep_first` region (covered)
- Duplicate `tool_call_id` bounce in `_find_split_index` (covered)

It does **not** cover the multi-tool-call case where **all** TRs follow one assistant. The trim loop's `_select_prune_candidate` returns the assistant index, but the compact code pops only the first TR.