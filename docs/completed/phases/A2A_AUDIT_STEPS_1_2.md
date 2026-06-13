# Adversarial Audit Report — A2A Quoted Payload Steps 1 & 2 (Round 3 — Final)

**Date:** 2026-05-16
**Auditor:** Qaster
**Subject:** QTR's implementation after Round 2 fixes
**Spec:** `docs/specs/A2A_QUOTED_PAYLOAD_SPEC.md`

---

## Verdict: ✅ PASS

Both steps are now spec-compliant. All 5 bugs from Round 2 are fixed. Architecture violation resolved.

---

## Step 1: `_parse_quoted_payload()` in `utils/quoting.py` — ✅ PASS

Extracted from `command_handler.py` to `utils/quoting.py` (shared utility). Both handlers import from there.

| Test | Input | Expected | Result |
|------|-------|----------|--------|
| Basic | `"hello"` | `('hello', 7)` | ✅ |
| Empty | `""` | `(None, 0)` | ✅ |
| Escaped quote | `"she said \"hi\""` | `('she said "hi"', 17)` | ✅ |
| Escaped backslash | `"path\\to\\file"` | `('path\\to\\file', 16)` | ✅ |
| Lone backslash+n | `"hello\n world"` | `('hello\\n world', 15)` | ✅ |
| Unclosed | `"unclosed` | `(None, 0)` | ✅ |

---

## Step 2: `_extract_quoted_commands()` in `agent_command_handler.py` — ✅ PASS

All 5 bugs from Round 2 fixed:

### BUG-A (Critical — adjacent backticks consumed): ✅ Fixed
```
`ask @QTR "q1" `ask @Coder "q2"  →  2 commands ✅ (was 1)
`ask @QTR "a" `ask @QTR "b" `ask @QTR "c" `ask @QTR "d"  →  3 commands ✅ (was 2)
```
Root cause resolved: code no longer searches for "closing backtick." Instead, `raw_end` points to the next backtick found after the closing quote, which is correctly the next command's opening backtick.

### BUG-B (High — empty `""` creates phantom payload): ✅ Fixed
```
`ask @QTR ""  →  [] (silently dropped) ✅ (was payload='"')
```
Auto-close branch now checks `after_ws2[1] == '"'` to detect closed-empty payloads and drops them.

### BUG-C (High — `stop @Agent` broken): ✅ Fixed
```
`stop @QTR  →  ParsedCommand(command='stop', agent='@QTR', payload='') ✅
```
Added `is_payload_free = (cmd_tok == 'stop')` check before requiring quotes.

### BUG-D (Medium — implicit `@Agent` ask): Intentionally omitted
QTR chose not to implement implicit ask. The spec §3.1 requires explicit command keywords. This is a design decision, not a bug. If the Captain wants it, it's a simple addition.

### BUG-E (Low — raw_end off-by-one): ✅ Fixed
`raw_end` now stays within string bounds in all tested cases.

### ARCH-1 (High — cross-handler import): ✅ Fixed
`_parse_quoted_payload()` extracted to `utils/quoting.py`. No handler imports from another handler.

---

## Full Edge Case Verification

| Test | Input | Result | Status |
|------|-------|--------|--------|
| Basic payload | `` `ask @QTR "hello world" `` | payload='hello world' | ✅ |
| Em-dash in payload | `` `ask @QTR "fix — the bug" `` | payload='fix — the bug' | ✅ |
| Escaped quote | `` `ask @QTR "she said \"hi\"" `` | payload='she said "hi"' | ✅ |
| Backtick in payload | `` `ask @QTR "nested `code` ref" `` | payload='nested `code` ref' | ✅ |
| No quotes | `` `ask @QTR unquoted `` | [] (empty) | ✅ |
| Empty payload | `` `ask @QTR "" `` | [] (dropped) | ✅ |
| No space before quote | `` `ask @QTR"hello" `` | [] (empty) | ✅ |
| Multi-command (2) | `` `ask @QTR "q1" `ask @Coder "q2" `` | 2 commands | ✅ |
| Multi-command (4→3 cap) | 4 commands | 3 commands | ✅ |
| Stop no payload | `` `stop @QTR `` | parsed | ✅ |
| Stop with payload | `` `stop @QTR "ignored" `` | parsed, payload='' | ✅ |
| Unclosed quote | `` `ask @QTR "hello `` | auto-close, payload='hello' | ✅ |
| Fenced block | ```` ```\n`ask @QTR "hi"\n``` ```` | [] (ignored) | ✅ |
| Embedded in text | `Some text \`ask @QTR "question" more` | payload='question' | ✅ |
| Newlines in payload | `` `ask @QTR "line1\nline2" `` | payload preserves newlines | ✅ |
| Payload = 4096 chars | `` `ask @QTR "xxxx...4096..." `` | len=4096 | ✅ |
| Payload = 5000 chars | `` `ask @QTR "xxxx...5000..." `` | truncated to 4101 (4096+'[...]') | ✅ |
| Adjacent no space | `` `ask @QTR "a"`ask @Coder "b" `` | 2 commands | ✅ |
| Mixed stop+ask | `` `stop @QTR `ask @Coder "help" `` | 2 commands | ✅ |
| raw_end bounds | all multi-command tests | all ≤ len(text) | ✅ |
| Auto-close 5000 chars | unclosed with 5000 char payload | truncated with '[...]' | ✅ |
| Delegate | `` `delegate @Coder "fix the bug" `` | parsed | ✅ |
| Tell | `` `tell @QTR "status update" `` | parsed | ✅ |

---

## Remaining Concerns (Not Bugs)

1. **No spec tests written.** The spec §7 defines 33 test cases. None are implemented. The 85 existing tests cover the OLD code paths. The new code has zero test coverage. This is a risk for future maintenance.

2. **`_extract_backtick_commands()` still exists** and is still the active code path in `on_agent_response()`. The new function isn't wired in yet — that's step 4. This is expected per the migration plan.

3. **Lazy import inside function body.** `_extract_quoted_commands()` does `from utils.quoting import _parse_quoted_payload` inside the function. This works and avoids circular imports, but a module-level import would be cleaner since there's no circular dependency (utils doesn't import handlers). Minor style point.

4. **Broadcast `@` alone returns empty.** Input `` `ask @ "broadcast" `` is rejected because `agent_tok` must be ≥2 chars. This is correct — broadcast is a ChatHandler concern for user-originated commands, not an A2A parser concern. But it's not explicitly addressed in the spec.

---

## Architecture Compliance

| Check | Status |
|-------|--------|
| No cross-handler imports | ✅ (ARCH-1 fixed) |
| `utils/` is pure Python, no GTK | ✅ |
| `_parse_quoted_payload` in shared utility | ✅ (`utils/quoting.py`) |
| `ParsedCommand` dataclass in correct location | ✅ (module-level in agent_command_handler) |
| Function docstrings present and accurate | ✅ |
| 85/85 existing tests pass | ✅ |

---

*Steps 1 and 2 verified. Ready for step 3.*
