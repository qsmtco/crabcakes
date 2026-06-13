# A2A Quoted Payload Specification

**Date:** 2026-05-16
**Status:** DRAFT — pending Captain approval
**Replaces:** Backtick + em-dash body separator system (`_BODY_SEP`, `_extract_backtick_commands`)
**Affects files:**
- `ui/handlers/command_handler.py` — body parsing
- `ui/handlers/agent_command_handler.py` — A2A command extraction
- `prompts/system/collab.md` — agent collaboration protocol prompt
- `prompts/system/project-awareness.md` — project context prompt
- `docs/ARCHITECTURE.md` — §3.21e, command format references
- `tests/test_agent_command_handler.py` — A2A command parsing tests
- `tests/test_command_handler.py` — command parsing tests

---

## 1. Problem Statement

The current A2A command parsing uses **em-dash** (`—`) as a body separator and **backtick boundaries** to delimit commands. Both characters appear naturally in agent-generated text (prose, code, markdown), causing **delimiter collision bugs**:

- Bug #1: Regular hyphens matched the body separator regex, splitting messages at the wrong point.
- Bug #2: Internal backticks (e.g., code references like `` `match()` ``) caused the parser to truncate the payload, sending only fragments to the target agent.

The current fixes (em-dash-only separator, segment-walking parser) reduce the probability but do not eliminate the fundamental problem: the parser's framing characters overlap with the payload's character set.

## 2. Solution

Replace the em-dash body separator with **quoted payloads**. The quote marks define an unambiguous boundary — the parser never interprets content inside quotes, only finds the matching close quote. This eliminates the delimiter collision class entirely.

## 3. Command Format

### 3.1 Canonical Syntax

```
`command @Agent "payload text"
```

**Anatomy (left to right):**

| Position | Component | Rule |
|----------|-----------|------|
| 1 | Opening backtick `` ` `` | Command trigger. Exactly one backtick. |
| 2 | Command keyword | `ask`, `tell`, `delegate`, `task`, `stop` (space after keyword required) |
| 3 | `@Agent` | At-sign + agent name, case-insensitive. `@` alone = broadcast to all project members. |
| 4 | Space | Required whitespace between `@Agent` and opening quote |
| 5 | Opening `"` | Double quote — must be the next non-whitespace character |
| 6 | Payload | Literal text. All characters treated as data — backticks, em-dashes, hyphens, markdown, code, unicode. |
| 7 | Escaped `\"` | Represents a literal `"` inside the payload |
| 8 | Escaped `\\` | Represents a literal `\` inside the payload |
| 9 | Closing `"` | Terminates the payload |
| 10 | Closing backtick `` ` `` | Ends the command |

**No other escape sequences are recognized.** `\n` is treated as literal backslash + n (newlines come from actual newlines in the source text, not escape sequences).

### 3.2 Payload-Free Commands

Some commands do not carry a payload. These have a shorter form:

```
`command @Agent`
`command
```

The following commands support payload-free forms:

| Command | Payload-free form | Meaning |
|---------|-------------------|---------|
| `stop @Agent` | No payload needed | Stop collaboration with agent |
| `tasks` | No @Agent, no payload | List all tasks |
| `review` | No @Agent, no payload | Start a review session |
| `check` | No @Agent, no payload | Check changes since checkpoint |
| `accept` | No @Agent, no payload | Accept all changes |
| `reject` | No @Agent, no payload | Reject all changes |
| `status` | No @Agent, no payload | Project status summary |
| `agents` | No @Agent, no payload | List project agents |
| `cost` | No @Agent, no payload | Spending summary |
| `help [command]` | No @Agent, no payload | Show help |

If `stop` receives a payload, it is silently ignored (not an error).

### 3.3 Task Management Commands

Task commands use `@Agent` for assignment and positional arguments for IDs. The quoted payload carries descriptions or reasons:

| Command | Format | Payload meaning |
|---------|--------|-----------------|
| `task @Agent "description"` | Quoted payload = task title/description | Required |
| `done <id>` | No payload — just a task ID | N/A |
| `start <id>` | No payload — just a task ID | N/A |
| `blocked <id> "reason"` | Quoted payload = reason for block | Optional (empty = no reason) |
| `cancel <id>` | No payload — just a task ID | N/A |
| `tasks` | No payload, lists all tasks | N/A |
| `assign <id> @Agent` | `@Agent` = new assignee | N/A |
| `priority <id> <level>` | `<level>` = low/medium/high/critical | N/A |

### 3.4 Session Command

```
`session list @Agent`       — list agent's sessions
`session <ref> @Agent`      — switch agent to session <ref>
```

No quoted payload. `@Agent` is required. `<ref>` is a session number or key fragment.

### 3.5 Complete Command Reference

| Command | Aliases | Format | Payload |
|---------|---------|--------|---------|
| `ask` | `a` | `` `ask @Agent "question" `` | Required, quoted |
| `tell` | — | `` `tell @Agent "information" `` | Required, quoted |
| `delegate` | `d` | `` `delegate @Agent "task description" `` | Required, quoted |
| `stop` | — | `` `stop @Agent` `` | None (ignored if present) |
| `task` | `t` | `` `task @Agent "task title" `` | Required, quoted |
| `done` | — | `` `done <id>` `` | N/A (positional arg) |
| `start` | — | `` `start <id>` `` | N/A (positional arg) |
| `blocked` | — | `` `blocked <id> "reason" `` | Optional, quoted |
| `cancel` | — | `` `cancel <id>` `` | N/A (positional arg) |
| `tasks` | — | `` `tasks` `` | None |
| `assign` | — | `` `assign <id> @Agent` `` | N/A |
| `priority` | — | `` `priority <id> <level>` `` | N/A (positional arg) |
| `review` | — | `` `review` `` | None |
| `check` | — | `` `check` `` | None |
| `accept` | — | `` `accept` `` | None |
| `reject` | — | `` `reject` `` | None |
| `status` | `st` | `` `status` `` | None |
| `agents` | — | `` `agents` `` | None |
| `cost` | — | `` `cost` `` | None |
| `session` | `s` | `` `session list @Agent` `` / `` `session <ref> @Agent` `` | N/A |
| `help` | `?` | `` `help [command]` `` | N/A |

---

## 4. Parsing Rules

### 4.1 Strict Validation

**The format must match exactly.** Deviations produce a user-visible error message in the chat tab and the command does NOT fire.

There is no fallback to unquoted payloads. No heuristic parsing. One format, one parse path.

### 4.2 Error Cases (User Input)

When a **human user** issues a malformed command, display an error in the chat tab and do NOT execute the command:

| Condition | Error Message |
|-----------|--------------|
| Payload required but missing quotes | `Malformed command — payload must be quoted: \`ask @Agent "your message"\`` |
| No space before opening quote (e.g. `@Agent"`) | `Malformed command — space required before quote: \`ask @Agent "your message"\`` |
| Empty payload (`""`) | `Empty payload — provide a message: \`ask @Agent "your message"\`` |
| Unclosed quote (no closing `"`) | `Unclosed quote — missing closing ": \`ask @Agent "your message"\`` |
| No `@Agent` token (when required) | `No target agent. Usage: \`ask @Agent "your message"\`` |
| Unknown agent name | `Unknown agent: @{name}` |
| Multiple `@Agent` tokens | `Only one @mention allowed. Found: @{a}, @{b}` |

### 4.3 Error Cases (Agent Responses)

When an **agent** issues a command that is malformed, silently skip it — do NOT surface errors to the human's chat. Agents should not pollute the human's conversation with syntax errors.

Exception: **missing closing quote** — see §4.4.

### 4.4 Missing Closing Quote (Auto-Close)

When parsing an agent's response and the opening `"` is found but no closing `"`:

1. Check the payload length from `"` to end of available text.
2. If ≤ 4,096 characters: **auto-close** — treat the end of text as the closing quote and send the payload.
3. If > 4,096 characters: **truncate** to 4,096, append `[…]`, send.
4. If the agent response has no closing quote AND the payload is empty (just `"` with nothing after): silently drop the command.

**Why auto-close for agents but not users?** Agent responses may be streamed or cut off. Auto-closing is pragmatic recovery. Human users get clear errors so they can fix their syntax.

### 4.5 Payload Size Limit

**Hard cap: 4,096 characters.**

| Payload length | Action |
|---------------|--------|
| 0 (empty `""`) | Error — empty payload (user) / silently drop (agent) |
| 1 – 4,096 | Send normally |
| > 4,096 | Truncate to 4,096, append `[…]`, send |

**Rationale:** 4,096 characters ≈ 1,000–1,500 tokens. Sufficient for a detailed question or multi-paragraph context. Insufficient for dumping entire files — agents that need to share large content should write to a file and reference it in the A2A message. Prevents runaway streaming from creating enormous payloads.

### 4.6 Multiple Commands Per Response

An agent response may contain multiple commands:

```
`ask @QTR "first question"` `ask @Coder "second question"`
```

The parser locates each opening backtick, parses independently. Maximum **3 commands per response** (unchanged). Excess commands are silently dropped.

### 4.7 Escape Sequences

| Sequence | Resolves to |
|----------|-------------|
| `\"` | Literal `"` in payload |
| `\\` | Literal `\` in payload |

All other backslash sequences are treated as literal text (`\n` = backslash + n, not newline).

---

## 5. Parser Implementation

### 5.1 `_parse_quoted_payload(text: str, start: int) -> tuple[str | None, int]`

**New function in `command_handler.py`.** Replaces `_BODY_SEP` regex splitting.

```python
def _parse_quoted_payload(text: str, start: int) -> tuple[str | None, int]:
    """Parse a quoted payload starting at position `start`.

    Expects text[start] == '"'. Reads to matching '"' (respecting escapes).
    Returns (payload_string, position_after_close_quote) or (None, start) on failure.
    """
```

**Algorithm:**
1. If `text[start]` != `"`, return `(None, start)`.
2. Scan forward from `start + 1`.
3. On `\"`: append literal `"` to payload, advance 2.
4. On `\\`: append literal `\` to payload, advance 2.
5. On `"`: close — return `(payload, pos + 1)`.
6. On any other char: append to payload, advance 1.
7. On end of string without closing `"`: return `(None, start)` for user context, or `(payload, len(text))` for agent auto-close context (see §5.3).

### 5.2 `_extract_quoted_commands(text: str) -> list[ParsedCommand]`

**New function in `agent_command_handler.py`.** Replaces `_extract_backtick_commands()`.

```python
@dataclass
class ParsedCommand:
    command: str       # "ask", "tell", etc.
    agent: str         # "@QTR" (with @)
    payload: str       # extracted payload (unescaped)
    raw_start: int     # position of opening backtick in source text
    raw_end: int       # position after closing backtick

def _extract_quoted_commands(text: str) -> list[ParsedCommand]:
    """Extract backtick-delimited A2A commands with quoted payloads from text."""
```

**Algorithm:**
1. Strip fenced code blocks (```` ```...``` ````) — unchanged from current behavior.
2. Scan text for backtick characters.
3. On finding `` ` ``:
   a. Read the next token — is it a known command keyword? If not, skip to next backtick.
   b. Read `@Agent` token.
   c. Skip whitespace. Is the next char `"`?
      - **Yes**: parse quoted payload via the escape-aware scanner. Find closing `"`.
      - **No**: this is not a valid command — skip. (Do NOT attempt unquoted fallback.)
   d. Validate payload is non-empty and ≤ 4,096 chars.
   e. If valid, append to result list. If invalid, skip silently (agent context) or note for error (user context).
