# SPEC: UI Responsiveness 3 — Rendered-Body Cap + Idle-Pulse Containment

**Date:** 2026-09-12
**Author:** Lt. Qrusher (external verification & profiling), per PM direction
**Status:** Draft — for PM review before implementation
**Depends on:** `SPEC-UI-RESPONSIVENESS-2` Phases 1–5 (landed; `bf0fe54`)
**Work orders:** `docs/specs/UIRESP2-T2-PHASE-1-INSTRUCTIONS.md` (Phase 1, as *Unit D*), `docs/specs/AGENTCTRL1-PHASE-1-INSTRUCTIONS.md` (unrelated unit, listed for tree context)
**Related:** `docs/specs/UIRESP2-PHASE1-3-LIVE-VERIFICATION-ADDENDUM.md`, `docs/specs/UIRESP2-P45-INSTRUCTIONS.md`
**Target branch:** main

> **Why this document exists.** The live native profile taken on 2026-09-12 proves that the residual
> main-thread burn is **not** in the Python feed path that Phases 1–5 fixed. It is in the GTK
> main loop, and two distinct causes are identified below. This spec is the durable record of
> both, including the numbers, so the evidence is not lost with the session that produced it.

---

## DISCOVERY (measured evidence — all figures reproducible)

### D1. Profile of the running app, 60 s, native frames

Command (note: `--native` is mutually exclusive with `--nonblocking`):

```
sudo env "PATH=$PATH" py-spy record -o /tmp/crab-native.svg --pid <pid> --duration 60 --native
```

Root totals, **7,089 samples**:

| Frame | Samples | Share |
|---|---|---|
| GTK main loop — `g_main_context_iteration` | 5,992 | **84.5 %** |
| `gtk_widget_allocate`, recursing ~16 frames deep | 5,992 | 84.5 % |
| `gtk_layout_manager_measure` | 5,992 | 84.5 % |
| **`pango_layout_get_size` (text measurement)** | 4,259 | **60.1 %** |
| — `g_utf8_strlen` | 1,495 | 21.1 % |
| — `pango_shape_item` → `hb_shape_full` (harfbuzz) | 932 | 13.1 % |
| Worker threads (agent runtime, feed persist, tiktoken) | ~1,097 | 15.5 % |

Hot path: `main.py:69 → main.py:63 → Gio.py:42 (Application.run) → ffi_call →
g_application_run → g_main_context_iteration → g_signal_emit → g_closure_invoke →
gtk_widget_allocate (×~16) → gtk_layout_manager_measure → pango_layout_get_size`.

**Conclusion:** the cost is GTK measuring and allocating a deeply-nested widget tree, dominated
by **text layout**. Not Python, not `feed_store`, not disk.

### D2. The spin is independent of input

Two independent 120 s per-thread samples (`/proc/<pid>/task/<tid>/stat`):

| Metric | Run A | Run B |
|---|---|---|
| Main-thread CPU | 99.8 % | **100.0 %** (24/24 five-second windows) |
| Main-thread state | R in 240/240 | R in 240/240 |
| `wchan` | `0` (running) | `0` (running) |
| Card arrivals during window | −2 | **0** |
| feed.json rewrites | 3 | **0** |

15 s delta while pinned: **0 voluntary context switches** (⇒ no syscalls at all), **0 minor
faults** (⇒ no allocation), 196 involuntary switches (preemption only).

**Conclusion:** a pure userspace loop that makes no syscalls and allocates nothing, running
**while the application is completely idle** — last card 22 minutes before the measurement.
This rules out the disk path, JSON parsing, and load-driven relayout as the proximate cause.

> Method note: an earlier internal measurement read `/proc/PID/stat` and labelled it "main thread".
> That file is **process-wide**. All figures above come from per-thread
> `/proc/PID/task/<tid>/stat`. Do not use `/proc/PID/stat` for main-thread attribution.

### D3. Card body-text distribution (`.crabcakes/feed.json`, 3,464 cards, ~1.27 M chars)

| Agent | cards | median | p90 | p99 | max |
|---|---|---|---|---|---|
| Coder | 1,090 | 190 | **2,000** | **2,000** | 9,774 |
| Debugger | 1,077 | 100 | 1,919 | 2,162 | **22,714** |
| Supervisor | 562 | 200 | 949 | 2,000 | 2,556 |
| other | 735 | 45 | 71 | 80 | 82 |

