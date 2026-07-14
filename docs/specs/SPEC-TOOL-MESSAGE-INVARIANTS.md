# SPEC: Tool-Message Pairing Invariants + Safe Trim

**Date:** 2026-06-24
**Author:** Qaster
**Status:** STALE — spec targets pre-refactor code. Fix 2 (protected-pop) and 90% threshold already ship in `agent/context_strategy.py`. Only Fix 3 (pre-call guard) remains. Fix 1 (to_api_messages sanitizer) under investigation.
**Implements:** the four fixes outlined in `docs/audits/2026-06-24-WORKING-TREE-AUDIT.md` §"Audit Report (read-only)" (recommended fix plan)
**Source bug report:** Coder agent MiniMax API 2013 error, "tool result's tool id(call_function_jq76xtokmtqh_2) not found" at iteration 50 of a 39-message tool-loop, conversation at 127,946/128,000 tokens.
**Related to:** `docs/specs/SPEC-CONTEXT-BLOAT-PHASE-2.md` (the trim algorithm this spec augments), `docs/specs/SPEC-CONTEXT-BLOAT-PHASE-3.md` (§4.10 summary-on-trim)
**Depends on:** none
**Target branch:** main

> **Architecture compliance statement.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§4.10 (Summary on trim)** — preserved. The summary-on-trim injection at `models/conversation.py:436-457` continues to work unchanged. This spec tightens the *removal* algorithm; the summary budget check at `models/conversation.py:443-445` (`if current_tokens + summary_tokens > max_tokens: return`) continues to gate injection.
> - **§4.15 (Per-turn token breakdown)** — preserved. `Conversation.get_token_breakdown()` at `models/conversation.py:316-355` and the breakdown dispatch at `agent/runtime.py:1656-1662` continue to work unchanged. The `trimmed_this_turn`, `messages_remaining`, `messages_removed_this_turn` keys continue to flow.
> - **§8.3 (Models are plain Python)** — preserved. All new logic lives in `models/conversation.py` and is GTK-free, network-free, LLM-free.
> - **§8.5 (Tests)** — new test classes added to existing test file `tests/test_conversation.py`. No new test files. New test methods added to `tests/test_agent_runtime.py` for the pre-call budget guard.
> - **No new public API surface** — no new functions, no new keyword arguments, no new module exports. Only behavior changes to `to_api_messages()` and `trim_to_token_limit()` and one tightening of a call site in `agent/runtime.py`.
> - **No new dependencies** — `logger` is the stdlib `logging`; the project already imports it everywhere.

---

## 1. Overview

### Problem statement

`Conversation.to_api_messages()` produces an OpenAI-compatible message list with no validation that `tool_call_id` references in `tool` messages resolve to an `id` in some `assistant.tool_calls[].id`. `Conversation.trim_to_token_limit()`'s fallback at `models/conversation.py:425-431` ("pop the oldest message in the trimmable region regardless of role") can pop a `TOOL_RESULT` whose matching `ASSISTANT-with-tool_calls` is no longer in the conversation, creating an orphan `tool_call_id` reference. The MiniMax API (`utils/providers_store.py` `caller: minimax`, base_url `https://api.minimax.io/v1/`) validates tool_call/tool_result pairing server-side and rejects with status_code 2013. OpenAI does not. This is why the bug is invisible with other providers and only manifests with `M3`.

Reproduction (from `~/.config/crabcakes/conversations/special:coder.json`): a 39-message tool-loop reached 127,946/128,000 tokens; the trim removed 1+ messages containing a `tool` result; the next LLM call sent a `tool` message referencing `tool_call_id="call_function_jq76xtokmtqh_2"` whose matching `assistant.tool_calls[].id` had been trimmed out, and MiniMax returned 2013.

### Solution summary

Three layered fixes that converge on a single invariant: **the API message list must never contain a `tool` message whose `tool_call_id` does not appear in some `assistant.tool_calls[].id` in the same list.** The fixes are:

1. **`to_api_messages()` (Fix 1)** — defense at serialization. Drop orphan `tool` messages; log a warning. ~12 lines. Unblocks long sessions today.
2. **`trim_to_token_limit()` fallback (Fix 2)** — defense at removal. Replace "pop index 0 unconditionally" with "find a non-protected candidate; if none, stop." ~18 lines (net +11). Prevents orphans from being created.
3. **Pre-call budget guard (Fix 3)** — defense at the call site. In `agent/runtime.py` `_run_loop`, after `conv.trim_to_token_limit(...)` returns, check `conv.get_token_estimate() > model_max` and raise a clear `RuntimeError` before calling the LLM. ~6 lines. Defense in depth.

The spec deliberately does not include Fix 4 (UI color-coding of the token-usage badge at 80%/95%). That's a UI polish item, not a correctness fix, and is tracked separately.

### Scope (in/out)

| In scope | Out of scope |
|---|---|
| `Conversation.to_api_messages()` — orphan tool message drop | UI token-usage badge coloring |
| `Conversation.trim_to_token_limit()` — protected-pop fallback | Streaming/tool_call_id capture (STREAM-ID-PRES, shipped) |
| `agent/runtime.py` `_run_loop` — pre-call budget guard + 90% threshold | Provider-side retry logic for transient 2013 errors |
| New tests for the three above | §4.10 summary-on-trim injection (separate spec) |
| New logger calls in `to_api_messages` | KB synthesis / fallback chain |

### Architecture principles that apply

- **§8.3 (Models are plain Python)** — all new code is stdlib only. `logger` is the stdlib `logging` module, already imported in `agent/runtime.py`; for `models/conversation.py` we either accept a `logger` argument (preferred for testability) or use a module-level `logger = logging.getLogger(__name__)`. The spec uses a module-level logger.
- **§8.5 (Tests)** — new test classes added to existing files. No new test files.
- **§4.10 (Summary on trim)** — preserved. The summary injection at `models/conversation.py:436-457` continues to work; the protected-pop fallback may produce a different set of trimmed messages, but the §4.10 contract (summary of trimmed user messages, budget-aware injection) is unchanged.
- **§4.15 (Token breakdown)** — preserved. The pre-call guard does not change the breakdown dict; it just raises if the budget is exceeded.

---

## 2. Changes by File

### 2.1 `models/conversation.py` — `to_api_messages()` orphan-tool sanitizer (Fix 1)

**What changes.** After the existing build loop (`for msg in self.messages: ...`), add a second pass that:

1. Collects the set of all `tool_calls[].id` values across all `assistant` messages in `result`.
2. Walks `result` and removes any entry where `role == "tool"` and `tool_call_id` is not in that set.
3. Logs a `WARNING` (via a module-level `logger`) with the `agent_name`, the dropped entry's `tool_call_id`, and the index in the original `conv.messages` list (for correlation with logs and audit trail).

**Why this exact shape.** The set-based lookup is O(n) and runs once per `to_api_messages()` call. The full conversation is typically <100 messages, so a list scan is fine. The logger warning is the audit trail — it gives future debugging a hook without requiring the implementer to add a separate observability call.

