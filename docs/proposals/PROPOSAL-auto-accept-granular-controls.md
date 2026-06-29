# PROPOSAL: Granular Auto-Accept Controls + Auto-Accept Exec Commands

**Date:** 2026-06-29
**Author:** qtr (OC Tech Writer)
**Status:** Proposal — pending Captain approval
**Priority:** Medium-High (touches trust model of every agent-driven change)
**Effort:** ~10-14 hours across 5 phases
**Related:** Phase 5 (auto-accept), Phase E (exec approvals), Bug B (label-tracking), Bug C (label tracking on disable)

> **Note (2026-06-29):** This proposal is the design deliverable for the user's request "I want A+B+C, and I also want to auto-accept exec commands." A small in-scope code fix for Bug C (label stuck "ON" after user turns OFF) was landed alongside this proposal as `ui/handlers/feed_handler.py:197` with regression test `tests/test_feed_handler.py::TestFeedToolbarAutoAccept::test_disable_auto_accept_updates_toggle_visual`. See "In-scope code fix (shipped)" below.

---

## Why

### The Problem

CrabCakes Phase 5 introduced a single **Auto-Accept** toolbar toggle that, when ON, silently auto-accepts four kinds of file-change cards from whichever agent writes them first. It is, operationally, a single all-or-nothing trust switch. Users have repeatedly asked "what does this button actually accept?" and the answer is unanswerable from the UI — it's defined by a constant set in `ui/handlers/feed_handler.py:25`:

```python
_AUTO_ACCEPT_TYPES = {"diff", "file_created", "file_modified", "file_deleted"}
```

Beyond that, three real gaps make the current auto-accept painful:

1. **Type granularity is invisible.** Users who are comfortable letting Coder write files but want to eyeball every `diff` cannot express that preference. Either all four types auto-accept or none do.
2. **Agent lock-in is implicit.** When Auto-Accept turns ON, the *first* card's author becomes the locked-in agent (see `ui/handlers/feed_handler.py:303`). From then on, *only that agent* is auto-accepted. A user who turns it on for Coder's diff doesn't expect Debugger's diffs to silently slip past while Coder's cards get auto-accepted. There's no way to say "auto-accept any agent" vs. "only this agent."
3. **Per-card escape hatch is missing.** There is no way to say "auto-accept, but show me this specific card before it commits." Once the user clicks Auto-Accept ON, every matching card is committed without a chance to read it.

### Complicating Factor: Exec Commands

Phase E introduced a *separate* approval flow for `exec_command` (`ui/handlers/agent_runtime_handler.py:803-907`). When an agent wants to run a shell command, an `agent_action` card with `metadata.needs_approval = True` is created with **Approve / Deny** buttons, not Accept/Reject. Auto-accept, as it exists today, does not touch this flow at all.

But fully-automated sessions are a real need: a long-running agent doing a multi-step migration needs to run `pytest`, `ruff`, `git commit`, etc., and pausing on every shell command would defeat the point of Auto-Accept. So exec auto-accept is a natural extension — but it needs to be **opt-in, gated, and reversible**, because shell commands have different blast radius than file writes.

### The Solution

Replace the single Auto-Accept toggle with a **layered trust model**:

- **Layer 1 — Type toggles:** one toggle per auto-acceptable card type, all visible in the toolbar.
- **Layer 2 — Per-card snooze:** any individual card can be flagged "show me this one" before it's auto-accepted.
- **Layer 3 — Agent scope:** choose between "all agents," "locked first author," or "this specific agent."
- **Layer 4 — Exec auto-accept:** a separate toggle, scoped independently from file-card auto-accept, with an extra safety net (interactive prompt storm prevention).

All four layers share the same persistence model and the same warning dialog on initial activation.

### Why Now

