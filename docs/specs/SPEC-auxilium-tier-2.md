# SPEC: Auxilium Tier 2 — LLM Synthesis with KB Lookup

**Date:** 2026-06-15
**Author:** Qaster (supervisor)
**Status:** ✅ IMPLEMENTED — _inject_kb_context, _prepare_kb_synthesis, agent_role="helper" gate, kb_lookup on every message, KB context injection into primary LLM call
**Implements:** `PROPOSAL-auxilium-three-tier-help-agent.md` — Tier 2
**Depends on:**
- `docs/specs/SPEC-auxilium-tier-1.md` (Tier 1 — completed)
- `docs/specs/SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md` (upstream KB provider work)
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§3.6 (Composition root)**: `ui/handlers/agent_runtime_handler.py:_create_runtime_conversation()` owns conversation creation. `agent/runtime.py:_run_loop()` is the composition root for KB synthesis. No new composition points needed.
> - **§3.14 (Chat handler)**: `ui/handlers/agent_runtime_handler.py` is unchanged except for passing `agent_role` to `create_conversation()`.
> - **§8 (utils/ rule)**: `utils/prompt_loader.py` is unchanged. The synthesis instruction is already in `prompts/system/auxilium.md` — loaded for `agent_role == "helper"` at `utils/prompt_loader.py:207`.
> - **No dead code**: KB synthesis is additive. All existing `_run_loop` behavior (tool calls, fallback chain, enforcement) is preserved.
> - **Fail-soft KB**: any KB lookup failure returns `kb_context = None` and the LLM call proceeds normally.

---

## 0. Summary

| # | Symptom / Goal | Fix |
|---|----------------|-----|
| 1 | Auxilium with a configured LLM provider has no KB-backed answers today — `kb_lookup` only fires when `fallback_provider` is set (KB fallback path), and even then only after the primary returns `KB_OUT_OF_SCOPE`. | Extend `_run_loop()` to always run `kb_lookup` for auxilium (`agent_role == "helper"`) on every user message, inject KB context into the primary LLM call, and let the LLM synthesize an answer from the chunks. |
| 2 | No explicit synthesis instruction to the LLM beyond the Phase 1 system prompt paragraphs. | `prompts/system/auxilium.md` already has the full Phase 2 synthesis mode section (lines 73-85). No system prompt changes needed. |
| 3 | No `agent_role` field on `Conversation` dataclass — `_run_loop()` can't determine which agent is running to gate the synthesis behavior. | Add `agent_role: str = ""` field to `Conversation`. Pass it from `agent_runtime_handler.py:_create_runtime_conversation()` when creating the conversation. |
| 4 | Multi-turn synthesis not exercised. | Per design decision: run `kb_lookup` fresh on every user message (not cached from first exchange). Covers the "how do I configure on Windows?" follow-up case with the current question as the query. |
| 5 | `auxilium_synthesis.py` was proposed as a separate module. | Not needed. Option A (extend existing runtime) achieves the same result with ~15 lines of change in `_run_loop()` and no new module. |

---

## 1. Overview

### 1.1 Problem statement

Auxilium currently has no KB-backed answers when a real LLM provider is configured. The `kb_lookup` call exists and works (verified: 209 chunks indexed, query returns relevant results with score 0.72), but it only fires inside the KB fallback chain (when primary returns `KB_OUT_OF_SCOPE`). A user with a configured provider asking "how do I configure the gateway?" gets a generic answer — not one grounded in `knowledge/configuration.md`.

The goal of Tier 2: Auxilium answers factual "how do I…" questions with synthesized answers grounded in the KB, for every user message, not just when the KB fallback fires.

### 1.2 Solution summary

Extend `AgentRuntime._run_loop()` to always call `kb_lookup` for auxilium (`agent_role == "helper"`) on every user message, and inject the KB context into the primary LLM call. The synthesis is handled by the LLM following the instructions already in `prompts/system/auxilium.md:73-85`. No new module, no new timeout, no changes to `utils/prompt_loader.py`.

The synthesis layer is `prompts/system/auxilium.md` (already written) + the `kb_lookup` → `_format_chunks_for_llm` → message injection pipeline in `_run_loop()`.

### 1.3 Design decisions (confirmed with Captain)

| Decision | Answer |
|----------|--------|
| KB lookup runs on every message or cached? | Fresh on every message (not cached). Query is the current user message text. |
| Heuristic to detect factual vs casual? | No heuristic. Always run `kb_lookup`; LLM decides whether to use the chunks. |
| KB returns empty → what happens? | `kb_context = None`; `_call_llm` proceeds without KB context. LLM answers from general knowledge. Per `auxilium.md`: "Say 'I don't have specific docs on this' if relevant." |
| Synthesis layer location | Option A — extend `_run_loop()`. No `auxilium_synthesis.py`. |
| `compose_system_prompt()` changes? | None. `auxilium.md` is already loaded for `agent_role == "helper"`. Synthesis instructions are already in the template. |
| Timeout management | Use existing `_config.tool_timeout_seconds` (default 120s). `_call_llm` already enforces it. |
| Error handling | `kb_lookup` wrapped in try/except → `kb_context = None` on failure. `_call_llm` errors propagate to `_dispatch(self._on_error, ...)`. No new error handling needed. |

