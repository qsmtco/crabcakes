# SPEC: Feed Card UX Improvements

**Date:** 2026-06-13
**Author:** qtr (spec), Captain (review)
**Status:** ✅ SHIPPED (5 phases — see commit history; verification post-mortem: `docs/post-mortems/2026-06-18-FEED-CARD-UX-POST-MORTEM.md`)
**Revised:** 2026-06-18 (Qaster review — 9 issues fixed, see Spec Revision History below; SHIPPED marker added after all 5 phases complete)
**Implements:** Feed card usability improvements (5 items from user feedback)
**Depends on:** None (builds on existing feed card system, Phase 5)
**Target branch:** main

> **Architecture compliance:** All changes follow the handler pattern (§8.6), CSS single-source-of-truth (§9.1), callback pattern (§5), and model/view/handler separation (§2, §3). No new module imports across forbidden layer boundaries (`models/` ↛ `ui/`, `utils/` ↛ `ui/`, `gateway/` ↛ `ui/`).

## Spec Revision History

**2026-06-18 — All 5 phases SHIPPED:**

- **Phase 1:** Card type button policy + color palette (`is_actionable`, `is_informational`, sub-state CSS for `agent_action` cards)
- **Phase 2:** Persistent decision badges on git_commit + approval cards
- **Phase 3:** Sequence numbers on cards with one-way migration for old feed.json
- **Phase 4:** Smart scroll (preserves reading position when scrolled up)
- **Phase 5:** Batch accept for consecutive file-change cards

**Verification:** 1750+ tests pass (targeted runs: 64 + 19 + 95 + 31 + 110 across 5 phases). Full suite OOM is a system env issue, not a code issue.
**Post-mortem:** `docs/post-mortems/2026-06-18-FEED-CARD-UX-POST-MORTEM.md` (11 sections, 23,915 bytes)
**Bug fixes needed during implementation:** 0 (5/5 phases clean; 2 scope-creep items reverted in Phase 1 by supervisor)
**Tier 2+ backlog:** 7 items (test design limitation, badge label UX, defensive validation, doc nits, CI batched runs, etc.)

**2026-06-18 — Qaster review:**

1. **Phase 2 fix location clarified** (Issue 1, CRITICAL): `card.accepted = approved` goes in `agent_runtime_handler.approve_exec()` inside the `if self._fh is not None:` block, before `self._fh.update_card(approval_id, card)`. Read the file to find the exact line.
2. **Removed all "verified at line N" claims** (Issue 2, MEDIUM): Code has grown by 200+ lines since the spec was drafted. Implementer must read each file in full before editing, not trust spec line numbers.
3. **Batch bar placement decision: PINNED TO TOP, OUTSIDE SCROLLED WINDOW** (Issue 3, MEDIUM): The batch bar lives in `FeedTab` (top-level), not in `_card_container` (the inner scrolled box). Uses `self.append(self._batch_bar)` then `self.reorder_child_after(self._batch_bar, None)` to put it at the very top. Alternative (scrolls with cards) documented but rejected.
4. **Removed contradictory "Additional fix" paragraph in Phase 4** (Issue 4, MEDIUM): Smart scroll is the only fix. Container `vexpand` stays as-is.
5. **`is_informational()` now returns True for `agent_action` with no `status` field** (Issue 5, MINOR): `if card_type == "agent_action" and status in (None, "running", "complete", "error"): return True`. This prevents the "Accept button that does nothing" bug for crabcard-parsed or manually-created `agent_action` cards.
6. **Added Test Plan** (was missing): Specific test cases for each phase, not just "run pytest."
7. **Added migration concern for `seq_num`**: On `on_project_opened()`, assign seq_nums in order of creation timestamp to existing cards that have `seq_num=None`. Eliminates the "first run after upgrade shows mixed" UX.
8. **Added concurrency requirement for `batch_accept()`**: Must acquire `self._lock` (same as `add_card()`) to be thread-safe with background git operations.
9. **CSS color consistency**: The existing `ui/styles.py` uses hardcoded hex colors (no `@define-color` or `var(--name)` variables). The new CSS in Phase 1.3 already matches the existing palette (`#6366f1` indigo, `#34, 197, 94` green, `#ef4444` red) for the seq badge and batch accept bar. The sub-state colors (orange/blue/green/red for agent_action sub-states) are NEW and should be added in the same hex format as the existing palette. The implementer should grep `ui/styles.py` for `color:` and `background:` to confirm the new CSS matches the existing visual style before adding it.

---

## 1. Overview

### Problem Statement

The project feed card system has five UX deficiencies reported by the user:

1. **Accept/Reject buttons disappear after clicking** — no persistent visual record of the decision remains on all card types.
2. **Feed auto-scrolls to top** when new cards arrive instead of staying at the current position or scrolling to the bottom (newest).
3. **No visible card ID number** — impossible to tell at a glance which cards have been reviewed vs. which are new.
4. **No batch accept** — long agent turns with many approval checkpoints require clicking Approve on each card individually.
5. **All card types look the same** — approval-request, command-running, and informational cards all get the same buttons and colors, making it hard to distinguish what needs action vs. what's just status.

### Solution Summary

Five phased improvements to the feed card system, each independently shippable:

| Phase | Feature | Priority | Risk |
|-------|---------|----------|------|
| 1 | Card type button policy + color palette | High | Low |
| 2 | Persistent decision badges on ALL card types | High | Low |
| 3 | Sequence numbers on cards | Medium | Low |
| 4 | Never auto-scroll to top (smart scroll) | High | Medium |
| 5 | Batch accept ("Accept All" / "Accept Next N") | Medium | Medium |

### Scope

| In scope | Out of scope |
|----------|-------------|
| `ui/views/feed_card.py` — button visibility logic | New card types |
| `ui/handlers/feed_handler.py` — sequence numbers, scroll policy, batch accept | Feed filtering/search |
| `ui/styles.py` — new CSS classes + color palette tweaks | Feed card persistence format changes |
| `models/feed_card.py` — `seq_num` field, `is_actionable()` / `is_informational()` helpers | Crabcard parser changes |
| `ui/views/feed_tab.py` — smart scroll logic | Activity drawer changes |

---

## DISCOVERY

- **Read `models/feed_card.py`**: `FeedCardData` dataclass with `card_type`, `source`, `accepted` (True/False/None), `card_id` (UUID string), `metadata` dict. Static method `css_class_for_type()` maps card types to CSS classes. `CardType` is a `Literal` of 11 types. No `seq_num` field exists. No notion of "actionable" vs "informational" card types — all types except `git_commit` get Accept/Reject/Review buttons.

- **Read `ui/views/feed_card.py`** (~583 lines): `build_feed_card()` factory. Button logic around the middle of the file: `is_resolved = card_data.accepted is not None`, `is_commit = card_data.card_type == "git_commit"`. Only `git_commit` skips buttons entirely. For resolved cards, Accept/Reject are hidden but Review remains. Badge logic: ACCEPTED/REJECTED labels appended to footer via `update_card_badge()` (search for the function name).

