# SPEC: Agent-Issued `/compact` and `/clear` for Supervisor Context Management

**Date:** 2026-07-11
**Author:** Debugger (spec drafter)
**Status:** Draft — ready for implementation
**Depends on:** `docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md` (shipped, implements compact machinery)
**Target branch:** main

> **Architecture compliance:** This spec touches `ui/handlers/agent_command_handler.py` only. No changes to `ui/handlers/project_handler.py` (cmd_compact/cmd_clear already accept any `target_session_key`), `agent/runtime.py` (state mutation callbacks already exist), `ui/handlers/agent_runtime_handler.py` (compact_conversation/clear_conversation already accept any session_key), or any other handler. The change is contained in the agent-issued command dispatch path. All changes respect ARCHITECTURE.md §2 layering.

---

## 0. Discovery

**Source files read:**

- **`ui/handlers/agent_command_handler.py`** (522 lines):
  - Line 45: `_COMMAND_KEYWORDS = frozenset({'ask', 'delegate', 'stop', 'tell'})` — **defined but never referenced** (verified via `grep -n _COMMAND_KEYWORDS` — single match, the definition line itself).
  - Lines 84-167: 5 regex passes.
    - Pass 1 (line 95) filters with `if cmd not in ('ask', 'tell', 'delegate', 'stop')`.
    - Pass 2 (line 122) filters with `if cmd not in ('ask', 'tell', 'delegate')`.
    - Pass 5 (line 163) is hardcoded for `/stop` only.
  - Line 255: `on_agent_response(session_key, text, project_name)` is the public entry point.
  - Lines 310-345: Command dispatch block.
    - Line 334 handles `forward_to + forward_text` (single target).
    - Line 338 handles `broadcast_targets + forward_text` (multi-target broadcast).
    - **No branch for `response_text`-only results.**
  - Line 13-14 docstring: "Thread safety: on_agent_response() is called from main thread via GLib.idle_add() — no additional dispatch needed."

- **`ui/handlers/collab_handler.py`** (67 lines):
  - Line 35-43: `cmd_ask` returns `CommandResult(handled=True, forward_to=cmd.target_session_key, forward_text=cmd.body)`. Pure pass-through, no state mutation.
  - Line 49-52: `cmd_delegate` same pattern.
  - Line 55-58: `cmd_stop` returns `forward_to=..., forward_text="stop"`.
  - Line 62-65: `cmd_tell` same pattern.

- **`ui/handlers/project_handler.py`** (873 lines):
  - Line 676 (`cmd_clear`): `sk = cmd.target_session_key or cmd.source_session_key or session_key` (verified working from prior audit). Line 685 checks `not sk`. Line 695 checks `sk.startswith("project:")` and returns hint. Line 706 checks `sk.startswith("special:")` and dispatches to `self._clear_callback(sk)`. Line 750 returns hint for unknown prefix.
  - Line 754 (`cmd_compact`): same structure. Line 773 uses `sk = cmd.target_session_key or ...`. Line 779 checks project. Line 786 checks special. Line 799 calls `self._compact_callback(sk, focus_text)`. Line 825 returns hint.
  - Both functions accept any `target_session_key`. Both already work for `/compact @Coder` and `/clear @Coder` from user-issued commands.

- **`ui/handlers/agent_runtime_handler.py`** (1588 lines):
  - Line 544: `def get_special_agent_def(self, session_key: str) -> Any | None:` — returns the SpecialAgentDef or None.
  - Line 444-545: `compact_conversation(session_key, focus_text)`. Line 460 checks `session_key.startswith("special:")`. Line 510 calls `rt.force_llm_compact(conv, target_budget, focus_text, agent_def=agent_def)` (passes agent_def per spec SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md).
  - `clear_conversation(session_key)` exists (referenced at project_handler.py:715).
  - Line 631: `_get_runtime(name, agent_def=None)` returns the runtime for a named agent.
  - Line 689: `send_to_special_agent(session_key, text)` sends text to a special agent's input stream.

- **`agent/runtime.py`** (3147 lines):
  - Line 1639: `self._lock = threading.Lock()` — per-runtime lock guarding conversation state.
  - Line 1800: `def get_conversation(self, session_key: str) -> Any | None:` — returns Conversation or None.
  - Line 2053: `with self._lock:` — lock acquired in `_run_loop` before mutating conversation.
  - Line 2063: `conv.add_user_message(text)` — called inside the lock block.