Coder p90 **and** p99 landing on exactly 2,000 (n=1,090), and Supervisor p99 = 2,000, is strong
evidence that a **2,000-character truncation already exists** somewhere in the pipeline.

**But it is bypassed.** Cards over 5,000 chars: **4 total**.

- Debugger: 2 cards, 39,682 chars — max **22,714 chars / 521 lines**, the full text of a Python
  test file written via heredoc (`cat > .crabcakes/tmp/uiresp2-audit/tests/probe_audit2.py <<'PYEOF'`)
- Coder: 2 cards, 16,173 chars — max 9,774

All four are `⚠️ <Agent> requests approval to run command` cards.

> **Status: VERIFIED (Supervisor, 2026-09-12, tree at `d51b71a`) — no longer inferred.**
>
> - **The cap exists, producer-side:** `ui/handlers/agent_runtime_handler.py:1583` in
>   `_do_tool_call_result` — `display = output_text[:2000]`. It applies **only** to tool-result
>   cards, and it truncates **before storage** (`card.body = display`), so tool-result storage is
>   already lossy today.
> - **The bypass:** `_do_approval_needed` (`:1745-1786`) sets `body=f"$ {command}"` at `:1773` with
>   **no cap** ⇒ the 22,714-char heredoc card. Every other unbounded `body=` construction site in
>   `ui/handlers/*.py` has the same exposure and must be swept.
> - **No test pins the tool-result cap** — the `2000` values in `tests/test_feed_handler.py` are
>   scroll-adjustment values. `crabcard` export and `_make_copy_cb` (`:2407`) read
>   `card_data.body` and are storage-side, so a render cap does not affect them.
>
> **Consequence for Phase 1:** the "keep the full text stored" requirement is achievable for
> **approval cards** (whose full body is stored) but **not** for tool-result cards, whose storage is
> already truncated at 2,000 by `:1583`. Phase 1 must not make that worse, and must not promise a
> reveal affordance for text that was never stored. Deciding whether to *un*-truncate tool-result
> storage is a separate question (see §10).

### D4. The idle-pulse loop (verified in code)

`ui/handlers/activity_handler.py`:

- **:641** — on every state transition: `self._status_ticker_id = self._GLib.timeout_add(250, self._status_tick)`
- **:727** — `_status_tick()` returns **`True` for `state == "idle"`**, so the timer re-arms forever
- **:769** — `_idle_pulse()` is explicitly documented *"ANIMATION: never skip-gated. The pulse must
  advance on every tick even when state/phase/hops are unchanged (a skipped pulse is a frozen bar)."*
  and calls `self._feedbar.pulse_progress()`

`ui/views/feedbar.py`:

- **:76** — `set_progress_hidden(hidden)` sets **`set_opacity(0)`**, *not* `set_visible(False)` ⇒ the
  "hidden" bar remains in the widget tree and is still traversed
- **:94** — `pulse_progress()` → `self._progress_bar.pulse()`

**Mechanism (coherent with every measurement, not yet proven):**

1. State settles to `idle` after a round completes
2. The 250 ms ticker fires, `_idle_pulse()` runs, and the tick returns `True` ⇒ the timer never dies
3. `GtkProgressBar.pulse()` invalidates ⇒ GTK frame clock ⇒ render/allocate traversal
4. The window holds **3,525 card widgets**; the traversal walks them all and pango lays out their text
5. Each traversal costs ≥250 ms ⇒ the loop never catches up ⇒ **100 % CPU, indefinitely**

This accounts for: the pin occurring **while idle**, zero syscalls, zero allocation, pango
dominance, independence from card arrivals, onset after the feed grew large, and onset *after* a
round finishes (state `done` → `idle`).

### D5. Related config finding (already actioned — Tier 1)

`~/.config/crabcakes/agents/debugger.yaml` had **no `write_file` and no `edit_file`** (Coder has
both). The Debugger therefore wrote every file through `exec_command` shell heredocs, each requiring
an approval whose card body contained **the entire file**.