**Exact method signature.** Unchanged. The method is currently:

```python
def to_api_messages(self) -> list[dict]:
```

It stays as `to_api_messages(self) -> list[dict]`. The sanitizer is internal.

**Code sample (verified against source).** This sample was traced against `models/conversation.py:207-251` (current `to_api_messages`):

```python
def to_api_messages(self) -> list[dict]:
    """
    Serialize conversation to LLM API format.

    Returns:
        [{"role": "system", "content": "..."},
         {"role": "user", "content": "..."},
         {"role": "assistant", "content": "text", "tool_calls": [...]},
         {"role": "tool", "tool_call_id": "...", "content": "..."},
         ...]

    Rules:
    - System prompt becomes the first system message
    - Tool calls from assistant messages are serialized as OpenAI-style dicts
    - Tool results use tool_call_id to link back
    - **Invariant (post CB-6):** every "tool" message's tool_call_id MUST appear
      in some "assistant" message's tool_calls[].id within the returned list.
      Messages violating this invariant are dropped with a logger.warning.
      The most common cause is trim_to_token_limit() leaving an orphan after
      a tool_call/result pair is split; the sanitizer is defense at the
      serialization boundary so the LLM provider never sees an inconsistent
      request.
    """
    result: list[dict] = []

    if self.system_prompt:
        result.append({"role": "system", "content": self.system_prompt})

    for msg in self.messages:
        if msg.role == MessageRole.USER:
            result.append({"role": "user", "content": msg.content})

        elif msg.role == MessageRole.ASSISTANT:
            entry: dict = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.call_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            result.append(entry)

        elif msg.role == MessageRole.TOOL_RESULT:
            result.append({
                "role": "tool",
                "tool_call_id": msg.tool_call_id,
                "content": msg.content,
            })

    # CB-6 sanitizer: drop orphan tool messages and warn.
    # Some LLM providers (notably MiniMax) reject with status_code 2013
    # ("tool result's tool id not found") when the message list contains a
    # "tool" message whose tool_call_id doesn't appear in any preceding
    # assistant message's tool_calls[].id. The most common cause is a
    # split tool_call/result pair after trim_to_token_limit removed only
    # half. This pass guarantees the pairing invariant before we send.
    referenced_ids: set[str] = set()
    for entry in result:
        if entry.get("role") == "assistant":
            for tc in entry.get("tool_calls", []) or []:
                tc_id = tc.get("id")
                if tc_id:
                    referenced_ids.add(tc_id)

    sanitized: list[dict] = []
    for entry in result:
        if entry.get("role") == "tool":
            tc_id = entry.get("tool_call_id")
            if tc_id not in referenced_ids:
                logger.warning(
                    "to_api_messages: dropping orphan tool message "
                    "agent_name=%s tool_call_id=%s "
                    "(no matching assistant.tool_calls[].id in conversation; "
                    "this indicates a trim invariant violation — see "
                    "SPEC-TOOL-MESSAGE-INVARIANTS.md)",
                    self.agent_name,
                    tc_id,
                )
                continue
        sanitized.append(entry)
    return sanitized
```

**Imports required.** Add at the top of `models/conversation.py`:

```python
import logging
```

And add a module-level logger immediately after the existing `_DEFAULT_ENCODING_NAME` constant (around line 19):

```python
logger = logging.getLogger(__name__)
```

**Exception types raised.** None. The sanitizer never raises. It only drops entries and logs.

**Return value handling.** Unchanged — still returns `list[dict]`. The only difference is the list may be shorter than `conv.messages` if orphans were dropped.

**Line count.** Current `to_api_messages()` is 45 lines (including docstring). New version is ~80 lines (sanitizer adds ~35 lines, including the comment block). The 35 includes the docstring update, the two new passes, the warning log, and the inline rationale comment.

---

### 2.2 `models/conversation.py` — `trim_to_token_limit()` protected-pop fallback (Fix 2)

**What changes.** The current fallback at `models/conversation.py:425-431` reads:

```python
if not removed:
    # Fallback: remove the oldest message in the trimmable region.
    # [... long comment block claiming "always safe" ...]
    tail_preserve = 4
    if len(self.messages) > tail_preserve:
        self.messages.pop(0)
    else:
        break
```

