# Phase 3 Verification Report

**Reviewer:** Qaster
**Date:** 2026-04-11
**Subject:** Phase 3 (Project Handler) extraction by Qrusher

---

## Summary

Phase 3 is structurally correct but has **one wiring bug** that will break project fan-out routing. Handler isolation, layer isolation, and tests all pass.

---

## What Was Done

- Created `ui/handlers/project_handler.py` (~150 lines)
- Created `tests/test_project_handler.py` (~120 lines, 15 tests)
- Updated `ui/window.py` to wire ProjectHandler
- All 146 tests pass (131 prior + 15 new)
- Handler isolation: PASS
- Layer isolation: PASS

---

## ✅ Correct Per Spec

1. **Correct ownership** — ProjectHandler owns `_active_project_name` and `_agent_to_project` per the extraction plan
2. **All three routing API methods** — `is_project_session()`, `get_project_for_agent()`, `get_project_members()` as specified
3. **No handler-to-handler imports** — ChatHandler doesn't import ProjectHandler; communication via shared `_agent_to_project` dict
4. **Thread safety** — `_dispatch()` wraps GTK calls via `GLib.idle_add()`
5. **Tests cover** open_project, toggle_agent, routing API, callbacks, edge cases (no active project, unknown agents)
6. **window.py delegates correctly** — `_on_project_opened` and `_on_project_members_changed` are now thin pass-throughs (`pass`); real logic lives in ProjectHandler

---

## 🟡 Bug: Duplicate `_agent_to_project` Initialization

**Location:** `ui/window.py` lines 59 and 127

Line 59 creates the dict and passes it to ChatHandler on line 80. Line 127 **re-creates it as a new empty dict**, orphaning the one ChatHandler holds:

```python
# Line 59 — first initialization
self._agent_to_project = {}

# Line 80 — ChatHandler gets the dict from line 59
agent_to_project=self._agent_to_project,

# Line 126-127 — DEAD CODE: re-creates new empty dicts, overwriting the reference
self._active_project_name = None  # dead — ProjectHandler owns this now
self._agent_to_project = {}       # NEW empty dict — ChatHandler still has the OLD one
```

**Impact:** Project fan-out routing is broken. ProjectHandler populates the *new* dict, but ChatHandler reads from the *old* one (always empty). Messages sent in project tabs will never reach members.

**Fix:** Remove lines 126-127 from `ui/window.py`. The `self._agent_to_project = {}` from line 59 is the correct shared instance.

---

## 🟡 Dead State in window.py

- `self._active_project_name` (line 126) — now owned by ProjectHandler, never read by window.py. Dead code.
- `self._agent_to_project` re-init (line 127) — see bug above.

Both should be removed.

---

## 🟡 ARCHITECTURE.md Not Yet Updated

`docs/ARCHITECTURE.md` needs a new section (3.16) for `ProjectHandler`, updated file inventory in Section 12, and the Phase 3 status recorded.

---

## Verification Checklist

| Check | Result |
|-------|--------|
| All tests pass | ✅ 146/146 |
| Handler isolation (no cross-imports) | ✅ PASS |
| Layer isolation (models/gateway no ui) | ✅ PASS |
| `project_handler.py` exists | ✅ |
| `test_project_handler.py` exists | ✅ |
| Routing API methods present | ✅ All 3 |
| No behavior changes (extraction only) | ✅ |
| `_agent_to_project` shared correctly | ❌ **Broken by duplicate init** |
| Dead state removed from window.py | ❌ Still present |
| ARCHITECTURE.md updated | ❌ Pending |

---

## Recommended Fix

```diff
--- a/ui/window.py
+++ b/ui/window.py
@@ -123,10 +123,6 @@
         self._gateway_handler.set_sync_callback(self._sync_gateway_to_chat_handler)
-        self._left_panel.set_on_project_opened(self._on_project_opened)
-        self._left_panel._file_tree.set_on_project_opened(self._on_project_opened)
-        self._left_panel.set_on_project_members_changed(self._on_project_members_changed)
-        self._active_project_name = None  # set when a project tab is opened
-        self._agent_to_project = {}  # {agent_session_key: project_name} — for routing
-        self._projects_module = __import__("utils.projects", fromlist=["projects"])
```

Wait — the `set_on_project_opened` and `set_on_project_members_changed` lines at 123-125 wire directly to window's methods, but lines 152-154 re-wire them to ProjectHandler. Lines 123-125 are also dead code (overwritten by 152-154). The `_projects_module` import at line 128 is still needed for ChatHandler but could be moved up.

**Minimal fix:**
1. Remove lines 123-127 (dead wiring + dead state)
2. Keep `_projects_module` import if ChatHandler still needs it directly
3. Run tests to confirm
4. Update `docs/ARCHITECTURE.md`
5. Commit
