# SPEC-5: Gateway Agent Platform Context

**Date:** 2026-05-25
**Author:** QTR
**Status:** Draft — for implementation
**Repository:** github.com/qsmtco/crabcakes
**Implements:** `docs/proposals/PLATFORM-CONTEXT-AGENTS.md` (platform context proposal)
**Target branch:** main

> **⚠️ Architecture Compliance:**
> This spec adheres strictly to ARCHITECTURE.md. Read ARCHITECTURE.md section 0 — "this document is the law." All code follows documented patterns, layers, and naming conventions. Deviation requires spec revision.

---

## 1. Overview

### 1.1 Purpose

Gateway agents (Qaster, QTR, etc.) operating in CrabCakes project tabs receive project awareness context but have no knowledge of the CrabCakes platform itself. They don't know about custom rendering formats, backtick commands, the review layer, or that they're operating inside a rich chat UI with activity indicators and feed cards.

Special agents (Coder, Debugger, Test Engineer) receive this via the template pipeline in `compose_system_prompt()`. Gateway agents — who go through `_build_awareness_prefix()` in `ChatHandler` instead — do not.

### 1.2 Scope

| Change | Type | File |
|--------|------|------|
| New template | New file | `prompts/system/crabcakes-context.md` |
| Gateway agent injection | Code | `ui/handlers/chat_handler.py` |
| Special agent injection | Code | `utils/prompt_loader.py` |

### 1.3 What This Does NOT Do

- Does not change how project context is injected
- Does not touch the routing table, activity handler, or render pipeline
- Does not add per-project `AGENTS.md` loading
- Does not change `build_awareness_block()` or `_build_awareness_prefix()` structure beyond appending one template

---

## 2. Architecture

### 2.1 Background

**Existing `compose_system_prompt()` flow (special agents):**
```
1. default.md
1b. collab.md          ← collaboration protocol injected here
2. project-awareness.md (if project active)
3. crabcakes-commands.md (if project active)
4. project-onboarding.md (if not onboarded)
5. code-review.md (if review mode on)
6. coder.md / debugger.md (by role)
7. {role}-bugs.md / {role}-rules.md (self-improvement)
```

**Existing `_build_awareness_prefix()` flow (gateway agents):**
```
1. build_awareness_block() — project context
2. collab.md              ← collaboration protocol injected here
→ returns combined string
```

Both flows inject `collab.md`. The gap: `compose_system_prompt()` also injects `crabcakes-commands.md` for special agents when a project is active, but `collab.md` is the only template injected unconditionally for special agents. Gateway agents receive neither `crabcakes-commands.md` nor any equivalent platform context.

### 2.2 Proposed Change

Add `prompts/system/crabcakes-context.md` to both flows. For gateway agents, inject it alongside `collab.md` in `_build_awareness_prefix()`. For special agents, inject it alongside `collab.md` in `compose_system_prompt()`.

**Rationale for injection alongside `collab.md`:** `collab.md` defines agent-to-agent interaction protocols. `crabcakes-context.md` defines the platform rendering environment. Both are app-level, unconditional, and apply regardless of project. Grouping them keeps the injection logic consistent across both flows.

---

## 3. Files to Create

### 3.1 `prompts/system/crabcakes-context.md`

Platform knowledge for all agents. Covers rendering, commands, review layer, and special vs gateway agent distinction.

```markdown
## CrabCakes Environment

You are chatting through CrabCakes — the first AI-native project development environment. CrabCakes is a GTK4 desktop application that brings together human developers and AI agents to build real software collaboratively. It connects to an OpenClaw gateway via WebSocket and provides a rich chat UI with project tabs, agent tabs, activity indicators, feed cards, git integration, a code review layer, and multi-agent task orchestration.

### Custom Rendering
Your markdown renders in GTK4 Pango widgets. Standard markdown works as expected. Additionally:

- Use a fenced code block with the language `image` to render an inline image. The content is the absolute file path:

    ```image
    /absolute/path/to/file.png
    ```

  Note: this is a standard 3-backtick code block — the language tag is `image`, and the body is one file path per block.
- Do NOT use `MEDIA:` directives for images in CrabCakes. The `MEDIA:` syntax is for other channels (webchat, Telegram, etc.). In CrabCakes, always use the `image` code block shown above.
- Feed cards appear automatically for git commits, file edits, and review events — you do not need to format these.
- Activity bubbles (tool calls, plans, patches) are generated from gateway events automatically.

### Backtick Commands
Use backtick commands to query CrabCakes state: `status`, `agents`, `tasks`, `review`, `cost`

### Review Layer
When agents write files through the project, changes go through a checkpoint → diff → accept/reject flow. You do not push changes directly.

### Special vs Gateway Agents
Special agents (Coder, Debugger, Test Engineer) run locally against LLM APIs with file/exec tools. Gateway agents (you) run through the OpenClaw gateway. Both types appear in the same project chats.
```

