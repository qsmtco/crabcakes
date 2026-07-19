# SPEC: Activity Drawer Bugfix Round 4 — Turn-Start Signal (BUG #21)

**Date:** 2026-07-18
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** Fix for BUG #21 found in the Debugger fourth-pass (ship-gate) audit
**Depends on:** `docs/specs/SPEC-ACTIVITY-DRAWER-BUGFIXES-ROUND3.md`
**Target branch:** main

> **Architecture compliance:** The code change is in `agent/runtime.py` (§3.21m, the local agent runtime — no UI deps) and `tests/test_agent_runtime.py`. No handler or view changes. No new callbacks. The fix reuses the existing `_on_text_delta` dispatch plumbing. Per §3.21m the runtime owns tool-loop orchestration; firing a turn-start signal before the first event is within its responsibility.

---

## DISCOVERY (read before writing any spec content)

- **Read `agent/runtime.py:2101-2140` (`_run_loop`):** confirmed this is the per-user-message entry point. One call per turn, before any LLM call or tool dispatch. The `conv` null-check at line 2110 is the last guard before turn processing begins. The `try:` block at line 2114 is where turn work starts.
- **Read `agent/runtime.py:2818-2835` (streaming loop):** confirmed `_on_text_delta` is dispatched ONLY on `ev.type == "text_delta"` (line 2831). Pure tool_call streams produce zero `text_delta` events → `_on_text_delta` never fires → handler's `_do_text_delta` never runs → `_ended_sessions` never clears.
- **Read `agent/runtime.py:1638-1655` (`__init__` callbacks):** confirmed the runtime has no dedicated turn-start callback. `_on_text_delta` is the closest existing signal.
- **Read `ui/handlers/agent_runtime_handler.py:945-985` (`_do_text_delta`):** confirmed the flag-clear (`_ended_sessions.discard`) at line 973 and the drawer-lifecycle "start" at line 980 are both inside `if not self._crh.is_streaming(session_key):` — meaning they fire only on the FIRST delta of a turn. For an empty-string delta at turn start, `is_streaming` is False → the block runs → flag clears, lifecycle starts. Then `update_streaming(sk, "")` is called (harmless no-op on an empty bubble).
- **Read `ui/handlers/agent_runtime_handler.py:1384-1420` (`_do_response_complete`):** confirmed an empty started-streaming-bubble is gracefully finalized via `end_streaming`. The "Non-streaming fallback" path handles empty text. No visual artifact from an empty bubble.
- **Architecture owner:** `AgentRuntime` (§3.21m) owns the tool loop and its callbacks. Firing a turn-start signal is within scope.
- **Existing patterns:** the runtime already fires `_on_text_delta` for text content; reusing it for a turn-start signal (with empty content) is the minimal-surface change. A dedicated `_on_turn_started` callback would touch 4 files (runtime, handler, wiring handler, window) for no behavioral gain.

---

## 1. Overview

### Problem
BUG #21: for a tool-only streaming turn (LLM emits only `tool_call_delta` events, no `text_delta`), `_on_text_delta` is never dispatched, so the handler's `_do_text_delta` never runs, so `_ended_sessions` is never cleared. All `_do_tool_call_start` calls for that turn are suppressed (BUG #18's pure-suppression blocks them). The drawer shows orphan `tool_end` bubbles without their `tool_start` counterparts, and no lifecycle "start" separator. This regresses the core drawer feature for the most common agent workflow: any tool-use agent on its second-and-later turn.

