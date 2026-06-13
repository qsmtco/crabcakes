# Fix Proposal: Enforcement Per-Project Config + Stuck Detection Bugs (3-7)

**Date:** 2026-05-09  
**Author:** Qaster  
**Status:** READY FOR IMPLEMENTATION  
**Scope:** 5 bugs found during adversarial review of Phase 6 code

> **Status (verified 2026-06-12):** ⚠️ **PARTIALLY DONE** — `agent/enforcement.py` is 29K (was likely smaller at proposal time), indicating active development, and `enforcement.json` is a per-project config override per `agent/enforcement.py:199`. However, no commit in the visible log explicitly closes "Bugs 3–7" with this proposal as the fix; the proposal pre-dates several other enforcement rewrites. **Verification per-bug is needed** — the proposal listed 5 specific bugs (3, 4, 5, 6, 7) but the codebase doesn't have explicit references to those bug numbers. **Marked partial pending per-bug audit.**

---

## Bug #3 — HIGH: Enforcement Per-Project Override Loads AFTER Tier 1 Syntax Check

### Problem

In `agent/enforcement.py` function `check()` (lines ~518-548), the per-project enforcement config (`_load_project_enforcement_config`) is loaded and applied **after** Tier 1 (syntax check) has already executed. The config override sets `config.syntax_check=False` at line ~543, but syntax already ran at lines ~519-521.

**Current code order:**
```python
# Line 519: Tier 1 runs with ORIGINAL config — project override not yet loaded
if config.syntax_check:
    syntax_result = _check_syntax(file_path, project_path, config)
    ...

# Line 533: NOW we load the project override — TOO LATE for Tier 1
project_override = _load_project_enforcement_config(project_path)
if project_override is not None:
    if not project_override.get("syntax_check", True):
        config = dataclasses.replace(config, syntax_check=False)  # doesn't affect Tier 1 that already ran
```

**Result:** If a project's `.crabcakes/enforcement.json` sets `syntax_check: false`, syntax still runs on every write. Only Tier 2 (tests) and Tier 3 (lint) are actually affected by the override.

### Fix

Move the per-project config loading to **before** all tier checks. The entire `check()` function should follow this order:

```
1. Early-exit guards (not a write tool, write failed, no file path)
2. Load per-project override and apply to config
3. Tier 1: Syntax check (using overridden config)
4. Determine syntax gate
5. Tier 2: Test runner (using overridden config)
6. Tier 3: Lint check (using overridden config)
7. Format and return result
```

### Specific Changes

**File:** `agent/enforcement.py`

Move the block at lines 533-548 (project override loading) to **before** line 519 (Tier 1 syntax check). The moved block should sit between the `file_path` empty check and the Tier 1 check:

```python
    file_path = tool_args.get("path", "")
    if not file_path:
        return EnforcementResult()

    # §F — Per-project override: load BEFORE any tier checks
    project_override = _load_project_enforcement_config(project_path)
    if project_override is not None:
        project_skip = project_override.get("skip_patterns")
        if project_skip and isinstance(project_skip, list):
            merged_skip = list(config.skip_patterns) + project_skip
        else:
            merged_skip = config.skip_patterns
        if not project_override.get("syntax_check", True):
            config = dataclasses.replace(config, syntax_check=False)
        if not project_override.get("test_run", True):
            config = dataclasses.replace(config, test_run=False)
        if not project_override.get("lint_check", True):
            config = dataclasses.replace(config, lint_check=False)
        config = dataclasses.replace(config, skip_patterns=merged_skip)

    checks: list[EnforcementCheck] = []

    # Tier 1: Syntax guard (now uses overridden config)
    if config.syntax_check:
        syntax_result = _check_syntax(file_path, project_path, config)
        ...
```

**No other changes needed.** The rest of `check()` stays the same.

### Architecture Alignment

Per ARCHITECTURE.md §3.21m: `check(tool_name, tool_args, tool_result, project_path, config) → EnforcementResult`. The function signature doesn't change. The only change is internal ordering — the project override is now applied before it can affect all three tiers. This is what the docstring already claims it does.

