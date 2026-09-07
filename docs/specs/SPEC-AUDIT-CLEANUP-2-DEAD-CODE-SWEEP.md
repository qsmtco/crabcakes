# SPEC-AUDIT-CLEANUP-2 — Dead-Code Sweep (verified-dead corpus, ~2,000 LOC)

**Loop authority:** `prompts/implementationLoop.md` + `prompts/implementationSupervisor.md`
**Builder playbook:** `prompts/steelFramedCodeWriter.md` — load fresh, follow every rule.
**Sources:** `docs/audits/2026-09-01-code-simplification-audit.md` §1/§2-P1/§5 + `docs/audits/dead-code-audit-2026-09-01.md` §1-2 — **every deletion below was re-verified against the live tree on 2026-09-07.** Items that failed re-verification were removed from this spec.
**Precondition:** tree clean at `d55b656`. Depends on SPEC-AUDIT-CLEANUP-1 being merged first (both touch `agent/runtime.py`; bug fixes first, deletions second).
**Tooling:** `/tmp/pf-venv/bin/pyflakes` (3.4.0). Run the full suite with `pytest tests/ -B` (stale-.pyc lesson).
**Rule:** every deletion in this spec is grep-verified zero-reference. The builder re-runs the grep before deleting (tree may have drifted since 2026-09-07). If ANY reference is found, do not delete — report back.

---

## Drift corrections vs the audits (do not act on the stale claims)

1. **`utils/prompts.py` is NOT dead** — `ui/views/chat_input_toolbar.py:18` imports `load_prompts` from it. DO NOT delete. (The prompts-scanner dedup moves to the later utils refactor unit.)
2. **`scripts/audit_attack_scenarios.py` is NOT import-broken** — `_PROVIDER_CALLERS` still exists in `agent/runtime.py`. Its deletion below stands on the zero-reference one-off rationale only.
3. **Task system is NOT fully dead** — `ui/handlers/project_handler.py:635` (`cmd_status`, the `/status` command) reads `task_store.list_all()`. Phase 2 migrates this to `work_store` BEFORE deleting the task system.
4. **`set_approval_callback`** — two same-named functions: the **method** `AgentRuntime.set_approval_callback` (`agent/runtime.py:592`, field at :564) is dead (field never read; runtime passes per-call callbacks at :1830). The **module function** `agent/tools.py:70` is the live global fallback used by `tests/test_tools.py` (13 call sites) — DO NOT delete it.
5. **`chat_bubble.html_escape` is not a duplicate** of any utils function (no `html_escape` exists in utils) — it is an orphan. Delete it; say "orphan, no utils counterpart" in the commit, not "duplicate".

## Explicitly OUT of scope (deferred — do NOT touch)
- `ui/views/feed_tab.py:626` `_on_auto_accept_toggled` and the `feed_handler.py:195-278` legacy v1 auto-accept paths — live tests exercise them (`test_feed_handler.py:1846,1869,1904`); needs a product decision. Later unit.
- `gateway/client.py` `on_sent` param — audit says dead, but removing a public callback param from the gateway client is an API-surface change; later unit.
- Any refactor, any rename, any dedup. This unit deletes only.

---

## Phase 1 — Root scratch scripts (17 files, zero references)

Delete exactly these (verified: 18 root `.py` minus `main.py`):
```
_audit_verify.py  _test_htmlescape.py  _verify_phase1.py
diagnose_drawer_gap.py  inspect_filetree_drawer.py
extract_architecture.py  extract_context.py  extract_create_project.py
extract_prompt_section.py  extract_sections.py  extract_window_lines.py
find_inventory.py  find_lines.py  find_section.py
read_arch_section.py  read_bytes.py  read_section.py
```
Builder: `for f in <list>; do grep -rn "<basename>" --include='*.py' . | grep -v ".git" | grep -v "^./<f>" || echo "$f: clean"; done` — any hit outside the file itself = report, don't delete.

## Phase 2 — Task-system retirement (delete after migrating the one live consumer)

**Step 2a — migrate `cmd_status` first** (`ui/handlers/project_handler.py:631-652`):
- Replace `task_store.list_all()` + `t.assigned_to in members` filtering with `work_store.list_all()` + `u.assigned_builder in members`.
- Status mapping (user-facing line becomes `Work units: ...`):
  - `pending` = status in {draft, spec-pending, spec-ready}
  - `active` = status in {in-progress, auditing}
  - `blocked` = `blocked_reason` non-empty (any status)
  - `done` = status == done
  - cancelled units are excluded from the counts.
- Import `work_store` (models) — remove the `from models import task_store` line (:19).
- Update/extend the `cmd_status` test to cover the new mapping (pending/active/blocked/done buckets).

**Step 2b — delete the task system:**
- `ui/handlers/task_handler.py` (358 LOC; verified: zero instantiations — only a comment at `ui/window.py:611`)
- `models/task.py` (108 LOC)
- `models/__init__.py`: remove the `.task` import line, the `task_store = TaskStore()` singleton (:29), and all task entries from `__all__` (`Task`, `TaskStore`, `task_store`, `TASK_STATUS_LABELS`, `PRIORITY_LABELS`)
- `ui/window.py`: remove `from models.task import Task` (:53) and drop `task_store` from `from models import task_store, work_store` (:54) — verified import-only, zero body usage
- `tests/test_tasks.py`: delete entire file (tests only the deleted module)

## Phase 3 — Confirmed-dead functions & runtime dead code

