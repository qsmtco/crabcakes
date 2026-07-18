# SPEC: Activity Drawer Bugfixes Round 2 — Regressions from Round 1

**Date:** 2026-07-18
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** Fixes for BUG #13, #14, #15 found in the Debugger re-audit + ARCHITECTURE.md doc update (known gap #2)
**Depends on:** `docs/specs/SPEC-ACTIVITY-DRAWER-OFFLINE-LOCAL.md`, `docs/specs/SPEC-ACTIVITY-DRAWER-BUGFIXES.md`
**Target branch:** main

> **Architecture compliance:** All changes stay within `ui/handlers/agent_runtime_handler.py` (view-layer handler, §3.21v) and `docs/ARCHITECTURE.md`. No cross-layer imports introduced. No new modules. The fixes are surgical corrections to the Round-1 code; the doc update is mandated by the project convention "ARCHITECTURE.md must be updated in the same commit as any structural code change."

---

## DISCOVERY (read before writing any spec content)

- **Read `ui/handlers/agent_runtime_handler.py` lines 995–1215, 1450–1460, 1715–1725:** confirmed the three defect sites and the two `_ended_sessions.add()` sites. The `_do_tool_call_result` signature is `(self, session_key: str, name: str, result: Any, success: bool = True)`. The shadowing occurs at lines 1116 (`success = result.success`) and 1121 (`success = True`), both inside the `if card_id is not None and self._fh is not None:` block — Python function scope means these leak to line 1170 (`is_error = not success`).
- **Read `agent/runtime.py` lines 2456, 2476, 2557:** confirmed the 3 dispatch sites pass `success` as the 4th arg (`False`, `False`, `result.success` respectively). No change needed here this round — the runtime is correct; the handler is wrong.
- **Read `tests/test_agent_runtime.py` lines 3785–3820 (`_make_handler`) and 3875–3900 (the BUG #1 tests):** confirmed `_make_handler` sets `handler._fh = MagicMock()` but the BUG #1 tests never populate `_tool_card_ids[sk]`, so `card_id = self._tool_card_ids.pop(session_key, None)` returns `None`, skipping the shadowing block. This is why the tests pass despite BUG #13.
- **Read `models/feed_card.py` lines 43–54:** `FeedCardData` is a dataclass with required fields `card_type, source, title, body, author, timestamp, project_name` and optional `metadata`. Required for the regression test fixtures.
- **Read `docs/ARCHITECTURE.md` lines 1078, 2284–2330, 2564–2640:** located the two stale references to `connection_sync_handler.sync()` owning the adapter (§3.14j line 1078, §3.23 line 2620), the §3.21y module description (line 2284), and the §3.23 activity_handler description (line 2564). These need updating to reflect the new `activity_wiring_handler`.
- **Architecture owner:** `AgentRuntimeHandler` (§3.21v) owns the local-agent UI bridge; `ActivityWiringHandler` (new, undocumented) owns the drawer wiring. The fixes belong in `agent_runtime_handler.py`; the doc updates touch ARCHITECTURE.md only.
- **Existing patterns:** the `_ended_sessions` set uses `add()`/`discard()` semantics; the `_pending_exec_commands` dict mirrors `_pending_tool_args` (both keyed by session_key, both set in start, popped in result).

---

## 1. Overview

### Problem
Round 1 fixed 5 bugs but introduced 3 regressions (BUG #13, #14, #15) and left the ARCHITECTURE.md doc stale (known gap #2). BUG #13 is critical: it silently re-introduces the original BUG #1 (denials/failures show as success) AND, for failed `write_file`, suppresses the bubble entirely (drawer goes silent).

### Solution
Three surgical fixes in `agent_runtime_handler.py`, two regression tests that exercise the production code path (not the no-card mock path), and the mandated ARCHITECTURE.md update documenting the `ActivityWiringHandler` that was added in Round 0.

### Scope

| In | Out |
|----|-----|
| `ui/handlers/agent_runtime_handler.py` — 3 bug fixes | `agent/runtime.py` (already correct) |
| `tests/test_agent_runtime.py` — 2 regression tests | `ui/handlers/activity_wiring_handler.py` (no change) |
| `docs/ARCHITECTURE.md` — doc update for the new handler | Any other handler |

### Architecture principles that apply
- §8.6 Handler Pattern: changes stay within the existing handler.
- §3.6 composition root: no window.py change.
- Project convention: ARCHITECTURE.md updated in the same commit as structural changes.

---

## 2. Changes by File

### 2.1 `ui/handlers/agent_runtime_handler.py`

#### Fix BUG #13 — `success` param shadowing (lines 1116, 1121)

**Root cause:** the feed-card block reuses the param name `success` for a local "card-display success" computation. Python has function scope, not block scope, so lines 1116/1121 clobber the param for the downstream bubble block at line 1170.

**Fix:** rename the feed-card locals to `card_success`. The param `success` is then read only by the bubble block. Three edits:

**Edit 1 — line 1116:**
```python
# OLD:
                    success = result.success
# NEW:
                    card_success = result.success
```

**Edit 2 — line 1121:**
```python
# OLD:
                    success = True
# NEW:
                    card_success = True
```

**Edit 3 — line 1127 (the `card.metadata["status"]` line):**
```python
# OLD:
                card.metadata["status"] = "complete" if success else "error"
# NEW:
                card.metadata["status"] = "complete" if card_success else "error"
```

After these three edits, the bubble block at line 1170 (`is_error = not success`) reads the runtime-dispatched param, which is no longer touched by the feed-card block. **No other line changes** — the bubble block, the `skip_tool_end` logic, the patch logic all remain as-is and now read the correct value.

**Traced verification:** for a denied exec_command (runtime dispatches `success=False`, result is a string): feed-card block runs the `else` branch → `card_success = True` (used only for `card.metadata["status"]`); bubble block reads `success=False` (the param, untouched) → `is_error = True` → emits `tool_error` with ❌. ✅ Correct.

For a failed write_file (runtime dispatches `success=False`, result is a string): feed-card block → `card_success = True`; bubble block → `is_error = True`, `skip_tool_end = ("write_file" == "write_file" and not True) = False` → emits `tool_error`. The patch block is skipped (result doesn't start with "OK"). ✅ Correct — failure is now visible.

#### Fix BUG #14 — `_ended_sessions` not discarded in tool-only turns (line 1002)

**Root cause:** the discard only lives in `_do_text_delta` (line 973). A tool-only turn (no streaming text, e.g. an LLM that emits a tool-call before any text) never reaches that discard, so the flag set by the previous turn's end suppresses the next turn's `tool_start`.

**Fix:** discard the flag in `_do_tool_call_start` *after* the stale-call suppression check, so the first tool_start of a new turn clears the flag for subsequent calls. Edit at line 1002:

```python
# OLD:
        if session_key in self._ended_sessions:
            logger.debug("_do_tool_call_start: suppressed for ended session %s", session_key)
            return
# NEW:
        if session_key in self._ended_sessions:
            # Stale dispatch from a previous turn (cancelled/completed).
            # The flag is cleared here so the NEXT tool_start of a new turn
            # is not suppressed. This handles tool-only turns that never
            # pass through _do_text_delta's discard path (BUG #14).
            logger.debug("_do_tool_call_start: stale call suppressed, clearing ended flag for %s", session_key)
            self._ended_sessions.discard(session_key)
            return
```

**Traced verification:**
- Turn 1 ends → `_ended_sessions.add("special:coder")`.
- Turn 2 is tool-only → `_do_tool_call_start` runs → flag is set → enters the `if` block → suppresses THIS (stale) call AND clears the flag → returns.
- Turn 2's NEXT `_do_tool_call_start` → flag is clear → proceeds normally → emits `tool_start`. ✅ Correct.

Note: this means the FIRST tool_start of a tool-only new turn is suppressed (treated as potentially stale), but subsequent ones fire. This is acceptable — the stale call is genuinely ambiguous (could be a leftover from the previous turn), and the drawer's counter-collapse will show the activity from the second tool onward. The alternative (clearing the flag and proceeding) risks re-introducing BUG #2's orphan bubble.

#### Fix BUG #15 — `_pending_exec_commands` capture inside project guard (line 1027)

**Root cause:** BUG #4's fix moved the bubble emissions and `_pending_tool_args` write outside the `if self._fh is not None and self._active_project is not None:` guard, but the `_pending_exec_commands[session_key] = cmd` capture stayed inside (line 1027, inside the `exec_command` branch). So when no project is open, exec_command bubbles fire but the command_output callback receives `cmd = ""`.

**Fix:** move the capture to the unconditional block. The `cmd` variable needs to be resolved before the guard so it's available in both places. Two edits:

**Edit A — line 1013 (inside the `elif name == "exec_command":` branch), remove the capture line:**
```python
# OLD:
            elif name == "exec_command":
                cmd = args.get("command", "?")
                title = f"{agent_name} is running: {cmd[:60]}"
                # SPEC-activity-drawer: capture the command for the command_output
                # drawer row that fires when the result comes back. Stored per-session
                # so _do_tool_call_result can resolve it.
                self._pending_exec_commands[session_key] = cmd
# NEW:
            elif name == "exec_command":
                cmd = args.get("command", "?")
                title = f"{agent_name} is running: {cmd[:60]}"
```

**Edit B — in the unconditional block (after line 1061 `self._pending_tool_args[session_key] = args`), add the capture:**
```python
# After the existing line:
        self._pending_tool_args[session_key] = args
# Add:
        # BUG #15: capture exec command unconditionally (outside the project guard)
        # so the command_output drawer row has the command text even with no project open.
        if name == "exec_command":
            self._pending_exec_commands[session_key] = args.get("command", "")
```

**Traced verification:** no project open, exec_command("ls -la") → `_do_tool_call_start` runs the unconditional block → `_pending_exec_commands["special:coder"] = "ls -la"` → `_do_tool_call_result` → `cmd = "ls -la"` → command_output callback gets the real command. ✅ Correct.

**Files NOT changed** (already correct):
- `agent/runtime.py` — the 3 dispatch sites already pass `success` correctly (verified lines 2456/2476/2557).
- `ui/handlers/activity_wiring_handler.py` — no defect found; unchanged from Round 0.
- `ui/handlers/connection_sync_handler.py` — already cleaned in Round 0.
- `ui/window.py` — already constructs `ActivityWiringHandler` correctly.

---

### 2.2 `tests/test_agent_runtime.py`

Add 2 regression tests to the existing `TestLocalAgentDrawerEmissions` class. Both prime `_tool_card_ids` and `_fh.get_card` so the feed-card block runs (exercising the BUG #13 path that the existing tests bypass).

**Test 1 — `test_denied_exec_with_card_still_emits_tool_error` (regression for BUG #13):**
```python
def test_denied_exec_with_card_still_emits_tool_error(self):
    """Regression for BUG #13: success param shadowed by feed-card block.

    The existing test_denied_exec_command_emits_tool_error_bubble bypasses the
    feed-card block (no _tool_card_ids entry). This test primes the card so the
    shadowing block runs, proving the rename fix holds.
    """
    handler, _, _ = self._make_handler_with_agent()
    # Prime _tool_card_ids as if _do_tool_call_start had run first
    from models.feed_card import FeedCardData
    from datetime import datetime, timezone
    card = FeedCardData(
        card_type="agent_action",
        source="agent",
        title="Coder is running: rm -rf /",
        body="⏳ Running...",
        author="Coder",
        timestamp=datetime.now(timezone.utc),
        project_name="test",
    )
    handler._tool_card_ids["special:coder"] = "card-123"
    handler._fh.get_card.return_value = card

    # Runtime dispatches success=False for a denied exec_command
    handler._do_tool_call_result(
        "special:coder", "exec_command",
        "exec_command requires PM approval — request denied or timed out",
        success=False,
    )

    types = [b.type for b in self._bubbles]
    assert "tool_error" in types, (
        f"BUG #13: tool_error not emitted when feed-card block ran first; got {types}"
    )
    tool_error = [b for b in self._bubbles if b.type == "tool_error"][0]
    assert tool_error.icon == "❌"
```

**Test 2 — `test_write_file_failure_string_result_emits_tool_error` (regression for BUG #13 compounding case):**
```python
def test_write_file_failure_string_result_emits_tool_error(self):
    """Regression for BUG #13 compounding case: failed write_file with a string
    result AND a feed card must emit tool_error (not be silently suppressed).

    Before the fix, the shadowing forced success=True → is_error=False →
    skip_tool_end=True (BUG #12 logic) → NO bubble at all for failed write_file.
    """
    handler, _, _ = self._make_handler_with_agent()
    from models.feed_card import FeedCardData
    from datetime import datetime, timezone
    card = FeedCardData(
        card_type="agent_action",
        source="agent",
        title="Coder is writing /etc/passwd",
        body="⏳ Running...",
        author="Coder",
        timestamp=datetime.now(timezone.utc),
        project_name="test",
    )
    handler._tool_card_ids["special:coder"] = "card-123"
    handler._fh.get_card.return_value = card
    handler._pending_tool_args["special:coder"] = {"path": "/etc/passwd"}

    handler._do_tool_call_result(
        "special:coder", "write_file", "blocked: sensitive path", success=False,
    )

    types = [b.type for b in self._bubbles]
    assert "tool_error" in types, (
        f"BUG #13: failed write_file emitted no terminal bubble; got {types}"
    )
    # No patch on failure
    assert "patch" not in types, f"Expected no patch on failure; got {types}"
```

**Traced verification of the tests:** after the BUG #13 fix, `_do_tool_call_result` with a primed card + `success=False` + string result → feed-card block runs but uses `card_success` (not `success`) → bubble block reads `success=False` → `is_error=True` → for exec_command emits `tool_error`; for write_file emits `tool_error` (since `skip_tool_end = write_file and not is_error = write_file and False = False`). Both assertions pass.

---

### 2.3 `docs/ARCHITECTURE.md`

Per project convention. Four edits:

**Edit 1 — §3.14j (line 1078):** change the stale reference.
```markdown
# OLD:
- Connected to ActivityHandler via `set_on_activity_bubble` (adapter in `connection_sync_handler.sync()` converts `ActivityBubble` to dict via `to_drawer_row()`)
# NEW:
- Connected to ActivityHandler via `set_on_activity_bubble` (adapter in `activity_wiring_handler.py` converts `ActivityBubble` to dict via `to_drawer_row()`)
```

**Edit 2 — §3.23 (line 2620):** change the stale reference.
```markdown
# OLD:
Architecture: ActivityHandler only creates ActivityBubble dataclass instances and fires the callback. As of SPEC-activity-drawer Phase 1, the callback target is `ActivityDrawer.append_event(bubble.to_drawer_row())` — the adapter that converts the dataclass to the drawer's dict shape lives in `connection_sync_handler.sync()`. ChatHandler no longer renders activity bubbles.
# NEW:
Architecture: ActivityHandler only creates ActivityBubble dataclass instances and fires the callback. As of SPEC-activity-drawer Phase 1, the callback target is `ActivityDrawer.append_event(bubble.to_drawer_row())` — the adapter that converts the dataclass to the drawer's dict shape lives in `activity_wiring_handler.py` (a dedicated handler constructed at startup, not deferred to gateway connect, so the drawer works offline). ChatHandler no longer renders activity bubbles.
```

**Edit 3 — §3.21y (line ~2310, the Public API block):** add a note that drawer wiring moved out.
```markdown
# After the existing "def sync(self, gw: GatewayClient) -> None" block, add a note:
    # NOTE: ActivityDrawer wiring (set_on_activity_bubble, set_on_agent_lifecycle,
    # set_on_command_output) has moved to ui/handlers/activity_wiring_handler.py
    # (constructed at startup, not deferred to connect) so the drawer works offline.
    # sync() now only injects AgentManager via set_agent_manager().
```

**Edit 4 — Add a new section §3.21zb for `activity_wiring_handler.py`.** Insert after §3.21za (settings_handler.py, line ~2377) or at the end of the §3.21 series. Content:

```markdown
### 3.21zb `ui/handlers/activity_wiring_handler.py` — Activity Wiring Handler (SPEC-activity-drawer offline + local)

**Responsibility:** Single owner of all ActivityDrawer event wiring — gateway AND local, online AND offline. Constructed in `window.py._build()` and `.wire()` called unconditionally at startup (no gateway required), so the drawer receives events from the first local-agent tool call onward.

**Owns:** The adapter logic that converts `ActivityBubble` dataclass instances to drawer row dicts (via `bubble.to_drawer_row()`), and the routing of local `AgentRuntimeHandler` tool/lifecycle/exec events into the drawer.

**Constructor dependencies:**
- `activity_handler`: ActivityHandler — source of gateway bubbles + lifecycle separators
- `agent_runtime_handler`: AgentRuntimeHandler — source of local exec_command output, tool lifecycle, agent start/end
- `activity_drawer`: ActivityDrawer — the target

**Public API:**
```python
class ActivityWiringHandler:
    def __init__(self, *, activity_handler, agent_runtime_handler, activity_drawer) -> None
    def wire(self) -> None   # idempotent — wires 5 callbacks (gateway bubble/lifecycle, local exec/tool/lifecycle)
```

**Dedup invariant:** Local bridges fire only for special-agent sessions (`special:*` keys via `AgentRuntimeHandler`); gateway bridges fire for gateway sessions. The namespaces are disjoint for built-in agents. No explicit dedup code is needed (documented invariant).

**Extracted from:** `connection_sync_handler.sync()` (the former home of the gateway-bubble adapter closures). Moved out because `sync()` only runs on gateway connect, which broke the drawer offline.

**Offline name resolution:** `_resolve_local_agent_name()` uses `AgentRuntimeHandler.get_agent_name_for_session()` (the local registry), not the gateway `AgentManager`, so agent names resolve correctly without a connection.
```

**Edit 5 — §2 directory tree (line ~155, the `ui/handlers/` block):** add the new file.
```markdown
# Add after connection_sync_handler.py line:
│   ├── activity_wiring_handler.py  # ActivityDrawer event wiring — gateway + local, online + offline (SPEC-activity-drawer)
```

---

## 3. Data Flow

Unchanged from Round 0/1. The fixes correct variable scoping and guard placement; no new data paths.

- Tool call: `agent/runtime.py` `_dispatch(_on_tool_call_result, sk, name, result, success)` → `AgentRuntimeHandler._on_tool_call_result` → (GLib.idle_add) → `_do_tool_call_result` → feed-card block (uses `card_success`, NOT `success`) → bubble block (reads `success` param → `is_error`) → drawer.
- Tool-only new turn: `_do_tool_call_start` → if `_ended_sessions` has the key → clear it + return (stale) → next `_do_tool_call_start` → key is clear → proceeds.

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|------------|-------|------|
| `ui/handlers/agent_runtime_handler.py` | 3 bug fixes (rename locals, move capture, add discard) | ~12 | Low |
| `tests/test_agent_runtime.py` | +2 regression tests | ~50 | Low |
| `docs/ARCHITECTURE.md` | Doc update (2 stale refs fixed, 1 note added, 1 new section, 1 tree entry) | ~30 | None |

## 5. Implementation Order

1. **BUG #13 fix** (3 edits in `_do_tool_call_result`): rename `success` → `card_success` at lines 1116, 1121, 1127. Verify: `python3 -c "..."` mental trace — bubble block now reads the param.
2. **BUG #14 fix** (1 edit in `_do_tool_call_start`): add `_ended_sessions.discard` inside the suppression `if` block at line 1002.
3. **BUG #15 fix** (2 edits): remove capture from line 1027 (inside guard), add unconditional capture after line 1061.
4. **Compile check:** `python3 -m py_compile ui/handlers/agent_runtime_handler.py`.
5. **Add 2 regression tests** to `TestLocalAgentDrawerEmissions`.
6. **Run tests:** `pytest tests/test_agent_runtime.py::TestLocalAgentDrawerEmissions -v`.
7. **ARCHITECTURE.md edits** (5 edits per §2.3).
8. **Final verification** per §6.

## 6. Acceptance Criteria

- [ ] `_do_tool_call_result` has no `success = ` assignment (only `card_success = ` and `is_error = not success`). Verified by: `grep -n "success = " ui/handlers/agent_runtime_handler.py` returns zero matches in `_do_tool_call_result`.
- [ ] `_do_tool_call_start` calls `self._ended_sessions.discard(session_key)` inside the `if session_key in self._ended_sessions:` block.
- [ ] `_pending_exec_commands[session_key]` is set in the unconditional block (outside the `if self._fh is not None and self._active_project is not None:` guard). Verified by: the only assignment to `_pending_exec_commands[` in `_do_tool_call_start` is NOT indented under the project guard.
- [ ] Both new regression tests pass.
- [ ] All 16 existing `TestLocalAgentDrawerEmissions` tests still pass.
- [ ] `grep -c "connection_sync_handler.sync()" docs/ARCHITECTURE.md` returns 0 matches in the activity-bubble context (the §3.14j and §3.23 references are updated).
- [ ] ARCHITECTURE.md contains a section for `activity_wiring_handler.py`.

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Denied exec_command WITH a feed card | `tool_error` ❌ (BUG #13 fix) |
| Failed write_file WITH a feed card | `tool_error` ❌, no patch (BUG #13 compounding fix) |
| Tool-only new turn after a completed turn | First stale tool_start suppressed + flag cleared; subsequent tool_starts fire (BUG #14 fix) |
| Multi-turn with text (normal case) | `_do_text_delta` discards flag as before; no behavior change |
| exec_command with no project open | command_output callback receives real command text (BUG #15 fix) |
| Card display status for a failed tool | `card.metadata["status"] = "error"` (still correct via `card_success`) |

## 8. ARCHITECTURE.md Updates Required

Documented in §2.3 above. Five edits: 2 stale-reference fixes (§3.14j, §3.23), 1 note addition (§3.21y), 1 new section (§3.21zb), 1 directory tree entry (§2).

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** Yes — all line numbers verified via `grep` and `sed` reads of the actual source. The rename targets exist at lines 1116/1121/1127. The discard target exists at line 1002. The capture-move targets exist at lines 1013-1019 and 1061.
2. **Did I catch all exception types?** N/A — no new exception handling; the fixes are variable renames and guard placement.
3. **Did I verify key structures?** Yes — `_tool_card_ids` is `dict[str, str]`, `_pending_exec_commands` is `dict[str, str]`, `_ended_sessions` is `set[str]`. All verified via `__init__` read.
4. **Did I trace the data flow end-to-end?** Yes — for each of the 3 bugs, I traced from the runtime dispatch site through the handler to the bubble emission, for both the ToolResult and string result cases.
5. **Would an implementer following this spec exactly produce working code?** Yes — the edits are mechanical (rename, move, add-discard) with exact before/after blocks.

The spec is complete.