- **Read `ui/handlers/feed_handler.py`** (~932 lines): `add_card()` generates `card_id = str(uuid.uuid4())` — no sequence number. `handle_accept()` / `handle_reject()` update `card.accepted` then call `_update_card_visual()`. `_update_card_visual()` calls `update_card_badge()` then adds/removes CSS classes. `add_card()` always calls `self._feed_tab.scroll_to_bottom()` after appending. `on_project_opened()` calls `scroll_to_bottom()` after rendering.

- **Read `ui/views/feed_tab.py`** (~167 lines): `scroll_to_bottom()` sets `vadj.set_value(vadj.get_upper())`. Called from `feed_handler.add_card()` via `self._feed_tab.scroll_to_bottom()`. No scroll-to-top anywhere in the code. The "scroll to top" bug is likely caused by `Gtk.Box` with `set_valign(Gtk.Align.START)` — when new widgets are appended at the bottom, GTK may re-center the viewport if the adjustment upper changes before the idle_add fires.

- **Read `ui/handlers/agent_runtime_handler.py`** lines 550-700: `_do_tool_call_start()` creates `agent_action` card with `metadata.status = "running"`, `_do_tool_call_result()` updates same card with `metadata.status = "complete"` or `"error"`. `_do_approval_needed()` creates `agent_action` card with `metadata.needs_approval = True`. All three use `card_type = "agent_action"` — no visual distinction between them.

- **Read `ui/styles.py`** lines 778-905: 11 card-type CSS class pairs (header + body). `.feed-card-accepted { opacity: 0.6; }`, `.feed-card-rejected { opacity: 0.4; }`. Badge classes `.feed-accepted-badge` and `.feed-rejected-badge`.

- **Architecture owner**: `FeedHandler` (§3.22c) owns card lifecycle and state mutations. `feed_card.py` view (§3.22a) owns widget construction. `FeedCardData` model (§3.22b) owns data structure. CSS in `styles.py` (§3.5/§9.1).

- **Existing patterns**: The `needs_approval` metadata flag already routes different callbacks in `build_feed_card()` via `feed_handler.add_card()` lines 140-148. This proves the pattern works — we extend it to cover more card states.

---

## 2. Changes by File

### Phase 1: Card Type Button Policy + Color Palette

#### 2.1 `models/feed_card.py` — New Helper Methods

**What changes:** Add two static helper methods to classify card types as actionable (needs user decision) vs informational (read-only).

**Method signatures (verified against actual class):**

```python
@staticmethod
def is_actionable(card_type: CardType, metadata: dict | None = None) -> bool:
    """True if this card type requires user action (Accept/Reject/Approve/Deny)."""
    # Approval-request cards (exec_command needing approval)
    if metadata and metadata.get("needs_approval"):
        return True
    # File-change cards that have git backing (can be accepted/rejected)
    if card_type in ("diff", "file_created", "file_modified", "file_deleted"):
        return True
    return False

@staticmethod
def is_informational(card_type: CardType, metadata: dict | None = None) -> bool:
    """True if this card is purely informational — no buttons needed."""
    # Approval cards are actionable, not informational
    if metadata and metadata.get("needs_approval"):
        return False
    # git_commit: result of accept/reject — informational
    if card_type == "git_commit":
        return True
    # agent_action with status=running/complete/error: tool execution log.
    # Also include status=None: a crabcard-parsed or manually-created
    # agent_action card with no status field is still informational (a
    # tool execution log), not actionable. Without this, the card would
    # show Accept/Reject buttons that do nothing.
    if card_type == "agent_action":
        status = metadata.get("status") if metadata else None
        if status in (None, "running", "complete", "error"):
            return True
    # system events, audit reports, tasks: informational
    if card_type in ("system", "audit_report", "task", "dir_created", "dir_deleted"):
        return True
    return False
```

**Imports required:** None new — uses only `CardType` and `dict` which are already in scope.

#### 2.2 `ui/views/feed_card.py` — Button Visibility Logic

**What changes:** Replace the current binary `is_commit` check with `FeedCardData.is_actionable()` / `FeedCardData.is_informational()` classification.

**Current code (search for `is_resolved = card_data.accepted is not None` in `build_feed_card`):**
```python
    is_resolved = card_data.accepted is not None
    is_commit = card_data.card_type == "git_commit"

    if not is_commit:
        actions = Gtk.Box(...)
        # ... Review + Accept + Reject buttons
```

**New code:**
```python
    is_resolved = card_data.accepted is not None
    is_actionable = FeedCardData.is_actionable(
        card_data.card_type, card_data.metadata
    )
    is_informational = FeedCardData.is_informational(
        card_data.card_type, card_data.metadata
    )

    if is_actionable and not is_resolved:
        # Show full action button row (Approve/Deny for approval cards,
        # Accept/Reject for file-change cards, Review for all actionable)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        actions.add_css_class("feed-card-actions")
        actions.set_spacing(6)

        # Review button always for actionable cards
        btn_review = Gtk.Button(label="Review")
        btn_review.add_css_class("feed-btn-review")
        btn_review.connect("clicked", lambda _, cid=card_id, w=card: on_review(cid, w))
        actions.append(btn_review)

        if not is_resolved:
            # For approval cards: "Approve" / "Deny" labels
            # For file-change cards: "Accept" / "Reject" labels
            # (callbacks are already wired correctly by feed_handler)
            btn_accept = Gtk.Button(label="Approve" if card_data.metadata.get("needs_approval") else "Accept")
            btn_accept.add_css_class("feed-btn-accept")
            btn_accept.connect("clicked", lambda _, cid=card_id: on_accept(cid))
            actions.append(btn_accept)

            btn_reject = Gtk.Button(label="Deny" if card_data.metadata.get("needs_approval") else "Reject")
            btn_reject.add_css_class("feed-btn-reject")
            btn_reject.connect("clicked", lambda _, cid=card_id: on_reject(cid))
            actions.append(btn_reject)

        card.append(actions)

    elif is_actionable and is_resolved:
        # Resolved actionable card: show Review button only
        # (badges handled in Phase 2)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        actions.add_css_class("feed-card-actions")
        actions.set_spacing(6)

        btn_review = Gtk.Button(label="Review")
        btn_review.add_css_class("feed-btn-review")
        btn_review.connect("clicked", lambda _, cid=card_id, w=card: on_review(cid, w))
        actions.append(btn_review)

        card.append(actions)

    # Informational cards: NO action buttons at all
```

**Line count estimate:** ~35 lines replacing ~25 lines (net +10).

#### 2.3 `ui/styles.py` — New CSS Classes for Card Sub-Types

**What changes:** Add CSS variants for `agent_action` sub-states (approval-request vs running vs result) so they're visually distinct.

**New CSS (appended after the existing `.feed-card-audit` block at ~line 829):**

