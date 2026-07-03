# SPEC: Enforce `allowed_tools` at Tool Execution Gate

**Date:** 2026-07-03
**Author:** qtr (OC Tech Writer)
**Status:** Draft — for implementation
**Implements:** N/A (bug fix)
**Depends on:** None
**Target branch:** main
**Bug class:** security / authorization (severity: bug)

> ARCHITECTURE compliance: §3.21n (`agent/tools.py` — Tool Definitions + Execution) names `execute_tool` as the tool execution point. This spec moves the existing `allowed_tools` filter from advisory (API-schema layer only) to enforced (execution-layer gate) and updates §3.21n accordingly. Per §1 (Architecture Law), `docs/ARCHITECTURE.md` must be updated in the same commit as the structural code change.

---

## 1. Overview

### 1.1 Problem statement

Per-agent tool permissions are honored **only** when the LLM API tool schema is built. `conv.allowed_tools` is passed to `get_tool_definitions_for_api()` to filter the JSON schemas the model sees, but `execute_tool()` — the function that actually invokes the handler — has no `allowed_tools` parameter and performs no membership check before running the handler.

Consequence: any agent, including a special agent whose agent-definition `tools:` list excludes `write_file` and `edit_file`, can invoke `write_file` / `edit_file` if the model emits those tool names. The Debugger special agent demonstrated this empirically: its agent-builder "Edit agent" dialog had `write_file` and `edit_file` unchecked, yet `edit_file` calls succeeded.

The schema-level filter is *advisory* — it influences what the model is told exists, but does not enforce what the runtime will execute.

### 1.2 Solution summary

Add an `allowed_tools: list[str] | None` parameter to `execute_tool()`. After the `_TOOLS.get(name)` lookup, return a denial `ToolResult` when `allowed_tools is not None and name not in allowed_tools`. Update the single caller in `agent/runtime.py` to forward `conv.allowed_tools`. Update §3.21n in `docs/ARCHITECTURE.md`.

### 1.3 Scope

| In scope | Out of scope |
|----------|--------------|
| Add `allowed_tools` gate to `execute_tool()` | MCP server-name enforcement (separate, see §7.2) |
| Update `agent/runtime.py:2296` to forward `conv.allowed_tools` | Redesigning the agent-builder UI |
| Update `docs/ARCHITECTURE.md` §3.21n | Restricting `allowed_tools=None` default |
| New unit tests in `tests/test_tools.py` | Changing tool registration or discovery |
| Update existing tests that pass `execute_tool()` without `allowed_tools` | Removing the API-schema filter (still useful for prompt size) |

### 1.4 Architecture principles applied

- **Single execution point:** §3.21n names `execute_tool` as the tool execution point. The fix makes it the *enforced* execution point. No new dispatch path is introduced; no call sites move.
- **Defense in depth:** the API-schema filter remains. It now backs up the execution gate (prompt-level *and* execution-level).
- **Backwards-compatible default:** `allowed_tools=None` retains today's behavior (any registered tool runs). This avoids breaking gateway-side agents or test fixtures that intentionally use the full tool set. See §7.3 for the trade-off.
- **Architecture-Law consistency (§1):** `docs/ARCHITECTURE.md` §3.21n is updated in the same commit as the code change.

---

## 2. Changes by File

### 2.1 `agent/tools.py` — add `allowed_tools` gate to `execute_tool`

#### 2.1.1 Signature change

Current (verified at `agent/tools.py:1155`):

```python
def execute_tool(
    name: str,
    arguments: dict,
    project_path: str,
    session_key: str = "_unknown",
    approval_callback: Callable[[str, str, dict], bool] | None = None,
    scratch_dir: str | None = None,
) -> ToolResult:
```

New:

```python
def execute_tool(
    name: str,
    arguments: dict,
    project_path: str,
    session_key: str = "_unknown",
    approval_callback: Callable[[str, str, dict], bool] | None = None,
    scratch_dir: str | None = None,
    allowed_tools: list[str] | None = None,
) -> ToolResult:
    """
    Execute a tool by name with the given arguments.

    Args:
        name: Tool name (e.g. "read_file")
        arguments: Parsed arguments dict (e.g. {"path": "src/main.py"})
        project_path: Absolute path to the project working directory (sandbox base)
        session_key: Session key of the agent (for exec_command approval)
        approval_callback: Per-call approval callback (MED-1). Takes precedence
            over the global _approval_callback.
        scratch_dir: Deprecated/ignored. Previously used as exec_command cwd.
            All tools now use project_path. Retained for API compatibility.
        allowed_tools: If provided, only tools whose name is in this list are
            permitted. Tools outside the list are denied with a ToolResult
            (success=False) BEFORE the handler runs. If None (default), all
            registered tools are permitted (back-compat). This is the
            enforcement gate; the API-schema filter in
            get_tool_definitions_for_api() is advisory only.

    Returns:
        ToolResult with output or error.

    All file paths are sandboxed to project_path.
    exec_command requires PM approval via the registered callback.
    """
```

#### 2.1.2 Gate insertion — after MCP routing, before `_TOOLS.get`

Verified MCP branch starts at `agent/tools.py:1182` (`if "/" in name:`). The MCP branch returns from inside the `try` block; control flow does not fall through to the `_TOOLS.get(name)` line. The gate must therefore live **after** the MCP block returns, at the `_TOOLS.get(name)` line (verified at `agent/tools.py:1211`).

**Change scope:** insert the gate immediately after the `_TOOLS.get(name)` lookup and its None-check, before the `defn, handler = entry` unpack. Do NOT insert it inside the MCP `try` block (MCP routing has its own gating policy — see §7.2).

Exact insertion (line numbers from current source):

```python
# BEFORE (current):
    entry = _TOOLS.get(name)
    if entry is None:
        return ToolResult(success=False, error=f"Unknown tool: {name}")

    defn, handler = entry

# AFTER (new):
    entry = _TOOLS.get(name)
    if entry is None:
        return ToolResult(success=False, error=f"Unknown tool: {name}")

    # §3.21n — allowed_tools enforcement gate.
    # When the caller (agent runtime) supplies an explicit allow-list,
    # we honor it here. The API-schema filter in get_tool_definitions_for_api()
    # is advisory only; this gate is the law.
    # allowed_tools=None retains back-compat (any registered tool runs).
    if allowed_tools is not None and name not in allowed_tools:
        return ToolResult(
            success=False,
            error=(
                f"Tool '{name}' is not in the agent's allowed_tools "
                f"(permitted: {sorted(allowed_tools)})"
            ),
        )

    defn, handler = entry
```

#### 2.1.3 Imports

No new imports. `ToolResult` is already in scope (defined in the same file at `agent/tools.py:41`).

#### 2.1.4 Lines changed

Estimated net change: ~12 added lines, 0 removed. Total file impact: ~12 lines.

---

### 2.2 `agent/runtime.py` — forward `conv.allowed_tools` to `execute_tool`

#### 2.2.1 Caller location

Verified at `agent/runtime.py:2296`:

```python
result = execute_tool(tool_name, args, conv.project_path, session_key,
                      approval_callback=per_call_cb)
```

This is the **only** call site of `execute_tool` in the production codebase (confirmed by `grep -rn "execute_tool(" --include="*.py"` filtered for non-test paths; results: `agent/runtime.py:2224` (import), `agent/runtime.py:2296` (call), `agent/tools.py:1155` (definition)).

#### 2.2.2 New call

```python
# Allowed-tools enforcement gate (§3.21n).
# Forward conv.allowed_tools so execute_tool can deny tools the agent
# was configured without. conv.allowed_tools is the single source of
# truth — set in create_conversation() from agent_def["tools"] and
# persisted on the conversation object.
result = execute_tool(tool_name, args, conv.project_path, session_key,
                      approval_callback=per_call_cb,
                      allowed_tools=conv.allowed_tools)
```

#### 2.2.3 Lines changed

Estimated net change: ~7 added lines (3 comment + 1 arg + 3 reflow), 2 removed. Total file impact: ~9 lines.

---

### 2.3 `docs/ARCHITECTURE.md` — update §3.21n

Per §1 (Architecture Law), this update ships in the same commit as the code change. Verified current text at `docs/ARCHITECTURE.md:1582`:

**Change A — Public API block (lines ~1582):**

