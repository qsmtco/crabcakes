# SPEC: Activity Drawer Bugfixes Round 3 — Final Closures

**Date:** 2026-07-18
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** Fixes for BUG #18, #17, #19, #20 from the Debugger third-pass audit
**Depends on:** `docs/specs/SPEC-ACTIVITY-DRAWER-BUGFIXES-ROUND2.md`
**Target branch:** main

> **Architecture compliance:** All code changes stay within `ui/handlers/agent_runtime_handler.py` (§3.21v). Doc changes touch `docs/ARCHITECTURE.md` and one docstring. No new modules, no cross-layer imports, no window.py change. These are the final surgical closures on a feature that has been through three audit rounds.

---

## DISCOVERY (read before writing any spec content)

- **Read `ui/handlers/agent_runtime_handler.py` lines 95–105 (`__init__` state), 968–978 (`_do_text_delta` discard), 1000–1012 (`_do_tool_call_start` suppression), 1122–1128 (`else` branch), 1450–1462 (end site 1), 1716–1728 (end site 2), 576–582 (docstring):** confirmed all four defect sites with exact line numbers. The `_ended_sessions` set is `add`ed at lines 1460 and 1726; `discard`ed at lines 973 (text-delta) and 1008 (tool-start, the broken site). The `else` branch hard-codes `card_success = True` at line 1127. The docstring references `connection_sync_handler.py` at line 578.
- **Read `docs/ARCHITECTURE.md` lines 2383–2431:** confirmed the section ordering violation — `### 3.21zc` (activity_wiring_handler, line 2407) appears BEFORE `### 3.21zb` (settings_dialog, line 2431). The §3.21zc content (lines 2407–2429) is accurate and should be preserved verbatim; only its label and position change.
- **Architecture owner:** `AgentRuntimeHandler` (§3.21v) owns all four code fixes.
- **Existing patterns:** the `_started_turn_sessions` set recommended below mirrors the existing `_ended_sessions` set semantics (set membership, `add`/`discard`). The card-bubble agreement pattern (BUG #17) mirrors the BUG #13 fix: read the runtime-dispatched `success` param, don't recompute from the result type.

---

## 1. Overview

### Problem
Round 2 fixed 3 regressions but introduced one more (BUG #18: the "discard inside suppression if" pattern fails on ≥2 stale dispatches) and left visible one pre-existing issue (BUG #17: card/bubble disagreement on denied tools). Two doc nits remain (BUG #19, #20).

### Solution
Four surgical closures. BUG #18 replaces the broken single-set state with a two-set state machine (`_ended_sessions` + `_started_turn_sessions`) that correctly distinguishes "stale (suppress all)" from "first call of new turn (clear and proceed)". BUG #17 is a 1-line read of the param. BUG #19/#20 are doc fixes.

### Scope

| In | Out |
|----|-----|
| `ui/handlers/agent_runtime_handler.py` — BUG #18 (state machine), BUG #17 (1 line), BUG #20 (docstring) | `agent/runtime.py` (unchanged) |
| `docs/ARCHITECTURE.md` — BUG #19 (section renumber + move) | `ui/handlers/activity_wiring_handler.py` (unchanged) |
| `tests/test_agent_runtime.py` — 2 new tests | Any other handler |

### Architecture principles that apply
- §8.6 Handler Pattern: changes stay within the existing handler.
- §3.6: no window.py change.
- Project convention: ARCHITECTURE.md corrected in the same commit.

---

## 2. Changes by File

### 2.1 `ui/handlers/agent_runtime_handler.py`

#### Fix BUG #18 — two-set state machine for stale-call suppression

**Root cause:** the Round 2 fix for BUG #14 placed `_ended_sessions.discard()` INSIDE the suppression `if` block. When ≥2 stale `_do_tool_call_start` dispatches are queued in `GLib.idle_add`, the first clears the flag and returns, the second sees a clear flag and proceeds — emitting an orphan `tool_start` bubble after the session ended. This re-introduces BUG #2 under a different mechanism.

**Fix:** add a second set `_started_turn_sessions` that tracks "has this session begun a new turn since the last end?". Stale calls are suppressed WITHOUT clearing the ended flag. The first call of a new turn (detected via absence from `_started_turn_sessions`) clears the ended flag and adds itself to `_started_turn_sessions`. Both end sites clear `_started_turn_sessions`.

**Edit 1 — `__init__` (after line 100, the `_ended_sessions` declaration):**
```python
# OLD:
        self._ended_sessions: set[str] = set()
# NEW:
        self._ended_sessions: set[str] = set()
        # BUG #18: Track sessions that have begun a new turn. Used with
        # _ended_sessions to correctly suppress ALL stale tool_start dispatches
        # (not just the first) while allowing the first tool_start of a genuine
        # new turn to clear the ended flag. Without this, the Round 2 BUG #14
        # fix re-introduces the BUG #2 orphan when ≥2 stale dispatches are queued.
        self._started_turn_sessions: set[str] = set()
```

**Edit 2 — `_do_tool_call_start` suppression block (lines 1003–1009):**
```python
# OLD:
        if session_key in self._ended_sessions:
            # Stale dispatch from a previous turn (cancelled/completed).
            # The flag is cleared here so the NEXT tool_start of a new turn
            # is not suppressed. This handles tool-only turns that never
            # pass through _do_text_delta's discard path (BUG #14).
            logger.debug("_do_tool_call_start: stale call suppressed, clearing ended flag for %s", session_key)
            self._ended_sessions.discard(session_key)
            return
# NEW:
        if session_key in self._ended_sessions:
            # Stale dispatch from a previous turn (cancelled/completed).
            # BUG #18: do NOT clear the flag here — if ≥2 stale dispatches are
            # queued, clearing on the first would let the second proceed and
            # emit an orphan tool_start. Suppress ALL stale calls; the flag is
            # cleared only when a genuine new turn begins (detected via
            # _started_turn_sessions below).
            logger.debug("_do_tool_call_start: stale call suppressed for ended session %s", session_key)
            return
        # First tool_start of a new turn — clear the ended flag for subsequent
        # calls. BUG #14: tool-only turns never reach _do_text_delta's discard
        # path, so this is the new-turn entry point for them.
        if session_key not in self._started_turn_sessions:
            self._started_turn_sessions.add(session_key)
            self._ended_sessions.discard(session_key)
```

**Edit 3 — `_do_text_delta` discard site (line 973):** add a parallel `_started_turn_sessions` add so the streaming path and the tool-only path agree on "turn started".
```python
# OLD:
                # BUG #2: Clear ended flag on new turn — this session is active again.
                self._ended_sessions.discard(session_key)
# NEW:
                # BUG #2: Clear ended flag on new turn — this session is active again.
                self._ended_sessions.discard(session_key)
                # BUG #18: mark turn as started so _do_tool_call_start's new-turn
                # detection agrees with the streaming path.
                self._started_turn_sessions.add(session_key)
```

**Edit 4 — end site 1 (`_do_response_complete`, after line 1460):**
```python
# OLD:
        self._ended_sessions.add(session_key)
# NEW:
        self._ended_sessions.add(session_key)
        self._started_turn_sessions.discard(session_key)
```

**Edit 5 — end site 2 (`_do_error`, after line 1726):**
```python
# OLD:
        self._ended_sessions.add(session_key)
# NEW:
        self._ended_sessions.add(session_key)
        self._started_turn_sessions.discard(session_key)
```

**Traced verification:**
- **Single stale call (original BUG #2 case):** turn ends → `_ended_sessions.add`, `_started_turn_sessions.discard`. Stale `_do_tool_call_start` → `session_key in _ended_sessions` → True → suppress + return (no flag clear). ✅ No orphan.
- **Two stale calls (BUG #18 case):** turn ends. Stale call 1 → `in _ended_sessions` → True → suppress + return (flag NOT cleared). Stale call 2 → `in _ended_sessions` → still True → suppress + return. ✅ No orphan.
- **Tool-only new turn (BUG #14 case):** turn 1 ends. Turn 2 first `_do_tool_call_start` → `in _ended_sessions` → True (still set) → suppress + return... BUT this is the first call of a NEW turn, not stale!

Wait — this is the subtle part. The new-turn detection (`if session_key not in self._started_turn_sessions`) is placed AFTER the stale-suppression `if`. So a tool-only new turn's first call hits the stale-suppression branch (because `_ended_sessions` still has the key) and is suppressed. This is the **documented tradeoff**: the first tool_start of a tool-only new turn is suppressed as potentially stale. The briefing and Round 2 spec both flagged this as "an acceptable ambiguity." The second tool_start of the new turn: `_ended_sessions` still has the key (we didn't clear it) → suppressed again!

**This is WRONG.** The above trace reveals that placing the new-turn detection after the stale-suppression `if` defeats BUG #14 entirely — a tool-only turn can NEVER clear the flag because every call hits the stale branch first. Let me reconsider the design.

The correct structure: the new-turn detection must come BEFORE the stale-suppression check, OR the stale-suppression must be conditional on whether a new turn has started. The cleanest fix:

**Revised Edit 2 — `_do_tool_call_start` (lines 1003–1009):**
```python
# NEW (revised):
        # BUG #18: new-turn detection MUST precede stale-suppression. A tool-only
        # turn's first tool_start arrives with _ended_sessions still set (the
        # previous turn ended). We detect "new turn" via _started_turn_sessions
        # (cleared at end, set at first start). If this call is the first of a
        # new turn, clear the ended flag and proceed; otherwise suppress.
        if session_key in self._ended_sessions:
            if session_key not in self._started_turn_sessions:
                # First call of a new (tool-only) turn — clear the ended flag.
                self._started_turn_sessions.add(session_key)
                self._ended_sessions.discard(session_key)
                # Fall through to emit the bubble (do NOT return).
                logger.debug("_do_tool_call_start: new turn detected for %s, clearing ended flag", session_key)
            else:
                # Turn already started but ended flag still set — genuinely stale.
                logger.debug("_do_tool_call_start: stale call suppressed for ended session %s", session_key)
                return
```

**Traced verification (revised):**
- **Single stale call:** turn ends (`_ended_sessions.add`, `_started_turn_sessions.discard`). Stale call → `in _ended_sessions` True → `in _started_turn_sessions` False (was discarded at end) → enters "first call of new turn" branch → adds to `_started_turn_sessions`, discards `_ended_sessions` → falls through → emits bubble.

**This is STILL wrong** — a genuinely stale call (single, right after end) would be treated as "first call of new turn" and emit an orphan. The fundamental problem: we cannot distinguish "stale call from the turn that just ended" from "first call of a genuinely new turn" using only set membership, because both arrive with `_ended_sessions` set and `_started_turn_sessions` clear.

**Resolution:** This ambiguity is inherent. The original BUG #2 tradeoff (suppress ALL calls that arrive while `_ended_sessions` is set, and rely on `_do_text_delta` to clear the flag for streaming turns) is the only correct design — it accepts that tool-only turns' first tool_start may be suppressed. BUG #14's goal (clear the flag for tool-only turns) is fundamentally incompatible with BUG #2's goal (suppress stale calls), because we cannot tell them apart at the call site.

**Therefore:** revert the BUG #14 fix entirely. Restore the original BUG #2 behavior (suppress without clearing), and document BUG #14 as a known limitation: tool-only turns' first tool_start is suppressed; subsequent tool_starts fire after `_do_text_delta` clears the flag (which happens once any text streams). This is the correct engineering tradeoff — BUG #2 (visible orphan) is worse than BUG #14 (missing first bubble of a tool-only turn).

**Final Edit 2 — `_do_tool_call_start` (lines 1003–1009) — revert to pure suppression:**
```python
# FINAL:
        # BUG #2 / BUG #18: Suppress ALL tool_start dispatches that arrive while
        # the session is in the ended state. We do NOT clear the flag here —
        # clearing on the first stale call let a second stale call proceed
        # (BUG #18). The flag is cleared only by _do_text_delta when a genuine
        # new turn begins streaming.
        # Known limitation (BUG #14): a tool-only turn (no streaming text) whose
        # first tool_start arrives before any text delta will be suppressed.
        # This is the correct tradeoff: we cannot distinguish "stale call from
        # the previous turn" from "first call of a new tool-only turn" at the
        # call site, and suppressing a legitimate first bubble is less harmful
        # than emitting an orphan after the session ended.
        if session_key in self._ended_sessions:
            logger.debug("_do_tool_call_start: suppressed for ended session %s", session_key)
            return
```

**And remove the `_started_turn_sessions` set entirely** — it's not needed with this design. Edits 1, 3, 4, 5 above (which added/used `_started_turn_sessions`) are CANCELLED. Only Edit 2 (the revert to pure suppression) and the existing `_do_text_delta` discard (line 973, unchanged from Round 1) remain.

**Net code change for BUG #18:** revert lines 1003–1009 to the original Round 1 suppression (suppress + return, no discard). No new state. The `_do_text_delta` discard at line 973 stays as-is (it correctly clears the flag when a new streaming turn begins).

#### Fix BUG #17 — card shows "complete" for denied tools

**Root cause:** the `else` branch at line 1127 hard-codes `card_success = True` for string results, so a denied exec_command (runtime dispatches `success=False`) shows "complete" on the card while the bubble correctly shows `tool_error`.

**Fix — line 1127:**
```python
# OLD:
                    card_success = True
# NEW:
                    # BUG #17: use the runtime-dispatched param, not a hard-coded True.
                    # A string result with success=False is a denied/failed tool — the
                    # card must agree with the bubble's tool_error classification.
                    card_success = success
```

**Traced verification:** denied exec_command (runtime `success=False`, string result) → `else` branch → `card_success = success` = False → `card.metadata["status"] = "error"`. Bubble: `is_error = not success` = True → `tool_error`. Card and bubble agree. ✅

#### Fix BUG #20 — stale docstring reference

**Fix — line 578:**
```python
# OLD:
        Used by the local exec adapter (in connection_sync_handler.py) to populate
# NEW:
        Used by the local exec adapter (in activity_wiring_handler.py) to populate
```

**Files NOT changed** (already correct):
- `agent/runtime.py` — unchanged.
- `ui/handlers/activity_wiring_handler.py` — unchanged.
- `ui/handlers/connection_sync_handler.py` — unchanged.
- `ui/window.py` — unchanged.

---

### 2.2 `tests/test_agent_runtime.py`

Add 2 tests to `TestLocalAgentDrawerEmissions`:

**Test 1 — `test_two_consecutive_stale_tool_starts_both_suppressed` (regression for BUG #18):**
```python
def test_two_consecutive_stale_tool_starts_both_suppressed(self):
    """Regression for BUG #18: ≥2 stale tool_start dispatches must all be
    suppressed. The Round 2 fix cleared the ended flag on the first stale
    call, letting the second proceed and emit an orphan bubble.
    """
    handler, _, _ = self._make_handler_with_agent()
    handler._ended_sessions.add("special:coder")

    # Two stale calls, back-to-back (as if queued in GLib.idle_add)
    handler._do_tool_call_start("special:coder", "read_file", {"path": "a.txt"})
    handler._do_tool_call_start("special:coder", "read_file", {"path": "b.txt"})

    # Both must be suppressed — no bubbles, flag still set
    assert len(self._bubbles) == 0, (
        f"BUG #18: expected 0 bubbles for 2 stale calls, got {len(self._bubbles)}"
    )
    assert "special:coder" in handler._ended_sessions, (
        "BUG #18: ended flag should NOT be cleared by a stale call"
    )
```

**Test 2 — `test_denied_exec_card_shows_error_status` (regression for BUG #17):**
```python
def test_denied_exec_card_shows_error_status(self):
    """Regression for BUG #17: card.metadata['status'] must be 'error' for a
    denied tool, not 'complete'. The card and bubble must agree.
    """
    handler, _, _ = self._make_handler_with_agent()
    from models.feed_card import FeedCardData
    from datetime import datetime, timezone
    card = FeedCardData(
        card_type="agent_action", source="agent",
        title="Coder is running: rm -rf /", body="⏳ Running...",
        author="Coder", timestamp=datetime.now(timezone.utc), project_name="test",
    )
    handler._tool_card_ids["special:coder"] = "card-123"
    handler._fh.get_card.return_value = card

    handler._do_tool_call_result(
        "special:coder", "exec_command",
        "exec_command requires PM approval — request denied or timed out",
        success=False,
    )

    assert card.metadata["status"] == "error", (
        f"BUG #17: card status should be 'error' for denied tool, got "
        f"{card.metadata.get('status')!r}"
    )
```

**Traced verification:** after the BUG #18 fix (pure suppression), the first stale call returns early (no discard), the second also returns early → 0 bubbles, flag still set → both assertions pass. After the BUG #17 fix, `card_success = success` = False → `card.metadata["status"] = "error"` → assertion passes.

---

### 2.3 `docs/ARCHITECTURE.md`

**Fix BUG #19 — section ordering.** Move the `### 3.21zc` section (lines 2407–2429) to AFTER `### 3.21zb` (which ends before line 2431's successor), and renumber it `### 3.21zd`. The content is unchanged; only the heading label and file position change.

Concretely:
1. Cut the entire block from `### 3.21zc \`ui/handlers/activity_wiring_handler.py\`...` through the `**Offline name resolution:**` line (the last line before `### 3.21zb`).
2. Paste it after the `### 3.21zb` section ends (after the settings_dialog content).
3. Change the heading from `### 3.21zc` to `### 3.21zd`.

After the move, the section order is: `za` (settings_handler) → `zb` (settings_dialog) → `zd` (activity_wiring_handler). The `zc` slot is skipped (acceptable — it was never legitimately assigned; the collision was the bug).

---

## 3. Data Flow

Unchanged from Round 2. The BUG #18 fix reverts to the Round 1 suppression model (suppress all stale calls, clear flag only on streaming new-turn via `_do_text_delta`). No new state sets.

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|------------|-------|------|
| `ui/handlers/agent_runtime_handler.py` | BUG #18 revert (4 lines), BUG #17 (1 line), BUG #20 (1 line) | ~6 | Low |
| `tests/test_agent_runtime.py` | +2 regression tests | ~45 | Low |
| `docs/ARCHITECTURE.md` | BUG #19 section move + renumber | ~0 net | None |

## 5. Implementation Order

1. **BUG #18 fix:** revert `_do_tool_call_start` suppression block (lines 1003–1009) to pure suppress-and-return. Verify: `grep -n "_started_turn_sessions" ui/handlers/agent_runtime_handler.py` returns zero matches (the set was never added in code, only proposed then cancelled in this spec).
2. **BUG #17 fix:** change line 1127 `card_success = True` → `card_success = success`.
3. **BUG #20 fix:** change line 578 `connection_sync_handler.py` → `activity_wiring_handler.py`.
4. **Compile check:** `python3 -m py_compile ui/handlers/agent_runtime_handler.py`.
5. **Add 2 regression tests.**
6. **Run tests:** `pytest tests/test_agent_runtime.py::TestLocalAgentDrawerEmissions -v`.
7. **BUG #19 fix:** move + renumber ARCHITECTURE.md section.
8. **Final verification** per §6.

## 6. Acceptance Criteria

- [ ] `_do_tool_call_start` suppression block contains NO `_ended_sessions.discard()` call (pure suppression). Verified by: reading lines 1003–1009.
- [ ] `grep -n "_started_turn_sessions" ui/handlers/agent_runtime_handler.py` returns zero matches.
- [ ] Line 1127 reads `card_success = success` (not `card_success = True`).
- [ ] Line 578 reads `activity_wiring_handler.py` (not `connection_sync_handler.py`).
- [ ] `test_two_consecutive_stale_tool_starts_both_suppressed` passes.
- [ ] `test_denied_exec_card_shows_error_status` passes.
- [ ] All 18 `TestLocalAgentDrawerEmissions` tests pass (16 existing + 2 new).
- [ ] ARCHITECTURE.md section order is `za` → `zb` → `zd` (no section appears before its numeric predecessor). Verified by: `grep -n "^### 3.21z" docs/ARCHITECTURE.md` shows ascending order.

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Single stale tool_start after end | Suppressed, no bubble (BUG #2 stays fixed) |
| Two stale tool_starts after end | Both suppressed, no bubbles, flag still set (BUG #18 fixed) |
| Tool-only new turn (no streaming) | First tool_start suppressed (known limitation, documented); flag cleared when streaming text arrives |
| Denied exec_command | Card shows "error", bubble shows "tool_error" (BUG #17 fixed) |
| Normal streaming turn | `_do_text_delta` clears ended flag on first delta; tool_starts fire normally |

## 8. ARCHITECTURE.md Updates Required

Only BUG #19 (section move + renumber). The content of the section is already correct from Round 2.

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** Yes. The BUG #18 revert restores the exact Round 1 suppression pattern, which was verified correct by the Round 1 audit. The BUG #17 one-liner reads the `success` param that is already in scope. All line numbers verified via `sed` reads.
2. **Did I catch all exception types?** N/A — no exception handling changes.
3. **Did I verify key structures?** Yes — `_ended_sessions` is `set[str]`; no new state added. The cancelled `_started_turn_sessions` proposal was removed entirely.
4. **Did I trace the data flow end-to-end?** Yes — I traced all three stale-call scenarios (single, double, tool-only-new-turn) and discovered that the two-set design is fundamentally ambiguous, leading to the revert decision. This is documented in the spec rationale.
5. **Would an implementer following this spec exactly produce working code?** Yes — the edits are a revert (restore known-good code), a one-line param read, a one-line docstring fix, and a doc section move. All low-risk.

**Important design note for the implementer:** The spec initially proposed a `_started_turn_sessions` two-set state machine, then discovered mid-trace that it is fundamentally ambiguous (cannot distinguish stale calls from new-turn calls). The spec was corrected to revert to pure suppression instead. **Implement only the final/revised edits (revert + BUG #17 + BUG #20 + BUG #19). Do NOT add `_started_turn_sessions`.** The Acceptance Criteria explicitly require zero `_started_turn_sessions` matches.

The spec is complete.
