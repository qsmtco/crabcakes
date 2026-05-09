# Coder Prompt Framework Enhancement Proposal

**Date:** 2026-05-07  
**Author:** Qaster (with Claude Code / Augment Code / Aider research)  
**Status:** DRAFT — Pending Captain JAQx Review

---

## 1. Executive Summary

Coder works. It successfully implemented `git_ops.py` for crabwatch with correct structure and reasonable quality. But it's not *elite*. The gap between "functional" and "exceptional" lives in the prompting framework — the system prompt, tool descriptions, context assembly, and execution harness that collectively define Coder's behavior.

This proposal identifies **28 specific improvements** across 7 domains, ranked by impact and feasibility. The goal: transform Coder from a competent code generator into a disciplined, autonomous software engineer that rivals Claude Code and Cursor.

---

## 2. Current Architecture — Complete Map

### 2.1 Agent Definition Chain

```
special_agents.py          → SpecialAgentDef (name, tools, prompt template)
      ↓
agent/config.py            → AgentConfig (model, providers, limits)
      ↓
agent/runtime.py           → AgentRuntime (tool loop, streaming, persistence)
      ↓
agent/context.py           → build_system_prompt() → build_file_context()
      ↓
utils/prompt_loader.py     → compose_system_prompt() — template composition
      ↓
utils/project_awareness.py → build_awareness_dict() — project state variables
      ↓
prompts/system/*.md        → Template files (default, coder, project-awareness, etc.)
```

### 2.2 System Prompt Assembly (Current)

The system prompt is composed by concatenating 4-6 template files:

1. **`default.md`** — Generic identity ("You are {AGENT_NAME}, a project team member")
2. **`project-awareness.md`** — Project name, team roster, workflow phase, context memory
3. **`crabcakes-commands.md`** — Backtick command reference + crabcard format
4. **`coder.md`** — 5-line coding guidelines (clean code, small steps, patterns)
5. **`code-review.md`** — (conditional) review mode rules
6. **`project-onboarding.md`** — (conditional) onboarding interview flow

Then `build_file_context()` appends:
- Directory tree (files listing)
- Key files content (README, ARCHITECTURE, package.json, etc.)

### 2.3 The Problem: Two Competing System Prompts

**Critical architectural issue:** There are actually TWO system prompt systems:

1. **`special_agents.py`** defines `CODER_PROMPT_TEMPLATE` — a static template with `{tools}`, `{project_path}`, `{file_context}` placeholders
2. **`prompt_loader.py`** composes from `prompts/system/*.md` templates

**But `prompt_loader.py` is what actually runs.** The `CODER_PROMPT_TEMPLATE` in `special_agents.py` appears to be dead code — `agent_runtime_handler.py` calls `build_system_prompt()` which goes through `prompt_loader`, not the template in `special_agents.py`.

This means:
- The carefully crafted `CODER_PROMPT_TEMPLATE` with its role description and working directory is **never sent to the model**
- The model gets the generic `default.md` + the thin `coder.md` instead
- The tool list is injected via `{{TOOL_LIST}}` in `default.md`, but tool descriptions are minimal

### 2.4 What the Model Actually Sees (Current)

```
[System] You are Coder, a project team member.                    ← generic
         Guidelines: be concise, reference files, ask if unsure.
         ## Tools
           - read_file
           - write_file
           - exec_command
           - list_files
           - search_files
           - web_search
           - web_fetch

[System] You are working on **crabwatch** at /home/q/projects/... ← awareness
         Team: PM: Captain JAQx, QTR (builder), Qaster (reviewer)
         Project Memory: [context.md content]
         Current State: Git: abc1234 (dirty)
         Workflow Phase: Implementation

[System] CrabCakes Commands Reference                              ← commands
         `task, `start, `done, `review, etc.
         Crabcard format for file modifications...

[System] You are Coder, a software engineering agent.             ← coder.md
         Guidelines: clean code, small steps, patterns, test.
         ← THIS IS ONLY 5 LINES

[User] Implement task #2: Git Integration (utils/git_ops.py)
```

**Total instruction for "how to be a good software engineer": ~5 lines.** This is the core problem.

---

## 3. Gap Analysis — Current vs. Elite

### 3.1 Claude Code (Reference Architecture)

Claude Code's prompt system (from VILA-Lab analysis):
- **~1.6% AI logic, 98.4% infrastructure** — but that 1.6% is dense, tested, and iterated
- 5-layer compaction pipeline before every model call
- `CLAUDE.md` hierarchy: project-level instructions with inheritance
- Explicit gather-act-verify loop baked into the prompt
- Tool definitions include **when to use / when NOT to use** guidance
- Error recovery: max output token escalation, reactive compaction, fallback model
- Subagent delegation with isolated context/permissions