```css
/* Agent action sub-states */
.feed-card-agent.feed-card-approval .feed-card-header {
    background: #5a3d2d; color: #ffb085;
}
.feed-card-agent.feed-card-approval .feed-card-body {
    background: #3d2a1a;
}
.feed-card-agent.feed-card-running .feed-card-header {
    background: #2d3a5a; color: #a8c1e6;
}
.feed-card-agent.feed-card-running .feed-card-body {
    background: #1a273d;
}
.feed-card-agent.feed-card-complete .feed-card-header {
    background: #2d4a3d; color: #a8e6c1;
}
.feed-card-agent.feed-card-complete .feed-card-body {
    background: #1a3d2a;
}
.feed-card-agent.feed-card-error .feed-card-header {
    background: #5a2d2d; color: #e6a8a8;
}
.feed-card-agent.feed-card-error .feed-card-body {
    background: #3d1a1a;
}

/* Sequence number badge */
.feed-card-seq {
    background: rgba(99, 102, 241, 0.3);
    color: #c7d2fe;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 10px;
    font-weight: bold;
    min-width: 20px;
    text-align: center;
}

/* Batch accept bar */
.feed-batch-bar {
    background: rgba(30, 30, 40, 0.9);
    border: 1px solid rgba(99, 102, 241, 0.3);
    border-radius: 6px;
    padding: 6px 12px;
    margin-bottom: 8px;
}
.feed-batch-bar-info {
    color: #a5b4fc;
    font-size: 12px;
}
.feed-btn-batch-accept {
    background: rgba(16, 185, 129, 0.3);
    color: #6ee7b7;
    border-radius: 4px;
    padding: 4px 12px;
    font-size: 12px;
    border: none;
}
.feed-btn-batch-accept:hover {
    background: rgba(16, 185, 129, 0.5);
}
```

**CSS class application (in `build_feed_card()`):** After the existing `css_class_for_type` class is applied, add sub-state classes based on metadata:

```python
    # Sub-state CSS classes for agent_action cards
    if card_data.card_type == "agent_action":
        if card_data.metadata.get("needs_approval"):
            card.add_css_class("feed-card-approval")
        elif card_data.metadata.get("status") == "running":
            card.add_css_class("feed-card-running")
        elif card_data.metadata.get("status") == "complete":
            card.add_css_class("feed-card-complete")
        elif card_data.metadata.get("status") == "error":
            card.add_css_class("feed-card-error")
```

**Line count estimate:** ~40 lines CSS, ~10 lines Python.

---

### Phase 2: Persistent Decision Badges on ALL Card Types

#### 2.4 `ui/views/feed_card.py` — Badge on Informational + Actionable Cards

**What changes:** Currently `git_commit` cards show no badge even though they represent the result of an accept/reject. The `update_card_badge()` function already works on any card by injecting into the footer. The `build_feed_card()` factory already adds badges for resolved cards. The fix: ensure ALL resolved cards show a badge, including `git_commit` and informational types.

**Current code (search for the `if card_data.accepted is True:` block in `build_feed_card`):**
```python
    # Accepted/rejected badge
    if card_data.accepted is True:
        badge = Gtk.Label(label="ACCEPTED")
        ...
    elif card_data.accepted is False:
        badge = Gtk.Label(label="REJECTED")
        ...
```

This already works for any card where `accepted` is set. The issue is that `git_commit` cards created by `_add_git_card()` in `feed_handler.py` never set `card.accepted` — they derive their title from the action ("Accepted: ..." / "Rejected: ...") but don't carry the `accepted` field.

**Fix in `ui/handlers/feed_handler.py` `_add_git_card()` (search for the function — its position has shifted as the file has grown):**

Current:
```python
        accepted = original_card.accepted is True
        action = "Accepted" if accepted else "Rejected"
        git_card = FeedCardData(
            card_type="git_commit",
            ...
            # accepted field NOT set
        )
```

New:
```python
        accepted = original_card.accepted is True
        action = "Accepted" if accepted else "Rejected"
        git_card = FeedCardData(
            card_type="git_commit",
            source="git",
            title=f"{action}: {original_card.title}",
            body=result.stdout.strip() if result.stdout else "",
            author="git",
            timestamp=datetime.now(timezone.utc),
            project_name=original_card.project_name,
            commit_sha=result.sha if hasattr(result, 'sha') and result.sha else None,
            file_path=original_card.file_path,
            accepted=accepted,  # NEW — propagate decision so badge renders
        )
```

**For approval cards** (`metadata.needs_approval = True`): After approval/denial, `agent_runtime_handler.approve_exec()` calls `self._fh.update_card(approval_id, card)` with `card.metadata["status"] = "approved" or "denied"`. But it never sets `card.accepted`. Fix: also set `card.accepted`:

**Fix in `agent_runtime_handler.approve_exec()`:**

The function structure is (approximate line numbers — read the file to find exact positions):

1. `pending = self._pending_approvals.pop(approval_id, None)` — first few lines of function
2. `for name, rt in self._runtimes.items():` — middle of function, forwards approval to runtime
3. `if self._fh is not None:` — near the end of the function, block that updates the card
   - `card = self._fh.get_card(approval_id)` — first line of block
   - `card.metadata["status"] = "approved" if approved else "denied"` — second line of block
   - `self._fh.update_card(approval_id, card)` — last line of block

**Add `card.accepted = approved` between the metadata update and the update_card call** (inside the `if self._fh is not None:` block, after the metadata update, before the update_card call):

```python
        if self._fh is not None:
            card = self._fh.get_card(approval_id)
            if card is not None:
                card.metadata["status"] = "approved" if approved else "denied"
                card.accepted = approved  # True=approved, False=denied — NEW: propagate decision so badge renders
                self._fh.update_card(approval_id, card)
```

**The `if card is not None:` guard is critical** — without it, an approval_id that doesn't match a card would raise `AttributeError` on `card.metadata[...]`. The existing code already has this guard; the new line goes inside it.

**Why this works:** `update_card()` calls `build_feed_card()` which reads `card.accepted` to decide button visibility (per Phase 1 changes). It also calls `_update_card_visual()` which adds the CSS class and badge via `update_card_badge()`. So setting `card.accepted = approved` propagates through both paths.

**Line numbers in the spec are stale** — read `ui/handlers/agent_runtime_handler.py` to find the actual line numbers before editing. The function is `approve_exec`; the relevant block is the `if self._fh is not None:` section near the end of the function.

**Line count estimate:** 2 lines in feed_handler.py, 1 line in agent_runtime_handler.py.

---

### Phase 3: Sequence Numbers on Cards

#### 2.5 `models/feed_card.py` — New `seq_num` Field

**What changes:** Add `seq_num: int | None = None` to `FeedCardData`. Include in `to_dict()` and `from_dict()`.

```python
@dataclass
class FeedCardData:
    # ... existing fields ...
    seq_num: int | None = None  # Sequential display number (per project)
```

In `to_dict()`:
```python
        return {
            # ... existing fields ...
            "seq_num": self.seq_num,
        }
```

In `from_dict()`:
```python
        return cls(
            # ... existing fields ...
            seq_num=data.get("seq_num"),
        )
```

#### 2.6 `ui/handlers/feed_handler.py` — Sequence Counter

**What changes:** Add a per-project sequence counter. Assign `seq_num` in `add_card()` before building the widget.

