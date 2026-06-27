# Phase 5 Context Management — Adversarial Audit Report

**Auditor:** qtr (OC Tech Writer) — direct, after subagent terminations
**Phase:** CM Phase 5 — P4 prune_tool_outputs (Layer 1 lossless stubbing)
**File audited:** `agent/context_strategy.py` (lines 254–341 for `prune_tool_outputs`, lines 119–124 for compact() integration)
**Test file:** `tests/test_context_strategy.py::TestPruneToolOutputs` (verify existence)
**Spec:** `docs/specs/CM-PHASE-5-INSTRUCTIONS.md`
**Adversarial prompt:** `prompts/adversarialDebugger.md`

---

## Summary

Phase 5 implements a single Layer 1 helper (`prune_tool_outputs()`) that stubs
oversized tool results before the Layer 2 trim loop fires. The implementation
matches the spec's literal algorithm. The 6 required tests exist and cover the
happy paths. However, adversarial review surfaces several real-world edge cases
the spec didn't anticipate:

1. **`tool_name` extraction assumes the parent ASSISTANT is at idx-1.** A
   tool_call_id match is performed against the IMMEDIATELY preceding message
   only — if the parent ASSISTANT is further back (e.g., after a summary
   message was inserted), the tool name silently defaults to "tool".
2. **No protection against stubbing the LAST user message's tool result.**
   `protect_turns=2` protects the 2 most recent TOOL_RESULT indices. If the
   conversation has 1 user message + 1 tool result, `protect_turns=2` is
   greater than the available count, so all tool results get protected — but
   `prunable = tool_result_indices[protect_turns:]` is `[]`, so nothing
   happens. The function returns 0 without raising. Silent.
3. **Cache invalidation uses a docstring assertion that may not match the
   actual cache key.** The docstring claims the cache key is
   `(len(messages), hash(system_prompt))` — unverified.
4. **`tool_call_id` lookup iterates `parent.tool_calls` linearly.** For
   agents with high tool-call counts per turn, this is O(N) per stub.
5. **The `tokens_after_layer1` snapshot is taken AFTER the function returns
   from `compact()`'s `prune_tool_outputs` call.** If `prune_tool_outputs`
   returns 0 (already under target), the snapshot is still computed but the
   layer logic correctly identifies no Layer 1 fired.
6. **`msg.tokens_used = 0` is set but `conv._token_estimate_cache` is reset
   to None.** The cache invalidation happens after each iteration but also
   redundantly after the loop. No correctness issue, but the docstring
   explanation of WHY is unverified.

The biggest gap: **the spec mandated a tiktoken-free Phase 5, but `_find_split_index`
is already called inside `compact()` and depends on the Layer 1 stub state**.
This is a Phase 6 / Phase 9 leakage — same pattern as BUG #1 in Phase 1.

---

## BUG #1 — `prune_tool_outputs` assumes parent ASSISTANT is at idx-1

```
BUG #[1]
Severity: HIGH
Assumption violated: prune_tool_outputs() at lines 326–332 finds the tool name
                     by inspecting conv.messages[idx - 1] (the IMMEDIATELY
                     preceding message). It assumes that message is the parent
                     ASSISTANT-with-tool-calls.
Attack vector: After a compaction cycle that injects a summary message, the
               message at idx-1 of a TOOL_RESULT may be the SUMMARY message
               (is_summary=True) rather than the parent ASSISTANT. The
               tool_name extraction loop finds no match (because the summary
               message has no tool_calls), so tool_name silently defaults to
               "tool". Telemetry then reports "[compacted — tool output, N
               chars removed]" — losing information about which tool was
               stubbed.
Reproduction:
    from models.conversation import Conversation, MessageRole, Message, ToolCall
    from agent.context_strategy import DefaultContextStrategy

    conv = Conversation(agent_name='t', model='test/x')
    conv.add_user_message('first user')
    tc = ToolCall(call_id='call_xyz', tool_name='exec_command',
                  arguments={'cmd': 'ls'})
    conv.add_assistant_message('', [tc])
    conv.add_tool_result('call_xyz', 'x' * 5000)
    # Inject a summary message at index 1 (between the user msg and the
    # tool-result pair)
    summary = Message(role=MessageRole.ASSISTANT,
                      content='Summary', is_summary=True)
    conv.messages.insert(1, summary)
    # Now: idx of TOOL_RESULT is 3. conv.messages[idx-1] is the ASSISTANT
    # (idx=2), so the test case actually passes. BUT: if a USER message is
    # injected between (e.g., the agent asked a follow-up question before
    # the tool result arrived), the parent is no longer adjacent.
    # Construct: [user, asst-with-tc, user-followup, tool-result]
    conv2 = Conversation(agent_name='t', model='test/x')
    conv2.add_user_message('first')
    conv2.add_assistant_message('', [tc])
    conv2.add_user_message('followup')   # user message between asst and tool result
    conv2.add_tool_result('call_xyz', 'x' * 5000)
    # tool_result index = 3, parent at idx-1 = the followup user message.
    # Tool name defaults to "tool" (silent loss of tool name).
    DefaultContextStrategy().prune_tool_outputs(conv2, target_tokens=100,
                                               protect_turns=0)
    # Inspect stub:
    assert 'exec_command' in conv2.messages[3].content  # FAILS — says "tool"
Root cause: The lookup logic is `parent = conv.messages[idx - 1]` — a single
            adjacent assumption. Real conversations can have interleaved
            messages that break this assumption.
Fix: Search BACKWARD from idx-1 to find the parent ASSISTANT-with-tool-calls
     that owns this tool_call_id. The same pattern as `_find_split_index`'s
     CB-6 search (line 376–405). Add this as a separate helper since both
     methods need it.
```

