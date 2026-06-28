# PHASE 1 of 2 — Token Tracking: agent_runtime_handler.py + _session_usage dict

**Spec:** `docs/specs/SPEC-token-tracking-fix.md`

## Files to Change

1. `ui/handlers/agent_runtime_handler.py` — add `_session_usage` dict, update `_on_token_usage`

## Instructions

### Read First (ALL of these, completely)

- `ui/handlers/agent_runtime_handler.py` — the full file, focus on `__init__` and `_on_token_usage`
- `docs/specs/SPEC-token-tracking-fix.md` — the spec
- `models/conversation.py` — see `total_tokens` and `total_cost` fields
- `agent/runtime.py` lines around 1798-1801 — see how `_on_token_usage` is dispatched

### Edit 1: Add `_session_usage` dict to `__init__`

In the `__init__` method of `AgentRuntimeHandler` (or wherever the handler initializes its instance variables), add:

```python
self._session_usage: dict[str, tuple[int, float]] = {}
```

This is an in-memory cache of per-session token usage. Keyed by session_key. Value is `(total_tokens, total_cost)` — the latest values from the runtime callback.

### Edit 2: Update `_on_token_usage` to store in addition to logging

The current method at approximately line 995:

```python
def _on_token_usage(self, session_key: str, total_tokens: int, cost: float) -> None:
    """AgentRuntime token usage callback. Logged for now."""
    logger.info(
        "Special agent token usage for %s: %d tokens, $%.4f",
        session_key,
        total_tokens,
        cost,
    )
```

Change to:

```python
def _on_token_usage(self, session_key: str, total_tokens: int, cost: float) -> None:
    """AgentRuntime token usage callback. Store and log."""
    self._session_usage[session_key] = (total_tokens, cost)
    logger.info(
        "Special agent token usage for %s: %d tokens, $%.4f",
        session_key,
        total_tokens,
        cost,
    )
```

### Edit 3: Add a public getter method

Add a method that the project_handler (or window.py wiring) can call to read usage:

```python
def get_session_usage(self) -> dict[str, tuple[int, float]]:
    """Return the in-memory session usage cache.

    Keyed by session_key. Values are (total_tokens, total_cost).
    Used by /cost command as fallback for agents without conversation files.
    """
    return dict(self._session_usage)
```

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`
- Run: `python3 -m pytest tests/test_agent_runtime.py -q --tb=short -x` and paste the output
- Run: `grep -n "_session_usage" ui/handlers/agent_runtime_handler.py` and paste output (should show 3 matches: init, store, getter)
- Do NOT modify any other handler. Do NOT touch project_handler.py (that is Phase 2).
- Report: files changed with line numbers, test results, COMPLETENESS checklist
- At the end, include:
  COMPLETENESS:
  - [x/not done] Edit 1: _session_usage dict added to __init__ — evidence
  - [x/not done] Edit 2: _on_token_usage stores to dict — evidence
  - [x/not done] Edit 3: get_session_usage getter method — evidence
  - [x/not done] Tests pass — paste output
