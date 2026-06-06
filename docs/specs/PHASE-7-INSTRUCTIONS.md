# PHASE 7 — Fix Bug #4 (data: null crash) + Bug #7 (callback signature drift)

**Date:** 2026-06-05
**Supervisor:** Qaster (using `implementationSupervisor` prompt exactly)
**Builder:** QTR (using `steelFramedCodeWriter` prompt exactly)
**Auditor:** Qaster (using `adversarialDebugger` prompt exactly)
**Source spec:** `docs/specs/SPEC-activity-drawer.md` §2.4, §2.5
**Source audit:** `docs/post-mortems/2026-06-05-SPEC-activity-drawer-AUDIT.md` (initial) + QTR's bug investigation 2026-06-05 22:55
**Predecessor:** PHASE 1-6 complete (9 commits, 56/56 tests pass, pushed to origin/main)

## Background

QTR ran an adversarial investigation and found 2 real bugs in the PHASE 1-6 work that I missed in my own audits. Both are real, both are fixable in this phase.

## Bugs Being Fixed

### Bug #4 (CRITICAL): `data: null` crashes the handler

**Reproduction:**
```python
handler.on_gateway_event("agent", {
    "stream": "item",
    "sessionKey": "sk-1",
    "runId": "r-1",
    "data": None,  # explicit null
})
# → AttributeError: 'NoneType' object has no attribute 'get'
```

**Root cause:** 8 call sites in `ui/handlers/activity_handler.py` use the pattern:
```python
data = payload.get("data", {})  # ← falls back to {} if MISSING, but {} if data is explicitly None
data.get("phase", "")  # ← crashes if data is None
```

The `or {}` default only fires when the key is **missing**. When the key is **present but null** (`data: None`), the default is bypassed and `data` becomes `None`, then `.get()` crashes.

**Fix:** Add a helper method `_safe_data(payload)` that returns `{}` whether the key is missing OR present-with-null:
```python
def _safe_data(self, payload: dict) -> dict:
    """Safely extract payload.data — handles both missing and explicit null."""
    data = payload.get("data")
    return data if isinstance(data, dict) else {}
```

Then replace `payload.get("data", {})` with `self._safe_data(payload)` at all 8 call sites.

### Bug #7 (issue): `set_on_command_output` callback signature drift

**Current state:** `agent_runtime_handler.py:108` declares:
```python
self._on_command_output: Callable[[str, str, str], None] | None = None
```
3 args: `(session_key, command, output)`.

**Spec §2.5 says:** 5 args: `(session_key, command, output, exit_code, duration_ms)`.

**Current impact:** `exit_code` and `duration_ms` are LOST in the local exec path. The drawer's `command_output` row will have `exit_code: None` always, which means the spec's "✓ 0 / ✗ N" exit badge never shows for local execs.

**Fix:** Update the signature to 5 args. Thread the values through the firing site in `_do_tool_call_result` (around line 651-665). Update the adapter in `connection_sync_handler.py:198` to accept the new args and pass them into the `ActivityBubble`.

## Files to change (2 files, 1 sub-phase)

### 1. `ui/handlers/activity_handler.py` — Bug #4 fix

#### Change 1a: Add `_safe_data` helper

Add a new method to the `ActivityHandler` class. Place it near the other private helpers (around line 200, near `_resolve_agent_name`).

#### Change 1b: Replace all 8 `payload.get("data", {})` sites

There are 8 occurrences. Each is in one of these forms:
- `data = payload.get("data", {})` then `data.get("phase", "")` etc.
- `payload.get("data", {}).get("xxx", default)` (inline)

For the first form, change to:
```python
data = self._safe_data(payload)
```

For the inline form, change to:
```python
self._safe_data(payload).get("xxx", default)
```

**The 8 call sites** (verify with `grep -n 'payload.get("data", {})' ui/handlers/activity_handler.py`):
- ~line 268: `if stream == "assistant":` branch
- ~line 281: `if stream == "lifecycle":` branch
- ~line 290: `_resolve_agent_name` (inside the helper)
- ~line 312: `elif stream == "item":` branch (the `data = payload.get("data", {})` line)
- ~line 353: `elif stream == "plan":` branch
- ~line 364: `elif stream == "approval":` branch
- ~line 376: `elif stream == "patch":` branch
- (one more — verify by grep)

