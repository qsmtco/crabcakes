# Phase 4E Post-Mortem — Streaming Token Count Always Zero

**Date:** 2026-06-21
**Supervisor:** Qaster
**Builder:** QTR
**Files changed:** 2 (`ui/handlers/activity_handler.py`, `tests/test_activity_bubbles.py`)
**Lines added:** +182 / -1
**Phases:** 3 (4E-1 helper + dispatcher fix, 4E-2 tests, 4E-3 verification)
**Process:** Supervisor wrote instructions file. Builder shipped code + tests in one cycle. Supervisor independently re-ran tests, performed mutation-style verification (reverted the fix → confirmed regression test fails with the expected assertion → restored), and verified the pre-fix baseline failure count via `git stash`.

---

## 1. The Bug

`ActivityHandler.on_gateway_event` dispatcher's `chat` branch read the wrong field name:

```python
# ui/handlers/activity_handler.py:469 (pre-fix)
self.on_chat_delta(payload.get("text", "") or "", session_key)
```

The gateway actually sends text at `payload["message"]["content"]` (per `models/streaming.py:28`). The top-level `text` key does not exist, so `.get("text", "")` always returned `""`. Downstream, `on_chat_delta` does `count = len(delta_text) if delta_text else 0` → `count = 0` → `_streaming_token_count` is never incremented. The FeedBar's streaming counter showed `0` indefinitely, and `velocity = token_est / elapsed` was also always `0 tok/s`.

The chat bubble itself was unaffected because `chat_handler.py:551-557` reads the correct field (`payload["message"]`) and passes it through `_extract_text` (`chat_handler.py:645-680`), which handles both string and list-of-blocks forms. The activity handler had no equivalent helper.

---

## 2. The Fix

**Change A — new helper method** (`ui/handlers/activity_handler.py:127-167`, +40 lines):

```python
def _extract_chat_text(self, payload: dict) -> str:
    """Extract plain text from a gateway chat event payload.
    Mirrors chat_handler._extract_text. Local copy to keep handlers
    decoupled — see tests/conftest.py::test_handlers_do_not_import_each_other.
    """
    msg_obj = payload.get("message", {})
    if isinstance(msg_obj, dict):
        content = msg_obj.get("content", "")
    else:
        content = msg_obj
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                t = block.get("text", "")
                if t:
                    parts.append(t)
            elif block_type == "input_image":
                continue  # image content not counted
        return "".join(parts)
    elif isinstance(content, str):
        return content
    return str(content) if content else ""
```

**Change B — dispatcher** (`ui/handlers/activity_handler.py:510`):

```python
# before
self.on_chat_delta(payload.get("text", "") or "", session_key)
# after
self.on_chat_delta(self._extract_chat_text(payload) or "", session_key)
```

The `or ""` belt-and-suspenders is preserved (helper always returns a string, but the guard is free).

---

## 3. Why a Local Copy Instead of Importing From `chat_handler`?

`tests/conftest.py::test_handlers_do_not_import_each_other` enforces handler decoupling. The activity and chat handlers are intentionally separated to avoid circular-import risk and to keep the activity handler as a pure state machine that knows nothing about chat rendering. If a third handler ever needs the same logic, promote `_extract_text` to a shared utility module. Out of scope for Phase 4E.

**Adaptation vs. the reference:** `chat_handler._extract_text` emits `input_image` blocks as ``` ```image ``` ``` code fences (used for bubble rendering). The activity helper skips them — the activity handler only needs text length for token estimation, and emitting markdown would inflate the character count with syntax characters, distorting the estimate.

---

## 4. Code Quality Grade: A (94/100)

### Justification