### Verification

Test: `tests/test_agent_runtime.py::TestPerProjectEnforcement::test_project_config_disable_tier`

This test creates `enforcement.json` with `syntax_check: false` and asserts syntax still runs. **After the fix, this test will FAIL because syntax should NOT run.** Update the test assertion:

```python
# Before fix (current — test is wrong):
assert "syntax" in tiers_run, "Syntax should still run"

# After fix (correct):
assert "syntax" not in tiers_run, "Syntax should be disabled by project config"
```

The `test_project_config_merge_skip_patterns` test should still pass unchanged.

---

## Bug #4 — HIGH: Enforcement Config File Read on Every Write

### Problem

`_load_project_enforcement_config()` opens and reads `.crabcakes/enforcement.json` from disk on **every single `write_file` or `edit_file` call**. During a coding session, Coder might write 20-50 files. That's 20-50 `os.path.isfile()` + `open()` + `json.load()` calls on a file that rarely changes.

### Fix

Add a simple in-memory cache to `_load_project_enforcement_config()` with a TTL of 30 seconds. This is the lightest-weight approach — no file watcher, no invalidation callbacks, just a time-based cache.

### Specific Changes

**File:** `agent/enforcement.py`

Add a module-level cache dict and TTL constant above `_load_project_enforcement_config()`:

```python
# ── Per-project enforcement config cache ──────────────────────────────────

_ENFORCEMENT_CONFIG_CACHE: dict[str, tuple[float, dict]] = {}
_ENFORCEMENT_CONFIG_TTL = 30.0  # seconds
```

Rewrite `_load_project_enforcement_config()`:

```python
def _load_project_enforcement_config(project_path: str) -> dict | None:
    """
    §F — Load per-project enforcement override from .crabcakes/enforcement.json.

    Results are cached for 30 seconds to avoid reading the file on every write.
    Priority: .crabcakes/enforcement.json > agent.json enforcement section > defaults.

    Returns parsed dict or None if file doesn't exist / can't be read.
    """
    now = time.monotonic()
    cached = _ENFORCEMENT_CONFIG_CACHE.get(project_path)
    if cached is not None:
        ts, data = cached
        if now - ts < _ENFORCEMENT_CONFIG_TTL:
            return data

    cfg_path = os.path.join(project_path, ".crabcakes", "enforcement.json")
    if not os.path.isfile(cfg_path):
        # Cache the None result too (file doesn't exist)
        _ENFORCEMENT_CONFIG_CACHE[project_path] = (now, None)
        return None
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _ENFORCEMENT_CONFIG_CACHE[project_path] = (now, data)
        return data
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("[enforcement] per-project config unreadable: %s", e)
        _ENFORCEMENT_CONFIG_CACHE[project_path] = (now, None)
        return None
```

**Key points:**
- `time.monotonic()` is already imported (used elsewhere in the module). If not, add it.
- Cache key is `project_path` (unique per project).
- `None` results are cached too — avoids repeated `isfile()` checks for projects without the config.
- TTL of 30 seconds means changes to `enforcement.json` take effect within 30 seconds. Acceptable for a config file.
- No thread safety concern — `_load_project_enforcement_config` is called from the tool loop thread within `AgentRuntime`, and each runtime has its own thread. Even if two threads access the cache simultaneously, the worst case is a stale read or a duplicate file read, not data corruption. Python's GIL protects dict operations.

### Architecture Alignment

Per ARCHITECTURE.md §3.21m: enforcement is "Pure logic — no UI imports, no GTK." The cache uses only `time` and `os` — no new dependencies. The public API (`check()`) doesn't change.

### Verification

The existing `TestPerProjectEnforcement` tests should still pass — they create the file, call `check()`, and assert results. The cache won't interfere because each test uses a fresh `tmp_path` that's not in the cache.

---

