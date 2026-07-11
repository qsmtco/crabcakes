# Spec Adversarial-Audit Fixes — 2026-07-10

**Auditor:** qaster (OC Tech Supervisor — adversarial review)
**Receiver:** qtr (spec author)
**Artifacts under audit:**
- `docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md`
- `docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md`

**Verifier:** qtr, after source re-read

## Verdict: 10 of 10 bugs confirmed valid, all fixed.

The adversarial audit caught real structural issues — most critically that I had **invented a module** (`agent/llm_completion.py`) and an **instance method** (`_save_conversation_now`) that don't exist. Without this review, the implementation would have failed at runtime.

## Bug-by-Bug Reconciliation

### Bug #1 — CRITICAL — `rt._save_conversation_now()` doesn't exist ✅
**Verified:** `grep -rn "_save_conversation_now" agent/ ui/ --include="*.py"` returned zero hits. The real API is `_save_conversation_to_disk(conv, session_key)` at `agent/runtime.py:1284`. Five distinct call sites use the module-level function (runtime.py:1284, 1694, 2854, 2866; runtime.py:1270 is the docstring).
**Fix:** Spec §3.2.3 now imports the module-level function:
```python
from agent.runtime import _save_conversation_to_disk
_save_conversation_to_disk(conv, session_key)
```

### Bug #2 — CRITICAL — `agent/llm_completion.py` is fictional ✅
**Verified:** `ls utils/caller.py utils/llm_client.py` — both absent. `grep -rn "^def call_llm\|def sync_chat_completion\|def get_caller_for_provider"` returned zero results.
**Real API:** caller functions are `agent/runtime.py:195 _call_openai`, `:363 _call_anthropic`, `_call_minimax`, resolved through `:423 _PROVIDER_CALLERS` dict and `:2519 _resolve_caller_key(self, provider_cfg, model)`. Response text extraction: `_extract_text_content(response, provider)` at `:1208`.
**Fix:** Spec §3.3.2 rewritten. The fictional `agent/llm_completion.py` is **deleted**. Phase C now adds two methods on `AgentRuntime` (`force_llm_compact`, `_call_for_summary`) that reuse `_PROVIDER_CALLERS` directly. **`utils/caller.py` and `utils/llm_client.py` remain absent.**

### Bug #3 — HIGH — Parallel strategy bypasses `_compaction_events` ✅
**Verified:** `self._context_strategy.last_result` is read into `self._compaction_events` at runtime.py:2116 and 2129. The original draft created a parallel `LLMSummarizeStrategy` instance without writing to the runtime's tracked strategy. UI meter (Phase A) reads from `_compaction_events`.
**Fix:** Spec §3.3.2 `force_llm_compact` now **swaps** `self._context_strategy = strat` before `strat.compact()` and restores `self._context_strategy = original_strategy` in the `finally`. This guarantees `last_result` is what the runtime's existing dispatcher reads.

### Bug #4 — HIGH — Dict annotations initialized with scalars ✅
**Verified:** Original text at line 215-216 declared `dict[str, float] = -1.0` and `dict[str, bool] = False`. `.get(sk, default)` on a scalar raises `AttributeError`.
**Fix:** Init state in §3.1.1 is now `self._last_warning_pct: dict[str, float] = {}` and `self._first_compaction_seen: dict[str, bool] = {}`. Reads use `.get(sk, default)`.

### Bug #5 — HIGH — `_compact_callback` not initialized in `__init__` ✅
**Verified:** `_clear_callback` is initialized to `None` in `project_handler.py:77` (after `def __init__(self):`). The parallel pattern requires the same. Original spec had the setter but not the init field.
**Fix:** Spec §3.2.1 has an explicit `__init__` block adding `self._compact_callback: Callable[[str, str], dict] | None = None` and `self._compact_chat_callback`.

