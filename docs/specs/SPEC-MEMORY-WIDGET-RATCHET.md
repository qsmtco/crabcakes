# SPEC: Memory Growth — Widget Ratchet + Per-Item Churn

**Date:** 2026-09-15
**Author:** Lt. Qrusher
**Status:** Draft — for implementation (round-2, post adversarial audit)
**Depends on:** `SPEC-UI-RESPONSIVENESS-2` §2.4 (Phase 4 in-place card updates) — landed `bf0fe54`
**Related:** `docs/proposals/WEBKIT-RENDER-SURFACE_PROPOSAL.md` (the structural alternative)
**Target branch:** main

> **Architecture compliance.** `ui/handlers/feed_handler.py` owns card data and the
> card-id → widget map; `ui/views/feed_tab.py` owns the container and what is parented;
> `ui/views/feed_card.py` owns construction and in-place mutation. The change keeps those
> boundaries.

> **Four adversarial audit rounds have corrected 37 defects** — round 1: ordering
> invariant, the missed `add_cards_batch` widget path, an unreachable acceptance gate, a
> false Load More claim, a suite-breaking test double. Round 2: a missing mock accessor,
> container spacing in the scroll compensation, a lost update on `_backlog`, double-indexing
> on same-project reopen, an unreachable widget-mass gate, an untestable mirror criterion,
> two wrong anchors, two more stale comments, the wrong interpreter. Round 3: Load More
> becoming a permanent no-op, unreachable cards after the backlog drains, a non-monotonic
> arrival metric, a fourth missing mock accessor, a bound that missed non-active projects, a
> vacuous mirror assertion, one more stale docstring, and lock contention with the loader.
> Round 4: a stale backlog copy that would re-render updated cards as pre-update (including a
> re-approve hazard), a count-based criterion that was both vacuous and spuriously failing,
> a loader rebind that discards eviction's push, an under-reporting Load More label, a
> possible duplicate sentinel widget, a sixth stale comment, and a self-contradictory edge
> case. Round 5: the sentinel cleanup was placed on a path that never runs for the case it
> named (load path, not eviction), the loader merge put survivors in the wrong slot, a
> redundant mutation was specified as mandatory, and two §4 counts were stale. Round 6: the
> documented viewport fail-safe was *inverted* — GTK 4.14 returns `compute_bounds -> (True,
> zero rect)` for a never-allocated widget, so unmeasurable widgets were being classified as
> "above the viewport" and destroyed; live arrivals were merged to the wrong end of
> `_project_cards` (invisible to the batch bar and Accept All); the sentinel cleanup skipped
> the no-backlog arm; and the `_load_more` eviction placement was ambiguous enough to produce
> two bars. Round 7 (final): the routing rule for pre-existing ids was built on a false
> premise (compaction-pruned ids were promoted to "newest" and would be committed by Accept
> All), the project-open path was never wired for eviction or widget de-duplication (a
> permanent orphan leak on same-project reopen), two paragraphs gave opposite lock
> instructions for the same dict, and one anchor was off by a line. Verified non-defects are
> recorded in §9. **No audit round after this one** — the next iteration is the implementation
> loop (§5), where the remaining risk lives.

---

## DISCOVERY

