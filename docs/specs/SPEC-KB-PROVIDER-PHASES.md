# KB Provider Phase Instructions

**Spec:** `/home/q/projects/crabcakes/docs/specs/SPEC-KB-PROVIDER.md`
**Builder must read the full spec before writing any code.**
**Include the word "please" in your acknowledgment so I know the message was received.**
**Demand: paste full pytest output, not summaries.**

---

## PHASE 1 of 6 — Data Model: SpecialAgentDef + Conversation fallback fields

**Files:**
1. `agent/special_agents.py`
2. `models/conversation.py`

### Changes:

**File 1: `agent/special_agents.py`**

Add two fields to `SpecialAgentDef` dataclass (after `llm_name` field):
```python
    fallback_provider: str | None = None   # KB fallback provider name (e.g. "openrouter")
    fallback_model: str | None = None      # KB fallback model (e.g. "openrouter/owl-alpha")
```

In `_load_registry()`, after the `llm_name` line, add:
```python
            fallback_provider=agent_def.get("fallback_provider"),
            fallback_model=agent_def.get("fallback_model"),
```

**File 2: `models/conversation.py`**

Add two fields to `Conversation` dataclass (after `app_title` field):
```python
    fallback_provider: str | None = None   # KB fallback provider (from agent def)
    fallback_model: str | None = None      # KB fallback model (from agent def)
```

### Verification:
```bash
python3 -c "from agent.special_agents import SpecialAgentDef; import dataclasses; print([f.name for f in dataclasses.fields(SpecialAgentDef)])"
# Must include fallback_provider and fallback_model

python3 -c "from models.conversation import Conversation; import dataclasses; print([f.name for f in dataclasses.fields(Conversation)])"
# Must include fallback_provider and fallback_model

pytest tests/test_special_agents.py tests/test_conversation.py -x -q --tb=short
# Paste full output
```

### COMPLETENESS:
- [ ] Phase 1: SpecialAgentDef has fallback_provider and fallback_model fields — evidence: dataclass fields print
- [ ] Phase 1: Conversation has fallback_provider and fallback_model fields — evidence: dataclass fields print
- [ ] Phase 1: _load_registry reads fallback_provider and fallback_model from YAML dict — evidence: grep output
- [ ] Phase 1: Tests pass — evidence: pytest output

---

## PHASE 2 of 6 — Wire fallback through create_conversation + send_to_special_agent

**Files:**
1. `agent/runtime.py` (create_conversation signature + Conversation construction)
2. `ui/handlers/agent_runtime_handler.py` (send_to_special_agent + sync block)

### Changes:

**File 1: `agent/runtime.py`**

In `create_conversation()` signature, add at the end:
```python
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
) -> str:
```

In the `Conversation()` construction inside `create_conversation`, add at the end:
```python
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
```

**File 2: `ui/handlers/agent_runtime_handler.py`**

In `send_to_special_agent()`, in the `rt.create_conversation()` call, add at the end:
```python
                fallback_provider=agent_def.fallback_provider,
                fallback_model=agent_def.fallback_model,
```

Also in the sync block (where conv is not None), after the app_title sync, add:
```python
                # Sync fallback config (in case agent was edited)
                conv.fallback_provider = agent_def.fallback_provider
                conv.fallback_model = agent_def.fallback_model
```

### Verification:
```bash
python3 -c "import inspect; from agent.runtime import AgentRuntime; sig = inspect.signature(AgentRuntime.create_conversation); print(sig)"
# Must show fallback_provider and fallback_model params

grep -n "fallback_provider" ui/handlers/agent_runtime_handler.py
# Must show fallback_provider in create_conversation call AND sync block

pytest tests/test_agent_runtime.py tests/test_special_agents.py -x -q --tb=short
# Paste full output
```

### COMPLETENESS:
- [ ] Phase 2: create_conversation accepts fallback_provider and fallback_model params — evidence: inspect.signature
- [ ] Phase 2: Conversation constructed with fallback fields — evidence: grep in runtime.py
- [ ] Phase 2: send_to_special_agent passes fallback from agent_def — evidence: grep output
- [ ] Phase 2: Sync block updates fallback on edit — evidence: grep output
- [ ] Phase 2: Tests pass — evidence: pytest output

---

## PHASE 3 of 6 — load_agent_config + _normalize_fallback_fields cleanup

**Files:**
1. `agent/config.py`
2. `utils/agent_defs.py`

### Changes:

**File 1: `agent/config.py`**

