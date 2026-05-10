# Proposal: System Prompt Library

> **Status: IMPLEMENTED** — Verified in code as of 2026-05-09
> - `prompts/system/` directory exists with 9 templates
> - `utils/prompt_loader.py` loads and composes templates with `compose_system_prompt()`
> - `CRABCAKES_PROMPT_DEBUG` env var for inspection
> - Note: The identity override bug (BUG_REPORT-identity-override.md) relates to HOW this is used for gateway agents

**Date:** 2026-04-25  
**Author:** Qaster  
**Status:** Implemented

---

## Problem

Project awareness is assembled programmatically in Python (`build_awareness_block()` in `utils/project_awareness.py`). The agent receives raw data — manifest, team roster, git state — but receives **no instructions** on how to use it. Agents don't know they can write to `context.md`, how to address team members, or what's expected in a project context.

Additionally, there is no centralized system for managing system prompts across the two execution paths:

| Path | Mechanism | System Prompt |
|------|-----------|---------------|
| **Agent Runtime** (Coder/Debugger) | `agent/context.py` → `build_system_prompt()` | Hardcoded Python templates (`_CODER_SYSTEM_PROMPT`, `_DEBUGGER_SYSTEM_PROMPT`) — to be removed |
| **Gateway Agents** (Qaster, QTR) | `chat_handler.py` → `_build_awareness_prefix()` | No system prompt — just raw awareness data prefixed to first message |

The only existing pattern for editable prompts is `improve-system-prompt.md` (loaded by `utils/improve.py`) and custom project prompts (`.crabcakes/agent-system-prompt.md` or `AGENTS.md`, loaded by `agent/context.py`).

**What's missing:**
1. Agents don't know how to use the awareness data they receive
2. System prompts are hardcoded in Python — editing requires code changes + restart
3. No composable prompt assembly — can't mix project context + collaboration rules + review mode
4. Gateway agents get no behavioral instructions at all (just raw data)
5. No way for users to customize agent behavior without editing Python

---

## Proposed Solution

A `prompts/system/` directory containing markdown template files. A new utility (`utils/prompt_loader.py`) loads, templates, and composes them. Both injection paths (agent runtime and gateway) consume the composed prompt.

### Architecture

```
prompts/
├── system/                         # NEW — system prompt templates
│   ├── default.md                  # Base agent behavior (always loaded)
│   ├── project-awareness.md        # How to use project data (when project active)
│   ├── project-collaboration.md    # Multi-agent etiquette (when team > 1)
│   ├── code-review.md              # Review mode behavior (when review = on)
│   ├── coder.md                    # Coder-specific instructions
│   ├── debugger.md                 # Debugger-specific instructions
│   └── improve.md                   # MOVED from prompts/improve-system-prompt.md
├── checkpointArchitectureFirst.md  # EXISTING — checkpoint code writer
└── ... (50+ existing prompt files)
```

**New file:** `utils/prompt_loader.py`

```
utils/
├── ...
├── prompt_loader.py    # NEW — load, template-fill, compose system prompts
└── ...
```

**No new packages.** `prompt_loader.py` is pure Python — no GTK, no network. Lives in `utils/` per architecture rules.

---

### Prompt Template Format

Templates use `{{VARIABLE}}` markers — same pattern as `improve-system-prompt.md` already uses `{{USER_INPUT}}`.

**Example: `prompts/system/project-awareness.md`**

```markdown
You are working on the project **{{PROJECT_NAME}}** located at `{{PROJECT_PATH}}`.

## Team
{{TEAM_ROSTER}}

## Project Memory
You can read and write to `.crabcakes/context.md` to persist notes across sessions.
- Read it at the start of a session to catch up on what happened before
- Append dated entries when you learn something worth remembering
- Keep entries concise — this is a shared notepad, not a log file

## Current State
{{CURRENT_STATE}}
```

**Example: `prompts/system/default.md`**

```markdown
You are {{AGENT_NAME}}, a member of the project team.

## Response Guidelines
- Be concise and technical
- Reference files and components by their actual names from the codebase
- When in doubt, ask for clarification
```

---

### New Utility: `utils/prompt_loader.py`

