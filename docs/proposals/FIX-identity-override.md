# Fix Proposal: Identity Override — Gateway Agent Awareness Injection

**Date:** 2026-05-09  
**Author:** Qaster  
**Status:** READY FOR IMPLEMENTATION  
**Severity:** CRITICAL  
**Bug doc:** `docs/bugs/BUG_REPORT-identity-override.md`

> **Status (verified 2026-06-12):** ⚠️ **NEEDS PER-BUG VERIFICATION** — 
> **status:** `PARTIAL` — sortable tag for `ls | grep STATUS` The bug doc reference (`docs/bugs/BUG_REPORT-identity-override.md`) was not located in this audit. The proposal's specific claim — that gateway agents receive identity-bearing system prompts as user message content — requires reading `agent/context.py` and the gateway integration to confirm. The proposal was authored 2026-05-09 and predates the Phase 6.2 A2A work; the A2A infrastructure may have incidentally fixed some of these issues, or they may still be open. **Marked NEEDS PER-BUG VERIFICATION pending a targeted audit.**

---

## Problem Statement

When a user sends a message in a project group chat, gateway agents (QTR, Qaster, etc.) receive identity-bearing system prompt text as **user message content**. The gateway `chat.send` API has no `systemPrompt` field — the `[System Instructions]` wrapper is cosmetic fiction that arrives as plain user text in the agent's session.

**What happens today:**

```
User sends "hello" in project group chat
  → ChatHandler._build_awareness_prefix() calls compose_system_prompt()
  → compose_system_prompt() loads 5+ templates including:
      default.md       → "You are {{AGENT_NAME}}."
      project-awareness.md → "You are working on project..."
      crabcakes-commands.md → "You are working inside CrabCakes..."
      project-onboarding.md → "You are onboarding onto a new project..." (if project not onboarded)
  → All concatenated and wrapped with "[System Instructions]\n...\n\n[User Message]\n"
  → gw.send_message() sends the whole thing as message text
  → Gateway delivers as USER MESSAGE to agent session
```

**Why it's bad:**
1. Gateway agents already have a real system prompt (configured via SOUL.md/IDENTITY.md in OpenClaw). Injecting "You are Qaster, a project team member" as user text **conflicts** with their actual identity.
2. The `[System Instructions]` wrapper implies a protocol mechanism that doesn't exist. There is no `systemPrompt` field in `chat.send`.
3. The onboarding template (interview questions, setup workflow) fires for ALL agents on new projects — but it's designed for Coder only.
4. Template composition loads 3,000+ tokens of behavioral instructions that are **redundant** for gateway agents (they already have their own system prompt) and **wrong** for them (wrong identity, wrong role).

---

## Root Cause

`ChatHandler._build_awareness_prefix()` (line 608) calls `compose_system_prompt()` for ALL agents, regardless of whether the target is a gateway agent or a special agent. `compose_system_prompt()` was designed for the **special agent path** (Coder/Debugger) where it serves as the actual system prompt. Gateway agents don't need it — they need raw project awareness data only.

**The call chain:**

```
chat_handler.py:375-376  (group broadcast loop)
    agent_display = self._get_agent_display_name(member)
    prefix = self._build_awareness_prefix(project_name, agent_display)

chat_handler.py:608-643  (_build_awareness_prefix)
    awareness_dict = build_awareness_dict(project_path)
    prompt = compose_system_prompt(agent_name=agent_display, ...)  ← WRONG for gateway agents
    return f"[System Instructions]\n{prompt}\n\n[User Message]\n"
```

---

## Proposed Fix

### Strategy

**Two-path awareness injection** — `ChatHandler` already knows whether a target is a special agent or a gateway agent (the `is_special` check exists at line 351). Use that same distinction to choose the correct awareness format:

| Target | Awareness format | Why |
|--------|-----------------|-----|
| **Special agents** (Coder, Debugger) | `compose_system_prompt()` — full template pipeline | They have NO other system prompt channel. This IS their system prompt. |
| **Gateway agents** (QTR, Qaster) | `build_awareness_block()` — raw structured data only | They have a real system prompt from OpenClaw. They only need project context data. |

### What Changes

#### 1. `ui/handlers/chat_handler.py` — `_build_awareness_prefix()` (PRIMARY FIX)

**Current signature:**
```python
def _build_awareness_prefix(self, project_name: str, agent_name: str = "") -> str:
```

**New signature:**
```python
def _build_awareness_prefix(self, project_name: str, agent_name: str = "", *, target_session_key: str = "") -> str:
```

Add `target_session_key` parameter so the method can determine if the target is a special agent.

**New logic:**

