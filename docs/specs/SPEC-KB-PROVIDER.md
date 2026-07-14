# SPEC: KB Provider — Per-Agent Fallback & Phase 2 Synthesis (v2)

**Date:** 2026-06-14 (revised)
**Author:** QTR (builder), directed by Qaster (supervisor)
**Parent proposal:** `docs/proposals/PROPOSAL-auxilium-three-tier-help-agent.md`
**Status:** ✅ IMPLEMENTED — kb_server (localhost:18790), KB_OUT_OF_SCOPE sentinel, ensure_kb_provider in providers_store, synthesis layer with fallback
**Depends on:** KB Provider Phase 1 (shipped), Legacy dead code cleanup (shipped commit `d04c6ee`)
**Target branch:** main

> **Architecture compliance:** All changes obey `docs/ARCHITECTURE.md` §2 (directory boundaries: `agent/` = no UI, `ui/handlers/` = business logic, `ui/views/` = view widgets only, `models/` = pure data). New fields on dataclasses are backward-compatible (default `None`). No new imports from `ui/` in `agent/`.

---

## 1. Overview

### Problem

The KB provider architecture (Phase 1) shipped with a fallback chain that never fires. The runtime checks `self._config.fallback_provider` (global `AgentConfig`), but:

1. `load_agent_config()` never reads `fallback_provider`/`fallback_model` from `agent.json` — the fields are always `None`.
2. Fallback is configured at the global level (`AgentConfig`), not per-agent. There's no way for Auxilium to have a fallback while Coder doesn't.
3. `SpecialAgentDef` has no fallback fields — agent YAML's `fallback_provider`/`fallback_model` are parsed by `_normalize_fallback_fields()` but never loaded into the dataclass or passed to the runtime.
4. `Conversation` has no fallback fields — the runtime can't track fallback state per-conversation.
5. `create_conversation()` doesn't accept or store fallback parameters.

Additionally, when the KB **does** return chunks, they're displayed as raw markdown. There's no LLM synthesis step (Phase 2 of the proposal) — the user sees concatenated KB chunks instead of a conversational answer.

### Solution

Two changes, in order:

**Change A — Per-agent fallback wiring:** Move fallback from global config to per-agent. Add fields to `SpecialAgentDef` and `Conversation`. Wire them through `create_conversation()` and `_get_runtime()` so Auxilium's YAML `fallback_provider: openrouter` actually reaches the runtime fallback chain.

**Change B — Phase 2 system prompt:** Update `prompts/system/auxilium.md` so that when a real LLM is the fallback provider, it receives instructions to synthesize conversational answers grounded in KB content (not raw chunks). The KB server's formatted chunks become context for the LLM, not the final user-facing response.

### Scope

| In | Out |
|----|-----|
| `SpecialAgentDef` fallback fields | Agent builder UI dropdown (future) |
| `Conversation` fallback fields | First-run wizard (separate SPEC) |
| `create_conversation()` fallback params | KB content expansion (Tier 2) |
| `_get_runtime()` per-agent config | Multi-agent fallback chains |
| `load_agent_config()` fallback parsing | Streaming synthesis |
| `agent.json` fallback fields | |
| Runtime fallback chain uses per-agent fallback | |
| System prompt Phase 2 update | |
| `_normalize_fallback_fields` cleanup | |

---

## 2. Changes by File

### 2.1 `agent/special_agents.py` — Add fallback fields to SpecialAgentDef

**Current state (verified):**

```python
@dataclass
class SpecialAgentDef:
    conv_id_prefix: str
    display_name: str
    role: str
    emoji: str
    color: str
    tools: list[str]
    can_write: bool
    llm_name: str | None = None
    api_key: str | None = None
    app_title: str | None = None
    self_improvement: dict = field(default_factory=dict)
    mcp_servers: list[str] = field(default_factory=list)
    auto_open: bool = False
    auto_add_to_projects: bool = False
```

**Change:** Add two optional fields:

```python
    fallback_provider: str | None = None   # KB fallback provider name (e.g. "openrouter")
    fallback_model: str | None = None      # KB fallback model (e.g. "openrouter/owl-alpha")
```

**`_load_registry()` must read them from the parsed YAML dict:**

Current (line 129):
```python
            llm_name=agent_def.get("llm_name"),
```