**Responsibility:** Load prompt template files, fill variables, compose multi-prompt sequences.

**Public API:**

```python
def load_prompt_template(name: str) -> str | None:
    """Load a prompt template from prompts/system/<name>.md.
    Returns raw template string with {{VARIABLES}} intact, or None if not found."""

def fill_template(template: str, variables: dict[str, str]) -> str:
    """Replace {{KEY}} with values from variables dict. 
    Unresolved variables are left as-is."""

def compose_system_prompt(
    agent_name: str,
    project_path: str | None = None,
    project_awareness: dict | None = None,   # from build_awareness_block() as dict
    team_size: int = 1,
    review_mode: str = "off",
) -> str:
    """Compose the full system prompt by loading and merging templates.
    
    Selection logic:
    1. Always: default.md
    2. If project active: project-awareness.md (filled with awareness variables)
    3. If team_size > 1: project-collaboration.md
    4. If review_mode != "off": code-review.md
    5. If agent_name contains "coder": coder.md
    6. If agent_name contains "debugger": debugger.md
    
    Templates are concatenated with blank-line separators.
    Missing templates are silently skipped.
    """
```

**Thread safety:** Pure functions, no mutable state. Safe to call from any thread.

---

### Changes to Existing Code

#### 1. `utils/project_awareness.py` — Add `build_awareness_dict()`

Currently `build_awareness_block()` returns a formatted string. Add a companion that returns raw data as a dict, so `prompt_loader` can use it as template variables.

```python
def build_awareness_dict(project_path: str) -> dict[str, str]:
    """Return awareness data as a dict of template variables.
    
    Keys: PROJECT_NAME, PROJECT_PATH, TEAM_ROSTER, CURRENT_STATE, PROJECT_MEMORY
    """
```

`build_awareness_block()` remains unchanged for backward compatibility. The dict version is a parallel API.

#### 2. `agent/context.py` — Use `prompt_loader` in `build_system_prompt()`

Replace the hardcoded templates and custom prompt check with:

```python
# Delete: load_custom_system_prompt() function entirely
# Delete: custom prompt check (lines 403-405)
# Delete: _CODER_SYSTEM_PROMPT and _DEBUGGER_SYSTEM_PROMPT constants

# Replace template selection with:
awareness_dict = build_awareness_dict(project_path) if project_path else {}
return compose_system_prompt(
    agent_name=agent_name,
    project_path=project_path,
    project_awareness=awareness_dict,
    review_mode=review_mode,
)
```

#### 3. `ui/handlers/chat_handler.py` — Use `prompt_loader` in `_build_awareness_prefix()`

Replace the raw data prefix with a composed system prompt:

```python
# Before:
block = build_awareness_block(project_path)
return f"[Project Context]\n{block}\n\n[User Message]\n"

# After:
awareness_dict = build_awareness_dict(project_path)
prompt = compose_system_prompt(
    agent_name="",
    project_path=project_path,
    project_awareness=awareness_dict,
)
return f"[System Instructions]\n{prompt}\n\n[User Message]\n"
```

This gives gateway agents actual behavioral instructions, not just raw data.

---

### What Does NOT Change

| Component | Reason |
|-----------|--------|
| `build_awareness_block()` | Unchanged — backward compatible |
| `build_awareness_snapshot()` | Unchanged — still produces awareness.json |
| Existing 50+ prompts in `prompts/` | Unchanged — user-facing prompts, not system prompts |

### Removed Code

The old custom prompt system has zero adoption and is replaced entirely by the template library.

| What | File | Action |
|------|------|--------|
| `load_custom_system_prompt()` | `agent/context.py` lines 143-168 | Delete |
| Custom prompt check in `build_system_prompt()` | `agent/context.py` lines 403-405 | Delete |
| 6 test cases for `load_custom_system_prompt` | `tests/test_context.py` | Delete |
| Hardcoded `_CODER_SYSTEM_PROMPT` / `_DEBUGGER_SYSTEM_PROMPT` | `agent/context.py` lines 23-80 | Delete |
| `improve-system-prompt.md` | Move to `prompts/system/improve.md` | Move |
| Improve prompt path reference | `utils/improve.py` line 89 | Update path to `prompts/system/improve.md` |

