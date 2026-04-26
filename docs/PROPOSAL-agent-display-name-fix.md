# Bug Fix Proposal: Agent Display Name in Awareness Injection

**Date:** 2026-04-26
**Author:** Qaster
**Bug:** Gateway agents receive `You are 7478874934` instead of `You are Qaster`
**Status:** Proposed — Awaiting Captain JAQx Approval
**Affects:** `ui/handlers/chat_handler.py`, `ui/handlers/project_handler.py`

---

## 1. Problem Statement

When `chat_handler._build_awareness_prefix()` composes the system prompt for a gateway agent, it passes an `agent_name` to `compose_system_prompt()`. The current code derives this name from the session key via:

```python
agent_display = member.split("/")[-1].split(":")[-1]
```

For session keys like `agent:qaster:telegram:direct:7478874934`, this produces `7478874934` (the Telegram user ID) — not a meaningful display name.

The system prompt then reads: `You are 7478874934, a project team member.` — which is useless to the agent.

---

## 2. Root Cause

**ChatHandler has no access to AgentManager.**

The display name for each agent session key is stored in `AgentManager._agent_names` (a `{session_key → name}` dict). `AgentManager` is owned by `GatewayHandler` and injected into:
- `ProjectHandler` via `set_agent_manager()`
- `CommandHandler` via `set_agent_manager()`
- `MainContent` via `set_agent_manager()`

But **NOT** into `ChatHandler`. ChatHandler was never given a way to resolve session keys to display names.

The current code tries to derive the name by string-splitting the session key, but session key formats vary by channel (`agent:name:telegram:direct:ID`, `agent:name:webchat:session:UUID`, `special:coder`) — there is no reliable string pattern to extract a display name.

---

## 3. Solution Options

### Option A: Add `set_agent_manager()` to ChatHandler (Recommended)

Add an `agent_mgr` dependency to ChatHandler, matching the pattern already used by ProjectHandler and CommandHandler.

**Changes:**

| File | Change |
|------|--------|
| `ui/handlers/chat_handler.py` | Add `self._agent_mgr = None` + `set_agent_manager(agent_mgr)` method |
| `ui/handlers/chat_handler.py` | `_build_awareness_prefix()`: use `self._agent_mgr.get_name(session_key)` instead of string splitting |
| `ui/window.py` | Wire `self._chat_handler.set_agent_manager(self._gateway_handler.agent_mgr)` alongside existing injections |

**Architecture compliance:**
- ✅ Handler receives dependency via setter (rule 3)
- ✅ Handler does not import another handler (rule 2)
- ✅ Window wires the connection (its responsibility per Section 8.6)
- ✅ Follows exact pattern of `ProjectHandler.set_agent_manager()` and `CommandHandler.set_agent_manager()`

**Fallback:** When `_agent_mgr` is None (pre-connect, tests), fall back to the last segment of the session key split on both `/` and `:`. This preserves current behavior as degradation path.

### Option B: Add `get_agent_name(session_key)` to ProjectHandler

ChatHandler already has `_project_handler`. Add a passthrough method that delegates to `_agent_mgr.get_name()`.

**Problem:** This routes ChatHandler's name resolution through ProjectHandler, creating a cross-handler dependency that violates the spirit of rule 2 even if technically using a method call. ProjectHandler's responsibility is project lifecycle, not agent name resolution.

**Verdict:** Architecturally weaker. Rejected.

### Option C: Add a callback-based name resolver

Window wires a `get_agent_name(session_key) -> str` callback into ChatHandler.

**Problem:** Overengineered for what is a simple data lookup. AgentManager is a pure data model — no reason to abstract it behind a callback. This would also be the only handler that uses a callback for a data dependency instead of a direct reference.

**Verdict:** Overengineered. Rejected.

---

## 4. Implementation Plan (Option A)

### Checkpoint 1: Add `agent_mgr` to ChatHandler

**File:** `ui/handlers/chat_handler.py`

```python
# In __init__():
self._agent_mgr = None  # injected via set_agent_manager() after gateway connect

# New method:
def set_agent_manager(self, agent_mgr) -> None:
    """Inject the live AgentManager after gateway connect. Called by window.py."""
    self._agent_mgr = agent_mgr

# Helper:
def _get_agent_display_name(self, session_key: str) -> str:
    """Resolve session_key to a display name. Falls back to last segment."""
    if self._agent_mgr:
        name = self._agent_mgr.get_name(session_key)
        if name:
            return name
    # Fallback: last meaningful segment
    return session_key.split("/")[-1].split(":")[-1]
```

### Checkpoint 2: Use `_get_agent_display_name()` in fan-out

Replace all `member.split("/")[-1].split(":")[-1]` calls with `self._get_agent_display_name(member)`.

Two locations in `on_send()`:
- Solo target path (~line 337)
- Group broadcast path (~line 355)

### Checkpoint 3: Wire in window.py

**File:** `ui/window.py`

Add alongside existing `set_agent_manager` calls (around line 994-996):

```python
self._chat_handler.set_agent_manager(self._gateway_handler.agent_mgr)
```

### Checkpoint 4: Update ARCHITECTURE.md

| Section | Update |
|---------|--------|
| 3.14 ChatHandler Public API | Add `set_agent_manager(agent_mgr)` |

---

## 5. Testing

| Test | What It Verifies |
|------|-----------------|
| `test_chat_handler.py::test_display_name_from_agent_mgr` | With agent_mgr set, resolves correctly |
| `test_chat_handler.py::test_display_name_fallback` | Without agent_mgr, falls back to last segment |
| `test_chat_handler.py::test_fan_out_uses_display_name` | Awareness prefix uses real name |

---

## 6. Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Agent mgr not set when awareness fires | Low — same timing as other handlers | Fallback to string split |
| Name is empty string in AgentManager | Medium — on first connect, names populate asynchronously | Fallback checks for empty string |
| Tests break | Low — same pattern as other handler injections | Tests create handler without agent_mgr, fallback path exercised |

---

*Upon approval, implementation follows the checkpoint discipline.*
