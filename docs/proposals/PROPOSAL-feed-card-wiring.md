# Proposal: Wire Task Commands and Git Operations to Feed

> **Status: PARTIALLY IMPLEMENTED** — Verified in code as of 2026-05-09
> - ✅ Task commands (`task_handler.py`) now emit feed cards via `_emit_feed_card()` and `on_feed_card` callback
> - ❌ Review handler (`review_handler.py`) NOT yet wired to feed — no feed_card references found
> - ❌ Git operation cards from accept/reject actions not yet implemented

> **Status (verified 2026-06-12):** ⚠️ **PARTIALLY DONE** — 
> **status:** `PARTIAL` — sortable tag for `ls | grep STATUS` **Task commands** (`ui/handlers/task_handler.py:58-84`) are fully wired: `_emit_feed_card()` creates `FeedCardData` and fires `on_feed_card` callback. **Review handler** still has **zero** `feed_card` / `on_feed_card` references — the proposal's "❌ Review handler NOT yet wired to feed" flag remains accurate. **Git operation cards** from accept/reject actions: `feed_handler.py:153-154` wires `on_accept`/`on_reject` callbacks to feed cards (the accept/reject buttons exist in the feed UI), but these are feed-level accept/reject for feed cards, not git operation cards per se. The original proposal's "git op cards" (showing diff stats + accept/reject → git apply / git revert) are not separately implemented as a distinct card type. **Marked PARTIAL; review_handler wiring is the remaining open item.**

**Date:** 2026-05-01
**Depends on:** ARCHITECTURE.md, existing FeedHandler, TaskHandler, ReviewHandler

---

## Background

The Project Feed has five documented card sources. Three are working:

1. ✅ Persisted cards from `feed.json`
2. ✅ Agent crabcard blocks extracted from chat
3. ✅ CrabWatch file events (system cards)

Two are not wired:

4. ❌ Task command cards — backtick commands like `` `task ``
5. ❌ Git operation cards — from accept/reject actions on feed cards

---

## Source 4: Task Command Cards

### Current Behavior

`TaskHandler.cmd_task/done/start/blocked/cancel` return `CommandResult(response_card=dict)`. The card dict is rendered as a chat bubble via `_on_command_card` → `ChatRenderHandler.render_event_card()`. It never reaches `FeedHandler`.

### Proposed

Add an `on_feed_card` callback to `TaskHandler`. When a task command produces a `response_card`, also fire the callback with a `FeedCardData` constructed from the card data. Wire it in `window.py`.

### Changes

#### `ui/handlers/task_handler.py` — Add optional callback + helper

**Constructor change:**

```python
def __init__(
    self,
    on_display_card=None,
    on_display_text=None,
    GLib_module=None,
    on_feed_card=None,          # NEW: callback(FeedCardData) — add to project feed
):
    ...
    self._on_feed_card = on_feed_card
```

**New private helper:**

```python
def _emit_feed_card(self, card_dict: dict, project_name: str):
    """Convert task card dict to FeedCardData and fire feed callback."""
    if not self._on_feed_card:
        return
    from models.feed_card import FeedCardData
    feed_card = FeedCardData(
        card_type="task",
        source="agent",
        title=card_dict.get("title", "Task"),
        body=f"Status: {card_dict.get('status', 'unknown')} • Assigned: {card_dict.get('assigned_to', '?')}",
        author=card_dict.get("assigned_to", "unknown"),
        timestamp=datetime.now(timezone.utc),
        project_name=project_name,
        task_id=str(card_dict.get("id", "")),
        metadata={"action": card_dict.get("action", "updated")},
    )
    self._on_feed_card(feed_card)
```

**Call in each command that returns a `response_card`:**

Extract project name from the `Command.source_session_key`:

```python
project_name = ""
if cmd.source_session_key and cmd.source_session_key.startswith("project:"):
    project_name = cmd.source_session_key.split(":", 1)[1]