**Justification:** `.crabcakes/agent-system-prompt.md` exists in zero projects. `AGENTS.md` exists only in `openclaw-src` (an OpenClaw convention, not a CrabCakes prompt). No active usage. Clean removal.

---

### Template Variable Reference

Variables available to all system prompt templates:

| Variable | Source | Example |
|----------|--------|---------|
| `{{AGENT_NAME}}` | Agent display name | `"Qaster"` |
| `{{PROJECT_NAME}}` | `.crabcakes/project.md` | `"CrabCakes"` |
| `{{PROJECT_PATH}}` | Project directory | `"/home/q/projects/crabcakes"` |
| `{{TEAM_ROSTER}}` | `.crabcakes/team.json` | Formatted member list |
| `{{CURRENT_STATE}}` | `.crabcakes/awareness.json` | Git SHA, tasks, review mode |
| `{{PROJECT_MEMORY}}` | `.crabcakes/context.md` | Cross-session notes (may be empty) |
| `{{REVIEW_MODE}}` | Project settings | `"off"` / `"review"` |
| `{{TOOL_LIST}}` | Agent runtime tools | Formatted tool list |

---

### Architecture Alignment

| Rule | Compliance |
|------|-----------|
| `utils/` = pure Python, no GTK/network | ✅ `prompt_loader.py` is pure file I/O |
| `models/` = pure data | ✅ No changes to models |
| Section 8.6: handlers don't import other handlers | ✅ `chat_handler` imports from `utils/`, not other handlers |
| Section 8.6: window wires callbacks | ✅ No new wiring needed — consumption is internal to handlers |
| Existing patterns: `improve-system-prompt.md` uses `{{USER_INPUT}}` | ✅ Same template pattern extended |
| Existing patterns: `.crabcakes/agent-system-prompt.md` overrides | ✅ Override hierarchy preserved |
| No new dependencies | ✅ Uses only stdlib (`os`, `string.Template` or simple replace) |

---

### Implementation Order

| Phase | What | Effort |
|-------|------|--------|
| 1 | Create `utils/prompt_loader.py` with `load_prompt_template()`, `fill_template()`, `compose_system_prompt()` | Small |
| 2 | Add `build_awareness_dict()` to `utils/project_awareness.py` | Small |
| 3 | Create `prompts/system/` with `default.md`, `project-awareness.md` | Small |
| 4 | Move `improve-system-prompt.md` → `prompts/system/improve.md`, update path in `utils/improve.py` line 89 | Small |
| 5 | Wire `agent/context.py` to use `compose_system_prompt()`, delete old system | Small |
| 6 | Wire `chat_handler.py` to use `compose_system_prompt()` | Small |
| 7 | Add remaining templates (`project-collaboration.md`, `code-review.md`, `coder.md`, `debugger.md`) | Medium |
| 8 | Update `ARCHITECTURE.md` Section 3 and Section 11 | Small |
| 9 | Tests in `tests/test_prompt_loader.py`, update `tests/test_context.py` | Medium |

---

### Risks

| Risk | Mitigation |
|------|-----------|
| Template variables not filled → raw `{{VAR}}` in prompt | `fill_template()` logs unresolved variables at WARNING level |
| Missing template file → empty system prompt | Fallback to current hardcoded templates if `prompts/system/` doesn't exist |
| Custom `.crabcakes/agent-system-prompt.md` conflicts | Removed — old system deleted |
| Prompt too long → token waste | Each template has a recommended max length; composer logs total size |
| Two awareness APIs (`_block` vs `_dict`) drift | Single internal function, both are thin wrappers |

---

### Open Questions

1. Should `prompts/system/` be editable from the Prompts tab UI, or remain a developer-only concern?
2. Should gateway agents receive the full composed prompt on every message, or only on first message (current behavior)?
3. Should the `default.md` template contain the agent's identity/personality, or just behavioral rules?
4. Should templates support conditional blocks (e.g., `{{#if project_path}}...{{/if}}`), or is selection logic in `compose_system_prompt()` sufficient?