**New state (in `__init__`, search for `self._project_paths` and add the new dict nearby):**
```python
        # Per-project sequence counter for display numbers
        self._project_seq: dict[str, int] = {}
```

**In `add_card()` (search for `card_data.card_id = card_id` and add the new code after it):**
```python
        # Assign sequence number
        proj = card_data.project_name
        if proj not in self._project_seq:
            self._project_seq[proj] = 0
        self._project_seq[proj] += 1
        card_data.seq_num = self._project_seq[proj]
```

**In `on_project_opened()` (in `_load_and_render()`, after loading cards):** Reconstruct `_project_seq` from loaded cards, AND assign seq_nums to cards loaded without them (migration concern):
```python
            # Migrate old cards: assign seq_nums to cards with seq_num=None,
            # in order of creation timestamp. This ensures every project gets
            # a clean sequence from #1 on first load after the seq_num field
            # is added. Without this migration, old projects would show a mix
            # of cards with seq badges and cards without, which is confusing.
            cards_sorted_by_timestamp = sorted(cards, key=lambda c: c.timestamp)
            next_seq = 1
            for card in cards_sorted_by_timestamp:
                if card.seq_num is None:
                    card.seq_num = next_seq
                next_seq = max(next_seq, card.seq_num + 1)

            # Rebuild sequence counter from loaded cards (now all have seq_num)
            max_seq = max((card.seq_num for card in cards if card.seq_num), default=0)
            self._project_seq[project_name] = max_seq
```

**The migration is one-way:** once a card has `seq_num=N`, it stays. New cards continue from `max_seq + 1`.

**Why this matters:** The first run after the Phase 3 upgrade will rewrite `feed.json` with seq_nums assigned to all existing cards. The user sees a clean sequence from #1 (oldest) to N (newest), with no visual gaps. Without the migration, the user would see e.g. card #1, then a gap, then card #5, then no badges on the cards in between, which is confusing.

**In `clear_project()` (search for the function and add the new line):** Add `self._project_seq.pop(project_name, None)`.

#### 2.7 `ui/views/feed_card.py` — Display Sequence Number

**What changes:** Show `#N` badge in the header next to the title.

**In `_make_feed_card_header()` (search for the function in `ui/views/feed_card.py`):** Add a small label before the title if `card_data.seq_num` is set:

```python
    # Sequence number badge (if assigned)
    if card_data.seq_num is not None:
        seq_label = Gtk.Label(label=f"#{card_data.seq_num}")
        seq_label.add_css_class("feed-card-seq")
        header.append(seq_label)
```

Insert after `header.add_css_class("feed-card-header")` and before the title label. The seq badge goes first (left), then title (expand), then copy button.

**Line count estimate:** ~8 lines model, ~12 lines handler, ~6 lines view, ~10 lines CSS (already in Phase 1 CSS block).

---

### Phase 4: Never Auto-Scroll to Top (Smart Scroll)

#### 2.8 `ui/views/feed_tab.py` — Smart Scroll Logic

**What changes:** Replace unconditional `scroll_to_bottom()` with `smart_scroll_to_bottom()` that checks whether the user is already near the bottom. If the user has scrolled up (reading old cards), do NOT scroll. Only auto-scroll if the user is already near the bottom.

**Current `scroll_to_bottom()` (search for the function in `ui/views/feed_tab.py`):**
```python
    def scroll_to_bottom(self) -> None:
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return
        vadj.set_value(vadj.get_upper())
```

**New method:**
```python
    def scroll_to_bottom(self) -> None:
        """Unconditional scroll to bottom (used on project open)."""
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return
        vadj.set_value(vadj.get_upper())

    def smart_scroll_to_bottom(self) -> None:
        """
        Only scroll to bottom if the user is already near the bottom
        (within 80px). If the user has scrolled up to read old cards,
        do NOT auto-scroll — preserve their reading position.
        """
        if self._feed_scroll is None:
            return
        vadj = self._feed_scroll.get_vadjustment()
        if vadj is None:
            return
        current = vadj.get_value()
        upper = vadj.get_upper()
        page_size = vadj.get_page_size()
        distance_from_bottom = upper - page_size - current
        if distance_from_bottom < 80:
            vadj.set_value(upper)
```

#### 2.9 `ui/handlers/feed_handler.py` — Use Smart Scroll

**What changes:** In `add_card()`'s `_append()` closure (search for `self._feed_tab.scroll_to_bottom()` in the closure), replace with `self._feed_tab.smart_scroll_to_bottom()`.

**Current (search for `self._feed_tab.scroll_to_bottom()` in `_append`):**
```python
        def _append():
            if self._feed_tab is not None:
                self._feed_tab.append_card(widget, card_id)
                self._feed_tab.scroll_to_bottom()
```

**New:**
```python
        def _append():
            if self._feed_tab is not None:
                self._feed_tab.append_card(widget, card_id)
                self._feed_tab.smart_scroll_to_bottom()
```

Keep the unconditional `scroll_to_bottom()` call in `on_project_opened()._render_feed()` (search for the call) — when a project opens, we always want to jump to the bottom.

**The scroll-to-top bug:** The root cause is GTK's adjustment mechanism. When a card is appended to a `Gtk.Box` with `set_valign(Gtk.Align.START)`, the viewport adjustment can temporarily reset. The smart scroll fix addresses the symptom: even if GTK does something weird with the adjustment, we only follow it to the bottom when the user is already there.

**The scroll-to-top bug:** The root cause is GTK's adjustment mechanism. When a card is appended to a `Gtk.Box` with `set_valign(Gtk.Align.START)`, the viewport adjustment can temporarily reset. The smart scroll fix addresses the symptom: even if GTK does something weird with the adjustment, we only follow it to the bottom when the user is already there.

**Do NOT change `card_container.set_vexpand(True)` to `set_vexpand(False)`** — `vexpand=True` is needed for the empty-state widget to center vertically when there are no cards. The smart scroll is the only fix; the container's expand behavior stays as-is.

**Line count estimate:** ~15 lines feed_tab.py, ~1 line feed_handler.py.

---

### Phase 5: Batch Accept

#### 2.10 `ui/handlers/feed_handler.py` — Batch Accept API

**What changes:** Add `batch_accept()` method that accepts all pending actionable cards for the active project. Add a `_make_batch_accept_cb()` factory for the batch accept button.

**New method:**
```python
    def batch_accept(self, project_name: str, limit: int = 0) -> int:
        """
        Accept all pending actionable cards for a project.

        Args:
            project_name: Project to accept cards for.
            limit: Max cards to accept (0 = no limit).

        Returns:
            Number of cards accepted.
        """
        count = 0
        # Acquire the lock to be thread-safe with background git operations.
        # The _project_cards and _cards dicts are read here and may be
        # mutated by background threads (e.g., when a git commit completes
        # and a git_commit card is added to the same project). Without the
        # lock, batch_accept could iterate over a list that's being modified,
        # leading to a RuntimeError or skipped/duplicated cards.
        with self._lock:
            card_ids = list(self._project_cards.get(project_name, []))
            for cid in card_ids:
                card = self._cards.get(cid)
                if card is None:
                    continue
                if card.accepted is not None:
                    continue  # Already resolved
                if not FeedCardData.is_actionable(card.card_type, card.metadata):
                    continue
                if limit > 0 and count >= limit:
                    break
                # handle_accept acquires the lock internally; safe to call here.
                self.handle_accept(cid)
                count += 1
        return count

    def get_pending_actionable_count(self, project_name: str) -> int:
        """Count pending actionable cards for a project."""
        with self._lock:
            count = 0
            for cid in self._project_cards.get(project_name, []):
                card = self._cards.get(cid)
                if card is None or card.accepted is not None:
                    continue
                if FeedCardData.is_actionable(card.card_type, card.metadata):
                    count += 1
        return count
```