- Debugger heredoc cards: **63 (5.8 %)**, carrying **122,651 chars = 25.5 % of all Debugger text**
- Coder: 17 (1.6 %), 33,401 chars (6.1 %)  ·  Supervisor: 15 (2.7 %), 17,025 chars (8.2 %)
- Debugger tool mix: **1,037 of 1,077 cards are `exec_command` (96 %)**

**Fixed 2026-09-12 08:49** by adding `edit_file` + `write_file` to `debugger.yaml`. Requires a
registry reload or app restart to take effect. Not yet proven in live use (only 1 Debugger card
since the change; 0 heredocs, 0 cards >5,000 chars in that window — consistent, but a sample of one).

---

## 1. Overview

### 1.1 Problem

`SPEC-UI-RESPONSIVENESS-2` Phases 1–5 removed the Python-side feed bottleneck (journal writes,
bounded lock, pruning, off-thread persistence). Verified: worker threads now account for only
~15 % of samples and the feed path is no longer on the main thread.

The remaining burn is different in kind: the application pegs a full CPU core **while idle**, with
no syscalls and no allocation, inside GTK's layout/render traversal — 60 % of it spent measuring
card text across a 3,500-card, non-virtualized widget tree.

### 1.2 Solution

Two independent, bounded fixes, each targeting one measured cause:

- **Phase 1 — Rendered-body cap.** Cap what is *rendered* at 2,000 chars (already the de-facto
  limit elsewhere), keep the full text *stored*, and make the truncation visible and reversible.
  Attacks the 60 % text-layout share directly.
- **Phase 2 — Idle-pulse containment.** Bound the idle pulse so the 250 ms ticker stops when there
  is nothing to animate. Removes the self-sustaining loop that keeps the expensive traversal
  running forever.

### 1.3 Scope

| In | Out |
|---|---|
| Locating the existing 2,000-char truncation and the approval-card bypass | Virtualizing the feed (follow-on, §8) |
| Rendered-body cap + reveal affordance | Changing what is stored in `feed.json` |
| Bounding/terminating the idle pulse | Redesigning the activity state machine |
| Calibrating card count to measured cost | Any new listener, daemon, or network surface |
| A repeatable performance probe + acceptance gate | Performance work outside the feed/status UI |

### 1.4 Principles

- **Measure, then change.** Both phases carry a measured acceptance gate (§7); no phase ships on
  reasoning alone.
- **Never hide information the user must act on.** An approval card's full text must be reachable
  before the decision is made.
- **Storage is not the problem.** The feed is bounded and correct after `UIRESP2` Phase 3. These
  fixes are about *rendering* cost, and must not alter persistence semantics.
- **No unbounded loops.** Any animation-driven work must terminate on its own.

---

## 2. Phase 1 — Rendered-body cap

### 2.1 Step 1 — locate the existing cap — **DONE (see D3)**

Completed by the Supervisor on 2026-09-12. The cap is producer-side
(`agent_runtime_handler.py:1583`, tool-result cards only, applied **before storage**) and the
approval-card bypass is `_do_approval_needed` (`:1773`, `body=f"$ {command}"`, uncapped).

**Remaining sub-task — the sweep.** Enumerate **every** `body=` construction site in
`ui/handlers/*.py` and report which are unbounded. The approval card is the worst offender at
22,714 chars, but it is unlikely to be the only uncapped site. This list is a deliverable.

**Work order:** this phase is already actioned as **Unit D** in
`docs/specs/UIRESP2-T2-PHASE-1-INSTRUCTIONS.md`. That document is the implementation instructions;
this spec is the durable record of the evidence and acceptance gate. Where they differ, the work
order governs the *how*, this spec governs the *why* and the *gate*.

### 2.2 Step 2 — cap rendering, not storage

- Truncate the **rendered** body at 2,000 chars. `feed.json` and card metadata keep the **full**
  text — approval decisions and the audit trail depend on it.
- Truncation must be **visibly indicated and reversible**: show `… N more characters` with a
  control to reveal the full text.
- For a card **awaiting approval**, the full text must remain reachable **before** the decision is
  made. Do not hide information the approver needs to make the call.
- Must compose with the Phase 4+5 **in-place update** path: an update that changes a body must
  re-evaluate truncation state rather than leaving a stale expanded/truncated render.

### 2.3 Step 3 — preserve existing behaviour

Text search/filtering over cards, copy-to-clipboard, and the approve/reject affordance must all
continue to work against the full stored text.