```diff
- def execute_tool(name, arguments, project_path) -> ToolResult
+ def execute_tool(name, arguments, project_path, allowed_tools=None) -> ToolResult
+ # When allowed_tools is provided, only tools in the list are executable.
+ # The API-schema filter (get_tool_definitions_for_api) is advisory;
+ # this execution gate is the law.
```

**Change B — New subsection after the existing Blocklist paragraph (after line ~1604):**

```markdown
**Allowed-tools enforcement gate:** `execute_tool` accepts an
`allowed_tools: list[str] | None` parameter. When non-None, only tools in
the list are executable; any other tool returns a denial `ToolResult`
without running the handler. The single caller in `agent/runtime.py:2296`
forwards `conv.allowed_tools`, which is set on conversation creation from
the agent definition's `tools:` field (`utils/agent_defs.py`,
`agent/special_agents.py`). When `allowed_tools=None` (default), all
registered tools are permitted — this preserves back-compat for callers
that don't pass an allow-list.

The API-schema filter in `get_tool_definitions_for_api(allowed_tools)`
remains as a *prompt-level* optimization (smaller tool list = smaller
JSON schemas sent to the LLM, lower per-turn cost, fewer chances of the
model hallucinating tool names). It is no longer the sole authorization
mechanism.
```

**Lines changed:** ~10 added, 1 changed.

---

### 2.4 `tests/test_tools.py` — add enforcement tests

Add a new test class at the end of the file (after `class TestApprovalCallback` at line ~682). Imports already present (`execute_tool` imported at line 16). No new imports needed.

```python
# ═══════════════════════════════════════════════════════════════════
#  Allowed-tools enforcement (§3.21n)
# ═══════════════════════════════════════════════════════════════════

class TestAllowedToolsGate:
    """The allowed_tools parameter on execute_tool() is the single
    authorization gate for non-default agents. Without it, the API-schema
    filter in get_tool_definitions_for_api is advisory only."""

    def test_disallowed_tool_returns_denied(self):
        """Agent without write_file in allowed_tools cannot invoke it."""
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool(
                "write_file",
                {"path": "x.txt", "content": "evil"},
                proj,
                allowed_tools=["read_file", "list_files"],
            )
        assert r.success is False
        assert "write_file" in r.error
        assert "allowed_tools" in r.error

    def test_disallowed_tool_creates_no_file(self):
        """Side-effect-free denial — no file written even on disallowed call."""
        with tempfile.TemporaryDirectory() as proj:
            execute_tool(
                "write_file",
                {"path": "should_not_exist.txt", "content": "leaked"},
                proj,
                allowed_tools=["read_file"],
            )
            full = os.path.join(proj, "should_not_exist.txt")
            assert not os.path.exists(full), "disallowed write_file leaked to disk"

    def test_allowed_tool_succeeds(self):
        """Tools in the allow-list still execute normally."""
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool(
                "write_file",
                {"path": "ok.txt", "content": "hello"},
                proj,
                allowed_tools=["write_file", "read_file"],
            )
        assert r.success is True
        assert os.path.exists(os.path.join(proj, "ok.txt"))

    def test_none_allowed_tools_permits_all(self):
        """Back-compat: allowed_tools=None permits any registered tool."""
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool(
                "write_file",
                {"path": "x.txt", "content": "hi"},
                proj,
                allowed_tools=None,
            )
        assert r.success is True

    def test_default_arg_permits_all(self):
        """Back-compat: omitting allowed_tools entirely permits any tool."""
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("write_file", {"path": "x.txt", "content": "hi"}, proj)
        assert r.success is True

    def test_empty_allowed_list_denies_everything(self):
        """An explicit empty list denies everything (not None)."""
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool(
                "read_file",
                {"path": "x.txt"},
                proj,
                allowed_tools=[],
            )
        assert r.success is False
        assert "read_file" in r.error

    def test_unknown_tool_still_rejected_before_gate(self):
        """The 'Unknown tool' check fires before the allowed_tools gate."""
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool(
                "nonexistent_tool",
                {},
                proj,
                allowed_tools=["read_file"],
            )
        assert r.success is False
        assert "Unknown tool" in r.error

    def test_realistic_special_agent_config(self):
        """Mirror the actual failing scenario: special:coder-style tools
        without write/edit should deny those tools."""
        # Approximates a 'read-only investigator' agent.
        readonly_tools = ["read_file", "list_files", "search_files", "file_search"]
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool(
                "edit_file",
                {"path": "x.py", "old_text": "a", "new_text": "b"},
                proj,
                allowed_tools=readonly_tools,
            )
        assert r.success is False
        assert "edit_file" in r.error
```

