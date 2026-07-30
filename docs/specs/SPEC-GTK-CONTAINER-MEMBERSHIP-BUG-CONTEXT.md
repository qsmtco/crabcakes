# Bug Context — GTK Container Membership Truncation

## Symptom
Agent chat messages get cut off mid-message. The streaming bubble stays
stuck at the last delta with raw partial text (literal backticks visible,
no markdown formatting). The final formatted bubble never replaces it.

## Root cause (confirmed by Supervisor + Debugger)
`ui/handlers/chat_render_handler.py:570`, inside `_finalize()` (called from
`end_streaming()`):

```python
if sb.bubble in sb.container:
    sb.container.remove(sb.bubble)
```

`sb.container` is a `Gtk.Box`. PyGObject does NOT wire Python's `__contains__`
operator onto GTK containers. The GTK C method `gtk_container_contains()` is
exposed only as `container.contains(widget)`. So `widget in gtk_box` raises:

    TypeError: argument of type 'Gtk.Box' is not iterable

That TypeError is raised inside `_finalize()`, which is dispatched via
`self._dispatch(_finalize)` → `GLib.idle_add(_wrap)` at line 747-755:

```python
def _dispatch(self, fn):
    """Call fn on the GTK main thread."""
    if self._GLib is not None:
        def _wrap():
            fn()
            return False
        self._GLib.idle_add(_wrap)
    else:
        fn()
```

`_wrap` has NO try/except. GLib's main loop silently swallows the exception.
The remainder of `_finalize()` is skipped: `sb.container.remove(sb.bubble)`
never runs, `build_role_bubble(...)` never runs, `sb.container.append(...)` never
runs. The streaming widget stays in the chat box; the parsed final bubble is
never appended. User sees the message cut off at the last delta.

## Affected sites (6 total)

| File:line | Pattern | Impact |
|---|---|---|
| `ui/handlers/chat_render_handler.py:570` | `if sb.bubble in sb.container:` | **Message truncation** (the user-visible symptom) |
| `ui/views/feed_tab.py:193` | `if widget in self._card_container:` | Empty-state cleanup skips mid-loop |
| `ui/views/feed_tab.py:210` | `if self._empty_widget is not None and self._empty_widget in self._card_container:` | First-card empty-widget not removed |
| `ui/views/feed_tab.py:236` | `if self._card_container and widget in self._card_container:` | **Card removal silently fails** |
| `ui/views/feed_tab.py:250` | `if self._empty_widget is not None and self._empty_widget in self._card_container:` | Lazy-load prepend skips empty clear |
| `ui/views/feed_tab.py:270` | `if old_widget not in self._card_container:` | **Card update silently skipped** |

No other call sites in `ui/`, `agent/`, or `models/` (verified by grep).

## Required fix (shape only — spec must detail this)

1. **`_is_in_container(widget, container)` helper** — sibling walk via
   `container.get_first_child()` then `child.get_next_sibling()`. Returns bool.
   Returns False if widget or container is None. Returns False if container is
   empty. Duplicated in BOTH files per ARCHITECTURE.md §8.6 (handlers never
   import from other handlers; this is a utility local to each subsystem).
2. **Replace all 6 sites** listed above with calls to the helper.
3. **Wrap `_dispatch`'s `_wrap` in try/except + `logger.exception(...)`** —
   defensive measure so future swallowed exceptions at least leave a log trail.
4. **New test file `tests/test_gtk_container_membership.py`** covering:
   - Documents the bug class: `widget in FakeGtkBox` raises TypeError
   - Unit tests the helper: present / absent / None widget / None container /
     empty container / middle child / child-after-remove / broken walk
   - Static regression checks: grep source to confirm the broken `in gtk_box`
     patterns are gone from all 6 sites

## Constraints

- NO textview/texttag work. This is a pure container-membership fix.
- NO changes to `models/streaming.py` or `ui/views/chat_bubble.py` render path.
- Helper must be duplicated (not shared) per §8.6 handler rule.
- Follow `prompts/steelFramedSpecWriter.md` for spec writing.

## Acceptance criteria (spec must enumerate testable outcomes)

- All 6 broken `in gtk_container` patterns replaced
- `_dispatch` exception logging added
- New test file passes
- No regressions in existing chat_render / feed_tab tests
- Pattern sweep grep returns zero matches for the old pattern
