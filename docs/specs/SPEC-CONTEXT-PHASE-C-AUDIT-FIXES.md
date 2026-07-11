# PHASE C Audit Fixes — 4 bugs

**File:** `agent/runtime.py`, `agent/context_strategy.py`, `ui/handlers/agent_runtime_handler.py`

---

## BUG #1 — _call_for_summary ignores per-agent api_key

**File:** `agent/runtime.py`

In `_call_for_summary` (around line 3081), the api_key resolution is:
```python
        api_key = getattr(provider_cfg, "api_key", "") or ""
```

This ignores `conv.api_key` (per-agent override). The real `_call_llm` at line 2583 uses `effective_api_key = conv.api_key or provider_cfg.api_key`.

**Fix:** Change the api_key resolution to check conv.api_key first. Since `_call_for_summary` doesn't receive `conv`, the simplest fix is to have `force_llm_compact` pass `conv` to the lambda. Or: change `_call_for_summary` to accept an optional `conv` parameter.

Simplest approach — in `_call_for_summary`, add `conv` as a parameter and resolve api_key from it:

```python
    def _call_for_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
        conv: "Conversation | None" = None,
    ) -> str:
```

Then in the api_key resolution:
```python
        api_key = ""
        if conv is not None and getattr(conv, "api_key", None):
            api_key = conv.api_key
        if not api_key:
            api_key = getattr(provider_cfg, "api_key", "") or ""
```

And in `force_llm_compact`, update the lambda to pass conv:
```python
        strat = LLMSummarizeStrategy(
            llm_provider=lambda sys_p, user_p, model_id=None:
                self._call_for_summary(
                    system_prompt=sys_p,
                    user_prompt=user_p,
                    model_id=model_id or conv.model,
                    conv=conv,
                ),
        )
```

---

## BUG #2 — Double truncation in LLMSummarizeStrategy._summary

**File:** `agent/context_strategy.py`

In `LLMSummarizeStrategy._summary` (around line 845), there's a truncation block:
```python
        if token_budget > 0:
            response_tokens = len(response) // 4
            if response_tokens > token_budget:
                target_chars = token_budget * 4
                cut_at = response.rfind("\n", 0, target_chars)
                if cut_at <= 0:
                    cut_at = target_chars
                response = response[:cut_at] + "\n[... summary truncated ...]"
```

This truncates naively, potentially slicing inside `<tag>` boundaries. The parent's `_fit_summary` already handles fitting.

**Fix:** Remove the entire `if token_budget > 0:` block. Let the parent's `_fit_summary` handle truncation. The strategy should return the raw LLM response and let the parent's compact() method fit it.

---

## BUG #4 — Stale comment + silent fallback

**File:** `ui/handlers/agent_runtime_handler.py`

Around line 507, there's a stale comment:
```python
            # Phase B: this branch is unreachable (no compaction_strategy
            # field on SpecialAgentDef, and force_llm_compact not implemented).
```

**Fix:** Update the comment to reflect Phase C:
```python
            # Phase C path — fires when force_llm_compact exists and
            # agent_def.compaction_strategy == "llm".
```

---

## BUG #6 — Dead variables in force_llm_compact

**File:** `agent/runtime.py`

In `force_llm_compact` (around line 3053), there are two unused variables:
```python
        messages_before = len(conv.messages)
        tokens_before = conv.get_token_estimate()
```

**Fix:** Delete both lines. They're never referenced.

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read each file before editing.
- 4 mechanical fixes across 3 files.

## Verification

```bash
cd /home/q/projects/crabcakes

# 1. Syntax
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['agent/runtime.py', 'agent/context_strategy.py', 'ui/handlers/agent_runtime_handler.py']]; print('SYNTAX OK')"

# 2. _call_for_summary has conv param
grep -n "conv.*None" agent/runtime.py | grep _call_for_summary

# 3. No truncation in LLMSummarizeStrategy._summary
grep -n "token_budget.*target_chars\|summary truncated" agent/context_strategy.py

# 4. Stale comment updated
grep -n "Phase C path" ui/handlers/agent_runtime_handler.py

# 5. No dead variables
grep -n "messages_before\|tokens_before" agent/runtime.py | grep force_llm_compact

# 6. Existing tests
python3 -m pytest tests/test_context_strategy.py tests/test_runtime_compaction.py -q
```