- The audit on 2026-06-29 surfaced **Bug C** — the label stays "Auto-Accept: ON" after the user clicks the toggle OFF (mirror image of Bug B). This indicates the current auto-accept code is at the edge of its design envelope; the right time to extend it is now, with the invariant "every state mutation calls `update_auto_accept_state`" freshly repaired.
- Phase E exec approvals have been live long enough that users have started asking "can the toolbar apply to exec too."
- The bottom toolbar of the Feed tab is already the established home for the Auto-Accept toggle and the Accept All batch button (`ui/views/feed_tab.py:78-101`); the new controls slot into the same row.
- Captain JAQx explicitly requested A+B+C + exec auto-accept on 2026-06-29.

---

## In-scope code fix (shipped)

A 1-line production fix landed in `ui/handlers/feed_handler.py:197` (the `_disable_auto_accept` method) plus its regression test `tests/test_feed_handler.py::TestFeedToolbarAutoAccept::test_disable_auto_accept_updates_toggle_visual`. This is the inverse of Bug B's fix to `_enable_auto_accept`. It is shipped now because the longer refactor in this proposal will move that method anyway, but waiting would have left the bug live for the duration of the multi-week implementation.

The fix:

```python
def _disable_auto_accept(self) -> None:
    """Disable auto-accept and persist state. (Phase 5)

    Mirrors the Bug B fix in `_enable_auto_accept`: any code path that
    mutates `_auto_accept_enabled` must also call
    `update_auto_accept_state(...)` so the toolbar label tracks state.
    """
    self._auto_accept_enabled = False
    if self._feed_tab is not None:
        self._feed_tab.update_auto_accept_state(False)   # ← new line
    self._GLib.idle_add(self._save_feed_prefs_idle)
```

The regression test asserts both that the flag clears AND that the visible toggle (`mock_feed_tab._auto_accept_active`) flips to `False`. Without that single line, the second assertion fails — which is exactly Bug C.

281 tests pass in the affected modules.

---

## What

### Before (current)

The Feed tab has a single **persistent bottom toolbar** (`ui/views/feed_tab.py:78-101`) that is always visible at the bottom of the feed:

```
[ Auto-Accept: OFF ]  |  [ Accept All ]   (info label)
```

(Axis note: this toolbar is at the **bottom** of the Feed sub-tab, not a top app-bar. Cards scroll above it.)

The `Auto-Accept: OFF` toggle, when ON, silently auto-accepts the union of `{diff, file_created, file_modified, file_deleted}` cards **from whichever agent writes first**, for the rest of the session (and persists across project reload via `.crabcakes/feed-prefs.json`). The `Accept All` button (right side, hidden when count < 2) does a one-shot batch accept. No per-type control. No per-card escape. No agent picker. No exec coverage.

When OFF (via the cancel button on the warning dialog), resets `_auto_accept_enabled = False` and updates the label. When OFF (via direct user click of the toggle), used to leave the label "ON" (Bug C — now fixed in this proposal).

### After (proposed)

The same **persistent bottom toolbar** of the Feed tab, with the new controls added **in the existing row** (not a new sub-widget, not a second row):

```
[ Diffs: OFF ] [ Files: OFF ] [ Exec: OFF ]   |   [Agent: First author ▾]   |   [Snooze 0 ⏸]   |   [ Accept All (3) ]
```

- **Per-type toggles** (Layer 1): `Diffs` (auto-accept `diff` cards), `Files` (auto-accept `file_created`, `file_modified`, `file_deleted` — grouped as one conceptual "file events" toggle). Two binary toggles, both follow the existing `Auto-Accept: OFF` label pattern. First activation triggers the existing warning dialog.
- **Exec auto-accept** (Layer 4): `Exec` toggle, separately persisted, with three states cycling on each click: `Off` → `Show` (auto-approve, but render the card so the user sees the command) → `Silent` (auto-approve, no card at all — for "let the agent just run pytest in peace" mode) → `Off`. Label format: `Exec: OFF` / `Exec: SHOW` / `Exec: SILENT`.
- **Agent picker** (Layer 3): `Gtk.DropDown` showing the current selection, opens a popover with `All agents`, `First author (lock-in)`, separator, then one entry per registered agent. Default after first activation: `First author`.
- **Snooze button** (Layer 2): a small `Gtk.MenuButton` showing the count of currently-snoozed card-ids. Hidden when count == 0. Opens a popover with the snooze list and per-row unsnooze affordances.