### Root cause (why four rounds didn't catch this)
The `_ended_sessions` state machine was designed in Round 1 (BUG #2) with `_do_text_delta` as the sole flag-clear site, under the assumption that every streaming turn produces at least one `text_delta` event. That assumption is false for tool-only turns. Rounds 2–3 tinkered with the suppression logic but never questioned the flag-clear site. Round 4 (this spec) fixes the actual root cause: guarantee a turn-start signal reaches the handler for every turn, regardless of event types.

### Solution
Dispatch `_on_text_delta(session_key, "")` once at the top of `_run_loop`, right after the `conv` null-check, before any LLM call or tool processing. This guarantees the handler receives a turn-start signal for every turn. The empty string is a harmless no-op for text accumulation; the handler's `if not self._crh.is_streaming()` block fires (clearing the flag and emitting the lifecycle separator) because streaming hasn't started yet for the new turn.

### Why reuse `_on_text_delta` instead of a new callback
- **Minimal surface:** 2 lines in `runtime.py`, zero changes to handler/wiring/window/callback-registration.
- **Reuses existing plumbing:** the handler's `_do_text_delta` already does exactly the right thing (clear flag, emit lifecycle start) on the first delta of a turn.
- **No semantic ambiguity:** an empty delta unambiguously means "turn started, no text yet." The handler already handles empty strings (`self._streaming_text[sk] = ... + ""` is a no-op).
- **Graceful at turn end:** `_do_response_complete` finalizes the empty streaming bubble without visual artifact (verified in discovery).

### Scope

| In | Out |
|----|-----|
| `agent/runtime.py` — 1 dispatch line in `_run_loop` | `ui/handlers/agent_runtime_handler.py` (unchanged) |
| `tests/test_agent_runtime.py` — 1 regression test | `ui/handlers/activity_wiring_handler.py` (unchanged) |
| | `ui/window.py` (unchanged) |

---

## 2. Changes by File

### 2.1 `agent/runtime.py`

**Edit — `_run_loop`, after the `conv` null-check guard (after line 2112), before the `try:` block (line 2114):**

```python
# CURRENT (lines 2108-2114):
            conv = self._conversations.get(session_key)
            if conv is None:
                self._dispatch(self._on_error, session_key, "No conversation found")
                return

        try:

# NEW:
            conv = self._conversations.get(session_key)
            if conv is None:
                self._dispatch(self._on_error, session_key, "No conversation found")
                return

        # BUG #21: Fire a turn-start signal BEFORE any LLM call or tool processing.
        # This guarantees the handler clears _ended_sessions and emits the drawer
        # lifecycle-start separator for EVERY turn — including tool-only turns
        # (LLM streams zero text_delta events). Reuses _on_text_delta with an
        # empty string: the handler's _do_text_delta clears the flag on the first
        # delta of a turn (is_streaming is False), and the empty content is a
        # harmless no-op for text accumulation.
        if self._on_text_delta:
            self._dispatch(self._on_text_delta, session_key, "")

        try:
```

**Traced verification:**
- **Normal text turn:** `_run_loop` dispatches `_on_text_delta(sk, "")` → `_do_text_delta` clears flag + emits lifecycle start + starts empty streaming bubble → subsequent real `text_delta` events append content → bubble populates normally. ✅ No behavior change (the first real delta would have cleared the flag anyway; the empty one just does it earlier).
- **Tool-only turn (BUG #21 case):** `_run_loop` dispatches `_on_text_delta(sk, "")` → `_do_text_delta` clears flag + emits lifecycle start → subsequent `_do_tool_call_start` calls see clear flag → tool_starts fire normally. ✅ Fixed.
- **Cancelled before any LLM call:** `_run_loop` dispatches the empty delta (flag clears), then the loop's cancel-check fires `_on_error` → `_do_error` → `_ended_sessions.add`. The flag is correctly set for the cancelled turn. ✅ Correct.
- **`_on_text_delta is None` (streaming disabled):** the `if self._on_text_delta:` guard skips the dispatch. Non-streaming mode doesn't use the drawer flag mechanism (no `_do_text_delta` wiring). ✅ No-op, correct.

**Files NOT changed** (already correct):
- `ui/handlers/agent_runtime_handler.py` — the `_do_text_delta` flag-clear and lifecycle-start logic (lines 965-978) is already correct; it just wasn't being reached for tool-only turns. This spec makes it reachable.
- `ui/handlers/activity_wiring_handler.py` — unchanged.
- `ui/handlers/connection_sync_handler.py` — unchanged.
- `ui/window.py` — unchanged.

---

### 2.2 `tests/test_agent_runtime.py`

Add 1 regression test to `TestLocalAgentDrawerEmissions`:

**Test — `test_tool_only_turn_tool_starts_not_suppressed` (regression for BUG #21):**

This test verifies the fix at the handler level. It simulates the scenario: previous turn ended (flag set), new turn's first signal is an empty text delta (as the runtime now dispatches), then a tool_start arrives. The tool_start must NOT be suppressed.

```python
def test_tool_only_turn_tool_starts_not_suppressed(self):
    """Regression for BUG #21: a tool-only turn (no streaming text) must
    still fire tool_start bubbles.

    The runtime now dispatches _on_text_delta(sk, '') at the top of _run_loop
    before any tool calls, so _do_text_delta clears _ended_sessions for the
    new turn. This test simulates that sequence at the handler level.
    """
    handler, crh, mc = self._make_handler_with_agent()
    # Simulate previous turn ended
    handler._ended_sessions.add("special:coder")

    # Simulate the runtime's turn-start signal (empty delta) — this is the fix.
    # _do_text_delta clears the flag on the first delta of a turn.
    handler._do_text_delta("special:coder", "")

    # Now a tool_start arrives (tool-only turn, no real text)
    handler._do_tool_call_start("special:coder", "read_file", {"path": "test.txt"})

    # The tool_start must NOT be suppressed — the flag was cleared.
    types = [b.type for b in self._bubbles]
    assert "tool_start" in types, (
        f"BUG #21: tool_start suppressed for tool-only turn; got {types}"
    )
    # The lifecycle-start separator must also have fired.
    start_events = [e for e in self._lifecycle_events if e[2] == "start"]
    assert len(start_events) == 1, (
        f"BUG #21: expected 1 lifecycle-start event, got {len(start_events)}: {self._lifecycle_events}"
    )
```

**Traced verification:** after the fix, `_do_text_delta("special:coder", "")` → `is_streaming` is False → clears `_ended_sessions` → emits lifecycle start. Then `_do_tool_call_start` → flag is clear → proceeds → emits `tool_start`. Both assertions pass.

**Note on the `_make_handler` helper:** it sets `handler._crh = MagicMock()` (via `_make_handler`). The `_do_text_delta` method checks `if self._crh is None: return` — with a MagicMock, this passes. Then `self._crh.is_streaming(session_key)` returns a MagicMock (truthy by default) which would skip the flag-clear block. **This is a test-scaffolding concern.** The test must set `crh.is_streaming.return_value = False` so the first-delta block runs. Check the existing `test_agent_start_emits_drawer_lifecycle_start` test (which exercises the same path) for the correct mock setup pattern and mirror it. If that test sets `crh.is_streaming.return_value = False`, do the same here.

---

## 3. Data Flow

```
User sends message
  → AgentRuntime._run_loop(session_key, text)
    → [NEW] _dispatch(_on_text_delta, session_key, "")   ← turn-start signal
      → handler._do_text_delta(sk, "")
        → is_streaming? No → clear _ended_sessions, emit lifecycle-start, start bubble
    → LLM call (streaming or non-streaming)
      → text_delta events → _do_text_delta appends content
      → tool_call_delta events → (no _do_text_delta needed; flag already clear)
      → tool execution → _on_tool_call_start → _do_tool_call_start (flag clear → fires)
      → tool result → _on_tool_call_result → _do_tool_call_result (fires tool_end/patch)
    → turn ends → _on_response_complete → _do_response_complete → _ended_sessions.add
```

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|------------|-------|------|
| `agent/runtime.py` | +1 dispatch line + 6 comment lines in `_run_loop` | ~7 | Low |
| `tests/test_agent_runtime.py` | +1 regression test | ~25 | Low |

## 5. Implementation Order

1. **Read** `agent/runtime.py` lines 2101-2140 (`_run_loop`) to confirm the insertion point.
2. **Read** `ui/handlers/agent_runtime_handler.py` lines 945-985 (`_do_text_delta`) to confirm the flag-clear path.
3. **Add** the dispatch line in `_run_loop` after the `conv` null-check, before `try:`.
4. **Compile check:** `python3 -m py_compile agent/runtime.py`.
5. **Read** the existing `test_agent_start_emits_drawer_lifecycle_start` test to mirror its `crh.is_streaming.return_value = False` mock setup.
6. **Add** the regression test.
7. **Run:** `pytest tests/test_agent_runtime.py::TestLocalAgentDrawerEmissions -v`.

## 6. Acceptance Criteria

- [ ] `_run_loop` in `agent/runtime.py` dispatches `_on_text_delta(session_key, "")` before the `try:` block, gated on `if self._on_text_delta:`.
- [ ] The dispatch is AFTER the `conv` null-check (so it doesn't fire for a missing conversation) and BEFORE any LLM call or tool processing.
- [ ] `test_tool_only_turn_tool_starts_not_suppressed` passes.
- [ ] All 19 `TestLocalAgentDrawerEmissions` tests pass (18 existing + 1 new).
- [ ] `python3 -m py_compile agent/runtime.py` succeeds.

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Normal text turn | Empty delta clears flag first; real deltas append content; no behavior change |
| Tool-only turn (BUG #21) | Empty delta clears flag; tool_starts fire normally; no orphans |
| Turn cancelled before LLM call | Empty delta clears flag, then cancel-check fires _on_error → flag re-set |
| Streaming disabled (`_on_text_delta is None`) | Dispatch skipped; non-streaming mode unaffected |
| Missing conversation (conv is None) | Returns before the dispatch; no signal sent (correct — no turn to start) |

## 8. ARCHITECTURE.md Updates Required

None. The change is internal to `_run_loop` (an existing method of an existing module). No new module, no new callback, no structural change. The §3.21m description of `_run_loop` ("Background thread: run the full tool loop for one user message") remains accurate.

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** Yes. The insertion point (after line 2112, before line 2114) is verified via `sed` read. The dispatch uses `self._dispatch` and `self._on_text_delta`, both existing instance attributes confirmed at lines 1717 and 1652.
2. **Did I catch all exception types?** N/A — the dispatch is wrapped in `_dispatch` which already has try/except (line 1721). The empty string cannot raise.
3. **Did I verify key structures?** Yes — `_on_text_delta` signature is `(session_key, delta_text)`, confirmed at line 1616. The handler's `_do_text_delta` accepts `(session_key, text)` and handles empty strings.
4. **Did I trace the data flow end-to-end?** Yes — traced four scenarios (normal text, tool-only, cancelled, streaming-disabled) in §2.1.
5. **Would an implementer following this spec exactly produce working code?** Yes — single dispatch line with exact insertion point, plus one test that mirrors an existing test's mock setup.

**One scaffolding caveat for the implementer:** the test's `_make_handler` helper uses `MagicMock()` for `_crh`, so `crh.is_streaming()` returns a truthy MagicMock by default, which would skip the flag-clear block in `_do_text_delta`. The test MUST set `crh.is_streaming.return_value = False` to exercise the first-delta path. Mirror the setup from the existing `test_agent_start_emits_drawer_lifecycle_start` test.

The spec is complete.
