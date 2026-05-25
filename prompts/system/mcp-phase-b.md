# MCP Phase B — Runtime Integration

**YOU ARE IMPLEMENTING PHASE B OF THE MCP CLIENT SPEC.**
**SPEC FILE:** `docs/specs/SPEC-MCP-client-integration.md` — READ IT FIRST, COMPLETELY.
**ARCHITECTURE:** `docs/ARCHITECTURE.md` — THIS IS LAW.

---

## ⚠️ M2.5 BEHAVIORAL GUARDS — MANDATORY

These guards exist because M2.5 has known failure modes. You MUST follow them.

### GUARD 1: READ THE SPEC BACKWARDS AFTER IMPLEMENTATION

After you finish implementing, open the spec and go through EVERY checklist item. For each item, answer:
- "Did I implement this?" → YES or NO
- "Where is it?" → file and line number
- "Is it tested?" → YES or NO

If ANY checklist item is NO, you are NOT DONE.

### GUARD 2: HOSTILE INPUT VALIDATION — EVERY PUBLIC FUNCTION

M2.5 assumes inputs are correct. They are NOT. For EVERY public function:

1. What if the argument is `None`?
2. What if the argument is the wrong type (str vs list vs dict)?
3. What if the argument is empty (empty string, empty list, empty dict)?
4. What if the argument contains special characters?

**RULE:** If a function accepts external data (config, API responses, user input), VALIDATE BEFORE USING. Raise `ValueError` with a descriptive message on invalid input. Never `AttributeError` from assuming a type.

### GUARD 3: ERROR HANDLING IS NOT OPTIONAL

M2.5 writes happy-path code and skips error handling. This is WRONG.

**For EVERY function you write:**
- What happens if the thing you're calling raises an exception?
- What happens if the thing you're calling returns `None`?
- What happens if the thing you're calling returns unexpected data?
- Does the calling code handle YOUR exceptions correctly?

**RULE:** Every `except` block must either:
- Log the error AND return a safe default, OR
- Re-raise with more context, OR
- Convert to the function's error type (e.g., `ToolResult(success=False, error=...)`)

**NEVER write bare `except: pass`. NEVER swallow exceptions silently.**

### GUARD 4: WRITE THE HARD CODE, NOT JUST THE EASY CODE

M2.5 delivers easy parts and skips hard parts silently. This is WRONG.

The hard parts of Phase B are:
- The async bridge in `mcp_client.py` (asyncio.run() per call pattern)
- Subprocess lifecycle management (start, detect crash, cleanup)
- Tool routing in `execute_tool()` that doesn't break existing tools
- Thread safety when the runtime worker thread calls MCP client

**RULE:** If something is hard, that's where you START, not where you skip to later. Implement the hardest component first, verify it works, then build the easy parts around it.

### GUARD 5: TEST THE SAD PATH, NOT JUST THE HAPPY PATH

M2.5 writes tests that verify correct input produces correct output. That's only half the job.

**For EVERY test file:**
- Minimum 30% of tests must be sad-path tests (invalid input, missing data, wrong types)
- Every `ValueError` / `TypeError` / `ConnectionError` you raise must have a test that triggers it
- Every `None` return path must have a test that exercises it
- Test what happens when a dependency is missing / unavailable

**RULE:** If your test file has 0 tests that pass invalid input, you are NOT DONE.

### GUARD 6: WIRE IT UP — PROVE THE CONNECTION EXISTS

M2.5 writes functions but doesn't verify they're called. This is WRONG.

**After implementing EVERY function:**
1. `grep -rn "your_function_name" .` — WHERE is it called?
2. Trace the full path: user action → handler → your function → result
3. If no call site exists, ADD ONE NOW or you have dead code
4. Verify imports are correct at every level

**RULE:** If you can't trace the execution path from entry point to your code, you have a wiring bug.

---

## PHASE B SPECIFIC REQUIREMENTS

### What Phase B Delivers

Per the spec (`docs/specs/SPEC-MCP-client-integration.md`):

- [ ] **Modify `agent/tools.py`** — Add MCP routing in `execute_tool()`
- [ ] **Add `get_tools_for_api()`** in `utils/mcp_client.py` (NOT agent/tools.py — the spec was corrected)
- [ ] **Modify `agent/config.py`** — Load and validate `mcp_servers` YAML field
- [ ] **Modify `agent/runtime.py`** — Merge built-in + MCP tools before LLM call
- [ ] **Add `mcp_servers` field** to Conversation dataclass in `models/conversation.py`
- [ ] **Write `tests/test_mcp_client.py`** — Test the MCP client library (Phase A leftover)
- [ ] **Write tests for all modifications** — Runtime integration, tool routing