#### Data model changes

The persisted feed-prefs file (`feed-prefs.json`) gains new fields:

```json
{
  "version": 2,
  "auto_accept": {
    "file_changes": {
      "diff":           { "enabled": true,  "agent_scope": "first_author" },
      "file_created":   { "enabled": true,  "agent_scope": "first_author" },
      "file_modified":  { "enabled": true,  "agent_scope": "first_author" },
      "file_deleted":   { "enabled": false, "agent_scope": "first_author" }
    },
    "exec_command": {
      "mode": "off",          // "off" | "show" | "silent"
      "agent_scope": "first_author"
    },
    "snoozed_card_ids": []
  }
}
```

`agent_scope` is one of: `first_author` (current behavior), `all_agents` (no lock-in), or a specific agent name string.

A `version: 2` is added so existing v1 files can be migrated in one shot: a present-tense `auto_accept_enabled: true` migrates to "Diffs/Files ON, first-author lock-in."

#### Code structure

Today:

```
ui/handlers/feed_handler.py
  ├── _AUTO_ACCEPT_TYPES = {"diff", "file_created", "file_modified", "file_deleted"}
  ├── _on_auto_accept_toggled(active)  → warns + enables / disables
  ├── _enable_auto_accept()
  ├── _cancel_auto_accept()
  ├── _disable_auto_accept()
  ├── _auto_accept_enabled: bool        # ← single flag
  ├── _auto_accept_agent: str | None    # ← single agent
  └── (in _append): if (_auto_accept_enabled and card_type in _AUTO_ACCEPT_TYPES …) → handle_accept
```

Tomorrow:

```
ui/handlers/feed_handler.py
  ├── _on_auto_accept_pref_changed(pref_key, value)  # unified callback for all 4 toggles
  ├── _enable_file_change_auto_accept(card_type: str)
  ├── _disable_file_change_auto_accept(card_type: str)
  ├── _enable_exec_auto_accept(mode: str)
  ├── _disable_exec_auto_accept()
  ├── _cancel_exec_auto_accept()
  ├── _is_card_auto_acceptable(card) → bool          # central policy check
  ├── _should_auto_accept_exec(card) → bool          # exec variant
  ├── _prefs: AutoAcceptPrefs                         # dataclass holding the v2 schema
  └── _auto_accept_enabled: bool                      # ← derives from prefs (kept for legacy external API)
```

The `_is_card_auto_acceptable(card)` method consolidates the policy: type toggle ON, agent matches `_auto_accept_agent` (or scope is `all_agents`), not in snooze list, etc. This is the single place to test the trust model.

#### Toolbar layout (revised 2026-06-29)

**No new sub-widget is added.** The new controls slot into the **existing** persistent bottom toolbar of the Feed tab — a single horizontal `Gtk.Box` at `ui/views/feed_tab.py:78-101` that already hosts the Auto-Accept toggle and the "Accept All" batch button. The toolbar is built eagerly in `FeedTab.__init__` and is always visible at the bottom of the feed regardless of card count.

**Today (line 78-101):**

```python
self._toolbar = Gtk.Box(orientation=Gtk.HORIZONTAL, spacing=8)
self._toolbar.add_css_class("feed-toolbar")

self._auto_accept_toggle = Gtk.ToggleButton(label="Auto-Accept: OFF")
self._auto_accept_toggle.add_css_class("feed-toolbar-toggle")
self._auto_accept_toggle.connect("toggled", self._on_auto_accept_toggled)

self._divider = Gtk.Separator(orientation=Gtk.ORIENTATION_VERTICAL)
self._divider.add_css_class("feed-toolbar-divider")

self._batch_accept_button = Gtk.Button(label="Accept All")
# ...hidden when count < 2
self._batch_accept_label = Gtk.Label(label="")

self._toolbar.append(self._auto_accept_toggle)
self._toolbar.append(self._divider)
self._toolbar.append(self._batch_accept_button)
self._toolbar.append(self._batch_accept_label)
self.append(self._toolbar)
```