### 3.2 Augment Code (Prompt Engineering)

Key principles from Augment's #1 SWE-bench agent:
- **Context is king** — "the most important factor is providing the model with the best possible context"
- Complete, consistent world view across all prompt components
- Tool definitions explain *when* to use each tool, not just *what* it does
- Truncation strategy matters — keep prefix and suffix, truncate middle
- "Present a complete picture of the world" — explain the setting, resources, constraints
- Thorough prompts beat clever prompts — "do not worry about prompt length"

### 3.3 The Gap

| Dimension | CrabCakes Coder (Current) | Elite Agents |
|-----------|--------------------------|--------------|
| System prompt length | ~200 words of engineering guidance | 2,000-10,000+ words |
| Tool descriptions | 1-2 sentences each | Detailed with examples, anti-patterns, when-to-use |
| Context assembly | Static tree + key files | Dynamic relevance scoring, query-aware retrieval |
| Error recovery | None (tool fails → game over) | Retry with escalation, fallback strategies |
| Verification | "Run tests" mentioned once | Explicit verify step in every action cycle |
| Conversation management | Simple trim to token limit | Graduated compaction (5 stages) |
| Planning | None | Plan → execute → verify loop |
| Self-correction | None | Structured debug cycle, hypothesis testing |

---

## 4. Proposed Improvements

### Priority 1: System Prompt Rewrite (HIGH IMPACT, MEDIUM EFFORT)

#### 4.1 Kill the Dead Template, Strengthen the Live One

The `CODER_PROMPT_TEMPLATE` in `special_agents.py` is dead code. Either:
- **Option A (Recommended):** Make `coder.md` the single source of truth and delete the dead template
- **Option B:** Wire `special_agents.py` template through `prompt_loader`

#### 4.2 Rewrite `prompts/system/coder.md`

**Current (5 lines):**
```
You are Coder, a software engineering agent.
Write clean code. Work in small steps. Prefer patterns.
Follow conventions. Test your changes.
```

**Proposed** — a comprehensive engineering agent prompt:

```markdown
You are Coder, a senior software engineer working on the project **{{PROJECT_NAME}}**.

## Core Operating Principles

1. **Read Before Write.** Always read existing code, tests, and documentation before
   making changes. Never assume you know what a file contains.

2. **Plan Then Execute.** Before writing code, briefly state:
   - What you're going to do (one sentence)
   - Which files you'll modify
   - What the expected outcome is
   
3. **Small, Verified Steps.** Each action should be independently verifiable.
   If a change touches >3 files, break it into smaller steps.

4. **Verify After Every Change.** After modifying code:
   - Run relevant tests
   - If tests don't exist, write them first (TDD when possible)
   - If tests fail, fix before proceeding
   - Never declare completion without verification

5. **Preserve Existing Patterns.** Match the codebase's existing style:
   - Import ordering
   - Naming conventions
   - Error handling patterns
   - Logging conventions
   - Type annotation style

## Workflow

### Starting a Task
1. Read `.crabcakes/architecture.md` for structural constraints
2. Read `.crabcakes/requirements.md` for what's needed
3. Read `.crabcakes/context.md` for prior work and decisions
4. Read relevant existing code files
5. State your plan
6. Execute

### During Implementation
- After each file modification, emit a crabcard (see commands reference)
- If you discover the architecture needs changes, STOP and report to PM
- If you're stuck after 3 attempts on something, report as blocked
- If tests exist, run them. If not, suggest creating them.

### Completing a Task
1. Run the full test suite
2. Run the linter (if configured in project.md)
3. Verify the implementation matches the architecture doc
4. Report completion with a summary of what was built

## Code Quality Standards

- Functions: single responsibility, <50 lines preferred
- Error handling: explicit, never silent failures
- Logging: use the project's logging framework, never bare print()
- Types: follow the project's type annotation conventions
- Documentation: docstrings for public functions, comments for non-obvious logic
- Naming: descriptive variable names, no single-letter exceptions (except i/j in loops)

## Tool Usage Strategy

- `read_file`: Use FIRST for any file you'll modify. Always.
- `list_files`: Use to understand project structure before diving in.
- `search_files`: Use to find patterns, imports, usages across the codebase.
- `write_file`: Use AFTER reading the existing file (or for new files).
- `exec_command`: Use for running tests, linters, git commands. NOT for file creation.
- `web_search` / `web_fetch`: Use when you need documentation or API references.

## Error Handling

When a tool fails:
1. Read the error message carefully
2. Identify the root cause (not the symptom)
3. If it's a code error: fix the code, re-run
4. If it's an environment error: report to PM
5. If you've failed 3 times: mark blocked and explain why

## Working with the Architecture

The architecture doc is law. If you discover a conflict between the architecture
and reality:
1. STOP
2. Report the discrepancy to the PM
3. Wait for guidance
Do NOT improvise structural changes.

## Git Conventions

- Commit messages: `type(scope): description` (e.g., `feat(git-ops): add staged files detection`)
- Never commit without PM approval (use `review` command)
- Keep commits atomic — one logical change per commit
```