```

Add `self._emit_feed_card(card, project_name)` before each `return CommandResult(...)` in:
- `cmd_task`
- `cmd_done`
- `cmd_start`
- `cmd_blocked`
- `cmd_cancel`

#### `ui/window.py` — Wire the callback

```python
# In _build(), where TaskHandler is constructed:
self._task_handler = TaskHandler(
    on_display_card=self._on_command_card,
    on_display_text=...,
    GLib_module=GLib,
    on_feed_card=self._feed_handler.add_card,    # NEW
)
```

### Architecture Compliance

- `TaskHandler` does NOT import `FeedHandler`. It fires a callback. ✅
- `window.py` wires the callback at construction time. ✅
- `FeedCardData` is a `models/` class — handlers may import from `models/`. ✅
- No GTK in the new code — pure Python data construction + callback. ✅
- `TaskHandler` public API is extended (new optional param) but backward-compatible. ✅

---

## Source 5: Git Operation Cards (Accept/Reject)

### Current Behavior

`FeedHandler.handle_accept()` does `git_ops.stage_all()` + `git_ops.commit()`. `FeedHandler.handle_reject()` does `git_ops.checkout_paths()`. Neither generates a new feed card for the resulting git state.

### Proposed

After successful git accept or reject, create a `git_commit` card in the feed.

### Changes

#### `ui/handlers/feed_handler.py` — Add helper + calls

**New private helper:**

```python
def _add_git_card(self, original_card: FeedCardData, commit_result) -> None:
    """Create a git_commit feed card after accept/reject."""
    if not commit_result.success:
        return
    git_card = FeedCardData(
        card_type="git_commit",
        source="git",
        title=f"Accepted: {original_card.title}" if original_card.accepted else f"Rejected: {original_card.title}",
        body=commit_result.stdout.strip() if commit_result.stdout else "",
        author="PM",
        timestamp=datetime.now(timezone.utc),
        project_name=original_card.project_name,
        commit_sha=commit_result.sha,
        file_path=original_card.file_path,
    )
    self.add_card(git_card)
```

**In `handle_accept()` — after successful commit:**

```python
def _git_accept():
    ...
    if result_commit.success:
        ...
        self._GLib.idle_add(_mark)
        self._GLib.idle_add(lambda: self._add_git_card(card, result_commit))  # NEW
```

**In `handle_reject()` — after successful checkout:**

```python
def _git_reject():
    ...
    self._GLib.idle_add(lambda: self._add_git_card(card, ...))  # NEW
```

### Architecture Compliance

- All changes inside `FeedHandler` itself — no cross-handler dependency. ✅
- `FeedCardData` from `models/` — already imported. ✅
- `git_ops` from `utils/` — already imported. ✅
- GTK dispatch via `GLib.idle_add()` — standard handler pattern. ✅
- `add_card()` handles its own persistence — no new I/O paths. ✅
- No new public methods — `_add_git_card` is private. ✅

---

## Summary

| File | Change | New Dependencies |
|------|--------|-----------------|
| `ui/handlers/task_handler.py` | Add `on_feed_card` callback param + `_emit_feed_card` helper + calls in `cmd_*` methods | `models.feed_card.FeedCardData` (models/) ✅ |
| `ui/handlers/feed_handler.py` | Add `_add_git_card` helper + calls in `handle_accept`/`handle_reject` | None (already imports all needed modules) |
| `ui/window.py` | Pass `on_feed_card=self._feed_handler.add_card` to `TaskHandler` constructor | None |

**No new modules. No new files. No handler-to-handler imports.** All wiring through callbacks per ARCHITECTURE.md Section 5 rule #2: *"Handlers never import other handlers. If ChatHandler needs something from GatewayHandler, `window.py` wires it via a callback or sync function."*

**No public API changes** to existing methods — only new optional constructor parameters (backward-compatible) and new private methods.

---

*This proposal is the implementation plan for wiring task commands and git operations to the Project Feed. It must be reviewed before implementation begins.*
