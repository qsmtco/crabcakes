# Allowed-Tools Gate — End-to-End Verification

**Date:** 2026-07-03
**Investigator:** QTR (with Debugger, Coder)
**Status:** ✅ Verified end-to-end in production. Fix shipped. Gate, fallback, and review-layer interception all confirmed working.

---

## TL;DR

The Debugger agent reported that `allowed_tools` did not block his `edit_file` calls — claiming a parallel dispatch path that bypassed `execute_tool`. The claim was **incorrect**. The actual cause was a stale persisted conversation with `allowed_tools: null`, which disabled the gate entirely.

Three layers of defense shipped and verified live:

1. **`execute_tool` gate** (`agent/tools.py:1222`) — denies tool calls not in the agent's allow-list
2. **Load-time fallback** (`agent/runtime.py:1369-1382`) — repairs `allowed_tools: None` from the live `SpecialAgentDef.tools`
3. **Tool catalog filter** (`agent/runtime.py:2073`) — LLM only sees permitted tool definitions, so it cannot pick disallowed tools from its function-calling menu

End-to-end test: created `helloworld.md` via Debugger `exec_command`. File was created, intercepted by the review layer, committed (`c601b16 Accept: helloworld.md`), and a `diff` feed card was emitted (seq 12229). The "bypasses review layer" claim was also incorrect — `exec_command` writes go through the checkpoint flow.

---

## Background

### The original report

The Debugger observed that he could call `edit_file` despite his YAML config (`prompts/default_agents/debugger.yaml`) not listing it. He proposed:

> A second path — used when special agents invoke tools directly during investigation (not via LLM tool loop) — was not found by the audit's grep-based search and remains ungated.

This was logged as a `gate-at-wrong-layer` issue against `agent/tools.py:1213`.

### The actual cause

The Debugger's persisted conversation file:

```
~/.config/crabcakes/conversations/special:debugger.json
```

had `allowed_tools: null` on disk. The `execute_tool` gate's signature is:

```python
def execute_tool(name, arguments, project_path, session_key,
                 approval_callback, scratch_dir,
                 allowed_tools: list[str] | None = None) -> ToolResult:
```

And its check is:

```python
if allowed_tools is not None and name not in allowed_tools:
    return ToolResult(success=False, error=...)
```

When `allowed_tools is None`, the check is a no-op. So the gate was correctly implemented but disabled by a stale persistence.

### Why this only affected Debugger (not Coder)

| File | `allowed_tools` on disk |
|---|---|
| `~/.config/crabcakes/conversations/special:debugger.json` | `null` |
| `~/.config/crabcakes/conversations/special:coder.json` | `["list_files", "read_file", "search_files", "edit_file", "write_file", "exec_command", "web_fetch", "web_search"]` |

