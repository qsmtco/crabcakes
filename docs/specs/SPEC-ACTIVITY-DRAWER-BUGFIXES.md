# Activity Drawer Bug Fixes — Follow-Up Spec

Fixes the 5 confirmed bugs from the Debugger adversarial audit + 2 known gaps. Read the original implementation spec at `docs/specs/SPEC-ACTIVITY-DRAWER-OFFLINE-LOCAL.md` for architectural context. All fixes stay within the files already changed by that spec.

---

## BUG #1 (CRITICAL) — `is_error` always False: denials/failures show as green ✅

### Root cause
`agent/runtime.py` lines 2456, 2476, 2557 dispatch `self._on_tool_call_result(session_key, tool_name, tc.result)` — passing `tc.result` which is a **string** (set by `mark_failed(msg)` or `mark_completed(result_text)`). The handler's check at `agent_runtime_handler.py:1144`:
```python
is_error = (hasattr(result, "error") and result.error) or (hasattr(result, "success") and not result.success)
```
always evaluates `False` on a string (strings have no `.error`/`.success` attrs). Denied exec_command and sensitive-path blocks become green ✅.

### Fix (structural)
Change the runtime to dispatch the `ToolCall` object's status alongside the result, OR dispatch the `ToolResult` dataclass. The cleanest minimal change: dispatch `(session_key, tool_name, result_text, tc.status)` where `tc.status` is the `ToolCallStatus` enum.

**Step 1 — `agent/runtime.py`:** At the THREE dispatch sites (lines 2456, 2476, 2557), change to pass the `tc` object's status. The existing `mark_failed`/`mark_executing`/`mark_completed` methods set `tc.status`. Check `models/conversation.py` for the `ToolCallStatus` enum values (likely `FAILED`, `COMPLETED`, `EXECUTING`). For the three dispatch sites:
- Line 2456 (exec denial): `self._dispatch(self._on_tool_call_result, session_key, tool_name, tc.result or "denied", False)`  — explicitly pass `success=False`.
- Line 2476 (sensitive-path block): same pattern, `success=False`.
- Line 2557 (normal completion): `self._dispatch(self._on_tool_call_result, session_key, tool_name, tool_result_text, result.success)` — pass the real `result.success` from the `ToolResult`.

**Step 2 — `agent_runtime_handler.py`:** Update `_on_tool_call_result` and `_do_tool_call_result` signatures to accept the new `success: bool` parameter. Update the `is_error` computation:
```python
# OLD (always False for strings):
is_error = (hasattr(result, "error") and result.error) or (hasattr(result, "success") and not result.success)
# NEW:
is_error = not success
```
Keep `duration_ms` extraction as-is (`getattr(result, "duration_ms", 0)` — works for strings since the runtime result string won't have it, defaulting to 0; that's acceptable).

**IMPORTANT — backward compat:** If any OTHER caller of `_on_tool_call_result` exists (grep `on_tool_call_result` across the codebase), it must be updated too, OR the new param must have a default (`success: bool = True`) so existing callers don't break. Prefer the default param for safety.

### Tests
Add to `tests/test_agent_runtime.py`:
- `test_denied_exec_command_emits_tool_error_bubble` — simulate the exec denial path, assert emitted bubble `type == "tool_error"`, `icon == "❌"`.
- `test_sensitive_path_block_emits_tool_error_bubble` — symmetric for write_file sensitive-path denial.
- `test_failed_tool_result_emits_tool_error_bubble` — a `read_file` that returns `success=False`.

---

## BUG #2 (HIGH) — Orphan `tool_start` bubble after cancel

### Root cause
`_dispatch` queues via `GLib.idle_add` (FIFO). A `_on_tool_call_start` dispatched microseconds before `cancel()` lands on the queue before the `_on_error`. Result: drawer shows `🔧 tool_start` AFTER `── Coder ended ──`.

### Fix
In `agent_runtime_handler._do_tool_call_start`, guard against emitting the bubble / writing `_pending_tool_args` if the session has already ended. Track a per-session "ended" set:
- Add `self._ended_sessions: set[str] = set()` to `__init__`.
- In `_do_tool_call_start`, early-return the bubble+args-write if `session_key in self._ended_sessions`.
- Clear `session_key` from `_ended_sessions` when a NEW turn starts (in `_do_text_delta` agent-start site, before emitting lifecycle "start").
- Add to `_ended_sessions` in BOTH agent-end sites (`_do_response_complete` ~line 1414, `_do_error` ~line 1678), right after the lifecycle "end" emission.

This is a cheap set-membership check; no race because all these run on the main thread (via idle_add).

### Tests
- `test_tool_start_suppressed_after_cancel` — mock GLib.idle_add to run callbacks synchronously; simulate: start → tool_call_start queued → cancel → drain; assert drawer got NO tool_start bubble.

---

## BUG #5 (HIGH) — `_pending_tool_args` leak on non-write_file errors

### Root cause
`_pending_tool_args[sk] = args` is written for ALL tools in `_do_tool_call_start` (line 1046), but only popped for `write_file` in `_do_tool_call_result` (line 1163/1172). Failed `read_file`/`search_files`/etc. leak their entry.