---

## 4. Code Changes

### 4.1 `ui/handlers/chat_handler.py` — `_build_awareness_prefix()`

**Location:** ~line 803, after the `collab` loading block and before the final `if parts` return.

**Change:** Add a second `try/except` block, identical in pattern to the `collab` block, loading `crabcakes-context` instead.

**Exact insertion point** (after line 803 `except Exception: pass` and before line 804 `if parts:`):

```python
        # Inject CrabCakes platform context — rendering formats, commands, review layer
        # Same template injected for special agents via compose_system_prompt().
        # Gateway agents do not reach compose_system_prompt(), so this is the injection point.
        try:
            from utils.prompt_loader import load_prompt_template
            cc_ctx = load_prompt_template("crabcakes-context")
            if cc_ctx and cc_ctx.strip():
                parts.append(cc_ctx)
        except Exception:
            pass

        if parts:
```

**Note:** The `try/except` wrapping means if the template file is missing or empty, the method silently continues. No existing behavior changes if the file does not exist.

### 4.2 `utils/prompt_loader.py` — `compose_system_prompt()`

**Location:** ~line 159–162, after the `collab` loading block (step 1b).

**Change:** Add step 1c — load `crabcakes-context.md` unconditionally alongside `collab.md`.

**Exact insertion point** (after line 162 `if collab: parts.append(collab)` and before line 164 `# 2. Project awareness`):

```python
    # 1c. CrabCakes platform context (all agents — applies regardless of project/role)
    cc_ctx = load_prompt_template("crabcakes-context")
    if cc_ctx:
        parts.append(cc_ctx)
```

**Rationale:** `compose_system_prompt()` already injects `collab.md` unconditionally at step 1b. Adding `crabcakes-context.md` at step 1c keeps platform context and collaboration protocol at the same logical level — app-level, unconditional, before any project-specific templates.

---

## 5. Verification

### 5.1 Manual Checks

1. **Template exists:** `prompts/system/crabcakes-context.md` is readable and non-empty.
2. **Gateway agent awareness:** Open a project tab with a gateway agent. Send a message. The agent's context should include the CrabCakes platform section. (Can be verified by asking the agent to describe the rendering environment.)
3. **Special agent context:** Send a message to the Coder agent in a project tab. The Coder's system prompt should include the `crabcakes-context.md` content.
4. **Missing file is safe:** Rename `crabcakes-context.md` temporarily. Restart the app. No crash, no error dialog. Gateway agent and special agent chats still function normally.
5. **Commands work:** With the template active, gateway agent responds to `` `status`` ``, `` `agents`` ``, `` `tasks`` `` commands in the project chat.

### 5.2 Tests

No new test files required. The change is additive and self-verifying via the try/except guard. The existing `test_prompt_loader.py` suite confirms `load_prompt_template()` behavior is unchanged.

---

## 6. Acceptance Criteria

- [ ] `prompts/system/crabcakes-context.md` created with content matching §3.1
- [ ] `ui/handlers/chat_handler.py` — `crabcakes-context` injected after `collab` in `_build_awareness_prefix()` at the correct insertion point
- [ ] `utils/prompt_loader.py` — `crabcakes-context` injected after `collab` in `compose_system_prompt()` at step 1c
- [ ] Both injection points use the same `try/except` pattern as the existing `collab` blocks
- [ ] Missing template file does not cause errors (try/except guards in both locations)
- [ ] ARCHITECTURE.md updated — `compose_system_prompt()` template sequence now includes step 1c (crabcakes-context)
- [ ] No changes to routing, activity handler, feed cards, or render pipeline