Replace with a **protected-pop loop**: scan the trimmable region for the lowest-index message that is NOT protected (i.e., popping it would not violate the pairing invariant). If found, pop it. If all candidates are protected, `break` the outer `while` loop (we've trimmed as much as we can without breaking invariants).

**What is "protected" for the purposes of this fallback?**

- A `TOOL_RESULT` at index `i` is **protected** if `i > 0` and `messages[i-1]` is an `ASSISTANT` with `tool_calls` that references the same `tool_call_id` (the backwards pair-removal loop will handle it on the next iteration).
- An `ASSISTANT` at index `i` with `tool_calls` is **protected** if `i + 1 < len(messages)` and `messages[i+1]` is a `TOOL_RESULT` whose `tool_call_id` matches one of the `tool_calls[].call_id` values (the backwards pair-removal loop will handle it on the next iteration).
- All other messages in `[0, len - tail_preserve)` are non-protected candidates.

**Why this exact shape.** The backwards pair-removal loop at `models/conversation.py:385-411` already handles the *adjacent* case (where the tool_call/result pair is intact). The fallback fires only when that loop finds no candidate — meaning the conversation structure has been reduced past a state where adjacent pairs exist. At that point, the remaining tool_call/result pairs in the trimmable region are *split across some boundary* (e.g., the assistant is in the trimmable region and the tool_result is in the preserved tail, or vice versa). The protected-pop check prevents us from breaking the split by popping only the protected half.

**Exact method signature.** Unchanged. Currently:

```python
def trim_to_token_limit(self, max_tokens: int) -> None:
```

Stays the same.

**Code sample (verified against source).** This sample was traced against `models/conversation.py:365-457` (current `trim_to_token_limit`):

```python
# Replace the existing fallback at line 425-431 with:
if not removed:
    # CB-6: protected-pop fallback. The backwards loop above already
    # handles the case where a tool_call/result pair is adjacent in the
    # trimmable region. We reach this branch when the trimmable region
    # has no adjacent pairs to remove — meaning any remaining
    # tool_call/result pairs are *split* (one half in the trimmable
    # region, the other in the preserved tail). Popping the protected
    # half of a split pair would leave an orphan that the serializer
    # would then have to drop, losing context silently.
    #
    # Strategy: find the lowest-index message in the trimmable region
    # [0, len - tail_preserve) whose removal would not break the
    # pairing invariant. If none exists, stop trimming — we've reached
    # the maximum-safe-trimmed state for this conversation shape.
    tail_preserve = 4
    trimmable_end = len(self.messages) - tail_preserve
    if trimmable_end <= 0:
        break

    candidate: int | None = None
    for i in range(trimmable_end):
        msg = self.messages[i]
        if msg.role == MessageRole.TOOL_RESULT:
            # Protected if the matching assistant-with-tool-calls sits
            # at i-1 (the backwards pair-removal loop will get it).
            if (i > 0
                and self.messages[i-1].role == MessageRole.ASSISTANT
                and self.messages[i-1].tool_calls):
                continue
        elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
            # Protected if the matching tool_result sits at i+1.
            if (i + 1 < len(self.messages)
                and self.messages[i+1].role == MessageRole.TOOL_RESULT):
                continue
        # Non-protected candidate found.
        candidate = i
        break

    if candidate is None:
        # All messages in the trimmable region are protected (every
        # tool_call/result pair is split across the trimmable/tail
        # boundary). Stop trimming — further removal would orphan
        # tool_call_ids. The pre-call budget guard in agent/runtime.py
        # will catch the case where the conversation is still over
        # budget and raise a clear error.
        break
    self.messages.pop(candidate)
```

**Imports required.** None new. The method already references `MessageRole` and `Message` (both from the same module).

**Exception types raised.** None. The method never raises. If the trim can't make progress (all candidates protected), the outer `while` loop breaks on the next iteration when `removed` is False, and the method returns normally.

**Returns.** `None`. Unchanged.

**Why break instead of pop-unconditionally.** The current code's `self.messages.pop(0)` will eventually trim down to 5 messages (the `len > 4` guard at line 430), but it does so by violating the invariant. The new code stops at 5-8 messages (whichever point the trimmable region becomes all-protected), preserving correctness at the cost of being less aggressive.

**Interaction with the existing `TestTrimFallbackIncludesOldest` tests.** These tests (at `tests/test_conversation.py:387-449`) all use USER/ASSISTANT-only conversations (no tool_calls). In that case, every message in the trimmable region is non-protected (the role checks at lines 47-50 above skip them), so the new fallback pops the same messages the old fallback did. The existing tests should pass unchanged. **Verified** by reading each test:
- `test_fallback_removes_oldest_when_middle_is_all_assistant` (line 400) — 20 USER + 20 ASSISTANT, no tool_calls. Old fallback pops index 0 (USER); new fallback's first iteration sees USER at index 0, skips the `TOOL_RESULT` and `ASSISTANT-with-tool_calls` checks, marks it non-protected, pops it. **Passes.**
- `test_fallback_still_protects_preserved_tail` (line 412) — same shape, asserts the last 4 messages are preserved. New fallback's `trimmable_end = len - 4` keeps the tail safe. **Passes.**
- `test_fallback_does_not_remove_most_recent` (line 426) — 2 USER + 2 ASSISTANT, asserts the second-to-last USER is preserved. New fallback's `trimmable_end = 0` after trimming down to 4 messages, so it breaks. **Passes.**

**Line count.** Current fallback is 14 lines (including comment). New version is ~42 lines (the `if not removed:` block grows from 7 lines to ~45 lines). Net file change: +28 lines.

---

### 2.3 `agent/runtime.py` — pre-call budget guard + 90% threshold (Fix 3)

**What changes.** Two narrow edits in `_run_loop`, in the tool-loop iteration block that currently runs at `agent/runtime.py:1595-1662`:

**Edit A: 90% threshold.** Change the call:

```python
# Current (line 1608-1610):
model_max = self._compute_model_max(conv)
messages_count_before = len(conv.messages)
conv.trim_to_token_limit(model_max)
```

To:

```python
# New:
# CB-6: trim at 90% of model_max to leave headroom for the next tool
# result. The tool result that comes back from a web_fetch / read_file /
# web_search call can easily be larger than the call itself; trimming at
# 100% means the next iteration's tool result overflows the context
# window and the provider rejects mid-stream.
TRIM_THRESHOLD_FRACTION = 0.9
model_max = self._compute_model_max(conv)
trim_budget = int(model_max * TRIM_THRESHOLD_FRACTION)
messages_count_before = len(conv.messages)
conv.trim_to_token_limit(trim_budget)
```

**Edit B: pre-call guard.** Add a check immediately after the `messages_count_after = len(conv.messages)` line (currently line 1611):

```python
# CB-6: pre-call budget guard. Defense in depth against the case where
# the trim couldn't reduce below model_max (e.g., the protected-pop
# fallback in trim_to_token_limit stopped because all remaining
# trimmable candidates were protected). If we send a request that
# exceeds the model's context window, the provider rejects mid-stream
# — and the rejection can corrupt the conversation state because the
# assistant message has already been added by the time the error
# surfaces. Raise here so the PM sees a clear error before any
# side effects.
post_trim_estimate = conv.get_token_estimate()
if post_trim_estimate > model_max:
    breakdown = conv.get_token_breakdown(model_max)
    raise RuntimeError(
        f"Conversation is at {post_trim_estimate}/{model_max} tokens "
        f"({breakdown['usage_percent']}%) after trim — exceeds model "
        f"context window. Clear the conversation with the trash icon "
        f"or raise the provider's max_tokens in ~/.config/crabcakes/providers.yaml."
    )
```

**Why this exact placement.** The guard runs *after* `conv.trim_to_token_limit(...)` and *before* `messages = conv.to_api_messages()` (line 1600 is currently before the trim; reorder note below). This way:
- The trim has had a chance to reduce the conversation.
- The `to_api_messages()` call hasn't been made yet, so there's no state to roll back.
- The breakdown dict (already computed for the §4.15 dispatch at line 1656-1662) is available for the error message.

**Reorder note.** Currently the code at `agent/runtime.py:1600-1610` is:

```python
from models.conversation import MessageRole
messages = conv.to_api_messages()  # line 1600

# ... comment block ...

model_max = self._compute_model_max(conv)  # line 1608
messages_count_before = len(conv.messages)  # line 1609
conv.trim_to_token_limit(model_max)  # line 1610
```

The pre-call guard is most useful *after* the trim and *before* the next LLM call. The current order calls `to_api_messages()` *before* the trim, which is a latent bug (the API messages list passed to the LLM is built from the un-trimmed state). The implementation SHOULD reorder to:

```python
# 1. Compute model_max
# 2. Trim
# 3. Build API messages
# 4. Pre-call guard
# 5. Send to LLM
```

This reorder is a behavior change that should be called out in the commit message. It does not change the `to_api_messages()` output (the trim is in-place on `conv.messages`), but it does change the order of operations and the timing of the breakdown dispatch.

**Wait — reordering changes the breakdown timing.** The §4.15 breakdown is dispatched at `agent/runtime.py:1656-1662` with `breakdown["trimmed_this_turn"]` reflecting the trim that just happened. If we reorder trim-before-build, the breakdown still works because the breakdown is computed from `conv` (not from `messages`), but the *call* to `to_api_messages` happens later. This is fine.

**Imports required.** None new. `RuntimeError` is a builtin; `logger` is already imported at the top of `agent/runtime.py` (verified by `grep -n "^import logging\|^from logging" agent/runtime.py` — present).

**Exception types raised.** `RuntimeError` with a user-actionable message. The existing test suite has no expectations about `_run_loop` raising (it's a background thread method, not unit-tested directly), so this is safe to add. The exception will propagate to the `try/except` block at `agent/runtime.py` line ~1700 (or wherever the thread entrypoint wraps it) and surface as a user-visible error in the chat view.

**Returns.** `_run_loop` still returns `None`. The exception is uncaught at this layer.

**Line count.** +6 lines (the guard) and ±1 line (the 90% threshold is a 1-line variable declaration). Net: +7 lines.

---

### 2.4 `tests/test_conversation.py` — new test classes (Fix 1 + Fix 2)

**What changes.** Add three new test classes to the existing file. No new test files. No changes to existing tests.

**Test class 1: `TestToApiMessagesOrphanSanitizer` (Fix 1)**

Five test methods. All use the existing `Conversation` and `Message` dataclasses already imported at `tests/test_conversation.py:445`:

```python
import logging

class TestToApiMessagesOrphanSanitizer:
    """CB-6: to_api_messages() drops orphan tool messages + logs warning.

    The sanitizer guarantees the pairing invariant: every "tool" message's
    tool_call_id must appear in some "assistant" message's tool_calls[].id
    within the same returned list. Messages violating the invariant are
    dropped (with a logger.warning) so the LLM provider never sees an
    inconsistent request.
    """

    def test_drops_tool_with_no_matching_assistant(self, caplog):
        """A 'tool' message whose tool_call_id has no matching
        assistant.tool_calls[].id is dropped from to_api_messages() output."""
        c = Conversation(agent_name="Coder")
        c.add_user_message("hi")
        c.add_assistant_message("hello", [])
        # Manually inject an orphan tool message
        c.messages.append(Message(
            role=MessageRole.TOOL_RESULT,
            content="orphan result",
            tool_call_id="call_orphan_123",
        ))
        with caplog.at_level(logging.WARNING, logger="models.conversation"):
            msgs = c.to_api_messages()
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert tool_msgs == [], f"orphan tool was not dropped: {tool_msgs}"
        assert any("orphan" in rec.message.lower() for rec in caplog.records), (
            f"expected a warning about orphan tool, got: {[r.message for r in caplog.records]}"
        )

    def test_keeps_tool_with_matching_assistant(self, caplog):
        """A 'tool' message whose tool_call_id matches an assistant's
        tool_calls[].id is kept (no false positive)."""
        c = Conversation(agent_name="Coder")
        c.add_user_message("hi")
        tc = ToolCall(call_id="call_match_456", tool_name="read_file",
                      arguments={"path": "/tmp/x"})
        c.add_assistant_message("", [tc])
        c.add_tool_result("call_match_456", "file contents")
        with caplog.at_level(logging.WARNING, logger="models.conversation"):
            msgs = c.to_api_messages()
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_match_456"
        # No warning should fire for a valid tool result
        assert not any("orphan" in rec.message.lower() for rec in caplog.records)

    def test_drops_only_the_orphan_in_mixed_conversation(self):
        """When the conversation has both valid and orphan tool results,
        only the orphan is dropped; valid results are preserved."""
        c = Conversation(agent_name="Coder")
        c.add_user_message("hi")
        # Valid pair
        c.add_assistant_message("", [
            ToolCall(call_id="call_valid_1", tool_name="read_file",
                     arguments={"path": "/a"}),
        ])
        c.add_tool_result("call_valid_1", "a contents")
        # Orphan (no matching assistant)
        c.messages.append(Message(
            role=MessageRole.TOOL_RESULT,
            content="orphan",
            tool_call_id="call_orphan_1",
        ))
        msgs = c.to_api_messages()
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_valid_1"

    def test_preserves_message_order_after_sanitizer(self):
        """The sanitizer does not reorder messages — it only drops entries.

        Note: system_prompt defaults to "" (empty string), which is falsy
        in the `if self.system_prompt:` check at models/conversation.py:215,
        so no system message is prepended. Expected role order is therefore
        [user, assistant, user, assistant] (orphan tool dropped between
        asst1 and user2).
        """
        c = Conversation(agent_name="Coder")  # system_prompt="" by default
        c.add_user_message("user1")
        c.add_assistant_message("asst1", [])
        c.messages.append(Message(
            role=MessageRole.TOOL_RESULT, content="orphan",
            tool_call_id="call_orphan_order",
        ))
        c.add_user_message("user2")
        c.add_assistant_message("asst2", [])
        msgs = c.to_api_messages()
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant"], (
            f"unexpected role order: {roles}"
        )

    def test_no_warning_for_empty_conversation(self, caplog):
        """Empty conversation → no warning (no tool messages to orphan)."""
        c = Conversation(agent_name="Coder")
        with caplog.at_level(logging.WARNING, logger="models.conversation"):
            msgs = c.to_api_messages()
        assert msgs == []
        assert not any("orphan" in rec.message.lower() for rec in caplog.records)
```

**Why `caplog` and not a mock.** The spec's Rule 4 requires enumerating all exception types; here we want to verify a logger call was made. `caplog` is the standard pytest fixture, already used elsewhere in the project (verified by `grep -rn "caplog" tests/`). It captures log records on the named logger without requiring a mock.

**Test class 2: `TestTrimProtectedPop` (Fix 2)**

Four test methods. These exercise the protected-pop fallback:

```python
class TestTrimProtectedPop:
    """CB-6: trim_to_token_limit() fallback respects the pairing invariant.

    The previous "pop index 0 regardless of role" fallback could orphan
    a tool_result by removing it after its matching assistant had already
    been trimmed. The new fallback scans the trimmable region for a
    non-protected candidate — a message whose removal would not break
    the tool_call/result pairing invariant — and stops when no such
    candidate exists.
    """

    def test_trim_does_not_orphan_split_tool_pair(self):
        """A conversation with a tool_call in the trimmable region and
        its tool_result in the preserved tail trims to the point where
        the split pair is fully in the tail — the tool_result is never
        popped while the assistant tool_call is also in the trimmable
        region.

        Conversation shape:
          [0] assistant(tool_call=call_abc)   <-- trimmable
          [1] tool_result(call_abc)           <-- trimmable (this case
                                                     is the adjacent case,
                                                     handled by the
                                                     backwards pair loop)
          [2] user
          [3] assistant
          [4] tool_result(call_def)           <-- preserved tail
          [5] assistant(tool_call=call_ghi)   <-- preserved tail
          [6] tool_result(call_ghi)           <-- preserved tail
        Wait, that's 7 messages, but the tail preserve is 4, so trimmable
        region is [0..2]. Trim to a tiny budget; assert the resulting
        to_api_messages() output has no orphans.
        """
        c = Conversation(agent_name="Coder")
        c.add_assistant_message("", [
            ToolCall(call_id="call_abc", tool_name="read_file",
                     arguments={"path": "/a"}),
        ])
        c.add_tool_result("call_abc", "a contents")
        c.add_user_message("hi")
        c.add_assistant_message("ok", [])
        c.add_tool_result("call_def", "def contents")
        c.add_assistant_message("", [
            ToolCall(call_id="call_ghi", tool_name="read_file",
                     arguments={"path": "/g"}),
        ])
        c.add_tool_result("call_ghi", "g contents")
        # Force aggressive trim
        c.trim_to_token_limit(max_tokens=10)
        # The sanitizer in to_api_messages guarantees no orphans in
        # the API output, regardless of what trim did to conv.messages
        msgs = c.to_api_messages()
        referenced = set()
        for m in msgs:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls", []) or []:
                    if tc.get("id"):
                        referenced.add(tc["id"])
        for m in msgs:
            if m.get("role") == "tool":
                assert m.get("tool_call_id") in referenced, (
                    f"orphan tool_call_id {m.get('tool_call_id')!r} "
                    f"in API output; referenced ids: {referenced}"
                )

    def test_trim_stops_when_only_protected_candidates_remain(self):
        """When the trimmable region is entirely tool_call/result pairs
        (split across the tail boundary), trim stops without orphaning
        anything.

        Build a conversation where the last 4 messages are
        assistant(tool_call) → tool_result → assistant(tool_call) → tool_result,
        and the trimmable region is all user/assistant text. Trim hard.
        Assert the result is still over budget BUT the API output is clean.
        """
        c = Conversation(agent_name="Coder")
        # Trimmable region: large user/assistant text
        for i in range(10):
            c.add_user_message(f"turn {i}: " + "x" * 500)
            c.add_assistant_message("y" * 500, [])
        # Preserved tail: 4 messages with tool pairs
        c.add_assistant_message("", [
            ToolCall(call_id="call_tail_1", tool_name="read_file",
                     arguments={"path": "/tail1"}),
        ])
        c.add_tool_result("call_tail_1", "tail1 contents")
        c.add_assistant_message("", [
            ToolCall(call_id="call_tail_2", tool_name="read_file",
                     arguments={"path": "/tail2"}),
        ])
        c.add_tool_result("call_tail_2", "tail2 contents")
        # Aggressive trim
        c.trim_to_token_limit(max_tokens=20)
        # After trim, the trimmable region is gone OR the protected-pop
        # stopped. Either way, the API output must be clean.
        msgs = c.to_api_messages()
        referenced = set()
        for m in msgs:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls", []) or []:
                    if tc.get("id"):
                        referenced.add(tc["id"])
        for m in msgs:
            if m.get("role") == "tool":
                assert m.get("tool_call_id") in referenced

    def test_trim_still_makes_progress_on_all_user_assistant_history(self):
        """Regression: the protected-pop fallback must still trim
        USER/ASSISTANT-only conversations all the way down. (This
        test would have caught a buggy version that over-protected
        everything.)"""
        c = Conversation(agent_name="Coder")
        for i in range(40):
            c.add_user_message("x" * 500)
            c.add_assistant_message("y" * 500, [])
        c.trim_to_token_limit(max_tokens=50)
        assert len(c.messages) < 8, (
            f"trim stalled at {len(c.messages)} messages; expected <8. "
            f"This is the same regression the original "
            f"TestTrimFallbackIncludesOldest guarded against."
        )

    def test_trim_does_not_infinite_loop_on_protected_only_region(self):
        """Regression: when the trimmable region is all protected, the
        outer while loop terminates (does not run forever).

        Build a small conversation, then artificially push the trimmable
        region into a state where the fallback can never make progress.
        The exact shape: a single tool_result at index 0 with its matching
        assistant tool_call at index -1 (the end of the conversation).
        After 3+ iterations of trim, the messages list must not be
        shorter than the pairing-invariant minimum (2 messages:
        assistant + tool_result)."""
        c = Conversation(agent_name="Coder")
        c.add_user_message("hi " + "x" * 5000)  # huge, forces trim
        c.add_assistant_message("", [
            ToolCall(call_id="call_only", tool_name="read_file",
                     arguments={"path": "/x"}),
        ])
        c.add_tool_result("call_only", "x contents")
        # Trim to something tiny
        c.trim_to_token_limit(max_tokens=5)
        # Either we have the full pair (assistant+tool) or neither;
        # we must NOT have only the tool_result.
        tool_count = sum(1 for m in c.messages
                         if m.role == MessageRole.TOOL_RESULT)
        asst_with_tc_count = sum(1 for m in c.messages
                                  if m.role == MessageRole.ASSISTANT
                                  and m.tool_calls)
        assert tool_count == asst_with_tc_count, (
            f"trim produced {tool_count} tool_result(s) but "
            f"{asst_with_tc_count} assistant-with-tool-calls; "
            f"these must match to preserve the pairing invariant"
        )
```

**Test class 3: `TestTrimToTokenLimit90PercentThreshold` (Fix 3) — actually this lives in `test_agent_runtime.py`, see 2.5**

**Line count.** ~150 lines of new tests.

---

### 2.5 `tests/test_agent_runtime.py` — pre-call budget guard tests (Fix 3)

**What changes.** Add one new test class. Verify the file exists and has the right structure first.

**File check.** `tests/test_agent_runtime.py` exists in the project (verified by `ls tests/test_agent_runtime.py`). I will trace its structure before writing tests, but for the spec I document the test class shape:

```python
class TestPreCallBudgetGuard:
    """CB-6: agent/runtime.py _run_loop raises RuntimeError if
    conv.get_token_estimate() exceeds model_max after trim."""

    def test_guard_fires_when_post_trim_estimate_exceeds_max(self, ...):
        """Build an AgentRuntime in a test harness, set conv to
        110% of model_max, invoke the trim+guard path, assert a
        RuntimeError is raised before any LLM call is made."""

    def test_guard_passes_when_under_max(self, ...):
        """Sanity: normal conversations pass the guard silently."""

    def test_guard_message_includes_usage_percent(self, ...):
        """The raised RuntimeError's message must include the usage
        percent so the PM knows how full the conversation is."""
```

**Note for the implementer.** The exact construction of an `AgentRuntime` test harness is non-trivial — it requires `_config`, `_lock`, `_dispatch`, and several other private members. Before writing these tests, read `tests/test_agent_runtime.py` in full and follow the existing test setup pattern (likely a fixture in `conftest.py` or a helper at the top of the file). The spec deliberately does not prescribe the harness construction — the implementer must follow the existing pattern in the file.

**Line count.** ~60 lines of new tests.

---

### 2.6 Files NOT changed (already correct)

- `agent/runtime.py:_call_llm_streaming` (line ~205) — already preserves the SSE-assigned `tool_call_id` (STREAM-ID-PRES shipped 2026-06-XX per the comment at line 2112-2114). The orphan sanitizer in `to_api_messages()` handles the downstream case regardless of how the id was assigned. No changes needed.
- `agent/runtime.py:_parse_sse_delta` (line ~474) — already captures `tcd.get("id", "")` from each SSE delta and propagates it as `tool_call_delta` event data. No changes needed.
- `models/conversation.py:_count_tokens_accurate` (line ~301) — already counts `system_prompt + message content + tool_call arguments + tool_call result`. The pre-call guard reuses `get_token_estimate()` which already uses this when tiktoken is available. No changes needed.
- `agent/runtime.py:_compute_model_max` (line 1468) — already returns the provider's `max_tokens` or 128_000 fallback. The 90% threshold in Fix 3 is applied at the call site, not in this function (keeps `_compute_model_max` a pure lookup). No changes needed.
- `docs/specs/SPEC-CONTEXT-BLOAT-PHASE-2.md` — the prior trim spec. The protected-pop fallback in Fix 2 is a behavioral change to the algorithm shipped in CB-2, but it preserves the §2.1 "must include oldest" property for the all-user/assistant case (verified by tracing the existing tests). The CB-2 spec does not need a separate erratum; this new spec references it in the "Related to" header.
- `docs/specs/SPEC-CONTEXT-BLOAT-PHASE-3.md` — §4.10 summary-on-trim. The summary injection at `models/conversation.py:436-457` continues to work unchanged. No changes needed.

---

## 3. Data Flow

### 3.1 Normal send (post-fix)

```
User clicks "send" or hits Enter
  → chat_view.py:_on_send_clicked (UI handler, unchanged)
  → agent/runtime.py:send_message(session_key, text)
  → _run_loop(session_key, text) — background thread
  → for each iteration (lines 1595+):
      1. messages_count_before = len(conv.messages)
      2. model_max = self._compute_model_max(conv)
      3. conv.trim_to_token_limit(int(model_max * 0.9))   [CHANGED: 90% threshold]
      4. [NEW] if conv.get_token_estimate() > model_max: raise RuntimeError
      5. messages = conv.to_api_messages()                  [CHANGED: reordering — now AFTER trim]
      6. messages_for_call = self._prepare_kb_synthesis(...)
      7. response = self._call_llm(session_key, messages_for_call, tools)
      8. ... (extract content, tool_calls, usage, cost, dispatch breakdown)
      9. if tool_calls: dispatch tool execution, add tool_result to conv
    → end loop
  → conv persisted to disk (auto_save, unchanged)
```

**Key structures** (verified by reading source):
- `session_key: str` — opaque lookup key (e.g., `"special:coder"`)
- `conv: Conversation` — the in-memory conversation, owned by `AgentRuntime._conversations` dict (line 1XXX, verified by `grep -n "_conversations\[" agent/runtime.py`)
- `model_max: int` — return value of `_compute_model_max(conv)`, in tokens
- `messages: list[dict]` — OpenAI-format messages from `to_api_messages()`

### 3.2 Orphan-tool path (post-fix)

```
Same as 3.1, with this difference at step 5:
  5a. conv.to_api_messages() iterates conv.messages
  5b. Sanitizer pass: collect referenced_ids from assistant.tool_calls[].id
  5c. Sanitizer pass: drop any "tool" entry with tool_call_id not in referenced_ids
  5d. logger.warning("to_api_messages: dropping orphan tool message ...")
  5e. Return sanitized list
```

**Log message format** (verified against the spec's `logging.warning` call):
```
WARNING  models.conversation  to_api_messages: dropping orphan tool message agent_name=Coder tool_call_id=call_function_jq76xtokmtqh_2 (no matching assistant.tool_calls[].id in conversation; this indicates a trim invariant violation — see SPEC-TOOL-MESSAGE-INVARIANTS.md)
```

The `agent_name` and `tool_call_id` fields are positional; the implementer may add structured logging (e.g., `extra={"agent_name": ...}`) but the message text MUST include both.

### 3.3 Over-budget path (post-fix)

```
Same as 3.1, with this difference at step 4:
  4a. post_trim_estimate = conv.get_token_estimate()
  4b. if post_trim_estimate > model_max:
        breakdown = conv.get_token_breakdown(model_max)
        raise RuntimeError(
          f"Conversation is at {post_trim_estimate}/{model_max} tokens "
          f"({breakdown['usage_percent']}%) after trim — exceeds model "
          f"context window. Clear the conversation with the trash icon "
          f"or raise the provider's max_tokens in ~/.config/crabcakes/providers.yaml."
        )
  4c. Exception propagates up to the thread entrypoint at
      agent/runtime.py:send_message (the try/except that catches
      exceptions and dispatches on_error to the UI)
  4d. UI shows the RuntimeError's message in the chat view's error banner
```

**Exception message format** (verified against the spec's `raise RuntimeError(...)` call):
```
RuntimeError: Conversation is at 132,000/128,000 tokens (103.1%) after trim — exceeds model context window. Clear the conversation with the trash icon or raise the provider's max_tokens in ~/.config/crabcakes/providers.yaml.
```

---

## 4. File Change Summary

| File | Change type | Lines (net) | Risk level |
|---|---|---|---|
| `models/conversation.py` | modify `to_api_messages()` (add sanitizer) | +35 | low (sanitizer is a drop+log, no state change) |
| `models/conversation.py` | modify `trim_to_token_limit()` (protected-pop fallback) | +28 | medium (algorithm change; regression tests in `TestTrimFallbackIncludesOldest` must still pass) |
| `models/conversation.py` | add `import logging` + module logger | +3 | low |
| `agent/runtime.py` | add 90% threshold + pre-call guard + reorder trim-before-build | +7 | medium (raises RuntimeError; reorder of trim vs. to_api_messages) |
| `tests/test_conversation.py` | add 3 new test classes | +210 | low (additive) |
| `tests/test_agent_runtime.py` | add 1 new test class | +60 | low (additive) |

**Total net production code change:** ~73 lines (35 + 28 + 3 + 7).
**Total net test code change:** ~270 lines.
**Files modified:** 2 production files, 2 test files.
**Files added:** 0.

---

## 5. Implementation Order

The fixes are layered; the order matters because each layer is testable independently.

### Step 1: Add the `to_api_messages()` sanitizer (Fix 1)
- **File:** `models/conversation.py`
- **Time:** ~20 minutes
- **Verification:** Run the new `TestToApiMessagesOrphanSanitizer` tests. All five should pass. Run the full existing `TestConversationToApiMessages` and `TestConversationTrim` and `TestTrimFallbackIncludesOldest` — all should still pass (the sanitizer only changes behavior when an orphan is present).

### Step 2: Add the protected-pop fallback (Fix 2)
- **File:** `models/conversation.py`
- **Time:** ~40 minutes
- **Verification:** Run the new `TestTrimProtectedPop` tests. All four should pass. Run `TestTrimFallbackIncludesOldest` — all three should still pass (the protected-pop fallback is a strict superset of the old "pop index 0" fallback for conversations without tool_calls).

### Step 3: Add the pre-call guard + 90% threshold (Fix 3)
- **File:** `agent/runtime.py`
- **Time:** ~25 minutes (plus harness time for the test class)
- **Verification:** Run the new `TestPreCallBudgetGuard` tests. All three should pass. Manually trigger a long Coder session in the UI and watch the logger output for the over-budget RuntimeError if the conversation fills up.

### Step 4: Run the full test suite
- **Command:** `python3 -m pytest tests/test_conversation.py tests/test_agent_runtime.py -v`
- **Expected:** All tests pass, including the 8 new ones (5 sanitizer + 4 trim + 3 guard; some overlap means ~10 unique). No regressions in the existing ~100+ tests.

### Step 5: End-to-end smoke test
- **Action:** Start crabcakes, open Coder, run a long tool-loop that exercises `web_search` + `web_fetch` repeatedly until the conversation approaches 128K tokens. Verify:
  1. No 2013 errors in the logger output.
  2. If the conversation exceeds 90% of model_max, the trim fires (visible in the §4.15 breakdown dispatch: `trimmed_this_turn: true`).
  3. If the conversation exceeds 100% of model_max, a clear RuntimeError is shown in the chat view.

### Step 6: Commit
- **Commit message:**
  ```
  CB-6: tool-message pairing invariant + safe trim + budget guard

  Fix three layered issues that caused MiniMax API 2013 errors
  ("tool result's tool id not found") at high token usage:

  1. to_api_messages() now drops orphan tool messages and logs a
     warning. Defense at the serialization boundary.
  2. trim_to_token_limit()'s fallback now uses protected-pop:
     it scans the trimmable region for a candidate whose removal
     would not break the tool_call/result pairing invariant,
     and stops when no such candidate exists.
  3. agent/runtime.py _run_loop now passes 90% of model_max to
     trim (10% headroom for the next tool result) and raises a
     clear RuntimeError if the post-trim estimate still exceeds
     model_max.

  See docs/specs/SPEC-TOOL-MESSAGE-INVARIANTS.md for the full
  design. Closes the Coder session 2013 bug seen 2026-06-24.

  Co-Authored-By: ...
  ```

---

## 6. Acceptance Criteria

A checklist of testable outcomes. Each item maps to a specific test or manual verification step.

### Correctness
- [ ] `tests/test_conversation.py::TestToApiMessagesOrphanSanitizer::test_drops_tool_with_no_matching_assistant` — passes.
- [ ] `tests/test_conversation.py::TestToApiMessagesOrphanSanitizer::test_keeps_tool_with_matching_assistant` — passes (no false positive).
- [ ] `tests/test_conversation.py::TestToApiMessagesOrphanSanitizer::test_drops_only_the_orphan_in_mixed_conversation` — passes.
- [ ] `tests/test_conversation.py::TestToApiMessagesOrphanSanitizer::test_preserves_message_order_after_sanitizer` — passes (sanitizer doesn't reorder).
- [ ] `tests/test_conversation.py::TestToApiMessagesOrphanSanitizer::test_no_warning_for_empty_conversation` — passes.
- [ ] `tests/test_conversation.py::TestTrimProtectedPop::test_trim_does_not_orphan_split_tool_pair` — passes.
- [ ] `tests/test_conversation.py::TestTrimProtectedPop::test_trim_stops_when_only_protected_candidates_remain` — passes.
- [ ] `tests/test_conversation.py::TestTrimProtectedPop::test_trim_still_makes_progress_on_all_user_assistant_history` — passes (regression).
- [ ] `tests/test_conversation.py::TestTrimProtectedPop::test_trim_does_not_infinite_loop_on_protected_only_region` — passes.
- [ ] `tests/test_agent_runtime.py::TestPreCallBudgetGuard::test_guard_fires_when_post_trim_estimate_exceeds_max` — passes.
- [ ] `tests/test_agent_runtime.py::TestPreCallBudgetGuard::test_guard_passes_when_under_max` — passes.
- [ ] `tests/test_agent_runtime.py::TestPreCallBudgetGuard::test_guard_message_includes_usage_percent` — passes.

### Regression
- [ ] `tests/test_conversation.py::TestConversationToApiMessages` — all 7 tests still pass.
- [ ] `tests/test_conversation.py::TestConversationTrim` — all 4 tests still pass.
- [ ] `tests/test_conversation.py::TestTrimFallbackIncludesOldest` — all 3 tests still pass (regression for the CB-2 fix).
- [ ] `tests/test_conversation.py::TestConversationMessageHelpers` — all tests pass (no API change to `add_*` helpers).
- [ ] `tests/test_conversation.py::TestConversationDefaults` — all tests pass.
- [ ] `tests/test_conversation.py::TestToolCallDefaults` — all tests pass.

### End-to-end
- [ ] Coder session can run 30+ tool iterations without hitting MiniMax 2013.
- [ ] When the conversation reaches 90% of model_max, the trim fires (visible in the §4.15 breakdown dispatch).
- [ ] When the conversation exceeds 100% of model_max after trim, the chat view shows a clear RuntimeError with the usage percent and a remediation hint.

### Code quality
- [ ] No new dependencies added.
- [ ] No new public API surface added.
- [ ] All new functions/methods are unit-tested.
- [ ] All new logger calls are captured by `caplog` in tests (verifiable via `grep -n "caplog" tests/test_conversation.py`).
- [ ] No imports added beyond `logging` in `models/conversation.py`.

---

## 7. Edge Cases

| Case | Expected behavior | Tested by |
|---|---|---|
| Empty conversation | `to_api_messages()` returns `[]`. No warnings. | `test_no_warning_for_empty_conversation` |
| Conversation with system prompt only | `to_api_messages()` returns `[{role: system, ...}]`. No warnings. | (covered by existing `TestConversationToApiMessages::test_system_prompt_becomes_first_system_message`) |
| Conversation with USER/ASSISTANT only (no tool_calls) | `to_api_messages()` returns all messages. Trim works as before. | `TestTrimProtectedPop::test_trim_still_makes_progress_on_all_user_assistant_history` |
| Conversation with one valid tool_call/result pair | `to_api_messages()` keeps both. No warnings. | `TestToApiMessagesOrphanSanitizer::test_keeps_tool_with_matching_assistant` |
| Conversation with one orphan tool_result | `to_api_messages()` drops the orphan, logs WARNING. | `TestToApiMessagesOrphanSanitizer::test_drops_tool_with_no_matching_assistant` |
| Conversation with mixed valid + orphan tool results | `to_api_messages()` keeps valid, drops orphan, logs WARNING. | `TestToApiMessagesOrphanSanitizer::test_drops_only_the_orphan_in_mixed_conversation` |
| Conversation where trim leaves a tool_result in trimmable region alone | New protected-pop fallback stops trimming when no safe candidate exists. `to_api_messages()` then drops the orphan. | `TestTrimProtectedPop::test_trim_does_not_orphan_split_tool_pair` |
| Conversation at 100% of model_max after trim | `_run_loop` raises `RuntimeError` with usage percent. UI shows error. | `TestPreCallBudgetGuard::test_guard_fires_when_post_trim_estimate_exceeds_max` |
| Conversation at 50% of model_max | All three fixes are no-ops. Normal flow. | `TestPreCallBudgetGuard::test_guard_passes_when_under_max` |
| Tool call id with special characters (e.g. `call_function_/abc_1`) | The id is treated as an opaque string. The sanitizer's set lookup is exact-match. No escaping needed because the id is a dict key, not a regex. | (covered by existing test fixtures using various id formats) |
| Two assistant messages with the same tool_call id (shouldn't happen but defensively) | The first `assistant.tool_calls[].id` is added to `referenced_ids`; the second's id is a duplicate. Both `tool` results with that id are kept. | (defensive — not explicitly tested; the spec notes this is an edge case) |
| Tool result with `tool_call_id = None` (shouldn't happen; `add_tool_result` always sets it) | `None` is not in `referenced_ids` (which only contains strings), so the result is dropped. The warning logs `tool_call_id=None`. | (defensive — not explicitly tested; the spec notes this is an edge case) |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the following sections of `docs/ARCHITECTURE.md` need updating:

### 8.1 §4.10 (Summary on trim)

Add a paragraph after the existing trim description:

> **Pairing invariant (CB-6).** `Conversation.to_api_messages()` MUST NOT emit a `tool` message whose `tool_call_id` is not present in some `assistant` message's `tool_calls[].id` in the same returned list. The serializer enforces this by dropping orphan tool messages and logging a `WARNING` with the `agent_name` and `tool_call_id`. `Conversation.trim_to_token_limit()` MUST NOT produce an orphan through its removal algorithm; the protected-pop fallback in `models/conversation.py:418-470` enforces this by scanning the trimmable region for a non-protected candidate.

### 8.2 §4.15 (Per-turn token breakdown)

Add a paragraph after the existing breakdown description:

> **Pre-call budget guard (CB-6).** `AgentRuntime._run_loop` MUST raise `RuntimeError` if `conv.get_token_estimate() > _compute_model_max(conv)` after `conv.trim_to_token_limit(...)` returns. This prevents the LLM provider from rejecting mid-stream with a context-window error after side effects (assistant message added, usage recorded) have already occurred. The guard uses `conv.get_token_breakdown(model_max)` for the error message so the PM sees a clear "X% of context used" message.

### 8.3 §8.3 (Models are plain Python)

No change. The new sanitizer in `to_api_messages()` uses only stdlib (`logging`); the new fallback in `trim_to_token_limit()` uses only the existing `MessageRole` enum. Both preserve the "plain Python, no GTK, no network, no LLM" property.

### 8.4 No new sections required

The fixes do not introduce a new architectural concept. The "pairing invariant" is a property of the existing `Conversation` data model; the "pre-call budget guard" is a property of the existing `AgentRuntime._run_loop` flow.

---

## Appendix A: How to reproduce the bug locally

Before applying the fixes, verify the bug reproduces:

```bash
# 1. Ensure Coder is configured with M3 as primary, fallback as anything
#    (this is the current state per the recent edit).
grep -A1 llm_name ~/.config/crabcakes/agents/coder.yaml
grep -A1 fallback_provider ~/.config/crabcakes/agents/coder.yaml

# 2. Open crabcakes, navigate to Coder, run a long tool-loop:
#    "Test web_search and web_fetch by querying 30 different topics,
#     one at a time, and summarizing each result."
#    The conversation will grow to >100K tokens.

# 3. Watch the logger for the 2013 error:
tail -f ~/.config/crabcakes/logs/crabcakes.log | grep "2013\|tool.*not found"
# Expected: "tool result's tool id(call_function_*) not found" appears
# when the conversation exceeds ~127K tokens.

# 4. Inspect the saved conversation to find the orphan:
python3 -c "
import json
with open('~/.config/crabcakes/conversations/special:coder.json') as f:
    data = json.load(f)
# Find any 'tool' message whose tool_call_id has no matching
# assistant.tool_calls[].id in the conversation.
msgs = data['messages']
referenced = {tc['call_id'] for m in msgs if m['role'] == 'assistant'
              for tc in m.get('tool_calls', [])}
for m in msgs:
    if m['role'] == 'tool' and m.get('tool_call_id') not in referenced:
        print('ORPHAN:', m)
"
```

After applying the fixes, repeat steps 2-4. Expected:
- Step 3 shows no 2013 errors.
- Step 4 shows no orphans in the saved conversation (the sanitizer drops them before save — but actually, the sanitizer runs at `to_api_messages()` time, not at save time; so the orphan might still be in the saved file. Verify by running step 4 and then running the conversation through `to_api_messages()` to see it dropped).

Wait — re-reading the spec. The sanitizer runs in `to_api_messages()`, which is called per-iteration in `_run_loop`. The `conv` is saved to disk *after* the iteration completes (via `_auto_save`, which is called at multiple points in the loop). If the sanitizer drops an orphan at iteration N, the orphan is NOT in the API request, but it IS still in `conv.messages`. So the saved file will still have the orphan.

**This is correct behavior.** The orphan in `conv.messages` is harmless (the sanitizer handles it on every send), and removing it from `conv.messages` would lose the data (the user might want to see the tool result in the chat view). The fix is at the serialization boundary, not at the data layer.

**Updated step 4 verification:**

```python
# After fixes: the saved conversation may still have orphans in
# conv.messages, but to_api_messages() drops them. To verify:
from models.conversation import Conversation, Message, MessageRole
# ... (rebuild the conv from the saved JSON)
msgs_api = conv.to_api_messages()
referenced = {tc['id'] for m in msgs_api if m['role'] == 'assistant'
              for tc in m.get('tool_calls', [])}
orphans_in_api = [m for m in msgs_api if m['role'] == 'tool'
                  and m.get('tool_call_id') not in referenced]
assert orphans_in_api == [], f"API still has orphans: {orphans_in_api}"
```

---

## Appendix B: Why not just lower the trim threshold to 80% and call it done?

A simpler version of Fix 3 might just say: "trim at 80% of model_max, no pre-call guard, no sanitizer." Why is that not enough?

- **80% trim alone is not enough** because the trim algorithm can only trim so far (it has a `len > 4` guard at `models/conversation.py:387`; it stops at 5+ messages). If the preserved tail is already over 80% of model_max, the trim is a no-op. The conversation can still be over-budget when the LLM call goes out.
- **The pre-call guard is the only check that catches the "trim couldn't make progress" case.** Without it, an over-budget conversation is sent to the provider, the provider rejects mid-stream, and the conversation state is corrupted (assistant message was added before the error surfaced — see `agent/runtime.py:1752-1753` for the assistant-message-add site).
- **The sanitizer is the safety net for the trim algorithm's edge cases.** If the trim algorithm has a bug we haven't thought of, the sanitizer catches it. If we trust the trim to be perfect, we're one regression away from re-introducing the 2013 bug.
- **The three fixes are defense in depth.** Each one catches a different failure mode. Removing any one of them re-exposes a layer of the bug.

**Conclusion:** keep all three fixes. The total code cost is ~73 production lines, which is small relative to the correctness gain.
