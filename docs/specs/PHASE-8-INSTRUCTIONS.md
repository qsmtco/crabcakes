# PHASE 8 — INSTRUCTIONS

**Builder:** QTR ("Cutter") — operative code: blade that cuts time
**Supervisor:** Qaster (this file is the delegation)
**Spec:** `docs/specs/SPEC-activity-drawer.md` §2.1, §2.4, §2.5 (enrichment); §3.4 (data flow)
**Audit prompt:** `adversarialDebugger.md` — will be run by Qaster after submission
**Steel-framed code writer prompt:** `prompts/steelFramedCodeWriter.md` — **USE THIS EXACTLY. NO DEVIATION.**

---

## Problem Statement

The activity drawer (`ui/views/activity_drawer.py`) shows every row prefixed with `[<agent>]` (e.g. `[Coder]`, `[Tester]`, `[QTR]`). For **5 of 6 `ActivityBubble(...)` call sites** in the codebase, the `agent_name` field is never set, so the drawer's `to_drawer_row()` falls back to the literal placeholder string `"Agent"` — and the user sees `[Agent]` for every tool call, plan, approval request, patch, and local exec command.

This is the **most visible defect** in the project right now and blocks the drawer's primary value proposition: telling the Captain which agent is doing what.

## Root Cause (verified by Qaster)

`ActivityBubble.to_drawer_row()` does `self.agent_name or "Agent"` — a defensive default. Five of eight `ActivityBubble(...)` call sites never set `agent_name`, so the default fires for every one of those event types.

**Affected sites:**

| # | File | Line | Event type | Symptom |
|---|------|------|------------|---------|
| 1 | `ui/handlers/activity_handler.py` | 373 | `plan` | Drawer shows `[Agent] plan: <title>` |
| 2 | `ui/handlers/activity_handler.py` | 385 | `approval_request` | Drawer shows `[Agent] approve: <cmd>` |
| 3 | `ui/handlers/activity_handler.py` | 398 | `patch` | Drawer shows `[Agent] ✏️ patch +N ~M` |
| 4 | `ui/handlers/connection_sync_handler.py` | 207 | `command_output` (local exec) | **Most visible** — fires on every shell command from a special agent (Coder, Debugger, Tester) |
| 5 | `ui/handlers/connection_sync_handler.py` | 209 (inside the same adapter) | `command_output` — `agent_name` kwarg missing | Same as #4 |

**NOT affected (already correct):**

- `lifecycle_start` (line 316) — already passes `agent_name=_agent_name`
- `tool_start` / `tool_end` / `tool_error` (lines 347, 359) — already pass `agent_name=_agent_name`

**Why the local exec adapter in `connection_sync_handler.py` is the worst offender:** It constructs a brand-new `ActivityBubble(...)` from scratch and forgets to forward an `agent_name=`. The data is in scope (we have `sk`); it just needs to be resolved via the same fallback chain that `ActivityHandler._resolve_agent_name()` already uses.

---

## The Fix (delegated to QTR)

### Scope: 2 files, 4 sub-phases

The fix is split into 4 sub-phases per the implementationSupervisor pattern (one focused change per phase, verifiable independently). Run them in this exact order.

---

### Sub-phase 8a — Fix `plan` bubble in `activity_handler.py`

**File:** `ui/handlers/activity_handler.py`
**Line:** 373
**Edit:** Add `agent_name=_agent_name,` to the `ActivityBubble(...)` constructor call for `plan`.

**Before (around line 373):**
```python
                    bubble = ActivityBubble(type="plan", session_key=sk, icon="📋", title=title, steps=steps)
```

**After:**
```python
                    bubble = ActivityBubble(type="plan", session_key=sk, icon="📋", title=title, steps=steps, agent_name=_agent_name)
```

**Verify:**
- `grep -n "type=\"plan\"" ui/handlers/activity_handler.py` shows the line with `agent_name=_agent_name` on it
- `python3 -c "import ast; ast.parse(open('ui/handlers/activity_handler.py').read())"` exits 0
- `python3 -m pytest tests/test_activity_bubbles.py -q --tb=short` still passes (no regression to existing tests)

