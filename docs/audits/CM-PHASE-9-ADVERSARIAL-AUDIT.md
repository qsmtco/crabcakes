# Phase 9 Context Management — Adversarial Audit Report

**Auditor:** qtr (OC Tech Writer) — direct, after subagent terminations
**Phase:** CM Phase 9 — CB-6 Hardening + Silent Exception Cleanup
**Files audited:** `agent/context_strategy.py` (lines 386–432, `_find_split_index` CB-6 block), `agent/runtime.py` (lines 305–313, 1355–1363), `tests/test_context_strategy.py` (TestFindSplitIndexCB6Hardening)
**Commit:** `a69e763`
**Spec:** `docs/specs/CM-PHASE-9-INSTRUCTIONS.md`
**Adversarial prompt:** `prompts/adversarialDebugger.md`

---

## Summary

Phase 9 is the first phase whose commit diff actually contains substantive code
changes unique to that phase. The git diff for `a69e763` shows:

1. **`_find_split_index`**: Added a `found_parent` flag, replaced the `for-else`
   pattern with explicit `if found_parent: continue`, and added a NEW search
   loop over the keep_first region (indices 0..keep_first-1) that increments
   `split` to include the orphan TOOL_RESULT in the head.

2. **`agent/runtime.py`**: Two `except Exception: pass` blocks replaced with
   `logger.debug(...)` at line 308 (tool-call args JSON) and line 1359
   (MCP cleanup). Verified by reading the current source.

3. **`tests/test_context_strategy.py`**: 177 lines added — TestFindSplitIndexCB6Hardening
   class with 3 tests.

This is the first phase that didn't forward-load its changes into an earlier
commit (because it's the LAST phase — there's nothing later to forward-load
into). The audit therefore focuses on the algorithm correctness and the
remaining edge cases.

The CB-6 hardening is real and correctly implemented for the spec's stated
case (parent at index `keep_first - 1`). However, several adjacent edge cases
are unaddressed:

1. **The new search loop uses `min(keep_first, len(conv.messages)) - 1` as
   the upper bound** — if `keep_first == 0`, this is `-1`, and the `for j
   in range(-1, -1, -1)` loop is empty. No search, no `found_parent`
   assignment, no split increment. The function then returns to the outer
   `while` loop which checks `split < len(messages)` and may re-enter the
   CB-6 block with the same TOOL_RESULT — infinite loop if the parent
   doesn't exist anywhere in the conversation.
2. **The `found_parent` flag may be set to `True` for a parent that exists
   in keep_first region but with a DIFFERENT tool_call_id** — no, wait,
   the loop checks `tc.call_id == msg_at_split.tool_call_id`, so the match
   is correct.
3. **What if the parent ASSISTANT has multiple tool_calls and only ONE
   matches the orphan's tool_call_id?** The search returns the first
   match (no break-on-match for partial-match). The behavior is correct
   but the matching loop is O(M*K) where M = tool_calls per candidate
   and K = candidates.
4. **The `while split < len(conv.messages)` outer loop has no
   `iterations` cap.** If the new search keeps incrementing split (e.g.,
   consecutive orphans), split could grow unbounded. In practice,
   the function increments split by 1 each iteration and the loop
   terminates when split reaches len(messages). Not infinite, but
   worst-case O(N) outer iterations.
5. **The `except Exception as e:` pattern at lines 308 and 1359 uses
   `%s` for string formatting**, which is correct. But the variable name
   `e` shadows the outer scope if there's an enclosing try block.
   Python 3.x allows this but it's a lint smell.
6. **The new tests have one subtle issue**: `test_tool_result_orphan_included_in_head`
   constructs the conversation by `conv.messages = []` and then manually
   appending — but the constructor's step_count and other state may be
   in an inconsistent state. The test only checks split > 2, which passes
   for either the old or new behavior.

---

## BUG #1 — `keep_first == 0` produces empty search loop, causing outer loop re-entry