After:
```python
            llm_name=agent_def.get("llm_name"),
            fallback_provider=agent_def.get("fallback_provider"),
            fallback_model=agent_def.get("fallback_model"),
```

**Risk:** LOW. Optional fields with `None` defaults. All existing callers that construct `SpecialAgentDef` without these fields continue to work.

---

### 2.2 `models/conversation.py` — Add fallback fields to Conversation

**Current state (verified):**

```python
@dataclass
class Conversation:
    agent_name: str
    project_path: str | None = None
    allowed_tools: list[str] | None = None
    mcp_servers: list[str] = field(default_factory=list)
    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    model: str = ""
    api_key: str | None = None
    si_enforcement: bool | None = None
    app_title: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    total_tokens: int = 0
    total_cost: float = 0.0
    step_count: int = 0
```

**Change:** Add two optional fields:

```python
    fallback_provider: str | None = None   # KB fallback provider (from agent def)
    fallback_model: str | None = None      # KB fallback model (from agent def)
```

**Risk:** LOW. Optional fields with `None` defaults. `to_api_messages()` and all other methods are unchanged. The fields are read-only context for the runtime fallback chain.

---

### 2.3 `agent/runtime.py` — Two changes

#### 2.3a `create_conversation()` accepts fallback params

**Current signature (verified, line 934):**

```python
def create_conversation(
    self,
    agent_name: str,
    session_key: str,
    project_path: str | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    mcp_servers: list[str] = None,
    agent_role: str = "",
    si_enforcement: bool | None = None,
    api_key: str | None = None,
    app_title: str = "",
) -> str:
```

**After:**

```python
def create_conversation(
    self,
    agent_name: str,
    session_key: str,
    project_path: str | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    mcp_servers: list[str] = None,
    agent_role: str = "",
    si_enforcement: bool | None = None,
    api_key: str | None = None,
    app_title: str = "",
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
) -> str:
```

**Conversation construction (verified, line 974):**

Current:
```python
        conv = Conversation(
            agent_name=agent_name,
            project_path=project_path,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers if mcp_servers else [],
            model=model,
            system_prompt=system_prompt,
            si_enforcement=si_enforcement,
            api_key=api_key,
            app_title=app_title,
        )
```

After:
```python
        conv = Conversation(
            agent_name=agent_name,
            project_path=project_path,
            allowed_tools=allowed_tools,
            mcp_servers=mcp_servers if mcp_servers else [],
            model=model,
            system_prompt=system_prompt,
            si_enforcement=si_enforcement,
            api_key=api_key,
            app_title=app_title,
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
        )
```

#### 2.3b Fallback chain reads per-conversation fallback

**Current fallback chain (verified, line 1144-1180):**

```python
                    if (
                        text_content == KB_OUT_OF_SCOPE
                        and self._config.fallback_provider
                        and not getattr(conv, "_fallback_attempted", False)
                    ):
                        conv._fallback_attempted = True
                        ...
                        fallback_model = self._config.fallback_model or f"{self._config.fallback_provider}/{self._config.default_model}"
                        conv.model = fallback_model
                        try:
                            fb_response = self._call_llm(session_key, messages, tools)
                            ...
```

**After:** Replace `self._config.fallback_provider` with `conv.fallback_provider`:

```python
                    if (
                        text_content == KB_OUT_OF_SCOPE
                        and conv.fallback_provider
                        and not getattr(conv, "_fallback_attempted", False)
                    ):
                        conv._fallback_attempted = True
                        logger.info(
                            "[tool-loop] sk=%s KB_OUT_OF_SCOPE — retrying with fallback provider %s",
                            session_key, conv.fallback_provider,
                        )
                        original_model = conv.model
                        fallback_model = conv.fallback_model or conv.fallback_provider
                        conv.model = fallback_model
                        try:
                            fb_response = self._call_llm(session_key, messages, tools)
                            fb_provider = fallback_model.split("/")[0] if "/" in fallback_model else fallback_model
                            fb_text = _extract_text_content(fb_response, fb_provider)
                            fb_tool_calls = _extract_tool_calls(fb_response, fb_provider)
                            text_content = fb_text
                            tool_calls_raw = fb_tool_calls
                            fb_prompt, fb_comp = _extract_usage(fb_response, fb_provider)
                            fb_cost = _cost_for_model(fallback_model, fb_prompt, fb_comp)
                            conv.record_usage(fb_prompt + fb_comp, fb_cost)
                            self._dispatch(self._on_token_usage, session_key, fb_prompt + fb_comp, fb_cost)
                        except Exception as e:
                            logger.warning("[tool-loop] sk=%s fallback call failed: %s", session_key, e)
                        finally:
                            conv.model = original_model
```