### 2.4 Invariants

1. Stored body text is never truncated by this change.
2. Truncation is never silent — the amount hidden is always visible.
3. An approver can always reach the full text before approving.
4. No regression to the existing 2,000-cap tests (identify them first).

---

## 3. Phase 2 — Idle-pulse containment

### 3.1 Bounded pulse

The idle branch of `_status_tick` (`activity_handler.py:739-741`) must stop re-arming. Recommended
shape — preserves the intended visual, removes the unbounded loop:

```python
if self._state == "idle":
    self._idle_pulse()
    self._idle_ticks = getattr(self, "_idle_ticks", 0) + 1
    return self._idle_ticks < 20      # ~5 s of pulse, then stop
```

`_idle_ticks` must reset on every state transition. The ticker must still start correctly on the
next transition into an active state.

### 3.2 Remove the "hidden" widget from traversal

`feedbar.py:76` should use `set_visible(False)` in addition to (or instead of) `set_opacity(0)` when
hidden, so a hidden progress bar is not walked by layout/render. Verify no caller depends on the
bar remaining visible-but-transparent.

### 3.3 Invariants

1. No animation-driven timer runs indefinitely in any state.
2. A hidden progress bar is not traversed.
3. The active-state live-update path (`_live_update`, signature-gated) is unchanged.
4. No visual regression to the active-state counters.

---

## 4. Calibration (conditional, PM decision)

If Phase 1 + Phase 2 do **not** bring the main thread under the §7 gate, the remaining lever is the
number of live card widgets. Two options, in cost order:

1. **Bound rendered cards** — render the newest *N*; provide "load more". Cheapest structural bound.
2. **Virtualize** — `GtkListView`/`GtkColumnView` over a `GListModel`, so only visible cards exist
   as widgets. Turns O(all cards) into O(visible). Correct end state; largest change; see §8.

PM decides after the Phase 1/2 measurement, not before.

---

## 5. Test plan

Red-first. Phase 1 tests must not require GTK unless they genuinely exercise rendering.

### Phase 1

| Test | Asserts |
|---|---|
| `test_rendered_body_capped_at_2000` | A 22,714-char body renders ≤2,000 + indicator |
| `test_stored_body_unchanged_by_render` | Stored body still exactly 22,714 after render |
| `test_truncation_indicator_reports_hidden_count` | Indicator reports exactly `N` remaining chars |
| `test_approval_card_full_text_reachable_before_decision` | Full text obtainable on an undecided card |
| `test_body_of_exactly_2000_unchanged` | No off-by-one |
| `test_inplace_update_reevaluates_truncation` | Oversized→small update collapses the reveal state, and vice versa |
| `test_search_operates_on_full_text` | Filtering still matches text beyond the render cap |

### Phase 2

| Test | Asserts |
|---|---|
| `test_idle_tick_terminates` | Idle branch returns `False` within the bounded tick count |
| `test_idle_ticks_reset_on_state_change` | Counter resets; the next active state ticks normally |
| `test_active_states_unaffected` | `reasoning`/`streaming`/`tool_use` still return `True` and update |
| `test_hidden_progress_bar_not_visible` | `set_progress_hidden(True)` ⇒ widget not visible |

### Performance regression test (both phases)

| Test | Asserts |
|---|---|
| `test_main_thread_idle_budget` | With a ≥3,500-card fixture and the app idle, main-thread CPU stays under the §7 budget over a 60 s sample |

---

## 6. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Approval card hides text the approver needs | **HIGH** | Full text reachable before decision; explicit test |
| Cap applied to storage instead of rendering | HIGH | Stored-body immutability test |
| Idle-pulse change breaks active-state counters | MEDIUM | Active states untouched; dedicated tests |
| The pulse hypothesis is wrong | MEDIUM | §7 gate plus the discriminating test in §7; Phase 1 stands alone |
| Truncation breaks in-place update path (Phase 4+5) | MEDIUM | Explicit re-evaluation test |
| 2,000-char cap does not actually exist in code | LOW | Step 1 requires locating it first; D3 is marked inferred |

---

## 7. Success criteria — measured, not asserted

**Baselines recorded 2026-09-12** (PID 1274483, Phases 1–5 build):

