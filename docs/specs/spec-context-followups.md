# SPEC: Context Management Follow-Ups — @Agent Targeting, Enum DRY, Concurrency Guard, Docs, Provider Resolution

**Date:** 2026-07-10
**Author:** Supervisor
**Status:** Draft — for implementation
**Depends on:** `docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md` (shipped)
**Target branch:** main

> **Architecture compliance:** This spec touches `ui/handlers/project_handler.py`, `ui/handlers/command_handler.py`, `ui/handlers/agent_runtime_handler.py`, `agent/runtime.py`, `utils/agent_defs.py`, `ui/views/agent_builder.py`, and `docs/ARCHITECTURE.md`. All changes respect ARCHITECTURE.md §2 layering. No changes to `models/` or `gateway/`.

---

## 0. Discovery

**Source files read:**
- `ui/handlers/project_handler.py` lines 673-832 — `cmd_clear` and `cmd_compact` both use `cmd.source_session_key` to determine the target. Neither checks `cmd.target_session_key`. The `@Agent` mention is already parsed by `CommandHandler._resolve_mention` (line 511) into `cmd.target_session_key` (line 411), but `cmd_clear`/`cmd_compact` ignore it.
- `ui/handlers/command_handler.py` lines 238-411 — `resolve_inline_mention` resolves `@Coder` to `special:coder` via `AgentManager.get_names_ref()` and `_special_agents` dict. The resolved session key is stored in `cmd.target_session_key` at line 411. Commands with `payload_free=True` (like `/clear` and `/compact`) skip the mention-parsing path at line 357 — they go through the "rest of text" path which does NOT populate `target_session_key`.
- `models/command.py` lines 29-60 — `Command` dataclass has `target_session_key: str | None = None` at line 60. Already in the data model, just unused by clear/compact.
- `agent/runtime.py` lines 1639-1659 — `self._lock`, `self._tool_history_lock`, `self._compaction_lock` all exist. `force_llm_compact` at line 3021 does NOT acquire `_compaction_lock` before swapping `self._context_strategy`. The `with self._compaction_lock:` pattern is used at lines 1982 and 2128.
- `agent/runtime.py` lines 3081-3140 — `_call_for_summary` resolves `model_id` via `conv.model` or `self._config.default_provider/default_model`. Does NOT consult `agent_def.llm_name` (the per-agent provider preference). The existing resolution chain is at `ui/handlers/agent_runtime_handler.py:604-630` (`_resolve_agent_model`).
- `ui/views/agent_builder.py` lines 136, 192, 740 — `["textual", "llm"]` hardcoded 3 times.
- `utils/agent_defs.py` line 377 — `validate_agent_def` returns `list[str]`. Already validates `compaction_strategy` at lines 481-486.
- `ui/handlers/agent_runtime_handler.py` lines 336-415 — `clear_conversation` takes `session_key: str`, validates `startswith("special:")`. Lines 444-525 — `compact_conversation` takes `(session_key, focus_text)`, same validation.

**Existing patterns observed:**
- `@Agent` resolution for `/ask` and `/delegate` already works via `resolve_inline_mention` → `cmd.target_session_key`. The pattern is: if `target_session_key` is set, use it instead of `source_session_key`.
- `_compaction_lock` is already used to guard compaction iterations. `force_llm_compact` should acquire it too.

---

## 1. Overview

### 1.1 Problem

Five follow-up items from the Context UI / Compact / LLM Strategy post-mortem:

1. **`/clear @Agent` and `/compact @Agent` don't work in project chat.** Both commands only target the current tab's agent. In project group chat, the user can't clear or compact a specific agent without switching tabs.

2. **`compaction_strategy` enum hardcoded 3 times.** `["textual", "llm"]` appears in `agent_builder.py` lines 136, 192, and 740. A typo in one location silently breaks the dropdown.

3. **`force_llm_compact` has no concurrency guard.** The `_context_strategy` swap is unprotected. Double-clicking `/compact` could corrupt the strategy state.

4. **ARCHITECTURE.md not updated** for `/compact`, context meter, or LLM strategy.

