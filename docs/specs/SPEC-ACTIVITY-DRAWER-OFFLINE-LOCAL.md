# Activity Drawer Offline + Local-Agent Events — Implementation Spec

**Source:** Supervisor investigation + architecture-conformance audit.
**Goal:** The Activity Drawer (bottom panel) must show events offline (no gateway) AND surface the full local-agent event surface (tool starts, tool ends, patches, lifecycle) — not just `exec_command`.

**Root cause:** All drawer wiring lives inside `connection_sync_handler.sync()`, which only runs after a gateway connect. Additionally, only one local event (`exec_command`) is bridged to the drawer.

---

## Architecture Mandate (read first)

Per `docs/ARCHITECTURE.md` §8.6 (Handler Pattern — MANDATORY) and §3.6 (window.py):
- The adapter logic (convert `ActivityBubble` → drawer dict, build bubbles from tool results, resolve agent names) is **inter-handler coordination logic**, not composition. It must NOT live in `window.py`.
- It must NOT live in `connection_sync_handler.sync()` either — that handler's documented scope (§3.21y) is *"Post-connect wiring... fires once per connect."* Offline-needed wiring belongs elsewhere.
- §5 (Callback Pattern): callbacks are passed, never hardcoded; a component never imports another component's module.

**Therefore: extract all activity→drawer wiring into a NEW handler `ui/handlers/activity_wiring_handler.py`.** This is the single owner. `window.py` constructs it and calls `.wire()` unconditionally at startup. `connection_sync_handler.sync()` loses the three adapter closures.

---

## Reference: Current (Broken) Wiring

The three adapters live in `connection_sync_handler.sync()` lines 186–230:
- `_bubble_to_row` (line ~192) — wraps `drawer.append_event(bubble.to_drawer_row())`.
- `_on_lifecycle` (line ~197) — splits start/end into `drawer.on_agent_start`/`on_agent_end`.
- `_on_command_output` (line ~217) — builds an `ActivityBubble(type="command_output")` from `(sk, command, output, exit_code, duration_ms)`, resolves agent name via `AgentRuntimeHandler.get_agent_name_for_session(sk)`.

---

## Part A — New Handler: `ui/handlers/activity_wiring_handler.py`

### A.1 Responsibilities

Owns ALL activity-event → drawer routing. Three pieces:
1. **Gateway path** (preserved): `ActivityHandler` bubble/lifecycle callbacks → drawer.
2. **Local exec path** (preserved): `AgentRuntimeHandler._on_command_output` → drawer.
3. **NEW local tool path**: `AgentRuntimeHandler` tool lifecycle → drawer (see Part B).

### A.2 Class skeleton