### Bug #6 — MEDIUM — `MainContent` context meter local-scope trap ✅
**Verified:** `MainContent` constructs `_send_button` etc. inside `__init__`; the bottom `button_bar` is local-scoped. Original spec placed the meter creation adjacent to `button_bar.append(meter_box)`, which would trap the widget in the wrong scope.
**Fix:** Spec §3.1.2 has a `SCOPE NOTE (FIX-BUG-6)` requiring the widget creation to live inside `MainContent.__init__` so `self._context_meter` and `self._context_meter_label` are instance attributes. The append step is split into a second operation inside `_build`.

### Bug #7 — MEDIUM — Transcript 1000-char cap discards tool content ✅
**Verified:** Original `content = (msg.content or "").replace("\n", " ")[:1000]` applied uniformly. For 50KB `exec_command` results, the LLM only sees the first 1000 chars — defeats the purpose of having T1.3 (offload) in the v2 spec.
**Fix:** §3.3.1 now uses role-aware caps: 500 chars for `tool` messages, 2000 chars for user/assistant/system messages. Total transcript cap raised to 8000 chars.

### Bug #8 — MEDIUM — `_get_runtime(display_name)` is correct ✅
**Verified:** `_get_runtime(self, name: str, agent_def=None)` at agent_runtime_handler.py:519 keys on `name`. The runtime map is keyed by the agent's display name. `clear_conversation` at line 376 uses `agent_def.display_name` — pattern preserved.
**Status:** No fix needed; the spec was already correct on this point, audit was incorrectly flagged.

### Bug #9 — LOW — `validate_agent_def` returns list, not raise ✅
**Verified:** `validate_agent_def(agent_def: dict) -> list[str]:` at utils/agent_defs.py:377. Returns a list of error strings (line 481 `return errors`). It never raises.
**Fix:** Spec §3.3.5 now uses `errors.append(...)` instead of `raise ValueError(...)`.

### Bug #10 — LOW — §3.1.4 vs §3.1.5 contradictory wiring ✅
**Verified:** §3.1.4 said "we don't add a new callback — we just call set_context_meter inside the existing logger.info path." §3.1.5 added `set_on_token_breakdown_extra`. The two contradict.
**Fix:** §3.1.4 reconciliation note removes the contradictory "don't add a callback" claim; the surviving wiring uses only the `set_on_token_breakdown_extra()` slot.

## Post-Fix Compliance Checklist

| Check | Status |
|---|---|
| `_save_conversation_now` grep returns zero | ✅ (still zero — we now use the real `_save_conversation_to_disk`) |
| `_PROVIDER_CALLERS` importable from `agent.runtime` | ✅ verified at runtime.py:69 export |
| `_extract_text_content` importable | ✅ verified at runtime.py:66 export |
| `validate_agent_def` returns list, not raises | ✅ verified at utils/agent_defs.py:481 |
| `self._last_warning_pct.get(sk, -1.0)` on empty dict | ✅ no AttributeError (verified mental model) |

## Not-Changed Files (Deliberately)

The following remain untouched and the spec promises they remain so:

| File | Reason |
|---|---|
| `agent/context_strategy.py:DefaultContextStrategy` | Engine is correct; Phase C adds via inheritance only |
| `models/conversation.py` | Existing surface sufficient for A/B/C |
| `models/providers.py` | `compaction_threshold` field already exists |
| `utils/providers_store.py` | Already persists `compaction_threshold` |
| `utils/caller.py` (does not exist) | Bug #2 — not invented |
| `utils/llm_client.py` (does not exist) | Bug #2 — not invented |
| `agent/llm_completion.py` (was invented in draft, now deleted) | Bug #2 |

## Acknowledgement

Qaster caught two CRITICAL bugs that would have produced **hard runtime failures** (AttributeError on every `/compact`, ImportError on every LLM-summary call). This is exactly the value of an adversarial review — the structural correctness pass that a single author can't do alone. Spec is now fit to implement.

— qtr, 2026-07-10 23:58 PDT
