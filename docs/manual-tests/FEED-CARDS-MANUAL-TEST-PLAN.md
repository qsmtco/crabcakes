# Manual Test Plan — Feed Cards (5-phase UX improvements)

**Target:** Crabcakes project feed tab — commit `5727675 feat(feed): ship 5-phase Feed Card UX improvements`
**Spec / post-mortem:** `docs/specs/SPEC-FEED-CARD-UX.md`, `docs/post-mortems/2026-06-18-FEED-CARD-UX-POST-MORTEM.md`
**Prereq:** Working crabcakes install with an open project. The project should have at least one chat agent connected so file-change accept/reject cards can be produced. A second terminal in the project root (`/home/q/projects/crabcakes`) is handy for `git log --oneline` checks.
**Reset state:** Before starting, run `rm -f ~/.local/share/crabcakes/feed/<project_id>.json` (or whatever the per-project feed store path is in your build) so you start with an empty feed. Reopen the project after deleting.

Each step lists **what to do**, **what to look for**, and **what would be a bug**. Steps build on each other — don't skip ahead.

---

## 1. Card-type button policy (Phase 1)

**Do:** With an empty feed, ask your chat agent to edit a small file. Wait for a `file_change` card to appear. Note its buttons and color. Then accept it. Then ask the agent to perform a read-only operation (e.g. "list the functions in foo.py") to provoke an `agent_action` card.

**Expect:**
- The pending `file_change` card shows two buttons (`Accept`, `Reject`) and uses the **actionable / pending** color.
- After clicking Accept, the same card now shows a single `Resolved` (or similar) affordance and uses the **actionable / resolved** color — buttons are gone.
- The `agent_action` card from a read-only prompt shows **no** Accept/Reject buttons and uses the **informational** color.

**Bug if:** Buttons appear on informational cards, disappear on resolved ones, or the wrong palette is used.

---

## 2. Persistent decision badges (Phase 2)

**Do:** Click Accept on a `git_commit` card. Then scroll down and click Reject on a different `git_commit` card.

**Expect:**
- Both cards keep their `ACCEPTED` / `REJECTED` badge in the header after the click. Closing and reopening the project preserves them (badge comes back from the feed store).
- The new `git_commit` produced by each decision also inherits its badge correctly (`ACCEPTED` for accept, `REJECTED` for reject).

**Bug if:** Badge vanishes on click, disappears after a project reload, or the follow-up commit card has no badge.

---

## 3. Sequence numbers (Phase 3)

**Do:** Force a stream of mixed cards — e.g. an agent edit + a `git_commit` + another agent edit. Open the project for the first time after deleting the feed store.

**Expect:**
- Each card in the feed has a `#N` badge in its header, starting at `#1` for the oldest card and incrementing without gaps.
- Closing and reopening the project keeps the same numbers on old cards. New cards continue from the highest existing `#N + 1`.
- On a project with an existing feed file written before Phase 3 (no `seq_num` field), the first open assigns `#1, #2, #3…` in timestamp order — this happens **once** and is persisted (the field is now in the JSON).

**Bug if:** Numbers are missing, duplicated, out of order, or reset on reload. Migration should run on first open only — re-running shouldn't reassign.

---

## 4. Smart scroll (Phase 4)

**Do:** Produce a long feed (or load a project with many cards). Then:

  4a. **At-bottom case:** Sit at the bottom of the feed. Ask the agent to do something that appends a new card.
  4b. **Scrolled-up case:** Scroll up so you are clearly more than 80 px above the bottom (a few screens up). Ask the agent to do another small task.
  4c. **Project-open case:** Close the project, then reopen it.

**Expect:**
- 4a: Feed scrolls smoothly to the new card at the bottom.
- 4b: Feed does **not** jump; you stay where you were scrolled, the new card appears below your viewport.
- 4c: Project open does an **unconditional** scroll to bottom regardless of where you were last (this is intentional).

**Bug if:** Feed jumps to top on every new card in 4b, or refuses to follow you in 4a, or stays put on reopen in 4c.

---

## 5. Batch Accept (Phase 5)

**Do:** Provoke a stream of file changes — easiest way is to ask the agent to make several small edits in a row, or have two agents work in parallel. Watch the bottom of the feed.

**Expect:**
- When **≥2 consecutive pending `file_change` cards** appear at the bottom of the feed, a batch bar appears above them with a count and an `Accept All` button.
- The bar does **not** appear if there is only one pending card, or if pending cards are interrupted by a non-file-change card (e.g. an `agent_action`).
- Clicking `Accept All` accepts each file in turn, each producing its own `git_commit` card, and the bar disappears when zero pending remain.
- After manually accepting one of the cards, the batch bar's count decrements correctly.

**Bug if:** Bar appears with only one pending card, misses a run of ≥2, or the count is wrong after a manual accept/reject.

---

## Sign-off

When all five phases pass, drop a short note in `docs/manual-tests/` (e.g. `FEED-CARDS-MANUAL-TEST-RESULTS-YYYY-MM-DD.md`) with date, build hash, and any observations. If you find a bug, file it in `docs/bugs/` per project convention and tag it `feed-card` so the post-mortem backlog (7 Tier-2 items) can be re-prioritised.
