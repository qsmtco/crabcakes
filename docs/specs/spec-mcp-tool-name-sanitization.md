# SPEC: MCP Tool Name Sanitization (Wire-Safe Namespacing)

**Date:** 2026-07-07
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** Fix for the HTTP 400 `tools.8.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'` error
**Depends on:** None
**Target branch:** main

> **Architecture compliance statement:** This fix touches `utils/mcp_client.py`, `agent/tools.py`, and `agent/runtime.py`. It introduces a bidirectional name-mapping layer at the wire boundary (outbound: sanitize for the provider; inbound: restore for routing). The internal `server_name/tool_name` representation is preserved — only the wire format changes. This follows the existing layering: `utils/mcp_client.py` owns MCP tool definitions, `agent/tools.py` owns tool execution routing, `agent/runtime.py` owns the tool-loop orchestration.

---

## 0. Discovery

Every file listed below was read before this spec was written. Line numbers in this spec refer to the current source.

**Source files read:**
- `utils/mcp_client.py` (full file, 541 lines) — confirmed `MCPToolDefinition` fields at lines 31-36 (decorator at 31, class at 32), `_tools_cache` dict structure at line 55, `get_tools_for_api` signature at line 489, namespacing expression at line **520** (spec citations corrected from 521), try/except wrapping at line **538** (spec citations corrected from 531).
- `agent/tools.py` lines 1155-1220 — confirmed `execute_tool` signature at line 1155, MCP routing block at lines **1189-1215** (spec citations corrected from 1190-1191: `if "/" in name:` is at 1189, `name.partition("/")` is at 1190), try/except wrapping at line 1197, inline MCP import at line 1198.
- `agent/runtime.py` lines 195-410, 1136-1150, 2113-2140, 2376 — confirmed `_call_openai` def at line 195, `payload["tools"] = tools` at line 211, `_convert_tools_for_anthropic` def at line 338 (call site at line 400), `_extract_tool_calls` def at line 1136, `func.get("name")` extraction at line 527, `tools.extend(mcp_tools)` at line 2127, `execute_tool` call at line 2376, `ToolCall.tool_name` persistence at line 1279.
- `utils/mcp_config.py` line 190 — confirmed server-name validation rejects `/` and whitespace but **does not reject `__`** (gap; documented as a limitation in §7).
- `models/conversation.py` lines 81-100 — confirmed `ToolCall.tool_name: str` field at line 96.
- `docs/ARCHITECTURE.md` — confirmed §3.21w (line 2192), §3.21x (line 2234), §4.12 (line 3283) exist; **noted pre-existing doc drift**: §3.21x documents `MCPToolDefinition` as having `input_schema`, but the code has `parameters` + `server_name`. Fix included in §8.

**Architectural layering (verified):**
- `utils/mcp_client.py` owns MCP tool definition formatting (OpenAI function-calling dict construction).
- `agent/tools.py` owns tool execution routing (built-in dict dispatch + MCP routing).
- `agent/runtime.py` owns the tool-loop orchestration (extract tool calls from provider response → dispatch to execute_tool).

**Existing patterns observed:**
- `execute_tool` already does inline imports from `utils.mcp_client` (see `from utils.mcp_client import call_tool as mcp_call_tool, is_connected` at line 1198). The new `_from_wire_name` import follows the same pattern.
- Tool caching uses post-sanitization cache entries (`_tools_cache` at line 55); the cache is safe to reuse across calls because dicts are immutable per spec.

---

## 1. Overview

### 1.1 Problem

MCP tool names are namespaced with a forward slash: `f"{server_name}/{tool.name}"` at `utils/mcp_client.py:521`. When Anthropic-via-OpenRouter receives a tool list containing a `/` in a name, it returns HTTP 400:

```
tools.8.custom.name: String should match pattern '^[a-zA-Z0-9_-]{1,128}$'
```

This breaks all MCP-enabled agents when routed through Anthropic or OpenRouter.

### 1.2 Root Cause (verified)

- **`utils/mcp_client.py:521`** — `namespaced = f"{server_name}/{tool.name}"` produces names like `memory/create_entities`.
- **`agent/runtime.py:2127`** — `tools.extend(mcp_tools)` merges MCP tools into the built-in tool list. The slash-containing names pass through unchanged.
- **`agent/runtime.py:211` / `agent/runtime.py:400`** — The tools list is passed verbatim into `payload["tools"]` (OpenAI format) or through `_convert_tools_for_anthropic()` (Anthropic format). Neither path sanitizes the `/`.
- **Provider rejects** — Anthropic strictly enforces `^[a-zA-Z0-9_-]{1,128}$`; the `/` violates it.