**Key difference:** `self._config.fallback_provider` → `conv.fallback_provider`. This makes fallback per-conversation (per-agent) instead of global.

**Also:** `fallback_model` resolution simplifies. The agent YAML stores the full model string (e.g. `"openrouter/owl-alpha"`), so the fallback is `conv.fallback_model` directly. No derivation from provider name needed.

**Risk:** MEDIUM. This changes the fallback chain's data source. Must verify that `conv.fallback_provider` is populated for conversations that need it and `None` for conversations that don't.

---

### 2.4 `ui/handlers/agent_runtime_handler.py` — Pass fallback from agent def to conversation

**Current `send_to_special_agent()` (verified, line 404):**

```python
        if rt.get_conversation(session_key) is None:
            rt.create_conversation(
                agent_name=agent_def.display_name,
                session_key=session_key,
                project_path=project_path,
                model=agent_model,
                allowed_tools=agent_def.tools,
                mcp_servers=agent_def.mcp_servers,
                agent_role=agent_def.role,
                si_enforcement=si_enforcement,
                api_key=agent_def.api_key,
                app_title=agent_def.app_title,
            )
```

**After:** Add fallback fields:

```python
        if rt.get_conversation(session_key) is None:
            rt.create_conversation(
                agent_name=agent_def.display_name,
                session_key=session_key,
                project_path=project_path,
                model=agent_model,
                allowed_tools=agent_def.tools,
                mcp_servers=agent_def.mcp_servers,
                agent_role=agent_def.role,
                si_enforcement=si_enforcement,
                api_key=agent_def.api_key,
                app_title=agent_def.app_title,
                fallback_provider=agent_def.fallback_provider,
                fallback_model=agent_def.fallback_model,
            )
```

Also update the "sync existing conversation" block (verified, line 420) to update fallback fields on edit:

```python
            if conv is not None:
                if agent_def.api_key:
                    conv.api_key = agent_def.api_key
                if agent_model:
                    conv.model = agent_model
                if agent_def.app_title:
                    conv.app_title = agent_def.app_title
                # Sync fallback config (in case agent was edited)
                conv.fallback_provider = agent_def.fallback_provider
                conv.fallback_model = agent_def.fallback_model
```

**Risk:** LOW. `getattr(agent_def, 'fallback_provider', None)` returns `None` for agents without the field. But since we're adding the field to `SpecialAgentDef` in §2.1, all special agents will have it.

---

### 2.5 `agent/config.py` — Parse fallback from agent.json + clean up global fields

**Current state (verified):**

`AgentConfig` has `fallback_provider` and `fallback_model` fields (line 81-82) but `load_agent_config()` (line 225-240) never reads them from `agent.json`. They're always `None`.

**Change:** Two options:

**Option A (recommended): Remove the global fallback fields entirely.** Fallback is per-agent now. Remove `fallback_provider` and `fallback_model` from `AgentConfig`. Remove the `self._config.fallback_provider` reference in the runtime (already replaced by `conv.fallback_provider` in §2.3b).

**Option B: Keep for backward compat.** Parse them from `agent.json` as a global default. Per-agent fallback overrides global. This is more complex and there's no backward compat to maintain.

**Recommendation:** Option A. Remove the fields. The fallback chain now reads from `conv.fallback_provider`. The global fields are dead code.

Lines to change in `agent/config.py`:
- Remove lines 81-82 (the two `fallback_*` fields from `AgentConfig`)
- No change needed to `load_agent_config()` body (it never populated them anyway)

Lines to change in `agent/runtime.py`:
- None beyond §2.3b (already replaced `self._config.fallback_provider` with `conv.fallback_provider`)

**Risk:** LOW. The fields were never populated, so removing them changes nothing at runtime.

---

### 2.6 `utils/agent_defs.py` — Clean up `_normalize_fallback_fields`

**Current state (verified, line 33):**

```python
def _normalize_fallback_fields(data: dict) -> None:
    """Ensure fallback_provider and fallback_model keys exist in the agent def dict."""
    data.setdefault("fallback_provider", data.get("fallback_provider"))
    data.setdefault("fallback_model", data.get("fallback_model"))
```

