# Audit Report: SPEC-activity-drawer.md

**Date:** 2026-06-05
**Auditor:** Qaster (M3)
**Spec:** `docs/specs/SPEC-activity-drawer.md` (98KB, 8 deliverables, 11 file changes, 23 acceptance criteria)
**Repo:** `/home/q/projects/crabcakes`
**Repo state at audit time:** working tree has 11 modified files + 1 new file (`ui/views/activity_drawer.py`), uncommitted. Last commit `ef9b1f0 docs: apply 4 audit fixes to SPEC-activity-drawer`.
**Test result:** `pytest tests/test_activity_bubbles.py` → 25/25 pass.
**Worked with:** QTR (spec author, Kage-7) on adjacent code

---

## TL;DR

**Implementation is ~80% complete and largely correct, but has 4 spec violations and is uncommitted.** The biggest issue is that the spec mandates the `command_output` branch in `ActivityHandler.on_gateway_event()` be **removed** (so `AgentRuntimeHandler` is the sole source), but the branch is still there. Compounding this, the `AgentRuntimeHandler.set_on_command_output` callback is **defined but never wired**, so local agent exec rows never reach the drawer with their `command`/`output` text. There are also 2 minor spec deviations in the `ActivityBubble.to_drawer_row()` output and the new `tests/test_activity_drawer.py` file is **missing**.

---

## 1. Deliverables (8 items from spec §1)

| # | Deliverable | Status | Notes |
|---|---|---|---|
| 1 | `ui/views/activity_drawer.py` — ActivityDrawer view | ✅ DONE | 680 lines, matches spec §2.2 spec |
| 2 | `ui/window.py._build()` rewrite — vertical Paned | ✅ DONE | Spec §2.3, lines 487-501 |
| 3 | Activity callback rewiring | ⚠️ PARTIAL | `set_on_activity_bubble` rewired; `set_on_agent_lifecycle` rewired; **`set_on_command_output` defined but never wired** |
| 4 | `ActivityBubble.to_drawer_row()` | ✅ DONE | Spec §2.1 — see minor deviations in §3 below |
| 5 | New fields on `ActivityBubble` | ✅ DONE | `agent_name`, `command`, `output`, `file_path` all present |
| 6 | Per-agent + per-type filter | ✅ DONE | Both dropdowns, AND semantics, default all-on |
| 7 | Lifecycle separators + click-to-expand | ✅ DONE | `_build_separator_widget`, `Gtk.Revealer`, last 10 lines |
| 8 | `set_on_agent_lifecycle` on ActivityHandler | ✅ DONE | Plus `_on_command_output` on AgentRuntimeHandler (not wired) |

**Score: 6.5/8 fully done, 1 partial, 1 structural issue.**

---

## 2. File-by-File Grading

### ✅ `models/activity.py` — Spec §2.1 — **DONE WITH 1 DEVIATION**

All 4 new fields (`agent_name`, `command`, `output`, `file_path`) appended at the end of the dataclass with `""` defaults — backward compatible. ✅
`to_drawer_row()` method present with all 12 spec keys, plus 6 extras (`agent_name`, `session_key`, `title`, `added`, `modified`, `deleted`). ✅
`_type_label()` and `_format_duration()` module-level helpers present. ✅

**Deviation #1 (minor):** `_format_duration` returns `""` for `ms <= 0` instead of `"0ms"` (spec §2.1 says "0 → 0ms"). The spec's drawer's `_format_summary` filters out `duration == "0ms"` (line 425 of activity_drawer.py), so the empty-string behavior makes the row show no duration, which is reasonable. Functionally equivalent, but the spec said `"0ms"`.

**Deviation #2 (minor):** `to_drawer_row()` uses `from datetime import datetime` **inside the method body** rather than the spec's `import datetime` at module top. Stylistic, not a defect.

### ✅ `ui/views/activity_drawer.py` — Spec §2.2 — **DONE**

File exists, 680 lines (spec estimated 430 — actual is +250, mostly extra docstrings + CSS class names). All public methods present:
- `__init__` ✅
- `append_event(row)` ✅ — line 171, counter-collapse, filter, trim
- `on_agent_start(sk, name)` ✅ — line 218, with double-separator guard
- `on_agent_end(sk, name)` ✅ — line 240, with summary using counter
- `clear_events()` ✅ — line 268, resets all state
- `toggle()` ✅ — line 290