## Bug #5 — MEDIUM: `_tool_history` Not Thread-Safe

### Problem

`_tool_history` in `agent/runtime.py` is a plain `dict` accessed from the tool loop thread via `_check_stuck()` and `_cleanup_tool_history()`. The runtime uses `self._lock` (a `threading.Lock`) for thread safety on other shared state (conversations dict, running flag), but `_tool_history` operations bypass the lock entirely.

**Unsynchronized operations:**
- `_check_stuck()`: `self._tool_history.setdefault()`, `history.append()`, list slicing
- `_cleanup_tool_history()`: `self._tool_history.pop()`

Per ARCHITECTURE.md §3.21h: "Thread safety: All callbacks dispatched via `GLib.idle_add()`." But the tool history is shared state mutated in the worker thread, not a callback.

**In practice with CPython's GIL:** Dict operations like `setdefault`, `pop`, and list `append` are atomic at the bytecode level, so real data corruption is unlikely. However, the code violates the thread-safety contract documented in ARCHITECTURE.md.

### Fix

Use a dedicated `threading.Lock` for `_tool_history`. Don't reuse `self._lock` — that lock protects conversations and runtime state, and acquiring it in the tool loop could cause deadlocks with `cancel()`.

### Specific Changes

**File:** `agent/runtime.py`

1. Add a new lock in `__init__()` (after `self._tool_history` declaration):

```python
        # §E: Stuck detection — per-session tool call history for detecting loops
        # session_key → list[dict{"tool", "args_hash", "iteration"}]
        self._tool_history: dict[str, list[dict]] = {}
        self._tool_history_lock = threading.Lock()
```

2. Wrap `_check_stuck()` body:

```python
    def _check_stuck(self, session_key: str, tool_name: str, args: dict, iteration: int) -> str | None:
        with self._tool_history_lock:
            history = self._tool_history.setdefault(session_key, [])
            args_str = str(sorted(args.items()))
            args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
            history.append({"tool": tool_name, "args_hash": args_hash, "iteration": iteration})

            if len(history) > 20:
                history[:] = history[-20:]

            # Check 1: same tool + same args 3+ times in last 10
            recent = history[-10:]
            same_count = sum(
                1 for e in recent
                if e["tool"] == tool_name and e["args_hash"] == args_hash
            )
            if same_count >= 3:
                return (
                    f"[stuck-detection] You've called {tool_name} with the same arguments "
                    f"{same_count} times in recent iterations. You appear to be stuck. "
                    f"Consider: re-reading the file, checking the error message carefully, "
                    f"or trying a completely different approach. "
                    f"If you've tried 3+ approaches without progress, report as blocked."
                )

            # Check 2: 8+ write operations with no verification commands
            recent_tools = [e["tool"] for e in recent]
            write_ops = recent_tools.count("write_file") + recent_tools.count("edit_file")
            if write_ops >= 8 and "exec_command" not in recent_tools[-8:]:
                return (
                    "[stuck-detection] You've written files 8+ times without running any "
                    "commands to verify. Run tests or check syntax before continuing."
                )

            return None
```

3. Wrap `_cleanup_tool_history()`:

```python
    def _cleanup_tool_history(self, session_key: str) -> None:
        with self._tool_history_lock:
            self._tool_history.pop(session_key, None)
```

**Important:** The entire `_check_stuck()` method runs inside the lock. This is fine because:
- The method is fast (list operations, no I/O, no blocking calls)
- It's called once per tool invocation (not in a tight loop)
- The lock is specific to `_tool_history` — no risk of deadlock with `self._lock`

### Architecture Alignment

Per ARCHITECTURE.md §3.21h: the runtime uses `threading.Lock` for shared state. This adds a second lock following the same pattern.

### Verification

The existing `TestStuckDetection` tests should still pass — they run in a single thread, so the lock adds no overhead. No test changes needed.

---

## Bug #6 — MEDIUM: Stuck Detection Message Pollutes Tool Output

### Problem