### 1.4 Scope

| In scope | Out of scope |
|---|---|
| Add `agent_role` field to `Conversation` dataclass | Adding KB synthesis to non-auxilium agents |
| Pass `agent_role` to `create_conversation()` from `_create_runtime_conversation()` | Adding a separate `auxilium_synthesis.py` module |
| Extend `_run_loop()` to always call `kb_lookup` for auxilium on every message | Changing `_call_llm` timeout (use existing 120s default) |
| Inject KB context into the primary `_call_llm` for auxilium | Changing `utils/prompt_loader.py` |
| Update `prompts/system/auxilium.md` synthesis section (already done — verify it's present) | Adding a KB context size limit or chunk count limit |
| Add `tests/test_auxilium_tier2.py` with 20-30 sample questions | Automating the 20-30 question verification (manual acceptable per Captain) |
| Update ARCHITECTURE.md | — |

### 1.5 Architecture principles (per `docs/ARCHITECTURE.md`)

- **§3.6**: `agent/runtime.py:_run_loop()` is the composition root for KB synthesis. `agent_runtime_handler.py:_create_runtime_conversation()` passes `agent_role`.
- **§8**: `utils/prompt_loader.py` is read-only for this spec. The synthesis instruction is already in `prompts/system/auxilium.md`.
- **Fail-soft KB**: `kb_lookup` failure is silent (`kb_context = None`), not fatal. LLM proceeds normally.
- **No new module**: Option A means `agent/auxilium_synthesis.py` is not created.

---

## 2. Changes by File

### 2.1 `models/conversation.py` — REVISED

**What changes:** Add `agent_role: str = ""` field to the `Conversation` dataclass.

**Discovery:** `Conversation` dataclass at `models/conversation.py:91-115`. Current fields confirmed: `agent_name, project_path, allowed_tools, mcp_servers, system_prompt, messages, model, api_key, si_enforcement, app_title, fallback_provider, fallback_model, created_at, total_tokens, total_cost, step_count`. `agent_role` is not present.

**New field (add after `agent_name`):**

```python
agent_name: str
agent_role: str = ""          # "helper" for Auxilium, "" for other agents
```

**Why empty string default:** `create_conversation()` always passes `agent_role` for special agents; the default is a safe fallback for any future callers that don't pass it.

**No other changes to this file.**

**Line count estimate:** +1 line.

---

### 2.2 `agent/runtime.py` — REVISED

**What changes:** Extend `_run_loop()` to always call `kb_lookup` for auxilium on every user message, not just when `fallback_provider` is set.

**Discovery:**

- `kb_context = None` block currently gated on `if conv.fallback_provider:` at line 1124.
- `kb_lookup` returns `list[KBChunk]`. `KBChunk` has `text, source, section, score`.
- `_format_chunks_for_llm(chunks)` is a free function at line 730 — not a method on a class. Takes `list` (not typed), returns `str`.
- `_call_llm(self, session_key, messages, tools)` — instance method. `messages` is `list[dict]`. `tools` is `list[dict]`.
- `to_api_messages()` returns `list[dict]` with role strings: `"system"`, `"user"`, `"assistant"`, `"tool"`.
- Exception types in `_run_loop` around KB lookup: `kb_lookup` itself raises no exceptions (fail-soft by design, verified in `agent/kb_lookup.py`). However, `_call_llm` raises `ValueError` (no conversation, no provider configured, no caller). These propagate naturally.

**Code change — the KB pre-fetch block (line 1123-1133):**

Current:
```python
kb_context = None
if conv.fallback_provider:
    try:
        from agent.kb_lookup import kb_lookup
        chunks = kb_lookup(text, top_k=5, min_score=0.35)
        if chunks:
            kb_context = _format_chunks_for_llm(chunks)
    except Exception:
        pass  # No KB context — fallback LLM answers without grounding
```

**Replace with:**
```python
# KB synthesis: run kb_lookup for every auxilium message.
# Option A — extend existing runtime. No auxilium_synthesis.py module needed.
# See SPEC-auxilium-tier-2.md §0 Decision 5.
kb_context = None
if conv.agent_role == "helper":
    try:
        from agent.kb_lookup import kb_lookup
        chunks = kb_lookup(text, top_k=5, min_score=0.35)
        if chunks:
            kb_context = _format_chunks_for_llm(chunks)
    except Exception:
        pass  # kb_lookup is fail-soft — kb_context stays None, LLM proceeds without KB
```

**Code change — the primary LLM call block (line 1135):**

Current:
```python
response = self._call_llm(session_key, messages, tools)
```

**Replace with:**
```python
# Inject KB context into the primary LLM call for auxilium.
# If kb_context is None (no relevant chunks or lookup failed), this is a no-op.
messages_for_call = messages
if kb_context:
    messages_for_call = self._inject_kb_context(messages, kb_context, text)
response = self._call_llm(session_key, messages_for_call, tools)
```

**New helper method — add near `_format_chunks_for_llm` (around line 730):**

```python
def _inject_kb_context(self, messages: list[dict], kb_context: str, text: str) -> list[dict]:
    """Inject KB context into the most recent user message.

    Modifies a copy of messages. The KB context is prepended to the last
    user message's content so the LLM sees it as part of the current turn.

    Args:
        messages: The full message list from to_api_messages().
        kb_context: Formatted KB context string from _format_chunks_for_llm().
        text: The current user message text (used as a fallback search key).

    Returns:
        A new message list with KB context injected into the last user message.
    """
    # Build a shallow copy — only the modified message is a new dict
    injected = list(messages)
    # Find the last user message and prepend KB context to it
    for i in range(len(injected) - 1, -1, -1):
        if injected[i].get("role") == "user":
            original_content = injected[i].get("content", "")
            injected[i] = {
                "role": "user",
                "content": f"{kb_context}\n\nUser question: {original_content or text}",
            }
            return injected
    # No user message found — return unchanged
    return messages
```

**Why `_inject_kb_context` is a method on `self`:** `_run_loop` is an instance method; `_call_llm` is on `self`. The helper needs access to `self._config` only for future extensibility (e.g., chunk count or context size limits — not in this spec). Using a method keeps it close to `_run_loop` without creating a new module.

**Note on the condition `conv.agent_role == "helper"`:** `agent_role` is added to `Conversation` in this spec (§2.1). `create_conversation()` is updated in §2.3 to pass it. `SpecialAgentDef` already has `role: str` (verified at `agent/special_agents.py:33`). `auxilium.yaml` has `role: helper` (verified: `prompts/default_agents/auxilium.yaml:4`).

**No changes to:**
- The KB fallback chain (lines 1177-1241). It remains gated on `KB_OUT_OF_SCOPE && fallback_provider && !_fallback_attempted`.
- `_call_llm` signature or behavior.
- `_format_chunks_for_llm` (free function, no changes).
- Auto-save, enforcement, token tracking.

**Line count estimate:** +18 lines (KB pre-fetch block changed, `_call_llm` call changed, new `_inject_kb_context` method).

---

### 2.3 `ui/handlers/agent_runtime_handler.py` — REVISED

**What changes:** Pass `agent_role` to `create_conversation()` in `_create_runtime_conversation()`.

**Discovery:** `create_conversation()` at `agent/runtime.py:953`. Current signature (verified at `agent/runtime.py:953`):
```python
def create_conversation(
    self,
    session_key: str,
    agent_name: str,
    project_path: str | None = None,
    ...
    agent_role: str = "",    # ← already in the signature! See §DISCOVERY below
```

Wait — let me verify. The `create_conversation()` signature at `agent/runtime.py:953-960`:
```
959:        agent_role: str = "",
```

Let me re-check — I need to read the actual signature:
```
agent_role: str = "",
```
at line 959 in the file. Actually from my earlier grep output:
```
953:        agent_name: str,
959:        agent_role: str = "",
```
Yes — `create_conversation()` already has `agent_role` as a parameter! It's already in the signature but it was never being passed by `_create_runtime_conversation()`. So the only change is in `agent_runtime_handler.py` — pass `agent_role=agent_def.role` when calling `create_conversation()`.

**Verification (from discovery):** `agent_runtime_handler.py:405-417` calls:
```python
self._runtime.create_conversation(
    session_key=session_key,
    agent_name=agent_def.display_name,
    ...
    fallback_provider=agent_def.fallback_provider,
    fallback_model=agent_def.fallback_model,
)
```
Note: `fallback_model` was removed from `create_conversation()` in SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md. The call still has it — need to check if it errors or is silently ignored. Actually, looking at `agent/runtime.py:1015`:
```python
fallback_model=fallback_model or self._config.fallback_model,
```
This is the `create_conversation()` call site. The parameter IS in the function signature. Good.

**New code at `agent_runtime_handler.py:417` (after `fallback_model=...`):**
```python
agent_role=agent_def.role,  # "helper" for Auxilium, enables KB synthesis in _run_loop
```

**Note:** `agent_def.role` is verified at `agent/special_agents.py:33`. For non-special agents, `agent_def.role` may be empty string — this is fine, the `_run_loop` condition `conv.agent_role == "helper"` will be False and KB synthesis won't fire for them.

**Line count estimate:** +1 line.

---

### 2.4 `prompts/system/auxilium.md` — VERIFY (no changes expected)

**What changes:** None. The Phase 2 synthesis section is already written (verified present at lines 73-85).

**Verification required before declaring done:** Run `grep -n "Phase 2\|LLM Synthesis\|synthesize" prompts/system/auxilium.md` and confirm the synthesis instructions are present.

If absent: add the synthesis section. If present: confirm it covers the 5 points from the spec (ground in chunks, supplement with general knowledge, friendly tone, no "Based on the knowledge base..." prefix, answer from general reasoning when no chunks).

**For reference — the synthesis section that must be present (from the current auxilium.md):**
```
## Phase 2 — LLM Synthesis Mode

1. The KB lookup runs first. If it finds relevant chunks, they are injected as context.
2. Your job is to synthesize the KB chunks into a conversational answer — not dump them raw.
3. Ground your answer in the chunks. Quote specific sections when relevant.
4. If the chunks don't fully answer the question, supplement with your general knowledge and say so.
5. Keep your tone friendly and concise. Do not preface with "Based on the knowledge base..." — just answer naturally.
6. If no KB chunks were found (empty context), answer from your general reasoning. Say "I don't have specific docs on this" if relevant.
```

---

### 2.5 `tests/test_auxilium_tier2.py` — NEW FILE

**What changes:** New test file covering the Tier 2 KB synthesis behavior.

**Location:** `tests/test_auxilium_tier2.py`

**Test classes and methods:**

```python
"""Tests for Auxilium Tier 2 — LLM Synthesis with KB Lookup.

Covers: kb_lookup fires for auxilium on every message,
kb_context injection, empty KB response, multi-turn synthesis,
and the Conversation.agent_role field.
"""

import pytest
from unittest.mock import patch, MagicMock
from agent.runtime import AgentRuntime
from agent.config import AgentConfig, LLMProviderConfig
from models.conversation import Conversation


class TestConversationAgentRole:
    """Verify Conversation has agent_role field."""

    def test_agent_role_field_exists(self):
        conv = Conversation(
            agent_name="Auxilium",
            agent_role="helper",
            model="openai/gpt-4o",
        )
        assert conv.agent_role == "helper"

    def test_agent_role_defaults_to_empty_string(self):
        conv = Conversation(agent_name="Test", model="openai/gpt-4o")
        assert conv.agent_role == ""


class TestKBLookupFiresForAuxilium:
    """KB lookup runs for every auxilium message (not just on KB_OUT_OF_SCOPE)."""

    def _make_runtime(self, agent_role="helper"):
        providers = {
            "openai": LLMProviderConfig(
                name="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                default_model="gpt-4o",
                caller="openai",
            ),
        }
        config = AgentConfig(providers=providers, default_provider="openai", default_model="openai/gpt-4o")
        rt = AgentRuntime(config)
        rt.start()
        conv = Conversation(
            agent_name="Auxilium",
            agent_role=agent_role,
            model="openai/gpt-4o",
            system_prompt="You are Auxilium.",
        )
        rt._conversations["test-session"] = conv
        return rt, conv

    def test_kb_lookup_called_for_helper_role(self):
        """kb_lookup fires when agent_role == 'helper'."""
        rt, conv = self._make_runtime(agent_role="helper")
        captured_kwargs = {}
        def fake_lookup(question, *, top_k, min_score):
            captured_kwargs["question"] = question
            captured_kwargs["top_k"] = top_k
            captured_kwargs["min_score"] = min_score
            return []
        with patch("agent.runtime.kb_lookup", fake_lookup):
            with patch.object(rt, "_call_llm") as mock_call:
                mock_call.return_value = {
                    "choices": [{"message": {"content": "answer"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
                rt._run_loop("test-session", "how do I configure the gateway?")
                assert "question" in captured_kwargs, "kb_lookup was not called"
                assert "how do I configure" in captured_kwargs["question"]

    def test_kb_lookup_not_called_for_non_helper_role(self):
        """kb_lookup does NOT fire when agent_role != 'helper'."""
        rt, conv = self._make_runtime(agent_role="coder")
        with patch("agent.runtime.kb_lookup") as mock_lookup:
            with patch.object(rt, "_call_llm") as mock_call:
                mock_call.return_value = {
                    "choices": [{"message": {"content": "answer"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
                rt._run_loop("test-session", "how do I configure the gateway?")
                mock_lookup.assert_not_called()

    def test_kb_lookup_runs_every_message(self):
        """kb_lookup fires on every user message, not just the first."""
        rt, conv = self._make_runtime(agent_role="helper")
        call_count = [0]
        def fake_lookup(question, *, top_k, min_score):
            call_count[0] += 1
            return []
        with patch("agent.runtime.kb_lookup", fake_lookup):
            with patch.object(rt, "_call_llm") as mock_call:
                mock_call.return_value = {
                    "choices": [{"message": {"content": "answer"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
                rt._run_loop("test-session", "first question")
                rt._run_loop("test-session", "second question")
                rt._run_loop("test-session", "third question")
                assert call_count[0] == 3, f"kb_lookup called {call_count[0]} times, expected 3"


class TestKBContextInjection:
    """KB context is injected into the primary LLM call for auxilium."""

    def _make_runtime(self):
        providers = {
            "openai": LLMProviderConfig(
                name="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                default_model="gpt-4o",
                caller="openai",
            ),
        }
        config = AgentConfig(providers=providers, default_provider="openai", default_model="openai/gpt-4o")
        rt = AgentRuntime(config)
        rt.start()
        conv = Conversation(
            agent_name="Auxilium",
            agent_role="helper",
            model="openai/gpt-4o",
            system_prompt="You are Auxilium.",
        )
        rt._conversations["test-session"] = conv
        return rt, conv

    def test_kb_context_injected_into_primary_call(self):
        """When kb_lookup returns chunks, they are prepended to the user message."""
        from agent.runtime import KBChunk
        rt, conv = self._make_runtime()
        fake_chunks = [
            KBChunk(text="Gateway config is in ~/.config/crabcakes/", source="configuration.md", section="Gateway", score=0.8),
        ]
        captured_messages = []
        def fake_call(sk, messages, tools):
            captured_messages.extend(messages)
            return {
                "choices": [{"message": {"content": "Here is the answer."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        with patch("agent.runtime.kb_lookup", return_value=fake_chunks):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop("test-session", "how do I configure the gateway?")
        # The last user message should have KB context prepended
        user_msgs = [m for m in captured_messages if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        last_user = user_msgs[-1]
        assert "[KB Context" in last_user.get("content", "")
        assert "Gateway config" in last_user.get("content", "")

    def test_primary_call_without_kb_context_when_lookup_returns_empty(self):
        """When kb_lookup returns [], the primary call has no KB context."""
        rt, conv = self._make_runtime()
        captured_messages = []
        def fake_call(sk, messages, tools):
            captured_messages.extend(messages)
            return {
                "choices": [{"message": {"content": "I don't have specific docs on this."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        with patch("agent.runtime.kb_lookup", return_value=[]):
            with patch.object(rt, "_call_llm", side_effect=fake_call):
                rt._run_loop("test-session", "what is the meaning of life?")
        user_msgs = [m for m in captured_messages if m.get("role") == "user"]
        last_user = user_msgs[-1]
        assert "[KB Context" not in last_user.get("content", "")
        # The question itself is in the message
        assert "meaning of life" in last_user.get("content", "")


class TestMultiTurnSynthesis:
    """KB lookup runs fresh on every message in a multi-turn conversation."""

    def _make_runtime(self):
        providers = {
            "openai": LLMProviderConfig(
                name="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                default_model="gpt-4o",
                caller="openai",
            ),
        }
        config = AgentConfig(providers=providers, default_provider="openai", default_model="openai/gpt-4o")
        rt = AgentRuntime(config)
        rt.start()
        conv = Conversation(
            agent_name="Auxilium",
            agent_role="helper",
            model="openai/gpt-4o",
            system_prompt="You are Auxilium.",
        )
        rt._conversations["test-session"] = conv
        return rt, conv

    def test_followup_question_uses_current_question_as_query(self):
        """A follow-up ('and on Windows?') queries KB with the follow-up text."""
        rt, conv = self._make_runtime()
        queries = []
        def fake_lookup(question, *, top_k, min_score):
            queries.append(question)
            return []
        with patch("agent.runtime.kb_lookup", side_effect=fake_lookup):
            with patch.object(rt, "_call_llm") as mock_call:
                mock_call.return_value = {
                    "choices": [{"message": {"content": "answer"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }
                # First turn
                rt._run_loop("test-session", "how do I configure the gateway on Linux?")
                # Second turn (follow-up)
                rt._run_loop("test-session", "and on Windows?")
        assert len(queries) == 2
        assert "Linux" in queries[0]
        assert "Windows" in queries[1]


class TestAgentRuntimeHandlerPassesRole:
    """AgentRuntimeHandler passes agent_role to create_conversation."""

    def test_create_conversation_receives_agent_role(self):
        """_create_runtime_conversation passes agent_role=agent_def.role."""
        # This is a contract test — verify the call includes agent_role.
        # We mock create_conversation on the runtime and check its args.
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        from agent.runtime import AgentRuntime
        from agent.config import AgentConfig
        from unittest.mock import MagicMock

        config = MagicMock(spec=AgentConfig)
        config.providers = {}
        config.default_provider = "openai"
        config.default_model = "openai/gpt-4o"
        config.tool_timeout_seconds = 120
        config.enforcement.enabled = False

        handler = AgentRuntimeHandler(config)
        handler._runtime = MagicMock(spec=AgentRuntime)

        agent_def = MagicMock()
        agent_def.display_name = "Auxilium"
        agent_def.role = "helper"
        agent_def.fallback_provider = None
        agent_def.fallback_model = None
        agent_def.system_prompt = "You are Auxilium."
        agent_def.tools = []

        handler._create_runtime_conversation("test-session", agent_def)

        call_kwargs = handler._runtime.create_conversation.call_args
        assert call_kwargs.kwargs.get("agent_role") == "helper", \
            f"agent_role not passed: {call_kwargs.kwargs}"
```

**Line count estimate:** ~260 lines.

---

### 2.6 Files NOT changed (already correct)

- `utils/prompt_loader.py` — already loads `auxilium.md` for `agent_role == "helper"` at line 207. No changes needed.
- `agent/kb_lookup.py` — already fail-soft. No changes needed.
- `agent/runtime.py:_call_llm` — already handles timeouts, retries, error propagation. No changes needed.
- `agent/runtime.py:_format_chunks_for_llm` — free function, no changes needed.
- `agent/runtime.py` KB fallback chain (lines 1177-1241) — unchanged. KB synthesis fires on primary call; the fallback chain fires only when primary returns `KB_OUT_OF_SCOPE` AND `fallback_provider` is set AND `_fallback_attempted` is False. These are separate concerns.
- `ui/wiring.py` — unchanged. `AgentRuntimeHandler` is already wired to `AgentRuntime`.
- `ui/window.py` — unchanged. Conversation creation goes through `_create_runtime_conversation()` which is updated in §2.3.
- `agent/special_agents.py` — `role: str` field already exists on `SpecialAgentDef` (verified at line 33). `auxilium.yaml` has `role: helper` (verified).

---

## 3. Data Flow

### 3.1 First message — auxilium with KB synthesis

```
User types: "how do I configure the gateway?"
    ↓
AgentRuntimeHandler._create_runtime_conversation()
    → runtime.create_conversation(agent_role="helper", ...)  [§2.3 change]
    → Conversation(agent_role="helper", ...) stored in _conversations
    ↓
AgentRuntime._run_loop("test-session", "how do I configure the gateway?")
    → conv.to_api_messages() builds full message list [unchanged]
    → NEW: if conv.agent_role == "helper":  [§2.2 change]
          kb_lookup("how do I configure the gateway?", top_k=5, min_score=0.35)
          → list[KBChunk]  (e.g. 3 chunks from configuration.md)
          → _format_chunks_for_llm(chunks)
          → kb_context = "[KB Context — relevant documentation chunks:] ..."
    → NEW: messages_for_call = _inject_kb_context(messages, kb_context, text)  [§2.2 change]
          → finds last user message in messages list
          → prepends KB context: "{fb_context}\n\nUser question: {original}"
    → runtime._call_llm(session_key, messages_for_call, tools)
    → LLM sees KB context + user question + system prompt (auxilium.md synthesis instructions)
    → LLM synthesizes: "To configure the gateway, open your config file at
      ~/.config/crabcakes/agent.json — see §Gateway configuration in your docs."
    → response returned, text extracted, conversation updated [unchanged]
```

### 3.2 KB returns empty (no relevant chunks)

```
kb_lookup("what is the meaning of life?", ...) → []
kb_context = None
messages_for_call = messages  ← no injection
_call_llm(session_key, messages, tools)  ← normal call, no KB context
LLM answers from general knowledge: "That's a philosophical question..."
```

### 3.3 Follow-up question (multi-turn)

```
User types: "and on Windows?"
    → conv.to_api_messages() includes: system prompt + first user msg + first LLM answer + second user msg
    → kb_lookup("and on Windows?", ...)  ← fresh query, not cached
    → new chunks possibly different from first exchange
    → _inject_kb_context() prepended to the new user message only
    → _call_llm(session_key, messages_with_new_context, tools)
    → LLM synthesizes with current chunks + full conversation history
```

### 3.4 Non-auxilium agent (agent_role != "helper")

```
User in Coder tab: "how do I configure the gateway?"
    → conv.to_api_messages() builds message list
    → if conv.agent_role == "helper":  ← FALSE
    → kb_context = None  ← KB synthesis skipped
    → _call_llm(session_key, messages, tools)  ← normal call
    → Coder answers normally
```

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `models/conversation.py` | Add `agent_role` field to `Conversation` | +1 | Low |
| `agent/runtime.py` | Extend `_run_loop()` KB pre-fetch + new `_inject_kb_context()` method | +18 | Medium (touches the hot loop) |
| `ui/handlers/agent_runtime_handler.py` | Pass `agent_role=agent_def.role` to `create_conversation()` | +1 | Low |
| `prompts/system/auxilium.md` | Verify Phase 2 synthesis section is present | 0 (or +20 if missing) | Low |
| `tests/test_auxilium_tier2.py` | New test file | +260 | Low |
| `docs/ARCHITECTURE.md` | Document KB synthesis in §3, §13 | +15 | Low |
| **Total** | | **+296 (+316 if auxilium.md missing)** | |

---

## 5. Implementation Order

### Phase T2-1: Conversation dataclass

1. Add `agent_role: str = ""` to `Conversation` in `models/conversation.py`.
2. Verify: `python3 -c "from models.conversation import Conversation; c = Conversation(agent_name='X', model='y', agent_role='helper'); print(c.agent_role)"` → `helper`.

### Phase T2-2: Runtime — KB synthesis in `_run_loop`

1. Change the KB pre-fetch condition from `if conv.fallback_provider:` to `if conv.agent_role == "helper":`.
2. Add `_inject_kb_context()` method to `AgentRuntime`.
3. Change the `_call_llm` invocation to use `messages_for_call` instead of `messages`.
4. Verify: `python3 -c "from agent.runtime import AgentRuntime; print('imports OK')"`.
5. Run `tests/test_auxilium_tier2.py` (Phase T2-4 will add the full test; during implementation, write a quick smoke test).

### Phase T2-3: Handler — pass `agent_role` to `create_conversation()`

1. Add `agent_role=agent_def.role,` to the `create_conversation()` call in `agent_runtime_handler.py:_create_runtime_conversation()`.
2. Verify: `grep -n "agent_role=" ui/handlers/agent_runtime_handler.py`.

### Phase T2-4: Tests

1. Write `tests/test_auxilium_tier2.py` (the 5 test classes above).
2. Run: `python3 -m pytest tests/test_auxilium_tier2.py -v`.

### Phase T2-5: System prompt verification

1. Run: `grep -n "Phase 2\|LLM Synthesis\|synthesize" prompts/system/auxilium.md`.
2. If the synthesis section is absent: write it (the 6-bullet template from §2.4).
3. If present: confirm it covers all 5 required behaviors.

### Phase T2-6: Documentation

1. Update `docs/ARCHITECTURE.md` §3 and §13 to document the KB synthesis path.
2. Mark `SPEC-auxilium-tier-2.md` as DONE in the frontmatter.

---

## 6. Acceptance Criteria

- [ ] **AC-T2-1** `Conversation` has `agent_role: str = ""` field and it defaults to `""`.
- [ ] **AC-T2-2** `_create_runtime_conversation()` passes `agent_role=agent_def.role` to `create_conversation()`.
- [ ] **AC-T2-3** For auxilium (`agent_role == "helper"`), `kb_lookup` fires on every user message — verified by mocking `kb_lookup` and asserting it is called.
- [ ] **AC-T2-4** For non-auxilium agents (`agent_role != "helper"`), `kb_lookup` does NOT fire — verified by mocking and asserting it is not called.
- [ ] **AC-T2-5** When `kb_lookup` returns chunks, KB context is prepended to the last user message in `_call_llm`'s messages — verified by capturing messages passed to `_call_llm`.
- [ ] **AC-T2-6** When `kb_lookup` returns `[]`, `_call_llm` receives messages without KB context — no `"[KB Context"` in any user message.
- [ ] **AC-T2-7** Follow-up questions trigger a fresh `kb_lookup` with the follow-up text as the query — not a cached result from the first exchange.
- [ ] **AC-T2-8** `prompts/system/auxilium.md` contains the Phase 2 synthesis instructions (6 bullets covering: ground in chunks, supplement with general knowledge, friendly tone, no prefix, answer from general reasoning when no chunks).
- [ ] **AC-T2-9** All 5 test classes in `tests/test_auxilium_tier2.py` pass.
- [ ] **AC-T2-10** Existing 55+ tests still pass (no regression from adding `agent_role` or changing the KB pre-fetch condition).
- [ ] **AC-T2-11** Manual verification: with a real provider configured, Auxilium answers "how do I configure the gateway?" with a response grounded in `knowledge/configuration.md` (exact answer quality is LLM-dependent; verify that the response mentions something from the KB chunks).

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| `agent_role` is `None` (not `""`) | `None == "helper"` is `False` — KB synthesis skipped. Safe. |
| `agent_def.role` is `""` (empty string, e.g. a custom agent without a role) | `"" == "helper"` is `False` — KB synthesis skipped. Correct — only auxilium gets synthesis. |
| `kb_lookup` raises an exception | `except Exception: pass` → `kb_context = None` → normal LLM call without KB. Fail-soft. |
| KB returns 0 chunks for a factual question | `kb_context = None` → LLM answers from general knowledge. Per auxilium.md: "Say 'I don't have specific docs on this' if relevant." |
| KB returns chunks but LLM call fails with `ValueError` (no provider configured) | Exception propagates → `_dispatch(self._on_error, ...)` → error shown to user. Same as any other provider error. |
| LLM call times out (default 120s) | `_call_llm` raises. `RuntimeError` / `TimeoutError` propagates. Error shown to user. No special handling needed. |
| Auxilium in a multi-turn conversation: the 3rd message has no KB chunks but the 1st and 2nd did | Each message is independent. Message 3 gets no KB context. LLM answers from general knowledge. Correct per design. |
| User switches primary provider mid-conversation | `conv.model` updated. `conv.agent_role` stays `"helper"`. KB synthesis continues to fire on every message. |
| KB fallback chain still fires for `KB_OUT_OF_SCOPE` | Yes — the fallback chain at lines 1177-1241 is unchanged. KB synthesis now also fires on the primary call. The two paths are independent. |
| Very long KB context (>50K chars) | `kb_lookup` returns top 5 chunks (`top_k=5`). Each chunk is a section. Total context is bounded. If needed, add a `max_chars` parameter to `_inject_kb_context`. Out of scope for this spec. |
| Concurrent messages (two auxilium sessions simultaneously) | `_run_loop` is called per session with separate `session_key`. Each `_conversations[session_key]` has its own `agent_role`. Thread-safe via `self._lock` around `_conversations` dict access (verified at `runtime.py:1025`). |

---

## 8. ARCHITECTURE.md Updates Required

**§3 (Agents + Runtime):** Add a section on KB synthesis:

> **Auxilium KB synthesis (Tier 2):** When `conv.agent_role == "helper"`, `AgentRuntime._run_loop()` calls `kb_lookup(text, top_k=5, min_score=0.35)` on every user message and injects the formatted chunks into the primary LLM call via `_inject_kb_context()`. The synthesis is handled by the LLM following `prompts/system/auxilium.md` Phase 2 instructions. This is separate from the KB fallback chain (which fires only when the primary returns `KB_OUT_OF_SCOPE`). The `Conversation` dataclass has `agent_role: str = ""` to distinguish auxilium from other agents.

**§13 (KB Provider):** Update the integration paragraph to note that auxilium now uses KB synthesis directly (not just as a fallback):

> **KB synthesis for Auxilium:** Auxilium (`agent_role == "helper"`) runs `kb_lookup` on every user message and injects KB context into the primary LLM call. The KB fallback chain (per-agent `conv.fallback_provider`) is unchanged — it fires when the primary returns `KB_OUT_OF_SCOPE`. See `docs/specs/SPEC-auxilium-tier-2.md`.

---

## 9. Spec Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `Conversation` field addition: verified at `models/conversation.py:91-115`. Adding `agent_role` after `agent_name` is safe.
   - `_run_loop` KB block change: verified at `agent/runtime.py:1123-1133`. Current `if conv.fallback_provider:` confirmed. Changing to `if conv.agent_role == "helper":` is correct.
   - `_inject_kb_context` method: modeled on the existing message injection in the fallback chain at `agent/runtime.py:1208-1219`. Same pattern, copied correctly.
   - `_call_llm` invocation: verified at `agent/runtime.py:1135`. Signature: `(self, session_key, messages, tools)`. Passing `messages_for_call` is type-compatible.
   - `create_conversation()` call: verified at `agent/runtime.py:953-1015`. `agent_role` is already a parameter (line 959). Passing it from `agent_runtime_handler.py` is the only change needed.

2. **Did I catch all exception types?**
   - `kb_lookup` raises no exceptions (verified in `agent/kb_lookup.py` — all code paths return, `IndexError` is caught internally). The `except Exception: pass` is defensive.
   - `_call_llm` raises `ValueError` (no conversation, no provider, no caller). These propagate to `_run_loop`'s caller. Already the existing behavior — not changed.
   - `_inject_kb_context` raises no exceptions.

3. **Did I verify key structures?**
   - `messages` from `to_api_messages()`: verified at `models/conversation.py:149-192`. Returns `list[dict]` with `{"role": "user"|"system"|"assistant"|"tool", "content": str}`.
   - `KBChunk` fields: verified at `agent/kb_lookup.py`. `text, source, section, score`.
   - `conv.agent_role`: added in this spec (§2.1), not yet in the codebase.

4. **Did I trace the data flow end-to-end?**
   - See §3 for four full data flow traces (first message, empty KB, multi-turn, non-auxilium).

5. **Would an implementer who follows this spec exactly produce working code?**
   - Yes, with the caveat that the Phase T2-5 verification (checking if the synthesis section is present) may require writing it if it's missing. The implementer should check `grep -n "Phase 2" prompts/system/auxilium.md` as the first step of Phase T2-5.

---

## 10. Risks and Follow-ups

### Risks

1. **`_call_llm` is called with modified messages** (Medium): `_inject_kb_context` creates a new `messages` list with a modified user message dict. This is a shallow copy — the list itself is new, but the other dicts are the same objects. If `_call_llm` mutates the messages (it shouldn't — it only reads them), this could cause issues. **Mitigation:** `_call_llm` only reads `messages`; it does not mutate them. Verified by reading the `_call_llm` body — it extracts data from messages but never appends or modifies them.
2. **`agent_role` defaulting to `""`** (Low): If `create_conversation()` is called without `agent_role` (future callers), the default is `""` and KB synthesis won't fire. This is the safe default — better to skip synthesis than fire it for the wrong agent. **Mitigation:** `auxilium.yaml` always sets `role: helper`, and `_create_runtime_conversation()` always passes `agent_def.role`.
3. **Multi-turn conversation: accumulated KB context in each message** (Low): Each turn prepends KB context to the *current* user message only (not to all previous messages). The `messages` list already contains the full conversation history (previous user + assistant messages). Prepending to the current message is correct. The LLM sees all history + current KB context. **Verified:** `_inject_kb_context` only modifies the last user message. Previous messages are passed through unchanged.

### Follow-ups (Tier 3)

1. **Add a KB context size limit** — if `kb_context` exceeds a threshold (e.g. 10K chars), truncate the oldest/least-relevant chunks. Currently unbounded.
2. **Add a `top_k` or `min_score` config option** — expose these as agent-level or global config fields so power users can tune.
3. **Add a "re-run KB lookup" tool** — let the LLM explicitly re-query the KB mid-conversation (useful for exploratory follow-ups where the initial query wasn't specific enough).
4. **Auxilium Tier 3 (`SPEC-auxilium-tier-3.md`)** — write the spec after Tier 2 ships. Content expansion + workflow KB file + verification automation.
5. **Add a `timeout_seconds` override for synthesis calls** — if the KB is large and the model is slow, the 120s default may be insufficient. Make it configurable.