This is a no-op — `setdefault` with the same value that `get` returns. But it does ensure the keys exist (defaulting to `None` if absent, which is what `setdefault` does when the key is missing).

**Change:** Rewrite to be explicit:

```python
def _normalize_fallback_fields(data: dict) -> None:
    """Ensure fallback_provider and fallback_model keys exist in the agent def dict.

    Reads from YAML/JSON if present, defaults to None if absent.
    Called after parsing every agent definition file.
    """
    if "fallback_provider" not in data:
        data["fallback_provider"] = None
    if "fallback_model" not in data:
        data["fallback_model"] = None
```

**Risk:** NONE. Same behavior, clearer code. Empty strings from YAML (e.g. `fallback_provider: ''`) are preserved — the runtime checks truthiness (`conv.fallback_provider` is truthy for non-empty strings, falsy for `None` and `""`).

---

### 2.7 `prompts/system/auxilium.md` — Phase 2 system prompt update

**Current state:** The system prompt already mentions KB lookup and the `[KB Context]` pattern. But when the fallback LLM is invoked, it receives the full message history — not KB chunks specifically.

When the fallback fires, the runtime calls `_call_llm` with the **same messages** (system + history + user). The KB server returned `[KB_OUT_OF_SCOPE]` as its response, which means the LLM never sees KB chunks. The LLM gets the raw user question with no KB grounding.

**This is the core Phase 2 gap.** The fallback LLM needs KB context to synthesize a good answer.

**Fix:** When the fallback chain fires, inject the KB chunks into the messages before calling the fallback LLM. Two implementation approaches:

#### Approach 1 (recommended): KB server returns chunks + sentinel

Change the KB server to return BOTH the chunks AND the sentinel:

```python
# When chunks are found but the question is out-of-scope:
content = _format_chunks(chunks)
# Append sentinel so runtime knows to fall back
content_with_sentinel = content + "\n\n" + KB_OUT_OF_SCOPE
```

But this changes the KB server's contract and the sentinel check. Not ideal.

#### Approach 2 (recommended): Two-step KB lookup in the runtime

Before calling the KB server (or when it returns chunks), do a direct `kb_lookup()` call in the runtime. If chunks are found, inject them as context for the fallback LLM.

This means the runtime imports `kb_lookup` directly:

```python
# In _run_loop, before _call_llm:
kb_context = None
if conv.fallback_provider:
    # This conversation has a fallback — pre-fetch KB chunks for synthesis
    try:
        from agent.kb_lookup import kb_lookup
        chunks = kb_lookup(text, top_k=5, min_score=0.35)
        if chunks:
            kb_context = _format_chunks_for_llm(chunks)
    except Exception:
        pass  # No KB context — fallback LLM answers without grounding

# ... call _call_llm with the KB server ...

# When fallback fires:
if text_content == KB_OUT_OF_SCOPE and conv.fallback_provider ...:
    # Inject KB context into messages for the fallback LLM
    if kb_context:
        # Prepend KB context to the user message
        messages_with_context = list(messages)
        # Find the last user message and prepend KB context
        for i in range(len(messages_with_context) - 1, -1, -1):
            if messages_with_context[i].get("role") == "user":
                messages_with_context[i] = {
                    "role": "user",
                    "content": f"{kb_context}\n\nUser question: {messages_with_context[i]['content']}",
                }
                break
        messages = messages_with_context  # Use augmented messages for fallback call
    
    fb_response = self._call_llm(session_key, messages, tools)
```

**System prompt addition** — add to `prompts/system/auxilium.md`:

```markdown
## Phase 2 — LLM Synthesis Mode

When a real LLM provider is configured as your fallback, you operate in synthesis mode:

1. The KB lookup runs first. If it finds relevant chunks, they're injected as context.
2. Your job is to **synthesize** the KB chunks into a conversational answer — not dump them raw.
3. Ground your answer in the chunks. Quote specific sections when relevant.
4. If the chunks don't fully answer the question, supplement with your general knowledge and say so.
5. Keep your tone friendly and concise. Don't preface with "Based on the knowledge base..." — just answer naturally.
6. If no KB chunks were found (empty context), answer from your general reasoning. Say "I don't have specific docs on this" if relevant.
```

