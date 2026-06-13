# SPEC: Wire `ReviewHandler` to emit git_commit feed cards

**Date:** 2026-06-12
**Author:** Qaster (after adversarial review of QTR's report)
**Status:** Ready for implementation
**Implements:** `docs/proposals/PROPOSAL-feed-card-wiring.md` (PARTIAL → DONE)
**Closes:** Roadmap Tier 1.2 (revised: 11-line fix, not 52-line merge)
**Target branch:** main

## Why

`PROPOSAL-feed-card-wiring.md` was marked PARTIAL because the original `❌ Review handler NOT yet wired to feed` flag was still accurate. `task_handler.py:51-84` has the pattern (`on_feed_card` constructor parameter + `_emit_feed_card()` helper); `review_handler.py` does not.

A Captain request at 2026-06-12 20:58 proposed a full handler-unification (merge `feed_handler.handle_accept/handle_reject` with `review_handler.accept_changes/reject_changes`). After an adversarial review, that scope was rejected in favor of the smaller 11-line fix because:

- The unification was 5× the scope (52 lines production + new test file) for a minor UX consistency gap
- The 7 entry points grew organically from different ownership domains (review state, command parsing, diff display, feed display) — they are not "the same code in two places"
- A synthesized `metadata["trigger"]` field to distinguish trigger sources is a code smell
- The user-visible inconsistency is one missing card per `/accept` invocation — a low-priority cosmetic gap

The full unification can become a separate Tier 3 item later if desired. This SPEC implements the small fix.

## What

Add `on_feed_card` wiring to `ReviewHandler` so that `accept_changes()` and `reject_changes()` emit a `git_commit` feed card on success, matching the user-visible behavior of clicking Accept/Reject on a feed card.

## Discovery

- **`ui/handlers/task_handler.py:51`** — `on_feed_card=None` constructor parameter; `task_handler.py:56` stores `self._on_feed_card = on_feed_card`; `task_handler.py:58-69` is the `_emit_feed_card` helper that builds `FeedCardData` and fires the callback. **This is the pattern to mirror.**
- **`ui/handlers/review_handler.py:51`** — current `__init__` signature (no `on_feed_card`).
- **`ui/handlers/review_handler.py:225`** — `def accept_changes(self, project_name: str, message: str, session_key: str | None = None)`. After successful commit, fires `_on_display_text` (text only) — needs to also fire `_on_feed_card`.
- **`ui/handlers/review_handler.py:264`** — `def reject_changes(self, project_name: str, reason: str, session_key: str | None = None)`. After successful checkout, fires `_on_display_text` (text only) — needs to also fire `_on_feed_card`.
- **`ui/window.py:450`** — `self._review_handler = ReviewHandler(...)` constructor call. Needs `on_feed_card=self._feed_handler.add_card` added.
- **`ui/handlers/feed_handler.py:102-192`** — `add_card()` auto-assigns `card_id = str(uuid.uuid4())` (line 116). Caller never supplies `card_id`; just passes a complete `FeedCardData` and `add_card()` handles the rest.
- **`models/feed_card.py:FeedCardData`** — required fields: `card_type`, `source`, `title`, `body`, `author`, `timestamp`, `project_name`. Optional: `file_path`, `commit_sha`, `metadata`, etc. `card_id` is set by `add_card()`.

## Design

### ReviewHandler changes

1. **Add `on_feed_card` constructor parameter** (mirroring `task_handler.py:51`):
   ```python
   on_feed_card=None,  # callback(FeedCardData) — add git_commit card to project feed
   ```

2. **Store the callback** (in `__init__`, mirroring `task_handler.py:56`):
   ```python
   self._on_feed_card = on_feed_card
   ```

3. **Add `_emit_feed_card()` helper** (mirroring `task_handler.py:58-69`):
   ```python
   def _emit_feed_card(self, card_dict: dict) -> None:
       """Convert git_commit card dict to FeedCardData and fire feed callback.

       Only fires if _on_feed_card is set and source is a project tab.
       Mirrors task_handler._emit_feed_card pattern.
       """
       if not self._on_feed_card:
           return
       feed_card = FeedCardData(
           card_type="git_commit",
           source="git",
           title=card_dict.get("title", ""),
           body=card_dict.get("body", ""),
           author="PM",
           timestamp=datetime.now(timezone.utc),
           project_name=card_dict.get("project_name", ""),
           commit_sha=card_dict.get("commit_sha"),
       )
       self._on_feed_card(feed_card)
   ```

4. **Call from `accept_changes()`** — inside `_update_state` lambda, after the existing `self._on_display_text` call, add:
   ```python
   self._emit_feed_card({
       "title": f"Accepted: {message}",
       "body": commit_result.stdout.strip() if commit_result.stdout else "",
       "project_name": project_name,
       "commit_sha": getattr(commit_result, "sha", None),
   })
   ```

5. **Call from `reject_changes()`** — inside `_update_state` lambda, after the existing `self._on_display_text` call, add:
   ```python
   self._emit_feed_card({
       "title": f"Rejected: {reason}",
       "body": result.stdout.strip() if result.stdout else "",
       "project_name": project_name,
       "commit_sha": sha,
   })
   ```

### window.py change

6. **Wire the callback** in `ui/window.py:450`:
   ```python
   self._review_handler = ReviewHandler(
       GLib=GLib,
       main_content=self._main_content,
       project_handler=self._project_handler,
       on_review_started=self._on_review_started,
       on_review_ended=self._on_review_ended,
       on_display_card=self._on_command_card,
       on_display_text=self._on_command_text,
       on_feed_card=self._feed_handler.add_card,  # NEW
   )
   ```

### Imports

7. **Add imports to `review_handler.py`** (top of file, near other model imports):
   ```python
   from datetime import datetime, timezone
   from models.feed_card import FeedCardData
   ```

## Per-entry-point behavior

After this fix, the user-visible behavior becomes:

| Trigger | User sees (in chat) | User sees (in feed) |
|---|---|---|
| `/accept` slash command | `"✅ Changes accepted and committed as: ..."` | `git_commit` card with `"Accepted: ..."` title |
| `/reject` slash command | `"❌ Changes rejected — files reverted to ..."` | `git_commit` card with `"Rejected: ..."` title |
| Review bar Accept button | same as `/accept` | same as `/accept` |
| Review bar Reject button | same as `/reject` | same as `/reject` |
| Click Accept on a feed card | (unchanged) | (unchanged — already emits `git_commit` via `feed_handler._add_git_card`) |
| Click Reject on a feed card | (unchanged) | (unchanged) |

The "missing card for `/accept`" inconsistency is closed. The two code paths (review_handler and feed_handler) remain independent — that's a deliberate trade-off; the full unification is deferred.

## Tests

Add `tests/test_review_handler_feed_card.py` with at least 3 test cases:

### 1. `test_accept_changes_emits_git_commit_card`

```python
def test_accept_changes_emits_git_commit_card(self, fake_glib, mock_git_ops):
    """accept_changes fires on_feed_card with a git_commit FeedCardData on success."""
    from ui.handlers.review_handler import ReviewHandler
    captured = []
    handler = ReviewHandler(
        GLib=fake_glib,
        main_content=MagicMock(),
        project_handler=MagicMock(),
        on_review_started=MagicMock(),
        on_review_ended=MagicMock(),
        on_display_card=MagicMock(),
        on_display_text=MagicMock(),
        on_feed_card=lambda card: captured.append(card),
    )
    # ... set up state with checkpoint_sha, mock git_ops to return success
    handler.accept_changes("myproject", "approved")
    # ... wait for thread to complete
    assert len(captured) == 1
    assert captured[0].card_type == "git_commit"
    assert captured[0].source == "git"
    assert "Accepted" in captured[0].title
```

### 2. `test_reject_changes_emits_git_commit_card`

Same shape as #1 but for `reject_changes`. Asserts `"Rejected"` in title.

### 3. `test_no_card_when_git_op_fails`

Mock `git_ops` to return failure. Assert `captured == []` (no card) and `_on_display_text` was called with an error message.

### 4. (Optional) `test_no_card_when_no_active_session`

Call `accept_changes` on a project with no `ReviewState`. Assert `captured == []` and no crash.

## Risks

1. **Cross-handler wiring** — `window.py:450` adds `on_feed_card=self._feed_handler.add_card`. If `self._feed_handler` doesn't exist yet at that point in `_build`, this will fail. **Verify:** `self._feed_handler` is created earlier in `_build` (confirmed at `window.py:436` for `task_handler`).
2. **Threading** — `accept_changes`/`reject_changes` already run in `threading.Thread`. The `_emit_feed_card` call inside `_update_state` is already in a `GLib.idle_add` callback, so it's already on the main thread. **No threading changes needed.**
3. **`on_feed_card=None` (production-safe)** — if `on_feed_card` is not wired (e.g. in tests), the helper returns early. The existing review_handler tests don't need updates.

## Files modified

| File | Change | Lines |
|---|---|---|
| `ui/handlers/review_handler.py` | Add `on_feed_card` ctor param, store callback, add `_emit_feed_card` helper, call from `accept_changes` and `reject_changes` | +13 / -0 |
| `ui/window.py` | Add `on_feed_card=self._feed_handler.add_card` to ReviewHandler constructor | +1 / -0 |
| `tests/test_review_handler_feed_card.py` | New test file with 3-4 tests | +120 / -0 (new file) |

**Total production code: 14 lines. New test file: ~120 lines.**

## What this SPEC does NOT do (explicitly out of scope)

- ❌ Does NOT merge `feed_handler.handle_accept/handle_reject` into `review_handler`
- ❌ Does NOT introduce a shared `_do_git_action` helper
- ❌ Does NOT change `feed_handler.add_card()` behavior
- ❌ Does NOT add a `metadata["trigger"]` field
- ❌ Does NOT add the 8-test full-integration suite
- ❌ Does NOT refactor the 7 entry points to funnel through one function
- ❌ Does NOT touch `task_handler`, `chat_handler`, or `agent_runtime_handler`

If you want any of those, file a follow-up proposal. They are not in scope here.

## Verification plan (after implementation)

1. `pytest tests/test_review_handler_feed_card.py -v` — all new tests pass
2. `pytest tests/test_review_handler.py tests/test_feed_handler.py -v` — existing tests still pass
3. `pytest tests/test_chat_handler.py tests/test_missing_message_fix.py -v` — affected code paths still pass
4. Manual smoke test (optional): launch app, run `/accept` in a project tab, confirm a `git_commit` card appears in the feed

## Open question for the implementer (QTR)

The synthesized `FeedCardData` in `_emit_feed_card` does not include `metadata["trigger"]` (the original plan's "trigger" field). Is that intentional? **Yes** — the trigger field was part of the rejected merge plan, not this fix. After this fix, all cards from `review_handler` are equivalent (no need to distinguish trigger source). If you want a `metadata` field for any reason, add it; if not, omit it.