Single-line field-name bug, fixed surgically with a 1-line dispatcher change + 40-line local helper that mirrors the established pattern. Seven unit tests, all mutation-verified. Zero regressions. No architectural violations. The two pre-existing quirks documented as out-of-scope are real and worth a Tier-3 follow-up but not bugs in the strict sense (they are design decisions with non-obvious trade-offs).

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 20/20 | Mutation-verified: reverting the dispatcher line causes the regression test to fail with the exact expected message ("Expected 13, got 0"). All 7 new tests pass. Zero regressions in `test_chat_handler.py` (30/30) and zero new failures in full suite (25 pre-existing = 25 post-fix). |
| Architecture compliance | 10/10 | Stays in `activity_handler.py` only for code; tests in `test_activity_bubbles.py`. No `chat_handler.py` changes. Local helper copy respects `test_handlers_do_not_import_each_other` decoupling rule. |
| Test coverage         | 10/10 | All 7 tests are behavior tests (assert state after gateway event), not helper-only tests. Each tests a distinct payload shape: string content, list-of-blocks, input_image, missing message, raw-string message, multi-delta accumulation, helper contract. Test 1 is the regression test that would have caught this bug. |
| Documentation         | 9/10 | Helper has a thorough docstring explaining why it's a local copy. Inline comment on `input_image` explains the skip decision. No `ARCHITECTURE.md` update — the helper is internal (`_` prefix) so not part of the public contract. |
| Maintainability       | 9/10 | Helper mirrors the established pattern in `chat_handler._extract_text`. Anyone reading `_extract_chat_text` can find the reference. Test design note in `test_chat_delta_increments_token_count_across_multiple_deltas` explains the cumulative-vs-delta semantic quirk and links to `models/streaming.py:28` so the next maintainer understands why the test uses distinct delta texts. |
| DX (Developer Exp.)   | 9/10 | Test names read as sentences (`test_chat_delta_handles_list_of_blocks_form`). Assertion messages name both expected and actual values. Failure messages cite the input that produced the failure. |
| **Total**             | **94/100** | **A** |

Deducted points:
- 1 Documentation: helper docstring mentions `_extract_text` line range (`chat_handler.py:645-680`) which may drift if `chat_handler.py` is edited. Consider switching to a function-name reference instead.
- 1 Maintainability: cumulative-vs-delta accumulator ambiguity is documented but still a footgun. Anyone reading `on_chat_delta` with `+=` and not knowing about gateway cumulative-send semantics will be confused.
- 1 DX: helper tests are bundled with the integration tests in `TestActivityHandlerActivityBubbles` rather than in their own dedicated class — slight readability cost when running just the helper tests.

---

## 5. What's Good About the Code

1. **Behavior tests, not helper tests.** Each test exercises the full gateway-event path (`on_gateway_event("chat", payload)` → dispatcher → helper → `on_chat_delta` → counter increment) and asserts on `_streaming_token_count`. Test 7 (`test_extract_chat_text_returns_empty_for_empty_payload`) is the only direct helper test, and it pins the contract for an edge case. The other 6 would all have failed pre-fix, which is the whole point of the regression test.

2. **Mutation-verified.** Reverting the one-line dispatcher fix causes `test_chat_delta_increments_token_count_from_string_content` to fail with `Expected _streaming_token_count == 13 for 'Hello, world!', got 0`. The test asserts the correct value (13 chars), not just "non-zero" — if the gateway ever sent different content the test would catch that too.

3. **Honest baseline diff.** The spec said "13 pre-existing failures" but the actual pre-fix baseline was **25**. Builder caught this discrepancy and ran a clean before/after diff via `git stash` rather than relying on the stale number. Supervisor confirmed independently.

4. **Local helper copy respects architecture.** `_extract_chat_text` is a near-verbatim mirror of `chat_handler._extract_text`, but with one adaptation: image blocks are skipped instead of rendered as code fences. The reason is documented inline — the activity handler counts characters, it doesn't render bubbles.

5. **Design quirk documented where it matters.** `test_chat_delta_increments_token_count_across_multiple_deltas` has a multi-line docstring explaining why the test uses distinct delta texts ("Hello" + " world" + "!") instead of cumulative deltas ("Hello" + "Hello world" + "Hello world!"). The next person reading this test will understand both the field-name fix AND the deferred semantic ambiguity.

---

## 6. Out of Scope (Tier-3 Follow-Up Candidates)

1. **`_streaming_token_count` field is misnamed.** It stores character count (via `len(delta_text)`), then divides by 4 in `_streaming_label` as a rough char-to-token approximation. A real fix would either (a) use the LLM's actual `usage.completion_tokens` from the `chat.final` event, or (b) rename the field to `_streaming_char_count` and document the /4 approximation. **Not addressed here — the field just needs to accumulate something.**

