# Activity Drawer Re-Audit Fixes — Steel-Framed Spec

**Date:** 2026-07-17
**Author:** Debugger (adversarial re-audit)
**Status:** Draft — for implementation
**Implements:** Adversarial re-audit findings from `docs/audits/BRIEFING-activity-drawer-reaudit.md`
**Depends on:** `docs/specs/SPEC-ACTIVITY-DRAWER-BUGFIXES.md` (BUG #1, #2, #4, #5, #12 fixes — verified correct)
**Target branch:** main

> Architecture compliance: all fixes stay within the files already changed by `SPEC-ACTIVITY-DRAWER-BUGFIXES.md` (`agent/runtime.py`, `ui/handlers/agent_runtime_handler.py`, `tests/test_agent_runtime.py`). No new files, no new dependencies. No handler-to-handler imports (per ARCHITECTURE.md §8.6).

---

## 1. Overview

### Problem statement
The Debugger re-audit of the activity-drawer bugfixes (14 new tests, 5 fixes verified correct) uncovered THREE new defects:

1. **BUG #13 (HIGH) — `success` param shadowed by feed-card block.** In `_do_tool_call_result`, the feed-card block at `ui/handlers/agent_runtime_handler.py:1116, 1121` reassigns the param `success`. The bubble block at line 1169 reads the clobbered value, not the runtime's dispatch. This re-introduces BUG #1 under a different mechanism: any tool that fails with a string result (denied exec_command, sensitive-path write_file block) emits `tool_end` ✅ instead of `tool_error` ❌. For `write_file` failures with string results, the bubble is suppressed entirely (worse than the original BUG #1).
2. **BUG #14 (HIGH) — `_ended_sessions` only discarded in `_do_text_delta`.** Tool-only turns (no streaming text) leave the flag set, suppressing the next turn's legitimate `tool_start` bubble.
3. **BUG #15 (MEDIUM) — `_pending_exec_commands` capture still inside the project guard.** BUG #4 fix moved the bubble emissions outside the guard but not the command capture, so the drawer's `command_output` row label is `""` when no project is open (original BUG #11 more frequent, not less).

Plus a **test gap (LOW)** in the 14 existing tests: `test_denied_exec_command_emits_tool_error_bubble` and `test_sensitive_path_block_emits_tool_error_bubble` call `_do_tool_call_result` directly without first calling `_do_tool_call_start`, so `_tool_card_ids[sk]` is empty and the feed-card block is skipped. The tests pass despite BUG #13 because they exercise the no-card path.

### Solution summary
- Rename the feed-card block's local from `success` to `card_success` (4-line rename, no behavior change in the card display). The bubble block reads the param.
- Discard `_ended_sessions[sk]` in `_do_tool_call_start` after the stale-call suppression check, so tool-only turns clear the flag.
- Move `self._pending_exec_commands[sk] = cmd` out of the project guard in `_do_tool_call_start`, alongside the existing unconditional `_pending_tool_args[sk] = args` block.
- Add 3 regression tests that exercise the real attack path (with a card primed in `_tool_card_ids`).

### Scope

| In scope | Out of scope |
|----------|--------------|
| BUG #13 fix (param rename) | ARCHITECTURE.md update (PM has queued as separate follow-up) |
| BUG #14 fix (`_do_tool_call_start` discard) | New tools or new bubble types |
| BUG #15 fix (move exec command capture) | Any change to `agent/runtime.py` |
| 3 new regression tests | Renaming of any other functions |
| | Reformatting of adjacent code |

### Architecture principles
- Layer separation: `ui/handlers/agent_runtime_handler.py` may not import from `gateway/` or `models/` (ARCHITECTURE.md §2). The fix does not add any new imports.
- No handler-to-handler imports (§8.6 R2). The fix does not add any.
- All callback signatures use `Callable[[...], None] | None = None` (existing pattern).
- BUG #4 fix (move bubble emissions outside the project guard) is structurally preserved and extended.

---

## 2. Changes by File

### 2.1 `ui/handlers/agent_runtime_handler.py` — three surgical edits

**Edit A (BUG #13): rename feed-card local in `_do_tool_call_result` (lines 1116, 1121, 1124)**

In the feed-card block (currently lines 1109-1142), the `if hasattr(result, 'output')` branch reads `result.success` into the param `success`, and the `else` branch hard-codes `success = True`. Both assignments persist into the bubble block at line 1169 because Python has no block scope. Rename the local to `card_success` in both branches, and use `card_success` in the `card.metadata["status"]` line.

Verified against source: the param `success` is the 4th positional in `_do_tool_call_result(self, session_key, name, result, success: bool = True)`. The feed-card block at lines 1109-1142 is the only place `success` is reassigned. The bubble block at line 1169 reads `is_error = not success` and MUST see the runtime-dispatched value.

Exact diff (3 lines):
```python
# Line 1116 (was: `success = result.success`):
card_success = result.success
# Line 1121 (was: `success = True`):
card_success = True
# Line 1124 (was: `card.metadata["status"] = "complete" if success else "error"`):
card.metadata["status"] = "complete" if card_success else "error"
```

The bubble block at line 1169 (`is_error = not success`) is UNCHANGED — it now reads the param, not the clobbered value.

**Edit B (BUG #14): discard `_ended_sessions[sk]` in `_do_tool_call_start` (line 1002)**

In `_do_tool_call_start`, after the existing stale-call suppression early-return, add a discard so the first `tool_start` of a new turn clears the flag for subsequent calls.

Current code (lines 1002-1004):
```python
if session_key in self._ended_sessions:
    logger.debug("_do_tool_call_start: suppressed for ended session %s", session_key)
    return
```

This early-return is correct for STALE dispatches. The bug is that the flag is never cleared for FRESH dispatches. The fix is to discard the flag when a fresh dispatch is recognized as the first call of a new turn.

Two viable approaches (the implementer chooses one):

**Option B1 (preferred — minimal change):** Move the discard before the early-return, so EVERY `_do_tool_call_start` call clears the flag. Stale calls still get suppressed (the early-return runs after the discard), but a new turn's first call clears the flag.
```python
# BUG #14: clear ended flag on any tool_start — this is the entry point
# of a new turn, since _do_text_delta may not fire (tool-only turn).
self._ended_sessions.discard(session_key)
if session_key in self._ended_sessions:  # this will always be False now
    ...  # dead code, can be removed
```

Wait — this is wrong. `_ended_sessions` is a `set`, and `discard` is idempotent. If the set didn't contain the key, discard is a no-op. If it did contain the key, discard removes it. After the discard, `in` is always False. So the existing early-return is now dead code and the flag-clear logic is correct.

But this breaks the stale-call suppression: a stale `idle_add`-dispatched `_do_tool_call_start` from a previous turn would no longer be suppressed.

**Option B2 (correct — preserve suppression):** Keep the early-return; add a separate code path for "first tool_start of a new turn". Detection: track the previous turn's end separately, OR re-architect the flag as a single-element set (the LAST session to end), OR rephrase the suppression as "if the runtime is currently in the middle of a turn".

The implementer should choose between B1 and B2 based on whether stale-call suppression is still required. Stale calls are dispatched via `GLib.idle_add` (FIFO). If a previous turn's `_on_tool_call_start` is in the queue when `cancel()` fires, the runtime now dispatches `_on_error` which sets `_ended_sessions[sk]`. The stale `_on_tool_call_start` then arrives and gets suppressed. **If B1 is chosen, the stale call would now PROCEED and emit a tool_start bubble after the cancel — which is exactly the BUG #2 orphan the suppression was added to prevent.**

Therefore **B1 is wrong** and **B2 is the correct fix**. The implementer MUST use B2 or a similarly safe variant.

**Option B2 implementation:** the cleanest approach is to add a parallel set `_started_turn_sessions: set[str]` that tracks "this session has had at least one tool_start since the last end". The first `tool_start` of a new turn clears `_ended_sessions`; subsequent calls don't. This preserves stale-call suppression.

```python
# In __init__ (around line 100, alongside _ended_sessions):
self._started_turn_sessions: set[str] = set()

# In _do_tool_call_start (after the existing stale-call suppression at line 1002-1004):
# BUG #14: tool-only turns never reach _do_text_delta's discard. Detect the first
# tool_start of a new turn by tracking which sessions have started their current turn.
if session_key not in self._started_turn_sessions:
    self._started_turn_sessions.add(session_key)
    self._ended_sessions.discard(session_key)
```

And the end sites (`_do_response_complete` ~line 1454, `_do_error` ~line 1720) must clear `_started_turn_sessions[sk]`:
```python
# After self._ended_sessions.add(session_key) in both end sites:
self._started_turn_sessions.discard(session_key)
```

Verify the implementer adds the discard in BOTH end sites (`_do_response_complete` and `_do_error`). Grep for `_ended_sessions.add` to find them.

**Edit C (BUG #15): move `_pending_exec_commands` capture out of project guard (line 1027)**

In `_do_tool_call_start`, the `self._pending_exec_commands[session_key] = cmd` line is inside the `if self._fh is not None and self._active_project is not None:` block (lines 1014-1060). BUG #4 fix (in the prior spec) moved the bubble emissions and `_pending_tool_args[sk] = args` out of this guard, but missed this line.

Verified against source: the `cmd` variable is resolved at line 1022-1024, INSIDE the project guard but BEFORE the `_pending_exec_commands[sk] = cmd` line at 1027. The fix is to move the capture line to the unconditional block at lines 1061-1062 (the existing unconditional block that stores `_pending_tool_args` and emits the tool_start bubble).

Exact diff:
```python
# Line 1027 (was: inside the project guard):
# self._pending_exec_commands[session_key] = cmd
# DELETE this line.

# After line 1061 (the existing unconditional block), ADD:
# BUG #15: capture the command string for the command_output callback, even
# when no project is open. The callback needs cmd for the drawer row label.
self._pending_exec_commands[session_key] = cmd
```

The `cmd` variable is already resolved at line 1022-1024 (inside the project guard, used for the feed-card title at line 1023). The fix is to resolve it once, use it twice: once for the title (inside the guard) and once for the capture (outside the guard). To do this, hoist `cmd = args.get("command", "?")` to BEFORE the project guard, at line 1010-1011 (alongside `agent_def = self._agents.get(session_key)` at line 1007 and `agent_name = ...` at line 1008).

```python
# Before line 1014 (the `if self._fh is not None and self._active_project is not None:` block), ADD:
# BUG #15: resolve command string early — needed for both the feed-card title
# and the unconditional _pending_exec_commands capture below.
cmd = args.get("command", "?")
```

Then in the project guard (line 1022-1024), REPLACE `cmd = args.get("command", "?")` with `# (cmd already resolved above for BUG #15)`. The title at line 1023 uses `cmd[:60]` and works unchanged.

The unconditional block at lines 1061-1062 then references `cmd` for the capture:
```python
# In the unconditional block (after line 1061):
self._pending_tool_args[session_key] = args
# BUG #15: capture exec command for command_output callback (works offline)
if name == "exec_command":
    self._pending_exec_commands[session_key] = cmd
```

### 2.2 `tests/test_agent_runtime.py` — three new regression tests

Add to `TestLocalAgentDrawerEmissions` (line 3770). The class already has a `_make_handler_with_agent` helper that sets up a handler with a registered Coder agent and captured bubbles.

**Edit D: test_denied_exec_with_card_still_emits_tool_error (regression for BUG #13, exec_command path)**

```python
def test_denied_exec_with_card_still_emits_tool_error(self):
    """Regression for BUG #13: success param shadowing by feed-card block.

    Real attack: a card was created in _do_tool_call_start, then a denied
    exec_command arrives with a string result and success=False. The
    feed-card block's `success = True` reassignment must not clobber the
    param read by the bubble block.
    """
    from models.feed_card import FeedCardData
    from datetime import datetime, timezone
    handler, _, _ = self._make_handler_with_agent()
    # Prime _tool_card_ids as if _do_tool_call_start had created a card
    card = FeedCardData(
        card_type="agent_action", source="agent",
        title="Coder is running: sudo bash",
        body="Running...", author="Coder",
        timestamp=datetime.now(timezone.utc), project_name="test",
        metadata={"tool_name": "exec_command", "session_key": "special:coder", "status": "running"},
    )
    handler._tool_card_ids["special:coder"] = "card-123"
    handler._fh.get_card.return_value = card

    handler._do_tool_call_result("special:coder", "exec_command",
                                 "exec_command requires PM approval - request denied", False)
    errs = [b for b in self._bubbles if b.type == "tool_error"]
    assert errs, (
        f"BUG #13 regression: expected tool_error bubble, got types "
        f"{[b.type for b in self._bubbles]}"
    )
    assert errs[0].icon == "\u274c"
```

**Edit E: test_write_file_failure_string_result_emits_some_bubble (regression for BUG #13, write_file path)**

```python
def test_write_file_failure_string_result_emits_some_bubble(self):
    """Regression for BUG #13/16: failed write_file with string result.

    The shadowing makes the failure invisible to the drawer. After the
    fix, the failed write_file must emit at least one terminal bubble
    (tool_error, since success=False).
    """
    from models.feed_card import FeedCardData
    from datetime import datetime, timezone
    handler, _, _ = self._make_handler_with_agent()
    card = FeedCardData(
        card_type="agent_action", source="agent",
        title="Coder is writing /etc/passwd",
        body="Running...", author="Coder",
        timestamp=datetime.now(timezone.utc), project_name="test",
        metadata={"tool_name": "write_file", "session_key": "special:coder", "status": "running"},
    )
    handler._tool_card_ids["special:coder"] = "card-123"
    handler._fh.get_card.return_value = card
    handler._pending_tool_args["special:coder"] = {"path": "/etc/passwd"}

    handler._do_tool_call_result("special:coder", "write_file", "permission denied", False)
    # Should emit at least one of: tool_error, tool_end
    endish = [b for b in self._bubbles if b.type in ("tool_error", "tool_end")]
    assert endish, (
        f"BUG #16 regression: failed write_file emitted no terminal bubble, "
        f"got types {[b.type for b in self._bubbles]}"
    )
    errs = [b for b in self._bubbles if b.type == "tool_error"]
    assert errs, "BUG #13: write_file failure should emit tool_error specifically"
```

**Edit F: test_tool_start_after_ended_session_works_for_new_turn (regression for BUG #14)**

```python
def test_tool_start_after_ended_session_works_for_new_turn(self):
    """Regression for BUG #14: _ended_sessions stale flag.

    A previous turn ended (set the flag). A new turn arrives whose first
    signal is _do_tool_call_start (tool-only turn, no streaming text).
    The fresh tool_start must NOT be suppressed.
    """
    handler, _, _ = self._make_handler_with_agent()
    # Simulate prior turn ended
    handler._ended_sessions.add("special:coder")

    # New turn: first call is _do_tool_call_start (no _do_text_delta)
    handler._do_tool_call_start("special:coder", "read_file", {"path": "b.txt"})

    assert len(self._bubbles) >= 1, (
        "BUG #14 regression: legitimate new-turn tool_start was suppressed"
    )
    assert self._bubbles[0].type == "tool_start"
```

**Edit G: test_exec_command_capture_works_without_active_project (regression for BUG #15)**

```python
def test_exec_command_capture_works_without_active_project(self):
    """Regression for BUG #15: _pending_exec_commands capture inside guard.

    BUG #4 fix moved bubbles outside the project guard, but the
    _pending_exec_commands[sk] = cmd capture remained inside. When no
    project is open, the command is lost and command_output callback
    fires with cmd=''.
    """
    handler, _, _ = self._make_handler_with_agent()
    handler._active_project = None  # no project open

    cmd_outputs = []
    handler.set_on_command_output(lambda sk, cmd, tail, ec, dur:
                                  cmd_outputs.append((sk, cmd, tail, ec, dur)))

    # Simulate tool_start + result for an exec_command with no project
    handler._do_tool_call_start("special:coder", "exec_command", {"command": "ls -la"})

    class FakeResult:
        output = "file1\nfile2\nfile3"
        error = ""
        success = True
        exit_code = 0
        duration_ms = 42

    handler._do_tool_call_result("special:coder", "exec_command", FakeResult(), True)

    assert len(cmd_outputs) == 1, "command_output callback should fire"
    assert cmd_outputs[0][1] == "ls -la", (
        f"BUG #15 regression: cmd was lost; got {cmd_outputs[0][1]!r}, expected 'ls -la'"
    )
```

### 2.3 Files NOT changed

- `agent/runtime.py` — already correct (3 dispatch sites pass `success` correctly at lines 2456, 2476, 2557). No changes needed.
- `models/activity.py` — `ActivityBubble` and `ToolStatus` enums unchanged.
- All other handlers, models, utils — no impact from this fix.
- `docs/ARCHITECTURE.md` — PM has queued as separate follow-up (per briefing).

---

## 3. Data Flow

### BUG #13 data flow (current → fixed)

**Current (broken):**
1. Runtime: `tc.mark_failed("exec_command requires PM approval — request denied or timed out")` → `tc.result = "exec_command requires PM approval — ..."` (a string).
2. Runtime: `self._dispatch(self._on_tool_call_result, session_key, "exec_command", tc.result, False)` (line 2456).
3. Handler `_do_tool_call_result`: param `success = False`.
4. Handler enters feed-card block: `card_id = self._tool_card_ids.pop(session_key, None)` → card found.
5. `hasattr(result, 'output')` is False for str → enters else branch: `success = True` (line 1121). **Param clobbered.**
6. Handler reads `card.metadata["status"] = "complete" if success else "error"` → "complete" (wrong, should be "error").
7. Handler exits feed-card block, enters bubble block: `is_error = not success` → `not True` → `False`. (Wrong, should be `True`.)
8. Handler emits `tool_end` bubble with ✅ instead of `tool_error` with ❌.

**Fixed (after Edit A):**
1–4. Same.
5. `hasattr(result, 'output')` is False for str → enters else branch: `card_success = True`. Local renamed; param `success` still `False`.
6. Handler reads `card.metadata["status"] = "complete" if card_success else "error"` → "complete". (Still wrong from the runtime's perspective, but the card display is intentionally optimistic when only a string is available — same as today's behavior. Out of scope for this spec.)
7. Handler exits feed-card block, enters bubble block: `is_error = not success` → `not False` → `True`. (Correct.)
8. Handler emits `tool_error` bubble with ❌. (Correct.)

### BUG #14 data flow (current → fixed)

**Current (broken):**
1. Turn 1: `_do_response_complete` → `_ended_sessions.add(sk)` (line 1454).
2. Turn 2: LLM issues `read_file` directly without streaming text (tool-only turn).
3. `_do_tool_call_start` checks `_ended_sessions` → `True` → early return. **Stale flag suppresses legitimate new-turn tool_start.**

**Fixed (after Edit B):**
1. Same.
2. Same.
3. `_do_tool_call_start` checks `_started_turn_sessions` (new set) → key not present → adds it, discards `_ended_sessions[sk]`. Proceeds.
4. Stale dispatches from a previous turn (still in the idle_add queue) hit the early-return because `_started_turn_sessions` was just cleared by the end site.

### BUG #15 data flow (current → fixed)

**Current (broken):**
1. No project open.
2. Coder issues `exec_command("ls -la")`.
3. `_do_tool_call_start` runs — bubbles fire (BUG #4 fix). `_pending_exec_commands[sk] = cmd` is INSIDE the project guard → not set.
4. `_do_tool_call_result` runs — `cmd = self._pending_exec_commands.pop(sk, "")` → `""`.
5. Drawer row label: empty.

**Fixed (after Edit C):**
1. Same.
2. Same.
3. `_do_tool_call_start` resolves `cmd = "ls -la"` before the project guard. Inside the guard, uses `cmd[:60]` for the title. Outside the guard (in the unconditional block), sets `_pending_exec_commands[sk] = "ls -la"`.
4. Same.
5. Drawer row label: `"ls -la"`.

---

## 4. File Change Summary

| File | Change type | Lines affected | Risk |
|------|-------------|----------------|------|
| `ui/handlers/agent_runtime_handler.py` | Rename local + add discard + move capture | ~10 lines | LOW (3 surgical edits, all in already-touched functions) |
| `tests/test_agent_runtime.py` | 4 new test methods appended to `TestLocalAgentDrawerEmissions` | ~100 lines | LOW (new code, no edits to existing tests) |
| **Total** | | **~110 lines** | |

---

## 5. Implementation Order

1. **Edit A first (BUG #13).** Smallest change (3 lines), highest impact. Run the 4 new regression tests to verify both the rename works and the write_file failure path now emits a terminal bubble.
2. **Edit C next (BUG #15).** Single-line move plus a 2-line hoist. Easy to verify by running the `test_exec_command_capture_works_without_active_project` test.
3. **Edit B last (BUG #14).** Most architecturally invasive (new `_started_turn_sessions` set, edits in 3 sites). Verify the `test_tool_start_after_ended_session_works_for_new_turn` test AND the existing `test_tool_start_suppressed_after_session_ended` test (must still pass — stale dispatch must still be suppressed).
4. **Run the full `TestLocalAgentDrawerEmissions` suite (now 18 tests).** All 18 must pass.
5. **Run the full `tests/test_agent_runtime.py` suite.** All 4000+ tests must pass; in particular, the 14 existing `TestLocalAgentDrawerEmissions` tests must still pass (no regressions to the BUG #1, #2, #4, #5, #12 fixes).
6. **Run `ruff` and `pyright`** on the changed files.

---

## 6. Acceptance Criteria

- [ ] `test_denied_exec_with_card_still_emits_tool_error` passes.
- [ ] `test_write_file_failure_string_result_emits_some_bubble` passes.
- [ ] `test_tool_start_after_ended_session_works_for_new_turn` passes.
- [ ] `test_exec_command_capture_works_without_active_project` passes.
- [ ] All 14 existing `TestLocalAgentDrawerEmissions` tests still pass.
- [ ] All `tests/test_agent_runtime.py` tests pass (full file).
- [ ] `ruff check ui/handlers/agent_runtime_handler.py tests/test_agent_runtime.py` passes.
- [ ] `pyright ui/handlers/agent_runtime_handler.py tests/test_agent_runtime.py` reports 0 errors.
- [ ] No new imports added to `agent_runtime_handler.py`.
- [ ] No edits to `agent/runtime.py` (out of scope per briefing).
- [ ] The 3-line rename in Edit A is the ONLY change in the feed-card block.
- [ ] `_started_turn_sessions` is added in `__init__` AND cleared in BOTH end sites (`_do_response_complete` and `_do_error`).
- [ ] The `cmd` hoist in Edit C happens BEFORE the project guard.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| `result` is a `ToolResult` with `success=True` (normal completion) | Card display "complete", bubble `tool_end` ✅. Edit A: `card_success = result.success = True` matches the param `success = True`. No behavior change. |
| `result` is a `ToolResult` with `success=False` (tool error) | Card display "error", bubble `tool_error` ❌. Edit A: `card_success = result.success = False` matches the param `success = False`. No behavior change. |
| `result` is a string starting with "OK — wrote N bytes to PATH" (write_file success) | Card display "complete", no bubble (write_file tool_end suppressed), patch bubble emitted. Edit A: `card_success = True` matches `success = True`. No behavior change. |
| `result` is a string error message (denied exec, sensitive-path block) | Card display "complete" (optimistic, same as today), bubble `tool_error` ❌. **Edit A FIXES THIS.** |
| `result` is an empty string (rare edge case) | `success = True` in else branch (param unchanged by Edit A). Card display "complete", bubble `tool_end` ✅. Same as today. |
| `_active_project is None` and `exec_command` issued | `_pending_exec_commands[sk] = cmd` set unconditionally. `command_output` callback fires with `cmd`. **Edit C FIXES THIS.** |
| Prior turn ended, new turn with streaming text | `_do_text_delta` discards `_ended_sessions[sk]` at line 973 (existing fix). `_do_tool_call_start` checks `_started_turn_sessions` (Edit B) which is empty → adds it and discards `_ended_sessions[sk]` (idempotent). Stale call suppression preserved. |
| Prior turn ended, new turn tool-only | `_do_text_delta` never fires. `_do_tool_call_start` checks `_started_turn_sessions` (Edit B) which is empty → adds it and discards `_ended_sessions[sk]`. **Edit B FIXES THIS.** |
| Stale `idle_add` dispatch from prior turn arrives AFTER `_do_response_complete` | `_do_response_complete` cleared `_started_turn_sessions[sk]` (Edit B). Stale `_do_tool_call_start` checks `_started_turn_sessions` → not in set → adds it, discards `_ended_sessions[sk]` (idempotent). **Stale call IS now processed, not suppressed.** This is a partial regression of BUG #2 fix. **MUST VERIFY** with the existing `test_tool_start_suppressed_after_session_ended` test. |
| ...continuing the stale-call case | If the implementer's Edit B adds the discard BEFORE the early-return, stale calls are NOT suppressed → BUG #2 regresses. If the implementer uses the `_started_turn_sessions` set, stale calls ARE suppressed because the set was cleared by the end site. **The implementer MUST use the set-based approach.** |

**Critical implementation note for Edit B:** the `_started_turn_sessions` set is REQUIRED. The simpler "just discard always" approach regresses BUG #2. The implementer must add the set, add to it in `_do_tool_call_start`, and clear it in both end sites.

---

## 8. ARCHITECTURE.md Updates Required

None in this spec. PM has the ARCHITECTURE.md update queued as a separate follow-up (per briefing). The fix in this spec does not add new layers, new handlers, or new callbacks — it only corrects existing state-machine logic within the existing `AgentRuntimeHandler` class.

---

## Appendix A — Verification commands (for the implementer)

```bash
# Confirm the param name in the dispatch sites
grep -n "_on_tool_call_result, session_key" agent/runtime.py
# Expected: 3 matches at lines 2456, 2476, 2557, all passing `False` or `result.success`

# Confirm the feed-card block's success reassignment (the bug)
grep -n "success = " ui/handlers/agent_runtime_handler.py
# Expected: only the param default `success: bool = True` (lines 1075, 1098) and the
# two reassignments at lines 1116, 1121 (the bug). After the fix, the two
# reassignments should read `card_success = ...` instead.

# Confirm the bubble block's read of success
grep -n "is_error = not success" ui/handlers/agent_runtime_handler.py
# Expected: 1 match (line 1169) reading the param.

# Confirm _ended_sessions is added in BOTH end sites
grep -n "_ended_sessions.add" ui/handlers/agent_runtime_handler.py
# Expected: 2 matches at lines 1454, 1720.

# Confirm _pending_exec_commands capture
grep -n "_pending_exec_commands" ui/handlers/agent_runtime_handler.py
# Expected: 4 matches after the fix:
#   - 1 declaration in __init__ (line 112)
#   - 1 capture in the unconditional block of _do_tool_call_start (NEW location)
#   - 1 pop in _do_tool_call_result (line 1149)
#   - 0 in the project guard (the fix removed it)

# Run the new tests
python3 -m pytest tests/test_agent_runtime.py::TestLocalAgentDrawerEmissions -v
# Expected: 18 tests pass (14 existing + 4 new).

# Run the full file
python3 -m pytest tests/test_agent_runtime.py -q
# Expected: 4000+ tests pass.

# Lint and type-check
ruff check ui/handlers/agent_runtime_handler.py tests/test_agent_runtime.py
pyright ui/handlers/agent_runtime_handler.py tests/test_agent_runtime.py
```

---

## Appendix B — File-existence check (Rule 1)

Before any edit, the implementer MUST:
```bash
git log -1 --oneline ui/handlers/agent_runtime_handler.py
git log -1 --oneline tests/test_agent_runtime.py
# Confirm the current branch has the SPEC-ACTIVITY-DRAWER-BUGFIXES commits
# (the BUG #1, #2, #4, #5, #12 fixes). The re-audit fixes are stacked on top.
```

---

## Appendix C — Architecture compliance check

- [ ] No new imports in `agent_runtime_handler.py` (still only stdlib + `models.feed_card` + relative imports).
- [ ] No imports from `gateway/` or `models/` (per ARCHITECTURE.md §2). `models.feed_card` is already imported at line 18.
- [ ] No handler-to-handler imports (per §8.6 R2). `_started_turn_sessions` is a state attribute on the same class, not a handler reference.
- [ ] All callback signatures unchanged (no setter changes).
- [ ] No new CSS classes.
- [ ] No new files.
- [ ] No new tests outside `tests/test_agent_runtime.py`.