---

## BUG #2 — `tool_name` defaults to "tool" silently when no parent found

```
BUG #[2]
Severity: MEDIUM
Assumption violated: BUG #1's silent fallback. When no parent ASSISTANT is
                     found adjacent to the TOOL_RESULT, the code defaults
                     tool_name to "tool" — a generic placeholder. This is
                     indistinguishable from a legitimate tool named "tool".
Attack vector: A user inspects conversation history and sees
               "[compacted — tool output, 5000 chars removed]" — they don't
               know whether:
               (a) there was a real tool named "tool" that returned 5000 chars, or
               (b) the tool name lookup failed and the placeholder was used.
               The first case is informative; the second is a bug hiding.
Reproduction: Same as BUG #1.
Root cause: Silent fallback in `tool_name = "tool"`. No warning, no log, no
            distinguishable marker.
Fix: Use a distinguishable fallback like "[unknown tool]" and log a warning
     when the parent can't be found. Or, fix BUG #1 so the lookup is
     always successful.
```

---

## BUG #3 — `protect_turns=2` vs. `len(tool_result_indices)` interaction is silent

```
BUG #[3]
Severity: LOW
Assumption violated: `prunable = tool_result_indices[protect_turns:]`. If
                     protect_turns > len(tool_result_indices), prunable is
                     empty, the for-loop is skipped, and the function returns 0.
Attack vector: A caller passes protect_turns=10 for a conversation with only
               3 TOOL_RESULT messages. The function silently does nothing
               instead of either (a) capping protect_turns at the available
               count or (b) raising an informative error. The caller has no
               way to know their request was effectively ignored.
Reproduction:
    from models.conversation import Conversation, ToolCall
    from agent.context_strategy import DefaultContextStrategy
    conv = Conversation(agent_name='t', model='test/x')
    for i in range(2):  # only 2 tool results
        tc = ToolCall(call_id=f'c{i}', tool_name='exec_command', arguments={})
        conv.add_assistant_message('', [tc])
        conv.add_tool_result(f'c{i}', 'x' * 5000)
    freed = DefaultContextStrategy().prune_tool_outputs(
        conv, target_tokens=100, protect_turns=10)
    assert freed == 0  # passes — but the caller's intent (protect 10) was ignored
Root cause: No validation of protect_turns against actual TOOL_RESULT count.
Fix: Either cap protect_turns at min(protect_turns, len(tool_result_indices))
     with a log warning, or raise ValueError when protect_turns exceeds the
     count. The spec doesn't say which is correct.
```

---

## BUG #4 — Docstring cache-key claim is unverified