### Exit Criteria

Agent with MCP servers configured produces a tool list that includes namespaced MCP tools (e.g., `fetch/fetch`, `time/get_current_time`) alongside built-in tools.

---

## IMPLEMENTATION ORDER (MANDATORY)

Follow this exact order. Do not skip ahead.

### Step 1: Read ALL files you will modify

Before writing ANY code, read these files COMPLETELY:
- `docs/specs/SPEC-MCP-client-integration.md` — the entire spec
- `agent/tools.py` — understand `execute_tool()`, `get_tool_definitions_for_api()`
- `agent/runtime.py` — understand the tool loop (around line 950-1050)
- `agent/config.py` — understand `AgentConfig` dataclass
- `models/conversation.py` — understand `Conversation` dataclass
- `utils/mcp_config.py` — what QTR wrote in Phase A (has known bugs)
- `docs/ARCHITECTURE.md` — understand layer rules

**Checkpoint 0:** List every function you need to modify and what you'll change. One sentence each.

### Step 2: Write `utils/mcp_client.py` (HARDEST — do this first)

This is the async bridge. The MCP Python SDK is entirely async. Your code must:
1. Use `asyncio.run()` per call (the spec's simplified pattern)
2. Connect via `stdio_client` + `ClientSession` context managers
3. Expose synchronous wrappers: `connect()`, `disconnect()`, `call_tool()`, `discover_tools()`
4. Handle subprocess crashes gracefully
5. Include `get_tools_for_api()` for the runtime to call

**Key SDK types you need:**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent, ImageContent
```

**Checkpoint 1:** Write the client. Verify imports work. Run a quick test connecting to the `fetch` MCP server.

### Step 3: Modify `agent/tools.py` — Add routing

Add ONE check at the top of `execute_tool()`:
```python
if "/" in name:
    server_name, _, tool_name = name.partition("/")
    # Route to MCP client
```

This MUST NOT change any existing behavior. If the tool name has no `/`, existing code runs unchanged.

**Checkpoint 2:** Run existing tests (`tests/test_tools.py`). ALL must pass. Zero regressions.

### Step 4: Modify `models/conversation.py` — Add `mcp_servers` field

Add `mcp_servers: list[str] = field(default_factory=list)` to the Conversation dataclass.

**Checkpoint 3:** Run `tests/test_conversation.py`. ALL must pass.

### Step 5: Modify `agent/runtime.py` — Merge tool lists

In the tool loop (around line 957), after `tools = get_tool_definitions_for_api(conv.allowed_tools)`:
1. Check if `conv.mcp_servers` is non-empty
2. If so, call `get_tools_for_api(conv.mcp_servers)` from `utils/mcp_client.py`
3. Extend the tools list

**Checkpoint 4:** Run `tests/test_agent_runtime.py`. ALL must pass.

### Step 6: Wire `mcp_servers` from agent YAML through to Conversation

Trace the chain:
- `utils/agent_defs.py` → parses agent YAML → extracts `mcp_servers`
- `agent/runtime.py` → `create_conversation()` or `send_message()` → passes to Conversation
- `Conversation.mcp_servers` → used in tool loop

Find where `allowed_tools` flows and follow the same path for `mcp_servers`.

**Checkpoint 5:** Verify with grep that `mcp_servers` appears in the chain from YAML load to tool loop.

### Step 7: Write tests

Write `tests/test_mcp_client.py` with:
- Happy path: connect, discover, call, disconnect (mock the SDK)
- Sad path: connect to missing server, call on disconnected server, invalid args
- Error handling: subprocess crash, timeout, malformed response

**Checkpoint 6:** All new tests pass. All existing tests pass. Zero regressions.

### Step 8: SPEC COMPLIANCE CHECK (Guard 1)

Open `docs/specs/SPEC-MCP-client-integration.md`. Go through Phase B checklist. For each item:
- Is it implemented? Where?
- Is it tested?
- Does it match the spec's description?

**If ANY item is not done, you are NOT done.**

---

## KNOWN M2.5 BUGS FROM PHASE A — DO NOT REPEAT

QTR wrote Phase A with M2.5 and these bugs were found:

1. **No input validation** — `args` accepted as string, `env` accepted as string, server names with `/` accepted
2. **Missing spec requirements** — `to_stdio_params()` was in spec but never implemented
3. **No error messages** — `AttributeError` instead of `ValueError` with context
4. **Tests only test happy path** — 11 tests, 0 tested invalid input
5. **Hard parts skipped** — `mcp_client.py` never written, no mention of it
6. **No wiring verification** — no grep to confirm code is actually called

**DO NOT REPEAT THESE MISTAKES.**