**Risk:** MEDIUM. The runtime now imports `kb_lookup` directly (previously only the KB server imported it). This is architectural — `agent/kb_lookup.py` is in `agent/` which is allowed. No circular imports (`kb_lookup` imports only `numpy`, `sentence_transformers`, stdlib).

**`_format_chunks_for_llm` helper** — new function in `agent/runtime.py`:

```python
def _format_chunks_for_llm(chunks: list) -> str:
    """Format KB chunks as context for LLM synthesis."""
    if not chunks:
        return ""
    parts = ["[KB Context — relevant documentation chunks:]"]
    for chunk in chunks:
        parts.append(f"\nSource: {chunk.source} :: {chunk.section}\n{chunk.text}\n")
    parts.append("[End KB Context]\n")
    return "\n".join(parts)
```

---

### 2.8 `agent.json` — Optional global fallback defaults

**Change:** Add optional `fallback_provider` and `fallback_model` keys to the default `agent.json` template (written by `_create_default_config`). These serve as global defaults — per-agent fallback overrides them.

```python
# In _create_default_config:
example = {
    ...
    "fallback_provider": None,   # global default; per-agent override in agents/*.yaml
    "fallback_model": None,
}
```

**In `load_agent_config()`:** Parse them:

```python
    return AgentConfig(
        ...
        fallback_provider=raw.get("fallback_provider"),
        fallback_model=raw.get("fallback_model"),
    )
```

Then `create_conversation()` can fall back to config-level defaults if the agent def doesn't specify:

```python
        fallback_provider=fallback_provider or self._config.fallback_provider,
        fallback_model=fallback_model or self._config.fallback_model,
```

**Decision point:** Keep global fallback as a default, or remove entirely (Option A from §2.5)?

**Recommendation:** Keep as global default. It's one line in `load_agent_config()` and provides a sensible default for agents that don't specify their own.

---

## 3. Data Flow

### Current flow (broken):

```
User asks Auxilium "How do I configure providers?"
    │
    ├─ _run_loop calls _call_llm with model "local-kb/local-kb"
    │   └─ KB server returns formatted chunks (score > 0.55)
    │       └─ text_content = "Based on the CrabCakes knowledge base:\n\n---\n..."
    │           └─ Not KB_OUT_OF_SCOPE → dispatched as final response
    │               └─ User sees raw markdown chunks
    │
    └─ OR: KB server returns [KB_OUT_OF_SCOPE] (score < 0.55)
        └─ Runtime checks self._config.fallback_provider
            └─ Always None → fallback never fires
                └─ User sees [KB_OUT_OF_SCOPE]
```

### After Change A (per-agent fallback):

```
User asks Auxilium "How do I configure providers?"
    │
    ├─ _run_loop calls _call_llm with model "local-kb/local-kb"
    │   └─ KB server returns chunks (score > 0.55)
    │       └─ User sees formatted chunks (unchanged for now)
    │
    └─ OR: KB server returns [KB_OUT_OF_SCOPE]
        └─ Runtime checks conv.fallback_provider (was None, now "openrouter")
            └─ conv.fallback_provider = "openrouter" → fallback fires!
                └─ conv.model = "openrouter/owl-alpha"
                    └─ _call_llm retries with OpenRouter
                        └─ User sees LLM response
```

### After Change B (Phase 2 synthesis):

```
User asks Auxilium "How do I configure providers?"
    │
    ├─ kb_lookup() runs directly in runtime → gets chunks
    │   └─ Chunks stored as kb_context for later use
    │
    ├─ _run_loop calls _call_llm with model "local-kb/local-kb"
    │   └─ KB server returns chunks (score > 0.55)
    │       └─ User sees formatted chunks (KB-only mode — no synthesis)
    │
    └─ OR: KB server returns [KB_OUT_OF_SCOPE]
        └─ Runtime checks conv.fallback_provider = "openrouter"
            └─ Inject kb_context into messages
                └─ _call_llm retries with OpenRouter + KB context
                    └─ LLM synthesizes conversational answer grounded in chunks
                        └─ User sees friendly answer, not raw chunks
```

**Note:** When the KB server DOES return chunks (high confidence), the user still sees raw chunks — not synthesized. Full synthesis (where even high-confidence KB answers go through the LLM) would require changing the KB server's response format or the runtime's provider routing. That's a larger change and should be a separate spec if desired.

