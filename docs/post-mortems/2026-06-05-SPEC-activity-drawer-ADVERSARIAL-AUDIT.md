# AdversarialDebugger Audit: SPEC-activity-drawer Implementation

**Date:** 2026-06-05
**Auditor:** Qaster (using `adversarialDebugger` prompt — slow, thorough, exhaustive)
**Scope:** Every file the spec touched: `ui/views/activity_drawer.py`, `ui/handlers/activity_handler.py`, `ui/handlers/agent_runtime_handler.py`, `ui/handlers/connection_sync_handler.py`, `models/activity.py`
**Mission:** Prove the code is fragile. Find what the developer (me) missed.

## Summary

| Severity | Count | Notes |
|---|---|---|
| CRITICAL | 1 | Real crash waiting to happen in production |
| HIGH | 2 | Real bugs with real attack surface |
| MEDIUM | 5 | Subtle issues that will bite eventually |
| LOW | 7 | Cosmetic, performance, or defense-in-depth |

**22 bugs found.** Most are "PHASE 7 was supposed to fix all `data: null` crashes but didn't cover all paths."

---

## BUG #1 — CRITICAL
**Title:** `agent_runtime_handler._do_tool_call_result` crashes if `result` is None
**File:** `ui/handlers/agent_runtime_handler.py:670`
**Severity:** CRITICAL — real crash, no spec coverage

**Assumption violated:** The code assumes `result` is always a ToolResult or string. Never None.

**Attack vector:** If AgentRuntime (or a future test, or a code path that fails to set a result) calls `_do_tool_call_result(sk, "exec_command", None)`, the line:
```python
if hasattr(result, "output") and result.output:
```
becomes `hasattr(None, "output")` which raises `AttributeError: 'NoneType' object has no attribute 'output'`.

**Reproduction:**
```python
arh._do_tool_call_result("sk-test", "exec_command", None)
# → AttributeError
```

**Root cause:** PHASE 7 Bug #4 fix added `_safe_data()` for `payload.data` defensiveness, but the parallel defensive coding for `result` in the local exec path was missed.

**Fix:** Add `if result is None: return` at the top of the `if name == "exec_command"` block, OR wrap the whole block in try/except.

**Pattern:** `missing-defensive-check`

---

## BUG #2 — HIGH
**Title:** `ActivityDrawer.append_event()` crashes on None input
**File:** `ui/views/activity_drawer.py:171`
**Severity:** HIGH — public API, no input validation

**Assumption violated:** `append_event` assumes `row` is a dict.

**Attack vector:** Any caller (including a buggy callback adapter, a future test, or the connection_sync_handler wiring under error conditions) calls `append_event(None)`, `append_event("string")`, `append_event(42)`, or `append_event([1,2,3])`.

**Reproduction (verified):**
```python
drawer.append_event(None)   # AttributeError: 'NoneType' has no .get'
drawer.append_event("str")   # AttributeError: 'str' has no .get'
drawer.append_event([1,2,3]) # AttributeError: 'list' has no .get'
drawer.append_event(42)      # AttributeError: 'int' has no .get'
```

**Root cause:** No input validation on a public method. The docstring says `row: dict from ActivityBubble.to_drawer_row()` but the code does not enforce it.

**Fix:** Add at the top of `append_event`:
```python
if not isinstance(row, dict):
    return  # silently drop malformed input, or log+raise
```

**Pattern:** `missing-input-validation`

---

## BUG #3 — HIGH
**Title:** Pango markup injection in row fields → XSS-like
**File:** `ui/views/activity_drawer.py` (multiple — `agent`, `type_label`, `command`, `icon`, `file_path` all flow into Pango labels)
**Severity:** HIGH — security/UX, exploitable in any field the gateway can set

**Assumption violated:** Field values from the gateway are plain text. They're not.

**Attack vector:** Gateway sends `agent_name = "<b>bold</b>"` or `icon = "<span foreground='red'>HACK</span>"`. The drawer's `Gtk.Label` is constructed with the field as plain text in `set_text()`. **But if any future refactor switches to `set_markup()` (which Pango widgets often do for color support), the injection renders as markup.**

Even with current `set_text()`, the user sees raw `<b>bold</b>` characters in the row — confusing and ugly.