**Lines changed:** ~95 added, 0 removed.

---

### 2.5 Files NOT changed

Per Rule 8 — explicit non-changes prevent the implementer from wondering "should I touch this?":

- **`agent/special_agents.py`** — `SpecialAgentDef.tools` already populates correctly from YAML `tools:` list (verified at `agent/special_agents.py:78,92-93`). The data is correct; only the enforcement is missing.
- **`models/conversation.py`** — `Conversation.allowed_tools` field already exists and is round-tripped in serialization (verified at lines 1246, 1360). No model change needed.
- **`ui/handlers/agent_runtime_handler.py`** — UI correctly passes `allowed_tools=agent_def.tools` when creating conversations (verified at line 642). No UI change needed.
- **`ui/views/agent_builder.py`** — Tool checkbox UI already collects the right values; nothing changes.
- **`utils/agent_defs.py`** — YAML loader already returns the correct `tools` list (verified at line 491: `from agent.tools import get_all_tools` for completeness check only; `agent_def["tools"]` is the source of truth).
- **`gateway/`** — gateway is a WebSocket *client* to OpenClaw; it does not invoke `execute_tool` (verified by grep). No change.
- **`utils/prompt_loader.py`** — only injects tool names into the system prompt string. No dispatch. No change.
- **`agent/context.py`, `utils/feedback_processor.py`, `agent/runtime.py` line 1662** — call `get_all_tools()` / `get_tool_definitions_for_api()` for prompt-context purposes; do not invoke `execute_tool`. No change.

---

## 3. Data Flow

Trace for the bug scenario (Debugger invokes `edit_file` while agent config has only `read_file` in `tools:`):

```
1. Project loads YAML: prompts/agents/debugger.yaml → tools: [read_file]
   └─ agent/special_agents.py:78     tools = agent_def.get("tools", [])
   └─ agent/special_agents.py:92-93  tools=tools, can_write="write_file" in tools or "edit_file" in tools
                                     # can_write=False for debugger (correct)

2. UI creates conversation:
   └─ ui/handlers/agent_runtime_handler.py:642
       allowed_tools=agent_def.tools   # ["read_file"]
   └─ agent/runtime.py:1621           allowed_tools=["read_file"]
   └─ agent/runtime.py:1663-1665       tool_names filtered for system prompt (advisory)
   └─ agent/runtime.py:1694           conv = Conversation(allowed_tools=["read_file"], ...)
   └─ models/conversation.py          Conversation.allowed_tools = ["read_file"]  ✓

3. Tool loop iteration — LLM emits edit_file tool call:
   └─ agent/runtime.py:2057-2058
       tools = get_tool_definitions_for_api(conv.allowed_tools)
       # → returns ONLY read_file's schema (LLM should not see edit_file)
       # BUT: model may still emit edit_file from training priors, prompt cache, or
       # a prompt-injection path. API filter is advisory.

4. Dispatcher prepares to execute:
   └─ agent/runtime.py:2229-2296  (current code)
       result = execute_tool(tool_name, args, conv.project_path, session_key,
                             approval_callback=per_call_cb)
       # ⚠ CURRENTLY: execute_tool has no allowed_tools parameter — edit_file runs.

5. WITH THIS FIX:
   └─ agent/runtime.py:2296 (new)
       result = execute_tool(tool_name, args, conv.project_path, session_key,
                             approval_callback=per_call_cb,
                             allowed_tools=conv.allowed_tools)  # ["read_file"]

   └─ agent/tools.py:1211 (gate inserted after MCP routing)
       entry = _TOOLS.get("edit_file")  # found
       if entry is None: ...            # skip — entry is not None
       # NEW GATE:
       if allowed_tools is not None and "edit_file" not in ["read_file"]:
           return ToolResult(success=False,
                             error="Tool 'edit_file' is not in the agent's "
                                   "allowed_tools (permitted: ['read_file'])")

   └─ Runtime propagates ToolResult → model sees error → model retries with read_file or stops.
```

---

## 4. File Change Summary

