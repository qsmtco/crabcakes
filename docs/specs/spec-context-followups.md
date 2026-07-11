# SPEC: Context Management Follow-Ups — @Agent Targeting, Enum DRY, Concurrency Guard, Docs, Provider Resolution

**Date:** 2026-07-10
**Author:** Supervisor
**Status:** Draft — for implementation (revised after Debugger audit)
**Depends on:** `docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md` (shipped)
**Target branch:** main

> **Architecture compliance:** This spec touches `ui/handlers/project_handler.py`, `agent/runtime.py`, `utils/agent_defs.py`, `ui/views/agent_builder.py`, `ui/handlers/agent_runtime_handler.py`, and `docs/ARCHITECTURE.md`. All changes respect ARCHITECTURE.md §2 layering. No changes to `models/` or `gateway/`.

---

## 0. Discovery

**Source files read (re-verified after Debugger audit):**
- `ui/handlers/command_handler.py` lines 300-411 — `process_input` already runs `_parse_mentions` → `_resolve_mention` → `target_sk` assignment UNCONDITIONALLY before the `is_payload_free` check. The `@Agent` in `/clear @Coder` is already resolved to `cmd.target_session_key`. No changes needed to `command_handler.py`.
- `ui/handlers/project_handler.py` lines 684, 773 — `cmd_clear` and `cmd_compact` both use `sk = cmd.source_session_key or session_key`, ignoring `cmd.target_session_key`. This is the actual bug — the consumer ignores the already-resolved target.
- `models/command.py` line 60 — `Command.target_session_key: str | None = None`. Already populated by `process_input`.
- `agent/runtime.py` line 1647 — `self._compaction_lock = threading.Lock()`. Used at lines 1982 and 2128. `force_llm_compact` (line 3021) does NOT acquire it. `force_compact` (line 3008) also does NOT acquire it.
- `agent/runtime.py` lines 3081-3140 — `_call_for_summary` resolves `model_id` via `conv.model` or `self._config.default_provider/default_model`. Does NOT consult `agent_def.llm_name`.
- `ui/views/agent_builder.py` lines 136, 192 — `["textual", "llm"]` hardcoded 2 times (NOT 3 — line 740 uses conditional, not list literal).
- `utils/agent_defs.py` line 377 — `validate_agent_def` returns `list[str]`. Already validates `compaction_strategy` at lines 481-486.
- `ui/handlers/agent_runtime_handler.py` lines 604-630 — `_resolve_agent_model(agent_def)` resolves `llm_name` → provider → `f"{llm_name}/{prov_cfg.default_model}"`. This pattern should be reused.
- `docs/ARCHITECTURE.md` — §3.21p.5 is `agent/context_strategy.py` (NOT §3.21n which is `agent/tools.py`). §4 has no "command list" subsection — `/compact` should go in `knowledge/commands.md` or a new §4.14.

---

## 1. Overview

### 1.1 Problem

Five follow-up items from the Context UI / Compact / LLM Strategy post-mortem:

1. **`/clear @Agent` and `/compact @Agent` don't work in project chat.** `process_input` already resolves `@Agent` mentions to `cmd.target_session_key`, but `cmd_clear` and `cmd_compact` ignore it — they use `cmd.source_session_key` only.

2. **`compaction_strategy` enum hardcoded 2 times.** `["textual", "llm"]` appears in `agent_builder.py` lines 136 and 192. A typo in one location silently breaks the dropdown.

3. **`force_llm_compact` and `force_compact` have no concurrency guard.** The `_context_strategy` swap is unprotected. Double-clicking `/compact` could corrupt the strategy state. Both the LLM path and the textual path need the lock.

4. **ARCHITECTURE.md not updated** for `/compact`, context meter, or LLM strategy.

5. **`_call_for_summary` ignores per-agent `llm_name`.** Uses `conv.model` or global `default_provider/default_model` instead of the agent's configured provider. The `llm_name` should take PRECEDENCE over `conv.model` (override, not fallback).

### 1.2 Solution

1. **`@Agent` targeting:** In `cmd_clear` and `cmd_compact`, use `cmd.target_session_key or cmd.source_session_key or session_key`. No changes to `command_handler.py` — `process_input` already resolves the mention.

2. **Enum constant:** Add `VALID_COMPACTION_STRATEGIES = ("textual", "llm")` to `utils/agent_defs.py`. Import in `agent_builder.py`. Replace 2 hardcoded occurrences.

3. **Concurrency guard:** Wrap BOTH `force_llm_compact` AND `force_compact` in `with self._compaction_lock:`.