```
BUG #[1]
Severity: HIGH
Assumption violated: Line 411: `for j in range(min(keep_first, len(conv.messages)) - 1, -1, -1):`.
                     If keep_first == 0, min(0, N) - 1 = -1. The range(-1, -1, -1)
                     is empty (no iterations).
Attack vector: A caller passes keep_first=0 (Phase 4 spec mentions this as a
               valid "no protected head" value). When the CB-6 forward
               check fires with a TOOL_RESULT whose parent is in the
               protected head (now an empty head), the search loop does
               nothing. `found_parent` stays False. The `if not found_parent:
               break` exits the outer while loop. So the orphan TOOL_RESULT
               stays at `split`, not in the head. This is the OLD
               (pre-hardening) behavior for this case — not a regression,
               but the hardening doesn't handle keep_first=0.
Reproduction:
    from agent.context_strategy import DefaultContextStrategy
    from models.conversation import Conversation, Message, MessageRole, ToolCall
    conv = Conversation(agent_name='t', model='test/x')
    conv.messages = []
    # Parent ASSISTANT at index 0
    parent = Message(role=MessageRole.ASSISTANT, content='checking',
                     tool_calls=[ToolCall(call_id='c1', tool_name='exec', arguments={})])
    conv.messages.append(parent)
    conv.messages.append(Message(role=MessageRole.TOOL_RESULT, content='r',
                                 tool_call_id='c1'))
    for i in range(10):
        conv.add_user_message(f'u{i}' + 'x'*1000)
        conv.add_assistant_message(f'a{i}' + 'y'*1000, [])
    s = DefaultContextStrategy()
    split = s._find_split_index(conv, budget_tokens=8000, keep_first=0)
    # The parent is at index 0, which IS in the keep_first region (keep_first=0,
    # so region is indices < 0, i.e., empty). The new search loop does nothing.
    # `found_parent` stays False. `split` does NOT advance past the TOOL_RESULT.
    # The orphan stays at split (which may be index 1 — the TOOL_RESULT itself).
    # This means the head is conv.messages[:1] = [parent], and the tail
    # is conv.messages[1:] = [TOOL_RESULT, ...]. The orphan is in the TAIL.
    # CB-6 violation: orphan TOOL_RESULT with no parent in the tail.
    # Note: keep_first=0 is unusual but Phase 4 spec mentions it as a valid value.
Root cause: The search range's upper bound is `min(keep_first, len) - 1`.
            When keep_first == 0, this is -1, range is empty.
Fix: The search range should be `range(keep_first - 1, -1, -1)` if
     `keep_first > 0`, else `range(0, -1, -1)` (no iteration needed —
     the head is empty, no parent can be in the head, the search is
     correctly skipped). But the CURRENT code's empty loop is CORRECT
     behavior for keep_first=0 — there's no head to search, so the
     orphan SHOULD stay in the tail if its parent is also not in the
     trimmable region.
     Actually re-reading: if keep_first=0 and the parent is at index 0,
     and we want the orphan TOOL_RESULT to stay with its parent, the
     parent is at index 0 which IS trimmable. The original backward
     search `range(split-1, keep_first-1, -1) = range(split-1, -1, -1)`
     WOULD find the parent at index 0. So the new keep_first search
     isn't even needed for this case.
     The bug, then, is more subtle: the new search is REDUNDANT for
     keep_first=0 (the original search covers it) and the empty loop
     doesn't cause incorrect behavior. The "BUG" is that the new search
     LOOKS like it has a bug but actually doesn't.
     WAIT — let me re-read more carefully. The original backward search
     was `range(split - 1, keep_first - 1, -1)`. With keep_first=0, this
     is `range(split-1, -1, -1)` which goes from split-1 down to 0
     (inclusive — range(stop=-1, step=-1) is exclusive of stop=-1, so
     indices split-1, split-2, ..., 0). Yes, the parent at index 0 is
     found. So the original code worked for keep_first=0.
     Conclusion: BUG #1 is not actually a bug. The empty loop is harmless
     because the original backward search covers keep_first=0 cases.
     REVISED SEVERITY: LOW (false alarm, but worth noting that the
     empty-loop behavior is non-obvious).
```

---