QTR's discovery step should confirm the exact 8 sites.

### 2. `ui/handlers/agent_runtime_handler.py` — Bug #7 fix

#### Change 2a: Update `set_on_command_output` type annotation

Line 108:
```python
self._on_command_output: Callable[[str, str, str], None] | None = None
```
Change to:
```python
self._on_command_output: Callable[[str, str, str, int, int], None] | None = None
```

#### Change 2b: Update the firing site in `_do_tool_call_result`

Around line 651-665, where the callback is invoked. Currently it passes 3 args. Update to pass 5:
```python
if name == "exec_command" and self._on_command_output is not None:
    cmd = self._pending_exec_commands.pop(session_key, "")
    output_text = ""
    exit_code = 0
    duration_ms = 0
    if hasattr(result, "output") and result.output:
        output_text = result.output
    elif isinstance(result, str):
        output_text = result
    if hasattr(result, "exit_code"):
        exit_code = result.exit_code
    if hasattr(result, "duration_ms"):
        duration_ms = result.duration_ms
    # Tail to last 10 lines (matches drawer's OUTPUT_LINE_CAP)
    lines = output_text.splitlines()
    tail = "\n".join(lines[-10:]) if lines else ""
    self._on_command_output(session_key, cmd, tail, exit_code, duration_ms)
```

**Discovery first:** QTR should verify the exact shape of `ToolResult` (look at `agent/tools.py` for the dataclass definition) so `hasattr` checks use the right attribute names.

### 3. `ui/handlers/connection_sync_handler.py` — Bug #7 fix (adapter update)

The adapter at line 198 builds an `ActivityBubble` from the callback args. Update to use the new exit_code and duration_ms:

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

The `ActivityBubble(type="command_output", ...)` constructor already accepts `exit_code` and `duration_ms` as fields — no model changes needed.

## Rules for the builder

- **You MUST use the `steelFramedCodeWriter` prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md` exactly as written — no deviation.** Begin your response with: "Starting Discovery Phase — reading all relevant files before writing any code."
- Discovery is mandatory: re-read `ui/handlers/activity_handler.py` (full file) to find the 8 sites, `ui/handlers/agent_runtime_handler.py` lines 600-680 to find the firing site, and `agent/tools.py` to confirm the `ToolResult` shape.
- Maximum 15 lines of code per checkpoint, then verify.
- Do NOT modify any other file. This phase is the 3 listed files ONLY.
- Do NOT change the `ActivityBubble` dataclass — its fields are already correct.
- Do NOT change the `_resolve_agent_name` helper's behavior — it already handles `data: null` correctly (uses `payload.get("data", {}).get(...)` which would crash on null data — fix that as part of Change 1b).

## Verification (run yourself, paste output in your report)

```bash
# 1. _safe_data helper exists
grep -n "_safe_data" ui/handlers/activity_handler.py
# Expected: 1+ definition match + 8 call site matches

# 2. No more raw `payload.get("data", {})` patterns in activity_handler.py
grep -nE 'payload\.get\(["'\'']data["'\'']\s*,\s*\{\}\)' ui/handlers/activity_handler.py
# Expected: 0 matches

# 3. set_on_command_output is now 5-arg
grep -n "set_on_command_output" ui/handlers/agent_runtime_handler.py
# Expected: type annotation shows Callable[[str, str, str, int, int], None]

# 4. Firing site passes 5 args
grep -n "_on_command_output(" ui/handlers/agent_runtime_handler.py
# Expected: shows 5-arg call

# 5. Connection_sync_handler adapter uses 5 args
grep -n "_on_command_output" ui/handlers/connection_sync_handler.py
# Expected: shows 5-arg call with exit_code, duration_ms

# 6. data: null no longer crashes
cd /home/q/projects/crabcakes && python3 -c "
import sys
sys.path.insert(0, '.')
from unittest.mock import MagicMock
from ui.handlers.activity_handler import ActivityHandler
handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=MagicMock())
try:
    handler.on_gateway_event('agent', {'stream': 'item', 'sessionKey': 'sk-1', 'runId': 'r-1', 'data': None})
    print('PASS: data=None no longer crashes')