5. **`_call_for_summary` ignores per-agent `llm_name`.** Uses global `default_provider/default_model` instead of the agent's configured provider.

### 1.2 Solution

1. **`@Agent` targeting:** When `cmd.target_session_key` is set (from `@Agent` mention), use it instead of `source_session_key`. For `payload_free` commands, the mention must be parsed from the raw text before the `payload_free` short-circuit. Add a pre-parse step in `process_input` that checks for `@` mentions in `payload_free` commands and resolves them.

2. **Enum constant:** Add `VALID_COMPACTION_STRATEGIES = ("textual", "llm")` to `utils/agent_defs.py`. Import in `agent_builder.py`.

3. **Concurrency guard:** Wrap `force_llm_compact`'s strategy swap in `with self._compaction_lock:`.

4. **ARCHITECTURE.md:** Add `/compact` to §4 command list. Add context meter mention. Add `LLMSummarizeStrategy` to §3.21n.

5. **Provider resolution:** Pass `agent_def` to `force_llm_compact`. Use `_resolve_agent_model` pattern to resolve `model_id` from `agent_def.llm_name`.

### 1.3 Scope

| In scope | Out of scope |
|----------|--------------|
| 5 items listed above | New compaction strategies beyond "textual"/"llm" |
| Tests for @Agent targeting | Confirmation prompt for /clear @Agent (deferred) |
| Tests for concurrency guard | Gateway agent targeting (special: only) |

---

## 2. Changes by File

### 2.1 `ui/handlers/command_handler.py` — Parse @Agent for payload_free commands

**Problem:** `payload_free=True` commands (like `/clear` and `/compact`) skip the mention-parsing path at line 357. The `@Agent` in `/clear @Coder` is never resolved to `target_session_key`.

**Fix:** Before the `payload_free` short-circuit, check if the raw text contains an `@` mention. If so, parse it and set `cmd.target_session_key`.

**Current code (around line 357):**
```python
        elif self._registry.is_payload_free(cmd_name):
            # Payload-free command: no quoted payload required.
            cmd = Command(
                name=cmd_name,
                args=[],
                flags={},
                raw_text=text,
                body="",
                source_session_key=session_key,
            )
```

**New code:**
```python
        elif self._registry.is_payload_free(cmd_name):
            # Payload-free command: no quoted payload required.
            # But check for @Agent mention in the raw text (e.g., "/clear @Coder").
            target_sk = None
            body_text = ""
            rest = text[len(cmd_name):].strip()
            if rest.startswith("@"):
                # Parse @mention from rest
                parts = rest.split(None, 1)
                mention = parts[0]
                body_text = parts[1].strip() if len(parts) > 1 else ""
                resolved = self._resolve_mention(mention, session_key)
                if isinstance(resolved, CommandResult):
                    return resolved
                target_sk = resolved if isinstance(resolved, str) else None
            cmd = Command(
                name=cmd_name,
                args=[],
                flags={},
                raw_text=text,
                body=body_text,
                source_session_key=session_key,
                target_session_key=target_sk,
            )
```

**Verified:** `_resolve_mention` at line 511 returns `str | list[str] | CommandResult`. For single-agent mentions like `@Coder`, it returns a `str` (the session key). The `isinstance(resolved, str)` check handles this.

### 2.2 `ui/handlers/project_handler.py` — Use target_session_key in cmd_clear and cmd_compact

**Fix:** In both `cmd_clear` and `cmd_compact`, replace:
```python
        sk = cmd.source_session_key or session_key
```
with:
```python
        sk = cmd.target_session_key or cmd.source_session_key or session_key
```

This makes `@Agent` targeting take priority over the current tab. If no `@Agent` is specified, behavior is unchanged (uses current tab).

**Two locations:** `cmd_clear` (line 684) and `cmd_compact` (line 773).

### 2.3 `utils/agent_defs.py` — Add VALID_COMPACTION_STRATEGIES constant