---

## 4. File Change Summary

| File | Change Type | Lines Changed | Risk |
|------|-------------|---------------|------|
| `agent/special_agents.py` | Add 2 fields + 2 lines in `_load_registry` | ~6 | LOW |
| `models/conversation.py` | Add 2 fields | ~2 | LOW |
| `agent/runtime.py` | `create_conversation` params + fallback chain + kb_lookup import + `_format_chunks_for_llm` | ~35 | MEDIUM |
| `ui/handlers/agent_runtime_handler.py` | Pass fallback params + sync on edit | ~6 | LOW |
| `agent/config.py` | Parse fallback in `load_agent_config` + add to `_create_default_config` | ~6 | LOW |
| `utils/agent_defs.py` | Rewrite `_normalize_fallback_fields` | ~4 | NONE |
| `prompts/system/auxilium.md` | Add Phase 2 synthesis section | ~15 | NONE |

**Files NOT changed:**
- `agent/kb_server.py` — KB server behavior unchanged. Still returns chunks or `[KB_OUT_OF_SCOPE]`.
- `agent/kb_lookup.py` — Lookup module unchanged. Already has the right interface.
- `ui/views/agent_builder.py` — Agent builder UI dropdown is future work (not in this spec).
- `ui/handlers/auxilium_wizard_handler.py` — First-run wizard is separate SPEC.

---

## 5. Implementation Order

1. **§2.1** `SpecialAgentDef` fallback fields — dataclass + `_load_registry`
2. **§2.2** `Conversation` fallback fields — dataclass only
3. **§2.3a** `create_conversation()` accepts + passes fallback params
4. **§2.4** `send_to_special_agent()` passes fallback from agent def
5. **§2.5** `AgentConfig` — keep global fallback as defaults, parse from agent.json
6. **§2.6** `_normalize_fallback_fields` cleanup
7. **§2.3b** Runtime fallback chain reads `conv.fallback_provider`
8. **Test:** Verify fallback fires with per-agent config. Set `fallback_provider: openrouter` in auxilium.yaml, ask out-of-scope question, verify OpenRouter is called.
9. **§2.7** Phase 2 synthesis: `kb_lookup` pre-fetch + context injection + system prompt update
10. **Test:** Verify synthesis. Ask out-of-scope question, verify LLM response references KB content.

---

## 6. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-1 | `SpecialAgentDef` has `fallback_provider` and `fallback_model` fields | `python3 -c "from agent.special_agents import SpecialAgentDef; import dataclasses; print([f.name for f in dataclasses.fields(SpecialAgentDef)])"` includes both |
| AC-2 | `Conversation` has `fallback_provider` and `fallback_model` fields | Same check for `Conversation` |
| AC-3 | `create_conversation()` accepts `fallback_provider`/`fallback_model` params | `inspect.signature` shows both params with `None` defaults |
| AC-4 | `send_to_special_agent()` passes fallback from agent def | `grep "fallback_provider" ui/handlers/agent_runtime_handler.py` shows it in create_conversation call |
| AC-5 | Runtime fallback chain reads `conv.fallback_provider` (not `self._config.fallback_provider`) | `grep "conv.fallback_provider" agent/runtime.py` shows the fallback chain |
| AC-6 | Auxilium YAML with `fallback_provider: openrouter` triggers fallback on `[KB_OUT_OF_SCOPE]` | Integration test: set fallback, ask "What is quantum physics?", verify OpenRouter is called |
| AC-7 | Existing 167 tests still pass | `pytest tests/test_kb_* tests/test_runtime_* tests/test_agent_* tests/test_special_* tests/test_project_* tests/test_bug_*` |
| AC-8 | Phase 2 synthesis: fallback LLM receives KB context | When fallback fires, LLM message includes `[KB Context]` block |
| AC-9 | System prompt has Phase 2 synthesis instructions | `grep "Synthesis Mode" prompts/system/auxilium.md` |

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Agent has no `fallback_provider` in YAML | `conv.fallback_provider` = `None`. KB_OUT_OF_SCOPE shown to user as-is. |
| Agent has `fallback_provider: ''` (empty string) | `conv.fallback_provider` = `""`. Falsy — same as `None`. KB_OUT_OF_SCOPE shown. |
| Fallback provider not in providers.yaml | `_call_llm` raises `RuntimeError("No provider configured for X")`. Caught by `except Exception` in fallback chain. User sees KB_OUT_OF_SCOPE. |
| Fallback provider returns error (401, 429) | `_call_llm` raises. Caught by `except Exception`. User sees KB_OUT_OF_SCOPE. |
| Fallback provider also returns KB_OUT_OF_SCOPE | One-shot guard (`_fallback_attempted`) prevents third call. User sees `[KB_OUT_OF_SCOPE]`. |
| `kb_lookup` fails (model not loaded) | `kb_context` = `None`. Fallback LLM answers without KB grounding. |
| User edits agent to remove fallback_provider | `send_to_special_agent` sync block sets `conv.fallback_provider = None`. Next message has no fallback. |
| Non-special agent (gateway agent) | `create_conversation` called with `fallback_provider=None`. No fallback. |
| Global `agent.json` has `fallback_provider: openrouter` and agent YAML has none | `create_conversation` uses `self._config.fallback_provider` as default. Agent inherits global. |
| Both global and per-agent fallback set | Per-agent wins (passed explicitly to `create_conversation`). |