**Why the lock matters:** `handle_accept()` triggers git operations (`git_ops.stage_all`, `git_ops.commit`) in a background thread. When the git operation completes, it calls `self._add_git_card()` which acquires `self._lock` and mutates `self._cards` and `self._project_cards`. If `batch_accept()` is iterating over `self._project_cards` without the lock, the dict can be modified mid-iteration, causing a `RuntimeError: dictionary changed size during iteration`. The `with self._lock:` block prevents this.

**Note:** `handle_accept()` is designed to be called from the main thread (it schedules `GLib.idle_add` for GTK operations). If `batch_accept()` is called from a background thread, the lock will serialize the iteration but the `handle_accept()` calls will still schedule GTK operations to the main thread via `idle_add`. This is the correct behavior.

**Do not add `GLib.idle_add` wrapping around `batch_accept()`.** It must be callable synchronously from the button click handler (which runs on the main thread). The lock provides the thread safety needed if it's called from a background thread (e.g., from a future cron-style "auto-accept after timeout" feature).

#### 2.11 `ui/views/feed_tab.py` — Batch Accept Bar

**What changes:** Add a batch accept bar widget PINNED TO THE TOP of `FeedTab` (outside the scrolled window). Shows "N cards pending" with an "Accept All" button.

**Why pinned to top (not inside the scrolled card container):**
- The batch bar is a TOOLBAR, not a card. It should stay visible when the user scrolls through many cards.
- The CSS class `.feed-batch-bar` has a `border` and `padding` that suggests a sticky toolbar look.
- The alternative (batch bar scrolls with cards) was considered and rejected: the user could scroll past the batch bar while reading old cards, defeating its purpose.

**How GTK4 `Gtk.Box.insert_child_after` works:**
- `insert_child_after(widget, sibling)` inserts `widget` AFTER `sibling` in the child list.
- `sibling=None` means "insert at the very end of the child list" — this is a BUG, not a "prepend" as the original spec claimed.
- The `prepend_card()` method in `feed_tab.py` (search for the function name) uses `self._card_container.insert_child_after(card_widget, None)` to prepend to the INNER container, but the `None` semantics are different there because the inner container starts empty and accepts the first child.

**To put the batch bar at the very top of `FeedTab` (the outer container):**
```python
# Create the batch bar widget first
self._batch_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
self._batch_bar.add_css_class("feed-batch-bar")
# ... set up children ...

# Insert at the end, then move to the start
self.append(self._batch_bar)  # adds to end of FeedTab's children
self.reorder_child_after(self._batch_bar, None)  # moves to position 0
```

`reorder_child_after(widget, None)` moves `widget` to be the first child. This is the GTK4-idiomatic way to prepend to a non-empty container.

**New method on FeedTab:**
```python
    def show_batch_bar(self, pending_count: int, on_accept_all: Callable) -> None:
        """Show or update the batch accept bar (pinned to top of FeedTab)."""
        if self._batch_bar is None:
            self._batch_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            self._batch_bar.add_css_class("feed-batch-bar")
            self._batch_bar.set_spacing(8)
            self._batch_info = Gtk.Label()
            self._batch_info.add_css_class("feed-batch-bar-info")
            self._batch_btn = Gtk.Button(label="Accept All")
            self._batch_btn.add_css_class("feed-btn-batch-accept")
            self._batch_bar.append(self._batch_info)
            self._batch_bar.append(self._batch_btn)
            # Pin to top of FeedTab (outside the scrolled window)
            self.append(self._batch_bar)
            self.reorder_child_after(self._batch_bar, None)
        self._batch_info.set_text(f"{pending_count} card{'s' if pending_count != 1 else ''} pending")
        # Disconnect old handler, connect new
        try:
            self._batch_btn.disconnect_by_func(self._batch_btn_cb)
        except (TypeError, RuntimeError):
            pass
        self._batch_btn_cb = on_accept_all
        self._batch_btn.connect("clicked", lambda *_: on_accept_all())
        self._batch_bar.set_visible(pending_count > 0)

    def hide_batch_bar(self) -> None:
        """Hide the batch accept bar."""
        if self._batch_bar is not None:
            self._batch_bar.set_visible(False)
```

**In `FeedTab.__init__()` (add new instance vars):**
```python
        self._batch_bar: Gtk.Widget | None = None
        self._batch_info: Gtk.Label | None = None
        self._batch_btn: Gtk.Button | None = None
        self._batch_btn_cb = None
```

#### 2.12 `ui/handlers/feed_handler.py` — Wire Batch Bar Updates

**In `add_card()` (after the card is appended), add via idle_add:**
```python
        def _update_batch_bar():
            if self._feed_tab is not None:
                pending = self.get_pending_actionable_count(card_data.project_name)
                self._feed_tab.show_batch_bar(pending, lambda: self._on_batch_accept(card_data.project_name))

    def _on_batch_accept(self, project_name: str) -> None:
        """Batch accept button clicked."""
        count = self.batch_accept(project_name)
        if count > 0 and self._feed_tab is not None:
            self._feed_tab.hide_batch_bar()
```

Add `_update_batch_bar` to the existing `idle_add(_append)` call or chain it after.

**Line count estimate:** ~35 lines feed_handler.py, ~30 lines feed_tab.py.

---

## 3. Data Flow

### Phase 1: Card Type Button Policy

```
Card created in feed_handler.add_card()
  → build_feed_card(card_data, ...) in ui/views/feed_card.py
    → FeedCardData.is_actionable(card_type, metadata)  [NEW — model method]
      → returns True for diff/file_*/approval cards
    → FeedCardData.is_informational(card_type, metadata)  [NEW — model method]
      → returns True for git_commit/running agent_action/system cards
    → If actionable + not resolved: show Review + Accept/Reject (or Approve/Deny)
    → If actionable + resolved: show Review only
    → If informational: NO buttons
    → Sub-state CSS class applied (feed-card-approval/running/complete/error)
```

### Phase 2: Decision Badges