```python
def _build_awareness_prefix(self, project_name: str, agent_name: str = "", *, target_session_key: str = "") -> str:
    """Build project awareness prefix for first message to an agent.

    Gateway agents receive raw awareness data only (build_awareness_block).
    Special agents receive the full composed system prompt (compose_system_prompt).

    Returns empty string if awareness not available or already sent.
    """
    if not self._project_handler:
        return ""
    project_path = self._project_handler.get_active_project_path()
    if not project_path:
        return ""

    # Determine if target is a special agent
    is_special = (
        self._agent_runtime_handler is not None
        and target_session_key in self._agent_runtime_handler.get_special_agents()
    )

    try:
        if is_special:
            # Special agents: full composed system prompt (this IS their system prompt)
            from utils.prompt_loader import compose_system_prompt
            from utils.project_awareness import build_awareness_dict
            awareness_dict = build_awareness_dict(project_path)
            review_mode = "off"
            try:
                from utils.project_awareness import build_awareness_snapshot
                snapshot = build_awareness_snapshot(project_path)
                review_mode = snapshot.get("review_mode", "off")
            except Exception:
                pass

            agent_def = self._agent_runtime_handler.get_special_agent_def(target_session_key)
            agent_role = agent_def.display_name.lower() if agent_def else ""

            prompt = compose_system_prompt(
                agent_name=agent_name,
                agent_role=agent_role,
                project_path=project_path,
                project_awareness=awareness_dict,
                review_mode=review_mode,
            )
            if prompt.strip():
                return f"{prompt}\n\n"
        else:
            # Gateway agents: raw awareness data only
            from utils.project_awareness import build_awareness_block
            block = build_awareness_block(project_path)
            if block.strip():
                return f"## Project Context\n\n{block}\n\n"
    except Exception:
        pass
    return ""
```

**Key changes:**
- Added `target_session_key` keyword parameter
- Two-path logic: special agents get `compose_system_prompt()`, gateway agents get `build_awareness_block()`
- Gateway agents get `## Project Context` header (neutral, not fake system instruction)
- Special agents get NO wrapper delimiters (their runtime handles this as a real system prompt)
- Both paths are existing, tested code — just routed correctly

#### 2. `ui/handlers/chat_handler.py` — Update all call sites

There are exactly **3 call sites** for `_build_awareness_prefix()`. All need the new `target_session_key` parameter:

**Call site 1: Solo DM, gateway agent (line ~358-360)** — Already in the `else` branch (not special), so:
```python
agent_display = self._get_agent_display_name(solo_target)
prefix = self._build_awareness_prefix(project_name, agent_display, target_session_key=solo_target)
```

**Call site 2: Group broadcast (line ~375-377)** — Each member is either special or gateway:
```python
agent_display = self._get_agent_display_name(member)
prefix = self._build_awareness_prefix(project_name, agent_display, target_session_key=member)
```

**Call site 3: Solo DM, special agent path (line ~353-354)** — Currently skips awareness entirely (calls `send_to_special_agent` directly). No change needed here — the special agent runtime handles its own prompt via `build_system_prompt()` in `agent/context.py`.

#### 3. No changes needed to `compose_system_prompt()` or `prompt_loader.py`

The `compose_system_prompt()` function is correct for its purpose (special agent system prompts). The bug is in HOW it's called, not in what it does.

#### 4. No changes needed to `gateway/client.py`

The gateway protocol is fine — it sends user messages. We just need to stop pretending user messages are system instructions.

### What Gets Removed

| What | Where | Why |
|------|-------|-----|
| `[System Instructions]` wrapper | `chat_handler.py` line 641 | Fake protocol convention — gateway has no such mechanism |
| `[User Message]` wrapper | `chat_handler.py` line 641 | Same reason |
| `compose_system_prompt()` call for gateway agents | `chat_handler.py` line 620-631 | Gateway agents don't need behavioral templates |

### What Does NOT Change

| Component | Reason |
|-----------|--------|
| `compose_system_prompt()` in `prompt_loader.py` | Correct for special agents — untouched |
| `build_awareness_block()` in `project_awareness.py` | Already exists and works — just now actually used |
| `build_awareness_dict()` in `project_awareness.py` | Still used by `compose_system_prompt()` path |
| `agent/context.py` → `build_system_prompt()` | Special agent runtime — separate system, untouched |
| `gateway/client.py` `send_message()` | Protocol is fine, no changes needed |
| All template files in `prompts/system/` | Unchanged — still used by special agent path |
| `_awareness_sent` tracking set | Still needed to avoid re-sending on every message |
| `_get_agent_display_name()` | Still needed for awareness context |
| Solo DM special agent routing (line ~351-354) | Already correct — routes through `AgentRuntimeHandler` |

---

## Files Changed

| File | Change Type | Lines | Description |
|------|-------------|-------|-------------|
| `ui/handlers/chat_handler.py` | Modify | ~608-643 | Rewrite `_build_awareness_prefix()` with two-path logic |
| `ui/handlers/chat_handler.py` | Modify | ~358-360 | Pass `target_session_key` in solo DM gateway call |
| `ui/handlers/chat_handler.py` | Modify | ~375-377 | Pass `target_session_key` in group broadcast call |