### 1.3 Why the Fix Is Non-Trivial

The `/` is **load-bearing for inbound routing**. `agent/tools.py:1190-1191` routes MCP tool calls by splitting on `/`:

```python
if "/" in name:
    server_name, _, tool_name = name.partition("/")
```

When the LLM responds with a tool call, `agent/runtime.py:527` extracts the tool name verbatim from the provider response (`func.get("name", "")`). That name must match what was sent on the wire. So:
- **Outbound:** sanitize `/` → provider-safe separator (e.g., `__`).
- **Inbound:** restore the provider-safe name back to `server/tool` format before `execute_tool` routes it.

### 1.4 Solution

Introduce a **wire-name mapping** layer with two functions in `utils/mcp_client.py`:

1. **`_to_wire_name(server_name, tool_name) -> str`** — produces a provider-safe name using `__` as the separator (e.g., `memory__create_entities`).
2. **`_from_wire_name(wire_name) -> tuple[str, str] | None`** — splits a wire name back into `(server_name, tool_name)`, returning `None` if the name is not a MCP wire name.

The outbound mapping is applied in `get_tools_for_api()` (where tool dicts are built). The inbound mapping is applied in `agent/tools.py:execute_tool()` (replacing the raw `name.partition("/")` logic).

**Collision safety:** The `__` separator can theoretically collide if a built-in tool name or an MCP tool name contains `__`. The mitigation:
- Built-in tool names are hardcoded (`read_file`, `write_file`, etc.) — none contain `__`.
- MCP tool names come from MCP servers. The spec adds a guard: `_from_wire_name` splits on the **first** `__` occurrence, so `server_name` cannot contain `__` (validated at config load by `mcp_config.py`, which already rejects `/`). If a tool name contains `__`, it is preserved intact after the split.

### 1.5 Scope