- **Read `ui/handlers/feed_handler.py` (2547 lines):** maps and lock at `:71-84`; `PAGE_SIZE = 15` at `:127`; `_backlog` (list of `FeedCardData`, newest-first for `pop(0)`) at `:125`; `add_card` builds + stores a widget at `:790-807` and appends in the idle callback at `:814-817`; **`add_cards_batch` (`:861-952`) is a second, unbounded widget path** — it stores widgets under the lock at `:941-943` and appends in `_append_all` at `:946-952`; `remove_card` (`:986-1001`, callers: tests only); `update_card` (`:1007-1093`) binds `old_widget` at `:1032`, persists, then takes the in-place path when `_body_label` exists (`:1073-1090`) else `_rebuild_and_replace_card` (`:1095-1147`, ends at `idle_add(_replace)`); the load path is a **nested `_load_and_render()` inside `on_project_opened`** (`:1560`), which indexes **all** cards by chronological append (`:1636-1640`) while building widgets only for the newest 15 (`:1629-1652`); `_load_more` (`:1749-1792`) builds and stores widgets at `:1768` **without the lock**; `clear_project` (`:1521-1532`) is the only bulk prune.
- **Read `ui/views/feed_tab.py` (798 lines):** `_cards_by_id` (`:41`); the card container is a `Gtk.Box` with **`set_spacing(8)`** (`:86`) — spacing is inter-child, so removing *N* children shortens the content by `Σheight + 8N` (round-2 BUG #2); `append_card` (`:203-218`); `remove_card` (`:220-240`) clears CSS state, unparents, deletes the entry; `prepend_card` (`:242-258`) uses `insert_child_after(child, None)`; `replace_card` (`:260-288`); `show_empty_state` (`:185-201`); `get_card_container()` (`:181`); the proximity arithmetic at `:401-407` is documented as a **pre-layout, stale-upper** check.
- **Read `ui/views/feed_card.py` (898 lines):** `_render_body` dispatch (`:105-137`); `_render_file_event_body` (`:307-345`) and `_render_task_body` (`:348-385`) expose no `_text_label` by design (comment `:337-339`); `RENDERED_BODY_LIMIT = 2000` (`:147`); `build_feed_card(card_data, *, on_review, on_accept, on_reject, on_copy)` (`:515-522`); seam read `:565` / `:568`; `update_card_in_place(card_widget, card_data) -> bool` (`:852-899`), whose docstring at `:871-873` says the seam is "set by build_feed_card **for text bodies**" — false after §2.3.
- **Read `ui/handlers/activity_handler.py`:** ticker `timeout_add(250, _status_tick)` (`:670`); `_update_feedbar` (`:676-706`); `_streaming_label` (`:708-724`); `_live_update` signature gate (`:806-820`) — the 4-tuple is (state, phase, hop, elapsed bucket) and does **not** include token count.
- **Read `ui/views/feedbar.py`:** `set_status_text` → `set_markup` (`:67-69`); `set_progress_fraction` (`:71-74`); the only other writer of `_status_label` is the constructor (`:49-52`).
- **Read `models/feed_card.py`:** `seq_num: int | None` (`:108`), serialized (`:207`), parsed (`:245`). Load path back-fills missing `seq_num` (`feed_handler.py:1600-1612`), so **`seq_num` is the reliable ordering key**, not list position.
- **Read `scripts/crab_perf_probe.py`:** CLI contract is `--pid` (**required**), `--duration`, `--window`, `--budget`, `--feed-json PATH`; exit 0/1/2/3. The new probe must mirror it.
- **Read `tests/test_feed_handler.py`:** `MockGLib.idle_add` executes callbacks **synchronously** (`:30-34`); `MockFeedTab` (`:59-130`) is a plain class with `append_card`/`prepend_card`/`remove_card`/`show_empty_state`/`replace_card`/… and holds `_vadjustment` as an attribute but defines **no** `is_near_bottom` / `is_above_viewport` / `get_vadjustment`; `set_feed_tab(` appears 13× with additional inline doubles. The `python3` first on `PATH` is the Hermes venv 3.11 **without PyGObject**; `/usr/bin/python3` (3.12.3) has `gi` — all headless GTK test commands must name it explicitly.
- **Verified GTK4 APIs live under Xvfb** (GTK 4.14 / PyGObject): `Gtk.Widget.get_height` ✔, `compute_bounds(target) -> (bool, Graphene.Rect)` ✔, `unset_state_flags` ✔, `insert_child_after` ✔, `ScrolledWindow.get_vadjustment` ✔.
- **Measured evidence (three separate windows — do not conflate):** a card widget costs **56 KB** (300 retained = +16.4 MB; releasing all returns **0 MB**). A 60-minute in-app trace: **+4.55 MB/min** (1,151 → 1,424 MB) with **199 cards appended** and 0.4 MB of new feed data. A ~7-hour instance: 897 → 2,177 MB ≈ **3.05 MB/min**. Widget mass at that card rate: 199 × 56 KB = 10.9 MB/h = **0.18 MB/min ≈ 4%** of the 60-minute slope.
- **Architecture owner / patterns:** widget maps are owned by `feed_handler` + `feed_tab`; reuse the paged backlog (`PAGE_SIZE`), the Phase-4 seam, and the CSS-state clearing in `FeedTab.remove_card`.

---

## 1. Overview

**Problem — two defects, both proportional to UI activity.**

1. **Widget ratchet.** Every card ever rendered holds a `Gtk.Widget` in both
   `feed_handler._card_widgets` and `feed_tab._cards_by_id`. Nothing evicts cards that
   scroll out of the page, and GTK/glibc never return freed memory (measured: 0 MB
   returned). At 56 KB/widget, a long session ratchets monotonically — 897 MB → 2,177 MB
   over ~7 h.
2. **Per-item churn.** `update_card` rebuilds the whole card for every body type with no
   seam (file-event and task cards — deliberate today), and the 250 ms ticker writes
   markup up to twice a second for the whole streaming state.

**Solution.** Bound the widget maps at **every** widget-append path (§2.1), push evicted
cards back onto the backlog so nothing becomes unreachable (§2.1), extend the seam (§2.3),
de-duplicate ticker markup (§2.4), and ship a committed probe (§2.5). The allocator
experiment (§5 step 6) is the lever for the churn component; §6 states the gate honestly
rather than claiming the widget bound alone clears the measured slope.

**Scope**

| In | Out |
|---|---|
| Bounded live-widget window across all four append paths | Chat transcript bubbles (separate unit; UIRESP2 §9) |
| Backlog-based re-render for evicted live cards | The WebKit render-surface swap (separate proposal) |
| In-place seam for file-event and task card bodies | `feed_store` persistence/compaction changes |
| Ticker markup de-duplication + 1 s elapsed bucket | Any `agent/` runtime or LLM path |
| Committed memory probe; corrected ordering invariant | `_cards` data-size reduction |

---

## 2. Changes by File

### 2.1 `ui/handlers/feed_handler.py`

**Module constants** (read at call time so tests can monkeypatch):

```python
MAX_LIVE_CARD_WIDGETS = 120   # bound on retained card widgets
KEEP_NEWEST_CARDS = 40        # newest K by seq_num are never evicted
```

**Prerequisite — restore the ordering invariant (F1).** Today the load path appends
chronologically (`:1636-1640`) while `add_card` inserts at index 0 (`:784`), so
`_project_cards[proj]` is oldest-first after a project open and newest-first for live-only
feeds. `get_cards_for_project` (`:1504-1508`) documents "newest first" and is therefore
already wrong after any open. Fix at the load site:

```python
                # Index ALL cards (including backlog) so _project_cards is complete.
                # Order by seq_num, newest-first — do NOT infer provenance from set
                # membership. `prev` can hold ids from two different sources:
                #   (1) live arrivals during the parse window  → NEWER than the snapshot
                #   (2) ids the feed pruned at compaction      → OLDER than the snapshot
                # (feed_store.py:55 `FEED_WINDOW_DEFAULT`, pruned oldest-first at
                # :673-678; `_project_cards` is never pruned, so those ids persist here).
                # Concatenating leftovers in front promotes (2) to "newest" and makes
                # Accept All act on a card no longer on disk — the same hazard as
                # acting on a stale card. seq_num is the only correct key, and it is
                # the same key eviction uses (round-6 BUG #2, round-7 BUG #1).
                # Dedupe is implicit via dict.fromkeys; ids no longer in `_cards` drop.
                new_ids = [c.card_id for c in cards if c.card_id]
                prev = self._project_cards.get(project_name, [])
                for card in cards:
                    self._cards[card.card_id] = card
                candidates = [cid for cid in dict.fromkeys(prev + new_ids)
                              if cid in self._cards]
                self._project_cards[project_name] = sorted(
                    candidates,
                    key=lambda cid: self._cards[cid].seq_num or 0,
                    reverse=True,
                )
```

(`cards` is chronological oldest→newest, documented at `:1616-1622`; `seq_num` is assigned
per project and back-filled on load at `:1608-1610`.) The **order matters to callers**:
`get_cards_for_project` is documented "newest first" and drives the batch bar count and
Accept All, both of which `break` at the first non-actionable card (`:2064-2074`,
`:2033-2049`) — a card placed last is invisible to both until the project is reopened.

Pruning also means an id can reference a card that no longer exists on disk: the `cid in
self._cards` filter drops ids this process never loaded, and a card pruned from disk but
still in `_cards` keeps its correct (older) position at the tail by seq_num.

**New method — eviction, wired into the two append paths + a guarded third (F2, F7, F8).**

```python
    def _evict_surplus_card_widgets(self, exclude: frozenset[str] = frozenset()) -> None:
        """Release card widgets for the oldest cards beyond the live window.

        Card DATA is never dropped: the evicted FeedCardData is pushed back onto
        _backlog (newest-first), so Load More re-renders it (F4). If the backlog
        was fully drained, the Load More widget is rebuilt so the pushed cards
        are reachable without reopening the project (round-3 BUG #2).

        Victims are chosen by seq_num — NOT list position — and across ALL
        projects, because _card_widgets is one flat dict (feed_handler.py:73)
        while widget creation is keyed on the CARD's project, which need not be
        the active one (round-3 BUG #5).

        `exclude` are the ids the caller just rendered (Load More passes its
        page): without it, a Load More click re-evicts the page it just built
        and the button becomes a permanent no-op (round-3 BUG #1).

        Threading: dict mutation under self._lock (class contract at :83);
        FeedTab calls are main-thread only and are never made while holding it.
        """
        if self._feed_tab is None:
            return
        with self._lock:
            if len(self._card_widgets) <= MAX_LIVE_CARD_WIDGETS:
                return
            candidates = {
                cid for ids in self._project_cards.values() for cid in ids
            } | set(self._card_widgets)
            live = [c for c in candidates
                    if c in self._card_widgets and c in self._cards and c not in exclude]
            if len(live) <= KEEP_NEWEST_CARDS:
                return
            live.sort(key=lambda cid: self._cards[cid].seq_num or 0)  # oldest first
            victims = live[: len(live) - KEEP_NEWEST_CARDS]
            target = len(self._card_widgets) - MAX_LIVE_CARD_WIDGETS

        was_near_bottom = self._feed_tab.is_near_bottom()
        vadj = self._feed_tab.get_vadjustment()
        spacing = self._card_container_spacing()
        removed_height = 0
        released = 0
        for card_id in victims:
            if released >= target:
                break
            with self._lock:
                widget = self._card_widgets.get(card_id)
                data = self._cards.get(card_id)
            if widget is None:
                continue
            # Never destroy a widget that is on screen or below the viewport (F10).
            if not self._feed_tab.is_above_viewport(widget):
                break
            height = widget.get_height() or 0
            with self._lock:
                if self._card_widgets.pop(card_id, None) is None:
                    continue
                if data is not None:
                    # Newest-first backlog (pop(0)) → Load More re-renders it. Under
                    # the lock: _load_and_render rebinds _backlog on a background
                    # thread (:1626-1627) (round-2 BUG #3).
                    self._backlog.insert(0, data)
            self._feed_tab.remove_card(card_id)     # clears state, unparents, drops map entry
            # Gtk.Box spacing (feed_tab.py:86) applies BETWEEN children, so each
            # removed child shortens the content by height + spacing (round-2 BUG #2).
            removed_height += height + spacing
            released += 1

        if released:
            # Load More must reflect the cards eviction just pushed back: the label
            # bakes `remaining` in at build time (:1736) and is otherwise only
            # recomputed inside _load_more (:1771, :1786-1788). Before this change
            # _backlog only ever shrank, so eviction is the first thing that can
            # make the widget under-report (round-4 BUG #4).
            # The remove_card call (early-returns on an unknown id) is for the
            # rebuild, NOT for duplicate prevention — the duplicate is created on
            # the load path, which eviction never runs on (round-5 BUG #1; see the
            # load-path bullet below).
            self._feed_tab.remove_card("__load_more__")
            self._load_more_widget = None
            if self._backlog:
                self._load_more_widget = self._build_load_more_widget(len(self._backlog))
                self._feed_tab.prepend_card(self._load_more_widget, card_id="__load_more__")
            if was_near_bottom:
                self._feed_tab.schedule_scroll_to_bottom()      # keep the bottom pinned
            elif vadj is not None and removed_height:
                vadj.set_value(max(0.0, vadj.get_value() - removed_height))
```

**Load-path sentinel cleanup (round-5 BUG #1).** The duplicate sentinel is minted on the
**load** path, not by eviction, so it must be fixed there: `_append_and_schedule_scroll`
prepends a new `__load_more__` widget (`:1672-1674`) without removing the old one, while
`on_project_opened` merely nulls the attribute (`self._load_more_widget = None`, `:1558`) and
never unparents the widget. The orphan is invisible to `clear_project` (it is not in
`_project_cards`) and to `FeedTab.remove_card` (which removes only the widget named by
`_cards_by_id["__load_more__"]`, `feed_tab.py:220-240`) — so after a same-project reopen, or a
switch to a project with a backlog, **two** Load More bars stay on screen for the session
whenever the widget count is below the cap and eviction never fires.

Required edit, in `_append_and_schedule_scroll` — **unconditionally**, hoisted out of the
`if` (round-6 BUG #3): the `if load_more_widget is not None:` guard skips the case the
paragraph above is about — switching from a project **with** a backlog to one **without**
(≤ `PAGE_SIZE` cards). There the new load builds no sentinel, so the previous project's bar
stays parented for the session showing *its* count, over a button that early-returns because
`_backlog` is empty (`:1751-1752`):

```python
                self._feed_tab.remove_card("__load_more__")   # drop any stale sentinel
                if load_more_widget is not None:
                    self._feed_tab.prepend_card(load_more_widget, card_id="__load_more__")
                else:
                    self._load_more_widget = None             # no sentinel for this project
```

`_card_container_spacing()` is a 3-line private helper:

```python
    def _card_container_spacing(self) -> int:
        """Gtk.Box spacing between cards, for scroll compensation. 0 if unknown."""
        try:
            return self._feed_tab.get_card_container().get_spacing()
        except (AttributeError, TypeError):
            return 0
```

(`get_card_container()` exists at `feed_tab.py:181`; the guard keeps the mock-free
path safe — see §2.6, which adds the accessor to the doubles so the spacing term is
actually exercised.)

**Call sites.** After the existing append work in each idle callback:

| Path | Anchor | Edit |
|---|---|---|
| `add_card` | `:814-817` (`_append`) | `self._evict_surplus_card_widgets()` after `_schedule_smart_scroll()` |
| `add_cards_batch` | `:946-952` (`_append_all`) | same, after the single `_schedule_smart_scroll()` |
| `_load_and_render` (project open) | `:1631-1658` | **`self._feed_tab.remove_card(card_id)` immediately before each `append_card`** in the render loop, then `self._evict_surplus_card_widgets()` after the appends. See below — this path was missed in rounds 1-6 (round-7 BUG #2). |
| `_load_more` | `:1773-1792` (`_render`) | **As the FINAL statement of `_render`**, after the Load More re-add/clear block — not after the page-prepend loop. `_render` removes the old sentinel, prepends the page, then rebuilds the sentinel from `remaining` captured at `:1771` (i.e. *before* any eviction push). If eviction ran mid-`_render` it would rebuild the sentinel from the post-push backlog, and the tail would then build a **second** one from the stale `remaining` and repoint `_cards_by_id` at it — two parented bars and an under-reporting label, failing two §6 criteria (round-6 BUG #4). Call: `self._evict_surplus_card_widgets(exclude=frozenset(ids_just_loaded))` — **the exclusion is mandatory**: the page just prepended is the oldest content in the feed, i.e. exactly the victim set, so without it every click would build 15 widgets, evict them and push them back, forever (round-3 BUG #1). `ids_just_loaded` is the set of `card_id`s built in this `_load_more` call. |

**Why the project-open path needs its own removal (round-7 BUG #2).** `_append_and_schedule_scroll`
appends a widget per `recent` card (`:1683-1695`) and never removes a pre-existing child.
`FeedTab.append_card` only *overwrites* `_cards_by_id[card_id]` (`feed_tab.py:211-218`) after
appending the new widget — so on a **same-project reopen** (which fires `on_project_opened`
with no close callback, and reuses the same `FeedTab`/container/`_cards_by_id`) the previous
widget stays parented while the map points at the new one. The old widget then belongs to no
map at all: `_card_widgets`, `_cards_by_id`, `remove_card`, `replace_card`, `clear_project`
and `show_empty_state` can none of them reach it, and eviction can never reclaim it. The user
sees the newest `PAGE_SIZE` cards twice and the orphans bleed into the next project, which is
a permanent widget leak of exactly the class this spec exists to bound. The `__load_more__`
sentinel in the same function gets this treatment already, so the omission is asymmetric.

`_load_more`'s widget store at `:1768` also moves under `self._lock` (F8) — it is the one
existing writer that violates the `:83` contract. **Also lock the other `_backlog` writers**
(round-2 BUG #3), which the eviction now shares: the slice-and-reassign in `_load_more`
(`:1755-1756`) and the two clears (`:1557`, `:1708`) all run unlocked today while
`_load_and_render` rebinds the list on a background thread (`:1626-1627`).

**The loader must merge, not rebind — survivors first (round-4 BUG #3, round-5 BUG #2).**
Because the loader *replaces* (`self._backlog = list(reversed(backlog))`) rather than appends,
the lock serializes the two operations without merging them: a card pushed by eviction during
the loader's read-and-parse window (hundreds of milliseconds on a 2,000-card feed) is discarded
by the rebind, and its widget has already been unparented — so the card is neither rendered nor
drainable through Load More until the project is reopened. That is the "unreachable card"
failure §2 exists to remove. Required form:

```python
new_backlog = list(reversed(backlog))          # newest-first; every entry older than PAGE_SIZE
seen = {c.card_id for c in new_backlog}
with self._lock:
    pushed = [c for c in self._backlog if c.card_id not in seen]   # eviction's inserts
    self._backlog = pushed + new_backlog
```

**Order matters:** the survivors go **first**. They are the cards eviction released, i.e. cards
that held a live widget — the newest, not-yet-backlogged ones — which is exactly why the
eviction path itself uses `insert(0, …)`. `new_backlog` holds only cards older than the
snapshot's newest `PAGE_SIZE` (`cards[:-PAGE_SIZE]`, `:1619`). Putting survivors last would
delay an evicted card's return by one click per page and then re-render it in the wrong
chronological slot — contradicting the newest-first contract the merge claims to preserve.
The dedupe still prevents duplicates.

**Narrow the loader's lock region (round-3 BUG #8).** `_load_and_render` currently holds
`self._lock` across the entire widget-build loop (`:1631-1652`), so the new eviction's
main-thread lock acquisitions can block behind up to `PAGE_SIZE` GTK widget constructions
on the background loader thread. Move the `build_feed_card(...)` calls **outside** the lock;
hold it only for the dict writes.

**One rule for `_card_widgets`, stated once (round-7 BUG #3).** `_card_widgets` is
lock-protected, like every shared dict (`:82-84`), so **every** write to it stays *inside*
the narrow lock — that is exactly what F8 requires of `_load_more` (`:1768`), and the loader
keeps its write inside the lock too. What leaves the lock is only the expensive
`build_feed_card(...)` construction, never the map assignment. Do not "move the widget map
writes outside the lock" as an earlier draft's phrasing suggested: the eviction pass computes
`len(self._card_widgets)` and its victim set under the same lock, and leaving the loader's
write unlocked would let that gate run against a dict being mutated.

**Evicted cards must re-render from authoritative data (round-4 BUG #1).**
`_load_more` builds each widget from the object it popped out of `_backlog`
(`for card in page: build_feed_card(card, …)`, `:1760-1767`). Make `self._cards` the single
render source: `data = self._cards.get(card.card_id, card)` and build from `data`
(`:1760-1767`). `update_card` writes `self._cards[card_id] = card_data` at `:1030` **before**
the guard, and every update path passes a new instance (`replace(card, …)` —
`review_handler.py:135`, `agent_runtime_handler.py:1660→:1701`), so resolving through the map
is sufficient on its own: the backlog entry may go stale but is never rendered from again.

*(An earlier draft also rewrote the matching `_backlog` entry inside the guard. That is
redundant — the map is read at render time — so it is deliberately **not** required; do not
add the extra mutation. Round-5 BUG #3.)*

**Evicted-card guard** in `update_card`, immediately after the persistence block
(`:1045-1065`), **reusing the `old_widget` already bound at `:1032`** (F11):

```python
        if old_widget is None:
            # Evicted (§2.1). Data was updated and persisted above; the widget is
            # rebuilt from data if the card is rendered again. Rebuilding here
            # would re-append an old card at the bottom of the feed.
            return
```

This makes the `old_widget is None` branch of `_rebuild_and_replace_card` unreachable —
both remaining callers (`:1087`, `:1093`) pass a non-None widget. The `else: append_card`
branch inside `_replace` may be deleted with the function's docstring updated.

**Debug instrument** (`_logger` at `:1025`/`:1060`; `os` imported at `:12`), after the new
widget is stored at `:1126-1127`:

```python
        if os.environ.get("CRABCAKES_DEBUG"):
            _logger.info("feed card rebuilt (no seam): %s", card_id)
```

### 2.2 `ui/views/feed_tab.py` — geometry helpers (F10)

```python
    def get_vadjustment(self):
        """The feed ScrolledWindow's vadjustment, or None before first map."""
        return self._feed_scroll.get_vadjustment() if self._feed_scroll else None

    def is_near_bottom(self, slack: int = 80) -> bool:
        """True when the viewport is within `slack` px of the feed bottom."""
        vadj = self.get_vadjustment()
        if vadj is None:
            return True                       # nothing rendered: eviction is safe
        return (vadj.get_upper() - vadj.get_page_size() - vadj.get_value()) < slack

    def is_above_viewport(self, widget) -> bool:
        """True when `widget` lies entirely above the visible region.

        FAIL-SAFE. A widget that has never been allocated reports
        `compute_bounds -> (True, rect)` with a ZERO rect (verified on GTK 4.14
        under Xvfb: an unrealized/unmapped Gtk.Label in a Gtk.Box inside a
        Gtk.ScrolledWindow gives ok=True, origin.y=0.0, size.height=0.0). A naive
        `origin.y + height <= value` test therefore returns True — "above the
        viewport" — for every unmeasurable widget and would DESTROY cards that
        are merely not laid out yet (e.g. while the Feed sub-tab is unmapped).
        So a non-positive extent means "unknown", never "above".
        """
        vadj = self.get_vadjustment()
        if vadj is None or self._card_container is None:
            return False
        try:
            ok, rect = widget.compute_bounds(self._card_container)
        except (AttributeError, TypeError):
            return False                  # mock widgets have no compute_bounds
        if not ok or rect.size.height <= 0:
            return False                  # geometry unavailable → never evict
        return (rect.origin.y + rect.size.height) <= vadj.get_value()
```

The `rect.size.height <= 0` guard is load-bearing, not defensive padding: without it the
change removes live widgets whenever layout has not run. The eviction loop relies on the same
condition — a zero-height victim contributes no height to `removed_height`, only the spacing
term, so it must not be released at all (round-6 BUG #1).

### 2.3 `ui/views/feed_card.py` — make the seam total (F11-doc)

After the `_set_body_text(box, desc_label, …)` call in `_render_file_event_body`
(`:340-343`), add `box._text_label = desc_label`. After
`_set_body_text(box, body_label, card_data.body)` in `_render_task_body` (`:375`), add
`box._text_label = body_label`. No change to `build_feed_card` is needed — `:565` reads
`getattr(body_widget, "_text_label", None)`. **Rewrite the now-stale comments** at
`:337-339` and `:561-564`: file-event and task bodies expose the seam when a non-empty
body exists at build time; an empty-body card still falls back to rebuild.

### 2.4 `ui/views/feedbar.py` + `ui/handlers/activity_handler.py` — ticker churn

`feedbar.py`: add `self._last_status_markup: str | None = None` to `__init__` (`:28-35`)
and short-circuit identical writes in `set_status_text` (`:67-69`). `activity_handler.py`:
widen the `_live_update` elapsed bucket `0.5 → 1.0` (`:806-820`).

### 2.5 `scripts/crab_mem_probe.py` — new, committed (F9)

Mirror `scripts/crab_perf_probe.py`'s contract exactly: `--pid` **required**, `--duration`
(default 1800 s), `--budget` (default **0.5** MB/min), optional `--feed-json`; exit
0 under budget / 1 over / 2 usage / 3 process gone. Samples `VmRSS` and `VmData` from
`/proc/<pid>/status` every 10 s and reports mean slope in MB/min.

**Card arrivals must not use feed.json file length or the journal line count** —
`feed_store` compacts and prunes (`FEED_WINDOW_DEFAULT = 2000`), **and compaction truncates
the journal** (`JOURNAL_COMPACT_THRESHOLD = 500` at `utils/feed_store.py:55`, truncated at
`:700-701`), so the journal sawtooths 0..500 and would report near-zero arrivals
(round-3 BUG #3). Use the delta of the **maximum `seq_num`** across cards — monotonic,
because `_apply_overlay` drops records for absent cards rather than creating them, and
pruning removes from the oldest end (`models/feed_card.py:108`, back-filled on load at
`feed_handler.py:1608-1610`). If a second signal is wanted, sum `len(cards) + journal
lines` per sample, which is monotonic under fold-and-truncate.

### 2.6 Tests

**Test-double prerequisite (F5, round-2 BUG #1, round-3 BUG #4).** The eviction pass calls
**four** methods/accessors on the tab: `is_near_bottom()`, `is_above_viewport(widget)`,
`get_vadjustment()` **and** `get_card_container()` (via `_card_container_spacing()`).
`MockFeedTab` (`tests/test_feed_handler.py:59-131`) defines none of them — it holds
`self._vadjustment` as an attribute but exposes no accessor and has no container stub. Add
all four to `MockFeedTab` and to the inline tab doubles created at each `set_feed_tab(...)`
call site (13 of them):

- `is_near_bottom(slack=80)` → configurable bool
- `is_above_viewport(widget)` → configurable bool (default `True` for eviction cases, `False` for the fail-safe case). For the **real-GTK** fail-safe case, drive it with a genuine unallocated widget: `compute_bounds` returns `ok=True, size.height=0.0`, and the test asserts nothing is evicted (round-6 BUG #1)
- `get_vadjustment()` → `self._vadjustment` (the existing `MockVadjustment`)
- `get_card_container()` → a stub whose `get_spacing()` returns **8** (the real container's spacing, `feed_tab.py:86`), so the compensation assertion in case 5 exercises the spacing term rather than silently reading 0

`MockGLib.idle_add` dispatches synchronously (`:30-34`), so a missing accessor surfaces
immediately.

**Correction to the F5 justification (round-2 BUG #7):** the eviction early-returns on
`len(self._card_widgets) <= MAX_LIVE_CARD_WIDGETS` before touching the tab, so existing
tests that add a handful of cards are unaffected. The exposure is the **new** tests (and
any future test that exceeds the cap), not the existing suite.

`tests/test_feed_handler.py` — new cases:

1. 500 `add_card` calls with the viewport guard permissive → `len(handler._card_widgets) <= MAX_LIVE_CARD_WIDGETS`, newest `KEEP_NEWEST_CARDS` survive by `seq_num`.
2. **Bounded-but-over-cap** (round-2 BUG #6): with `is_above_viewport` returning `False`, assert nothing is evicted and the map is unchanged — the cap is a bound *when the guard permits*, not an unconditional invariant.
3. Evicted card's data is in `_cards` **and** at the front of `_backlog`; `_load_more` restores a widget for it.
4. Viewport guard stops the loop → no widget destroyed.
5. Near-bottom: `schedule_scroll_to_bottom` called; scrolled-up: `vadj.set_value` called with `value - (height + spacing)`.
6. `update_card` on an evicted card → no rebuild, no re-append, data persisted.
7. `add_cards_batch` burst → eviction runs (the batch path is covered).
8. `_load_more` **page identity** (round-3 BUG #1, round-4 BUG #2): with ≥121 live widgets, every id in the page just loaded is still in `_card_widgets` after the click, and at least one non-page card was released (non-vacuity).
9. **Drained-backlog reachability** (round-3 BUG #2): with the backlog empty and `_load_more_widget is None`, an eviction that pushes cards back also rebuilds the Load More widget.
10. Same-project reopen → `get_cards_for_project` returns each id exactly once, newest-first (round-2 BUG #4).
11. **Cross-project bound** (round-3 BUG #5): cards added while a different project is active are still eviction candidates.

**Mirror assertion needs the real FeedTab — and a non-vacuity precondition
(round-2 BUG #6, round-3 BUG #6).** `MockFeedTab` stores cards in a list and has no
`_cards_by_id`, so "membership of `FeedTab._cards_by_id` equals membership of
`_card_widgets`" lives in the **Xvfb class that already builds a real `FeedTab`** (the
scroll-test harness, `tests/test_feed_handler.py:1284-1297`). That harness never allocates
widgets, so `compute_bounds` returns a **zero rect with `ok=True`**, and the
`rect.size.height <= 0` guard makes `is_above_viewport` return `False` — so nothing is evicted
and both maps agree trivially (round-6 BUG #1: `ok=True` with a zero rect is the real
behaviour, not `ok=False`). The test must therefore **assert
non-vacuity first**: at least one id left `_card_widgets` **and** left `_cards_by_id` in the
same pass (drive the eviction with a fake widget whose `compute_bounds` succeeds).

`tests/test_feed_card.py` — file-event and task card with a non-empty body take the
in-place path (`update_card_in_place` returns True, no rebuild); empty-body card still
returns False.

Headless only, **with the interpreter that has PyGObject** (round-2 BUG #10 — the `python3`
first on `PATH` is the Hermes venv 3.11 without `gi`):

```bash
xvfb-run -a /usr/bin/python3 -m pytest tests/test_feed_handler.py tests/test_feed_card.py -q
```

### 2.7 Stale comments to rewrite (round-2 BUG #9, round-4 BUG #6)

Six call sites, not two:

| File | Anchor | Why it becomes false |
|---|---|---|
| `ui/views/feed_card.py` | `:337-339` | "file-event cards have no single body seam" — they will |
| `ui/views/feed_card.py` | `:561-564` | seam comment says "None for … file events, task cards" |
| `ui/views/feed_card.py` | `:871-873` | `update_card_in_place` docstring says the seam is set "for text bodies" (round-3 BUG #7) |
| `ui/handlers/feed_handler.py` | `:122-124` | `_backlog` comment says it is "Populated by on_project_opened() … Loaded in pages by `_load_more()`" — eviction also populates it now, and the ordering contract is newest-first |
| `ui/views/feed_tab.py` | `:5-11` | module "Public API" list omits the three geometry primitives being added |
| `ui/handlers/activity_handler.py` | `:812-813` | "0.5s granularity — labels update at most twice per second for pure time drift" — §2.4 widens the bucket to 1.0 s (at most once per second) |

Also update the section header count (six call sites, not four) — §4 and §5 counts were
corrected in round 5 (round-4 BUG #6).

**Files NOT changed:** `ui/handlers/chat_render_handler.py` (bubbles — separate unit);
`utils/gtk_containers.py`; `utils/feed_store.py`; `agent/**`.

---

## 3. Data Flow

```
add_card / add_cards_batch / _load_more
  → self._cards[card_id] = data                       (unbounded by design)
  → build_feed_card(...) → self._card_widgets[card_id] (bounded — §2.1)
  → GLib.idle_add(append callback):
       FeedTab.append_card / prepend_card → _cards_by_id[card_id]
       _schedule_smart_scroll()
       _evict_surplus_card_widgets()                   ← NEW, all three paths
            victims = oldest by seq_num, above the viewport only
            _card_widgets.pop(id)  →  _backlog.insert(0, data)  →  FeedTab.remove_card(id)
            viewport compensated (pin bottom, or shift value by removed height)

update on a card whose widget was evicted
  → data + persist updated → old_widget is None → return (no rebuild, no re-append)
```

---

## 4. File Change Summary

| File | Change | Lines (est.) | Risk |
|---|---|---|---|
| `ui/handlers/feed_handler.py` | ordering fix (seq_num-ordered), constants, `_evict_surplus_card_widgets(exclude=)`, `_card_container_spacing`, **4** eviction call sites, load-path widget de-dupe, Load More rebuild, load-path sentinel cleanup, `_backlog` lock fixes + loader merge, narrowed loader lock, evicted-card guard, debug log | +125 / −20 | MEDIUM |
| `ui/views/feed_tab.py` | `get_vadjustment`, `is_near_bottom`, `is_above_viewport`, Public-API docstring | +34 | LOW |
| `ui/views/feed_card.py` | two seam assignments + **three** comment rewrites | +8 / −6 | LOW |
| `ui/views/feedbar.py` | markup de-duplication | +5 | LOW |
| `ui/handlers/activity_handler.py` | elapsed bucket 0.5 → 1.0 | +1 / −1 | LOW |
| `scripts/crab_mem_probe.py` | new probe | +140 | LOW |
| `tests/test_feed_handler.py` | `MockFeedTab` + inline doubles gain **four accessors**; **11 cases** | +240 | LOW |
| `tests/test_feed_card.py` | 2 cases | +40 | LOW |

---

## 5. Implementation Order

1. Land `scripts/crab_mem_probe.py`; record a **baseline** slope on the running app, from an
   instance already holding more than `MAX_LIVE_CARD_WIDGETS` widgets, or over a window of
   ≥ 60 minutes (round-2 BUG #5 — below the cap nothing can change).
   PID discovery (the app is the non-stopped `python3 main.py`):
   `ps -eo pid,stat,args | awk '$3=="python3" && $4=="main.py" && $2 !~ /T/ {print $1}' | tail -1`.
2. Fix the ordering invariant (§2.1 prerequisite, `seq_num`-ordered) + regression test on `get_cards_for_project` (open the same project twice, and once after a compaction).
3. `MockFeedTab`/inline doubles gain the **four** accessors first (F5), then eviction (with the `exclude` parameter) + all **four** call sites (including the project-open path's de-dupe + eviction) + guard, with tests.
4. **Lock the `_backlog` writers** (§2.1): the eviction insert, the `_load_more` slice-and-reassign (`:1755-1756`), the `_load_more` widget store (`:1768`), the clears (`:1557`, `:1708`) — and **narrow `_load_and_render`'s hold** so widget construction happens outside the lock (round-3 BUG #8).
5. Seam extension + the six comment rewrites (§2.7) + debug log.
6. Ticker de-duplication + bucket widen.
7. Allocator experiment (no code): relaunch with
   `MALLOC_MMAP_THRESHOLD_=131072 MALLOC_TRIM_THRESHOLD_=131072 MALLOC_ARENA_MAX=2`,
   re-measure. Record which setting moved the slope; if it helps, bake it into
   `~/.local/share/applications/com.crabcakes.app.desktop`; if not, say so and stop.
8. Re-run the probe per the §6 precondition and report the invariant **and** the slope,
   with the observed widget count.

---

## 6. Acceptance Criteria

**Primary — the invariant (testable, deterministic):**

- [ ] After 500 simulated `add_card` calls **with the viewport guard permissive and `_active_project_name` set to the cards' project**, `len(handler._card_widgets) <= MAX_LIVE_CARD_WIDGETS`.
- [ ] With the guard refusing (`is_above_viewport` False), **nothing is evicted** and the map is unchanged — the cap is a bound *when the guard permits*, not an unconditional invariant (round-2 BUG #6).
- [ ] Cards added for a **non-active project** are still eviction candidates (round-3 BUG #5).
- [ ] The newest `KEEP_NEWEST_CARDS` cards (by `seq_num`) are never evicted.
- [ ] Eviction fires from `add_card` and `add_cards_batch`; from `_load_more` it fires **only** for ids outside the page just loaded.
- [ ] **Load More preserves its own page**: with the viewport guard permissive and ≥121 live widgets, after one `_load_more()` click every id in `ids_just_loaded` is still in `_card_widgets` **and** still in `FeedTab._cards_by_id`, and (non-vacuity) at least one non-page card left both maps (round-4 BUG #2 — count-based assertions are not a valid instrument here: with `N ≥ 120` pre-click widgets the pass releases `N + 15 − 120 ≥ 15`, so `len(_backlog)` is unchanged or grows and the rendered count *falls*, which is correct behaviour that the old assertions would have failed; and for `N ∈ [106, 119]` the same numbers appear with the `exclude` deleted, so they passed vacuously).
- [ ] **Load More reflects eviction**: after an eviction that pushes cards back while a Load More widget already exists, its label reports the new backlog size (round-4 BUG #4).
- [ ] At most one `__load_more__` widget is ever parented — after a project switch or same-project reopen, **below the cap so eviction never fires** (round-5 BUG #1: the guard is the load-path `remove_card`, not eviction).
- [ ] **Ordering is by `seq_num`, not by provenance** (round-6 BUG #2, round-7 BUG #1): after a project open, `get_cards_for_project(project)` is newest-first by `seq_num`; a live arrival during the parse window is at index 0. **And after a compaction that pruned ids still listed in `prev`**, the list is still newest-first — the pruned (older) ids stay at the tail and are never promoted to index 0. Regression test: load, prune, reopen.
- [ ] **No orphaned widgets on a same-project reopen** (round-7 BUG #2): `len([c for c in feed_tab._card_container if c not in (empty_widget, load_more_widget)]) == len(feed_tab._cards_by_id)` after reopening the same project twice. This cannot be checked by the map-mirror assertion — both maps agree even when orphans exist.
- [ ] Eviction also runs on the project-open path (round-7 BUG #2).
- [ ] **Unallocated widgets are never evicted** (round-6 BUG #1): with real unallocated widgets in a real `FeedTab`, the map is unchanged (drives the `rect.size.height <= 0` branch, which `ok=True` alone does not).
- [ ] **Switching to a project without a backlog clears the previous bar** (round-6 BUG #3): after switching from a backlogged project to one with ≤ `PAGE_SIZE` cards, no `__load_more__` widget remains parented.
- [ ] An evicted card that is updated and then re-rendered through Load More shows the **post-update** body and badge (round-4 BUG #1).
- [ ] An evicted card's data survives in `_cards` **and** is reachable through the Load More widget — including when the backlog had been fully drained and the widget had to be rebuilt (round-3 BUG #2).
- [ ] `update_card` on an evicted card does no widget work and does not re-append it.
- [ ] For every id in `_project_cards[active]`, membership of `FeedTab._cards_by_id` equals membership of `_card_widgets` — **excluding the `__load_more__` sentinel** (`:1674`, `:1779`, `:1788`), run in the real-FeedTab (Xvfb) class **and asserting non-vacuity first** (at least one id left both maps in the same pass).
- [ ] `get_cards_for_project` returns each id exactly once, newest-first, including after a **same-project reopen**.
- [ ] `set_status_text` with identical markup reaches `set_markup` once; with state, phase and hop held constant, `set_markup` is called at most once per second (F12 — any state/hop change may legitimately re-render inside the same second).
- [ ] Full suite green headless with `/usr/bin/python3`; paste the actual pytest output.

**Secondary — the measured slope (honest gate, F3):**

Clearing the widget ratchet can remove at most the widget-attributable mass:
199 cards/h × 56 KB = **0.18 MB/min**, ≈ **4%** of the measured 60-minute slope of
**4.55 MB/min**. The remaining churn is *not* addressed by §2.1-2.4.

**Precondition (round-2 BUG #5):** the bound only engages above `MAX_LIVE_CARD_WIDGETS`, and
at the recorded rate a 30-minute window from an empty feed accumulates ~100 widgets — the
eviction never fires and no slope change is possible. Run the measurement either from an
instance that already holds more than the cap, or over a window of **≥ 60 minutes**, and
report the observed `len(_card_widgets)` alongside the slope.

- [ ] Probe run per the precondition above: the slope is **measurably lower than the recorded baseline**, and the reduction is at least the widget-attributable mass (0.18 MB/min). Report baseline, result, window length and the peak widget count.
- [ ] The allocator experiment (§5 step 6) is run and its result recorded — pass or fail.
- [ ] **If the residual slope is still above the 0.5 MB/min budget after steps 1-7, that is the honest outcome: report "invariant fixed, churn unaddressed" and escalate to the WebKit proposal.** Do not re-scope this spec to chase the remainder, and do not declare the gate met.

---

## 7. Edge Cases

| Case | Expected behaviour |
|---|---|
| User scrolled up reading history | Above-viewport victims **are** released and the offset is compensated (`vadj.set_value(value − removed_height)`); the loop breaks at the first widget that is on screen or below the viewport, so nothing visible is destroyed (round-4 BUG #7) |
| User at the bottom | Bottom stays pinned (`schedule_scroll_to_bottom()`), no jump |
| Content above the viewport removed while scrolled up | `vadj.set_value(value − removed_height)` compensates |
| Very short cards in a tall window | `is_above_viewport` is geometric, so the "youngest victim on screen" case cannot occur (F10) |
| Mock widgets (no `compute_bounds`) | `is_above_viewport` returns False → no eviction; tests drive the path via the mock's own return value |
| **Unallocated real widget** (never realized/mapped, e.g. Feed sub-tab hidden) | `compute_bounds` returns `ok=True` with a **zero** rect; the `rect.size.height <= 0` guard makes this "unknown" → no eviction (round-6 BUG #1 — the naive test would destroy every card here) |
| Card mid-click / PRELIGHT | `FeedTab.remove_card` clears state recursively before unparenting (existing, `:232-239`) |
| `__load_more__` sentinel | Never in `_project_cards` ids → never a victim; excluded from the mirror assertion (F6) |
| Card deleted after eviction | `remove_card` early-returns when the id is unknown (`feed_tab.py:229-230`) |
| Evicted card later updated | Data + persistence only; no rebuild, no re-append |
| Feed shorter than `KEEP_NEWEST_CARDS` | No eviction (early return) |
| `_feed_scroll` not yet created | `is_near_bottom` True, `is_above_viewport` False → no eviction |
| Re-eviction of a restored card | Load More pops it from `_backlog`; a later eviction pushes it again — no duplicates accumulate |
| Guard refuses (scrolled up / unmeasurable widget) | Nothing is evicted; the map legitimately stays above the cap until the guard permits — it is a bound, not an invariant (round-2 BUG #6) |
| Load More click while above the cap | The page just loaded is excluded from the victims, so the click makes progress; eviction may still remove older cards (round-3 BUG #1) |
| Eviction while the backlog is empty and no Load More button exists | The widget is rebuilt and prepended so the pushed cards are reachable (round-3 BUG #2) |
| Cards arriving for a project that is not active | Still candidates: the victim set is the **union across projects**, not the active project's list (round-3 BUG #5) |
| Project open running while eviction fires | The loader's lock is narrowed to the dict writes, so the main thread can't block behind widget construction (round-3 BUG #8) |
| Same-project reopen | `_project_cards[proj]` is deduped (`dict.fromkeys`) so `get_cards_for_project` returns each id once (round-2 BUG #4) |
| Live arrival during the load's parse window | Ordered by `seq_num`, so it lands at index 0 and the batch bar / Accept All see it (round-6 BUG #2) |
| Feed compacted, pruned ids still in `prev` | Those ids sort to the **tail** by `seq_num` and are never promoted to "newest" — a pruned card must not become the first entry Accept All commits (round-7 BUG #1) |
| Same-project reopen | Each re-appended card is `remove_card`-ed first, so the previous widget is unparented instead of orphaned; `_project_cards[proj]` is ordered by `seq_num` (round-7 BUG #2) |
| Feed sub-tab hidden / layout never ran | `compute_bounds` yields `ok=True` with a zero rect → treated as unmeasurable, nothing evicted (round-6 BUG #1) |
| Switch from a backlogged project to one with ≤ `PAGE_SIZE` cards | The load path removes any sentinel unconditionally, so the previous project's bar does not survive (round-6 BUG #3) |
| Removed widgets sat in a container with spacing | Compensation adds `Gtk.Box.get_spacing()` per removal (`feed_tab.py:86`, spacing 8) (round-2 BUG #2) |
| `_backlog` rebound by the load thread mid-eviction | The insert runs under `self._lock`, and the loader **merges** its rebuilt list with any entry pushed in the meantime instead of replacing it (`:1626-1627`) — a plain rebind would silently drop the evicted card (round-2 BUG #3, round-4 BUG #3) |
| Project switch / close | Already handled: `on_project_closed` (`:1703`) → `clear_project` (`:1521`) pops `_card_widgets` for that project and clears `_backlog`. Regression test only |

---

## 8. ARCHITECTURE.md Updates Required

- Document the bounded live-widget window (`MAX_LIVE_CARD_WIDGETS` / `KEEP_NEWEST_CARDS`)
  and the invariant: **card data is unbounded; card widgets are bounded**.
- Document that `_project_cards[project]` is newest-first at every insertion point.
- Document `FeedTab.is_above_viewport` / `is_near_bottom` / `get_vadjustment` as the
  geometry primitives, and that eviction is fail-safe when geometry is unavailable —
  including the trap: GTK 4.14 returns `compute_bounds -> (True, zero rect)` for a widget
  that has never been allocated, so "unknown" must be `ok is False` **or** a non-positive
  extent (round-6 BUG #1).
- Note that GTK never returns memory to the OS, which is why the bound exists.

---

## 9. Out of Scope (explicit)

Chat transcript bubbles, the WebKit render-surface swap, `_cards` data-size reduction,
allocator changes in code, and any `agent/` change.

**Verified non-defects from the round-1 audit (recorded so they are not re-litigated):**
the evicted-card guard does make the `old_widget is None` branch unreachable and cannot
lose data (persistence precedes it); `box._text_label` on the file-event/task boxes does
satisfy every reachable branch of `update_card_in_place` (those boxes never set
`_body_is_placeholder`, and `_set_body_text` always writes `_body_full_text` and installs
the reveal button); `_active_project_name` keys the same string as `card_data.project_name`;
and the `feed_tab.py` / `feedbar.py` / `activity_handler.py` / `feed_card.py` anchors cited
above were confirmed accurate.