---

## 8. ARCHITECTURE.md Updates Required

| Section | Update |
|---------|--------|
| §3.21q (kb_server) | Note that fallback is now per-agent, not global |
| Line 1323 (AgentConfig) | Remove `fallback_provider`/`fallback_model` from AgentConfig field list (moved to per-agent) |
| Conversation dataclass | Add `fallback_provider`/`fallback_model` to Conversation field list |
| SpecialAgentDef dataclass | Add `fallback_provider`/`fallback_model` to SpecialAgentDef field list |
| §3.21q.5a (kb_server.py) | Update description to note runtime now calls `kb_lookup` directly for synthesis context |

---

## 9. Discovery Notes

### Files read during discovery:

- **`agent/special_agents.py`**: `SpecialAgentDef` dataclass with 14 fields (no fallback fields). `_load_registry()` reads from parsed YAML dict at line 118-135. Fields are accessed via `agent_def.get("key")` on the raw dict before constructing the dataclass.
- **`models/conversation.py`**: `Conversation` dataclass with 14 fields (no fallback fields). No methods reference fallback. `_fallback_attempted` is a dynamic attribute set by the runtime, not a declared field.
- **`agent/runtime.py`**: `create_conversation()` at line 934, signature verified. `_run_loop()` at line 1054. Fallback chain at lines 1144-1180, reads `self._config.fallback_provider` (global). `_call_llm()` at line 1394. `_resolve_caller_key()` at line 1339 (simplified to only use `provider_cfg.caller`).
- **`agent/config.py`**: `AgentConfig` has `fallback_provider`/`fallback_model` fields (lines 81-82) but `load_agent_config()` never parses them from `agent.json` (line 225-240). `_create_default_config()` doesn't include them either.
- **`ui/handlers/agent_runtime_handler.py`**: `send_to_special_agent()` at line 360. `create_conversation` call at line 404. Sync block at line 420. `_get_runtime()` at line 321 mutates `config.default_provider` (safe — fresh config each call).
- **`utils/agent_defs.py`**: `_normalize_fallback_fields()` at line 33 — no-op `setdefault` pattern. Called after every agent file parse.
- **`agent/kb_server.py`**: Full file read. Returns chunks formatted as markdown or `[KB_OUT_OF_SCOPE]`. Confidence threshold 0.55. No changes needed.
- **`utils/providers_store.py`**: Full file read. `ensure_kb_provider()` seeds local-kb and patches Auxilium. No changes needed.
- **`prompts/system/auxilium.md`**: Full file read. Already mentions KB lookup and `[KB Context]` pattern but describes it as automatic injection which doesn't actually happen in the runtime. Needs Phase 2 synthesis section.
- **`~/.config/crabcakes/agents/auxilium.yaml`**: Has `fallback_provider: ''` and `fallback_model: ''` (empty strings, not set).

### Existing patterns copied:
- Per-agent field propagation follows the same pattern as `api_key`, `app_title`, `si_enforcement` — dataclass field → `_load_registry()` reads from dict → `send_to_special_agent()` passes to `create_conversation()` → stored on `Conversation` → runtime reads from `conv`.
- The sync-on-edit pattern at line 420 mirrors `api_key` and `model` sync.