**After (proposed, all in the same `self._toolbar`):**

```
[ Diffs: ON ] [ Files: ON ] [ Exec: OFF ] | [Agent: Coder  ▾] | [Snooze 0 ⏸] | (divider) | [Accept All (3)]
```

Concretely, in code:

```python
# Group 1 — per-type toggles (Layer 1)
self._diffs_toggle    = Gtk.ToggleButton(label="Diffs: OFF")
self._files_toggle    = Gtk.ToggleButton(label="Files: OFF")
self._exec_toggle     = Gtk.ToggleButton(label="Exec: OFF")   # cycles off → show → silent

# Group 2 — agent scope (Layer 3)
self._agent_dropdown  = Gtk.DropDown()                          # All / First / Coder / Debugger / …

# Group 3 — snooze (Layer 2)
self._snooze_button   = Gtk.MenuButton(label="Snooze 0")        # count badge; opens snooze list

# Existing — unchanged
self._divider, self._batch_accept_button, self._batch_accept_label

self._toolbar.append(self._diffs_toggle)
self._toolbar.append(self._files_toggle)
self._toolbar.append(self._exec_toggle)
self._toolbar.append(Gtk.Separator(orientation=Gtk.ORIENTATION_VERTICAL))
self._toolbar.append(self._agent_dropdown)
self._toolbar.append(Gtk.Separator(orientation=Gtk.ORIENTATION_VERTICAL))
self._toolbar.append(self._snooze_button)
self._toolbar.append(self._divider)            # existing
self._toolbar.append(self._batch_accept_button) # existing
self._toolbar.append(self._batch_accept_label)  # existing
```

**Layout decisions anchored to the existing row:**

- The bar is already a single horizontal `Gtk.Box` with 8px spacing, perfect for one row of controls. The proposal does not stack into a second row.
- The original single `Auto-Accept: OFF` toggle is **replaced**, not wrapped. Wrapping would consume extra horizontal space and the bar is already busy. The replacement is a 3-button group (`Diffs` / `Files` / `Exec`) which the user reads left-to-right and which has the same visual weight.
- The `Exec` toggle is a 3-state cycle button, not a binary toggle. Each click advances `off → show → silent → off`. The label is `Exec: OFF` / `Exec: SHOW` / `Exec: SILENT` (capitals to make the mode visible at a glance). A tooltip on hover explains what each mode does.
- The agent dropdown collapses to a small `Gtk.DropDown` that shows the current selection (e.g. `Coder`) and opens a popover with the choices. Default choices are `All agents`, `First author (lock-in)`, and a separator followed by one entry per registered agent.
- The snooze button shows the count of currently-snoozed card-ids; clicking it opens a `Gtk.Popover` listing them with an "unsnooze" affordance per row. The button is hidden when count == 0.
- The existing `_divider` and `_batch_accept_button` and `_batch_accept_label` stay where they are, on the right side of the bar. The "Accept All" button only appears when ≥2 pending cards exist (`feed_tab.py:90`); the new controls are always visible.
- All new widgets get a `feed-toolbar-*` CSS class so the theme is consistent with the existing toggle (`feed-toolbar-toggle`) and the batch button (`feed-btn-batch-accept`). No new colors, no new sizes.
- A small "Advanced" popover (the `⚙` icon between the snooze button and the divider) hosts the exec allowlist regex editor and the per-card snooze list when it grows long. It is a single button — not a second row.

**Visual states for the per-type toggles, mirroring the existing pattern:**

The current `update_auto_accept_state(active: bool)` in `feed_tab.py:395` reads:

```python
def update_auto_accept_state(self, active: bool) -> None:
    self._auto_accept_toggle.set_active(active)
    self._auto_accept_toggle.set_label(f"Auto-Accept: {'ON' if active else 'OFF'}")
```

After, this is replaced by a new method on `FeedTab`:

```python
def update_auto_accept_prefs(self, prefs: AutoAcceptPrefs) -> None:
    """Reconcile the toolbar visuals from the v2 prefs dataclass.

    Called by FeedHandler whenever prefs change. The view never owns state;
    it only reflects what the handler tells it.
    """
    self._diffs_toggle.set_active(prefs.file_changes.diff.enabled)
    self._diffs_toggle.set_label(f"Diffs: {'ON' if prefs.file_changes.diff.enabled else 'OFF'}")
    self._files_toggle.set_active(prefs.file_changes.files.enabled)
    self._files_toggle.set_label(f"Files: {'ON' if prefs.file_changes.files.enabled else 'OFF'}")
    self._exec_toggle.set_label(f"Exec: {prefs.exec_command.mode.upper()}")
    # agent_dropdown selection index
    # snooze_button label "{count} snoozed"
```

This preserves the existing pattern (the view is a pure reflection of handler-owned state) and fixes the Bug C invariant: any handler-side state mutation calls `update_auto_accept_prefs(...)` so the labels can never drift again.

**Why no new sub-widget:**

The original draft of this proposal invented a `FeedToolbar` sub-widget with an `AutoAcceptSegmented` container. That was wrong: the existing `self._toolbar` is already a `Gtk.Box` and `Gtk.Box` is the natural place for sibling controls. Wrapping the existing row in a new sub-widget would have added a layer of indirection that the existing `feed_handler.set_feed_tab()` wiring does not need. This revision drops that invention.

#### Phase E integration

Exec auto-accept hooks into the existing approval flow at `ui/handlers/agent_runtime_handler.py:_do_approval_needed`:

```python
# Today:
card = FeedCardData(card_type="agent_action", …, metadata={"needs_approval": True, …})
card_id = self._fh.add_card(card)

# Tomorrow, inside _fh.add_card (or _is_card_auto_acceptable):
if (self._prefs.exec_command.mode != "off"
        and self._is_card_auto_acceptable(card)
        and not self._is_snoozed(card_id)):
    self._GLib.idle_add(lambda: self.handle_approve_exec(card_id, True))
```

In `Silent` mode, the approval card is **not even created** — `agent_runtime_handler` short-circuits earlier, calling `rt.approve_exec(session_key, "exec_command", args, True)` directly without a feed card. The execution still appears in the Activity Bubble and the `command_output` callback, but there's no Accept/Deny prompt.

#### Per-card snooze

A new field `snoozed_card_ids: list[str]` in the v2 schema. The auto-accept guard at line 297 inserts `and card_id not in self._prefs.snoozed_card_ids`. Snoozed cards:

- Still appear in the feed (rendered normally).
- Are **not** auto-accepted on arrival.
- Show a small "Auto-accept snoozed" badge in the corner with a click-to-unsnooze control.
- Are logged to the agent context with a system-event entry explaining they were held for review.
- Can be bulk-unsnoozed via the SnoozeButton's panel.

The snooze is per-card-id (not per-type), so it survives neither reload nor project-reopen by default. An optional "remember snooze for this session" checkbox keeps it across the current session.

---

## How

### Five phases of work

#### Phase 1 — Bug C fix ✅ DONE (shipped 2026-06-29)
`_disable_auto_accept` updated, regression test added, 281 tests pass. See "In-scope code fix" above.

#### Phase 2 — Preferences v2 schema + migration (2-3 hours)
- New `ui/feed_store.py` (or whichever owns prefs) loader handles v1→v2.
- `feed-prefs.json` with `version: 2` is written on first save under v2.
- Unit tests for the migration (golden-file: take a v1 prefs file, produce expected v2).