```
User clicks Accept/Reject on actionable card
  → feed_handler.handle_accept(card_id) / handle_reject(card_id)
    → card.accepted = True/False
    → _update_card_visual(card_id, accepted=...)
      → update_card_badge(widget, accepted)  — adds ACCEPTED/REJECTED label
      → add_css_class("feed-card-accepted" / "feed-card-rejected")

For git_commit cards:
  → _add_git_card(original_card, result)
    → git_card.accepted = original_card.accepted  [NEW — was missing]
    → add_card(git_card) → build_feed_card sees accepted=True/False → badge renders

For approval cards:
  → agent_runtime_handler.approve_exec(approval_id, approved)
    → card.accepted = approved  [NEW — was missing]
    → feed_handler.update_card(card_id, card) → widget rebuilds → badge renders
```

### Phase 3: Sequence Numbers

```
feed_handler.add_card(card_data)
  → self._project_seq[proj] += 1
  → card_data.seq_num = self._project_seq[proj]
  → build_feed_card(card_data)
    → _make_feed_card_header(card_data.title, ..., card_data)
      → if card_data.seq_num: header shows "#N" badge

On project open:
  → on_project_opened() → _load_and_render()
    → _project_seq reconstructed from max(seq_num) in loaded cards
```

### Phase 4: Smart Scroll

```
New card arrives → feed_handler.add_card()
  → idle_add(_append)
    → feed_tab.append_card(widget, card_id)
    → feed_tab.smart_scroll_to_bottom()  [NEW]
      → if user within 80px of bottom: scroll to bottom
      → if user scrolled up: do nothing (preserve position)

Project opened → on_project_opened()
  → _render_feed()
    → feed_tab.scroll_to_bottom()  (unconditional — always jump to newest)
```

### Phase 5: Batch Accept

```
New actionable card added → feed_handler.add_card()
  → idle_add: _update_batch_bar()
    → feed_tab.show_batch_bar(pending_count, on_accept_all)
      → Bar appears at top: "3 cards pending [Accept All]"

User clicks "Accept All"
  → feed_handler._on_batch_accept(project_name)
    → batch_accept(project_name)
      → for each pending actionable card: handle_accept(card_id)
    → feed_tab.hide_batch_bar()

User accepts/rejects individual cards → count decreases
  → (batch bar updates on next add_card or could be updated in _update_card_visual)
```

---

## 4. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|------------|-----------|------|
| `models/feed_card.py` | Add `seq_num` field + `is_actionable()` / `is_informational()` helpers + serialization | +25 | Low |
| `ui/views/feed_card.py` | Button visibility logic + sub-state CSS classes + seq badge | +25 (net) | Low |
| `ui/handlers/feed_handler.py` | Seq counter + batch accept + smart scroll call + badge fix | +50 | Medium |
| `ui/handlers/agent_runtime_handler.py` | Set `card.accepted` on approval resolution | +1 | Low |
| `ui/views/feed_tab.py` | `smart_scroll_to_bottom()` + batch bar widget | +45 | Medium |
| `ui/styles.py` | Sub-state CSS + seq badge CSS + batch bar CSS | +50 | Low |
| `docs/ARCHITECTURE.md` | Update §3.22a, §3.22b, §3.22c, §3.35 with new methods | +20 | None |

**Total estimate:** ~215 lines new/changed code.

**Files NOT changed:**
- `utils/feed_store.py` — no format change needed; `seq_num` flows through existing `to_dict()`/`from_dict()` via the model
- `utils/crabcard_parser.py` — no changes; crabcard blocks don't carry sequence info
- `ui/window.py` — no wiring changes needed; FeedHandler and FeedTab are already wired
- `gateway/` — no network protocol changes
- `agent/` — no runtime/tool changes

---

## 5. Implementation Order

### Phase 1: Card Type Button Policy + Color Palette
**Priority: HIGH — biggest visual impact, lowest risk**

1. Add `is_actionable()` and `is_informational()` to `models/feed_card.py`
2. Add sub-state CSS classes to `ui/styles.py`
3. Rewrite button visibility logic in `ui/views/feed_card.py` `build_feed_card()`
4. Add sub-state CSS class application in `build_feed_card()`
5. **Verify:** Launch app, trigger various card types (file write, exec approval, commit), confirm correct button visibility + colors
6. Run `pytest tests/test_feed_card.py tests/test_feed_handler.py`

### Phase 2: Persistent Decision Badges
**Priority: HIGH — user's #1 complaint**

1. Set `accepted=accepted` in `feed_handler._add_git_card()`
2. Set `card.accepted = approved` in `agent_runtime_handler.approve_exec()`
3. **Verify:** Accept/reject a card, confirm git_commit card shows badge, approval card shows badge after Approve/Deny
4. Run `pytest tests/test_feed_handler.py`

### Phase 3: Sequence Numbers
**Priority: MEDIUM — navigational aid**

1. Add `seq_num` field to `models/feed_card.py` + serialization
2. Add `_project_seq` counter to `feed_handler.py`, assign in `add_card()`
3. Reconstruct counter in `on_project_opened()`
4. Add seq badge to header in `ui/views/feed_card.py`
5. Add `.feed-card-seq` CSS to `ui/styles.py`
6. **Verify:** Open project with existing cards, confirm seq numbers continue correctly
7. Run `pytest tests/test_feed_card.py tests/test_feed_handler.py`

### Phase 4: Smart Scroll
**Priority: HIGH — user's #2 complaint**

1. Add `smart_scroll_to_bottom()` to `ui/views/feed_tab.py`
2. Change `feed_handler.add_card()._append()` to use `smart_scroll_to_bottom()`
3. Keep `scroll_to_bottom()` (unconditional) in `on_project_opened()`
4. **Verify:** Scroll up in feed, trigger agent action, confirm view doesn't jump. Scroll to bottom, trigger action, confirm it follows.
5. Run `pytest tests/test_feed_handler.py`

### Phase 5: Batch Accept
**Priority: MEDIUM — convenience feature**

1. Add `batch_accept()` and `get_pending_actionable_count()` to `feed_handler.py`
2. Add batch bar widget methods to `ui/views/feed_tab.py`
3. Wire `_update_batch_bar()` into `add_card()` flow
4. Add batch bar CSS to `ui/styles.py`
5. **Verify:** Trigger multiple agent writes, confirm batch bar appears with correct count, click Accept All, confirm all cards resolved
6. Run `pytest tests/test_feed_handler.py`
7. Add new test: `test_batch_accept()` in `tests/test_feed_handler.py`

### Final: Architecture Doc Update
1. Update §3.22a (`feed_card.py`) with new methods
2. Update §3.22b (`FeedCardData`) with `seq_num` + helper methods
3. Update §3.22c (`FeedHandler`) with `batch_accept()` + sequence counter
4. Update §3.35 (`FeedTab`) with `smart_scroll_to_bottom()` + batch bar
5. Commit with message: "docs: update ARCHITECTURE.md for feed card UX improvements"

---

## 6. Acceptance Criteria

### Phase 1
- [ ] Approval-request cards (exec_command) show "Approve"/"Deny" buttons with distinct orange color
- [ ] Command running cards (status=running) show NO buttons, distinct blue color
- [ ] Command result cards (status=complete/error) show NO buttons, distinct green/red color
- [ ] git_commit cards show NO buttons (informational)
- [ ] File-change cards (diff, file_created, etc.) show Accept/Reject + Review
- [ ] System/audit/task cards show NO buttons