```
BUG #[4]
Severity: LOW (potential HIGH if the claim is wrong)
Assumption violated: prune_tool_outputs' docstring at lines 287–291 asserts
                     "The token estimate cache is keyed on
                      (len(messages), hash(system_prompt)) — neither changes
                      when we mutate content. So we MUST invalidate the cache
                      after each stub."
Attack vector: If the actual cache key in models/conversation.py includes
               content-derived state (e.g., sum(len(m.content)) or a hash
               of all content), then:
               (a) The manual invalidation is unnecessary work.
               (b) The docstring's confidence is unfounded.
               (c) Any future cache-key change could silently make the
                   invalidation WRONG (e.g., if the cache key becomes
                   content-derived, the manual set to None becomes harmless
                   but the rationale in the docstring is now false).
Reproduction:
    from models.conversation import Conversation
    c = Conversation(agent_name='t', model='test/x')
    c.add_user_message('hi'); c.add_assistant_message('hello', [])
    c.get_token_estimate()  # populate cache
    # READ models/conversation.py:get_token_estimate() and identify the actual
    # cache key. If it's (len(messages), hash(system_prompt)), the docstring
    # is correct. If it includes content, the docstring is wrong.
Root cause: Docstring written before verifying the actual cache key.
Fix: Read get_token_estimate()'s implementation, confirm or correct the
     docstring's claim. Update either the docstring or the invalidation
     strategy to match.
```

---

## BUG #5 — `tokens_after_layer1` snapshot is taken unconditionally even when no Layer 1 work was done

```
BUG #[5]
Severity: LOW
Assumption violated: The compact() integration at lines 122–124:
                        self.prune_tool_outputs(conv, token_budget, protect_turns=2)
                        tokens_after_layer1 = conv.get_token_estimate()
                     The tokens_after_layer1 snapshot is ALWAYS taken, even
                     when prune_tool_outputs returned 0 (no work done). The
                     subsequent layer-determination logic correctly identifies
                     Layer 1 as not fired (because tokens_after_layer1 ==
                     tokens_before), but the snapshot is still computed.
Attack vector: get_token_estimate() is potentially expensive (iterates all
               messages, possibly calls tiktoken). For a compaction call
               where Layer 1 was a no-op (under budget), this snapshot is
               wasted work.
Reproduction: A tight compaction loop calling compact() 1000 times when the
              budget is already satisfied will compute tokens_after_layer1
              1000 times for nothing.
Root cause: Snapshot taken before the layer-determination branch, not after
            the prune_tool_outputs call's return value check.
Fix: Only snapshot if prune_tool_outputs returned > 0. Or, refactor the
     layer-determination to not need a second snapshot at all (compare
     tokens_before at the top to tokens_after at the bottom — the layer
     fired iff tokens_after < tokens_before AND messages weren't removed).
```

---

## BUG #6 — `_find_split_index` is called inside `compact()` despite being Phase 6 code

```
BUG #[6]
Severity: MEDIUM (process / scope)
Assumption violated: Phase 5 spec Step 1 CRITICAL RULES #1 and #2:
                     "Do NOT change _select_prune_candidate() — it's correct from
                      Phase 4."
                     "Do NOT change _summary() — still Phase 1's mechanical extraction."
                     And "SCOPE: This phase implements P4 ONLY. Do NOT implement:
                          P5 (_find_split_index) — Phase 6"
                     But compact() (line 119 onward) calls _find_split_index
                     INSIDE the trim loop and summary injection block, both
                     of which are Phase 5 territory.
Attack vector: git log shows _find_split_index was added in the same commit
               as prune_tool_outputs (or an earlier commit). The Phase 6
               commit then makes incremental changes to a method that
               already existed.
Reproduction:
    cd /home/q/projects/crabcakes
    git log --oneline -- agent/context_strategy.py
    # The first commit that adds _find_split_index — was it Phase 1 (forward-
    # loaded), Phase 5 (scope creep), Phase 6 (correct), or later?
Root cause: Same root cause as BUG #1 in the Phase 1 audit: the phase
            boundaries weren't enforced, and _find_split_index was absorbed
            into an earlier commit.
Fix: Verify the git history. If _find_split_index was added before Phase 6,
     the Phase 6 commit's diff against the previous state shows the
     incremental change. If the Phase 6 commit message claims "added
     _find_split_index" but the method already existed, that's a false
     commit message.
```

---

## BUG #7 — `_summary` is NOT Phase 1's mechanical extraction — it was upgraded to Phase 6 logic