4. **ARCHITECTURE.md:** Add `/compact` to `knowledge/commands.md`. Add `LLMSummarizeStrategy` note to §3.21p.5. Add `force_compact()` and `force_llm_compact()` to §3.21m.

5. **Provider resolution:** Pass `agent_def` to `force_llm_compact`. Resolve `model_id` with precedence: `agent_def.llm_name` → `conv.model` → global default. The `llm_name` OVERRIDES `conv.model`.

---

## 2. Changes by File

### 2.1 `ui/handlers/project_handler.py` — Use target_session_key in cmd_clear and cmd_compact

**Fix:** In both `cmd_clear` (line 684) and `cmd_compact` (line 773), replace:
```python
        sk = cmd.source_session_key or session_key
```
with:
```python
        sk = cmd.target_session_key or cmd.source_session_key or session_key
```

This makes `@Agent` targeting take priority over the current tab. No changes to `command_handler.py` — `process_input` already resolves `@Agent` mentions into `cmd.target_session_key`.

### 2.2 `utils/agent_defs.py` — Add VALID_COMPACTION_STRATEGIES constant

**Add before `validate_agent_def` (line 377):**
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

### 2.3 `ui/views/agent_builder.py` — Use constant instead of hardcoded list

**Add import at top of file:**
```python
from utils.agent_defs import VALID_COMPACTION_STRATEGIES
```

**Replace line 136:**
```python
        self._compaction_strategy_combo = Gtk.DropDown.new_from_strings(list(VALID_COMPACTION_STRATEGIES))
```

**Replace line 192:**
```python
            "compaction_strategy":
                list(VALID_COMPACTION_STRATEGIES)[self._compaction_strategy_combo.get_selected()],
```

**Line 740 stays as-is** (uses conditional `if cs == "llm"`, not a list literal — no change needed).

### 2.4 `agent/runtime.py` — Concurrency guard for BOTH force_compact and force_llm_compact

**Fix A: Wrap `force_compact` (line 3008) in lock:**
```python
    def force_compact(self, conv: "Conversation", token_budget: int) -> None:
        """Public wrapper around self._context_strategy.compact()."""
        with self._compaction_lock:
            self._context_strategy.compact(conv, token_budget)
```

**Fix B: Wrap `force_llm_compact` (line 3021) strategy swap in lock:**
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

Both paths now serialize on the same lock, preventing concurrent strategy corruption.

### 2.5 `agent/runtime.py` — Per-agent llm_name resolution in force_llm_compact

**Problem:** `_call_for_summary` uses `conv.model` first, falling back to global default. The agent's `llm_name` should take PRECEDENCE (override, not fallback).

**Fix:** Add `agent_def` parameter to `force_llm_compact`. Resolve `model_id` with precedence: `agent_def.llm_name` → `conv.model` → global default.

**In `force_llm_compact` (line 3021), add parameter:**
```python
    def force_llm_compact(
        self,
        conv: "Conversation",
        token_budget: int,
        focus_text: str = "",
        agent_def: Any = None,
    ) -> dict:
```

**Resolve model_id with correct precedence (llm_name OVERRIDES conv.model):**
```python
        # Resolve model_id with precedence: agent_def.llm_name > conv.model > global default.
        resolved_model = None
        if agent_def is not None:
            llm_name = getattr(agent_def, "llm_name", None)
            if llm_name:
                prov_cfg = self._config.providers.get(llm_name)
                if prov_cfg and prov_cfg.default_model:
                    if "/" in prov_cfg.default_model:
                        resolved_model = prov_cfg.default_model
                    else:
                        resolved_model = f"{llm_name}/{prov_cfg.default_model}"
        if not resolved_model:
            resolved_model = conv.model
        # If still None, _call_for_summary falls back to global default.
```

**Use `resolved_model` in the lambda:**
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

**In `agent_runtime_handler.py:compact_conversation` (line 506), pass agent_def:**
```python
                return rt.force_llm_compact(conv, target_budget, focus_text, agent_def=agent_def)
```

### 2.6 `docs/ARCHITECTURE.md` — Documentation updates

**`knowledge/commands.md`:** Add `/compact` entry to the command reference.

**§3.21p.5 (agent/context_strategy.py):** Add note:
```
**LLMSummarizeStrategy:** Inherits from DefaultContextStrategy. Overrides
_summary() to make one LLM call producing a 9-section structured summary.
Falls back to textual preview on LLM failure. Enabled per-agent via
`compaction_strategy: "llm"` in agent YAML.
```

