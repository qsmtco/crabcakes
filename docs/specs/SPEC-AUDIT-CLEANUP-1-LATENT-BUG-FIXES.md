# SPEC-AUDIT-CLEANUP-1 — Latent Bug Fixes (undefined names, label drift, audit-log leak)

**Loop authority:** `prompts/implementationLoop.md` + `prompts/implementationSupervisor.md`
**Builder playbook:** `prompts/steelFramedCodeWriter.md` — load fresh, follow every rule.
**Sources:** `docs/audits/dead-code-audit-2026-09-01.md` §4 + `docs/audits/2026-09-01-code-simplification-audit.md` §2-P3/§5-P2 — **every site below was re-verified against the live tree on 2026-09-07.** Line numbers are current.
**Precondition:** tree is clean at `d55b656` (pushed). Do not begin if `git status` is dirty.

**Tooling note:** pyflakes is available at `/tmp/pf-venv/bin/pyflakes` (3.4.0). Run:
`/tmp/pf-venv/bin/pyflakes agent ui models utils gateway scripts main.py | grep "undefined name"`
— this must return **zero** lines at the end of this unit.

---

## Classification (verified 2026-09-07)

The dead-code audit listed 23 undefined-name sites. Verification shows they split into **three classes**. Only Class A crashes today.

### Class A — real crash-class bugs (5 sites, fix first)

| # | Site | Bug | Fix |
|---|---|---|---|
| A1 | `gateway/client.py:118` | `logger.warning(...)` but module defines `_logger` (:30). No bare `logger` name exists. Crashes whenever device-auth.json is missing keys. | Grep the file for other bare `logger` uses; change all to `_logger`. |
| A2 | `ui/handlers/feed_handler.py:978` | `logger.warning("update_card: card %s not found", ...)` but module defines `_logger` (:31). Crashes on update_card for an unknown card id. | Change to `_logger.warning`. |
| A3 | `ui/handlers/review_handler.py:297-299` | `except Exception as e:` → `idle_add(lambda sk=sk, err=e: ... f"{type(e).__name__}: {e}")`. The lambda **body** references bare `e`; Python deletes `e` at except-block exit, so the deferred idle callback raises NameError — the error-report path itself crashes. | Use the captured default: `f"{type(err).__name__}: {err}"`. |
| A4 | `ui/handlers/chat_render_handler.py:281` | `except Exception as exc:` → `self._dispatch(lambda: on_error(str(exc)))`. Deferred lambda closes over deleted `exc` → NameError when `on_error` is provided and a render fails. | `lambda err=exc: on_error(str(err))`. |
| A5 | `ui/handlers/chat_render_handler.py:314` | Same pattern in `render()`'s `_build()`. | Same fix. |

### Class B — annotation-only (no crash today; fix for correctness)

All Class B sites are inside **quoted or `from __future__ import annotations`** annotations, which are never evaluated at runtime. pyflakes flags them because the names are never imported — the files would break under `typing.get_type_hints()`, IDEs, or any future un-quoting. Fix each with the **lightest correct import** (prefer `TYPE_CHECKING` where a runtime import would add cost or a cycle; direct import where the target module is already a runtime dependency).

| # | Site | Undefined name | Defined in | Suggested fix |
|---|---|---|---|---|
| B1 | `agent/persistence.py:42,134` | `Conversation` (quoted) | `models/conversation.py` | `if TYPE_CHECKING: from models.conversation import Conversation` |
| B2 | `ui/handlers/feed_handler.py:70,87,839,1243` | `Gtk` (annotations; file has future-annotations at :4) | `gi.repository.Gtk` | plain `from gi.repository import Gtk` — module already transitively pulls GTK via `ui.views.feed_card` (:25), so runtime cost is zero. |
| B3 | `ui/views/left_panel.py:191,195,199` | `FeedTab` (quoted) | `ui/views/feed_tab.py` | TYPE_CHECKING import (avoid ui↔ui cycle risk with window). |
| B4 | `ui/views/settings_dialog.py:359` | `SettingsHandler` (future-annotations present at :12) | `ui/handlers/settings_handler.py:33` | TYPE_CHECKING import (file already uses this pattern for `TestResult`). |
| B5 | `ui/handlers/chat_render_handler.py:324` | `Callable`, `FeedCardData` (quoted) | `typing`, `models/feed_card.py` | Import `Callable` directly from typing (zero cost); TYPE_CHECKING import for `FeedCardData`. |
| B6 | `ui/handlers/command_handler.py:240` | `MentionResolution` (quoted) | `models/command.py:22` | Direct import — :30 already imports from `models.command`. |
| B7 | `ui/handlers/auxilium_wizard_handler.py:355` | `ProviderConfig` (quoted) | `models/providers.py` | TYPE_CHECKING import (module deliberately import-light; header says so). |
| B8 | `utils/gtk_safe_link.py:84` | `Gtk.Label` (quoted return annotation; GTK import is deliberately deferred to :119) | `gi.repository` | TYPE_CHECKING import — do NOT add a top-level runtime GTK import; the deferred-import design is intentional (utils purity). |
| B9 | `utils/mcp_config.py:51` | `StdioServerParameters` (quoted; real import deferred at :60) | `mcp` SDK | TYPE_CHECKING import — same deferred-import rationale. |