```python
# ui/handlers/activity_wiring_handler.py
"""
Owns all ActivityDrawer event wiring — gateway AND local, online AND offline.

Per ARCHITECTURE.md §8.6 this is a handler (not window.py logic). Per §3.21y
the wiring must NOT live in connection_sync_handler.sync() (post-connect only).
This handler is constructed in window.py._build() and .wire() is called
unconditionally at startup, so the drawer receives events from the first
local-agent tool call onward — no gateway required.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.handlers.activity_handler import ActivityHandler
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
    from ui.views.activity_drawer import ActivityDrawer


class ActivityWiringHandler:
    """Single owner of activity-source → drawer routing."""

    def __init__(
        self,
        *,
        activity_handler: "ActivityHandler",
        agent_runtime_handler: "AgentRuntimeHandler",
        activity_drawer: "ActivityDrawer",
    ) -> None:
        self._activity_handler = activity_handler
        self._agent_runtime_handler = agent_runtime_handler
        self._drawer = activity_drawer

    def wire(self) -> None:
        """Wire all activity sources → drawer. Call once at startup (no gateway needed)."""
        # 1. Gateway bubbles → drawer
        self._activity_handler.set_on_activity_bubble(self._on_activity_bubble)
        # 2. Gateway lifecycle separators → drawer
        self._activity_handler.set_on_agent_lifecycle(self._on_agent_lifecycle)
        # 3. Local exec_command output → drawer
        self._agent_runtime_handler.set_on_command_output(self._on_local_command_output)
        # 4. NEW: local tool lifecycle → drawer
        self._agent_runtime_handler.set_on_activity_bubble(self._on_local_activity_bubble)
        # 5. NEW: local agent start/end → drawer separators
        self._agent_runtime_handler.set_on_drawer_lifecycle(self._on_local_drawer_lifecycle)

    # ── Gateway path adapters ───────────────────────────────────────────

    def _on_activity_bubble(self, bubble) -> None:
        """Gateway ActivityBubble → drawer row."""
        self._drawer.append_event(bubble.to_drawer_row())

    def _on_agent_lifecycle(self, session_key: str, agent_name: str, phase: str) -> None:
        """Gateway lifecycle start/end → drawer separator."""
        if phase == "start":
            self._drawer.on_agent_start(session_key, agent_name)
        elif phase == "end":
            self._drawer.on_agent_end(session_key, agent_name)

    # ── Local path adapters ─────────────────────────────────────────────

    def _resolve_local_agent_name(self, session_key: str) -> str:
        """Resolve agent name for a LOCAL session key. Works offline (no AgentManager).

        Uses AgentRuntimeHandler.get_agent_name_for_session — the local registry.
        """
        return self._agent_runtime_handler.get_agent_name_for_session(session_key) or "Agent"

    def _on_local_command_output(self, sk, command, output, exit_code, duration_ms) -> None:
        """Local exec_command result → drawer row (preserved from sync())."""
        from models.activity import ActivityBubble, ToolStatus
        agent_name = self._resolve_local_agent_name(sk)
        is_error = exit_code != 0
        bubble = ActivityBubble(
            type="command_output",
            session_key=sk,
            tool_name=command,
            command=command,
            output=output,
            exit_code=exit_code,
            duration_ms=duration_ms,
            icon="💻",
            status=ToolStatus.ERROR if is_error else ToolStatus.SUCCESS,
            agent_name=agent_name,
        )
        self._drawer.append_event(bubble.to_drawer_row())

    def _on_local_activity_bubble(self, bubble) -> None:
        """Local tool/patch bubble → drawer row."""
        # Enrich agent_name if the runtime didn't set it.
        if not bubble.agent_name:
            bubble.agent_name = self._resolve_local_agent_name(bubble.session_key)
        self._drawer.append_event(bubble.to_drawer_row())

    def _on_local_drawer_lifecycle(self, session_key: str, agent_name: str, phase: str) -> None:
        """Local agent start/end → drawer separator (mirrors gateway _on_agent_lifecycle)."""
        if phase == "start":
            self._drawer.on_agent_start(session_key, agent_name)
        elif phase == "end":
            self._drawer.on_agent_end(session_key, agent_name)
```

### A.3 Construction in `window.py._build()`

After `self._activity_drawer = ActivityDrawer()` (current line ~707) and after `self._agent_runtime_handler` is constructed:

```python
from ui.handlers.activity_wiring_handler import ActivityWiringHandler
self._activity_wiring_handler = ActivityWiringHandler(
    activity_handler=self._activity_handler,
    agent_runtime_handler=self._agent_runtime_handler,
    activity_drawer=self._activity_drawer,
)
self._activity_wiring_handler.wire()
```

This replaces the current `self._connection_sync_handler.set_activity_drawer(self._activity_drawer)` call (line ~712). That setter and the drawer reference held by ConnectionSyncHandler become unnecessary.

### A.4 Removal from `connection_sync_handler.sync()`

Delete lines 186–230 (the `if self._activity_drawer is not None:` block containing the three closures). Keep `self._activity_handler.set_agent_manager(...)` (line 184) — that genuinely needs the gateway's AgentManager.