#### Phase 3 — Per-type toggles (3-4 hours)
- Replace `_AUTO_ACCEPT_TYPES` constant with a `_prefs.file_changes.{type}.enabled` lookup.
- Toolbar: replace single toggle with two toggles (`Diffs`, `Files`), grouped. Label logic moves from `feed_tab.update_auto_accept_state(active: bool)` to a new method `feed_tab.update_type_toggles(prefs)` that computes each toggle's visual state from prefs.
- `_is_card_auto_acceptable(card)` consolidates the policy at `feed_handler._append`.
- Each toggle gets its own warning dialog on first activation (so the user explicitly opts in to each type).
- Tests: parametrized test that toggling each type independently produces correct accept/don't-accept behavior; "all types off" → no card gets auto-accepted; "diff only" → only `diff` cards get auto-accepted.

#### Phase 4 — Agent picker + lock-in replacement (2-3 hours)
- Agent picker dropdown. Three options: "All agents," "First author (lock-in)," "Specific agent." When "Specific" is chosen, a follow-up dropdown selects the agent.
- `_prefs.snoozed_card_ids = []` is initialized. Per-card snooze UI: a small badge on each auto-accepted card with "hold this one" / "let this one through." SnoozeButton in toolbar shows the count badge.
- Tests: lock-in behavior preserved as default; "All agents" → no _auto_accept_agent set; snoozed cards do not auto-accept; unsnooze re-enables.

#### Phase 5 — Exec auto-accept (3-4 hours)
- `Exec` toggle added to toolbar with three states (`Off`, `Show`, `Silent`).
- `_should_auto_accept_exec(card)` centralizes the policy: mode != "off" + agent_scope matches + not snoozed.
- Phase E integration: in `_do_approval_needed`, check exec policy. In `Silent`, bypass card creation entirely and call `rt.approve_exec(...)` immediately.
- Tests: each of the 3 modes produces correct behavior; `Off` is a no-op; `Show` creates an auto-approved card; `Silent` does not create a card but does fire `command_output` callback.

### Risk analysis

#### Risk 1: Snooze + silent-exec interaction
A user in `Silent` exec mode who then snoozes an `agent_action` card — does the snooze apply if the card wouldn't have appeared anyway? Yes: snooze is per-card-id, but in `Silent` mode there's no card. Mitigation: the snooze button's tooltip explains this. Snoozes are visible/manageable in the SnoozeButton panel even in Silent mode.

#### Risk 2: Persisted prefs drift between v1 and v2
A user with v1 prefs who upgrades mid-session could end up with half-migrated state if they toggle auto-accept before the migration runs. Mitigation: load is eager on every `on_project_opened`; the first save in v2 produces a complete v2 file. Recovery from half-state is automatic on next load.

#### Risk 3: Exec auto-accept is dangerous
This is the largest trust-expansion in the proposal. Without any opt-in, an agent could run `rm -rf` against the project root. Mitigations, layered:

1. The toggle is **off by default**, like file-change auto-accept.
2. The first activation shows a warning dialog specifically framed around shell commands ("an auto-accepted exec can delete files, run network calls, etc.").
3. The `Silent` mode is gated behind a "I understand the blast radius" confirmation checkbox in the warning dialog.
4. The Advanced panel exposes a per-command allowlist (regex) — for example, `^pytest `, `^ruff `, `^git commit`. A command matching the allowlist is auto-approved; anything else drops to manual approval even if exec-auto-accept is `Show` or `Silent`.
5. The card metadata records `auto_accepted_by: "exec_auto_accept"` so post-hoc auditing via `git log` / `audit_report` cards can attribute what was auto-approved vs. manually approved.

Risk is non-zero, but the optionality (`Off` always available, allowlist, auditability) keeps it scoped.

#### Risk 4: Toolbar density (revised 2026-06-29)

The new controls go into the **existing** persistent bottom toolbar of the Feed tab (`feed_tab.py:78-101`), not a new sub-widget. After: 3 toggles + 1 dropdown + 1 menu button + the existing batch button + the existing info label, separated by 2 vertical dividers. That's roughly 7-8 controls in one row.

Mitigations:

1. **Hide labels by default on narrow windows.** `Gtk.Label` is hidden on width < 800px; the toggle shows just `Diffs` / `Files` / `Exec` (the mode suffix `OFF/ON/SHOW/SILENT` is still there as a tooltip). A `Gtk.Window` `configure-event` handler toggles label visibility based on width.
2. **The snooze button is hidden when count == 0.** No visual footprint when there is nothing to snooze.
3. **The agent dropdown is a compact `Gtk.DropDown` that only shows the current selection** (`Coder` not `Coder (locked-in agent)`).
4. **Visual separators (existing `Gtk.Separator` widget) group the controls** into three logical clusters: trust (Diffs/Files/Exec), scope (Agent), and escape (Snooze). The existing divider between Auto-Accept and Accept All is reused.
5. **Worst case (very narrow window, e.g. 600px), the Advanced `⚙` button opens a popover that contains the entire toolbar in a vertical stack** as an overflow fallback. This is a graceful degradation, not a redesign.

No new toolbar pattern is introduced. The existing `feed-toolbar` CSS class applies; new controls get `feed-toolbar-toggle-per-type` and `feed-toolbar-agent-dropdown` etc. to match.

#### Risk 5: Performance / GC
The current code reads `_auto_accept_enabled` on every `add_card` call. New code reads `_prefs` and runs a more expensive policy check. `add_card` is on a hot path during agent streaming. Mitigation: keep `_auto_accept_enabled` as a derived field that's invalidated when `_prefs` changes. The policy check stays O(1) on the hot path.

### Migration plan

1. Phase 1 ships behind the scenes as the Bug C fix.
2. Phase 2 ships schema migration; v1 prefs are auto-upgraded on first open; v2 file is written on first save.
3. Phase 3 ships behind a feature flag `auto_accept_granular`. Default off; flip on after Phase 4 land.
4. Phase 5 ships behind a separate flag `exec_auto_accept`. Default off.
5. After one full release cycle, both flags default to on for new projects, then the old single toggle is removed.

### Testing strategy

- **Unit tests** for each phase's new logic, all in the existing `tests/test_feed_handler.py::TestFeedToolbarAutoAccept` class (extended with new fixtures for the multi-toggle scenario). One test class per concern, no shotgun.
- **A scenario test** that walks a full session: project opens with v1 prefs → migration → user toggles Diffs → Diffs card auto-accepts → user toggles Files → Files card auto-accepts → user toggles Files off → next Files card lands unaccepted → relaunch app → state survives.
- **An exec scenario test**: project opens with v2 prefs → user enables Exec in `Show` mode → agent runs `pytest` → card appears with status="auto_approved" → next user unchecks the show option → `Silent` → `pytest` runs, no card, output still fires.
- **A snooze scenario test**: Diffs on, exec `Show` on. Agent sends 3 diffs + 1 exec. User snoozes cards 2 and 3. Cards 2 and 3 do not auto-accept. Card 1 does. The exec auto-approves (snooze was for diffs only — exec snooze is separate). User unsnoozes card 2. Card 2 stays unaccepted (snooze only blocks the *initial* auto-accept path; it does not retroactively accept cards).
- **A migration regression test**: golden v1 prefs file → golden v2 output → compare.

### Documentation

- `docs/ARCHITECTURE.md` §8.6 (handler pattern) extended with the `AutoAcceptPrefs` dataclass and the `_is_card_auto_acceptable` policy method. Same commit as Phase 2.
- `docs/specs/SPEC_AUTO_ACCEPT_GRANULAR.md` — full spec of the toolbar, prefs, and trust model. Written in parallel with Phase 5.
- `docs/post-mortems/2026-06-29-PHASE-5-AUTO-ACCEPT-GRANULAR-LAUNCH.md` — post-mortem after the feature flag flips on.

---

## Verification

The proposal is verifiable in three ways:

1. **Read the schema.** `feed-prefs.json` files written under v2 should match the example in "Data model changes" above. Field count and types are checked by a serialization round-trip test.
2. **Read the policy.** Every card-acceptance decision passes through `_is_card_auto_acceptable(card)` (Phase 3). That method, with its inputs mocked, can be unit-tested against a matrix of `(card_type, agent_scope, snoozed?, file_change_pref, exec_pref)` to produce a 32-row truth table that's checked in as `tests/test_feed_handler.py::TestAutoAcceptPolicy::test_policy_matrix`.
3. **Run the scenarios.** The three scenario tests above (diffs/files toggle, exec show/silent, snooze) run as integration tests in the existing test suite and must pass before any merge.