**§3.21m (agent/runtime.py):** Add to public API:
```
- `force_compact(conv, token_budget)` — public wrapper for textual compaction
- `force_llm_compact(conv, token_budget, focus_text="", agent_def=None)` — LLM strategy compaction
```

---

## 3. Data Flow

### @Agent targeting

```
User types "/compact @Coder" in project chat
↓
command_handler.process_input()
  → _parse_mentions finds "@Coder"
  → _resolve_mention("@Coder") → "special:coder"
  → cmd.target_session_key = "special:coder"  (ALREADY HAPPENS — no change needed)
↓
project_handler.cmd_compact(cmd)
  → sk = cmd.target_session_key or cmd.source_session_key or session_key
  → sk = "special:coder"  (NEW — was using source_session_key only)
  → dispatches to compact_conversation("special:coder", "")
```

### Concurrency guard

```
User double-clicks /compact
↓
Thread 1: force_llm_compact acquires _compaction_lock
Thread 2: force_compact blocks on _compaction_lock (NEW — was unlocked)
Thread 1: swaps strategy, runs compact, restores, releases lock
Thread 2: acquires lock, runs textual compact on restored strategy
→ No corruption
```

### Provider resolution (corrected precedence)

```
agent_def.llm_name = "anthropic"
conv.model = "openai/gpt-4o"
↓
resolved_model = "anthropic/claude-3-5-sonnet"  (llm_name WINS)
↓
_call_for_summary(model_id="anthropic/claude-3-5-sonnet")
→ uses Anthropic provider, not OpenAI
```

---

## 4. Acceptance Criteria

- [ ] `/compact @Coder` from a project tab compacts Coder's conversation (test: `test_cmd_compact_with_mention`)
- [ ] `/clear @Coder` from a project tab clears Coder's conversation (test: `test_cmd_clear_with_mention`)
- [ ] `/compact` without @Agent still works on current tab (test: `test_cmd_compact_without_mention`)
- [ ] `VALID_COMPACTION_STRATEGIES` constant exists in `utils/agent_defs.py` (test: import succeeds)
- [ ] `agent_builder.py` has no hardcoded `["textual", "llm"]` (test: grep returns 0)
- [ ] `force_llm_compact` acquires `_compaction_lock` (test: `test_force_llm_compact_acquires_lock`)
- [ ] `force_compact` acquires `_compaction_lock` (test: `test_force_compact_acquires_lock`)
- [ ] `_call_for_summary` uses `agent_def.llm_name` when set, overriding `conv.model` (test: `test_llm_name_overrides_conv_model`)
- [ ] ARCHITECTURE.md mentions `/compact` and `LLMSummarizeStrategy` in correct sections
- [ ] All existing 285+ tests pass

---

## 5. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| `/compact @Unknown` | Returns "No agent matching @Unknown" error (from `_resolve_mention`) |
| `/compact @` (bare @) | Returns broadcast error or compacts first member (existing behavior — not changed) |
| `/clear @Coder` | Clears Coder's conversation (destructive — no confirmation in this phase) |
| `/compact @Coder "focus on auth"` | Focus text passed through via `cmd.body` |
| Double-click /compact | Second call blocks until first completes (lock on both paths) |
| Agent with `llm_name="anthropic"`, `conv.model="openai/gpt-4o"` | Uses Anthropic (llm_name overrides) |
| Agent with no `llm_name` | Falls back to `conv.model`, then global default |
| `compaction_strategy: "hybrid"` in YAML | Validation rejects; dropdown shows "textual" |
| `agent_def=None` with `strat_name="llm"` | Falls back to `conv.model` → global default (defensive) |

---

## 6. Spec Self-Audit

1. **Code samples traced?** Yes — re-verified after Debugger audit. `cmd.target_session_key` already populated by `process_input` (no changes to command_handler.py needed). `_compaction_lock` at runtime.py:1647. `agent_builder.py` has 2 hardcoded lists (not 3). §3.21p.5 is context_strategy (not §3.21n).
2. **Exception types?** Lock is `threading.Lock` — blocks, doesn't raise. `_resolve_mention` returns `CommandResult` on error — already handled by `process_input`.
3. **Key structures?** `Command.target_session_key` is `str | None`. `_compaction_lock` is `threading.Lock`. `VALID_COMPACTION_STRATEGIES` is `tuple[str, ...]`.
4. **Data flow traced?** Yes — §3 shows @Agent targeting (consumer-side only), concurrency guard (both paths), and corrected provider precedence.
5. **Would this produce working code?** Yes — all changes are small, follow existing patterns, and the Debugger's 14 findings have been addressed.