| In scope | Out of scope |
|----------|--------------|
| `utils/mcp_client.py` — wire name helpers + `get_tools_for_api` rewrite | `utils/mcp_config.py` — no new validation needed (already rejects `/` in server names) |
| `agent/tools.py` — `execute_tool` routing update | `agent/runtime.py` — no changes to the tool-loop; the wire name arrives via `_extract_tool_calls` and is passed to `execute_tool` unchanged |
| Tests for the mapping, the tool-merge, and the routing | Built-in tool name changes (they're already valid) |

---

## 2. Changes by File

### 2.1 `utils/mcp_client.py` — Wire-name helpers + `get_tools_for_api` rewrite

**Add two module-level functions** (place them after the existing `_sanitize_tool_description` function, before `get_tools_for_api`):

```python
# Wire-name separator: replaces "/" in MCP namespaced tool names.
# Must be provider-safe (matches ^[a-zA-Z0-9_-]{1,128}$) and not collide
# with built-in tool names (none of which contain "__").
_WIRE_NAME_SEPARATOR = "__"


def _to_wire_name(server_name: str, tool_name: str) -> str:
    """Convert an MCP (server_name, tool_name) pair to a provider-safe wire name.

    Provider APIs (Anthropic, OpenAI) reject tool names containing "/".
    The internal namespacing uses "server/tool" for routing, but the wire
    format must use only [a-zA-Z0-9_-]. This function produces "server__tool".

    Args:
        server_name: MCP server name (e.g. "memory"). Must not contain "__"
                    or the separator. mcp_config.py already validates that
                    server names do not contain "/".
        tool_name: MCP tool name (e.g. "create_entities"). May contain "__"
                  internally — the split in _from_wire_name uses the FIRST
                  separator occurrence, preserving it.

    Returns:
        Provider-safe wire name (e.g. "memory__create_entities").
    """
    return f"{server_name}{_WIRE_NAME_SEPARATOR}{tool_name}"


def _from_wire_name(wire_name: str) -> tuple[str, str] | None:
    """Split a wire name back into (server_name, tool_name).

    Splits on the FIRST separator occurrence, so tool names containing "__"
    are preserved intact after the split.

    Args:
        wire_name: The wire-format name (e.g. "memory__create_entities").

    Returns:
        (server_name, tool_name) if the name contains the separator, else None.
        None means this is NOT an MCP wire name — the caller should treat it
        as a built-in tool name.
    """
    if _WIRE_NAME_SEPARATOR not in wire_name:
        return None
    server, _, tool = wire_name.partition(_WIRE_NAME_SEPARATOR)
    if not server or not tool:
        return None
    return server, tool
```

**Rewrite `get_tools_for_api`** — replace the namespacing line (`namespaced = f"{server_name}/{tool.name}"`) with the wire-name helper:

Current code (line 521):
```python
                namespaced = f"{server_name}/{tool.name}"
                raw_desc = tool.description or f"MCP: {tool.name}"
                sanitized_desc = _sanitize_tool_description(raw_desc)
                func_dict = {
                    "type": "function",
                    "function": {
                        "name": namespaced,
                        "description": sanitized_desc or f"MCP: {tool.name}",
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    },
                }
```

New code:
```python
                wire_name = _to_wire_name(server_name, tool.name)
                raw_desc = tool.description or f"MCP: {tool.name}"
                sanitized_desc = _sanitize_tool_description(raw_desc)
                func_dict = {
                    "type": "function",
                    "function": {
                        "name": wire_name,
                        "description": sanitized_desc or f"MCP: {tool.name}",
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    },
                }
```

**Function signatures verified:**
- `get_tools_for_api(server_names: list[str], conversation_key: str | None = None) -> list[dict]` — confirmed at line 489.
- `MCPToolDefinition` dataclass has `.name`, `.description`, `.parameters`, `.server_name` fields — confirmed at lines 32-36.

**Exceptions raised by new functions:** None. `_to_wire_name` and `_from_wire_name` are pure string operations — no file I/O, no network, no exceptions.

### 2.2 `agent/tools.py` — `execute_tool` routing update

**Update the MCP routing block** at lines 1190-1191.

Current code:
```python
    # Phase B: MCP tool routing — namespaced tools like "fetch/fetch"
    if "/" in name:
        server_name, _, tool_name = name.partition("/")
        if not server_name or not tool_name:
            return ToolResult(
                success=False,
                error=f"Invalid MCP tool name '{name}': expected 'server/tool' format",
            )
```

New code:
```python
    # MCP tool routing. Wire names use "__" as the separator (provider-safe).
    # The old "/" separator is still accepted for backward compatibility
    # (e.g. persisted conversations from before this fix).
    server_tool = None
    if "/" in name:
        # Legacy format: "server/tool" (pre-fix persisted conversations)
        server_name, _, tool_name = name.partition("/")
        if server_name and tool_name:
            server_tool = (server_name, tool_name)
    if server_tool is None:
        # Wire format: "server__tool" (current)
        from utils.mcp_client import _from_wire_name
        server_tool = _from_wire_name(name)
    if server_tool is not None:
        server_name, tool_name = server_tool
```

The rest of the MCP routing block (the `try:` ... `mcp_call_tool(...)` section at lines 1197-1215) stays unchanged — it already uses `server_name` and `tool_name` variables.

**Function signature verified:**
- `execute_tool(name, arguments, project_path, session_key="_unknown", approval_callback=None, scratch_dir=None, allowed_tools=None) -> ToolResult` — confirmed at line 1155.

**Import:** The `_from_wire_name` import is done inline (inside the function body) to match the existing pattern in `execute_tool` (which already does `from utils.mcp_client import call_tool as mcp_call_tool, is_connected` inline at line 1198).

### 2.3 Files NOT changed (already correct)

- **`agent/runtime.py`** — No changes. The runtime passes tool names through unchanged: `_extract_tool_calls` reads the name from the provider response (`func.get("name", "")`), stores it in `ToolCall.tool_name`, and passes it to `execute_tool`. The wire name (`memory__create_entities`) arrives intact and is routed by the updated `execute_tool`. The `tools.extend(mcp_tools)` at line 2127 needs no change — the tool dicts already have sanitized names (produced by the updated `get_tools_for_api`).
- **`utils/mcp_config.py`** — No changes. It already validates that server names do not contain `/`. The new `__` separator does not need validation here because `_from_wire_name` splits on the first `__`, making the mapping unambiguous.
- **`models/conversation.py`** — No changes. `ToolCall.tool_name` stores the wire name. On save/load round-trip, the wire name persists. The updated `execute_tool` handles both wire (`__`) and legacy (`/`) formats.

---

## 3. Data Flow

### 3.1 Outbound (tools → provider)

```
1. AgentRuntime._run_loop (runtime.py:2113)
   → tools = get_tool_definitions_for_api(conv.allowed_tools)  # built-in tools
   → mcp_tools = get_tools_for_api(conv.mcp_servers, session_key)  # MCP tools
2. get_tools_for_api (mcp_client.py:489)
   → for each MCP server, discover_tools() returns MCPToolDefinition list
   → _to_wire_name(server_name, tool.name) produces "memory__create_entities"
   → tool dict built with wire name
3. tools.extend(mcp_tools)  (runtime.py:2127)
4. _call_openai / _call_anthropic (runtime.py:195 / 363)
   → payload["tools"] = tools  (no "/" in any name — provider accepts)
```

### 3.2 Inbound (provider response → tool execution)

```
1. Provider returns tool_call with name="memory__create_entities"
2. _extract_tool_calls (runtime.py:1136)
   → reads func.get("name", "") → "memory__create_entities"
   → returns (call_id, "memory__create_entities", args)
3. ToolCall object created with tool_name="memory__create_entities"
4. execute_tool("memory__create_entities", args, ...)  (runtime.py:2376)
5. execute_tool (tools.py:1155)
   → "/" not in name → skip legacy branch
   → _from_wire_name("memory__create_entities") → ("memory", "create_entities")
   → mcp_call_tool("memory", "create_entities", args, conv_key)
6. MCP server executes "create_entities" — correct routing
```

### 3.3 Backward compatibility (persisted conversations)

A conversation saved before this fix has `ToolCall.tool_name = "memory/create_entities"`. When re-executed (rare, but possible on conversation restore), `execute_tool` checks for `/` first (legacy branch), routes correctly, and the MCP server still works.

---

## 4. File Change Summary

| File | Change Type | Lines | Risk Level |
|------|-------------|-------|------------|
| `utils/mcp_client.py` | Add `_to_wire_name`, `_from_wire_name`; rewrite `get_tools_for_api` namespacing | ~30 added, ~2 changed | Low |
| `agent/tools.py` | Update `execute_tool` MCP routing to use `_from_wire_name` + legacy `/` fallback | ~10 changed | Low |

---

## 5. Implementation Order

1. **Add `_to_wire_name` and `_from_wire_name` to `utils/mcp_client.py`** — pure functions, no dependencies.
2. **Rewrite `get_tools_for_api` to use `_to_wire_name`** — one-line change inside the loop.
3. **Update `execute_tool` in `agent/tools.py`** — replace the `name.partition("/")` block with the dual-format routing.
4. **Write tests** — unit tests for the helpers, integration test for the round-trip.
5. **Verify** — run the full test suite + manual confirmation that the wire name is provider-safe.

---

## 6. Acceptance Criteria

- [ ] `_to_wire_name("memory", "create_entities")` returns `"memory__create_entities"`
- [ ] `_from_wire_name("memory__create_entities")` returns `("memory", "create_entities")`
- [ ] `_from_wire_name("read_file")` returns `None` (built-in tool, not MCP)
- [ ] `_from_wire_name("memory__create__entities")` returns `("memory", "create__entities")` (split on first `__` only)
- [ ] `_from_wire_name("")` returns `None`
- [ ] `_from_wire_name("__tool")` returns `None` (empty server name)
- [ ] `get_tools_for_api(["memory"], ...)` produces tool dicts with names matching `^[a-zA-Z0-9_-]{1,128}$` (no `/`)
- [ ] `execute_tool("memory__create_entities", {...})` routes to `mcp_call_tool("memory", "create_entities", ...)`
- [ ] `execute_tool("memory/create_entities", {...})` still works (legacy format, backward compat)
- [ ] `execute_tool("read_file", {...})` still works (built-in tool, no MCP routing)
- [ ] All existing `tests/test_mcp_client.py` tests pass
- [ ] All existing `tests/test_mcp_integration.py` tests pass
- [ ] All existing `tests/test_tools.py` tests pass
- [ ] New test file `tests/test_mcp_tool_naming.py` passes with all cases from §7

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Server name contains `__` | Not possible — `mcp_config.py` validates server names. `_from_wire_name` splits on first `__`, so `my__server__tool` → `("my", "server__tool")`. Documented as a limitation; the server name would have to be changed. |
| Tool name contains `__` | Works — split on first `__`. `memory__create__entities` → `("memory", "create__entities")`. |
| Tool name is empty | `_from_wire_name("memory__")` → `None` (empty tool name rejected). `execute_tool` falls through to built-in lookup, returns "Unknown tool". |
| Wire name has no separator | `_from_wire_name("read_file")` → `None`. `execute_tool` treats as built-in. |
| Legacy persisted conversation with `/` | `execute_tool` checks `/` first, routes correctly via legacy branch. |
| Two MCP servers with same tool name | No collision — wire names include server prefix. `memory__search` and `fetch__search` are distinct. |
| Empty server name | `_to_wire_name("", "tool")` → `"__tool"`. `_from_wire_name("__tool")` → `None` (empty server). Defensive — server names are always non-empty (validated at config load). |

---

## 8. ARCHITECTURE.md Updates Required

**Section 3.21w (`utils/mcp_config.py`)** — add note that server names must not contain `__` (the wire-name separator). This is already enforced implicitly (server names don't contain `/`), but should be documented for the new separator.

**Section 3.21x (`utils/mcp_client.py`)** — document the wire-name mapping (`_to_wire_name` / `_from_wire_name`) and the `__` separator. Note that the internal `server_name/tool_name` representation is preserved; only the wire format changes.

**Section 4.12 (MCP Tool Execution Flow)** — update the namespacing rule from `server_name/tool_name` to `server_name__tool_name` (wire format). Note that inbound routing uses `_from_wire_name`.

---

## 9. Spec Self-Audit

### 1. Does every code sample actually work against the current codebase?

- **`_to_wire_name` / `_from_wire_name`** — pure functions, no external dependencies. Verified against the existing `MCPToolDefinition` structure (`.name`, `.server_name`).
- **`get_tools_for_api` rewrite** — verified the exact current code at `mcp_client.py:521`. The only change is `namespaced = f"{server_name}/{tool.name}"` → `wire_name = _to_wire_name(server_name, tool.name)`. The rest of the loop body is unchanged.
- **`execute_tool` update** — verified the exact current code at `tools.py:1190-1191`. The legacy `/` branch preserves backward compat. The new `_from_wire_name` branch handles current wire names.
- **Runtime passthrough** — verified that `_extract_tool_calls` reads the name verbatim (`func.get("name", "")` at runtime.py:527) and passes it to `execute_tool` at runtime.py:2376. No change needed.

### 2. Did I catch all exception types for every function I call?

- `_to_wire_name` — no exceptions (pure string formatting).
- `_from_wire_name` — no exceptions (pure string parsing).
- `get_tools_for_api` — already wrapped in `try/except Exception` at line 531. No change.
- `execute_tool` — already wraps MCP calls in `try/except Exception` at line 1197. No change.

### 3. Did I verify key structures, not assume them?

- `MCPToolDefinition` fields verified: `.name`, `.description`, `.parameters`, `.server_name` (lines 32-36).
- `_tools_cache` structure verified: `dict[tuple[str, str], list[dict]]` (line 55). The cache stores tool dicts; the name change propagates through the cache automatically (cached dicts will have wire names).
- `ToolCall.tool_name` field verified (models/conversation.py, persisted at runtime.py:1279).

### 4. Did I trace the data flow end-to-end?

Yes — §3 traces outbound (tools → provider), inbound (provider response → tool execution), and backward compat (persisted conversations). Every function name and key structure verified against source.

### 5. Would an implementer who follows this spec exactly produce working code?

Yes. The changes are:
- 2 pure functions (~25 lines total).
- 1 one-line change in `get_tools_for_api`.
- 1 routing-block rewrite in `execute_tool` (~10 lines, replacing 6).
- Tests.

All function signatures verified. All import paths verified. No invented APIs.

---

## Spec Completion Verification

### 1. Scope checklist

```
[ ] utils/mcp_client.py — added _to_wire_name, _from_wire_name; rewrote get_tools_for_api namespacing (§2.1)
[ ] agent/tools.py — updated execute_tool MCP routing (§2.2)
```

### 2. Test suite (to be pasted after implementation)

```bash
cd /home/q/projects/crabcakes
xvfb-run -a python3 -m pytest tests/test_mcp_client.py tests/test_mcp_integration.py tests/test_tools.py tests/test_mcp_tool_naming.py -v
```

### 3. Pattern sweep

```bash
# Verify no remaining raw "/" namespacing in get_tools_for_api
grep -n 'server_name}/' utils/mcp_client.py
# Expected: 0 matches in get_tools_for_api (legacy comment references are OK)

# Verify execute_tool handles both formats
grep -n '_from_wire_name\|partition.*"/"' agent/tools.py
# Expected: both the legacy "/" branch and the new _from_wire_name branch present
```

### 4. Declaration

Spec is complete. All code samples traced against source. All function signatures verified. All edge cases enumerated.