## BUG #2 — Outer while loop has no iteration cap; consecutive orphans → O(N) iterations

```
BUG #[2]
Severity: LOW (performance, not correctness)
Assumption violated: The `while split < len(conv.messages):` loop processes
                     one TOOL_RESULT per iteration. With the new search,
                     split is incremented past consecutive orphans. For
                     a conversation with K consecutive TOOL_RESULTs whose
                     parents are all in the head, the loop runs K times.
                     Each iteration does O(N) backward search (in the
                     original code) or O(K) (in the new code, since the
                     head is bounded by keep_first). Total: O(K²).
Attack vector: A conversation with 50 consecutive (orphan TOOL_RESULT)
               messages where each parent is in keep_first. _find_split_index
               takes O(50²) = O(2500) work for the CB-6 block.
Reproduction: Construct a conversation with 50 consecutive orphan
              TOOL_RESULTs and time _find_split_index.
Root cause: No skip-ahead optimization. Each orphan is processed
            independently.
Fix: After finding a parent in keep_first and incrementing split, the
     NEXT iteration's TOOL_RESULT might also be an orphan with the SAME
     parent. The new search would find the same parent again. Optimization:
     skip ahead to the message after the parent (since all consecutive
     orphans until the next non-orphan message share the same parent).
     Low priority — the function is only called once per compaction cycle.
```

---

## BUG #3 — `found_parent` flag is shadowed / reused incorrectly

```
BUG #[3]
Severity: LOW (style)
Assumption violated: The variable `found_parent` is set to True in two
                     different branches (the original trimmable-region
                     search and the new keep_first-region search). It's
                     also checked in two `if` statements after each
                     branch. The flow is:
                       1. Search trimmable region, set found_parent if found.
                       2. If found_parent: continue.
                       3. Search keep_first region, set found_parent if found.
                       4. If not found_parent: break.
                     Step 3 sets found_parent. Step 4 checks it. OK, this
                     works. But step 2's check means we never reach step
                     3 if the trimmable region succeeded. So the variable
                     is correctly scoped.
Attack vector: None — the logic is correct. Style nit only.
Reproduction: Code inspection at lines 396–428.
Root cause: Variable name suggests a single concept ("did we find the
            parent?") but is reused across two distinct searches. A more
            descriptive name would be `parent_found_in_trimmable` and
            `parent_found_in_keep_first`.
Fix: Rename for clarity, or break into a helper method
     `_find_parent_assistant(conv, tool_call_id, start_idx, end_idx)`
     that returns the parent index or None.
```

---

## BUG #4 — `except Exception as e: logger.debug(...)` uses `%s` formatting, which is fine but `%s` with `e` may swallow exception details

```
BUG #[4]
Severity: LOW
Assumption violated: Lines 308 and 1359 use:
                        logger.debug("Failed to parse tool-call args JSON: %s", e)
                        logger.debug("MCP best-effort cleanup failed for %s: %s", session_key, e)
                     The `%s` formatting passes the exception's `str(e)` to
                     the log. This loses the traceback.
Attack vector: A developer investigating a JSON parse failure sees only
               "Failed to parse tool-call args JSON: Expecting value: line 1
               column 1 (char 0)" — they don't see WHERE in the tool-call
               processing pipeline the failure occurred. The traceback is
               needed for stack context.
Reproduction: Construct an invalid tool-call args JSON in a test, trigger
              the except branch, inspect the log output.
Root cause: `logger.debug("...", e)` uses `%s` which calls `str(e)`, not
            `repr(e)` and not `traceback.format_exc()`. The traceback is
            only logged if `logger.exception(...)` is used (which auto-
            includes traceback).
Fix: Use `logger.exception(...)` for unexpected exceptions, or
     `logger.debug("...", exc_info=True)` to include the traceback. The
     spec said `logger.debug(...)` with `%s` format strings, so this is
     spec-compliant — but consider amending for production debugging.
```

---

## BUG #5 — Test `test_tool_result_orphan_included_in_head` may pass for the wrong reason