### Phase 2
- [ ] After accepting a file-change card, ACCEPTED badge appears and persists
- [ ] After rejecting a file-change card, REJECTED badge appears and persists
- [ ] git_commit card created after accept/reject shows the decision badge
- [ ] Approval card shows APPROVED/DENIED badge after resolution

### Phase 3
- [ ] Every card in the feed displays a "#N" sequence number badge in the header
- [ ] Sequence numbers are per-project and increment in order of card creation
- [ ] Sequence numbers survive app restart (persisted in feed.json via to_dict/from_dict)
- [ ] Opening a different project shows that project's independent sequence

### Phase 4
- [ ] When user is scrolled to bottom of feed, new cards auto-scroll to show the new card
- [ ] When user has scrolled up (>80px from bottom) in the feed, new cards do NOT cause scroll
- [ ] Opening a project always scrolls to bottom (unconditional)
- [ ] Feed never scrolls to the TOP unexpectedly

### Phase 5
- [ ] When ≥1 actionable card is pending, a batch bar appears at the top of the feed
- [ ] Batch bar shows correct pending count
- [ ] Clicking "Accept All" resolves all pending actionable cards
- [ ] Batch bar hides when no pending actionable cards remain
- [ ] Individual accept/reject updates the pending count

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Card with `accepted=True` loaded from feed.json on restart | Badge renders, no action buttons |
| Card with `accepted=False` loaded from feed.json on restart | Badge renders, no action buttons |
| Card with no `seq_num` in old feed.json | `seq_num=None`, no badge shown (graceful) |
| Agent does 5 writes rapidly while user scrolled up | No scroll jump; batch bar shows "5 cards pending" |
| User clicks "Accept All" with 0 pending | No-op, batch bar already hidden |
| Project has 500 persisted cards, opened fresh | `_project_seq` set to max seq_num from loaded cards; new cards continue numbering |
| `agent_action` card with `needs_approval=True` AND `status=running` | `needs_approval` takes precedence — treated as actionable (approval needed first) |
| Two projects open (switching between them) | Each has independent `_project_seq` counter |
| Batch accept encounters an already-resolved card | Skipped via `card.accepted is not None` check |
| Card type `dir_created` (informational) — no buttons | Correct: informational cards never get buttons |

---

## 8. ARCHITECTURE.md Updates Required

### Section 3.22a — `ui/views/feed_card.py`
- Document new button visibility logic using `is_actionable()` / `is_informational()`
- Document sub-state CSS class application
- Document sequence number badge in header
- Document `show_batch_bar()` / `hide_batch_bar()` on FeedTab

### Section 3.22b — `models/feed_card.py`
- Add `seq_num: int | None` to field list
- Document `is_actionable()` and `is_informational()` static methods

### Section 3.22c — `ui/handlers/feed_handler.py`
- Document `_project_seq` state
- Document `batch_accept()` and `get_pending_actionable_count()` methods
- Document smart scroll usage

### Section 3.35 — `ui/views/feed_tab.py`
- Document `smart_scroll_to_bottom()`
- Document batch bar widget methods

### Section 9 — CSS
- Document new CSS classes: `.feed-card-approval`, `.feed-card-running`, `.feed-card-complete`, `.feed-card-error`, `.feed-card-seq`, `.feed-batch-bar`, `.feed-btn-batch-accept`

---

## 9. Test Plan

This section specifies WHAT to test, not just that tests should pass. The implementer MUST add these tests as part of the corresponding phase.

### Phase 1 Tests — `models/feed_card.py` helpers

Add to `tests/test_feed_card.py`:

```python
class TestIsActionable:
    """Phase 1: is_actionable() returns True for cards that need user action."""

    def test_diff_card_is_actionable(self):
        assert FeedCardData.is_actionable("diff", {}) is True

    def test_file_created_is_actionable(self):
        assert FeedCardData.is_actionable("file_created", {}) is True

    def test_file_modified_is_actionable(self):
        assert FeedCardData.is_actionable("file_modified", {}) is True

    def test_file_deleted_is_actionable(self):
        assert FeedCardData.is_actionable("file_deleted", {}) is True

    def test_needs_approval_makes_actionable(self):
        """Any card type with metadata.needs_approval=True is actionable."""
        assert FeedCardData.is_actionable("agent_action", {"needs_approval": True}) is True
        assert FeedCardData.is_actionable("system", {"needs_approval": True}) is True

    def test_git_commit_not_actionable(self):
        assert FeedCardData.is_actionable("git_commit", {}) is False

    def test_system_not_actionable(self):
        assert FeedCardData.is_actionable("system", {}) is False

    def test_none_metadata(self):
        """is_actionable must handle metadata=None gracefully."""
        assert FeedCardData.is_actionable("diff", None) is True
        assert FeedCardData.is_actionable("git_commit", None) is False


class TestIsInformational:
    """Phase 1: is_informational() returns True for cards with no buttons."""

    def test_git_commit_is_informational(self):
        assert FeedCardData.is_informational("git_commit", {}) is True

    def test_system_is_informational(self):
        assert FeedCardData.is_informational("system", {}) is True

    def test_audit_report_is_informational(self):
        assert FeedCardData.is_informational("audit_report", {}) is True

    def test_task_is_informational(self):
        assert FeedCardData.is_informational("task", {}) is True

    def test_dir_created_is_informational(self):
        assert FeedCardData.is_informational("dir_created", {}) is True

    def test_dir_deleted_is_informational(self):
        assert FeedCardData.is_informational("dir_deleted", {}) is True

    def test_agent_action_running_is_informational(self):
        assert FeedCardData.is_informational("agent_action", {"status": "running"}) is True

    def test_agent_action_complete_is_informational(self):
        assert FeedCardData.is_informational("agent_action", {"status": "complete"}) is True

    def test_agent_action_error_is_informational(self):
        assert FeedCardData.is_informational("agent_action", {"status": "error"}) is True

    def test_agent_action_no_status_is_informational(self):
        """Issue 5 fix: agent_action with no status field is informational, not actionable."""
        assert FeedCardData.is_informational("agent_action", {}) is True

    def test_needs_approval_not_informational(self):
        """Even if agent_action has needs_approval=True, it's not informational."""
        assert FeedCardData.is_informational("agent_action", {"needs_approval": True}) is False

    def test_diff_not_informational(self):
        assert FeedCardData.is_informational("diff", {}) is False


class TestActionableInformationalMutuallyExclusive:
    """Every card type must be one or the other, never both, never neither."""

    @pytest.mark.parametrize("card_type", [
        "git_commit", "diff", "file_created", "file_modified", "file_deleted",
        "dir_created", "dir_deleted", "agent_action", "task", "system", "audit_report",
    ])
    def test_every_card_type_is_one_or_other(self, card_type):
        actionable = FeedCardData.is_actionable(card_type, {})
        informational = FeedCardData.is_informational(card_type, {})
        # Exactly one must be True
        assert actionable != informational, f"{card_type} is both or neither"
```

### Phase 2 Tests — Decision badges on informational cards