| Metric | Baseline |
|---|---|
| Main-thread CPU, pinned | **99.8 % / 100.0 %** sustained |
| `pango_layout_get_size` share of samples | **60.1 %** |
| Main-thread CPU, healthy idle | 2–6 % |

**Gate:**

- [ ] Idle, ≥3,500 cards: main-thread CPU **< 10 %** sustained over 60 s
- [ ] Under an agent storm: main-thread CPU **< 25 %** sustained over 60 s
- [ ] `pango_layout_get_size` share materially below the 60.1 % baseline in the native profile
- [ ] **No card body exceeds 2,000 rendered chars**, while stored bodies remain unmodified
- [ ] A 30-minute idle soak shows no return to the pinned state

**Discriminating test for the Phase 2 hypothesis (run before implementing, if convenient):**
start any agent turn while the app is pinned. If the idle-pulse theory holds, CPU should **drop**
during the turn (the state leaves `idle`, the pulse stops, and `_live_update` is signature-gated).
If CPU remains at 100 % during the turn, the pulse is not the sole cause and Phase 1 + §4 carry the
fix.

### 7.1 Required evidence artefacts

Every phase must paste, in its completion report:

1. The per-thread main-thread CPU sample (60 s) before/after — measured with a **committed** probe
   script (see below), not ad-hoc commands
2. The native flamegraph shares (`pango_layout_get_size`, `gtk_widget_allocate`) before/after
3. The card body distribution (p90 / p99 / max) after the change
4. Confirmation that stored bodies are byte-identical for the sampled oversized cards

The probe should be committed as `scripts/crab_perf_probe.py` so the gate is reproducible by anyone
and cannot be satisfied by a favourable one-off run. Reference implementation of the sampling is in
this spec's DISCOVERY method notes (per-thread `/proc/<pid>/task/<tid>/stat`, 5 s windows).

---

## 8. Out of scope / follow-on

- **Feed virtualization** (`GtkListView` + `GListModel`) — the structural fix; §4 option 2. Deserves
  its own unit given the 188 tests in `test_feed_handler.py` covering the card-widget path.
- **F-A compaction-threshold churn** and **F-B O(n) new-card writes** — tracked separately in the
  UIRESP2 verification addendum; both are feed-store concerns, not UI.
- **Auto-answering approvals** — permanently out.
- Non-atomic conversation persistence (`agent/persistence.py:92`) — separate small fix.

---

## 9. Effort

| Item | Work | Effort |
|---|---|---|
| Phase 1 step 1 | Locate cap + bypass, report findings | 1–2 h |
| Phase 1 | Rendered-body cap + reveal affordance + tests | 3–5 h |
| Phase 2 | Bounded idle pulse + traversal removal + tests | 1–2 h |
| §7 | Committed probe script + baseline/after evidence | 1–2 h |
| §4 (conditional) | Rendered-card bound, or virtualization | 1–2 days / 1–2 weeks |

Phase 2 is the cheapest item in the document and may be the whole fix; Phase 1 is independent and
independently valuable.

---

## 10. Open questions for the PM

1. **Phase 2 before Phase 1?** Phase 2 is 1–2 h and, if the hypothesis holds, removes the pin
   outright. Phase 1 is larger but reduces the cost of every traversal regardless. Recommendation:
   ship Phase 2 first, measure, then Phase 1.
2. **If Phase 1 + 2 fail the gate, which §4 option** — bounded card rendering, or full
   virtualization?
3. **Is the idle pulse wanted at all**, or should the idle state have no animation? Bounding it
   (±5 s) is the recommendation; removing it is simpler still.
4. **Should tool-result storage be un-truncated?** Today `agent_runtime_handler.py:1583` truncates
   tool results at 2,000 **before storing**, so the full output is already lost. Phase 1 as scoped
   does not change that. If full tool output should be retained for audit, that is a **storage**
   change with its own risk profile (feed size, prune math, F-A/F-B) and belongs in a separate unit.
   Recommendation: keep it out of Phase 1; decide separately.

---

## 11. Sign-off

- [ ] PM approves Phase 1 (rendered-body cap)
- [ ] PM approves Phase 2 (idle-pulse containment)
- [ ] Spec goes through the normal Coder → Debugger audit loop before either phase ships
- [ ] Acceptance evidence in §7.1 attached to the completion report