Class constants match spec: `MAX_ROWS=100`, `TRIM_BATCH=25`, `DEFAULT_VISIBLE_PX=200`, `OUTPUT_LINE_CAP=10`. ✅

Row construction (`_build_row_widget`, `_format_summary`, `_build_revealer`, `_mutate_counter_row`, `_build_separator_widget`) all present and match spec. ✅

Filter machinery (`_show_filter_popover`, `_on_filter_all_toggled`, `_on_filter_value_toggled`, `_refresh_row_visibility`, `_passes_filter`, `_count_visible_rows`) all present with AND semantics. ✅

**Deviation #3 (cosmetic):** Row metadata is stored on `row_box._qtr_row_meta` (line 300) rather than the spec's `row_box._row_meta`. Same data, different attribute name. Intentional (per the `_qtr_` prefix, looks like QTR's style) — works fine.

### ⚠️ `ui/window.py` — Spec §2.3 — **MOSTLY DONE, 1 MISSING WIRE**

ActivityDrawer import added (line 31). ✅
Vertical `Gtk.Paned` wrapping `main_content` (lines 489-501). ✅
`set_on_activity_bubble` rewired indirectly via `connection_sync_handler.sync()` (which is spec-compliant — connection_sync_handler is the canonical post-connect wiring point). ✅
Project-switch clear hook: `self._activity_drawer.clear_events()` added to `set_on_project_opened` lambda (line 274). ✅
Lifecycle callback NOT wired in window.py — instead it's wired in `connection_sync_handler.sync()` (line 195). Spec §2.3 mentions only the bubble rewire here, so this is OK.

**Issue:** `set_on_command_output` from `AgentRuntimeHandler` is **never wired anywhere** (verified by grep — `connection_sync_handler.py` and `window.py` have zero references to it). Local agent exec rows will never reach the drawer with command + output.

### ⚠️ `ui/handlers/activity_handler.py` — Spec §2.4 — **DONE WITH 1 SPEC VIOLATION**

`_on_agent_lifecycle` callback state added in `__init__` (line 89). ✅
`set_on_agent_lifecycle(cb)` setter added (line 161). ✅
`agent_name` captured from `data.agentName` at top of `lifecycle` branch (line 271). ✅
Lifecycle callback fired for both `start` and `end`/`error` (lines 295, 312). ✅
`lifecycle_start` ActivityBubble includes `agent_name=_agent_name` (line 304). ✅
`tool_start`/`tool_end`/`tool_error` bubbles — **agent_name is NOT added** to the constructor call (lines 314-337). This is a spec violation — spec §2.4 lists this as one of "all 6 construction sites" needing `agent_name=agent_name,`.