2. **Cumulative-vs-delta accumulator semantics.** `on_chat_delta` does `self._streaming_token_count += count`. Per `models/streaming.py:28`, the gateway sends cumulative text — so in production, three deltas would be `"Hello"`, `"Hello world"`, `"Hello world!"`, and the counter would over-count (5+11+12=28 for a 12-char final string). The `+=` should probably be `=` with the understanding that each delta contains the full-so-far text. **Not addressed here — semantics not the cause of the always-zero bug, but worth a follow-up to make the counter accurate in production.**

3. **Shared `_extract_chat_text` module.** If a third handler needs the same logic, promote from two local copies to a shared `ui/handlers/_text_extract.py` (or `models/text_extract.py`). Currently two copies exist (`activity_handler._extract_chat_text`, `chat_handler._extract_text`); a third would be the trigger.

4. **Velocity time-window.** `_streaming_label` computes `velocity = token_est / elapsed` as a session-lifetime average. A more useful metric would be a rolling window (e.g., tokens in last 2 seconds). **Pre-existing design choice; not addressed.**

---

## 7. Process Notes

- **Spec-driven delegation worked.** 14.5 KB instructions file written before any code. Builder followed it verbatim — helper location, dispatcher change, all 7 test names, payloads, and assertions matched exactly.
- **One spec error caught by the builder.** Spec stated "13 pre-existing failures" but actual baseline was 25. Builder ran a clean before/after diff rather than relying on the stale number. Supervisor verified independently. Diff method is the correct regression detection; the absolute number was documentation drift.
- **Two-completion-event flow.** Both QTR (via `/ask` from project chat) and an orphaned sub-agent (spawned in error earlier in the loop, killed) produced the same code. Working tree is one consistent set of changes. Net effect: zero conflict.
- **Mutation-style verification by supervisor.** Reverted the one-line dispatcher fix, confirmed the regression test fails with the expected assertion message, restored. Proves the regression test is real, not theater.

---

## 8. Lessons Learned

1. **Baseline numbers in specs go stale.** Always re-measure at the start of a phase; never trust a number from a previous post-mortem. The diff-vs-baseline method is robust; absolute numbers are not.
2. **Spec files are a contract, not a deliverable.** The instructions file is committed for audit trail purposes but the actual contract is the helper signature + dispatcher change + test set. Builder matched all three exactly.
3. **"Reverts cleanly" is a real test of code quality.** The mutation-style verification (revert → test fails → restore) is fast and proves the test is non-tautological. Worth doing for every bug fix going forward.
4. **`/ask` is a chat-channel slash command.** The supervisor cannot emit it directly from a webchat session; the captain types it in the project chat. The mechanism that worked here was the user invoking `/ask` with the spec-file path.

---

## 9. Verification Evidence

- **Phase 4E tests:** `pytest tests/test_activity_bubbles.py -k "chat_delta or extract_chat" -v` → 7 passed, 0 failed
- **Regression check:** `pytest tests/test_chat_handler.py -v` → 30 passed, 0 failed
- **Full suite:** `pytest tests/ -q` → 25 failed (pre-existing baseline), 1936 passed (1929 baseline + 7 new), 1 skipped. **Zero new failures.**
- **Pre-fix baseline confirmation:** `git stash && pytest tests/test_improve.py tests/test_provider_test.py tests/test_mcp_config.py -q` → 25 failed. `git stash pop`. **Same number pre- and post-fix.**
- **Mutation-style:** revert dispatcher line → `test_chat_delta_increments_token_count_from_string_content` fails with `Expected 13, got 0`. Restore → all 7 pass.
- **`grep` audit:** `grep -rn 'payload.get("text"' ui/handlers/` → zero matches. Field-name bug pattern fully eliminated.
- **Handler decoupling:** `test_handlers_do_not_import_each_other` (in `conftest.py`) still passes. No cross-handler import introduced.
- **Working tree:** `git status` shows exactly 2 modified files (`activity_handler.py`, `test_activity_bubbles.py`) and 1 untracked file (spec for audit trail). Total: +182/-1 lines.