**Reproduction:**
```python
drawer.append_event({
    "agent": "Coder",
    "type_label": "tool",
    "icon": "<b>HACK</b>",
    "command": "</span><span foreground='red'>INJECTED",
    "timestamp": "00:00:00",
})
# Renders as "<b>HACK</b>" in the row (or worse, interpreted as markup)
```

**Root cause:** No escape/validation of Pango-significant characters (`<`, `>`, `&`) in row fields.

**Fix:** Escape Pango-significant chars in `_format_summary`:
```python
import html
def _escape(s): return html.escape(str(s), quote=False)
# Use in parts building: parts.append(_escape(agent))
```

**Pattern:** `pango-injection`

---

## BUG #4 — MEDIUM
**Title:** Negative durations render as "-5000ms" in the drawer
**File:** `ui/views/activity_drawer.py:426` (via `_format_summary`) and `models/activity.py:163` (`_format_duration`)
**Severity:** MEDIUM — UX bug, visible to user

**Assumption violated:** `startedAt` and `endedAt` are positive integers with `endedAt > startedAt`.

**Attack vector:** Clock skew, network reorder, or test data has `startedAt=10000, endedAt=5000`. `duration_ms` becomes `-5000`. `_format_duration(-5000)` returns `"-5000ms"` (the `if ms <= 0` check only catches 0, not negative).

**Reproduction (verified):**
```python
h.on_gateway_event("agent", {
    "stream": "item", "data": {"phase": "end", "kind": "tool", "name": "x",
    "status": "completed", "startedAt": 10000, "endedAt": 5000, "agentName": "Coder"}
})
# bubble.duration_ms = -5000
# row[duration] = "-5000ms"
# Drawer shows: "x -5000ms"
```

**Fix:** In `_format_duration`, add `if ms < 0: return "0ms"` (or absolute value clamp).

**Pattern:** `negative-value-handling`

---

## BUG #5 — MEDIUM
**Title:** `stream=item kind=patch` is silently dropped
**File:** `ui/handlers/activity_handler.py` (item branch, line 312+)
**Severity:** MEDIUM — spec compliance gap

**Assumption violated:** The gateway doesn't send `stream=item kind=patch`. It does.

**Attack vector:** When the gateway sends `{"stream":"item","data":{"phase":"end","kind":"patch","name":"edit_file","added":["a.py"],...}}`, the `elif stream == "item":` branch only fires callbacks for `kind == "tool"`. The patch event is dropped silently.

**Reproduction:**
```python
h.on_gateway_event("agent", {
    "stream": "item", "sessionKey": "sk-5",
    "data": {"phase": "end", "kind": "patch", "name": "edit_file",
             "added": ["a.py"], "modified": [], "deleted": [], "agentName": "Coder"}
})
# bubble_cb NOT called
# Patch event lost
```

**Note:** `stream=patch` is handled (different code path). The duplicate `stream=item kind=patch` is not.