Also remove from `ConnectionSyncHandler`:
- `self._activity_drawer = None` (line ~95)
- `set_activity_drawer()` method (line ~97)
- The `activity_drawer=` is no longer needed in the `ConnectionSyncHandler.__init__` signature if it was passed there (it currently is NOT — it's set via setter post-construction; verify).

---

## Part B — New Local-Agent Event Bridges

`AgentRuntimeHandler` already fires `_on_tool_call_start` / `_do_tool_call_result` (feed-card path) and `_on_agent_start_cb` / `_on_agent_end_cb`. Add a parallel drawer path.

### B.1 New callback slots on `AgentRuntimeHandler` (`__init__`, ~line 88)

```python
# NEW: activity-bubble callback for the drawer (tool lifecycle).
# cb(ActivityBubble) — fired on tool_start/tool_end/patch.
self._on_activity_bubble: Callable | None = None
# NEW: drawer-lifecycle callback for agent start/end separators.
# cb(session_key, agent_name, phase) where phase ∈ {"start", "end"}.
self._on_drawer_lifecycle: Callable | None = None
```

Add setters:
```python
def set_on_activity_bubble(self, cb) -> None:
    """cb(ActivityBubble) — local tool lifecycle → activity drawer."""
    self._on_activity_bubble = cb

def set_on_drawer_lifecycle(self, cb) -> None:
    """cb(session_key, agent_name, "start"|"end") — agent turn → drawer separators."""
    self._on_drawer_lifecycle = cb
```

### B.2 Emit bubbles from `_do_tool_call_start` (~line 961)

At the END of `_do_tool_call_start`, after the feed-card logic, emit a `tool_start` bubble:

```python
# NEW: activity-drawer tool_start bubble
if self._on_activity_bubble is not None:
    from models.activity import ActivityBubble, ToolStatus
    self._on_activity_bubble(ActivityBubble(
        type="tool_start",
        session_key=session_key,
        tool_name=name,
        icon="🔧",
        status=ToolStatus.RUNNING,
        agent_name=agent_name,   # already resolved above (line ~967)
    ))
```

### B.3 Emit bubbles from `_do_tool_call_result` (~line 1032)

At the END of `_do_tool_call_result`, after the existing exec_command handling, emit `tool_end` / `tool_error`:

```python
# NEW: activity-drawer tool_end/tool_error bubble
if self._on_activity_bubble is not None:
    from models.activity import ActivityBubble, ToolStatus
    is_error = (hasattr(result, "error") and result.error) or (hasattr(result, "success") and not result.success)
    duration_ms = getattr(result, "duration_ms", 0) or 0
    self._on_activity_bubble(ActivityBubble(
        type="tool_error" if is_error else "tool_end",
        session_key=session_key,
        tool_name=name,
        duration_ms=duration_ms,
        icon="❌" if is_error else "✅",
        status=ToolStatus.ERROR if is_error else ToolStatus.SUCCESS,
        agent_name=self._resolve_local_agent_name_for(session_key),
    ))
```

Where `_resolve_local_agent_name_for` is a small helper on AgentRuntimeHandler reusing the existing `self._agents.get(session_key)` lookup (mirror `get_agent_name_for_session` at line 548). If `agent_name` is already in scope in `_do_tool_call_result`, use it directly.

### B.4 Emit patch bubbles for write_file success

In `_do_tool_call_result`, when `name == "write_file"` and the result indicates success (the existing check at ~line 1100: `result.startswith("OK")`), also emit a `patch` bubble:

```python
# NEW: activity-drawer patch bubble for write_file
if name == "write_file" and isinstance(result, str) and result.startswith("OK") and self._on_activity_bubble is not None:
    from models.activity import ActivityBubble, ToolStatus
    path = args.get("path", "") if isinstance(args, dict) else ""   # capture args at start
    self._on_activity_bubble(ActivityBubble(
        type="patch",
        session_key=session_key,
        tool_name="write_file",
        file_path=path,
        modified=1,
        icon="✏️",
        status=ToolStatus.SUCCESS,
        agent_name=<resolved>,
    ))
```

NOTE: `args` is not passed to `_do_tool_call_result` today (signature is `(session_key, name, result)`). To get the file path for the patch bubble, either (a) store `args` from `_on_tool_call_start` in a `self._pending_tool_args[session_key]` dict (same pattern as `self._pending_exec_commands`), or (b) skip `file_path` enrichment and leave it empty. Option (a) is preferred — the drawer shows the path.

### B.5 Emit drawer-lifecycle from agent start/end

The existing `_on_agent_start_cb` and `_on_agent_end_cb` (fired at lines 944 and 1328/1587) currently route ONLY to `ActivityHandler` (the top progress bar). Add a parallel drawer-separator fire:

At agent-start site (~line 944), after the existing `_on_agent_start_cb(session_key)` call:
```python
if self._on_drawer_lifecycle is not None:
    agent_name = self._resolve_local_agent_name_for(session_key)
    self._on_drawer_lifecycle(session_key, agent_name, "start")
```

At BOTH agent-end sites (lines 1328 and 1587), after the existing `_on_agent_end_cb(session_key)` call:
```python
if self._on_drawer_lifecycle is not None:
    agent_name = self._resolve_local_agent_name_for(session_key)
    self._on_drawer_lifecycle(session_key, agent_name, "end")
```

---

## Dedup Strategy (Online + Local)

When BOTH the gateway AND the local runtime are active for the same session, a tool call could produce two drawer bubbles (one from the gateway `item` event, one from local `_do_tool_call_result`).

**Rule:** Local bridges fire ONLY for special-agent sessions. Gateway bridges fire for gateway sessions. They are naturally disjoint because:
- Local special agents have session keys like `special:coder` and route through `AgentRuntimeHandler` (never the gateway — see §3.21v: *"local AgentRuntime agents never hit the gateway"*).
- Gateway agents have gateway-assigned session keys and route through `on_gateway_event`.

**No explicit dedup code is needed.** The session-key namespaces do not overlap. Add a comment in `activity_wiring_handler.wire()` documenting this invariant. If a future architecture change violates this, the drawer's existing counter-collapse will visually merge duplicates — but the invariant should hold.

---

## Offline Agent-Name Resolution

`ActivityHandler._resolve_agent_name` (activity_handler.py:242) uses `self._agent_mgr.get_name(session_key)` — unavailable offline (AgentManager is set in `sync()` from the gateway).

The local path does NOT go through `ActivityHandler._resolve_agent_name` — it resolves names via `AgentRuntimeHandler.get_agent_name_for_session()` (already exists, line 548). This works offline because it reads the local `self._agents` registry, not the gateway AgentManager.

For the gateway path (still going through `ActivityHandler._activity_bubble_callback`), `_resolve_agent_name` is still used and still requires `agent_mgr`. This is fine — the gateway path only fires online. No change needed.

---

## Tests — `tests/test_activity_wiring_handler.py` (NEW FILE)

Follow the pattern in `tests/test_connection_sync_handler.py`. Mock the three dependencies. Test:

1. `test_wire_sets_all_callbacks` — after `.wire()`, assert `activity_handler.set_on_activity_bubble`, `set_on_agent_lifecycle`, `agent_runtime_handler.set_on_command_output`, `set_on_activity_bubble`, `set_on_drawer_lifecycle` were each called once.
2. `test_on_activity_bubble_routes_to_drawer_append_event` — build an `ActivityBubble`, call `_on_activity_bubble`, assert `drawer.append_event` called with `bubble.to_drawer_row()`.
3. `test_on_agent_lifecycle_start_calls_drawer_on_agent_start` — call `_on_agent_lifecycle(sk, "Coder", "start")`, assert `drawer.on_agent_start` called.
4. `test_on_agent_lifecycle_end_calls_drawer_on_agent_end` — symmetric for "end".
5. `test_on_local_command_output_builds_command_output_bubble` — call `_on_local_command_output(sk, "ls", "file.txt", 0, 12)`, assert `drawer.append_event` called with a dict whose `activity_type == "command_output"` and `agent` resolved via the runtime.
6. `test_on_local_activity_bubble_enriches_missing_agent_name` — build a bubble with `agent_name=""`, call `_on_local_activity_bubble`, assert the drawer row's `agent` field is the resolved name (not "").
7. `test_on_local_drawer_lifecycle_start_end` — both phases route to the drawer.
8. `test_resolve_local_agent_name_uses_runtime_registry` — patch `agent_runtime_handler.get_agent_name_for_session`, assert the wiring handler uses it.
9. `test_resolve_local_agent_name_falls_back_to_Agent_when_unknown` — runtime returns `""` → resolved name is `"Agent"`.

### Local-agent bubble emission tests — extend `tests/test_agent_runtime_handler.py`

10. `test_do_tool_call_start_emits_tool_start_bubble` — set `_on_activity_bubble`, call `_do_tool_call_start`, assert callback received an `ActivityBubble` with `type=="tool_start"`.
11. `test_do_tool_call_result_emits_tool_end_bubble` — symmetric; assert `type=="tool_end"` on success.
12. `test_do_tool_call_result_emits_tool_error_on_failure` — simulate a failed result, assert `type=="tool_error"`.
13. `test_do_tool_call_result_emits_patch_for_write_file_success` — `name=="write_file"`, success result → `type=="patch"`.
14. `test_agent_start_emits_drawer_lifecycle_start` — assert `_on_drawer_lifecycle` called with phase `"start"`.
15. `test_agent_end_emits_drawer_lifecycle_end` — both end sites (normal completion + error path).

### Regression — `tests/test_connection_sync_handler.py`

16. Update the existing test that asserted `set_activity_drawer` + sync wired the adapters. After this change, `sync()` no longer wires drawer adapters. The test should assert `sync()` still calls `activity_handler.set_agent_manager` but does NOT call `set_on_activity_bubble`. Remove the now-obsolete drawer-wiring assertions.

---

## Architecture Doc Updates (REQUIRED — same change per project conventions)

Per the project convention *"ARCHITECTURE.md is the law — must be updated in the same commit as any structural code change"*, update:

1. **§3.23 (activity_handler.py)** — change the sentence *"the adapter that converts the dataclass to the drawer's dict shape lives in `connection_sync_handler.sync()`"* to reference the new `activity_wiring_handler`.
2. **§3.21y (connection_sync_handler.py)** — note that drawer wiring has moved out; `sync()` now only sets `agent_manager` on the activity handler.
3. **Add §3.21za (or next number) for `activity_wiring_handler.py`** — document responsibility (single owner of activity→drawer routing, online + offline), constructor deps, and the `.wire()` method.
4. **§2 directory tree** — add the new file.
5. **§3.21v (agent_runtime_handler.py)** — document the new `set_on_activity_bubble` / `set_on_drawer_lifecycle` callbacks and that local agents now emit drawer events.

---

## Summary of File Changes

| File | Change |
|---|---|
| `ui/handlers/activity_wiring_handler.py` | **NEW** — owns all activity→drawer wiring |
| `ui/handlers/agent_runtime_handler.py` | Add 2 callback slots + setters; emit bubbles in `_do_tool_call_start/result` and agent start/end sites |
| `ui/handlers/connection_sync_handler.py` | Remove `set_activity_drawer`, the `_activity_drawer` attr, and the 3 adapter closures from `sync()`; keep `set_agent_manager` |
| `ui/window.py` | Construct `ActivityWiringHandler`, call `.wire()` at startup; remove the `set_activity_drawer` call |
| `tests/test_activity_wiring_handler.py` | **NEW** — 9 tests |
| `tests/test_agent_runtime_handler.py` | +6 tests for local bubble/lifecycle emission |
| `tests/test_connection_sync_handler.py` | Update regression test (sync no longer wires drawer) |
| `docs/ARCHITECTURE.md` | Update §3.23, §3.21y, §3.21v; add new section for `activity_wiring_handler.py` |

---

## Edge Cases

1. **Offline startup** — `.wire()` runs before any gateway; `_resolve_agent_name` on the gateway path will return "" until `set_agent_manager` is called in `sync()`. Gateway bubbles simply show blank/`"Agent"` name until then — acceptable, since no gateway events arrive offline anyway.
2. **Double `.wire()` calls** — make `.wire()` idempotent (safe to call twice; just re-sets callbacks).
3. **`agent_runtime_handler` is `None` at wiring time** — `window.py` constructs it before the drawer, so this won't happen, but the wiring handler's methods should null-check defensively.
4. **`_pending_tool_args` for patch path** — must be cleared in `_do_tool_call_result` to avoid stale-path bleed across tool calls in the same session (mirror `_pending_exec_commands.pop`).
5. **Existing exec_command bubble still works** — the `_on_local_command_output` adapter preserves the exact same `ActivityBubble(type="command_output")` shape as the old sync() closure; only its location changes.

---

## Verification Steps After Implementation

1. `pytest tests/test_activity_wiring_handler.py -v` — all 9 pass.
2. `pytest tests/test_agent_runtime_handler.py -v` — existing + 6 new pass.
3. `pytest tests/test_connection_sync_handler.py -v` — updated regression passes.
4. `python3 -m py_compile ui/handlers/activity_wiring_handler.py ui/handlers/agent_runtime_handler.py ui/handlers/connection_sync_handler.py ui/window.py` — all compile.
5. Manual: run the app offline (no gateway), open a project, send a message to Coder, observe the Activity Drawer populate with tool_start/tool_end/patch/command_output rows and start/end separators.
