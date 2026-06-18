# Phase 5 of 5 — Batch Accept for Consecutive File-Change Cards

**Master spec:** `/home/q/projects/crabcakes/docs/specs/SPEC-FEED-CARD-UX.md` (read it in full, especially "Spec Revision History" and Section 2.10/2.11/2.12)

**Phase 1-4 status:** COMPLETE (button policy + decision badges + sequence numbers + smart scroll all in working tree, 101/101 targeted tests passing, full suite OOM is a system env issue not a code issue)

**Scope of this phase:** Section 2.10 + 2.11 + 2.12 of the spec (3 files). Medium complexity — touches view (batch bar widget), handler (batch logic), and tests.

---

## ⚠️ MANDATORY: Read every file in full before writing any code

Per `prompts/steelFramedCodeWriter.md` Rule 1, before writing ANY code, read EVERY file you will touch. ALL of it. Not snippets — the whole file. The spec's line numbers are stale — anchor edits to identifiers, NOT line numbers.

**Files to read in full before writing any code:**

1. `ui/views/feed_tab.py` (167 lines) — find `append_card()` and the layout. The new batch bar widget goes ABOVE the feed_scroll (between the top toolbar and the scroll window).
2. `ui/handlers/feed_handler.py` (977 lines) — find `handle_accept()` (singular). The new `handle_batch_accept()` (plural) follows the same pattern but iterates over a list of card_ids.
3. `ui/styles.py` (1185 lines) — find the existing feed-card CSS block. The new `.feed-batch-bar` and `.feed-btn-batch-accept` CSS goes there. **The seq badge CSS `.feed-card-seq` is already in place from Phase 3 — do NOT re-add it.**
4. `tests/test_feed_handler.py` (366 lines) — existing test patterns
5. `tests/test_feed_card.py` (existing test patterns)

**Output a discovery block before writing code** (per steelFramedCodeWriter Step 0).

---

## The feature

**User complaint #4:** "Tedious to Accept each file-change card one at a time when there are 5+ pending."

**What we're building:** When 2+ consecutive file-change cards (`diff`, `file_created`, `file_modified`, `file_deleted`) are pending at the bottom of the feed, show a batch bar above the feed: "3 file changes pending — [Accept All]". Clicking Accept All accepts them all in one go (in order, top-to-bottom), and each one creates a git_commit card as it would individually.

**Key behavior:**
- The batch bar is contextual — it appears only when ≥2 consecutive file-change cards are pending and stacked
- The count reflects the actual pending count (so if 1 was already accepted, the bar shows "2 file changes pending — [Accept All]")
- Accepting one card via individual Accept button updates the bar count or hides it
- "Consecutive" means the pending file-change cards form an unbroken sequence at the BOTTOM of the feed (no git_commit, system, agent_action, or other non-file-change cards between them)

---

## Edits

### Edit 1: `ui/views/feed_tab.py` — Add batch bar widget

Find the `__init__` of the FeedTab class. The current layout has a toolbar at the top, then a `card_container` (Gtk.Box) wrapped in a `feed_scroll` (Gtk.ScrolledWindow). The batch bar goes BETWEEN the toolbar and the feed_scroll.

**a) Add a new attribute in `__init__`:**

```python
        # Batch accept bar (Phase 5): shown when ≥2 consecutive file-change cards are pending
        self._batch_bar: Gtk.Box | None = None
```

**b) Add a new method `update_batch_bar(self, pending_count: int)`:**