```
BUG #[7]
Severity: MEDIUM (spec violation, scope creep)
Assumption violated: Phase 5 CRITICAL RULE #2: "Do NOT change _summary() —
                     still Phase 1's mechanical extraction."
                     Actual _summary() at lines 534–575 has:
                       - Phase 6: token_budget > 0 → use _find_split_index()
                       - Legacy fallback: token_budget == 0 → messages[:-4]
                     The method's docstring even says "Phase 6: Uses
                     _find_split_index() to compute a smarter split point".
Attack vector: Same scope violation pattern. Phase 5 was supposed to leave
               _summary() untouched, but the file shipped with Phase 6 logic.
Root cause: Phase 1 absorbed Phase 6 logic into the same commit. Phase 5
            and Phase 6 then made refinements to code that already existed.
Fix: See BUG #6 — verify git history, document the actual scope of each
     commit, and either amend specs or split commits.
```

---

## BUG #8 — No test for `prune_tool_outputs` when conversation has interleaved non-tool messages

```
BUG #[8]
Severity: MEDIUM (test gap)
Assumption violated: TestPruneToolOutputs has 6 tests, all of which use
                     cleanly-paired (ASSISTANT-with-tool-calls, TOOL_RESULT)
                     messages with no interleaving. Real conversations can
                     have user messages interleaved between tool calls (a
                     user might ask a follow-up while the previous tool
                     result is being processed).
Attack vector: The implementation assumes parent ASSISTANT is at idx-1 (BUG
               #1). A test that interleaves a USER message between the
               ASSISTANT-with-tool-calls and the TOOL_RESULT would catch
               this. The 6 existing tests don't have this case.
Reproduction:
    # Add this test to TestPruneToolOutputs:
    def test_interleaved_messages_use_correct_tool_name(self):
        """When user messages interleave, the parent ASSISTANT is not at idx-1."""
        from models.conversation import ToolCall
        conv = Conversation(agent_name='test', model='test/x')
        tc = ToolCall(call_id='call_z', tool_name='exec_command',
                      arguments={'cmd': 'ls'})
        conv.add_assistant_message('', [tc])
        conv.add_user_message('follow-up question')  # interleaved
        conv.add_tool_result('call_z', 'x' * 5000)
        strategy = DefaultContextStrategy()
        strategy.prune_tool_outputs(conv, target_tokens=100, protect_turns=0)
        # If the implementation only checks idx-1, tool_name defaults to "tool".
        # If the implementation searches backward, tool_name is 'exec_command'.
        tool_result = [m for m in conv.messages
                       if m.role == MessageRole.TOOL_RESULT][0]
        assert 'exec_command' in tool_result.content  # FAILS with current code
Root cause: Test cases don't reflect real-world message interleaving.
Fix: Add the test above. If it fails (as it should), fix BUG #1.
```

---

## BUG #9 — `prune_tool_outputs` doesn't return which messages were stubbed

```
BUG #[9]
Severity: LOW (API design)
Assumption violated: The function returns `tokens_before - tokens_after`
                     (an int). Callers have no way to know WHICH messages
                     were modified.
Attack vector: A caller (e.g., a UI that wants to highlight stubbed
               messages) can't iterate and find them — they have to scan
               every message and check `msg.content.startswith("[compacted")`
               themselves.
Reproduction: Hypothetical UI integration wanting to mark stubbed messages
              in the conversation view.
Root cause: API returns a scalar, not a list of indices or modified message
            references.
Fix: Either return a tuple (tokens_freed, stubbed_indices: list[int]), or
     add a separate method to query the set of stubbed messages. Low
     priority — the function is currently internal-only.
```

---

## BUG #10 — `conv._token_estimate_cache = None` after the for-loop is redundant

```
BUG #[10]
Severity: LOW (style, not correctness)
Assumption violated: prune_tool_outputs() invalidates the cache INSIDE the
                     loop (after each mutation) AND again AFTER the loop
                     (line 339). The post-loop invalidation is redundant
                     because the loop's last iteration already invalidated.
Attack vector: None — purely stylistic. Two invalidations don't hurt
               correctness, but they imply the cache invalidation is fragile
               when it isn't.
Reproduction: Code inspection at lines 336–339.
Root cause: Defensive programming gone too far. The post-loop invalidation
            is a no-op if the loop ran at least once.
Fix: Remove the post-loop invalidation. Or, document why it's needed (e.g.,
     "defense against future loop-bailout paths that might skip the
     in-loop invalidation").
```

---

## VERIFIED CORRECTNESS TABLE