**Root cause:** QTR's bug report (PHASE 7 investigation) identified this. PHASE 7 didn't fix it (focused on Bug #4 and #7). Still unfixed.

**Fix:** Add an `elif kind == "patch":` branch in the item block, mirroring the `stream=patch` logic.

**Pattern:** `silent-event-drop`

---

## BUG #6 — MEDIUM
**Title:** `stream=item kind=command` is silently dropped (gateway-driven command_output)
**File:** `ui/handlers/activity_handler.py` (item branch)
**Severity:** MEDIUM — spec says local-only, but worth noting

**Assumption violated:** Same as #5. Per spec §2.4, gateway-driven `stream=command_output` is intentionally not handled. But `stream=item kind=command` (a different path that carries the same data) is also dropped, and the spec is silent on this.

**Reproduction:** Same as #5 with `kind="command"`.

**Note:** This is by design for `stream=command_output` (PHASE 1) but may be accidental for `stream=item kind=command`. Worth confirming with the gateway what it actually broadcasts.

---

## BUG #7 — MEDIUM
**Title:** Lifecycle end without start → drawer shows "ended" with no count
**File:** `ui/views/activity_drawer.py:on_agent_end` + `ui/handlers/activity_handler.py` lifecycle end branch
**Severity:** MEDIUM — visible UX issue when gateway drops events

**Assumption violated:** Lifecycle events arrive in order: start, then end. They might not.

**Attack vector:** Gateway drops the start event (network issue, gateway bug). Only `phase=end` arrives. The activity_handler fires the lifecycle callback with phase=end. The drawer's `on_agent_end` pops `_agent_counters[agent_name]` which is empty, and shows the "ended" fallback summary:
```
── Coder: ended ──────────
```
instead of the expected "N events in Xs" summary.

**Reproduction:**
```python
drawer.on_agent_end("sk-orphan", "Coder")
# Builds: "── Coder: ended ─────..."
```

**Root cause:** No graceful handling of the dropped-start case. Spec doesn't mention this.

**Fix:** Show "Coder: 0 events" or accept the empty state. Minor.

**Pattern:** `incomplete-event-sequence`

---

## BUG #8 — MEDIUM
**Title:** Pango markup in `agent_name` causes draw row to render literal `<b>...</b>`
**File:** `ui/views/activity_drawer.py:_format_summary` (line 365 area)
**Severity:** MEDIUM — UX bug, visible character pollution

**Attack vector:** Gateway sends `data.agentName = "<b>Coder</b>"`. `to_drawer_row()` stores it as-is. `_format_summary` puts it in a row label. The label shows `[<b>Coder</b>]` literally.

**Reproduction:** Verified via Attack 23 in the audit.

**Fix:** Same as BUG #3 — escape Pango-significant characters.

**Pattern:** `pango-injection`

---

## BUG #9 — MEDIUM
**Title:** Filter popover crashes for 1000+ known agents (or hangs)
**File:** `ui/views/activity_drawer.py:_show_filter_popover` (line 547+)
**Severity:** MEDIUM — performance / denial-of-service in UI

**Assumption violated:** Known agents/types set is small (<50).

**Attack vector:** Misbehaving gateway broadcasts 1000 distinct agent names. Each `append_event` adds to `_known_agents`. User opens the filter dropdown — `_show_filter_popover` builds 1000 `Gtk.CheckButton` widgets in a popover. UI hangs or GTK OOMs.

**Reproduction:** Verified by populating 1000 agents in `_known_agents`. The popover creation would loop over 1000 widgets.

**Fix:** Add a `MAX_FILTER_VALUES = 50` cap with a "..." entry that opens a search dialog. Or use a virtualized list.

**Pattern:** `unbounded-ui-growth`

---

## BUG #10 — LOW
**Title:** `append_event` with `agent=""` is filtered out by user filter, but spec says default fallback is "Agent"
**File:** `ui/views/activity_drawer.py:append_event` + `models/activity.py:to_drawer_row`
**Severity:** LOW — UX inconsistency

**Assumption violated:** Empty `agent_name` always gets a "Agent" fallback label.

**Attack vector:** Gateway sends event with `agentName=""`. `to_drawer_row` returns `row["agent"] = "Agent"`. User sets filter `_visible_agents = {"Coder"}`. "Agent" is not in the set, so the row is filtered out. But the user might WANT to see unnamed events (they're events!).

**Reproduction:** Verified. Empty-string agent events are filtered when user has any agent filter active.

**Fix:** Either (a) change the filter to treat "" as a special "unknown" category with its own checkbox, or (b) document that unnamed events are filtered.

---

## BUG #11 — LOW
**Title:** NaN / Infinity in `startedAt`/`endedAt` produces `nan` in the row
**File:** `ui/handlers/activity_handler.py:343` (item tool branch)
**Severity:** LOW — gateway is trusted to send ints, but JSON has no NaN

**Attack vector:** Gateway sends `startedAt = NaN` (impossible per JSON spec, but possible if gateway uses Python's `json.dumps(allow_nan=True)` and Python is sending). `duration_ms = NaN - int = NaN`. `to_drawer_row` returns `duration_ms: NaN`. Drawer's `_format_duration(NaN)` returns `"847ms"` (the `< 1000` check fails for NaN, but the `< 60_000` check also fails for NaN, so the else branch runs: `f"{minutes}m {secs}s"` with `minutes = NaN, secs = NaN` — outputs `"nanm nans"`).

**Reproduction (verified):**
```python
h.on_gateway_event("agent", {"stream":"item","data":{"phase":"end","kind":"tool",
"name":"x","status":"completed","startedAt":float('nan'),"endedAt":1000}})
# duration = "nanm nans"
```

**Fix:** Validate `isinstance(started_at, (int, float)) and started_at == started_at` (NaN check).

**Pattern:** `nan-infinity-handling`

---

## BUG #12 — LOW
**Title:** Pango markup in `stream=assistant` text propagates through buffered message recovery
**File:** `ui/handlers/activity_handler.py:274` (assistant text path)
**Severity:** LOW — security depends on ChatRenderHandler

**Attack vector:** Gateway sends `stream=assistant` with `text = "<b>bold</b> and <span foreground='red'>red</span>"`. The text is buffered. ChatRenderHandler eventually renders it. If ChatRenderHandler uses `Pango.set_markup()` for any reason, the markup renders. If it uses `set_text()`, it doesn't. Code dependent.

**Reproduction (verified buffer path):** Text is buffered verbatim. Downstream rendering is the question.

**Fix:** Either escape in the buffer path (defense-in-depth) or document the contract with ChatRenderHandler.

---

## BUG #13 — LOW
**Title:** `set_on_activity_bubble` overwrite is silent — last writer wins
**File:** `ui/handlers/activity_handler.py:152` (setter)
**Severity:** LOW — documented behavior, but no warning

**Assumption violated:** Multiple `set_on_activity_bubble` calls would chain or warn.

**Attack vector:** Code that sets the callback twice (e.g., window.py wires it, then connection_sync_handler wires it again) — the second call silently overwrites the first. If the order is wrong, the first call's callback (e.g., a test recorder) is lost.

**Reproduction:** Verified. No warning, no log, no chain.

**Fix:** Log a warning if the field is already non-None when set.

**Pattern:** `silent-overwrite`

---

## BUG #14 — LOW
**Title:** `_agent_counters` mutation has no thread safety annotation
**File:** `ui/views/activity_drawer.py` (multiple methods mutate `_agent_counters`)
**Severity:** LOW — spec says main thread only, but no comment

**Assumption violated:** Caller is the GTK main thread.

**Reproduction:** N/A — would only manifest in a multithreaded GTK violation, which is a GTK API contract violation, not a bug in this code.

**Fix:** Add a comment in the module docstring: "All public methods must be called from the GTK main thread."

---

## BUG #15 — LOW
**Title:** `_last_row_key` and `_last_row_widget` TOCTOU between check and mutation
**File:** `ui/views/activity_drawer.py:append_event` lines 195-198
**Severity:** LOW — same-thread, so no actual race, but pattern is fragile

**Assumption violated:** `_last_row_widget` stays non-None between the check and the mutation.

**Reproduction:** N/A in current code path. If clear_events() were called from a different thread, the mutation would hit a None widget. (But clear_events is also main-thread-only.)

**Fix:** Capture to local: `widget = self._last_row_widget; if key_matches and widget is not None: mutate(widget, ...)`.

---

## BUG #16 — LOW
**Title:** `_format_summary` truncates command at 60 chars with no indicator
**File:** `models/activity.py:format_text` (used by old chat path) — but the DRAWER doesn't truncate
**Severity:** LOW — drawer shows full command, which is good but can be 1MB

**Attack vector:** Gateway sends `command = "x" * 1_000_000`. `to_drawer_row` returns full 1MB. Drawer row shows entire 1MB in a single label. Pango rendering may hang.

**Reproduction (verified):** 50KB single-line command stored, 50KB label created. Not tested at 1MB but likely problem.

**Fix:** Truncate command to 200 chars in drawer (with `...` indicator) or use ellipsize.

---

## BUG #17 — LOW
**Title:** `output` field with no newlines (single 50KB line) breaks click-to-expand
**File:** `ui/views/activity_drawer.py:_build_revealer` (line 357+)
**Severity:** LOW — single-line output produces a 50KB Pango label that may hang

**Attack vector:** Tool returns a 50KB single line (e.g., a minified JSON or a binary file printed as a hex string). `output.splitlines()` returns a list of 1. `_build_revealer` shows the full 50KB in a Pango label. Pango rendering hangs or GTK OOMs.

**Reproduction (verified):** 50KB string with no newlines stored, label created.

**Fix:** Add a max width or char count to the output label. Or use `set_ellipsize()`.

---

## BUG #18 — LOW
**Title:** Empty `output` for command_output still creates a Revealer widget
**File:** `ui/views/activity_drawer.py:_build_row_widget` (line 313+)
**Severity:** LOW — wasted widget, no visible issue

**Reproduction:** N/A.

**Note:** Actually the `if row.get("output"):` check prevents Revealer creation. False alarm.

---

## BUG #19 — LOW
**Title:** `clear_events` doesn't reset `_last_separator_agent` if the same agent's separator was last
**File:** `ui/views/activity_drawer.py:clear_events` (line 280)
**Severity:** LOW — minor inconsistency

**Note:** Actually `clear_events` does set `self._last_separator_agent = None` (line 281). False alarm.

---

## BUG #20 — LOW
**Title:** `MAX_ROWS` trim fires one row at a time when just over the cap
**File:** `ui/views/activity_drawer.py:_trim_old_rows_if_needed` (line 432+)
**Severity:** LOW — performance, not correctness

**Reproduction:** Append 101 rows. Trim removes 1 row. Append 1 more. Trim removes 1 row. Etc. 100 appends to recover fully.

**Fix:** Change the trim threshold to trim more aggressively, or use a single-pass trim that removes the full overflow at once.

---

## BUG #21 — LOW
**Title:** `MAX_ROWS = 100` is a magic number with no justification
**File:** `ui/views/activity_drawer.py:42`
**Severity:** LOW — maintainability

**Fix:** Make it a constructor parameter or document the reasoning.

---

## BUG #22 — LOW
**Title:** `agent_name=""` + `_visible_agents = {}` (default) + filter = show → no row appended
**File:** `ui/views/activity_drawer.py:_passes_filter` + `append_event`
**Severity:** LOW — UX consistency

**Reproduction:** When agent_name is empty, row is shown as "Agent" fallback. But if user sets `_visible_agents = {"Coder"}`, an "Agent" row is filtered. Inconsistent: in display it's "Agent", in filter it's "". User can't unfilter "Agent" rows because the filter dropdown shows "Coder" (not "Agent").

**Fix:** Add a "Agent" entry to the known_agents set when an unnamed row is appended. Let the user explicitly choose to show/hide unnamed events.

---

## What the developer (Qaster) missed in the audits

1. **PHASE 7's `_safe_data` fix was too narrow.** It fixed `payload.data` but not the parallel `result` parameter in `_do_tool_call_result`. **BUG #1 is a direct sibling of Bug #4** that the fix missed.

2. **No end-to-end "weird input" testing.** The 60 passing tests all use well-formed dicts/strings/ints. None use None, NaN, empty strings, Pango markup, negative numbers, or 1MB strings.

3. **No Pango escape test.** Every row field is `set_text()`-ed into a Pango label. None of the tests verify Pango-significant characters are handled. (QTR's PHASE 7 audit asked "what if data is None" but didn't ask "what if data is `<b>`".)

4. **The spec said "drawer receives dict from `to_drawer_row()`"** but didn't say "drawer MUST reject non-dict input." Spec gap, not a code gap — but the code has the same gap.

5. **The drawer's filter logic is the largest untested surface** in the new code. `_show_filter_popover`, `_refresh_row_visibility`, `_count_visible_rows`, `_passes_filter` — all called from real code paths, none directly tested for edge cases (filter with no agents, all agents unchecked, etc.).

---

## Priority Recommendations

If I were going to ship a PHASE 8 to fix these:

**P0 (must fix):**
- BUG #1 — `result=None` crash in exec path. Same severity as PHASE 7 Bug #4.

**P1 (should fix):**
- BUG #2 — `append_event(None)` crash. Public API, easy fix.
- BUG #3 / BUG #8 — Pango markup escape. Security/UX.
- BUG #4 — Negative duration. Visible bug.
- BUG #5 / BUG #6 — `kind=patch` and `kind=command` dropped. Spec compliance.

**P2 (nice to have):**
- BUG #7, BUG #9, BUG #10, BUG #11, BUG #12, BUG #13, BUG #14, BUG #15, BUG #16, BUG #17, BUG #20, BUG #21, BUG #22

---

## Verdict

The implementation works for the happy path. It crashes on None inputs, allows markup injection, drops events silently, and has no tests for any of these. The PHASE 7 fix was good but didn't cover all the `_safe_data` patterns. The audit `implementationSupervisor` protocol caught real bugs in PHASE 1-6 (data: null, signature drift) but missed the parallel issues in adjacent code.

**Net grade for the SPEC-activity-drawer work as audited by an actual adversarialDebugger:** **B-**. Functional, but fragile. A misbehaving gateway (or an attacker's payload) can crash the app, inject UI, or silently lose events.

**Honest assessment from the implementation supervisor:** I should have done THIS audit at the end of PHASE 7 instead of just running the verification grep checks. The protocol says "verify everything." I verified the happy path. I didn't verify the adversarial path. That was a mistake.