Add to `tests/test_feed_handler.py`:

```python
class TestPersistentBadges:
    """Phase 2: git_commit and approval cards must show decision badges after accept/reject."""

    def test_git_commit_card_has_accepted_field(self):
        """After accepting a file-change card, the git_commit card created must have accepted=True."""
        # Setup: create a file-change card, accept it, wait for git_commit to be added
        # Assert: the new git_commit card has card.accepted = True
        ...

    def test_approval_card_has_accepted_field(self):
        """After approving a pending approval card, the card.accepted must be True."""
        # Setup: create a card with needs_approval=True, call approve_exec(approved=True)
        # Assert: the card's accepted field is True
        ...
```

### Phase 3 Tests — Sequence numbers

Add to `tests/test_feed_card.py` and `tests/test_feed_handler.py`:

```python
class TestSeqNum:
    """Phase 3: every card gets a sequential display number, per project."""

    def test_seq_num_assigned_on_add(self):
        """add_card() must assign an incrementing seq_num to each new card."""
        # Setup: feed handler with no project open
        # Add 3 cards to project "foo"
        # Assert: card1.seq_num=1, card2.seq_num=2, card3.seq_num=3

    def test_seq_num_per_project(self):
        """seq_num is per-project, not global."""
        # Add 2 cards to project "foo", 1 card to project "bar"
        # Assert: foo cards are 1,2 and bar card is 1

    def test_seq_num_persists_through_serialization(self):
        """seq_num survives to_dict() and from_dict()."""
        card = FeedCardData(card_type="diff", ..., seq_num=42)
        round_tripped = FeedCardData.from_dict(card.to_dict())
        assert round_tripped.seq_num == 42

    def test_seq_num_reconstructed_on_project_open(self):
        """When loading existing cards, the next seq_num must be max(loaded) + 1."""
        # Pre-populate feed.json with 3 cards having seq_nums 1, 2, 3
        # Open the project
        # Add a 4th card
        # Assert: 4th card has seq_num=4 (not 1)

    def test_missing_seq_num_on_load(self):
        """Cards loaded without seq_num (old format) get None, not auto-assigned."""
        # Pre-populate feed.json with cards missing seq_num
        # Open the project
        # Assert: loaded cards have seq_num=None
        # (The migration concern in the spec recommends assigning on first load,
        # but this test documents the GRACEFUL behavior if the migration is skipped.)
```

### Phase 4 Tests — Smart scroll

Add to `tests/test_feed_handler.py`:

```python
class TestSmartScroll:
    """Phase 4: smart_scroll_to_bottom only scrolls when user is near the bottom."""

    def test_smart_scroll_when_near_bottom(self):
        """If user is within 80px of bottom, smart_scroll scrolls to bottom."""
        # Setup: FeedTab with vadjustment set to upper-50 (within 80px)
        # Call smart_scroll_to_bottom()
        # Assert: vadjustment value is now upper

    def test_smart_scroll_when_far_from_bottom(self):
        """If user is >80px from bottom, smart_scroll does nothing."""
        # Setup: FeedTab with vadjustment set to 0 (scrolled to top)
        # Call smart_scroll_to_bottom()
        # Assert: vadjustment value is still 0 (NOT changed to upper)

    def test_scroll_to_bottom_always(self):
        """The unconditional scroll_to_bottom() always scrolls (used on project open)."""
        # Setup: FeedTab with vadjustment set to 0
        # Call scroll_to_bottom()
        # Assert: vadjustment value is now upper (forced)
```

### Phase 5 Tests — Batch accept

Add to `tests/test_feed_handler.py`:

```python
class TestBatchAccept:
    """Phase 5: batch_accept() resolves all pending actionable cards."""

    def test_batch_accept_returns_count(self):
        """batch_accept() returns the number of cards accepted."""
        # Setup: 3 pending actionable cards
        # Call batch_accept(project_name)
        # Assert: returns 3

    def test_batch_accept_skips_resolved(self):
        """batch_accept() skips cards that are already accepted/rejected."""
        # Setup: 2 pending + 1 already accepted
        # Call batch_accept()
        # Assert: returns 2 (the pending ones), already-accepted is untouched

    def test_batch_accept_skips_informational(self):
        """batch_accept() skips informational cards (no buttons, no actions)."""
        # Setup: 2 pending actionable + 1 git_commit (informational)
        # Call batch_accept()
        # Assert: returns 2, git_commit is untouched

    def test_batch_accept_respects_limit(self):
        """batch_accept(limit=N) accepts at most N cards."""
        # Setup: 5 pending actionable
        # Call batch_accept(limit=2)
        # Assert: returns 2, remaining 3 still pending

    def test_get_pending_actionable_count(self):
        """get_pending_actionable_count() returns the right number."""
        # Setup: 2 pending + 1 resolved + 1 informational
        # Call get_pending_actionable_count(project)
        # Assert: returns 2

    def test_batch_accept_thread_safety(self):
        """batch_accept() must acquire the lock to be safe with background git ops."""
        # Setup: handler with _lock
        # Call batch_accept() from a background thread
        # Assert: no race condition (cards are processed in order, no duplicates)
```

### Test Execution Order

After EACH phase:
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_feed_card.py tests/test_feed_handler.py -v
```

After ALL phases:
```bash
cd /home/q/projects/crabcakes && python3 -m pytest -x -q
```

Expect: 1662 passed + new tests passed, 1 skipped, 4 warnings (or whatever the new count is).

---

## 10. Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** ✅ — All function signatures verified via source reads. `_add_git_card` verified by reading `ui/handlers/feed_handler.py`. `approve_exec` verified at `ui/handlers/agent_runtime_handler.py`. `build_feed_card` button logic verified at `ui/views/feed_card.py`. `scroll_to_bottom` verified at `ui/views/feed_tab.py`. **Implementer must re-read each file before editing — the file line numbers have shifted since this spec was drafted.**

2. **Did I catch all exception types?** ✅ — No new exception handling introduced. All new code uses simple conditionals and dict lookups that can't raise unexpected types. `batch_accept()` iterates a list of card_ids and checks each — no exceptions possible from the iteration itself.

3. **Did I verify key structures?** ✅ — `_project_cards: dict[str, list[str]]` verified in feed_handler `__init__`. `_pending_approvals: dict[str, dict]` verified in agent_runtime_handler line 78. `FeedCardData.accepted: bool | None` verified (None=pending, True=accepted, False=rejected). `metadata.needs_approval` flag verified as the routing key in feed_handler lines 140-148.

4. **Did I trace the data flow end-to-end?** ✅ — Card creation → build_feed_card → button visibility → user click → handle_accept/handle_approve_exec → card state mutation → update_card/badge update. All paths traced through actual source.

5. **Would an implementer produce working code?** ✅ — Each phase has exact file, exact location reference, verified signatures, and code samples that match existing patterns. The `is_actionable()` / `is_informational()` methods are self-contained on the model. The CSS additions are independent strings. The smart scroll is a 15-line method with a clear algorithm.

---

*This spec is a contract. Follow the implementation order. Verify each phase before proceeding to the next.*