### Class C — script annotation (1 site) — reclassified 2026-09-07 after verification

| # | Site | Bug | Fix |
|---|---|---|---|
| C1 | `scripts/rebuild_kb_index.py:170` | **Originally misdiagnosed as a runtime crash.** Verification: line 170 is the *quoted return annotation* `-> "np.ndarray"` on `embed_chunks`; the real numpy uses (:173, :234) are function-local imports that work fine. Quoted annotation is never evaluated → no crash; pyflakes flags it because `np` has no module scope. | `from typing import TYPE_CHECKING` + `if TYPE_CHECKING: import numpy as np` at module top. Numpy IS a project dependency (`agent/kb_lookup.py` imports it), but TYPE_CHECKING makes the fix zero-runtime-cost and pyflakes-clean. Do NOT add a module-level runtime import. |

---

## Bug 2 — Activity-label drift (fixes a live divergence)

`ui/views/activity_drawer.py:26` defines a local `_type_label()` whose docstring says "See models/activity.py._type_label for full docstring" — a keep-in-sync duplicate that **has already drifted**: per the simplification audit §5, the drawer copy omits `lifecycle_end` / `tool_*` mappings and a None guard that `models/activity.py:179` has. (Both copies verified present 2026-09-07.)

**Fix:**
1. Delete the local `_type_label` from `activity_drawer.py`.
2. Import from the model layer: `from models.activity import _type_label` — models must not import ui (architecture rule), ui importing models is correct direction. If the underscore bothers you, promote `models/activity.py._type_label` to a public `activity_type_label()` first, keep a thin `_type_label = activity_type_label` alias for any other in-file uses, and update both call sites.
3. `ui/views/activity_drawer.py:428` fallback (`row.get("type_label", "") or _type_label(...)`) keeps working via the import.
4. **Tests:** `tests/test_activity_drawer.py:106 test_type_label_mapping` — verify it still passes against the single implementation; extend it to cover the mappings the drifted copy was missing (`lifecycle_end`, `tool_start`, `tool_end`, `tool_error`, None guard) so the drift can't recur.

---

## Bug 3 — `AuditLog` unbounded in-memory growth (slow leak)

`agent/audit.py`: `AuditLog._entries` grows forever; `flush_audit_log()` (which clears after write) is called **only by tests** (`tests/test_agent_audit.py:35,47`). Runtime wires it at `agent/runtime.py:567` and records at 4 sites (:1756, :1776, :1846, and via `audit_log=` kwarg at :1819). In a long session this leaks memory indefinitely.

**Fix (both halves):**
1. **Cap:** in `AuditLog.record()`, after append, if `len(self._entries) > MAX_ENTRIES` (new module constant, `MAX_ENTRIES = 2000`), drop the oldest: `del self._entries[:len(self._entries) - MAX_ENTRIES]` (inside the existing lock).
2. **Auto-flush at turn end:** in `agent/runtime.py`, at the point where a turn completes (the same place `response complete` callbacks fire — find the single completion path in `_run_loop`), call `self._audit_log.flush_audit_log()` wrapped in `try/except Exception` with a `logger.exception` — audit flush must never break the turn.
3. Docstring of `AuditLog` must be updated to describe cap + auto-flush (the old text says "In-memory by default; flush to disk via flush_audit_log()").
4. **Tests:** add one test for the cap (record `MAX_ENTRIES + 500` entries → `len(log.entries) == MAX_ENTRIES`, oldest dropped) and one that the runtime completion path triggers flush (monkeypatch/spy). Existing `test_agent_audit.py` must stay green.

---

## Explicitly OUT of scope
- The dead-code sweep (SPEC-AUDIT-CLEANUP-2) — do not delete anything here.
- The perf throttling (SPEC-AUDIT-CLEANUP-3).
- `main.py` trailing dev comments, scratch scripts — sweep unit.

## Acceptance criteria
1. `/tmp/pf-venv/bin/pyflakes agent ui models utils gateway scripts main.py | grep -c "undefined name"` → **0**.
2. Class A fixes each have a regression test that would fail on the old code (for A3/A4/A5: a deferred-callback test that exercises the error path; for A1/A2: direct calls into the guarded paths).
3. Activity drawer renders every `ActivityType` value; `test_type_label_mapping` extended per Bug 2.4.
4. Audit-log cap test + turn-end flush test pass; `tests/test_agent_audit.py` green.
5. Full suite green (`pytest tests/ -B`; use `-B` per the stale-.pyc lesson).
6. No behavior change other than the 5 crash fixes becoming non-crashing, labels gaining missing mappings, and the audit log flushing/capping.

## Audit checklist (Debugger)
- For each Class A site: prove the crash exists on the pre-fix code (unit-level repro), then prove the fix.
- For each Class B site: confirm the fix is the lightest correct import, no new runtime import cycles (`python3 -c "import <module>"` smoke), and `TYPE_CHECKING` blocks are actually under `if TYPE_CHECKING:`.
- Bug 3: confirm the flush call is on the completion path for ALL completion outcomes (success, error, cancel) or document why not; confirm cap arithmetic (off-by-one check at exactly MAX_ENTRIES and MAX_ENTRIES+1).
- Re-run the pyflakes gate. Run the full suite. Paste real output.