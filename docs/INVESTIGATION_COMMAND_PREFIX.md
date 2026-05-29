# Investigation: Changing Command Prefix from Backtick

**Date:** 2026-05-28
**Author:** Qaster
**Honest opinion requested**

---

## The Problem

Backtick (`) is used as the command prefix in CrabCakes. Type `` `help `` to see commands, `` `ask @Coder "fix this" `` to send A2A commands, etc. The problem: backtick is also the markdown inline code delimiter and the fenced code block delimiter (``` ```). This creates conflicts:

1. **AI agents use backticks constantly.** Every code snippet, every `variable_name` reference, every fenced code block uses backticks. When agents return text with inline code, the A2A scanner has to carefully skip fenced blocks.
2. **The A2A regex `r'\`([^\`]+)\`'` scans all text for backtick-wrapped tokens** — it has to distinguish between `` `code references` `` and `` `ask @Agent "message"` `` commands.
3. **Help text is awkward.** Every help string wraps commands in backticks for formatting: `` `help <command>` `` — but those backticks are also the command prefix.

---

## Current State (The Numbers)

| Metric | Count |
|--------|-------|
| Total backtick occurrences across Python files | **249** |
| Files containing backticks | **~29 files** |
| Command prefix config (`COMMAND_PREFIX`) | **1 line** (`utils/config.py:71`) |
| `set_prefix()` method (already exists!) | **1 method** in `command_handler.py` |
| A2A backtick scanner regex | **1 regex** in `agent_command_handler.py` |
| Markdown/fence parsing (unrelated to commands) | **93 occurrences** (stays the same) |
| Test assertions using backtick command input | **~80+ assertions** |
| UI help strings with backtick formatting | **~17 occurrences** |

---

## What Would Actually Need to Change

### Tier 1: Core (must change)
1. **`utils/config.py` line 71** — `COMMAND_PREFIX = "\`"` → change one character
2. **`ui/handlers/agent_command_handler.py` line 69** — A2A scanner regex `r'\`([^\`]+)\`'` → update to new character
3. **`ui/handlers/command_handler.py`** — help strings that format commands with backticks (lines 106-115)
4. **`ui/handlers/task_handler.py`** — all usage/help strings (~17 occurrences)

### Tier 2: Tests (must update to match)
5. **`tests/test_command_handler.py`** — ~34 assertions with `` `command `` inputs
6. **`tests/test_agent_command_handler.py`** — ~46 assertions
7. **`tests/test_crabcard_parser.py`** — 28 occurrences (mostly fenced block tests — probably don't change)
8. Other test files — ~20 more

### Tier 3: Display formatting (optional but recommended)
9. Help text, error messages, and UI strings that show command syntax

### What Does NOT Change
- **Markdown parsing** (`utils/markdown.py`) — backticks for inline code stay as-is. That's markdown spec, not our command system.
- **Fenced code blocks** (`utils/block_parser.py`) — triple backticks stay. That's markdown.
- **Syntax highlighting** — unrelated.
- **Any file content or code rendering** — unchanged.

---

## Candidate Replacements

| Character | Pros | Cons |
|-----------|------|------|
| `/` | Familiar (IRC, Discord, Slack) | Conflicts with file paths in messages. Agents mention `/home/q/...` constantly. |
| `@` | Familiar (Twitter, mentions) | Already used for `@Agent` targets. Double duty is confusing. |
| `!` | Familiar (IRC, Discord bots) | Agents use `!` in natural language ("don't do this!") and some code. Low conflict though. |
| `#` | Familiar (channels, headings) | Conflicts with markdown headings. Already used for `# heading`. |
| `.` | Clean, minimal | Rare in natural text start. But `.` is easy to miss visually. |
| `>` | Shell-like | Conflicts with blockquote in markdown. Agents use `>` for quotes. |
| `$` | Shell-like | Already used for terminal block detection. And agents show `$ command` output. |
| `~` | Rare at start of messages | Tilde is uncommon enough to avoid conflicts. Slightly weird UX. |
| `//` | Code comment style | Two characters. Already means "comment" in many languages. Agents use it. |
| `\|` | Not used as command prefix anywhere | Conflicts with markdown tables (our new table feature!). Bad timing. |

---

## My Honest Recommendation

**Change it to `/` (slash).**

Here's why, and I'll be straight with you about the tradeoffs:

### Why `/`

1. **Everyone already knows it.** Every chat app on earth uses `/` for commands. Discord, Slack, IRC, Telegram, Matrix, Teams. Zero learning curve.
2. **It's the expected convention.** When someone sees `/help` in a chat app, they know what it means. When they see `` `help `` they have to learn it.
3. **File path conflicts are manageable.** Yes, agents mention `/home/q/projects/...` in messages. But `process_input()` only checks `text.startswith(self._prefix)` — and file paths rarely start a *user's chat message*. Users don't type `/home/q/...` as a command. The conflict is theoretical, not practical.
4. **The prefix is already configurable.** `set_prefix()` exists. `COMMAND_PREFIX` is a single config line. The plumbing is done.
5. **Agent-generated text is irrelevant.** Commands are only parsed from *user input*, not from agent responses. So even if an agent says `/help` in a message, it's not scanned as a command — it's just text.

### Why NOT `/`

1. File paths starting with `/` in user messages would trigger command parsing. Mitigation: check if the first token after `/` is a registered command name. If not, pass through. This is already how it works — unknown commands return `handled=False`.
2. Users on Linux might reflexively avoid typing `/` at the start of a message. But this is actually the behavior we *want* — it makes commands deliberate.

### The alternatives I rejected

- **`!`** — tempting, but agents use exclamation marks in natural text constantly. "Great job!" or "Don't do that!" starting a message would be a worse conflict than backtick.
- **`@`** — already taken for agent mentions.
- **`~`** — too obscure, weird UX.
- **`$`** — conflicts with terminal blocks.

---

## Effort Estimate

| Task | Lines | Time |
|------|-------|------|
| Change `COMMAND_PREFIX` | 1 | 1 min |
| Update A2A scanner regex | 1 | 2 min |
| Update help strings (command_handler) | ~8 | 5 min |
| Update help strings (task_handler) | ~17 | 10 min |
| Update help strings (other handlers) | ~8 | 5 min |
| Update test assertions | ~80 | 30 min |
| Test and verify | — | 15 min |
| **Total** | **~115 lines** | **~1 hour** |

---

## Bottom Line

The backtick-as-prefix was a reasonable choice when CrabCakes started — it's compact and distinctive. But now that the app has a real command system with A2A, tasks, reviews, and more, the collision with markdown's primary delimiter is a real problem that will only get worse.

Slash is the right answer. It's the universal chat command prefix. The change is mechanical — find-and-replace in test files, update ~5 strings in handlers, change one config value. The architecture already supports it via `set_prefix()`.

**Do it. The longer we wait, the more tests we write with backticks, and the harder it gets.**