In `_create_default_config()`, in the example dict, add:
```python
    "fallback_provider": None,
    "fallback_model": None,
```

In `load_agent_config()`, in the `AgentConfig()` return, add:
```python
        fallback_provider=raw.get("fallback_provider"),
        fallback_model=raw.get("fallback_model"),
```

Keep the local `fallback_provider`/`fallback_model` fields on `AgentConfig` (do NOT remove them — they serve as global defaults).

Also update `create_conversation()` to fall back to config defaults:
Change:
```python
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
```
To:
```python
            fallback_provider=fallback_provider or self._config.fallback_provider,
            fallback_model=fallback_model or self._config.fallback_model,
```

**File 2: `utils/agent_defs.py`**

Replace `_normalize_fallback_fields` with explicit version:
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

### Verification:
```bash
grep -n "fallback_provider\|fallback_model" agent/config.py
# Must show in _create_default_config, load_agent_config, and create_conversation

grep -n "fallback_provider\|fallback_model" utils/agent_defs.py
# Must show explicit None default pattern

pytest tests/test_config.py tests/test_agent_defs.py -x -q --tb=short
# Paste full output
```

### COMPLETENESS:
- [ ] Phase 3: _create_default_config includes fallback_provider and fallback_model — evidence: grep
- [ ] Phase 3: load_agent_config parses fallback from agent.json — evidence: grep
- [ ] Phase 3: create_conversation falls back to config defaults — evidence: grep output
- [ ] Phase 3: _normalize_fallback_fields uses explicit None default pattern — evidence: grep
- [ ] Phase 3: Tests pass — evidence: pytest output

---

## PHASE 4 of 6 — Runtime fallback chain reads conv.fallback_provider

**File:** `agent/runtime.py`

### Changes:

In `_run_loop()`, replace the fallback chain block. Currently reads `self._config.fallback_provider`. Replace with `conv.fallback_provider`:

Current (around line 1144):
```python
                    if (
                        text_content == KB_OUT_OF_SCOPE
                        and self._config.fallback_provider
                        and not getattr(conv, "_fallback_attempted", False)
                    ):
                        conv._fallback_attempted = True
                        ...
                        fallback_model = self._config.fallback_model or f"{self._config.fallback_provider}/{self._config.default_model}"
```

Replace `self._config.fallback_provider` with `conv.fallback_provider` and `self._config.fallback_model` with `conv.fallback_model`:

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
                            fb_cost = _cost_for_model(fb_model, fb_prompt, fb_comp)
                            conv.record_usage(fb_prompt + fb_comp, fb_cost)
                            self._dispatch(self._on_token_usage, session_key, fb_prompt + fb_comp, fb_cost)
                        except Exception as e:
                            logger.warning("[tool-loop] sk=%s fallback call failed: %s", session_key, e)
                        finally:
                            conv.model = original_model
```

### Verification:
```bash
grep -n "conv.fallback_provider" agent/runtime.py
# Must show in fallback chain (not self._config.fallback_provider)

grep -n "self._config.fallback_provider" agent/runtime.py
# Must return 0 matches (replaced everywhere)

pytest tests/test_runtime_caller_resolution.py tests/test_runtime_fallback.py tests/test_bug_fixes.py -x -q --tb=short
# Paste full output
```

### COMPLETENESS:
- [ ] Phase 4: Fallback chain reads conv.fallback_provider — evidence: grep output
- [ ] Phase 4: No remaining self._config.fallback_provider references — evidence: grep returns 0
- [ ] Phase 4: fallback_model simplified to conv.fallback_model or conv.fallback_provider — evidence: code inspection
- [ ] Phase 4: Tests pass — evidence: pytest output

---

## PHASE 5 of 6 — Phase 2 Synthesis: kb_lookup pre-fetch + context injection + system prompt

**Files:**
1. `agent/runtime.py`
2. `prompts/system/auxilium.md`

### Changes:

**File 1: `agent/runtime.py`**

Add import at top of file:
```python
from agent.kb_lookup import kb_lookup
```

Add helper function (after `_resolve_caller_key`):
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

In `_run_loop()`, before the `_call_llm` call, add KB pre-fetch:
```python
            kb_context = None
            if conv.fallback_provider:
                try:
                    chunks = kb_lookup(text, top_k=5, min_score=0.35)
                    if chunks:
                        kb_context = _format_chunks_for_llm(chunks)
                except Exception:
                    pass  # No KB context — fallback LLM answers without grounding