**CRITICAL SPEC VIOLATION (Issue #1):** The `stream == "command_output"` branch in `on_gateway_event()` (lines 332-343) is **STILL PRESENT**. Spec §2.4 says:
> "The `command_output` branch in `ActivityHandler.on_gateway_event()` is REMOVED (no longer fires bubbles; AgentRuntimeHandler is the sole source)."

The spec's Verification Cheat Sheet explicitly checks:
```
grep -rn "command_output" ui/handlers/activity_handler.py | grep "data.get"  # should be ZERO matches
```
This grep returns 2 matches (lines 334, 336, 337, 338). **Spec is not satisfied.**

This is an **internal spec inconsistency** though — spec §2.10 keeps the test `test_command_output_end_fires_callback` which exercises this branch. The test would break if the branch were removed. So either:
- The test should have been removed (spec §2.10's list is incomplete), or
- The branch should have been kept (spec §2.4 is wrong).

**Recommendation:** the spec's intent is clear (AgentRuntimeHandler is the sole source), so the test should be removed and the branch deleted. The gateway-driven `command_output` event doesn't carry `command` or `output` text (per the spec's own discovery), so the gateway branch produces rows with empty `command`/`output` anyway. The local handler path is the one that matters for click-to-expand.

### ⚠️ `ui/handlers/agent_runtime_handler.py` — Spec §2.5 — **MOSTLY DONE, 1 MISSING WIRE**

`_on_command_output` callback state added (line 101). ✅
`set_on_command_output(cb)` setter added (line 108). ✅
`self._pending_exec_commands[session_key] = cmd` written in `_do_tool_call_start` (line 526, in `name == "exec_command"` branch). ✅
Callback fired in `_do_tool_call_result` (lines 615-630) with `cmd`, tail-to-10-lines of `output`, no exit_code/duration (signature is `(str, str, str)` not `(str, str, str, int, int)` as spec proposed — this is a deviation but signature is local to AgentRuntimeHandler so it's fine). ✅

**Deviation #4:** Spec §2.5 says callback signature is `cb(session_key, command, output, exit_code, duration_ms)` (5 args). Implementation uses `cb(session_key, command, output)` (3 args). Less information passed upstream, but the function is **not wired to anything**, so no test or runtime behavior depends on the signature.

**Issue #1 (again):** `set_on_command_output` is **never called** from `window.py` or `connection_sync_handler.py`. Dead code path.

### ✅ `ui/handlers/chat_handler.py` — Spec §2.6 — **DONE**

`_render_activity_bubble`, `_render_activity_bubble_impl`, and `set_on_activity_bubble` are all removed. Verified by grep — zero matches. ✅
The `from models.activity import ActivityBubble` import is also gone (the test file at line 1-13 still mentions it in docstring, but that's harmless).

### ✅ `ui/handlers/chat_render_handler.py` — Spec §2.7 — **DONE**

`render_activity` removed. Verified by grep — zero matches. ✅

### ✅ `ui/styles.py` — Spec §2.8 — **DONE**

Old `.activity-bubble` classes fully removed. Verified by grep — zero matches. ✅
New `.activity-drawer` classes all added (lines 979-1042). Covers drawer, header, row, row-{type} variants, output, separator. ✅

**Minor note:** Implementation uses `rgba(255, 255, 255, 0.03)` literal RGB values rather than the spec's `alpha(@theme_fg_color, 0.04)` GTK4 named-color syntax. Both work in GTK4, but the spec's form is theme-aware. Acceptable simplification.

### ✅ `docs/ARCHITECTURE.md` — Spec §2.9 — **DONE**

§2 directory structure: `activity_drawer.py` listed (line 129). ✅
§3.14j new subsection for `ui/views/activity_drawer.py` added (lines 790-829). ✅
§3 (model) updated — `ActivityBubble` mentions `to_drawer_row()` (line 265). ✅
§11 file inventory: `activity_drawer.py` listed (line 3045). ✅
§12 test file inventory: `test_activity_drawer.py` listed (line 3125) — but **the file doesn't exist** (see Issue #2).
§3.23 (handler) updated with `set_on_agent_lifecycle` mention (line 1827). ✅

**Note:** Spec §2.9 says update §3.7b, but implementation put it at §3.14j (existing numbering). Functionally equivalent.

### ⚠️ `tests/test_activity_bubbles.py` — Spec §2.10 — **PARTIALLY DONE**

Spec says: "Remove 5 tests in `TestChatHandlerActivityBubbleRender`". Implementation removed the 4 `_render_activity_bubble*` tests (per the docstring at line 285-288: "The 4 _render_activity_bubble tests were REMOVED in SPEC-activity-drawer Phase 1"). The 3 remaining tests in this class are NOT in the spec's remove list and exercise still-active code (`_handle_lifecycle_completed`, `_is_ui_active`).

`TestActivityBubbleModel` (9 tests) — kept, pass. ✅
`TestActivityHandlerActivityBubbles` (10 tests) — kept, pass. ✅
`TestChatHandlerActivityBubbleRender` — 3 tests, kept, pass. ✅
`TestSystemBubbleCSS` (3 tests) — kept, pass. ✅

All 25 tests pass. ✅

### ❌ `tests/test_activity_drawer.py` — Spec §2.10 — **MISSING**

Spec §2.10 mandates: "New file `tests/test_activity_drawer.py` with ~15 tests" (TestToDrawerRow, TestActivityDrawer, TestActivityHandlerLifecycleCallback). The file does not exist. ARCHITECTURE.md §12 references it (line 3125) but the file isn't there.

This is the **#1 test coverage gap** and blocks the spec's acceptance criterion 23.

---

## 3. Acceptance Criteria (23 items from spec §6)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `ActivityBubble` has 4 new fields | ✅ | models/activity.py:70-82 |
| 2 | `to_drawer_row()` returns all 12 fields | ✅ | models/activity.py:108-138 (returns 17, includes all 12) |
| 3 | `ui/views/activity_drawer.py` exists, instantiates | ✅ | 680 lines, file present |
| 4 | `append_event(row)` adds new row | ✅ | activity_drawer.py:171 |
| 5 | Consecutive same-(agent, type) collapses | ✅ | activity_drawer.py:195-198 |
| 6 | Different (agent, type) starts new row | ✅ | _last_row_key check at line 194 |
| 7 | `on_agent_start` inserts separator + breaks chain | ✅ | activity_drawer.py:218-235 |
| 8 | `on_agent_end` inserts summary + pops counter | ✅ | activity_drawer.py:240-264 |
| 9 | Lifecycle end for A doesn't break chain for B | ⚠️ | UNTESTED — no test file exists |
| 10 | Click-to-expand revealer with last 10 lines | ✅ | _build_revealer lines 348-389 |
| 11 | Agent filter dropdown with checkboxes, AND, default all-on | ✅ | _show_filter_popover |
| 12 | Type filter dropdown with checkboxes, AND, default all-on | ✅ | _show_filter_popover |
| 13 | Count label "N events" or "N visible / M total" | ✅ | _update_count_label |
| 14 | Clear button removes rows + resets state | ✅ | clear_events line 268 |
| 15 | Toggle button expands/collapses | ✅ | toggle line 290 |
| 16 | `set_on_agent_lifecycle` fires on lifecycle events | ✅ | activity_handler.py:161 + callbacks at 295, 312 |
| 17 | `set_on_command_output` fires after exec_command | ⚠️ | Function exists, NEVER WIRED |
| 18 | `command_output` branch in ActivityHandler REMOVED | ❌ | **STILL PRESENT** (lines 332-343) |
| 19 | ChatHandler 3 methods REMOVED | ✅ | grep returns 0 |
| 20 | ChatRenderHandler.render_activity REMOVED | ✅ | grep returns 0 |
| 21 | Old CSS classes REMOVED | ✅ | grep returns 0 |
| 22 | New CSS classes ADDED | ✅ | ui/styles.py:979-1042 |
| 23 | ARCHITECTURE.md updated (§2, §3, §11) | ⚠️ | Done, but §3.7b misnumbered as §3.14j (cosmetic); §12 references missing test file |

**Score: 19/23 fully satisfied, 3 partial, 1 hard fail.**

---

## 4. Spec Verification Cheat Sheet (spec §"Verification")

```
[ ] models/activity.py — new fields, to_drawer_row(), _type_label(), _format_duration()   ✅
[ ] ui/views/activity_drawer.py — NEW FILE, ActivityDrawer class                            ✅
[ ] ui/window.py — wrap in vertical Paned, rewire callback, wire lifecycle                 ⚠️  lifecycle wired in connection_sync_handler, not window.py; on_command_output not wired
[ ] ui/handlers/activity_handler.py — new setter, new state, agent_name on bubbles, REMOVE command_output branch   ❌  branch NOT removed; tool bubbles missing agent_name
[ ] ui/handlers/agent_runtime_handler.py — new setter, new state, capture command in start, fire callback in result   ⚠️  done but not wired
[ ] ui/handlers/chat_handler.py — REMOVE 3 methods                                          ✅
[ ] ui/handlers/chat_render_handler.py — REMOVE render_activity                            ✅
[ ] ui/styles.py — add new CSS, remove old CSS                                              ✅
[ ] docs/ARCHITECTURE.md — §2, §3.7b (new), §3.7, §3.21, §11, §12                          ⚠️  done except §12 lists missing test file
[ ] tests/test_activity_bubbles.py — remove chat-render tests                              ✅
[ ] tests/test_activity_drawer.py — NEW FILE                                               ❌  MISSING

Pattern sweep:
grep -rn "render_activity" ui/                          # 0 matches ✅
grep -rn "_render_activity_bubble" ui/                  # 0 matches ✅
grep -rn "activity-bubble" ui/styles.py                 # 0 matches ✅
grep -rn "set_on_activity_bubble.*chat_handler" ui/     # 0 matches ✅
grep -rn "command_output" ui/handlers/activity_handler.py | grep "data.get"   # 2 matches ❌
```

**Cheat sheet score: 3/5 pattern checks pass, 2 fail.**

---

## 5. Issues Summary (priority order)

### 🔴 P0 — Blocks spec completion

1. **`command_output` branch not removed from `ActivityHandler.on_gateway_event()`** (activity_handler.py:332-343)
   - Spec §2.4 explicitly says REMOVE; Verification Cheat Sheet flags it; ARCHITECTURE.md §3.23 still describes the old behavior
   - Fix: delete the `elif stream == "command_output":` block, OR keep it and update spec to allow dual-source

2. **`set_on_command_output` is defined but never wired**
   - AgentRuntimeHandler has the setter and fires the callback; nothing receives it
   - Local agent exec rows never reach the drawer with command + output
   - Fix: in `connection_sync_handler.sync()`, wire `agent_runtime_handler.set_on_command_output(lambda sk, cmd, out: drawer.append_event(...))` — needs a small adapter to build a dict matching the drawer's expected shape

3. **`tests/test_activity_drawer.py` doesn't exist**
   - Spec §2.10 mandates it; ARCHITECTURE.md §12 references it
   - Fix: create with the 15 tests outlined in spec §2.10

### 🟡 P1 — Spec deviations

4. **`tool_start`/`tool_end`/`tool_error` bubbles missing `agent_name`**
   - activity_handler.py:314-337 — `ActivityBubble(...)` constructor doesn't pass `agent_name=_agent_name` (the variable is in scope at line 271 but not used in the tool branches)
   - Fix: add `agent_name=_agent_name` to all 3 tool bubble constructor calls

5. **Spec internal inconsistency: test `test_command_output_end_fires_callback` kept**
   - If branch is removed (P0 #1), this test breaks
   - If branch stays, spec §2.4 is wrong
   - Resolution: remove the test along with the branch; update spec to reflect this OR keep both (gateway is the only path, not local)

### 🟢 P2 — Cosmetic / acceptable deviations

6. `models/activity.py:130` — `from datetime import datetime` inside method body instead of module top
7. `activity_drawer.py:300` — row metadata attribute `_qtr_row_meta` instead of spec's `_row_meta` (works, intentional?)
8. `_format_duration(0)` returns `""` not `"0ms"` (defensive behavior, downstream filter handles it)
9. CSS uses `rgba(255, 255, 255, 0.03)` literals instead of `alpha(@theme_fg_color, 0.04)` (theme-aware spec, literal impl — both work)
10. ARCHITECTURE.md new section is §3.14j not §3.7b (renumbered to fit existing structure)
11. `set_on_command_output` signature is `(sk, cmd, out)` not `(sk, cmd, out, exit, duration)` — moot since unwired

### 🟢 P3 — Process

12. Everything is uncommitted. Working tree has 11 modified + 1 new file.
13. ARCHITECTURE.md §12 mentions a test file that doesn't exist — should be removed from §12 inventory OR the test file should be created.

---

## 6. What to Do Next (recommendation)

For landing this spec correctly, in order:

1. **Create `tests/test_activity_drawer.py`** with the 15 tests from spec §2.10. Lowest risk, highest spec value.
2. **Add `agent_name=_agent_name` to tool bubbles** in `activity_handler.py:314-337`. 3-line fix, matches spec §2.4.
3. **Wire `set_on_command_output`** in `connection_sync_handler.sync()`. The adapter needs to construct an `ActivityBubble(command_output, ...)` and call `drawer.append_event(bubble.to_drawer_row())`. ~5 lines.
4. **Decide on the `command_output` branch** — either remove it from `ActivityHandler.on_gateway_event()` AND remove `test_command_output_end_fires_callback`, or keep both. Spec says remove; the local handler is the only path with `command` text.
5. **Re-run the verification cheat sheet** — all 5 pattern checks should pass, all 11 file deltas should be green.
6. **Commit** — the work has been done but is uncommitted.
