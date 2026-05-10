# ADVERSARIAL DEBUG REPORT — crabCakes Identity Override Bug

> **Status: FIXED** — Verified in code as of 2026-05-09
> - ✅ BUG #1 (CRITICAL): `_build_awareness_prefix()` is now gateway-only — returns raw `build_awareness_block()`, no `compose_system_prompt()` call
> - ✅ BUG #2 (HIGH): Group broadcast now routes special agents through `AgentRuntimeHandler.send_to_special_agent()`, not `gw.send_message()`
> - ❌ BUG #3 (HIGH): `{{AGENT_NAME}}` still comes from gateway snapshot, not configured identity
> - ❌ BUG #4 (MEDIUM): `[System Instructions]` / `[User Message]` delimiters still present
> - ❌ BUG #5 (MEDIUM): `is_project_onboarded()` check still applies onboarding template to all agents

**Date:** 2026-04-26  
**Investigator:** QTR  
**Status:** Report only — no code changes made

---

## Executive Summary

When a user opens a project tab and sends a message, gateway agents (QTR, Qaster) receive a composed system prompt as **user message content** rather than through the gateway's proper system prompt mechanism. The `[System Instructions]` wrapper is a fiction — the gateway has no `systemPrompt` field in its `chat.send` protocol. The result is identity-bearing text in the message body that can override or conflict with the agent's configured identity.

The PROPOSAL is explicit (`docs/PROPOSAL-system-prompt-library.md`): *"Gateway Agents (Qaster, QTR) — No system prompt — just raw awareness data."* The implementation does the opposite.

---

## BUG #[1]
**Severity:** CRITICAL

**Assumption violated:** Gateway agents receive only raw project awareness data as message content — no system prompt templates are applied to them.

**Attack vector:** `chat_handler.py` `_build_awareness_prefix()` (line 627) calls `compose_system_prompt()` — which loads and assembles system prompt templates from `prompts/system/` — then sends the result as **plain text** prepended to the user message. The gateway has no `systemPrompt` field in its `chat.send` API (`gateway/client.py` `send_message` only sends `message: text`). The `[System Instructions]` block is therefore **user message content**, not a protocol-level system prompt.

**Reproduction:**
1. Open any project tab in crabCakes
2. Send any message — e.g., "hello"
3. Observe that the message sent is: `"[System Instructions]\nYou are {{AGENT_NAME}}, a project team member.\n\n[User Message]\n\nhello"`
4. For QTR's session, `{{AGENT_NAME}}` resolves to "QTR" (from `AgentManager.get_name()`)
5. Result: `"[System Instructions]\nYou are QTR, a project team member.\n\n[User Message]\n\nhello"`

**Root cause:** `prompt_loader.py` `compose_system_prompt()` assembles **system prompt text** (identity declarations, behavioral guidelines) by design. The PROPOSAL explicitly states gateway agents should get no system prompt. `_build_awareness_prefix()` violates this by using `compose_system_prompt()` and sending the result as user message content.

**Fix:** `_build_awareness_prefix()` must NOT call `compose_system_prompt()` for gateway agents. For gateway agents, send only raw awareness data. The `compose_system_prompt()` → `prompts/system/` pipeline is correct for **local special agents** (Coder, Debugger) only.

---

## BUG #[2]
**Severity:** HIGH

**Assumption violated:** The project onboarding template (`prompts/system/project-onboarding.md`) is loaded only for the special agent being onboarded (Coder), not for every gateway agent in an unonboarded project.

**Attack vector:** `prompt_loader.py` `compose_system_prompt()` loads `project-onboarding.md` whenever `project_path` is set AND `is_project_onboarded(project_path)` returns `False`. For any freshly created project (skeleton manifest + empty context.md), this is always `False`. The onboarding template is then concatenated into the awareness prefix for **every gateway agent** that is a project member.

The onboarding template declares:
```
You are {{AGENT_NAME}}, a project team member.
[interview questions]
```