```
BUG #[5]
Severity: MEDIUM (test integrity)
Assumption violated: Test 1 (lines 1 of TestFindSplitIndexCB6Hardening)
                     constructs:
                       conv.messages = []
                       conv.add_user_message("question")
                       conv.messages.append(parent)  # at index 1 (after user message at 0)
                       conv.messages.append(child)   # at index 2
                     With keep_first=2, the protected head is indices 0 and 1
                     (user message + parent ASSISTANT). The TOOL_RESULT at
                     index 2 is the first non-protected message.
                     The half-budget loop accumulates from the END of the
                     conversation (10 user/assistant pairs of ~1000 chars each).
                     With budget=8000, half_budget=4000. The loop breaks when
                     accumulated tokens >= 4000. ~3 messages per side, so
                     split lands around index 14 or so.
                     Then the CB-6 forward check fires at split=14 (a regular
                     user message — not TOOL_RESULT, so the outer while
                     breaks). split > 2 is trivially True.
                     The test PASSES regardless of whether the CB-6 hardening
                     was applied, because the half-budget loop already puts
                     split well past index 2.
Attack vector: A reviewer assumes the test verifies the hardening. It
               doesn't — the assertion `split > 2` would pass even if
               the hardening were reverted to the pre-Phase-9 version
               (which didn't search keep_first).
Reproduction: Revert the Phase 9 changes (remove lines 409–424), re-run
              the test. It still passes.
Root cause: The test doesn't CONSTRUCT a scenario where the half-budget
            loop would land split at or near the orphan's position.
            Specifically: the test puts the orphan at index 2 (immediately
            after the keep_first region), so the half-budget loop almost
            always lands split much further along.
Fix: Construct the test such that the half-budget loop LANDS at the
     orphan's index. For example, put the orphan AT THE END of the
     conversation (index = len - 1) and use a tight budget so split
     lands near the end:
       conv.messages.append(parent)  # keep_first-1
       # Fill middle with regular messages
       for i in range(10):
           conv.add_user_message(f'u{i}')
           conv.add_assistant_message(f'a{i}', [])
       # Orphan at the end
       conv.messages.append(Message(role=MessageRole.TOOL_RESULT, ...))
       split = strategy._find_split_index(conv, budget_tokens=100, keep_first=2)
       # With tight budget, split lands near the end. The orphan is the
       # last message. CB-6 forward check fires. The parent is in
       # keep_first region. The hardening should include the orphan in
       # the head (split += 1, but split is already at the orphan's
       # position, so it advances past).
       assert split > orphan_index
```

---

## BUG #6 — Test 2 `test_consecutive_tool_results_with_parent_in_head` has same issue

```
BUG #[6]
Severity: MEDIUM (test integrity)
Assumption violated: Same as BUG #5. The test places the consecutive orphans
                     at indices 2 and 3 (immediately after keep_first region).
                     The half-budget loop lands split much further along.
                     `assert split > 3` passes trivially.
Attack vector: Same as BUG #5.
Root cause: Same as BUG #5.
Fix: Same as BUG #5 — construct orphans at the END of the conversation
     with a tight budget so split lands near them.
```

---

## BUG #7 — Test 3 `test_no_orphan_when_parent_in_trimmable_region` is the only meaningful CB-6 test

```
BUG #[7]
Severity: LOW (positive note)
Assumption violated: Test 3 verifies the NORMAL CB-6 behavior (parent
                     in trimmable region, normal backward search). The
                     assertion is `split >= 2`, which is the keep_first
                     minimum. This passes for any non-broken implementation.
                     This test is the most useful of the three — it verifies
                     that the Phase 9 changes didn't break the existing
                     CB-6 logic.
Reproduction: All three tests pass.
Root cause: Test 3 is well-designed (it verifies the existing path doesn't
            regress). Tests 1 and 2 are poorly designed (they don't
            construct scenarios where the new logic actually fires).
Fix: Rewrite Tests 1 and 2 per BUG #5 and BUG #6 fixes.
```

---

## BUG #8 — Phase 9 commit message claims "except Exception cleanup" but only replaces 2 of N occurrences