**Evidence to report:** paste the grep output, the AST parse exit code, and the pytest tail (last 5 lines).

---

### Sub-phase 8b — Fix `approval_request` bubble in `activity_handler.py`

**File:** `ui/handlers/activity_handler.py`
**Line:** 385
**Edit:** Add `agent_name=_agent_name,` to the `ActivityBubble(...)` constructor call for `approval_request`.

**Before (around line 385):**
```python
                        bubble = ActivityBubble(type="approval_request", session_key=sk, icon="🔒", command=cmd, reason=reason, approval_id=approval_id)
```

**After:**
```python
                        bubble = ActivityBubble(type="approval_request", session_key=sk, icon="🔒", command=cmd, reason=reason, approval_id=approval_id, agent_name=_agent_name)
```

**Verify:**
- `grep -n "type=\"approval_request\"" ui/handlers/activity_handler.py` shows the new kwarg
- AST parse exits 0
- Pytest still passes

**Evidence to report:** grep output + pytest tail.

---

### Sub-phase 8c — Fix `patch` bubble in `activity_handler.py`

**File:** `ui/handlers/activity_handler.py`
**Line:** 398
**Edit:** Add `agent_name=_agent_name,` to the `ActivityBubble(...)` constructor call for `patch`.

**Before (around line 398):**
```python
                        bubble = ActivityBubble(type="patch", session_key=sk, tool_name=name, added=added, modified=modified, deleted=deleted, icon="✏️")
```

**After:**
```python
                        bubble = ActivityBubble(type="patch", session_key=sk, tool_name=name, added=added, modified=modified, deleted=deleted, icon="✏️", agent_name=_agent_name)
```

**Verify:**
- `grep -n "type=\"patch\"" ui/handlers/activity_handler.py` shows the new kwarg
- AST parse exits 0
- Pytest still passes

**Evidence to report:** grep output + pytest tail.

---

### Sub-phase 8d — Fix local exec adapter in `connection_sync_handler.py`

This is the **highest-impact sub-phase** because it fires on every local shell command (pytest, curl, ls, etc.) from every special agent (Coder, Debugger, Tester). The `agent_name` field is missing from the `ActivityBubble` constructor. The fix needs to resolve the name via the same fallback chain that `ActivityHandler._resolve_agent_name()` already uses.

**File:** `ui/handlers/connection_sync_handler.py`
**Lines:** 199-220 (the `_on_command_output` adapter inside the `agent_runtime.set_on_command_output(...)` block)
**Edit:** Add `agent_name=` to the `ActivityBubble(...)` constructor, resolved via `_resolve_agent_name`-equivalent logic.

**Constraints (read carefully):**

1. The local exec adapter currently has **no `agent_mgr` reference**. You cannot copy `_resolve_agent_name` from `activity_handler.py` because it lives on the `ActivityHandler` instance, which `connection_sync_handler.py` may or may not have. Read `connection_sync_handler.py` to confirm what references it has. The fix is one of:

   - **Option A (preferred):** Get the name from the `AgentRuntimeHandler` (which knows what agent is running locally — see `agent/agents.py:AgentManager.get_name(session_key)`). The adapter is already wired via `agent_runtime = self._chat_handler._agent_runtime_handler` (line 198 in current file). Use `agent_runtime._agent_mgr.get_name(sk)` if `_agent_mgr` is accessible, OR add a new public method `AgentRuntimeHandler.get_agent_name_for_session(sk) -> str` that returns the agent's display name. **You may add the new method** — it's a small accessor, not a behavioral change.

   - **Option B (fallback):** If you can't find a clean resolution path, default the local exec adapter to use `agent_name=""` and let `to_drawer_row()` fall back to `"Agent"`. This is **no worse than the current state** but is **not a real fix**. The Captain wants real names. Document why Option A was rejected in the COMPLETENESS checklist.

   **Do NOT invent a new mechanism.** If neither A nor B is straightforward, STOP and report — do not improvise.