| Behavior | Spec says | Code does | Status |
|----------|-----------|-----------|--------|
| `prune_tool_outputs()` stub format | "[compacted — {tool_name} output, {N} chars removed]" | Matches (line 336) | ✅ |
| Stub skips already-stubbed messages | Yes ("[compacted —" prefix) | Matches (line 322) | ✅ |
| protect_turns skips N most recent | Yes | Matches (line 314) | ✅ |
| Tool name extraction via tool_call_id | Yes | Matches (line 326–332) but **limited to idx-1** | ⚠️ |
| Cache invalidated after each mutation | Yes | Matches (line 339) | ✅ |
| Cache invalidated once more after loop | Yes | Matches (line 341) | ✅ (redundant) |
| Returns tokens freed | Yes | Matches (line 343) | ✅ |
| Mutates `msg.content` in place (no message add/remove) | Yes (CRITICAL RULE 6) | Matches | ✅ |
| `conv._token_estimate_cache = None` on every iteration | Yes | Matches | ✅ |
| Stops when get_token_estimate() <= target_tokens | Yes | Matches (line 319) | ✅ |
| 6 TestPruneToolOutputs tests pass | Yes | Yes (per post-mortem) | ✅ |
| `compact()` calls prune_tool_outputs before trim loop | Yes | Matches (line 122) | ✅ |
| `tokens_after_layer1` snapshot for telemetry | Yes | Matches (line 124) | ✅ |
| Layer detection: layer=1 if tokens decreased, layer=max with 2 if msgs removed | Yes | Matches (lines 244–249) | ✅ |
| Layer 0 (no compaction) defaults to layer=2 | Spec says it's OK | Matches (line 251) but **misleading** (see BUG #4 in Phase 1) | ⚠️ |
| Do NOT change `_select_prune_candidate()` | Yes | NOT changed | ✅ |
| Do NOT change `_summary()` | Yes | CHANGED (Phase 6 logic shipped) | ❌ |
| Do NOT use tiktoken | Yes | tiktoken NOT used in prune_tool_outputs | ✅ |
| Do NOT change `models/conversation.py` | Yes | NOT changed | ✅ |
| Do NOT change `agent/runtime.py` | Yes | NOT changed | ✅ |

---

## COMPLETENESS CHECKLIST

```
PHASE 5 COMPLETENESS:
- [x] prune_tool_outputs() method added to DefaultContextStrategy — evidence (line 265)
- [x] prune_tool_outputs() integrated into compact() as Layer 1 — evidence (line 122)
- [x] Idempotence: "[compacted —" prefix detection — evidence (line 322)
- [x] protect_turns: most recent N tool results skipped — evidence (line 314)
- [WARN] Tool name extraction from parent ASSISTANT's tool_calls — evidence (line 326)
      BUT: only checks idx-1, not backward search (BUG #1, BUG #8 test gap)
- [x] Cache invalidated after each content mutation — evidence (line 339)
- [x] CB-6 pairing preserved: tool_call_id and parent tool_calls unchanged — evidence (TestCB6)
- [x] TestPruneToolOutputs added with 6 tests — verify in test file
- [x] All new tests pass — per post-mortem
- [x] All existing tests pass — per post-mortem
- [x] Full suite no regressions — per post-mortem
- [NOT DONE] _summary() left untouched per spec — VIOLATED (BUG #7)
- [NOT DONE] Phase boundaries enforced — VIOLATED (BUG #6, BUG #7)
```

---

## Audit Metadata

- **Total bugs found:** 10 (1 HIGH, 4 MEDIUM, 5 LOW)
- **Critical findings:**
  - BUG #1: tool_name extraction only checks idx-1; breaks with interleaved messages
  - BUG #8: Test gap — no test for interleaved messages
  - BUG #6 + BUG #7: Phase boundary violations (same pattern as Phase 1 audit)
- **Pattern tags:** `adjacent-message-assumption`, `silent-fallback`,
  `scope-creep`, `test-gap-real-world-shape`, `redundant-cache-invalidation`
- **Most important question raised:** Why does Phase 5's test suite not
  exercise interleaved messages when real tool loops commonly have
  follow-up user messages? The tests verify the spec's happy path
  (cleanly-paired ASSISTANT/TOOL_RESULT) but miss the most common real-world
  conversation shape.
- **Recommendation:** Add BUG #8's interleaved test. If it fails, fix BUG #1.
  If it passes, the implementation has hidden backward-search logic that
  should be documented.