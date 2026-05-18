# Adversarial Audit Report — Step 3: process_input() Rewrite

**Date:** 2026-05-16
**Auditor:** Qaster
**Subject:** QTR's implementation of spec step 3 — wiring `_parse_quoted_payload()` into `process_input()`
**Spec:** `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md`

---

## Summary

Step 3 replaces the old em-dash body extraction in `process_input()` with quoted-payload parsing. The core logic is structurally sound — the new flow correctly parses `@mention` → quoted payload, and the old em-dash code is removed from the active code path.

However, there are **3 functional bugs**, **1 dead code violation**, **3 test quality issues**, and **1 spec compliance gap**. All are fixable. The bugs are in error-path edge cases, not in the happy path.

---

## Functional Bugs

### BUG-F: Empty payload `""` gives wrong error message (Medium)

**Severity:** Medium — wrong error message confuses users
**Spec ref:** §4.2 — `Empty payload — provide a message: \`ask @Agent "your message"\``
**File:** `ui/handlers/command_handler.py`, ~line 258

```python
if not after_ws[1:]:  # nothing after opening quote
    error_msg = 'Empty payload...'
else:
    error_msg = 'Unclosed quote...'
```

When `_parse_quoted_payload` returns `(None, 0)` for `""`, the code checks `after_ws[1:]`. For input `""`, `after_ws` is `'""'` and `after_ws[1:]` is `'"'` — which is truthy. So it falls through to "Unclosed quote" instead of "Empty payload".

**Reproduction:**
```
Input:  `ask @Debugger ""
Got:    'Unclosed quote — missing closing ": ...'
Expect: 'Empty payload — provide a message: ...'
```

**Fix:** Check if the closing quote is immediately after the opening quote:
```python
if payload is None:
    if len(after_ws) >= 2 and after_ws[1] == '"':
        error_msg = 'Empty payload...'    # "" — opened and closed with nothing inside
    else:
        error_msg = 'Unclosed quote...'   # "... — genuinely unclosed
```

---

### BUG-G: `stop @Agent` requires quotes — payload-free commands broken (High)

**Severity:** High — `stop` command completely broken for user input
**Spec ref:** §3.2 — `stop @Agent` is payload-free
**File:** `ui/handlers/command_handler.py`, ~line 252

The new `process_input()` requires a quoted payload for ALL commands that have mentions. When `stop @Debugger` is entered:
1. `@Debugger` is resolved → `target_sk` set
2. `args_after_mentions` = `[]` (empty — no tokens left after @mention)
3. `rest_text` = `""` (empty string)
4. `after_ws` = `""` (empty)
5. `not after_ws or after_ws[0] != '"'` → `True`
6. Error: "Malformed command — payload must be quoted"

Per spec §3.2, `stop` is payload-free. The code needs to distinguish payload-requiring commands from payload-free ones.

**Reproduction:**
```
Input:  `stop @Debugger
Got:    'Malformed command — payload must be quoted: ...'
Expect: handled=True, forward_to="agent:debugger:1"
```

**Fix:** After `@mention` resolution, check if the command is payload-free before requiring quotes. Define a set:
```python
_PAYLOAD_FREE_COMMANDS = frozenset({'stop'})
```
Then in the validation:
```python
if cmd_name not in _PAYLOAD_FREE_COMMANDS:
    if not after_ws or after_ws[0] != '"':
        error_msg = 'Malformed command...'
```

Alternatively, skip payload validation when `args_after_mentions` is empty AND the command is registered — let the command handler decide. But explicit is better than implicit here.

---

### BUG-H: No space before quote gives wrong error message (Low)

**Severity:** Low — confusing error message, but the command is correctly rejected
**Spec ref:** §4.2 — `Malformed command — space required before quote`
**File:** `ui/handlers/command_handler.py`, mention parsing