If `{{AGENT_NAME}}` resolves to "Qaster" instead of the correct agent's name, every gateway agent gets "You are Qaster" in their message content.

**Root cause:** `is_project_onboarded()` is a project-level check, but the onboarding template is an **agent-specific** template. The loading logic in `compose_system_prompt()` does not distinguish gateway agents from special agents.

**Fix:** Gate the onboarding template on `agent_role == "coder"`, not on `is_project_onboarded()` alone. Or move the decision to `_build_awareness_prefix()` which already knows whether the target is a special agent.

---

## BUG #[3]
**Severity:** HIGH

**Assumption violated:** `{{AGENT_NAME}}` always resolves to the correct agent's display name from the AgentManager. If `get_name()` returns `""` (session not yet registered), the fallback is the last segment of the session key — which for QTR is `"7478874934"`, NOT `"QTR"`.

**Attack vector:** `get_agent_display_name()` in `chat_handler.py` calls `AgentManager.get_name(session_key)`. `AgentManager.register()` only writes to `_agent_names` if `session_key not in self._agent_names`. If a session key is registered with **the wrong name** (gateway snapshot has incorrect mapping), every subsequent awareness prefix carries the wrong identity.

Additionally, the name mapping in `gateway_handler.py` `on_connected()` is:
```python
name = agent.get("name") or agent_id   # "Qaster" if gateway reports name="Qaster"
self._agent_mgr.register(session_key, name)
```
If the gateway's snapshot reports the wrong name for a session key, it poisons every awareness prefix permanently.

**Root cause:** The `{{AGENT_NAME}}` for gateway agents comes from the gateway snapshot's name field, not from the agent's configured identity (SOUL.md/IDENTITY.md). There is no re-validation.

**Fix:** The `{{AGENT_NAME}}` for gateway agents should come from the agent's configured identity, not from the gateway snapshot. Or, the awareness prefix for gateway agents should not include identity declarations at all (per BUG #1).

---

## BUG #[4]
**Severity:** MEDIUM

**Assumption violated:** The `[System Instructions]` wrapper is a recognized gateway protocol mechanism that causes the gateway to treat the wrapped content as a system prompt override.

**Attack vector:** There is **no such mechanism**. The gateway `chat.send` protocol (`gateway/client.py` `send_message`) has no `systemPrompt` field. The `[System Instructions]` block is stripped of its wrapper by the gateway and delivered as plain user text to the agent's session. The wrapper is cosmetic — it has no effect on the gateway's behavior.

**Root cause:** `_build_awareness_prefix()` invents a protocol convention (`[System Instructions]` / `[User Message]`) that doesn't exist in the gateway. The PROPOSAL says "raw awareness data prefixed to first message" — there is no instruction/wrapper concept in that design.

**Fix:** Remove the `[System Instructions]` and `[User Message]` delimiters. Send only the raw awareness text as a plain prefix. If guidance is needed, use a neutral marker like `## Project Context\n` — not a system-instruction-like wrapper.

---

## BUG #[5]
**Severity:** MEDIUM

**Assumption violated:** `is_project_onboarded()` accurately detects whether a project has completed onboarding, so the onboarding template is only loaded for projects that genuinely need it.

**Attack vector:** `is_project_onboarded()` returns `False` for any project whose manifest has only section headers (the initial state of every new project created by `generate_project_skeleton()`) AND whose context.md is empty. Any new project will trigger the onboarding template for every gateway agent on the very first message sent.

**Root cause:** `is_project_onboarded()` is too permissive — a project with a skeleton manifest is correctly considered "not onboarded," but the onboarding template should not blanket-apply to all gateway agents. The template is designed for onboarding the Coder special agent, not for informing gateway agents about a new project.

**Fix:** Gate the onboarding template on `agent_role == "coder"`, not on `is_project_onboarded()` alone.

---

## Root Cause Chain