Each verified zero-reference on 2026-09-07. Builder re-greps first (pattern = function name, exclude self-file and `.git`).

| What | Where | Note |
|---|---|---|
| `get_recent_commits` | `utils/git_ops.py:228` | duplicates `log` (:215) |
| `diff_stat_against` | `utils/git_ops.py:158` | audit's "3 refs" are gone (were scratch scripts); now zero |
| `hex_to_rgb` | `models/colors.py:127` | |
| `all_palette_css_classes` | `models/colors.py:110` | |
| `display_name_from_row` | `ui/views/session_menu.py:213` | |
| `html_escape` | `ui/views/chat_bubble.py:1113` | orphan, no utils counterpart |
| `_load_crabcakes_doc` | `agent/context.py:694` | docstring admits unused |
| `get_index_path` | `agent/kb_lookup.py:84` | only comment refs remain — update the module docstring (:20) when deleting |
| `DEFAULT_SKIP_PATTERNS` | `agent/enforcement.py:124-138` | real default lives in `EnforcementConfig.skip_patterns` (`agent/config.py`); `test_enforcement.py:573` mentions it in a **comment only** — update that comment to name the config field instead |
| `set_approval_callback` method + `_approval_callback` field | `agent/runtime.py:564, 592-594` | method+field never read; per-call path at :1830 is live. DO NOT touch `agent/tools.py:70` |
| unused locals | `agent/runtime.py:1799` (`workspace`), `:2659` (`tokens_after`) | remove the assignments |
| unused imports | `agent/runtime.py` (:16-32, :190-278 — `re`, `time`, `Iterator`, `AuditEntry`, `convert_*_for_anthropic`, SSL-retry constants, `urllib.*`), `ui/handlers/feed_handler.py` (:11 `dataclass`, :29 `ConversationSnapshot`), `ui/handlers/agent_runtime_handler.py` (:23 `FeedCardData`), `agent_runtime_handler.py:106-111` `_session_completed` (redundant with `_ended_sessions` — grep first, keep if referenced) | authoritative list = `/tmp/pf-venv/bin/pyflakes agent ui models utils gateway scripts main.py | grep "imported but unused"`; verify each with grep before removing; skip anything with a live reference |

## Phase 4 — Conversation shims + shim-only tests

`models/conversation.py:404` `trim_to_token_limit` and `:448` `_last_exchange_summary` are pure delegation shims to `agent.context_strategy.DefaultContextStrategy` (verified: bodies defer-import the strategy and forward). They violate the models→agent layer rule and are kept only for tests.

- Delete both shims.
- Delete shim-only tests: `tests/test_conversation.py:411-510` (the `trim_to_token_limit` test block) and `tests/test_phase4.py` §4.10 classes (`_last_exchange_summary` tests at :203-275 and the trim-integration tests at :280-385).
- **Before deleting each test class, confirm the equivalent behavior is covered by the strategy tests** (`tests/test_context_strategy*.py`, `tests/test_llm_summarize_strategy.py`, `tests/test_runtime_compaction.py`). If any assertion is unique (e.g. summary-injection on trim), migrate it to a strategy-level test FIRST, then delete. Report the coverage check in your summary.
- Update `models/conversation.py:322` docstring reference ("see trim_to_token_limit") to point at `DefaultContextStrategy.compact`.

## Phase 5 — Scripts, comments, pycache

- Delete `scripts/audit_attack_scenarios.py` (128) and `scripts/audit_streaming_scenarios.py` (287) — zero-referenced one-off Phase-11 scratch; git history preserves them.
- Delete `scripts/bulk_repair_empty_assistant.py` (194) — one-shot migration confirmed complete by its post-mortem.
- `main.py:59-62`: delete the four trailing dev comments (`# test change`, `# actual test change`, `# new uncommitted change`, `# another test`).
- Housekeeping: `find agent knowledge ui models utils gateway scripts -name __pycache__ -type d -exec rm -rf {} +` plus any root `__pycache__` (dead-code audit housekeeping item; also prevents the stale-.pyc trap).

---

## Acceptance criteria
1. `pytest tests/ -B` — full suite green (minus the deliberately deleted tests; count them in the summary).
2. `/tmp/pf-venv/bin/pyflakes agent ui models utils gateway scripts main.py` — no NEW findings vs the pre-unit baseline; the "undefined name" count stays 0 (SPEC-1's gate) and flagged unused-imports from the Phase 3 list are resolved.
3. App import smoke: `python3 -c "import main"` succeeds (or the project's standard smoke equivalent); `python3 -c "from models import work_store"` succeeds; `python3 -c "import ui.window"`.
4. `git grep -l "task_store\|models.task\|TaskHandler\|task_handler"` returns nothing outside `docs/` and `.crabcakes/` (docs may reference history).
5. `/status` in a project tab shows Work-unit counts (verify via its unit test, not manually).
6. Net LOC deleted reported in the summary; no file outside the spec's lists was modified.

## Audit checklist (Debugger)
- Re-run the per-item grep for EVERY deletion (the builder's report must include them; verify independently). One live reference = SEND-BACK.
- Confirm Phase 2 ordering: cmd_status migrated + tested BEFORE task files deleted (check commit order or diff coherence).
- Confirm no deleted test covered behavior that no longer has coverage: diff the strategy-test coverage against the deleted §4.10 assertions.
- Confirm `agent/tools.py` `set_approval_callback` and the per-call approval path are untouched; run `pytest tests/test_tools.py -B`.
- Run the full suite yourself; paste real output. Check `git status` for stray files.