4. Return up to 3 parsed commands.

**Complexity:** O(n) single pass. No regex. No segment accumulation. The quote boundary makes the parser trivially correct.

### 5.3 `process_input()` Changes (command_handler.py)

Current flow:
```
text → strip prefix → _BODY_SEP split → extract body → parse @mentions → build Command
```

New flow:
```
text → strip prefix → tokenize → read command keyword → read @Agent → _parse_quoted_payload() → build Command
```

**Key changes:**
- **Remove** `_BODY_SEP` regex entirely.
- **Remove** the em-dash body extraction logic (`parts = _BODY_SEP.split(...)`).
- **Add** `_parse_quoted_payload()` call after `@Agent` resolution.
- For commands that require payloads (`ask`, `tell`, `delegate`, `task`): validate quote presence. Return error `CommandResult` if missing.
- For commands that don't use payloads (`stop`, `done`, `start`, etc.): skip quote parsing, use positional args as before.
- The `blocked` command optionally accepts a quoted payload for the reason. If no quote is found after the task ID, `body` is empty (allowed).

### 5.4 Canonicalization (agent_command_handler.py)

Current: reconstructs command with em-dash separator:
```python
candidate = f"`{cmd_token} {agent_token} — {body_text}"
```

New: reconstructs with quoted payload:
```python
# Escape any " in the payload before wrapping
escaped = body_text.replace('\\', '\\\\').replace('"', '\\"')
candidate = f"`{cmd_token} {agent_token} \"{escaped}`"
```

This ensures canonicalized commands always use the quoted format, even if the source command was parsed from a partially-formed agent response.

---

## 6. Prompt Templates

### 6.1 `prompts/system/collab.md` — Updated

Replace the current collab prompt with the new quoted-payload syntax. Key points for agents:

- Commands use quoted payloads: `` `ask @Agent "your question" ``
- The 4,096 character hard cap — payloads exceeding this are truncated
- All characters inside quotes are literal — no special meaning
- Use `\"` for literal quotes inside the payload
- Use `\\` for literal backslashes inside the payload
- `stop @Agent` does not need a payload
- Only one `@Agent` per command
- Maximum 3 commands per response

### 6.2 `prompts/system/project-awareness.md` — Updated

Include a brief note about the 4K hard cap so agents are aware when they first receive project context.

---

## 7. Test Matrix

### 7.1 `_parse_quoted_payload()` Tests

| # | Input | Expected payload | Expected result |
|---|-------|-----------------|-----------------|
| 1 | `"hello"` | `hello` | Success |
| 2 | `"hello world"` | `hello world` | Success |
| 3 | `""` | — | Error: empty payload |
| 4 | `"fix the — bug"` | `fix the — bug` | Success (em-dash preserved) |
| 5 | `"use a dict — not a list"` | `use a dict — not a list` | Success |
| 6 | `"nested \`backtick\` in quotes"` | `nested \`backtick\` in quotes` | Success (backticks preserved) |
| 7 | `"she said \"use a dict\""` | `she said "use a dict"` | Success (escaped quote) |
| 8 | `"path\\\\to\\\\file"` | `path\\to\\file` | Success (escaped backslash) |
| 9 | `"\\n not a newline"` | `\n not a newline` | Success (literal backslash+n) |
| 10 | (4,096 char payload) | Full payload | Success |
| 11 | (4,097 char payload) | First 4,096 + `[…]` | Truncated + sent |
| 12 | `"unclosed quote` | — | Error (user) / auto-close (agent) |

### 7.2 `_extract_quoted_commands()` Tests

