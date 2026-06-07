# Post-Mortem: Filter Dropdown Bug Fix Sprint (FILTERFIX-1 and FILTERFIX-2)

**Date:** 2026-06-07
**Duration:** ~50 minutes (23:35 – 00:30 PDT)
**Commits:** 2 on main (`3a0703a`, `40121d6`)
**Builder:** QTR — steelFramedCodeWriter prompt
**Supervisor:** Qaster — implementationSupervisor + adversarialDebugger prompts
**Final test result:** 1247/1249 pass (2 pre-existing failures unchanged)

---

## Code Quality Grade: A-

**Justification:** Both fixes are surgical, follow the codebase's existing GTK4 pattern (set_popover), and include regression tests. One real perf bug found in audit (unnecessary popover rebuild) was caught and fixed. The only deduction is for the counter-not-updated-for-filtered-events issue, which is a related but separate bug not in scope.

---

## What's Good

1. **QTR followed the existing GTK4 pattern.** The fix mirrors `chat_input_toolbar.py:212-238` exactly — build popover eagerly, call `set_popover()`. This is the proper GTK4 way and is consistent with the codebase.

2. **The refactor was clean.** Splitting `_show_filter_popover` into `_build_filter_popover_content` + `_refresh_filter_popovers` is the right separation of concerns. The old method was doing two things; the new ones do one each.

3. **The audit found a real perf bug.** The unnecessary-rebuild on every event is a genuine waste of CPU. The guard `if new_agent or new_type: self._refresh_filter_popovers()` is a clean one-line fix.

4. **QTR added a companion test** (`test_filtered_event_does_not_increment_visible_rows_but_still_counts`) that I didn't ask for. It guards against regressions in the counting semantics, which is exactly the right thing to verify when reordering code paths.

5. **The ordering fix is minimal.** Moving 4 lines of code (the known-set update + refresh) above the filter check is a surgical change. No collateral edits.

---

## What's Bad

1. **I specified the perf-bug pattern in the original spec.** The spec said "Add the call in append_event: After `self._known_agents.add(agent)` and `self._known_types.add(activity_type)`, call `self._refresh_filter_popovers()`." I didn't think about whether to call it on every event or only on change. The audit caught it, but it would have been better to specify it correctly the first time.

2. **The pre-existing stale comment** at line 92 (now corrected by me) said "Cleared on clear_events()" when it isn't. I fixed it inline as a 1-line edit. This is a sign that comment-driven development can propagate lies.

3. **The counter-not-updated-for-filtered-events bug** is a real issue I noticed during the audit but didn't fix because it was out of scope. The user can see filtered agents in the dropdown but `on_agent_end` will show wrong counts for those agents. This should be a future ticket.

---

## Bugs Found During Audit

| Bug | Found By | Phase | Severity | Description |
|-----|----------|-------|----------|-------------|
| Unnecessary popover rebuild | Qaster (adversarialDebugger) | FILTERFIX-1 audit | issue | _refresh_filter_popovers called on every event, not just when sets change |
| Counter not updated for filtered events | Qaster (adversarialDebugger) | FILTERFIX-2 audit | bug (latent) | Filtered events don't update _agent_counters, so on_agent_end shows wrong stats |
| Stale comment at line 92 | Qaster (adversarialDebugger) | FILTERFIX-1 audit | issue | "Cleared on clear_events()" claim was false; fixed inline |

**Audit rounds per fix:**
- FILTERFIX-1: 2 rounds (1 perf bug found in round 1, clean in round 2)
- FILTERFIX-2: 1 round (clean)

---

## Commits

```
40121d6 fix: track known agents/types before filter check (FILTERFIX-2)
3a0703a fix: filter dropdowns use set_popover pattern + only refresh on change (FILTERFIX-1)
```

---

## Lessons Learned

1. **Always check the GTK4 widget signal catalog.** The "activate" signal on `MenuButton` is a common copy-paste from `Gtk.Button` code. GTK4's introspection makes it easy to verify — `mb.emit("activate")` will succeed (the signal exists as a no-op) but clicking doesn't fire it. The fix is `set_popover()`, not signal connections.

2. **The adversarial audit catches what the spec misses.** I wrote the FILTERFIX-1 spec and missed the perf issue. The audit's job is to find what the spec got wrong, not just verify the spec was followed. This time, the audit paid for itself.

3. **Refactors that split methods often have ordering side-effects.** When the original `_show_filter_popover` was a single method, the order of operations was clear. Splitting it into build + refresh made the call site (`_refresh_filter_popovers()` in `append_event`) more prominent and exposed the perf issue.

4. **Filter-side effects on counters are subtle.** If a filter blocks an event, the row doesn't appear, but the user's mental model is "this event happened, it's just hidden." The counter for `on_agent_end` should still reflect all events, not just visible ones. This is a design issue worth thinking about — maybe counters should be tracked in a separate pass, decoupled from filter visibility.

---

## Recommendations for Future Work

1. **Fix the counter-not-updated-for-filtered-events bug.** The `_agent_counters` initialization (BUGFIX-3) should happen for ALL events, not just visible ones. This is a 2-line change: move the `agent_counter` init above the filter check, just like we did for `_known_agents`.

2. **Decide: should filters affect counter stats?** Two valid designs:
   - (A) Counters reflect ALL events (current intent post-FILTERFIX-2, but not implemented)
   - (B) Counters reflect VISIBLE events (current implementation, confusing UX)
   - Recommend (A) for consistency.

3. **Update ARCHITECTURE.md Section 3.8 (ActivityDrawer)** to document the filter architecture:
   - `_known_agents` / `_known_types` are global (see all events, regardless of filter)
   - `_visible_agents` / `_visible_types` are per-filter (see only events matching the filter)
   - These are separate concerns; mixing them causes the bugs we just fixed.

4. **Add a test for the MenuButton signal regression** in a CI test that runs on every widget setup. A test like `assert btn.get_popover() is not None` on all MenuButton instances would prevent this bug from coming back.