```

In the fallback chain (Phase 4 changes), before calling `_call_llm` for fallback, inject KB context:
```python
                        # Inject KB context into messages for fallback LLM
                        if kb_context:
                            messages_with_context = list(messages)
                            for i in range(len(messages_with_context) - 1, -1, -1):
                                if messages_with_context[i].get("role") == "user":
                                    messages_with_context[i] = {
                                        "role": "user",
                                        "content": f"{kb_context}\n\nUser question: {messages_with_context[i]['content']}",
                                    }
                                    break
                            fb_response = self._call_llm(session_key, messages_with_context, tools)
                        else:
                            fb_response = self._call_llm(session_key, messages, tools)
```

**File 2: `prompts/system/auxilium.md``

Add at the end of the file:
```markdown
## Phase 2 — LLM Synthesis Mode

When a real LLM provider is configured as your fallback, you operate in synthesis mode:

1. The KB lookup runs first. If it finds relevant chunks, they are injected as context.
2. Your job is to synthesize the KB chunks into a conversational answer — not dump them raw.
3. Ground your answer in the chunks. Quote specific sections when relevant.
4. If the chunks don't fully answer the question, supplement with your general knowledge and say so.
5. Keep your tone friendly and concise. Do not preface with "Based on the knowledge base..." — just answer naturally.
6. If no KB chunks were found (empty context), answer from your general reasoning. Say "I don't have specific docs on this" if relevant.
```

### Verification:
```bash
grep -n "kb_lookup" agent/runtime.py
# Must show import and usage in _run_loop

grep -n "_format_chunks_for_llm" agent/runtime.py
# Must show definition and usage

grep -n "Phase 2" prompts/system/auxilium.md
# Must show Phase 2 synthesis section

pytest tests/test_kb_lookup.py tests/test_runtime_fallback.py -x -q --tb=short
# Paste full output
```

### COMPLETENESS:
- [ ] Phase 5: kb_lookup imported in runtime.py — evidence: grep
- [ ] Phase 5: _format_chunks_for_llm helper defined — evidence: grep
- [ ] Phase 5: KB pre-fetch before _call_llm in _run_loop — evidence: grep
- [ ] Phase 5: KB context injected into fallback messages — evidence: code inspection
- [ ] Phase 6: System prompt has Phase 2 synthesis section — evidence: grep
- [ ] Phase 5: Tests pass — evidence: pytest output

---

## PHASE 6 of 6 — Full verification

**No code changes. Verification only.**

### Verification checklist:
```bash
# 1. All dataclass fields present
python3 -c "from agent.special_agents import SpecialAgentDef; import dataclasses; f = [x.name for x in dataclasses.fields(SpecialAgentDef)]; print(f); assert 'fallback_provider' in f and 'fallback_model' in f"

# 2. Conversation fields present
python3 -c "from models.conversation import Conversation; import dataclasses; f = [x.name for x in dataclasses.fields(Conversation)]; print(f); assert 'fallback_provider' in f and 'fallback_model' in f"

# 3. create_conversation signature
python3 -c "import inspect; from agent.runtime import AgentRuntime; sig = inspect.signature(AgentRuntime.create_conversation); print(sig); params = list(sig.parameters.keys()); assert 'fallback_provider' in params and 'fallback_model' in params"

# 4. conv.fallback_provider in runtime (not self._config)
grep -c "self._config.fallback_provider" agent/runtime.py
# Must be 0

grep -c "conv.fallback_provider" agent/runtime.py
# Must be >= 2

# 5. System prompt
grep -c "Phase 2" prompts/system/auxilium.md
# Must be >= 1

# 6. No self._config.fallback references remain in runtime.py
grep -n "self._config.fallback" agent/runtime.py
# Must return 0 matches

# 7. Full relevant test suite
pytest tests/test_kb_lookup.py tests/test_kb_server.py tests/test_runtime_fallback.py tests/test_runtime_caller_resolution.py tests/test_special_agents.py tests/test_conversation.py tests/test_config.py tests/test_agent_defs.py tests/test_bug_fixes.py tests/test_create_project.py tests/test_project_awareness.py -x -q --tb=short
# Paste full output
```

### COMPLETENESS:
- [ ] Phase 6: All AC-1 through AC-9 verified — evidence: command outputs
- [ ] Phase 6: No self._config.fallback references remain in runtime.py — evidence: grep
- [ ] Phase 6: Full test suite passes — evidence: pytest output