except AttributeError as e:
    print(f'FAIL: still crashes: {e}')
"
# Expected: PASS

# 7. Existing 56 tests still pass
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py -q
# Expected: 56 passed (then +2 for new regression tests = 58)

# 8. AST parse
python3 -c "import ast; ast.parse(open('ui/handlers/activity_handler.py').read()); print('activity_handler.py: PARSE OK')"
python3 -c "import ast; ast.parse(open('ui/handlers/agent_runtime_handler.py').read()); print('agent_runtime_handler.py: PARSE OK')"
python3 -c "import ast; ast.parse(open('ui/handlers/connection_sync_handler.py').read()); print('connection_sync_handler.py: PARSE OK')"

# 9. App still starts
cd /home/q/projects/crabcakes && timeout 3 python3 main.py 2>&1 | head -5
# Expected: clean exit
```

## Required new tests (Bug #4 + Bug #7 each get 1 regression test)

### Test 1: Bug #4 regression — `data: null` doesn't crash

Add to `tests/test_activity_bubbles.py` in `TestActivityHandlerActivityBubbles`:

```python
def test_data_null_does_not_crash(self, fake_glib):
    """Gateway payload with data=None must not crash the handler (PHASE 7 Bug #4)."""
    from ui.handlers.activity_handler import ActivityHandler
    handler = ActivityHandler(feedbar=MagicMock(), main_content=MagicMock(), GLib_module=fake_glib)
    cb = MagicMock()
    handler.set_on_activity_bubble(cb)
    
    # Should not raise
    try:
        handler.on_gateway_event("agent", {
            "stream": "item",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": None,  # explicit null
        })
        handler.on_gateway_event("agent", {
            "stream": "lifecycle",
            "sessionKey": "sk-1",
            "runId": "r-1",
            "data": None,
        })
    except Exception as e:
        pytest.fail(f"handler crashed on data=None: {e}")
```

### Test 2: Bug #7 regression — `set_on_command_output` fires with 5 args

Add to `tests/test_activity_bubbles.py` (or wherever appropriate):

```python
def test_set_on_command_output_5_args(self, fake_glib):
    """AgentRuntimeHandler fires set_on_command_output with 5 args (PHASE 7 Bug #7)."""
    # Verify the type annotation accepts the 5-arg signature
    import inspect
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
    src = inspect.getsource(AgentRuntimeHandler)
    assert "Callable[[str, str, str, int, int]" in src, \
        "set_on_command_output signature should be 5 args per spec §2.5"
```

## Report format

```
COMPLETENESS:
- [x/not done] Bug #4 Fix 1a: added _safe_data helper — evidence (line number, grep)
- [x/not done] Bug #4 Fix 1b: replaced 8 call sites with _safe_data — evidence (grep showing 0 matches for old pattern)
- [x/not done] Bug #7 Fix 2a: updated set_on_command_output type annotation to 5 args — evidence (line number)
- [x/not done] Bug #7 Fix 2b: updated firing site in _do_tool_call_result to pass 5 args — evidence (line number)
- [x/not done] Bug #7 Fix 3: updated connection_sync_handler adapter for 5 args — evidence (line number)
- [x/not done] Test 1: added test_data_null_does_not_crash — evidence (test passes)
- [x/not done] Test 2: added test_set_on_command_output_5_args — evidence (test passes)
- [x/not done] Test result: pytest tests/test_activity_bubbles.py tests/test_activity_drawer.py — paste full output (expect 58)
- [x/not done] App still starts — paste output
- [x/not done] Manual test: data=None no longer crashes — paste output
```

## After QTR reports done

Qaster will:
1. Re-verify all commands above
2. Run adversarialDebugger with mutation tests (e.g., break the helper back to non-safe, confirm test catches it)
3. Commit if clean (Qaster author per Captain's authorization)
4. Push to origin/main
5. Write post-mortem