2. The local exec adapter runs on the GTK main thread (it's called from `_do_tool_call_result` via `GLib.idle_add`). It is safe to call AgentManager methods directly. No `GLib.idle_add` needed inside the adapter.

3. **Rule 8 from steelFramedCodeWriter** — Do not modify anything outside this adapter. Don't reformat, don't reorder imports, don't rename variables. Touch only the lines needed for the `agent_name` resolution.

**Before (around lines 199-220, exact current text per the spec):**
```python
                def _on_command_output(sk, command, output, exit_code, duration_ms):
                    from models.activity import ActivityBubble
                    bubble = ActivityBubble(
                        type="command_output",
                        session_key=sk,
                        tool_name=command,
                        command=command,
                        output=output,
                        exit_code=exit_code,
                        duration_ms=duration_ms,
                        icon="💻",
                    )
                    drawer.append_event(bubble.to_drawer_row())
                agent_runtime.set_on_command_output(_on_command_output)
```

**After (Option A — preferred — using AgentManager):**
```python
                def _on_command_output(sk, command, output, exit_code, duration_ms):
                    from models.activity import ActivityBubble
                    # Resolve agent name via AgentManager (mirrors the fallback chain
                    # in ActivityHandler._resolve_agent_name). Local exec bubbles
                    # don't have a gateway payload to read data.agentName from, so
                    # we resolve locally via session_key.
                    agent_name = ""
                    if agent_runtime is not None:
                        agent_name = agent_runtime.get_agent_name_for_session(sk) or ""
                    bubble = ActivityBubble(
                        type="command_output",
                        session_key=sk,
                        tool_name=command,
                        command=command,
                        output=output,
                        exit_code=exit_code,
                        duration_ms=duration_ms,
                        icon="💻",
                        agent_name=agent_name,
                    )
                    drawer.append_event(bubble.to_drawer_row())
                agent_runtime.set_on_command_output(_on_command_output)
```

**You must ALSO add the accessor to `AgentRuntimeHandler`** if you go with Option A. The new method is one line:

**File:** `ui/handlers/agent_runtime_handler.py`
**Where:** next to other public accessors (search for existing methods like `get_active_project`, `get_conversation_for_session`, etc. — pick a logical neighbor)

```python
    def get_agent_name_for_session(self, session_key: str) -> str:
        """Return the display name of the agent that owns this session, or ''.

        Used by the local exec adapter to populate ActivityBubble.agent_name
        so the activity drawer shows the right agent name in the [Agent] column.

        Args:
            session_key: The agent's session key.

        Returns:
            The agent's display name (e.g. "Coder"), or "" if not found.
        """
        if self._agent_mgr is None:
            return ""
        try:
            return self._agent_mgr.get_name(session_key) or ""
        except Exception:
            return ""
```

**Verify (sub-phase 8d):**
- `grep -n "agent_name=" ui/handlers/connection_sync_handler.py` shows the new kwarg
- `grep -n "get_agent_name_for_session" ui/handlers/agent_runtime_handler.py` shows the new method
- `python3 -c "import ast; ast.parse(open('ui/handlers/connection_sync_handler.py').read())"` exits 0
- `python3 -c "import ast; ast.parse(open('ui/handlers/agent_runtime_handler.py').read())"` exits 0
- `python3 -m pytest tests/ -q --tb=short -x` all pass (full suite, not just the activity tests — make sure you didn't break anything else)

**Evidence to report:** grep outputs for both files, AST exit codes, full pytest tail.

---

## Cross-cutting rules

1. **SteelFramedCodeWriter prompt is MANDATORY.** Read `prompts/steelFramedCodeWriter.md` before writing any code. Follow the 6-step process: Discovery → Data Flow Trace → Implement (hard part first) → Wire → Test → Verify. **Maximum 15 lines of code per batch before stopping to verify.**

2. **No new files.** This phase is purely a 4-edit fix. No new modules, no new tests beyond what's needed to verify the fix.

3. **If a test already exists that covers the local exec agent_name path, run it.** If it doesn't exist and is needed, **add a single test in `tests/test_activity_bubbles.py`** that:
   - Mocks `AgentRuntimeHandler` with a known session_key → name mapping
   - Calls the local exec adapter with that session_key
   - Asserts the resulting `ActivityBubble.agent_name` equals the mocked name

   Do not add tests for sub-phases 8a/8b/8c — those are 1-line kwarg additions; the existing `test_activity_bubbles.py::TestActivityHandlerActivityBubbles` will catch regressions.

4. **No reformatting.** Touch only the lines you must. Don't fix adjacent comments. Don't reorder imports.

5. **If you find any other `ActivityBubble(...)` call site that's missing `agent_name` and isn't on this list, STOP and report it** — do not silently fix it without including it in the COMPLETENESS checklist.

---

## What NOT to do

- ❌ Do NOT modify `ui/views/activity_drawer.py` — the drawer is already correct, the bug is upstream.
- ❌ Do NOT modify `models/activity.py` — the `to_drawer_row()` fallback to `"Agent"` is intentional defensive code, and changing it would mask other bugs.
- ❌ Do NOT add a new callback or refactor the wiring. The minimum-touch fix is the goal.
- ❌ Do NOT remove the `or "Agent"` fallback in `to_drawer_row()`. It guards against truly unknown bubbles.
- ❌ Do NOT change CSS, do NOT update ARCHITECTURE.md (the spec already documents the field and the architecture, and the fix is a kwarg addition — Section 0's "code change → doc update" rule applies to PUBLIC API changes, not to filling in fields that the spec already lists).

---

## What success looks like

After Phase 8 is merged:

1. **Drawer shows real names everywhere.** Trigger a local `pytest` from Coder → drawer shows `[Coder] exec pytest ...`. Trigger a `plan` from QTR → drawer shows `[QTR] plan: <title>`. Trigger an `approval_request` → drawer shows `[Coder] approve: rm -rf /tmp/x`. Trigger a `patch` → drawer shows `[Coder] ✏️ patch +2 ~1`.

2. **No `[Agent]` placeholder anywhere** — except as the last-resort fallback in the `to_drawer_row()` code (which is correct defensive code).

3. **All existing tests pass.** Plus the one new test for the local exec adapter.

4. **No new files**, no architectural changes, no CSS changes, no docs changes (per the spec, this is a kwarg-fill-in, not a new feature).

---

## COMPLETENESS CHECKLIST (MANDATORY — include in your final report)

When you report done, your response MUST end with this checklist, with every item filled in. Items marked `[NOT DONE]` with a reason are OK; items that simply don't appear are NOT OK.

```
COMPLETENESS:
- [x/not done] Sub-phase 8a: agent_name=_agent_name added to `plan` ActivityBubble — evidence (grep line, pytest tail)
- [x/not done] Sub-phase 8b: agent_name=_agent_name added to `approval_request` ActivityBubble — evidence
- [x/not done] Sub-phase 8c: agent_name=_agent_name added to `patch` ActivityBubble — evidence
- [x/not done] Sub-phase 8d: agent_name resolved in local exec adapter (connection_sync_handler.py) — evidence
- [x/not done] Sub-phase 8d: get_agent_name_for_session() added to AgentRuntimeHandler — evidence (grep line)
- [x/not done] (Optional) New test in tests/test_activity_bubbles.py for local exec adapter — evidence
- [x/not done] Full test suite (pytest tests/ -q) passes — paste the last 10 lines
- [x/not done] No other ActivityBubble(...) call sites missing agent_name (grep all files) — evidence
- [x/not done] No collateral edits to lines outside the 4 sub-phase scopes — evidence (git diff shows only the 4 areas)
```

---

## Tools you'll need

- **Read:** `ui/handlers/activity_handler.py`, `ui/handlers/connection_sync_handler.py`, `ui/handlers/agent_runtime_handler.py`, `agent/agents.py` (for AgentManager.get_name), `tests/test_activity_bubbles.py` (for test patterns)
- **Grep:** `grep -rn "ActivityBubble(" ui/ tests/`
- **Test:** `python3 -m pytest tests/ -q --tb=short`
- **AST parse:** `python3 -c "import ast; ast.parse(open('FILE').read())"`

---

*End of PHASE 8 instructions. QTR — your move. Report back with the COMPLETENESS checklist and paste real command output. Qaster will then audit with adversarialDebugger and either accept or send it back.*

*Mantra: "Trust the builder's intent, verify the builder's output." — implementationSupervisor*