**Add after line 376 (before `validate_agent_def`):**
```python
VALID_COMPACTION_STRATEGIES: tuple[str, ...] = ("textual", "llm")
```

**Update validation at line 482:**
```python
    cs = agent_def.get("compaction_strategy", "textual")
    if not isinstance(cs, str) or cs not in VALID_COMPACTION_STRATEGIES:
        errors.append(
            f"Invalid compaction_strategy: {cs!r}. "
            f"Must be one of: {', '.join(VALID_COMPACTION_STRATEGIES)}."
        )
```

### 2.4 `ui/views/agent_builder.py` — Use constant instead of hardcoded list

**Replace all 3 occurrences of `["textual", "llm"]`:**

Line 136:
```python
        from utils.agent_defs import VALID_COMPACTION_STRATEGIES
        self._compaction_strategy_combo = Gtk.DropDown.new_from_strings(list(VALID_COMPACTION_STRATEGIES))
```

Line 192:
```python
            "compaction_strategy":
                list(VALID_COMPACTION_STRATEGIES)[self._compaction_strategy_combo.get_selected()],
```

Line 740:
```python
        cs = agent_def.get("compaction_strategy", "textual")
        try:
            idx = VALID_COMPACTION_STRATEGIES.index(cs)
            self._compaction_strategy_combo.set_selected(idx)
        except ValueError:
            self._compaction_strategy_combo.set_selected(0)
```

**Import at top of file:**
```python
from utils.agent_defs import VALID_COMPACTION_STRATEGIES
```

### 2.5 `agent/runtime.py` — Concurrency guard for force_llm_compact

**Current (around line 3055):**
```python
        original_strategy = self._context_strategy
        strat = LLMSummarizeStrategy(...)
        self._context_strategy = strat
        ...
        try:
            strat.compact(conv, token_budget)
        finally:
            self._context_strategy = original_strategy
            conv.system_prompt = original_sp
```

**Fix:** Wrap the entire swap/compact/restore in `with self._compaction_lock:`:
```python
        with self._compaction_lock:
            original_strategy = self._context_strategy
            strat = LLMSummarizeStrategy(...)
            self._context_strategy = strat
            ...
            try:
                strat.compact(conv, token_budget)
            finally:
                self._context_strategy = original_strategy
                conv.system_prompt = original_sp
```

**Verified:** `self._compaction_lock` exists at line 1647. Already used at lines 1982 and 2128.

### 2.6 `agent/runtime.py` — Per-agent llm_name resolution in _call_for_summary

**Problem:** `_call_for_summary` falls back to `self._config.default_provider/default_model` when `model_id` is None. It should use the agent's `llm_name` to resolve the provider.

**Fix:** `force_llm_compact` already receives `conv` which has `conv.model`. But `conv.model` may be empty for a fresh conversation. The fix: pass `agent_def` to `force_llm_compact` and use `_resolve_agent_model` pattern.

**In `force_llm_compact` (around line 3021), add `agent_def` parameter:**
```python
    def force_llm_compact(
        self,
        conv: "Conversation",
        token_budget: int,
        focus_text: str = "",
        agent_def: Any = None,
    ) -> dict:
```

**In the lambda, resolve model_id from agent_def:**
```python
        # Resolve model_id from agent_def.llm_name (per-agent provider preference).
        resolved_model = conv.model
        if not resolved_model and agent_def is not None:
            llm_name = getattr(agent_def, "llm_name", None)
            if llm_name:
                prov_cfg = self._config.providers.get(llm_name)
                if prov_cfg and prov_cfg.default_model:
                    resolved_model = f"{llm_name}/{prov_cfg.default_model}"
```

Then use `resolved_model` in the lambda:
```python
        strat = LLMSummarizeStrategy(
            llm_provider=lambda sys_p, user_p, model_id=None:
                self._call_for_summary(
                    system_prompt=sys_p,
                    user_prompt=user_p,
                    model_id=model_id or resolved_model,
                    conv=conv,
                ),
        )
```

**In `agent_runtime_handler.py:compact_conversation` (around line 506), pass agent_def:**
```python
                return rt.force_llm_compact(conv, target_budget, focus_text, agent_def=agent_def)
```