---

## Audit Report

**Task:** Land label-tracking fix for Auto-Accept OFF path; produce design proposal for granular controls + exec auto-accept.
**File:** `ui/handlers/feed_handler.py:197`
**Severity:** bug (label-tracking)
**Bug:** `_disable_auto_accept` mutated `_auto_accept_enabled` and scheduled a save but never called `feed_tab.update_auto_accept_state(False)`, so the toolbar label stayed "Auto-Accept: ON" after a user-click OFF despite the flag and persisted prefs being correct.
**Expected:** Toolbar label tracks underlying state on both ON and OFF paths.
**Actual:** ON path fixed in prior turn (Bug B). OFF path was broken; fixed now.
**Root cause:** Mirror-image of Bug B; the invariant "every state mutation calls `update_auto_accept_state`" was not symmetric across `_enable_auto_accept` and `_disable_auto_accept`.
**Fix:** Add `if self._feed_tab is not None: self._feed_tab.update_auto_accept_state(False)` to `_disable_auto_accept` (mirrors `_enable_auto_accept` at `ui/handlers/feed_handler.py:181-182`).
**Pattern:** missing-invariant-check
**Tests:** `tests/test_feed_handler.py::TestFeedToolbarAutoAccept::test_disable_auto_accept_updates_toggle_visual` — asserts visible toggle flips to `False`. 281 tests pass in affected modules.

---

## Hand-off checklist

- [x] Bug C fix landed (Phase 1)
- [x] Bug C regression test added
- [x] 281 tests pass
- [x] Discovery complete (card types enumerated, exec approval flow understood, proposal format conventions read)
- [x] Proposal doc written at `docs/proposals/PROPOSAL-auto-accept-granular-controls.md`
- [ ] Captain JAQx reviews proposal
- [ ] Phase 2 implementation begins (prefs v2 schema + migration)
- [ ] Phase 3 (per-type toggles) — gated behind `auto_accept_granular` flag
- [ ] Phase 4 (agent picker + snooze)
- [ ] Phase 5 (exec auto-accept) — gated behind `exec_auto_accept` flag
- [ ] Feature flag flip → default on for new projects
- [ ] Old single-toggle removal
- [ ] Post-mortem filed

---

## Status: PROPOSAL — PENDING CAPTAIN APPROVAL

This proposal is a design deliverable. No code outside the in-scope label-bug fix has been written. Implementation requires Captain approval and a feature-flag strategy. The proposal is shippable as-is to `docs/proposals/` for review.

---

## Revision log

- **2026-06-29, 08:28 PDT — placement correction.** Captain clarified that the new buttons go on the **feed tab toolbar at the bottom of the feed, next to the current Auto-Accept button**. The original draft of this section invented a `FeedToolbar` sub-widget with an `AutoAcceptSegmented` container, which would have been a new wrapper layer. That was wrong. Revision:
    - The "After" mockup and the "Toolbar layout" section now anchor all new controls in the **existing** `self._toolbar` `Gtk.Box` at `ui/views/feed_tab.py:78-101`, alongside the existing Auto-Accept toggle and Accept All button.
    - Risk 4 (toolbar density) rewritten to address the real concern: 7-8 controls in one row, with concrete mitigations (label hiding on narrow windows, snooze button hidden when count == 0, dropdown shows compact selection, existing `feed-toolbar` CSS class reused, overflow popover fallback).
    - The "Why no new sub-widget" paragraph explicitly records the correction so the next reader doesn't re-introduce the wrapper.
- **2026-06-29, 08:24 PDT — initial draft.** First version, designed without re-reading the actual toolbar code. Carried Bug C fix inline (Phase 1, shipped).