**Total: 1 file, ~40 lines changed.** No new files. No new dependencies.

---

## Verification Plan

### Manual Testing

1. **Gateway agent in project group chat:**
   - Open a project with QTR/Qaster as members
   - Send "hello" in the project group chat
   - Observe in agent's session: message starts with `## Project Context` followed by structured data
   - Verify: NO "You are..." identity statements, NO `[System Instructions]` wrapper
   - Verify: agent still has its own identity (from SOUL.md/IDENTITY.md)

2. **Special agent (Coder) in project:**
   - Add Coder to project
   - Send a message to Coder via group chat or solo DM
   - Verify: Coder still gets full composed system prompt with all templates
   - Verify: Coder's identity, tools, and workflow instructions are intact

3. **Solo DM to gateway agent from project:**
   - Right-click → select a gateway agent as solo DM target
   - Send message
   - Verify: same raw awareness format as group chat

4. **Second message in same session:**
   - Send a second message to the same agent
   - Verify: NO awareness prefix (already sent, tracked in `_awareness_sent`)

5. **No project open:**
   - Chat directly with an agent (no project tab)
   - Verify: no awareness prefix at all (falls through to plain `gw.send_message`)

### Automated Tests

Add to `tests/test_chat_handler.py`:

```python
class TestBuildAwarenessPrefix:
    """Test two-path awareness injection."""

    def test_gateway_agent_gets_raw_awareness(self, handler, tmp_path):
        """Gateway agents receive build_awareness_block, not compose_system_prompt."""
        prefix = handler._build_awareness_prefix(
            "test-project", "QTR",
            target_session_key="agent:qtr:telegram:direct:1234"
        )
        assert "[System Instructions]" not in prefix
        assert "[User Message]" not in prefix
        assert "## Project Context" in prefix

    def test_special_agent_gets_composed_prompt(self, handler, tmp_path):
        """Special agents receive the full composed system prompt."""
        prefix = handler._build_awareness_prefix(
            "test-project", "Coder",
            target_session_key="special:coder"
        )
        assert "Coder" in prefix  # from default.md identity
        assert len(prefix) > 500  # full composed prompt is substantial

    def test_no_project_returns_empty(self, handler):
        """No project → empty prefix."""
        prefix = handler._build_awareness_prefix("nonexistent", "QTR")
        assert prefix == ""
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Gateway agents lose project context | Low | High | `build_awareness_block()` is already tested and produces rich structured data |
| Special agent prompts break | Very Low | High | No changes to `compose_system_prompt()` or special agent runtime path |
| `build_awareness_block()` missing data that `compose_system_prompt()` had | Low | Medium | Compare outputs — `build_awareness_block()` includes manifest, team, state, memory, tasks. Only "missing" items are behavioral instructions (correct to omit) and crabcakes command reference (gateway agents don't use backtick commands) |
| Tests break | Low | Low | `compose_system_prompt()` tests are in `test_prompt_loader.py` and don't touch `chat_handler.py` |

---

## Architecture Alignment

Per ARCHITECTURE.md:
- **Handler boundary:** ChatHandler owns awareness injection for gateway messages. This fix keeps that boundary intact.
- **No cross-boundary imports:** All imports stay within existing patterns (`utils/project_awareness`, `utils/prompt_loader`).
- **No new state:** Uses existing `_awareness_sent` set, `_project_handler`, `_agent_runtime_handler`.
- **Minimal change surface:** Only `chat_handler.py` is modified. All downstream components are untouched.

---

## Implementation Notes for the Coder

1. **Read `_build_awareness_prefix()` first** (lines 608-643 in `chat_handler.py`). Understand the current flow before changing it.

2. **Read `build_awareness_block()`** (line 441 in `utils/project_awareness.py`). This is what gateway agents will get instead. It's already tested and produces: manifest, team roster, current state (git/tasks/review mode), and project memory.

3. **The three call sites are at lines ~358, ~375, and the special agent path at ~353.** Only the first two call `_build_awareness_prefix()`. The third routes through `AgentRuntimeHandler.send_to_special_agent()` which has its own prompt pipeline.

4. **`build_awareness_block()` vs `build_awareness_dict()`:** `build_awareness_block()` returns a formatted string. `build_awareness_dict()` returns a dict of template variables. Use `build_awareness_block()` for gateway agents (it's designed for this exact purpose).

5. **Don't overthink the wrapper.** Gateway agents just need `## Project Context\n\n{block}\n\n` as a prefix. No `[System Instructions]`, no `[User Message]`, no identity declarations. The block itself contains all the context data they need.

6. **Test with `CRABCAKES_PROMPT_DEBUG=1`** to inspect what the composed prompt looks like for special agents before and after the change.

7. **After implementing, verify manually** using the 5-step verification plan above. Pay special attention to the gateway agent path — open a project, add QTR, send a message, and confirm the agent receives raw context data without identity injection.
