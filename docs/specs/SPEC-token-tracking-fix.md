# SPEC: Token Tracking Display Fix

**Status:** Ready for implementation
**Scope:** 3 files, 1 feature — make token usage visible in the UI

## Problem

The agent runtime correctly tracks `total_tokens` and `total_cost` per conversation (accumulated in `models/conversation.py:record_usage()`). The runtime dispatches real usage data via the `_on_token_usage` callback (`agent/runtime.py:1801`). However:

1. **`_on_token_usage` only logs** (`ui/handlers/agent_runtime_handler.py:995-1002`) — it receives `(session_key, total_tokens, cost)` and writes a log line, but never stores the data for UI retrieval.
2. **`/cost` command is a stub** (`ui/handlers/project_handler.py:520-545`) — it prints "contact gateway for usage API" for every agent instead of reading the conversation's accumulated `total_tokens`/`total_cost`.
3. **No per-agent usage display** — there is no way for the user to see how many tokens/cost each agent has consumed.

The conversation model already has the data:
- `models/conversation.py:159`: `total_tokens: int = 0`
- `models/conversation.py:160`: `total_cost: float = 0.0`
- `models/conversation.py:432-435`: `record_usage()` accumulates both correctly

The runtime calls `conv.record_usage(prompt_tok + comp_tok, cost)` at `agent/runtime.py:1800`.

## Goal

Make token/cost usage visible to the user through the `/cost` command by reading from conversation data that is already tracked.

## Acceptance Criteria

### AC-1: `/cost` command reads real data
- When the user types `/cost` in a project tab, the output shows each agent's `total_tokens` and `total_cost` from the persisted conversation.
- Format: `@AgentName  N tokens  $X.XXXX`
- If a conversation file doesn't exist or has zero usage, show `0 tokens  $0.0000`.

### AC-2: `/cost` works for special agents
- Special agents (Coder, Debugger, etc.) have conversation files at `~/.config/crabcakes/conversations/special:{name}.json`.
- The `/cost` command reads these files and displays their accumulated usage.

### AC-3: `/cost` handles missing conversations gracefully
- If a conversation file doesn't exist for an agent, show `0 tokens  $0.0000` (don't crash).

### AC-4: `_on_token_usage` callback stores per-session usage in a dict
- The callback at `agent_runtime_handler.py:995` should store the latest `(tokens, cost)` in a `self._session_usage: dict[str, tuple[int, float]]` dict, keyed by session_key, so the handler has a quick in-memory cache without disk I/O on every callback.
- This dict is for the `/cost` command to read when conversation files aren't available (e.g., gateway agents).

### AC-5: `/cost` uses in-memory cache as fallback
- For agents where a conversation file exists (special agents), read from the conversation file (authoritative).
- For agents where no conversation file exists (gateway agents), read from the in-memory `_session_usage` dict.
- If neither is available, show `0 tokens  $0.0000`.

## Out of Scope

- Fixing provider-level usage reporting (if MiniMax or other providers don't send usage in streaming responses, that's a separate investigation).
- Adding a real-time usage widget to the toolbar or status bar.
- Persisting `_session_usage` across restarts.
- Token breakdown display (`_on_token_breakdown`).

## Files to Change

1. **`ui/handlers/agent_runtime_handler.py`** — add `_session_usage` dict to `__init__`, update `_on_token_usage` to store in addition to logging.
2. **`ui/handlers/project_handler.py`** — rewrite `cmd_cost` to read conversation files and/or in-memory cache.
3. **`tests/test_project_handler.py`** (or nearest test file) — add tests for the new `cmd_cost` behavior.

## Architecture Notes

- The `/cost` command runs in `project_handler.py`, which does NOT import from `agent_runtime_handler.py` (handler separation per ARCHITECTURE.md).
- To bridge this: `project_handler` needs a reference to read usage data. Two options:
  - **Option A (preferred):** Read conversation files directly from disk using the existing `_conversations_dir()` helper from `agent/runtime.py` or `utils/config.py:get_config_dir()`. This is the same pattern the runtime uses for persistence.
  - **Option B:** Inject a callback/setter from `window.py` (the composition root) that provides usage data. This follows the existing setter pattern but adds complexity.
- **Use Option A** — it's simpler, reads the same authoritative data, and doesn't add wiring complexity. The in-memory cache from AC-4 is a secondary source for gateway agents.

## Test Plan

1. **Unit test:** `cmd_cost` with a mock conversation file containing `total_tokens=5000, total_cost=0.15` → output contains `5000 tokens` and `$0.1500`.
2. **Unit test:** `cmd_cost` with no conversation file → output contains `0 tokens` and `$0.0000`.
3. **Unit test:** `cmd_cost` with corrupted/empty conversation file → output contains `0 tokens` (graceful fallback).
4. **Unit test:** `_on_token_usage` stores in `_session_usage` dict.