```
Input:  `ask @Debugger"hello"
Got:    'Unknown agent: @Debugger"hello"'
Expect: 'Malformed command — space required before quote: ...'
```

The `@mention` parser reads `@Debugger"hello"` as a single token (stops at whitespace, not at quotes). This then fails agent resolution with "Unknown agent" instead of the more helpful "space required" message.

**Assessment:** The command IS correctly rejected — it just gives a less helpful error. This is a UX issue, not a spec violation. The `_parse_mentions` tokenizer doesn't know about quotes. Fixing this would require adding quote-awareness to the mention tokenizer, which is a more invasive change. Low priority.

---

## Dead Code

### DEAD-1: `_BODY_SEP` regex still defined (Must Remove)

**File:** `ui/handlers/command_handler.py`, lines 35–36

```python
_BODY_SEP = re.compile(r'\s+[—–]\s+')   # em-dash/en-dash with spaces — body separator (NOT regular hyphen)
# NOTE: _BODY_SEP is DEPRECATED — will be replaced by _parse_quoted_payload() in step 3
```

Step 3 IS the step that replaces it. The comment says "will be replaced in step 3" — we're IN step 3. `_BODY_SEP` is never referenced anywhere in the codebase. This is dead code that must be removed.

Also: the `import re` at the top of the file — check if it's still needed after removing `_BODY_SEP`.

---

## Test Quality Issues

### TEST-1: Duplicate line in test_body_extracted (Must Fix)

**File:** `tests/test_command_handler.py`, line 175

```python
result = configured_handler.process_input("agent:1", "`bodytest @Debugger \"actual body text\"")
result = configured_handler.process_input("agent:1", "`bodytest @Debugger \"actual body text\"")
```

The same call is made twice — the first result is overwritten. This is a copy-paste artifact. Remove the duplicate.

### TEST-2: Weakened assertion in test_multiple_partial_matches_returns_error (Must Fix)

**File:** `tests/test_command_handler.py`, line 224

The old test asserted:
```python
assert "Multiple agents" in result.response_text
```

This assertion was **removed**. The test now only asserts `result.handled is True` — it no longer verifies that the correct error message is returned. The test name says "returns_error" but it doesn't check the error content. This weakens the test to the point where it could pass with any handled=True result.

**Fix:** Re-add the assertion:
```python
assert "Multiple agents match @deb" in result.response_text
```
Note: the message format may have changed. Verify the actual error message from `_resolve_mention` and assert on that.

### TEST-3: Weakened assertion in test_handler_exception_returns_error_response (Must Fix)

**File:** `tests/test_command_handler.py`, line 239

The old test asserted:
```python
assert "Error" in result.response_text
assert "boom" in result.response_text
```

The `"boom"` assertion was **removed**. The test now only checks for "Error" in the response. This means the test would pass even if the error handling swallowed the exception message entirely.

**Fix:** Re-add:
```python
assert "boom" in result.response_text
```

### TEST-4: Unused `Q = chr(34)` variables (Cleanup)

**File:** `tests/test_command_handler.py`, multiple locations

The diff added `Q = chr(34)` on several lines but never uses the `Q` variable. These are dead assignments. Remove them or use them to construct test strings.

---

## Spec Compliance

### SPEC-1: Payload-free commands not handled in process_input() (High)

This is the same issue as BUG-G but viewed from the spec angle. The spec §3.2 explicitly lists `stop @Agent` as payload-free. The spec §3.5 shows `stop` with "None (ignored if present)" as the payload column. The implementation must support this.

Additionally, the spec §3.2 lists several commands that don't need `@Agent` at all: `tasks`, `review`, `check`, `accept`, `reject`, `status`, `agents`, `cost`, `help`. The current code may handle these correctly (no @mention → no payload check), but this should be verified for each command.

---

## What's Correct

The happy path works well:

| Test | Input | Result | Status |
|------|-------|--------|--------|
| Basic ask | `` `ask @Debugger "hello" `` | forward_text="hello" | ✅ |
| Escaped quote | `` `ask @Debugger "she said \"hi\"" `` | forward_text='she said "hi"' | ✅ |
| Backtick in payload | `` `ask @Debugger "nested `code` ref" `` | forward_text="nested `code` ref" | ✅ |
| Em-dash in payload | `` `ask @Debugger "fix — the bug" `` | forward_text="fix — the bug" | ✅ |
| Unquoted payload | `` `ask @Debugger hello `` | error: "Malformed" | ✅ |
| Unclosed quote | `` `ask @Debugger "unclosed `` | error: "Unclosed" | ✅ |
| Unknown agent | `` `ask @Nobody "hello" `` | error: "Unknown agent" | ✅ |
| Implicit @ ask | `` `@Debugger "hello" `` | forward_to=agent:debugger:1 | ✅ |
| Case-insensitive | `` `ask @debugger "hello" `` | forward_to=agent:debugger:1 | ✅ |
| Multiple mentions | `` `ask @Debugger @Coder "hi" `` | error: "Only one" | ✅ |
| Help (no @Agent) | `` `help `` | shows commands | ✅ |
| Done (positional) | `` `done 00000042 `` | handled | ✅ |
| 4096 char payload | 4096 chars | accepted | ✅ |
| Plain text | `just some text` | passthrough | ✅ |

---

## Architecture Compliance

| Check | Status |
|-------|--------|
| No cross-handler imports | ✅ |
| `_parse_quoted_payload` from `utils/quoting` | ✅ |
| Models are pure data (Command, CommandResult) | ✅ |
| Old em-dash logic removed from active path | ✅ |
| `_BODY_SEP` removed from active path | ✅ |
| `_BODY_SEP` still defined (dead code) | ❌ DEAD-1 |
| 85/85 tests pass | ✅ |

---

## Recommendations

**Must fix before proceeding to step 4:**

1. **BUG-G** — Add payload-free command handling for `stop`. This is a broken command.
2. **BUG-F** — Fix empty payload error message. One-line fix.
3. **DEAD-1** — Remove `_BODY_SEP` definition and comment. Check if `import re` is still needed.
4. **TEST-1** — Remove duplicate line.
5. **TEST-2** — Re-add "Multiple agents" assertion.
6. **TEST-3** — Re-add "boom" assertion.
7. **TEST-4** — Remove unused `Q = chr(34)` assignments.

**Can defer:**

8. **BUG-H** — Wrong error for no-space-before-quote. Low priority UX fix.

---

*End of Step 3 audit.*