### 2.7 `docs/ARCHITECTURE.md` — Documentation updates

**§4 (Data Flow) — command list:** Add `/compact` entry:
```
| `/compact [focus]` | Forces compaction of current agent's conversation |
| `/compact @Agent` | Compacts a specific agent from project chat |
```

**§3.21n (agent/context_strategy.py):** Add note about `LLMSummarizeStrategy`:
```
**LLMSummarizeStrategy:** Inherits from DefaultContextStrategy. Overrides
_summary() to make one LLM call producing a 9-section structured summary.
Falls back to textual preview on LLM failure. Enabled per-agent via
`compaction_strategy: "llm"` in agent YAML.
```

**§3.21m (agent/runtime.py):** Add `force_compact()` and `force_llm_compact()` to public API list.

---

## 3. Data Flow

### @Agent targeting

```
User types "/compact @Coder" in project chat
↓
command_handler.process_input()
  → cmd_name = "compact"
  → is_payload_free("compact") → True
  → rest = "@Coder"
  → _resolve_mention("@Coder", session_key) → "special:coder"
  → cmd.target_session_key = "special:coder"
↓
project_handler.cmd_compact(cmd)
  → sk = cmd.target_session_key or cmd.source_session_key
  → sk = "special:coder"
  → dispatches to compact_conversation("special:coder", "")
```

### Concurrency guard

```
User double-clicks /compact
↓
Thread 1: force_llm_compact acquires _compaction_lock
Thread 2: force_llm_compact blocks on _compaction_lock
Thread 1: swaps strategy, runs compact, restores, releases lock
Thread 2: acquires lock, swaps strategy (now the original), runs compact, restores
→ No corruption
```

---

## 4. Acceptance Criteria

- [ ] `/compact @Coder` from a project tab compacts Coder's conversation
- [ ] `/clear @Coder` from a project tab clears Coder's conversation
- [ ] `/compact` without @Agent still works on current tab
- [ ] `/clear` without @Agent still works on current tab
- [ ] `VALID_COMPACTION_STRATEGIES` constant exists in `utils/agent_defs.py`
- [ ] `agent_builder.py` imports and uses the constant (no hardcoded `["textual", "llm"]`)
- [ ] `force_llm_compact` acquires `_compaction_lock`
- [ ] `_call_for_summary` resolves model from `agent_def.llm_name` when `conv.model` is empty
- [ ] ARCHITECTURE.md mentions `/compact` and `LLMSummarizeStrategy`
- [ ] All existing tests pass
- [ ] New tests for @Agent targeting

---

## 5. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `/compact @Unknown` | Returns "No agent matching @Unknown" error |
| `/compact @` (bare @) | Returns "No active project for @ broadcast" or similar |
| `/clear @Coder` | Clears Coder's conversation (destructive — no confirmation in this phase) |
| `/compact @Coder focus text` | Focus text passed through (body parsed after mention) |
| Double-click /compact | Second call blocks until first completes (lock) |
| Agent with no llm_name | Falls back to conv.model, then global default |
| `compaction_strategy: "hybrid"` in YAML | Validation rejects; dropdown shows "textual" |

---

## 6. Spec Self-Audit

1. **Code samples traced?** Yes — `cmd.target_session_key` verified at command.py:60. `_resolve_mention` verified at command_handler.py:511. `_compaction_lock` verified at runtime.py:1647. `_resolve_agent_model` pattern verified at agent_runtime_handler.py:604-630.
2. **Exception types?** `_resolve_mention` returns `CommandResult` on error — handled with `isinstance` check. Lock acquisition can raise `RuntimeError` if re-entered — but `threading.Lock` is non-reentrant and will block, not raise.
3. **Key structures?** `Command.target_session_key` is `str | None`. `_compaction_lock` is `threading.Lock`.
4. **Data flow traced?** Yes — §3 shows @Agent targeting and concurrency guard flows.
5. **Would this produce working code?** Yes — all changes are small and follow existing patterns.