#### 4.3 Rewrite Tool Descriptions in `agent/tools.py`

**Current `read_file` description:**
```
"Read the contents of a file from the project directory. Returns the text 
content, or an error if the file is binary, missing, or inaccessible. Truncates at 50KB."
```

**Proposed:**
```
"Read a file's text content from the project directory.

WHEN TO USE: Always read a file BEFORE modifying it. Use to understand existing 
code, check imports, verify structure, or review test expectations.

WHEN NOT TO USE: For listing directory contents (use list_files). For searching 
across files (use search_files).

BEHAVIOR: Returns UTF-8 text content. Binary files return an error. Truncates 
at 50KB. Supports offset/limit for reading specific sections of large files.

COMMON PATTERNS:
- Read a file before writing: understand context, imports, style
- Read tests before implementing: understand expected behavior
- Read architecture.md first when starting a new task"
```

Similarly enhance all 7 tool descriptions with WHEN TO USE / WHEN NOT TO USE / BEHAVIOR / COMMON PATTERNS sections.

---

### Priority 2: Dynamic Context Assembly (HIGH IMPACT, HIGH EFFORT)

#### 4.4 Query-Aware File Context

**Current:** Static directory tree + key files (README, ARCHITECTURE, package.json).

**Problem:** The model gets the same context whether it's implementing a database module or fixing a UI bug. The tree is ~200 lines of noise when you only need 3 files.

**Proposed:** Two-phase context:

1. **Phase A (Quick Win):** Always include architecture.md, requirements.md, context.md, tasks.md from `.crabcakes/` — these are small and always relevant.

2. **Phase B (Future):** Query-aware retrieval — analyze the user message to identify relevant files, include those instead of the full tree. This is what Augment Code does.

```python
def build_smart_file_context(project_path: str, user_message: str) -> str:
    """
    Build context prioritized by relevance to the user's request.
    
    Priority:
    1. .crabcakes/ project docs (always included)
    2. Files mentioned in the user message
    3. Files related by import graph (future)
    4. Directory tree (fallback, truncated)
    """
```

#### 4.5 Context Budget Management

**Current:** No token budget awareness. Context grows until `trim_to_token_limit()` kicks in with crude oldest-first removal.