| File | Change type | Lines (added / removed) | Risk |
|------|-------------|-------------------------|------|
| `agent/tools.py` | Function signature + 12-line gate | +13 / -1 | Low (additive, defaults preserve behavior) |
| `agent/runtime.py` | Pass new kwarg to single call site | +5 / -1 | Low (single call site; existing tests don't assert call shape) |
| `docs/ARCHITECTURE.md` | §3.21n API signature + new subsection | +10 / -1 | Trivial (docs) |
| `tests/test_tools.py` | New test class `TestAllowedToolsGate` | +95 / 0 | Trivial (new code, isolated) |
| **Total** | | **+123 / -3** | **Low** |

---

## 5. Implementation Order

Numbered for one developer to execute sequentially. Each step has a verification gate.

### Step 1 — `agent/tools.py` signature + gate
1. Open `agent/tools.py`.
2. Add `allowed_tools: list[str] | None = None,` to the `execute_tool` signature after `scratch_dir` (line 1155).
3. Extend the docstring with the new `allowed_tools` parameter description (see §2.1.1).
4. Insert the gate after `if entry is None: ...` and before `defn, handler = entry` (line 1211, see §2.1.2).
5. **Verify:** `python3 -c "import inspect; from agent.tools import execute_tool; print(inspect.signature(execute_tool))"` — must show `allowed_tools=None` as the last parameter.
6. **Verify:** `cd /home/q/projects/crabcakes && python3 -m pytest tests/test_tools.py -x -q` — all existing tests still pass (back-compat default).

### Step 2 — `agent/runtime.py` caller
1. Open `agent/runtime.py`.
2. Update line 2296 to pass `allowed_tools=conv.allowed_tools` (see §2.2.2).
3. **Verify:** `cd /home/q/projects/crabcakes && grep -n "execute_tool(" agent/runtime.py` — should show the kwarg.
4. **Verify:** `cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py -x -q` — runtime tests pass.

### Step 3 — `tests/test_tools.py` new tests
1. Append `class TestAllowedToolsGate` block at end of file (after `class TestApprovalCallback`).
2. **Verify:** `cd /home/q/projects/crabcakes && python3 -m pytest tests/test_tools.py::TestAllowedToolsGate -v` — all 8 new tests pass.
3. **Verify:** `cd /home/q/projects/crabcakes && python3 -m pytest tests/test_tools.py -q` — full test_tools.py still passes.

### Step 4 — `docs/ARCHITECTURE.md` §3.21n
1. Update the Public API block (line ~1582) per §2.3 Change A.
2. Append the new subsection after the Blocklist paragraph (after line ~1604) per §2.3 Change B.
3. **Verify:** `cd /home/q/projects/crabcakes && grep -n "allowed_tools" docs/ARCHITECTURE.md` — must show the new signature and the new subsection.

### Step 5 — Full regression sweep
1. Run the full test suite: `cd /home/q/projects/crabcakes && python3 -m pytest -x -q`.
2. Capture the full pytest output for the completion report (Rule 10 §2).
3. Pattern sweep (Rule 10 §3): `grep -rn "execute_tool(" agent/ ui/ utils/ gateway/ --include="*.py" | grep -v "test_" | grep -v "def execute_tool"` — must show exactly one call site, and that call must include `allowed_tools=`.
4. Confirm no call site was missed.

---

## 6. Acceptance Criteria

Each is independently testable. All must pass before declaring complete.

1. **AC-1 (gate blocks):** `execute_tool("write_file", {...}, "/tmp/proj", allowed_tools=["read_file"])` returns `ToolResult(success=False, error contains "write_file")` and creates no file on disk.
2. **AC-2 (gate allows):** `execute_tool("read_file", {...}, "/tmp/proj", allowed_tools=["read_file"])` succeeds.
3. **AC-3 (back-compat):** `execute_tool("write_file", {...}, "/tmp/proj")` (no `allowed_tools` kwarg) succeeds — today's behavior preserved.
4. **AC-4 (back-compat explicit None):** `execute_tool("write_file", {...}, "/tmp/proj", allowed_tools=None)` succeeds — `None` is a wildcard, not an empty list.
5. **AC-5 (empty list denies):** `execute_tool("read_file", {...}, "/tmp/proj", allowed_tools=[])` returns denial — explicit empty list denies everything.
6. **AC-6 (caller wired):** The single production caller in `agent/runtime.py` line 2296 passes `allowed_tools=conv.allowed_tools`. Verified by `grep` and by test inspection.
7. **AC-7 (architectural conformance):** `docs/ARCHITECTURE.md` §3.21n Public API block shows the new signature, and a new "Allowed-tools enforcement gate" paragraph exists below the Blocklist paragraph.
8. **AC-8 (full regression):** `pytest -x -q` passes with zero failures, zero errors.
9. **AC-9 (manual smoke):** Reproduce the Debugger scenario in the running app: edit the Debugger agent's tool checkboxes to remove `write_file` and `edit_file`, attempt a conversation, attempt to invoke `edit_file` via slash command or chat — the runtime returns a denial message and no file is created.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| `allowed_tools=None` | Wildcard — any registered tool runs. Back-compat. |
| `allowed_tools=[]` (empty list) | Everything denied. Tested. |
| `allowed_tools=["unknown_tool_name"]` | No registered tool is in the list → all `execute_tool` calls return `success=False`. The `_TOOLS.get(name)` check still fires first for genuinely unknown names. |
| MCP tool like `"fetch/fetch"` with `allowed_tools=["read_file"]` | MCP branch fires *before* the gate. The MCP tool runs unchecked. **This is a known limitation** — see §7.2 below. |
| MCP tool with `allowed_tools=None` | MCP tool runs. Back-compat preserved. |
| `name` contains `/` but is malformed (e.g. `"foo/"` or `"/bar"`) | Existing MCP branch already handles: returns `ToolResult(success=False, error="Invalid MCP tool name...")` at line 1187. Gate is not reached. |
| `allowed_tools` containing `write_file` but model emits `Write_File` (case mismatch) | Gate compares strings literally — `Write_File not in allowed_tools` → denial. Models don't typically emit case-variant tool names, but the strict comparison is safer. |
| Concurrent calls with the same `conv.allowed_tools` | No race — `allowed_tools` is a list passed by reference, but the gate only reads it. No mutation happens in `execute_tool`. |

### 7.1 MCP routing caveat — IMPORTANT

Verified at `agent/tools.py:1182`: the MCP branch (`if "/" in name:`) returns from inside its own `try/except` block before reaching the new gate. Therefore:

- An MCP tool name like `"fetch/fetch"` is **not** covered by `allowed_tools` as a built-in tool name would be.
- `conv.allowed_tools` is set from the agent's `tools:` YAML list, which currently does not include MCP server names (`SpecialAgentDef.mcp_servers` is a separate field — verified at `agent/special_agents.py:42`).
- Today, MCP-server access is gated by `conv.mcp_servers` being non-empty. The bug being fixed here is about the *built-in* tool set; MCP is a separate authorization model.

**Out of scope for this spec.** A future spec should decide whether MCP server names belong in the same `allowed_tools` list or in a separate allow-list. Documented here so the implementer does not assume MCP is covered.

### 7.2 Tests not asserting MCP gating

The new test class `TestAllowedToolsGate` deliberately does NOT test MCP behavior — that is out of scope. If the implementer needs to add a separate MCP gating spec, it should be a follow-up document.

### 7.3 `allowed_tools=None` default — trade-off

Today, callers that omit `allowed_tools` (or pass `None`) get the full registered tool set. This preserves back-compat for:

- The Debugger's `agent-runtime-handler.py:642` path that always passes an explicit list (fine).
- Tests in `tests/test_tools.py` that don't pass `allowed_tools` (verified by grep: zero existing tests pass it).
- Any future internal callers.

The alternative — requiring an explicit `allowed_tools` list for every call — would be safer (no accidental wildcards) but would break all existing tests and require a sweeping refactor. **Back-compat is the right choice for this fix.** A follow-up spec can tighten the default later.

---

## 8. ARCHITECTURE.md Updates Required

Per §1 (Architecture Law), `docs/ARCHITECTURE.md` is updated in the same commit. Specific changes:

### 8.1 §3.21n — Public API block

Update the function signature line for `execute_tool`:

```diff
- def execute_tool(name, arguments, project_path) -> ToolResult
+ def execute_tool(name, arguments, project_path, allowed_tools=None) -> ToolResult
```

### 8.2 §3.21n — new paragraph after the Blocklist paragraph

Append (after the existing blocklist paragraph at line ~1604):

```markdown
**Allowed-tools enforcement gate:** `execute_tool` accepts an
`allowed_tools: list[str] | None` parameter. When non-None, only tools in
the list are executable; any other tool returns a denial `ToolResult`
without running the handler. The single caller in `agent/runtime.py`
forwards `conv.allowed_tools`, which is set on conversation creation from
the agent definition's `tools:` field. When `allowed_tools=None` (default),
all registered tools are permitted — preserves back-compat.

The API-schema filter in `get_tool_definitions_for_api(allowed_tools)`
remains as a *prompt-level* optimization. It is no longer the sole
authorization mechanism.
```

### 8.3 Section heading touched

The §3.21n section heading at line 1563 does NOT need a change — its scope ("Tool Definitions + Execution") already covers the gate. Do not rename the section.

---

## 9. Self-Audit (Rule 9)

Per the steel-framed-spec-writer prompt, re-reading before declaring complete:

1. **Does every code sample work against the current codebase?**
   - Verified `execute_tool` signature at `agent/tools.py:1155-1162` — signature change is purely additive (new keyword arg with default).
   - Verified `_TOOLS.get(name)` lookup at `agent/tools.py:1211` — gate insertion point is after the None check, before the `defn, handler = entry` unpack. No reordering of existing logic.
   - Verified `agent/runtime.py:2296` — single call site. Pass-through is straightforward.
   - Verified `ToolResult` signature at `agent/tools.py:41` — fields used in the new gate (`success`, `error`) exist.
   - Verified `conv.allowed_tools` is on the Conversation object — used in many places (lines 1246, 1360, 1663, 2058, 2823). No new attribute needed.

2. **Did I catch all exception types for every function I call in samples?**
   - The new gate does not raise — it returns a `ToolResult(success=False, error=...)`. No `except` clauses added or removed.
   - The `runtime.py` change is a kwarg addition. No exception handling changed.

3. **Did I verify key structures, not assume them?**
   - `allowed_tools` is a `list[str]` — verified by `Conversation` docstring/usage at `runtime.py:1636`, `models/conversation.py` (via `data.get("allowed_tools")` round-trip).
   - No dict keys or tuples introduced.

4. **Did I trace the data flow end-to-end?**
   - Yes — see §3. Walks YAML → SpecialAgentDef → UI → create_conversation → conv.allowed_tools → API-schema filter (advisory) → execute_tool → new gate → denial ToolResult.

5. **Would an implementer who follows this spec exactly produce working code?**
   - The four file changes are independent and testable. Each step in §5 has a verification gate. The acceptance criteria in §6 are concrete and reproducible. The new tests in §2.4 are self-contained and import nothing new.

**Verdict:** Spec is ready for implementation.

---

## 10. Completion Checklist (Rule 10) — for the implementer

Run these after the four edits land.

### 10.1 Scope checklist

- [ ] `agent/tools.py` — signature + 12-line gate added at line ~1211
- [ ] `agent/runtime.py` — line 2296 forwards `allowed_tools=conv.allowed_tools`
- [ ] `docs/ARCHITECTURE.md` — §3.21n Public API block updated; new paragraph appended
- [ ] `tests/test_tools.py` — `class TestAllowedToolsGate` appended with 8 tests

If any box is unchecked, work is not complete.

### 10.2 Test suite output (paste verbatim after running)

```
$ cd /home/q/projects/crabcakes && python3 -m pytest tests/test_tools.py tests/test_agent_runtime.py -v
```

Include the full output. If a test fails, fix it; do not summarize.

### 10.3 Pattern sweep

```
$ grep -rn "execute_tool(" /home/q/projects/crabcakes --include="*.py" | grep -v "test_" | grep -v "__pycache__" | grep -v "def execute_tool"
```

Expected: exactly one line, from `agent/runtime.py`, containing `allowed_tools=`.

### 10.4 Declaration

Declare complete only when:
1. All four boxes in §10.1 are checked.
2. The test output in §10.2 shows zero failures and zero errors.
3. The pattern sweep in §10.3 returns exactly one match (the wired caller).

Otherwise report what's done, what's missing, and what's blocking.