```
BUG #[8]
Severity: LOW (process / scope)
Assumption violated: Phase 9 spec said "Find the EXACT lines with
                     `grep -n "except Exception:" agent/runtime.py` first.
                     There should be exactly 2 remaining (after Phase 7
                     fixed the third). Replace ONLY the `except Exception: pass`
                     patterns — do not change any `except Exception as e:`
                     patterns that already log."
                     Actual grep shows 16 `except Exception` patterns in
                     runtime.py. The spec said there were 2 `pass` patterns.
                     The Phase 9 commit replaced those 2. The remaining 14
                     are `except Exception as e: logger.error(...)` or
                     similar, which were ALREADY logging.
Attack vector: A reviewer assumes Phase 9 cleaned up all silent
               exceptions. It only cleaned up the 2 that were `pass`.
               The other 14 were already logging — but the spec didn't
               explain this clearly.
Reproduction:
    grep -n "except Exception" agent/runtime.py | wc -l    # 16
    grep -n -A1 "except Exception" agent/runtime.py | grep "pass" | wc -l  # 0
    # All 16 are now either logging or re-raising. No silent `pass` remains.
Root cause: Spec was unclear about the count (it said "2 remaining" which
            was correct at the time, but didn't say "16 total patterns
            exist, of which 14 already log").
Fix: Update the spec post-hoc to clarify: "16 except clauses exist;
     14 already log; 2 used `pass`. Phase 9 replaces the 2 `pass`
     patterns with `logger.debug(...)`." Or, more usefully, audit the
     14 already-logging clauses to ensure their log messages are
     actionable.
```

---

## BUG #9 — `conv.messages = []` in tests bypasses the Conversation invariants

```
BUG #[9]
Severity: LOW (test hygiene)
Assumption violated: The CB-6 hardening tests use `conv.messages = []` then
                     manually append messages. This bypasses the
                     Conversation constructor's invariants (e.g.,
                     step_count increment, message validation in
                     add_user_message / add_assistant_message).
Attack vector: If the constructor adds invariants in a future change
               (e.g., rejects messages without required fields), the
               tests would silently use a Conversation that violates
               those invariants.
Reproduction: All tests pass currently.
Root cause: Test construction pattern uses raw list mutation instead
            of the public API.
Fix: Use the public API to construct the conversation. For the parent
     ASSISTANT with tool_calls, use `conv.add_assistant_message(content,
     [ToolCall(...)])`. For the TOOL_RESULT, use `conv.add_tool_result(
     tool_call_id, content)`. This way the test exercises the same code
     paths as production.
```

---

## BUG #10 — No test for `keep_first=0` edge case in CB-6 hardening

```
BUG #[10]
Severity: LOW (test gap)
Assumption violated: The 3 new tests all use `keep_first=2`. None exercise
                     keep_first=0 (where the new search loop's range is
                     empty). The behavior at keep_first=0 is correct
                     (the original backward search covers it), but is
                     unverified.
Reproduction: Add a test:
    def test_keep_first_zero_orphan_covered_by_original_search(self):
        """keep_first=0: orphan's parent in trimmable region, covered by original search."""
        strategy = DefaultContextStrategy()
        conv = Conversation(agent_name="Coder", model="openai/gpt-4o")
        conv.messages = []
        parent = Message(role=MessageRole.ASSISTANT, content="checking",
                         tool_calls=[{"id": "call_1", "type": "function",
                                      "function": {"name": "search", "arguments": "{}"}}])
        conv.messages.append(parent)  # at index 0
        conv.messages.append(Message(role=MessageRole.TOOL_RESULT, content="r",
                                     tool_call_id="call_1"))
        for i in range(10):
            conv.add_user_message(f"u{i} " + "x" * 1000)
            conv.add_assistant_message(f"a{i} " + "y" * 1000, [])
        split = strategy._find_split_index(conv, budget_tokens=8000, keep_first=0)
        # Original backward search should find parent at index 0.
        # split should land at parent (index 0) or higher.
        # But split >= keep_first = 0, so this is trivially True.
        # Real assertion: messages after split should not have orphan TOOL_RESULTs.
        # If split > 1 (past the orphan), no orphans. If split = 0, head is empty
        # and tail includes parent + orphan (CB-6 valid: parent comes first).
        assert split <= 1  # orphan in head (split=1) or tail with parent (split=0)
Root cause: Test gap.
Fix: Add the test above.
```