```
User opens project tab, sends message
  │
  ├─► _show_and_send() detects project: prefix
  │     │
  │     ├─► _build_awareness_prefix(project_name, agent_display)
  │     │     │
  │     │     ├─► AgentManager.get_name(session_key) ──► "QTR" (or wrong name per BUG #3)
  │     │     │
  │     │     └─► compose_system_prompt(
  │     │            agent_name="QTR",        ← from AgentManager
  │     │            agent_role="",           ← empty for gateway agents
  │     │            project_path=...,
  │     │            project_awareness=...,
  │     │            review_mode=...)
  │     │           │
  │     │           ├─► default.md loaded    ← "You are {{AGENT_NAME}}, a project team member."
  │     │           ├─► project-awareness.md loaded
  │     │           └─► project-onboarding.md loaded (is_project_onboarded=False) ← BUG #2+#5
  │     │               "You are {{AGENT_NAME}}, a project team member.
  │     │               [interview questions]"
  │     │
  │     └─► Returns: "[System Instructions]\n{{composed_prompt}}\n\n[User Message]\n"
  │           │
  │           └─► gw.send_message(session_key,
  │                 "[System Instructions]\nYou are QTR, a project team member.\n...\n\nUser Message\n\nhello")
  │              │
  │              └─► Gateway delivers as USER MESSAGE CONTENT ──► BUG #1
  │                   No system prompt field exists in chat.send
  │
  └─► QTR receives: "You are QTR, a project team member.\n...\n\nhello"
        as user message content (NOT as system prompt)
```

The identity override occurs because the system prompt template `default.md` declares `You are {{AGENT_NAME}}, a project team member` as **user message content**. The LLM receives QTR's system prompt (`You are QTR`) AND the message content (`You are QTR, a project team member`). If `{{AGENT_NAME}}` resolves to "Qaster" (wrong name mapping per BUG #3), the message content says "You are Qaster" while the system prompt says "You are QTR" — creating the override effect.

---

## Key Files Involved

| File | Role |
|------|------|
| `ui/handlers/chat_handler.py:606-634` | `_build_awareness_prefix()` — builds the awareness block, calls `compose_system_prompt()` |
| `ui/handlers/chat_handler.py:597-605` | `_get_agent_display_name()` — resolves agent name from AgentManager |
| `utils/prompt_loader.py:61-108` | `compose_system_prompt()` — loads templates, assembles system prompt |
| `utils/prompt_loader.py:30-46` | `fill_template()` — replaces `{{VARIABLES}}` |
| `utils/project_awareness.py:242-257` | `is_project_onboarded()` — project onboarding state check |
| `prompts/system/default.md` | Base template — "You are {{AGENT_NAME}}, a project team member." |
| `prompts/system/project-onboarding.md` | Onboarding template — loaded when `is_project_onboarded=False` |
| `gateway/client.py:271-295` | `send_message()` — only sends `message: text`, no `systemPrompt` field |
| `gateway_handler.py:99-105` | `on_connected()` — populates AgentManager from gateway snapshot |
| `models/agents.py:19-23` | `AgentManager.register()` — maps session_key → name |

---

## Fix Direction

1. **For gateway agents** (QTR, Qaster, etc.): `_build_awareness_prefix()` must NOT call `compose_system_prompt()`. Send only raw awareness data (build via `build_awareness_dict()` directly) as a plain text prefix to the message.

2. **For special agents** (Coder, Debugger): `compose_system_prompt()` is correct — these agents have no other system prompt channel.

3. **Onboarding template**: Gate on `agent_role == "coder"`, not `is_project_onboarded()` alone.

4. **Remove delimiters**: Drop `[System Instructions]` and `[User Message]` wrappers. Use `## Project Context\n` or similar neutral marker if any prefix is needed.

5. **`{{AGENT_NAME}}` source**: For gateway agents, do not derive from AgentManager snapshot. Either use the agent's configured identity or omit the identity declaration entirely (per the PROPOSAL).