| # | Input | Expected |
|---|-------|----------|
| 1 | `` `ask @QTR "hello"` | 1 command: ask, @QTR, "hello" |
| 2 | `` `ask @QTR "fix — the bug"` | 1 command: payload preserves em-dash |
| 3 | `` `ask @QTR "nested \`code\` ref"` | 1 command: payload preserves backticks |
| 4 | `` `ask @QTR "q1" \`ask @Coder "q2"` | 2 commands parsed independently |
| 5 | `` `ask @QTR unquoted` | 0 commands — no quotes |
| 6 | `` `ask @QTR""` | 0 commands — empty payload |
| 7 | `` `ask @QTR"no space"` | 0 commands — no space before quote |
| 8 | 4 commands in one response | 3 parsed, 4th silently dropped |
| 9 | `` `stop @QTR` | 1 command: stop (no payload needed) |
| 10 | Fenced block ```` ```\n`ask @QTR "hi"\n``` ```` | 0 commands — inside fenced block |
| 11 | `` `ask @QTR "she said \"hi\""` | 1 command: payload = `she said "hi"` |

### 7.3 `process_input()` Integration Tests

| # | Input (user) | Expected |
|---|-------------|----------|
| 1 | `` `ask @QTR "hello"` | forward_to=resolved_sk, forward_text="hello" |
| 2 | `` `ask @QTR hello` | error: "Malformed command — payload must be quoted" |
| 3 | `` `ask @QTR ""` | error: "Empty payload" |
| 4 | `` `ask @QTR"hello"` | error: "Malformed command — space required before quote" |
| 5 | `` `ask @QTR "unclosed` | error: "Unclosed quote" |
| 6 | `` `stop @QTR` | forward_to=resolved_sk, no payload |
| 7 | `` `task @Coder "implement auth"` | creates task with body "implement auth" |
| 8 | `` `blocked 00000042 "waiting on API"` | marks task blocked with reason |
| 9 | `` `done 00000042` | marks task done (no quotes needed) |
| 10 | `` `help` | shows command list |

---

## 8. Migration Plan

### 8.1 No Backward Compatibility

The unquoted format is **not supported**. This is intentional — the old format is the source of the bug class. A clean break forces consistent syntax from day one.

### 8.2 Migration Steps (Order Matters)

1. **Implement `_parse_quoted_payload()`** in `command_handler.py`
2. **Implement `_extract_quoted_commands()`** in `agent_command_handler.py`
3. **Update `process_input()`** to use new parser — remove `_BODY_SEP`, remove em-dash logic
4. **Update `on_agent_response()`** to use new extractor — remove `_extract_backtick_commands()`
5. **Update canonicalization** to use quoted format instead of em-dash
6. **Update `prompts/system/collab.md`** with new syntax + 4K cap note
7. **Update `prompts/system/project-awareness.md`** with 4K cap note
8. **Update tests** — `test_command_handler.py` and `test_agent_command_handler.py`
9. **Update `docs/ARCHITECTURE.md`** — §3.21e, remove `_BODY_SEP` references, add quoted payload format
10. **Run full test suite** — verify all pass

### 8.3 Risk Assessment

- **Low risk.** The collab prompt is loaded per-conversation. Agents pick up the new format immediately.
- **No persistent state** depends on the old format.
- **Special agents** (Coder, Debugger) get their system prompt from `prompts/system/collab.md` — same update path.
- **Gateway agents** receive `collab.md` as part of the awareness prefix — updated on first send after deployment.

---

## 9. Summary of What's Removed vs. Added

### Removed
- `_BODY_SEP` regex in `command_handler.py`
- Em-dash body splitting logic in `process_input()`
- `_extract_backtick_commands()` function in `agent_command_handler.py`
- Em-dash canonicalization in `on_agent_response()`
- All em-dash references in error messages and docs

### Added
- `_parse_quoted_payload()` function in `command_handler.py`
- `_extract_quoted_commands()` function in `agent_command_handler.py`
- `ParsedCommand` dataclass in `agent_command_handler.py`
- Quoted-payload canonicalization
- 4,096 character hard cap enforcement
- Escape sequence handling (`\"`, `\\`)
- Auto-close behavior for agent-sourced unclosed quotes

---

*Awaiting Captain approval before implementation begins.*