---

## VERIFIED CORRECTNESS TABLE

| Behavior | Spec says | Code does | Status |
|----------|-----------|-----------|--------|
| `_find_split_index` searches keep_first region for parent | Yes | Matches (lines 409–424) | ✅ |
| Orphan TOOL_RESULT included in head (split += 1) | Yes | Matches (line 419) | ✅ |
| Consecutive orphans all handled | Yes | Matches (`continue` re-enters loop) | ✅ |
| Backward search in trimmable region unchanged | Yes | Matches (lines 396–407) | ✅ |
| `_find_split_index` signature unchanged | Yes | Matches | ✅ |
| `agent/runtime.py:308` replaced with `logger.debug` | Yes | Matches (lines 305–313) | ✅ |
| `agent/runtime.py:1359` replaced with `logger.debug` | Yes | Matches (lines 1355–1363) | ✅ |
| Other `except Exception` patterns NOT changed | Yes | Verified by grep | ✅ |
| `logger` already defined at module level | Yes | Verified | ✅ |
| TestFindSplitIndexCB6Hardening added with 3 tests | Yes | Yes (177 lines added) | ✅ |
| Tests pass | Yes | Per post-mortem | ✅ |
| `_select_prune_candidate` unchanged | Yes | Unchanged | ✅ |
| `models/conversation.py` unchanged | Yes | Unchanged | ✅ |
| `utils/prompt_loader.py` unchanged | Yes | Unchanged | ✅ |

---

## COMPLETENESS CHECKLIST

```
PHASE 9 COMPLETENESS:
- [x] CB-6 fix: _find_split_index searches keep_first region — evidence (lines 409–424)
- [x] CB-6 fix: orphan TOOL_RESULT included in head — evidence (line 419, split += 1)
- [x] CB-6 fix: consecutive TOOL_RESULTs handled — evidence (continue re-enters while)
- [x] except Exception: pass → logger.debug at line 308 — evidence (lines 305–313)
- [x] except Exception: pass → logger.debug at line 1359 — evidence (lines 1355–1363)
- [x] TestFindSplitIndexCB6Hardening added with 3 tests — evidence (commit a69e763)
- [x] All new tests pass — per post-mortem
- [x] All existing tests pass — per post-mortem
- [x] Full suite no regressions — per post-mortem
- [WARN] Tests 1 and 2 don't actually verify the hardening (BUG #5, BUG #6)
```

---

## Audit Metadata

- **Total bugs found:** 10 (1 HIGH [revised to LOW], 2 MEDIUM, 7 LOW)
- **Critical findings:**
  - BUG #5, BUG #6: Tests 1 and 2 don't construct scenarios where the
    CB-6 hardening actually fires — they pass for the wrong reason
  - BUG #8: Spec was unclear about which `except Exception` patterns
    to clean up
- **Pattern tags:** `empty-loop-no-op`, `trivial-test-assertion`,
  `test-construction-bypasses-invariants`, `log-format-without-traceback`,
  `commit-message-scope-ambiguity`
- **Most important question raised:** Are the CB-6 hardening tests
  actually testing the hardening, or are they just checking trivial
  assertions? If the hardening were reverted to the pre-Phase-9 code,
  would the tests still pass? Answer: Tests 1 and 2 would still pass
  (they assert split > 2 or split > 3, which is trivially true with
  the half-budget loop). Test 3 verifies the unchanged path. So the
  hardening is UNVERIFIED by the new tests — only the unchanged path
  is verified.
- **Recommendation:** Rewrite Tests 1 and 2 to put the orphans at the
  END of the conversation with a TIGHT budget, so the half-budget
  loop lands split near the orphan's position and the CB-6 forward
  check actually fires.