**Proposed:**
- Explicit token budget: e.g., 40% system prompt, 30% conversation history, 30% tool results
- Smart truncation: keep recent tool results + user message intact, compress older messages
- Mid-truncation for long tool outputs (keep head + tail, drop middle — per Augment's research)

---

### Priority 3: Execution Harness Improvements (MEDIUM IMPACT, LOW EFFORT)

#### 4.6 Plan-Execute-Verify Loop

**Current:** The tool loop just runs until no more tool calls. No explicit plan → execute → verify cycle.

**Proposed:** Inject a structured thinking step into the system prompt that enforces:

```
1. [PLAN] What am I going to do?
2. [EXECUTE] Do it (read → write → test)
3. [VERIFY] Did it work? Run tests, check output.
4. [REPORT] Emit crabcard + completion status
```

This can be done purely through prompt engineering — no code changes to the runtime.

#### 4.7 Error Recovery

**Current:** Tool failure → the model gets the error text and tries again. No structured retry.

**Proposed:** Add retry guidance to the system prompt:
- On tool error: read the error, identify root cause, try a fix (max 3 attempts)
- On 3 failures: mark blocked, report to PM with what you tried
- On test failure: fix the code, not the test (unless the test is wrong)

#### 4.8 Max Iterations Intelligence

**Current:** `max_tool_iterations: int = 50` — blunt hammer.

**Proposed:** Track iteration purpose:
- If last 5 iterations are read-only (exploration) → extend budget
- If last 5 iterations are write-only (implementation) → warn and pause
- If stuck in a loop (same tool, same args) → break and report

---

### Priority 4: Conversation Management (MEDIUM IMPACT, MEDIUM EFFORT)

#### 4.9 Graduated Compaction

**Current:** `trim_to_token_limit()` removes oldest messages first.

**Proposed:** 3-tier strategy (simplified from Claude Code's 5-tier):
1. **Snip:** Truncate long tool outputs (keep head + tail)
2. **Compress:** Replace old assistant+tool exchanges with summaries
3. **Drop:** Remove oldest messages entirely

#### 4.10 Summary on Trim

When messages are trimmed, inject a compressed summary so the model doesn't lose context:

```python
# Before trimming old messages, generate a one-paragraph summary
# of what was accomplished in those turns
conv.inject_context_summary("Previously: Implemented git_ops.py with 9 functions...")
```

---

### Priority 5: Tool Enhancements (MEDIUM IMPACT, MEDIUM EFFORT)

#### 4.11 Add `edit_file` Tool

**Current:** Only `write_file` (full file overwrite). This is the #1 source of bugs in AI coding — the model rewrites the entire file and subtly changes things it didn't mean to.

**Proposed:** Add an `edit_file` tool that takes `old_string` + `new_string` and does precise replacement (like OpenClaw's edit tool, or Aider's search-and-replace):

```python
{
    "name": "edit_file",
    "description": "Make a targeted edit to a file by replacing exact text...",
    "parameters": {
        "path": "Relative path within the project directory",
        "old_text": "Exact text to find (must be unique in the file)",
        "new_text": "Replacement text",
    }
}
```

Benefits:
- Forces the model to read first (can't replace what it hasn't seen)
- Preserves unchanged code (no accidental modifications)
- Much clearer crabcard diffs (the edit IS the diff)

#### 4.12 Add `grep_code` Tool (Enhanced search)

**Current:** `search_files` uses basic grep. 

**Proposed:** Enhance to support:
- Symbol search (function/class definitions)
- Import graph queries
- Reference finding

This is a stretch goal — the basic grep is functional.

#### 4.13 Improve `exec_command` Output

**Current:** Returns stdout+stderr combined, truncated at 100KB.

**Proposed:**
- Separate stdout and stderr
- Return exit code explicitly in the tool result
- For test failures, include the specific failure lines (not just "1 test failed")

---

### Priority 6: Observability & Debugging (LOW IMPACT, LOW EFFORT)

#### 4.14 Prompt Dump on Request

Add a debug command (or env var) that dumps the composed system prompt to a file for inspection. This is invaluable for prompt engineering iteration.

```python
# In prompt_loader.py
if os.environ.get("CRABCAKES_PROMPT_DEBUG"):
    with open("/tmp/crabcakes-last-prompt.md", "w") as f:
        f.write(result)
```

#### 4.15 Token Budget Logging

Log the token breakdown per turn:
- System prompt: X tokens
- Conversation history: Y tokens
- Tool results: Z tokens
- Available budget: remaining

This helps identify context bloat issues.

---

### Priority 7: Architecture Cleanup (LOW IMPACT, LOW EFFORT)

#### 4.16 Eliminate Dead Code

- `CODER_PROMPT_TEMPLATE` and `DEBUGGER_PROMPT_TEMPLATE` in `special_agents.py` are never used by `prompt_loader.py`. Either wire them in or delete them.
- The `{review_mode_block}` placeholder in the dead templates doesn't exist in `prompt_loader`'s variable system.

#### 4.17 Template Variable Consistency

The prompt template system uses `{{VARIABLE}}` (double curly) in the `.md` files, but the dead templates in `special_agents.py` use `{variable}` (single curly). Standardize on one format.

#### 4.18 System Prompt Ordering

Current order: default → project-awareness → commands → coder → review

**Proposed order:** coder (identity) → project-awareness → engineering-guidelines → commands → review

The identity should come first and be strongest. The current `default.md` is a generic "you're a team member" that dilutes the Coder identity.

---

## 5. Implementation Priority Matrix

| # | Improvement | Impact | Effort | Dependencies | Recommended Phase |
|---|------------|--------|--------|--------------|-------------------|
| 4.2 | Rewrite `coder.md` | 🔴 Critical | 2h | None | **Phase 1** (immediate) |
| 4.3 | Enhance tool descriptions | 🔴 Critical | 2h | None | **Phase 1** |
| 4.1 | Kill dead template | 🟡 Medium | 30m | 4.2 | **Phase 1** |
| 4.6 | Plan-Execute-Verify prompt | 🔴 High | 1h | 4.2 | **Phase 1** |
| 4.14 | Prompt dump debugging | 🟢 Low | 30m | None | **Phase 1** |
| 4.18 | Reorder prompt templates | 🟡 Medium | 15m | 4.2 | **Phase 1** |
| 4.16 | Eliminate dead code | 🟢 Low | 30m | 4.1 | **Phase 1** |
| 4.11 | Add `edit_file` tool | 🔴 High | 4h | None | **Phase 2** |
| 4.4a | Always include .crabcakes/ docs | 🟡 Medium | 1h | None | **Phase 2** |
| 4.7 | Error recovery prompt | 🟡 Medium | 1h | 4.2 | **Phase 2** |
| 4.13 | Improve exec output format | 🟡 Medium | 2h | None | **Phase 2** |
| 4.5 | Context budget management | 🟡 Medium | 4h | 4.4a | **Phase 3** |
| 4.9 | Graduated compaction | 🟡 Medium | 4h | 4.5 | **Phase 3** |
| 4.10 | Summary on trim | 🟡 Medium | 3h | 4.9 | **Phase 3** |
| 4.8 | Smart iteration limits | 🟢 Low | 2h | None | **Phase 3** |
| 4.4b | Query-aware retrieval | 🔴 High | 8h | 4.5 | **Phase 4** |
| 4.12 | Enhanced grep tool | 🟢 Low | 4h | None | **Phase 4** |
| 4.15 | Token budget logging | 🟢 Low | 1h | None | **Phase 4** |

---

## 6. Phase 1 Implementation Plan (Immediate)

Phase 1 is all prompt engineering — no runtime code changes needed:

1. **Rewrite `prompts/system/coder.md`** — Full engineering agent prompt (Section 4.2)
2. **Enhance tool descriptions in `agent/tools.py`** — When to use / not use for each tool (Section 4.3)
3. **Rewrite `prompts/system/default.md`** — Remove generic identity, just be the tool list carrier
4. **Delete `CODER_PROMPT_TEMPLATE`** from `special_agents.py` — Dead code
5. **Add `CRABCAKES_PROMPT_DEBUG`** to `prompt_loader.py` — One line
6. **Test** — Run Coder on a known task and compare before/after quality

Estimated time: **4-6 hours**

---

## 7. Expected Outcomes

### Before (Current)
```
[User] Implement task #2: Git Integration
[Coder] *writes entire file without reading existing code*
        *includes bugs like is_dirty() on IndexObject*
        *doesn't run tests*
        *doesn't read architecture doc first*
```

### After (Phase 1)
```
[User] Implement task #2: Git Integration
[Coder] Let me start by reading the architecture doc and requirements.
        [reads architecture.md, requirements.md, context.md]
        
        Plan: Implement utils/git_ops.py with the 4 required public functions
        (is_git_repo, get_git_log, get_diff_stat, load_gitignore) plus
        helper functions as needed.
        
        [reads existing project files to understand conventions]
        [implements in small functions]
        [reads each function back to verify]
        [runs tests]
        [emits crabcard with diff]
```

### After (Phase 4)
```
[User] Implement task #2: Git Integration
[Coder] [auto-loaded: architecture, requirements, context, relevant existing files]
        
        Plan: 4 public functions per architecture. I see the project uses
        GitPython based on pyproject.toml. Will follow existing patterns
        from crabwatch/utils/__init__.py.
        
        Step 1: is_git_repo + get_repo_root
        Step 2: get_git_log
        Step 3: get_diff_stat
        Step 4: load_gitignore
        Step 5: Test each function
        
        [implements with targeted edits, not full file rewrites]
        [runs tests after each function]
        [reports completion with verification results]
```

---

## 8. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Longer prompts increase cost | Medium | Token budget management (Phase 3) |
| Over-specified prompts reduce creativity | Low | Test on diverse tasks, iterate |
| edit_file tool introduces new failure mode | Medium | Fall back to write_file on match failure |
| Model ignores detailed instructions | Low | Use structured sections, bold key rules |
| Prompt changes cause regressions | Medium | Keep old prompts, test side-by-side |

---

## 9. Conclusion

The most impactful single change is **rewriting `coder.md`** — going from 5 lines of generic advice to a comprehensive engineering methodology. This alone should dramatically improve Coder's behavior on the crabwatch tasks.

The second most impactful change is **enhancing tool descriptions** — telling the model *when* to use each tool, not just *what* it does. This prevents the common pattern of writing code without reading existing files first.

Phase 1 is pure prompt engineering with no runtime risk. I recommend starting there and measuring the improvement before investing in the more complex runtime changes.

---

*"The agent loop is a simple while-loop; the real engineering complexity lives in the systems around it." — VILA-Lab, on Claude Code's architecture*