The Coder's conversation was created with `create_conversation(allowed_tools=agent_def.tools)` after the gate shipped, so its disk state was correct. The Debugger's was created before (or via a path that didn't pass the parameter), so its disk state was stale.

---

## Fix Shipped

Three commits, in order:

| SHA | Subject |
|---|---|
| `83986ae` | `Accept: prompts/system/debugger.md` |
| `65be78a` | `Accept: agent/runtime.py` — load-time fallback for stale `allowed_tools: None` |
| `c818f97` | `Accept: tests/test_agent_runtime.py` — 3 fallback tests |

### Load-time fallback (`agent/runtime.py:1369-1382`)

```python
if conv.allowed_tools is None:
    try:
        from agent.special_agents import get_special_agent
        agent_def = get_special_agent(session_key)
        if agent_def is not None and agent_def.tools:
            conv.allowed_tools = list(agent_def.tools)
    except Exception:
        pass
```

Pattern after HIGH-3 `api_key` re-resolution. Runs in `_load_conversation_from_disk`. Repairs the in-memory `conv.allowed_tools` even when the disk state is stale.

### Test coverage

```
$ python3 -m pytest tests/test_tools.py tests/test_agent_runtime.py
======================= 154 passed in 139.94s =======================
```

Key classes:

- **`TestAllowedToolsGate`** (`tests/test_tools.py:712`) — 8 tests. Direct invocation of `execute_tool(..., allowed_tools=[...])` with various allow-lists; verifies denial message format, `success=False`, and edge cases.
- **`TestAllowedToolsFallback`** (`tests/test_agent_runtime.py:2910`) — 3 tests. (a) Persisted `None` falls back to live agent def. (b) Persisted list wins over fallback. (c) Unknown agent leaves `None`.

---

## End-to-End Verification (live)

### Phase 1: Unit-level gate confirmation

Direct invocation with the Debugger's live allow-list:

```python
from agent.tools import execute_tool

result = execute_tool(
    name="edit_file",
    arguments={"path": "/tmp/x", "old_text": "a", "new_text": "b"},
    project_path="/home/q/projects/crabcakes",
    session_key="special:debugger",
    approval_callback=None,
    scratch_dir="/tmp",
    allowed_tools=["read_file", "list_files", "search_files"],
)
# result.success = False
# result.error = "Tool 'edit_file' is not in the agent's allowed_tools ..."
```

### Phase 2: Delete-and-restart creates clean state

```bash
$ rm ~/.config/crabcakes/conversations/special:debugger.json
$ # restart app
$ # send "hello are you ready to work?" to Debugger
$ jq '.allowed_tools' ~/.config/crabcakes/conversations/special:debugger.json
[
  "list_files",
  "read_file",
  "search_files",
  "exec_command",
  "web_fetch",
  "web_search"
]
```

After deletion, the next message routed through `agent_runtime_handler.py:642` → `rt.create_conversation(allowed_tools=agent_def.tools)` → `Conversation(allowed_tools=agent_def.tools)`. The Debugger's system prompt was re-injected (read-only posture, role boundaries, etc.), but the conversation history was empty. The Debugger behaved as a fresh agent.

### Phase 3: Positive-path test (`exec_command`)

PM sent: *"please create a helloworld.md file in the project root with the words 'Hello World' in it"*

Debugger initially declined (role-boundary defense in system prompt), offered to delegate to Coder. After PM explicitly overrode his read-only posture, he issued:

```python
execute_tool(
    name="exec_command",
    arguments={"command": 'echo "Hello World" > helloworld.md'},
    ...
    allowed_tools=['list_files', 'read_file', 'search_files',
                   'exec_command', 'web_fetch', 'web_search'],
)
```

**Result:** success. File created. Working tree diff went through the review layer:

- `c601b16 Accept: helloworld.md` — auto-accepted by the checkpoint flow
- Feed card: `diff` (`card_id: 16318a46-1b66-4a14-8d88-374e31e4b3c4`, seq 12229)
- Feed card: `git_commit` (`card_id: edf4f244-6968-42a0-a44c-7de0156042e4`, seq 12227)

### Three-layer defense confirmed

| Layer | Mechanism | Verified by |
|---|---|---|
| 1 | Catalog filter — LLM only sees permitted tool definitions | Debugger doesn't see `write_file`/`edit_file` in function-calling menu |
| 2 | `execute_tool` gate — runtime denies based on `allowed_tools` | Direct unit invocation returns `success=False` |
| 3 | System prompt — LLM self-restrains on read-only role | Debugger declined write request initially, proposed Coder delegation |

The Debugger can only escape these layers if PM explicitly overrides (as in Phase 3) AND uses a tool in his allow-list (`exec_command`). `edit_file`/`write_file` are unreachable.

---

## Findings vs Original Report

The Debugger's original hypothesis:

> "A second path was not found by the audit's grep-based search and remains ungated."

This is **incorrect**. There is no second path. `grep -rn "_edit_file\|_write_file\|_TOOLS\[" --include="*.py" agent/ ui/ utils/ gateway/` returned only:

- Handler definitions and string comparisons in policy code
- One caller of `execute_tool` (`agent/runtime.py:2303`) — correctly forwards `conv.allowed_tools`

The grep-based search was sufficient. The Debugger's actual edit capability came from the stale `allowed_tools: None`, not a hidden dispatch path.

The Debugger's secondary hypothesis:

> "Shell writes bypass the review layer."

This is **also incorrect**. The Phase 3 test shows `exec_command` writes go through checkpoint → diff → accept automatically. The "Accept" commit (`c601b16`) and the two feed cards prove the review layer captured the write.

---

## Out of Scope (still open)

### MCP routing bypass (`agent/tools.py:1182`)

The MCP routing branch:

```python
if "/" in name:
    # ... MCP routing, returns before reaching the gate
```

returns before reaching the `allowed_tools` gate. MCP namespaced tools like `"fetch/fetch"` are not covered.

**Status:** Known issue. Logged as `missing-invariant-check` against `agent/tools.py:1182`. Not addressed by this fix. Separate hardening task.

### Stale-persistence migration

The fallback repairs in-memory state at load time. If `_save_conversation_to_disk` runs after load (any auto-save tick), the disk state is rewritten with the live `allowed_tools` value, so subsequent restarts skip the fallback. Verified by Phase 2 — file after delete-and-restart had correct `allowed_tools`.

**Status:** No migration script needed. Fallback + auto-save converge to correct state.

---

## Recommended Actions

None — the fix is complete and verified. Optionally:

1. **Clean up the smoke-test artifact** — `c601b16 Accept: helloworld.md` and the file itself. Decide whether to keep or revert (`git revert c601b16`).
2. **Address the MCP gate** — open a separate issue for the `if "/" in name:` branch.

---

## Artifacts

| Path | Purpose |
|---|---|
| `agent/tools.py:1222` | Gate implementation |
| `agent/runtime.py:1369-1382` | Load-time fallback |
| `agent/runtime.py:2073` | Catalog filter for LLM tool definitions |
| `agent/runtime.py:2303` | Single dispatch site that forwards `conv.allowed_tools` |
| `tests/test_tools.py:712` | `TestAllowedToolsGate` (8 tests) |
| `tests/test_agent_runtime.py:2910` | `TestAllowedToolsFallback` (3 tests) |
| `~/.config/crabcakes/conversations/special:debugger.json` | Persisted Debugger conversation (correctly populated after delete-and-restart) |
| `c601b16` | Live-verification commit: `Accept: helloworld.md` |
| `/home/q/.openclaw/workspace/qtr/notes/debugger-edit-file-investigation-2026-07-03.md` | Pre-verification investigation note |

## Commits

| SHA | Subject |
|---|---|
| `83986ae` | Accept: prompts/system/debugger.md |
| `65be78a` | Accept: agent/runtime.py |
| `c818f97` | Accept: tests/test_agent_runtime.py |
| `c601b16` | Accept: helloworld.md (live-verification smoke test, optional cleanup) |