```python
    def update_batch_bar(self, pending_count: int) -> None:
        """
        Show or hide the batch accept bar based on pending consecutive file-change cards.
        pending_count is the number of consecutive pending file-change cards stacked
        at the bottom of the feed. Bar is hidden if count < 2. (Phase 5)
        """
        if pending_count < 2:
            if self._batch_bar is not None:
                self._batch_bar.set_visible(False)
            return
        if self._batch_bar is None:
            # Lazy-create on first show
            self._batch_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            self._batch_bar.add_css_class("feed-batch-bar")
            info_label = Gtk.Label()
            info_label.add_css_class("feed-batch-bar-info")
            self._batch_bar.append(info_label)
            self._batch_bar._info_label = info_label  # type: ignore[attr-defined]

            accept_btn = Gtk.Button(label="Accept All")
            accept_btn.add_css_class("feed-btn-batch-accept")
            accept_btn.connect("clicked", lambda _: self._on_batch_accept_clicked())
            self._batch_bar.append(accept_btn)
            self._batch_bar._accept_btn = accept_btn  # type: ignore[attr-defined]

            # Insert before feed_scroll in the parent
            parent = self._feed_scroll.get_parent()
            if parent is not None:
                parent.insert_child_before(self._batch_bar, self._feed_scroll)

        # Update the count text
        self._batch_bar._info_label.set_text(  # type: ignore[attr-defined]
            f"{pending_count} file changes pending"
        )
        self._batch_bar.set_visible(True)
```

**c) Add a placeholder callback hook** (the real callback is wired in Edit 2):

```python
    def _on_batch_accept_clicked(self) -> None:
        """
        Placeholder — overridden by FeedHandler when it wires the batch accept flow.
        The handler calls set_batch_accept_callback() to install the real handler. (Phase 5)
        """
        pass
```

**d) Add a setter for the callback:**

```python
    def set_batch_accept_callback(self, callback: Callable[[], None]) -> None:
        """
        Install the real batch accept callback. Called by FeedHandler after construction. (Phase 5)
        """
        self._on_batch_accept_clicked = callback
```

**Important:** The `Callable` type needs `from typing import Callable` at the top of the file (check if it's already imported; if not, add it).

### Edit 2: `ui/handlers/feed_handler.py` — Add `handle_batch_accept()`

Find `handle_accept()` (singular). The new `handle_batch_accept()` follows the same structure but iterates over a list.

**a) Add the new method right after `handle_accept()`:**

```python
    def handle_batch_accept(self, card_ids: list[str]) -> None:
        """
        Accept a batch of consecutive file-change cards in one click.
        Iterates in order (top-to-bottom in the feed); each accept creates a
        git_commit card via _add_git_card() with the same flow as the singular
        handle_accept(). (Phase 5)

        Used by the batch accept bar when ≥2 file-change cards are pending.
        """
        for card_id in card_ids:
            self.handle_accept(card_id)
```

**b) Wire the callback in the constructor (or wherever FeedTab is created/connected to FeedHandler):**

Find where `FeedHandler` connects to `FeedTab` (look for `set_callback` or `on_card_added` wiring near the end of `__init__`). Add the wiring:

```python
        # Phase 5: wire batch accept callback
        if self._feed_tab is not None:
            self._feed_tab.set_batch_accept_callback(
                lambda: self._on_batch_accept_clicked()
            )
```

**c) Add the trigger method:**

```python
    def _on_batch_accept_clicked(self) -> None:
        """
        Called when user clicks the batch accept bar's "Accept All" button.
        Computes the list of consecutive pending file-change cards at the
        bottom of the feed and accepts them all. (Phase 5)
        """
        if self._feed_tab is None:
            return
        # Get cards for the currently active project
        project_name = self._active_project_name
        if project_name is None:
            return
        all_cards = self.get_cards_for_project(project_name)
        if not all_cards:
            return
        # Cards are stored newest-first. Find the trailing run of pending file-change cards.
        actionable_types = ("diff", "file_created", "file_modified", "file_deleted")
        batch_ids: list[str] = []
        for card in all_cards:  # newest first
            if (card.card_type in actionable_types
                    and card.accepted is None
                    and card.card_id is not None):
                batch_ids.append(card.card_id)
            else:
                break
        # batch_ids is now newest-first; reverse to top-to-bottom for handle_accept order
        batch_ids.reverse()
        self.handle_batch_accept(batch_ids)
        # Refresh the batch bar (count may now be 0 or 1)
        self._update_batch_bar_for_active_project()

    def _update_batch_bar_for_active_project(self) -> None:
        """Recompute the pending count for the active project and update the bar."""
        if self._feed_tab is None or self._active_project_name is None:
            return
        all_cards = self.get_cards_for_project(self._active_project_name)
        actionable_types = ("diff", "file_created", "file_modified", "file_deleted")
        count = 0
        for card in all_cards:  # newest first
            if (card.card_type in actionable_types and card.accepted is None):
                count += 1
            else:
                break
        self._feed_tab.update_batch_bar(count)
```