The stuck detection message is appended directly to the tool's `output` field via string concatenation:

```python
# agent/runtime.py lines ~1068-1072
if stuck_msg:
    result = dataclasses.replace(
        result,
        output=(result.output or "") + "\n" + stuck_msg,
    )
```

If `read_file` returns file contents and stuck fires, the LLM sees:

```
<contents of main.py>
[stuck-detection] You've called read_file with the same arguments 3 times...
```

This pollutes the tool output. The LLM might interpret the stuck message as part of the file contents, or have trouble distinguishing tool result from intervention.

Compare with how the enforcement layer handles this — it uses a separate `appended_message` field on `EnforcementResult`. The stuck detection should follow the same pattern.

### Fix

Instead of polluting `result.output`, add the stuck message as a **separate conversation message** after the tool result. The tool loop already has the machinery for this — it appends messages to the conversation. The stuck message should be injected as a system-level note.

### Specific Changes

**File:** `agent/runtime.py`

Replace the stuck detection output pollution (lines ~1067-1072):

```python
                    # Current (BAD — pollutes tool output):
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        result = dataclasses.replace(
                            result,
                            output=(result.output or "") + "\n" + stuck_msg,
                        )
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)
```

With:

```python
                    # §E: Stuck detection — record this tool call and check for loops
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        # Inject as a separate system note, not appended to tool output
                        conv.add_tool_result(
                            call_id,
                            f"{tc.result or ''}\n\n---\n⚠️ {stuck_msg}",
                        )
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)
```

**Wait — that still modifies the tool result string.** Let me think about this differently.

Actually, the cleanest approach that doesn't require changing data models: inject the stuck message as a **fake tool result** by appending it to the message that gets sent back to the LLM. The key insight is that `conv.add_tool_result()` already concatenates the tool result. Instead of polluting `result.output` (which goes into `tc.mark_completed()` and then `conv.add_tool_result()`), we should append the stuck message AFTER the tool result is recorded.

**Better approach:** Keep `result.output` clean. After the tool result is recorded and added to the conversation, append the stuck message as an additional note:

```python
                    # §E: Stuck detection — record this tool call and check for loops
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)
                    if stuck_msg:
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)

                    tc.mark_completed(result.output if result.success else result.error or "")
                    conv.add_tool_result(call_id, tc.result or "")
```

Then, after the tool results are added to the conversation (after the `for tool_call` loop), add the stuck message as an injected system note. Find the point after all tool results are processed but before the next LLM call:

```python
                    # After tc.mark_completed and conv.add_tool_result:
                    if stuck_msg:
                        # Append as a note after the tool result
                        conv.add_message("system", stuck_msg)
```

**Actually, simplest correct fix:** The `conv.add_tool_result()` method concatenates text into the tool result message. The current approach of appending to `result.output` means it flows through `tc.mark_completed()` → `conv.add_tool_result()`. This is actually fine functionally — the message gets to the LLM. The issue is aesthetic: it pollutes the `ToolResult` dataclass.

The simplest fix that keeps the message reaching the LLM but doesn't pollute `result.output`:

```python
                    # §E: Stuck detection
                    stuck_msg = self._check_stuck(session_key, tool_name, args, iteration)

                    tc.mark_completed(result.output if result.success else result.error or "")

                    # Inject stuck detection AFTER tool result is recorded cleanly
                    if stuck_msg:
                        stuck_result = tc.result + "\n\n---\n⚠️ " + stuck_msg
                        conv.add_tool_result(call_id, stuck_result)
                        logger.warning("[stuck-detection] sk=%s: %s", session_key, stuck_msg)
                    else:
                        conv.add_tool_result(call_id, tc.result or "")
```

This keeps `result.output` and `tc.result` clean — the stuck message is only added when writing to the conversation. The `ToolResult` dataclass is untouched.

**BUT WAIT** — I need to check if `conv.add_tool_result()` appends or overwrites. If it appends, we'd get duplicate results.

Let me reconsider. Looking at the code flow:

```python
tc.mark_completed(result.output if result.success else result.error or "")
conv.add_tool_result(call_id, tc.result or "")
```

If `conv.add_tool_result()` overwrites the tool result for `call_id`, then the approach above works. If it appends, we'd get the clean result + the stuck-augmented result.

### Recommended Minimal Fix

The safest approach: just move the stuck message appending to AFTER `tc.mark_completed()` and `conv.add_tool_result()`, by injecting it as an additional message in the conversation. Check if `Conversation` has an `add_message()` method:

```python
# After existing:
tc.mark_completed(result.output if result.success else result.error or "")
conv.add_tool_result(call_id, tc.result or "")

# Stuck detection — inject as system note (separate from tool output)
if stuck_msg:
    conv.messages.append({
        "role": "system",
        "content": stuck_msg,
    })
    logger.warning(...)
```

**However**, this depends on how `conv.messages` is structured. The implementer should check `models/conversation.py` for the correct way to inject a system-level note.

### Fallback Simpler Fix

If injecting a separate message is too complex (depends on conversation internals), the current approach of appending to `result.output` is **functionally correct** — it just mixes tool output with intervention text. If the team decides this is acceptable, no change is needed. The `---` separator would help:

```python
if stuck_msg:
    result = dataclasses.replace(
        result,
        output=(result.output or "") + "\n\n---\n⚠️ " + stuck_msg,
    )
```

**Implementer:** Check `models/conversation.py` to understand the conversation message format. If there's a clean way to inject a system note, use that. If not, add the `⚠️` and `---` separator to the current approach and move on.

---

## Bug #7 — MEDIUM: `agent_role` Derivation is Fragile

### Problem