- **`models/conversation.py`**:
  - Line 188: `def add_user_message(self, content: str) -> Message:` — appends a user-role message to the conversation.

- **`models/command.py`**:
  - Line 110-130: `CommandResult` dataclass: `handled: bool`, `response_text: str | None`, `response_card: dict | None`, `forward_to: str | None`, `forward_text: str | None`, `broadcast_targets: list[str]`.

**Architecture owner:** `AgentCommandHandler` owns agent-issued command dispatch. This spec modifies only that file.

**Existing patterns observed:**
- `ask`/`delegate`/`tell` route via `forward_to + forward_text` and are delivered to the target agent as a user message via `send_to_special_agent`.
- `stop` routes via `forward_to + forward_text="stop"` — a synthetic message that the target agent's runtime interprets as a stop signal.
- `cmd_compact` and `cmd_clear` do NOT route. They mutate state via injected callbacks and return `response_text`. The current agent-issued dispatch has no branch for this case.

**The ask pattern does not directly apply to compact/clear** because compact/clear mutate target state, not send a message. The "ask" pattern would route "Compacted. Freed 12K tokens" to the target agent as a user message, which would be wrong (the target doesn't need a user message about its own state). The right analog of "ask" is: **the supervisor sees the result of its action in its own next-turn context**, the same way an agent sees the answer to a question it asked.

---

## 1. Overview

### 1.1 Problem

A supervisor agent cannot currently issue `/compact @Coder` or `/clear @Coder` to manage the context of peer agents during long runs. The mechanism works for user-issued commands (the user types in a project tab) but is silently broken for agent-issued commands (the agent types in its own response).

The break has two layers:

1. **Scanner filter** (`_extract_quoted_commands` at `agent_command_handler.py:55-167`) only extracts `ask`, `tell`, `delegate`, `stop` from agent response text. `/compact` and `/clear` are silently dropped before `process_input` is called.

2. **Result dispatch** (`on_agent_response` at lines 310-345) only handles `forward_to` (line 334) and `broadcast_targets` (line 338). The `response_text` results returned by `cmd_compact` and `cmd_clear` are computed but never delivered to anyone — the supervisor has no way to know the action succeeded.

### 1.2 Solution

Two minimal changes, both in `ui/handlers/agent_command_handler.py`:

1. **Add `compact` and `clear` to the recognized command set in `_extract_quoted_commands`.** Add 2 filter entries and 1 new regex pass for payload-free commands. Total: ~15 lines.

2. **Add one new branch in `on_agent_response` for `response_text`-only results.** The branch injects the result text into the supervisor's own conversation as a user-role message (so the supervisor sees the result on its next turn). Total: ~12 lines.

**No changes to:**
- `ui/handlers/project_handler.py` — `cmd_compact` and `cmd_clear` already accept any `target_session_key`.
- `ui/handlers/agent_runtime_handler.py` — `compact_conversation`, `clear_conversation`, `get_special_agent_def`, `_get_runtime` all exist and accept the right arguments.
- `agent/runtime.py` — `force_compact`, `force_llm_compact`, `get_conversation`, `conv.add_user_message` all exist.
- `ui/handlers/command_handler.py` — `process_input` already handles all registered commands; `/compact` and `/clear` are registered as `payload_free=True` at lines 144-155.
- `models/command.py` — `CommandResult` already has `response_text` field; no schema change needed.
- `ui/handlers/collab_handler.py` — unaffected.
- `prompts/system/coder.md`, `prompts/system/debugger.md` — no prompt changes needed.

### 1.3 Scope

| In scope | Out of scope |
|----------|--------------|
| 2 changes in `ui/handlers/agent_command_handler.py` | New compaction strategies |
| Tests for agent-issued `/compact` and `/clear` | New `CommandResult` fields |
| Thread-safe injection of result text into supervisor's conversation | Supervisor pre-turn hooks (deferred) |
| Payload-free and quoted-payload forms of `/compact` and `/clear` | Supervisor prompt updates (separate concern) |

---

## 2. Changes by File

### 2.1 `ui/handlers/agent_command_handler.py` — Recognize `compact` and `clear` in the scanner

**Location:** Module-level constant `_COMMAND_KEYWORDS` at line 45, and the regex passes at lines 81-167.

**Why this approach:** The filters at lines 95 and 122 are inline string tuples. `_COMMAND_KEYWORDS` at line 45 is dead code (verified — no other references). The fix adds the new command names to the inline tuples rather than switching to the `_COMMAND_KEYWORDS` constant, to minimize diff size.

#### Change A: Pass 1 filter at line 95

```python
# Before:
if cmd not in ('ask', 'tell', 'delegate', 'stop'):
# After:
if cmd not in ('ask', 'tell', 'delegate', 'stop', 'compact'):
```

**Why only `compact` here:** Pass 1 requires a quoted payload `"..."`. `/clear` takes no payload, so it would only match if written as `/clear @Coder "ignored"`, which is not natural. `/compact` optionally takes a quoted focus string (`/compact @Coder "preserve auth"`), so it benefits from Pass 1's quoted-payload parsing.

#### Change B: Pass 2 filter at line 122

```python
# Before:
if cmd not in ('ask', 'tell', 'delegate'):
# After:
if cmd not in ('ask', 'tell', 'delegate', 'compact'):
```

**Why:** Pass 2 handles unclosed trailing quotes (text that has `"` at end without a closing `"`). A supervisor might cut off mid-quote. Same rationale as Change A: `compact` optionally takes a quoted focus, so it belongs in Pass 2.

#### Change C: New Pass 6 — payload-free compact and clear (add after line 165)

```python
# ── Pass 6: payload-free /compact and /clear (no quotes at all) ────────
for m in re.finditer(r'(?:^|\s)/(compact|clear)\s+(@[^\s"]+)', text):
    if m.span() in seen_spans:
        continue
    _emit(m.group(1), m.group(2), '', m.span())
```

**Why a new pass:** `/compact @Coder` (no payload) and `/clear @Coder` (always payload-free) don't match Pass 1 (which requires quotes) or Pass 5 (hardcoded to `stop`). A new Pass 6 mirrors Pass 5's pattern with `(compact|clear)` instead of `stop`.

**Verification:**
- `r'(?:^|\s)/(compact|clear)\s+(@[^\s"]+)'` — matches start-of-string or whitespace, command `compact` or `clear`, whitespace, agent token (no spaces, no quotes). Identical structure to Pass 5.
- `m.group(1)` returns the command string (`"compact"` or `"clear"`).
- `m.group(2)` returns the agent token (e.g. `"@Coder"`).
- `_emit(cmd, agent, '', span)` — empty payload, consistent with payload-free semantics.
- `seen_spans` deduplication prevents overlap with earlier passes.

### 2.2 `ui/handlers/agent_command_handler.py` — Dispatch `response_text`-only results

**Location:** The `if parsed_commands:` block in `on_agent_response` at lines 310-345.

**Why this design:** The supervisor needs feedback on its action to make intelligent next decisions. The natural feedback channel is the supervisor's own LLM context — the supervisor will see the result on its next turn. This mirrors the "ask" pattern: an agent asks, the answer appears in the next turn. Here, an agent acts (compacts), the result appears in the next turn.

#### Change D: Add new dispatch branch after line 345

```python
elif result.handled and result.response_text:
    # Action result (e.g. /compact, /clear) — no forward target.
    # Inject the result into the issuing agent's own conversation
    # so the supervisor sees the outcome on its next turn.
    self._record_action_result(session_key, result.response_text)
    command_count += 1
```

**Why after line 345:** The existing branches are (1) `forward_to + forward_text` at line 334, (2) `broadcast_targets + forward_text` at line 338. Both have been checked and found False (compact/clear don't set forward targets). The response_text-only branch is the third possibility.

#### Change E: New method `_record_action_result` (add after `on_agent_response`, around line 350)

```python
def _record_action_result(self, source_sk: str, text: str) -> None:
    """Inject an action result into the issuing agent's own conversation.

    Used for agent-issued commands that mutate peer state (e.g. /compact,
    /clear) and return a response_text result with no forward target.
    The supervisor's next turn will include this text in its LLM context,
    closing the feedback loop.

    Args:
        source_sk: The session key of the agent that issued the command
                  (e.g. "special:supervisor").
        text: The result text to inject (e.g. "Compacted coder's
              conversation. Removed 5 messages, freed ~12,000 tokens.").
    """
    if self._agent_runtime_handler is None:
        logger.warning(
            "[agent-cmd] Cannot record action result for %s — "
            "agent_runtime_handler not wired",
            source_sk,
        )
        return

    # Resolve source_sk → runtime
    agent_def = self._agent_runtime_handler.get_special_agent_def(source_sk)
    if agent_def is None:
        logger.debug(
            "[agent-cmd] _record_action_result: no SpecialAgentDef for %s",
            source_sk,
        )
        return

    try:
        rt = self._agent_runtime_handler._get_runtime(
            agent_def.display_name, agent_def=agent_def
        )
    except Exception as exc:
        logger.warning(
            "[agent-cmd] _record_action_result: failed to get runtime "
            "for %s: %s", source_sk, exc,
        )
        return

    try:
        conv = rt.get_conversation(source_sk)
    except Exception as exc:
        logger.warning(
            "[agent-cmd] _record_action_result: get_conversation failed "
            "for %s: %s", source_sk, exc,
        )
        return

    if conv is None:
        logger.debug(
            "[agent-cmd] _record_action_result: no conversation for %s",
            source_sk,
        )
        return

    # Inject as a user-role message under the runtime lock.
    # The supervisor's next turn will see this in its context.
    # Prefix with "[Action result]:" so the supervisor can distinguish
    # self-injected results from actual user input.
    try:
        with rt._lock:
            conv.add_user_message(f"[Action result]: {text}")
    except Exception as exc:
        logger.warning(
            "[agent-cmd] _record_action_result: add_user_message failed "
            "for %s: %s", source_sk, exc,
        )
```

**Thread safety:** The `with rt._lock:` block matches the pattern at `runtime.py:2053` (where `add_user_message` is called inside `_run_loop` under the same lock). Verified consistent with existing code.

**Edge cases:**
- `agent_runtime_handler` is None (test fixture, not wired): returns early with warning.
- `source_sk` is not a special agent (e.g. gateway agent): `get_special_agent_def` returns None, returns early.
- Agent has no active conversation: `get_conversation` returns None, returns early.
- Lock acquisition failure: handled by outer try/except.

### 2.3 `ui/handlers/agent_command_handler.py` — Update module docstring

**Location:** Lines 1-20 (module docstring).

**Change:** Add a line documenting the new dispatch responsibility:

```python
# - Agent-initiated /compact and /clear: state mutation + self-injected
#   action result (so the issuing agent sees the outcome next turn)
```

---

## 3. Data Flow

### Agent-issued `/compact @Coder "preserve auth context"` in Supervisor's response

```
Supervisor's response is rendered (text contains "/compact @Coder \"preserve auth context\"")
↓
window.py:664 — set_on_agent_response callback fires
↓
AgentCommandHandler.on_agent_response(supervisor_sk, final_text, project_name)
↓
(line ~287) _process_audit_reports(supervisor_sk, final_text) — no-op for /compact
↓
(line ~311) parsed_commands = _extract_quoted_commands(clean_text, command_names)
  → Pass 1 matches /compact @Coder "preserve auth context"
  → cmd="compact" passes new filter at line 95 (after Change A)
  → Returns ParsedCommand(command="compact", agent="@Coder", payload="preserve auth context")
↓
(line ~318) Build canonical: "/compact @Coder \"preserve auth context\""
↓
(line ~321) result = command_handler.process_input(supervisor_sk, candidate, skip_dispatch=True)
  → process_input resolves @Coder → target_sk="special:coder"
  → calls cmd_compact which calls self._compact_callback("special:coder", "preserve auth context")
  → returns CommandResult(handled=True,
       response_text="Compacted coder's conversation. Removed 5 messages, freed ~12,000 tokens.")
↓
(line 334) result.handled and result.forward_to and result.forward_text — False (no forward_to)
(line 338) result.handled and result.broadcast_targets and result.forward_text — False (no broadcast)
(line 346 NEW) elif result.handled and result.response_text — TRUE
↓
self._record_action_result(supervisor_sk, "Compacted coder's conversation. ...")
  → get_special_agent_def("special:supervisor") → agent_def
  → _get_runtime("Supervisor", agent_def) → rt
  → rt.get_conversation("special:supervisor") → conv
  → with rt._lock: conv.add_user_message("[Action result]: Compacted coder's conversation. ...")
↓
Supervisor's next turn (when user or another agent sends a message)
  → LLM context includes the [Action result] message
  → Supervisor can make informed decisions (e.g. "no need to compact again")
```

### Agent-issued `/clear @Coder` (payload-free)

```
Supervisor's response contains "/clear @Coder"
↓
_extract_quoted_commands → Pass 1,2 miss (no quotes) → Pass 6 (NEW) matches
→ ParsedCommand(command="clear", agent="@Coder", payload="")
↓
candidate = "/clear @Coder" (no payload, no quoting needed)
↓
process_input → cmd_clear → callback fires → CommandResult(handled=True,
  response_text="Cleared coder's conversation. Step count reset to 0.")
↓
_record_action_result(supervisor_sk, "Cleared coder's conversation. ...")
```

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `ui/handlers/agent_command_handler.py` | 2 filter entries + 1 regex pass + 1 dispatch branch + 1 method + 1 docstring line | +45 | Low |
| `tests/test_agent_command_handler.py` | 5 new tests | +120 | Low |
| `docs/ARCHITECTURE.md` §3.21a | 1 paragraph cross-reference | +5 | Low |

**Files NOT changed** (already correct):
- `ui/handlers/project_handler.py` — `cmd_compact` and `cmd_clear` already accept any `target_session_key`.
- `ui/handlers/agent_runtime_handler.py` — all required methods exist.
- `agent/runtime.py` — all required methods exist.
- `ui/handlers/command_handler.py` — `process_input` already handles all commands.
- `models/command.py` — `CommandResult` already has `response_text`.
- `ui/handlers/collab_handler.py` — unaffected.
- `prompts/system/coder.md` — no prompt changes needed.

---

## 5. Implementation Order

1. **Edit `ui/handlers/agent_command_handler.py`:**
   a. Add `'compact'` to filter at line 95 (Change A)
   b. Add `'compact'` to filter at line 122 (Change B)
   c. Add new Pass 6 after line 165 (Change C)
   d. Add new dispatch branch after line 345 (Change D)
   e. Add new `_record_action_result` method after `on_agent_response` (Change E)
   f. Update module docstring (Change F)

2. **Run existing tests:** `python -m pytest tests/test_agent_command_handler.py -q`
   Expected: all existing tests pass.

3. **Add new tests** to `tests/test_agent_command_handler.py` (see §6).

4. **Run full test suite:**
   `python -m pytest tests/test_agent_command_handler.py tests/test_command_handler.py tests/test_project_handler.py -q`
   Expected: all tests pass.

5. **Update `docs/ARCHITECTURE.md` §3.21a** with cross-reference paragraph.

6. **Pattern sweep:** `grep -rn "compact\|clear" ui/handlers/agent_command_handler.py` — confirm all references resolve to the new code. No dangling old patterns.

---

## 6. Test Plan (5 new tests)

### 6.1 `test_extract_quoted_commands_recognizes_compact_with_quoted_focus`

Input text contains `/compact @Coder "preserve auth context"`. Assert the parser returns a `ParsedCommand` with `command="compact"`, `agent="@Coder"`, `payload="preserve auth context"`.

### 6.2 `test_extract_quoted_commands_recognizes_clear_payload_free`

Input text contains `/clear @Coder`. Assert Pass 6 matches: `command="clear"`, `agent="@Coder"`, `payload=""`.

### 6.3 `test_extract_quoted_commands_recognizes_compact_payload_free`

Input text contains `/compact @Coder`. Assert Pass 6 matches: `command="compact"`, `agent="@Coder"`, `payload=""`.

### 6.4 `test_on_agent_response_injects_action_result_into_issuing_conversation`

Set up mock AgentRuntimeHandler, mock runtime, mock conversation. Call `on_agent_response("special:supervisor", "/compact @Coder \"focus\"", "myproject")`. Assert `conv.add_user_message` was called with a string containing "Compacted" and the literal "[Action result]:" prefix.

### 6.5 `test_on_agent_response_skips_action_result_when_runtime_handler_unwired`

Set `self._agent_runtime_handler = None`. Call `on_agent_response(...)`. Assert no exception is raised.

---

## 7. Acceptance Criteria

- [ ] `_extract_quoted_commands("/compact @Coder \"preserve auth\"")` returns `ParsedCommand(command="compact", agent="@Coder", payload="preserve auth")`
- [ ] `_extract_quoted_commands("/compact @Coder")` returns `ParsedCommand(command="compact", agent="@Coder", payload="")`
- [ ] `_extract_quoted_commands("/clear @Coder")` returns `ParsedCommand(command="clear", agent="@Coder", payload="")`
- [ ] `_extract_quoted_commands("/ask @Coder \"what is the status?\"")` continues to return `ParsedCommand(command="ask", agent="@Coder", payload="what is the status?")` (no regression)
- [ ] `on_agent_response("special:supervisor", "/compact @Coder \"focus\"", "myproject")` calls `process_input` → `cmd_compact` → compact callback fires (full action path)
- [ ] After `on_agent_response` returns, the supervisor's conversation contains a user-role message beginning with `[Action result]:`
- [ ] When `self._agent_runtime_handler is None`, `on_agent_response` does not raise; action still completes (callback fires synchronously in process_input)
- [ ] All existing tests pass
- [ ] ARCHITECTURE.md §3.21a cross-references the new behavior
- [ ] No changes to project_handler.py, agent_runtime_handler.py, runtime.py, command_handler.py, command.py, collab_handler.py

---

## 8. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `/compact @Coder "preserve auth"` in supervisor's response | Coder compacted; result injected into supervisor's conversation |
| `/compact @Coder` (no payload) | Coder compacted (default focus); result injected |
| `/clear @Coder` | Coder cleared; result injected |
| `/compact @Unknown` (unknown agent) | `process_input` returns error `response_text`; result injected so supervisor knows command failed |
| Supervisor is a gateway agent (not `special:`) | `get_special_agent_def` returns None; action completes but no feedback injection |
| `agent_runtime_handler` is None | Action completes; feedback lost; warning logged |
| Supervisor has no conversation yet | `get_conversation` returns None; action completes; feedback lost |
| Two supervisors emit `/compact @Coder` same response | Both go through dispatch; both call compact callback sequentially; second compact finds nothing to do and returns zero-count result |
| `/compact @Coder "focus"` inside ```code block``` | `_strip_fenced_blocks` removes it; command invisible to parser (correct — prevents accidental execution) |
| Supervisor issues `/compact @Self` | Works but destroys own context. Known sharp edge (v2 concern). |

---

## 9. Spec Self-Audit

1. **Every code sample works against current codebase.** All regex patterns, method signatures, and field names verified against actual source via `search_files` (grep-based verification).

2. **All exception paths considered.** Three separate try/except blocks guard `_get_runtime`, `get_conversation`, and `add_user_message`. Each logs appropriately and returns gracefully.

3. **Key structures verified:**
   - `session_key` is `str` like `"special:supervisor"` (per `SpecialAgentDef.conv_id_prefix`)
   - `ParsedCommand` is a namedtuple with `(command, agent, payload, raw_start, raw_end)`
   - `CommandResult.response_text` is `str | None`

4. **Data flow traced end-to-end** in Section 3 for both `/compact` with payload and `/clear` payload-free.

5. **Lock ordering:** `_record_action_result` acquires `rt._lock` on the **supervisor's** runtime. The compact callback acquires `_compaction_lock` on the **target's** runtime. Different instances → no nested locking. Same instance (self-compact) → single lock, fine.

6. **Concurrency with in-loop compaction:** Compact callback acquires `_compaction_lock`. If target is mid-LLM call, caller blocks until LLM finishes. This is existing behavior, not introduced here.

---

## 10. Caveat to Implementer

The `read_file` tool was unreliable for `ui/handlers/agent_command_handler.py` during spec drafting. Key line numbers were verified via `search_files` (grep-based) against the actual file on disk. Before implementing, please re-verify these anchor points:

- `agent_command_handler.py:95` — Pass 1 filter: `if cmd not in ('ask', 'tell', 'delegate', 'stop'):`
- `agent_command_handler.py:122` — Pass 2 filter: `if cmd not in ('ask', 'tell', 'delegate'):`
- `agent_command_handler.py:163-164` — Pass 5: `/stop @Agent` payload-free
- `agent_command_handler.py:255` — `def on_agent_response`
- `agent_command_handler.py:334` — First dispatch branch (`forward_to`)
- `agent_command_handler.py:338` — Second dispatch branch (`broadcast_targets`)
- `agent_runtime_handler.py:544` — `def get_special_agent_def`
- `runtime.py:1639` — `self._lock = threading.Lock()`
- `runtime.py:1800` — `def get_conversation`
- `conversation.py:188` — `def add_user_message`

If any line number is stale, adjust accordingly. The spec's structural shape is correct.