**d) Call `_update_batch_bar_for_active_project()` whenever a card state changes:**

In `add_card()` (after the existing seq_num logic), add:

```python
        # Refresh batch accept bar (Phase 5)
        self._update_batch_bar_for_active_project()
```

And in `handle_accept()` (right before the return), add:

```python
        # Refresh batch accept bar (Phase 5)
        self._update_batch_bar_for_active_project()
```

**Important:** Do NOT call the bar update from background threads. `add_card()` is called on the main thread via GLib.idle_add in the existing code path. ✓

### Edit 3: `ui/styles.py` — Add batch bar CSS

Find the existing `.feed-card-seq` CSS block (Phase 3 added it). Add the batch bar CSS right after the seq badge CSS:

```css
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

**Important:** The CSS from Phase 1 spec scope creep (`.feed-card-seq` etc.) was REVERTED in my Phase 1 audit because it was out of scope. Phase 3 added the `.feed-card-seq` CSS back in scope. The batch bar CSS here is in scope for Phase 5 — add it now.

### Edit 4: `tests/test_feed_handler.py` and `tests/test_feed_card.py` — Add Phase 5 tests

Add the `TestBatchAccept` test class from spec section 9 (Phase 5 Tests). The tests cover:
- `update_batch_bar(0)` hides the bar
- `update_batch_bar(1)` hides the bar
- `update_batch_bar(2)` shows the bar with "2 file changes pending"
- `update_batch_bar(3)` shows the bar with "3 file changes pending"
- Clicking Accept All triggers `handle_batch_accept` with the correct card_ids
- `handle_batch_accept` calls `handle_accept` for each card_id in order
- The trailing-run logic: if 1 diff + 1 system + 2 diffs, only the trailing 2 are batched
- `_update_batch_bar_for_active_project` correctly counts trailing pending file-change cards

**Total: 4 edits in 3 source files + 1 test file. ~80-100 lines of production code + ~150-200 lines of test code.**

---

## Rules

- Use the `prompts/steelFramedCodeWriter.md` prompt
- Read every file in full before editing
- Anchor edits to identifiers, NOT line numbers
- Scope is exactly the 4 edits above. Do NOT touch any other file.
- Do NOT silently expand scope. If you find a related issue, note it in the COMPLETENESS checklist as "Related issue found, not fixed in this phase" and stop.
- Do NOT touch the ARCHITECTURE.md doc updates — those come after all phases ship.
- Do NOT add a global "Accept All" button. The bar is contextual, shown only when ≥2 consecutive file-change cards are pending.
- Do NOT call `_update_batch_bar_for_active_project()` from background threads. It's main-thread only.
- Do NOT use `GLib.idle_add` for the bar update — `add_card()` is already on the main thread.
- Do NOT change the unconditional `scroll_to_bottom()` behavior from Phase 4.
- Do NOT re-add the Phase 1 scope creep CSS (`.feed-card-seq` was added in Phase 3; the batch bar CSS is new for Phase 5).

## Verification commands to run (in order)

1. **Batch bar widget methods exist:**
   ```bash
   cd /home/q/projects/crabcakes && grep -n "def update_batch_bar\|def set_batch_accept_callback\|def _on_batch_accept_clicked" ui/views/feed_tab.py
   ```
   Expect: 3 matches (one per method)

2. **Batch bar CSS exists:**
   ```bash
   cd /home/q/projects/crabcakes && grep -c "feed-batch-bar\|feed-btn-batch-accept" ui/styles.py
   ```
   Expect: ≥ 4 matches (the CSS definitions and selectors)

3. **Handler methods exist:**
   ```bash
   cd /home/q/projects/crabcakes && grep -n "def handle_batch_accept\|def _on_batch_accept_clicked\|def _update_batch_bar_for_active_project" ui/handlers/feed_handler.py
   ```
   Expect: 3 matches

4. **Wiring is present:**
   ```bash
   cd /home/q/projects/crabcakes && grep -n "set_batch_accept_callback\|_update_batch_bar_for_active_project" ui/handlers/feed_handler.py
   ```
   Expect: ≥ 2 matches (one for set_batch_accept_callback, multiple for the bar update calls)

5. **New tests pass:**
   ```bash
   cd /home/q/projects/crabcakes && python3 -m pytest tests/test_feed_handler.py tests/test_feed_card.py -v
   ```
   Expect: all existing tests + new TestBatchAccept tests pass

6. **Import sanity:**
   ```bash
   cd /home/q/projects/crabcakes && python3 -c "import ui.views.feed_tab; import ui.handlers.feed_handler; print('OK')"
   ```
   Expect: `OK`

7. **Trailing-run logic sanity:**
   ```bash
   cd /home/q/projects/crabcakes && python3 -c "
   from datetime import datetime, timezone
   from models.feed_card import FeedCardData
   # Build a feed: 1 diff accepted, 1 system, 2 diffs pending (newest first = batch_ids)
   cards = [
       FeedCardData(card_type='diff', source='s', title='t', body='b', author='a', timestamp=datetime.now(timezone.utc), project_name='p', accepted=None),
       FeedCardData(card_type='diff', source='s', title='t', body='b', author='a', timestamp=datetime.now(timezone.utc), project_name='p', accepted=None),
       FeedCardData(card_type='system', source='s', title='t', body='b', author='a', timestamp=datetime.now(timezone.utc), project_name='p', accepted=None),
       FeedCardData(card_type='diff', source='s', title='t', body='b', author='a', timestamp=datetime.now(timezone.utc), project_name='p', accepted=True),
   ]
   actionable = ('diff', 'file_created', 'file_modified', 'file_deleted')
   count = 0
   for c in cards:
       if c.card_type in actionable and c.accepted is None:
           count += 1
       else:
           break
   assert count == 2, f'Expected 2 trailing pending diffs, got {count}'
   print(f'Trailing-run logic correct: {count} pending')
   "
   ```
   Expect: `Trailing-run logic correct: 2 pending`

8. **No accidental scope creep:**
   ```bash
   cd /home/q/projects/crabcakes && git diff HEAD --stat
   ```
   Expect: only `ui/views/feed_tab.py`, `ui/handlers/feed_handler.py`, `ui/styles.py`, `tests/test_feed_handler.py`, `tests/test_feed_card.py` changed (plus prior phase changes which were not re-modified).

## Report

When done, send back a completion report with:
- Files changed with line numbers (of the actual edits, not the spec's claimed line numbers)
- Output of all 8 verification commands
- Full pytest output for the test_feed_handler.py and test_feed_card.py runs
- COMPLETENESS checklist (per steelFramedCodeWriter Step 6.5)
- Any related issues found (flagged, not silently fixed)

**Required word marker for /ask acknowledgment: "please write"** — include it in your response so the channel knows your acknowledgment is canonical.

**Do not skip the COMPLETENESS checklist.** Include every edit with `[x]` or `[NOT DONE] WHY` and paste the evidence. A response without the literal `**COMPLETENESS:** [x]` block is a missing deliverable.

**FINAL PHASE:** This is the last of 5 phases. After Phase 5 is complete and audited clean, I (the supervisor) will write the 11-section post-mortem and commit/push all 5 phases. Do NOT commit anything yourself — leave the working tree dirty for the post-mortem + commit cycle.