In the previous fix (Bug #1 group broadcast), special agents are now correctly routed through `AgentRuntimeHandler.send_to_special_agent()`, which calls `_get_runtime()` → `AgentRuntime()` → `create_conversation()`. The system prompt for special agents is built inside `agent/context.py`'s `build_system_prompt()`:

```python
# agent/context.py line 418
agent_role="coder" if "coder" in agent_name.lower() else "debugger" if "debugger" in agent_name.lower() else ""
```

This uses substring matching (`"coder" in agent_name.lower()`), which works for "Coder" and "Debugger" but is fragile. If a future agent is named "CodeAssistant", the substring "coder" won't match.

The previous version of `_build_awareness_prefix()` (now removed — this method is gateway-only) had a similar issue using `agent_def.display_name.lower()`. That code path no longer exists after Bug #1 fix, so the remaining issue is **only** in `agent/context.py`.

### Fix

Add a `role` field to `SpecialAgentDef` so the role is explicitly declared rather than derived from the display name.

### Specific Changes

**File:** `agent/special_agents.py`

1. Add `role` field to `SpecialAgentDef`:

```python
@dataclass
class SpecialAgentDef:
    """Definition of a built-in Crabcake Special Agent."""
    conv_id_prefix: str           # e.g. "special:coder" — used as session_key
    display_name: str             # e.g. "Coder"
    role: str                     # e.g. "coder" — matches prompts/system/{role}.md
    emoji: str                    # e.g. "🛠️"
    color: str                    # hex color from AGENT_COLORS
    tools: list[str]              # tool names this agent can use
    can_write: bool               # whether write_file is in the default tool set
```

2. Update `SPECIAL_AGENTS` registry:

```python
SPECIAL_AGENTS: dict[str, SpecialAgentDef] = {
    "special:coder": SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        color="#6366f1",
        tools=[...],
        can_write=True,
    ),
    "special:debugger": SpecialAgentDef(
        conv_id_prefix="special:debugger",
        display_name="Debugger",
        role="debugger",
        emoji="🐛",
        color="#f43f5e",
        tools=[...],
        can_write=False,
    ),
}
```

3. **File:** `agent/context.py` line ~418

Change the `agent_role` derivation from substring matching to using the role directly. The caller (`build_system_prompt`) receives `agent_name` (display name), but the `AgentRuntimeHandler.send_to_special_agent()` path already knows the `SpecialAgentDef`.

**Option A (preferred):** Pass `agent_role` explicitly to `build_system_prompt()`.

Update `build_system_prompt()` to accept an optional `agent_role` parameter:

```python
def build_system_prompt(
    agent_name: str,
    project_path: str | None,
    tools: list[str],
    review_mode: str = "off",
    agent_role: str = "",       # NEW — explicit role override
) -> str:
```

Then in the body, use it directly instead of substring matching:

```python
    # Use explicit role if provided, otherwise fall back to name-based detection
    effective_role = agent_role or (
        "coder" if "coder" in agent_name.lower() else
        "debugger" if "debugger" in agent_name.lower() else ""
    )
    prompt = compose_system_prompt(
        agent_name=agent_name,
        agent_role=effective_role,
        ...
    )
```

4. **File:** `ui/handlers/agent_runtime_handler.py`

In `send_to_special_agent()`, pass the role when calling `create_conversation()`:

```python
        if rt.get_conversation(session_key) is None:
            rt.create_conversation(
                agent_name=agent_def.display_name,
                session_key=session_key,
                project_path=project_path,
                allowed_tools=agent_def.tools,
            )
```

Check if `create_conversation()` passes `agent_role` to `build_system_prompt()`. If not, add it:

```python
        conv = Conversation(
            agent_name=agent_name,
            session_key=session_key,
            project_path=project_path,
            system_prompt=build_system_prompt(agent_name, project_path, tool_names, agent_role=???),
            ...
        )
```

The implementer should trace the full path from `create_conversation()` → system prompt building to find where to thread the role through. The key insight: `SpecialAgentDef.role` is the source of truth, and it should flow all the way to `compose_system_prompt()` without any name-based guessing.

### Architecture Alignment

Per ARCHITECTURE.md §3.21l: `SpecialAgentDef` lists its fields. Adding `role` is a non-breaking additive change (the dataclass has no positional-only args in the existing instantiations... wait, actually it does since dataclasses use positional args by field order). **Important:** Since `SpecialAgentDef` is a dataclass, the new `role` field must be added AFTER `display_name` to maintain the existing field order for any positional callers. Check all `SpecialAgentDef(...)` instantiations — if they use keyword args (they do in the registry), insertion order doesn't matter. But if any code creates instances positionally, the field must go at the end.

Looking at the code: both instances in `SPECIAL_AGENTS` use keyword args. The tests also use keyword args. So adding `role` between `display_name` and `emoji` is safe.

### Verification

The `test_prompt_loader.py` tests call `compose_system_prompt(agent_name="Coder", agent_role="coder")` with the role already explicit. These should pass unchanged.

Add a test for the fallback path:
```python
def test_role_fallback_from_name(self):
    """When no explicit role, derive from agent_name."""
    prompt = compose_system_prompt(agent_name="Coder")  # no agent_role
    assert "Coder" in prompt
```

This test should pass both before and after the fix.

---

## Summary

| Bug | File(s) | Change Type | Risk |
|-----|---------|-------------|------|
| #3 | `agent/enforcement.py` | Move 16 lines up | Very low — pure reorder |
| #4 | `agent/enforcement.py` | Add cache to existing function | Low — additive, no API change |
| #5 | `agent/runtime.py` | Add lock, wrap 2 methods | Low — additive, same pattern as existing locks |
| #6 | `agent/runtime.py` | Move stuck message append to after tool result recording | Low — check conversation model first |
| #7 | `agent/special_agents.py`, `agent/context.py` | Add `role` field, thread it through | Medium — touches 3 files, dataclass change |

**Recommended implementation order:** #3 → #4 → #5 → #7 → #6

Bugs #3 and #4 are in the same file and same function — fix them together. Bug #5 is a standalone lock addition. Bug #7 touches the dataclass and should be done before #6 since #6 is the least critical and may need investigation of the conversation model.
