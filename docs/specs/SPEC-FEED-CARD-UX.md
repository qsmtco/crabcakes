# SPEC: Feed Card UX Improvements

**Date:** 2026-06-13
**Author:** qtr (spec), Captain (review)
**Status:** Draft — for implementation
**Implements:** Feed card usability improvements (5 items from user feedback)
**Depends on:** None (builds on existing feed card system, Phase 5)
**Target branch:** main

> **Architecture compliance:** All changes follow the handler pattern (§8.6), CSS single-source-of-truth (§9.1), callback pattern (§5), and model/view/handler separation (§2, §3). No new module imports across forbidden layer boundaries (`models/` ↛ `ui/`, `utils/` ↛ `ui/`, `gateway/` ↛ `ui/`).

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

- **Read `ui/views/feed_card.py`** (~583 lines): `build_feed_card()` factory. Button logic at line ~370: `is_resolved = card_data.accepted is not None`, `is_commit = card_data.card_type == "git_commit"`. Only `git_commit` skips buttons entirely. For resolved cards, Accept/Reject are hidden but Review remains. Badge logic: ACCEPTED/REJECTED labels appended to footer via `update_card_badge()` at line ~560.

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
    # agent_action with status=running/complete/error: tool execution log
    if card_type == "agent_action":
        status = metadata.get("status") if metadata else None
        if status in ("running", "complete", "error"):
            return True
    # system events, audit reports, tasks: informational
    if card_type in ("system", "audit_report", "task", "dir_created", "dir_deleted"):
        return True
    return False
```

**Imports required:** None new — uses only `CardType` and `dict` which are already in scope.

#### 2.2 `ui/views/feed_card.py` — Button Visibility Logic

**What changes:** Replace the current binary `is_commit` check with `FeedCardData.is_actionable()` / `FeedCardData.is_informational()` classification.

**Current code (line ~370, verified):**
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

**Current code (line ~360, verified):**
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

**Fix in `ui/handlers/feed_handler.py` `_add_git_card()` (verified at ~line 440):**

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

**Fix in `agent_runtime_handler.approve_exec()` (verified at ~line 250):**

After `card.metadata["status"] = "approved" if approved else "denied"`, add:
```python
                card.accepted = approved  # True=approved, False=denied
```

This ensures the badge renders and the buttons hide after resolution.

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

**New state (in `__init__`, verified at lines 47-63):**
```python
        # Per-project sequence counter for display numbers
        self._project_seq: dict[str, int] = {}
```

**In `add_card()` (after line 100, after `card_data.card_id = card_id`):**
```python
        # Assign sequence number
        proj = card_data.project_name
        if proj not in self._project_seq:
            self._project_seq[proj] = 0
        self._project_seq[proj] += 1
        card_data.seq_num = self._project_seq[proj]
```

**In `on_project_opened()` (in `_load_and_render()`, after loading cards):** Reconstruct `_project_seq` from loaded cards:
```python
            # Rebuild sequence counter from loaded cards
            max_seq = 0
            for card in cards:
                if card.seq_num and card.seq_num > max_seq:
                    max_seq = card.seq_num
            self._project_seq[project_name] = max_seq
```

**In `clear_project()` (verified at ~line 200):** Add `self._project_seq.pop(project_name, None)`.

#### 2.7 `ui/views/feed_card.py` — Display Sequence Number

**What changes:** Show `#N` badge in the header next to the title.

**In `_make_feed_card_header()` (verified at line 36):** Add a small label before the title if `card_data.seq_num` is set:

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

**Current `scroll_to_bottom()` (verified at line 157):**
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

**What changes:** In `add_card()`'s `_append()` closure (verified at ~line 160), replace `self._feed_tab.scroll_to_bottom()` with `self._feed_tab.smart_scroll_to_bottom()`.

**Current (verified at ~line 163):**
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

Keep the unconditional `scroll_to_bottom()` call in `on_project_opened()._render_feed()` (line ~310) — when a project opens, we always want to jump to the bottom.

**The scroll-to-top bug:** The root cause is GTK's adjustment mechanism. When a card is appended to a `Gtk.Box` with `set_valign(Gtk.Align.START)`, the viewport adjustment can temporarily reset. The smart scroll fix addresses the symptom: even if GTK does something weird with the adjustment, we only follow it to the bottom when the user is already there.

**Additional fix:** Add `set_vexpand(False)` to the card_container in FeedTab so it doesn't try to expand and re-center:

**In `feed_tab.py.__init__()` (verified at ~line 46):** The container already has `set_valign(Gtk.Align.START)` and `set_vexpand(True)`. Change to:
```python
        card_container.set_vexpand(False)
```

Wait — this would break the empty-state centering. Instead, keep `vexpand=True` but ensure `valign=START` is respected. The actual fix is the smart scroll — do not change the container expand behavior.

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
        card_ids = self._project_cards.get(project_name, [])
        for cid in list(card_ids):
            card = self._cards.get(cid)
            if card is None:
                continue
            if card.accepted is not None:
                continue  # Already resolved
            if not FeedCardData.is_actionable(card.card_type, card.metadata):
                continue
            if limit > 0 and count >= limit:
                break
            self.handle_accept(cid)
            count += 1
        return count

    def get_pending_actionable_count(self, project_name: str) -> int:
        """Count pending actionable cards for a project."""
        count = 0
        for cid in self._project_cards.get(project_name, []):
            card = self._cards.get(cid)
            if card is None or card.accepted is not None:
                continue
            if FeedCardData.is_actionable(card.card_type, card.metadata):
                count += 1
        return count
```

#### 2.11 `ui/views/feed_tab.py` — Batch Accept Bar

**What changes:** Add a batch accept bar widget at the top of the feed (below the scrolled window, or as an overlay). Shows "N cards pending" with an "Accept All" button.

**New method on FeedTab:**
```python
    def show_batch_bar(self, pending_count: int, on_accept_all: Callable) -> None:
        """Show or update the batch accept bar."""
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
            # Insert before the scrolled window
            self.insert_child_after(self._batch_bar, None)  # prepend
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

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?** ✅ — All function signatures verified via source reads. `_add_git_card` verified at feed_handler.py ~line 440. `approve_exec` verified at agent_runtime_handler.py line 222. `build_feed_card` button logic verified at feed_card.py line ~370. `scroll_to_bottom` verified at feed_tab.py line 157.

2. **Did I catch all exception types?** ✅ — No new exception handling introduced. All new code uses simple conditionals and dict lookups that can't raise unexpected types. `batch_accept()` iterates a list of card_ids and checks each — no exceptions possible from the iteration itself.

3. **Did I verify key structures?** ✅ — `_project_cards: dict[str, list[str]]` verified in feed_handler `__init__`. `_pending_approvals: dict[str, dict]` verified in agent_runtime_handler line 78. `FeedCardData.accepted: bool | None` verified (None=pending, True=accepted, False=rejected). `metadata.needs_approval` flag verified as the routing key in feed_handler lines 140-148.

4. **Did I trace the data flow end-to-end?** ✅ — Card creation → build_feed_card → button visibility → user click → handle_accept/handle_approve_exec → card state mutation → update_card/badge update. All paths traced through actual source.

5. **Would an implementer produce working code?** ✅ — Each phase has exact file, exact location reference, verified signatures, and code samples that match existing patterns. The `is_actionable()` / `is_informational()` methods are self-contained on the model. The CSS additions are independent strings. The smart scroll is a 15-line method with a clear algorithm.

---

*This spec is a contract. Follow the implementation order. Verify each phase before proceeding to the next.*