### Fix
Make the pop **unconditional** at the top of the write_file-specific block. Move the cleanup to a single site that always runs. Concretely: replace the scattered conditional pops with a single unconditional pop right after the activity-bubble dispatch (which runs for all tools). The `write_file` success path re-reads from the popped value:

```python
# After the tool_end/tool_error bubble dispatch (runs for all tools), pop unconditionally:
args_write = self._pending_tool_args.pop(session_key, {})

# Then the write_file-specific block uses args_write instead of popping again:
if name == "write_file" and isinstance(result, str) and result.startswith("OK") and self._on_activity_bubble is not None:
    file_path = args_write.get("path", "") if isinstance(args_write, dict) else ""
    ...patch bubble...
```

### Tests
- `test_pending_tool_args_cleared_after_non_writefile_error` — 3 failed `read_file` calls; assert `_pending_tool_args` is empty after.

---

## BUG #4 (MEDIUM) — Empty-project lifecycle-without-events

### Root cause
`_do_tool_call_start` early-returns when `_active_project is None` (line 995), but lifecycle start/end fire unconditionally. Drawer shows "Coder started / 0 events / Coder ended" — misleading.

### Fix (chosen behavior: emit tools even without a project)
The tool/lifecycle bubbles should NOT depend on `_active_project` — they only need `_on_activity_bubble`, not a feed card. Move the `_on_activity_bubble` emissions (tool_start, tool_end, patch) and the `_pending_tool_args` write **outside** the `if self._fh is None or self._active_project is None: return` guard. Keep the feed-card logic inside the guard (it needs `_active_project`).

Concretely in `_do_tool_call_start`: resolve `agent_name` BEFORE the guard (it uses `self._agents.get(session_key)`, not the project), then the guard only protects the feed-card block. Same for `_do_tool_call_result`.

### Tests
- `test_tool_bubbles_emitted_without_active_project` — no `set_active_project`; run a tool; assert drawer got tool_start + tool_end.

---

## BUG #12 (MEDIUM) — write_file double-count (tool_end + patch)

### Root cause
Local path emits BOTH `tool_end` AND `patch` for a successful write_file. The gateway path emits ONLY `patch` (for stream="patch"). Asymmetry inflates the drawer's visible row count vs its summary counter.

### Fix
Suppress the `tool_end`/`tool_error` bubble when `name == "write_file"` — emit ONLY the `patch` bubble for write_file success (matching the gateway). Guard the tool_end/tool_error dispatch:
```python
if self._on_activity_bubble is not None and name != "write_file":
    # tool_end / tool_error bubble (write_file gets patch instead)
    ...
```
The `patch` bubble already fires separately for write_file success. For write_file FAILURE, keep emitting `tool_error` (no patch on failure).

### Tests
- `test_write_file_success_emits_patch_not_tool_end` — successful write_file; assert drawer got exactly one bubble with `type == "patch"`, and NO `tool_end` bubble.
- `test_write_file_failure_emits_tool_error` — failed write_file; assert `type == "tool_error"`.

---

## Known Gap #1 — Add the 6 missing local-emission tests

Add to `tests/test_agent_runtime.py` (this is the correct file — the original spec misnamed it `test_agent_runtime_handler.py`):
- `test_do_tool_call_start_emits_tool_start_bubble`
- `test_do_tool_call_result_emits_tool_end_bubble` (non-write_file success)
- `test_do_tool_call_result_emits_tool_error_on_failure`
- `test_do_tool_call_result_emits_patch_for_write_file_success`
- `test_agent_start_emits_drawer_lifecycle_start`
- `test_agent_end_emits_drawer_lifecycle_end` (cover BOTH end sites: `_do_response_complete` and `_do_error`)

These target `AgentRuntimeHandler` methods directly (set `_on_activity_bubble` / `_on_drawer_lifecycle` to a capturing list, invoke the `_do_*` methods, assert the captured bubbles). Mock `_fh`, `_mc`, `_crh`, `_GLib=None` as needed.

---

## Known Gap #2 — Update `docs/ARCHITECTURE.md`

Per project convention ("must be updated in the same commit as any structural code change"):
1. **§3.23** (activity_handler.py): change "the adapter that converts the dataclass to the drawer's dict shape lives in `connection_sync_handler.sync()`" → reference `activity_wiring_handler.py`.
2. **§3.21y** (connection_sync_handler.py): note drawer wiring moved out; `sync()` now only sets `agent_manager`.
3. **§3.21v** (agent_runtime_handler.py): document the new `set_on_activity_bubble` / `set_on_drawer_lifecycle` callbacks.
4. **Add new section** (e.g., §3.21zb) for `activity_wiring_handler.py`: responsibility (single owner of activity→drawer routing, online + offline), constructor deps, `.wire()` method, dedup invariant note.
5. **§2 directory tree**: add `ui/handlers/activity_wiring_handler.py`.

---

## Verification After All Fixes

1. `pytest tests/test_agent_runtime.py -v` — new tests pass.
2. `pytest tests/test_activity_wiring_handler.py tests/test_connection_sync_handler.py -v` — still pass (42).
3. `python3 -m py_compile` all touched files.
4. Grep confirms no remaining `hasattr(result, "error")` / `hasattr(result, "success")` type-confusion patterns in the bubble emission paths.
5. Grep confirms `_pending_tool_args.pop` is unconditional.
