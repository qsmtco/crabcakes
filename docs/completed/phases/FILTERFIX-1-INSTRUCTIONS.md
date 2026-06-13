# FILTERFIX 1 — Fix filter dropdown buttons (Agent/Type popovers don't open)

## Problem

`ui/views/activity_drawer.py:137,142` — Both filter buttons (`_agent_filter_btn` and `_type_filter_btn`) connect the wrong signal:

```python
self._agent_filter_btn = Gtk.MenuButton(label="Agent: all")
self._agent_filter_btn.connect("activate", self._on_agent_filter_clicked)  # WRONG — never fires
```

`Gtk.MenuButton` in GTK4 inherits from `Gtk.Widget` directly (NOT from `Gtk.Button`). It has NO custom signals — no "activate", no "clicked", no "toggled". The "activate" signal never fires in normal click flow. The popover-opening handler is never called, so the dropdown popovers never appear.

## Working Pattern in the Codebase

`ui/views/chat_input_toolbar.py:212-238` shows the correct GTK4 pattern for a MenuButton that opens a popover:

```python
btn = Gtk.MenuButton()
btn.set_icon_name("document-save-symbolic")
# ... build popover ...
popover = Gtk.PopoverMenu()
popover.set_child(vbox)
btn.set_popover(popover)   # ← This is the key — set popover on the button
return btn
```

The MenuButton opens its set popover AUTOMATICALLY on click. No signal connection needed.

## What to implement

### File: `ui/views/activity_drawer.py`

#### Step 1: Replace the broken MenuButton setup

In `_build_header` (around line 120-145), change:

```python
# OLD (broken):
self._agent_filter_btn = Gtk.MenuButton(label="Agent: all")
self._agent_filter_btn.connect("activate", self._on_agent_filter_clicked)
self._header.append(self._agent_filter_btn)

# OLD (broken):
self._type_filter_btn = Gtk.MenuButton(label="Type: all")
self._type_filter_btn.connect("activate", self._on_type_filter_clicked)
self._header.append(self._type_filter_btn)
```

To (option A — build popover eagerly, let MenuButton manage it):

```python
# NEW: build popover eagerly and set it on the MenuButton
self._agent_filter_btn = Gtk.MenuButton(label="Agent: all")
agent_popover = Gtk.Popover()
agent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
agent_popover.set_child(agent_box)
self._agent_filter_btn.set_popover(agent_popover)
self._header.append(self._agent_filter_btn)

self._type_filter_btn = Gtk.MenuButton(label="Type: all")
type_popover = Gtk.Popover()
type_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
type_popover.set_child(type_box)
self._type_filter_btn.set_popover(type_popover)
self._header.append(self._type_filter_btn)
```

Then **move the popover-building logic** from `_show_filter_popover` into a new method `_build_filter_popover_content(kind, all_values, visible_set, label_widget, new_label_fn)` that RETURNS the box to put inside the popover. The popovers are now built once at startup (with empty content) and refreshed when new agents/types appear.

**OR** (option B — keep the click-to-build approach, but use `set_popover()` instead of the signal):

```python
# Keep _on_agent_filter_clicked but call it differently
self._agent_filter_btn = Gtk.MenuButton(label="Agent: all")
# In the click handler, set the popover on first click and trigger it
```

**RECOMMENDED: Option A.** Build the popover content once, set it on the button, let GTK4 handle the show/hide on click. The button manages the popover lifecycle (autohide, etc.) for free.

#### Step 2: Refactor `_show_filter_popover` to be called from a content-refresh method

The old `_show_filter_popover` built AND showed the popover. Split this into:

- `_build_filter_popover_content(box, kind, all_values, visible_set, label_widget, new_label_fn)` — builds the checkbox list into an existing Gtk.Box (clears it first)
- `_refresh_filter_popovers()` — called from `append_event` after `_known_agents`/`_known_types` are updated, rebuilds the checkbox content of both popovers

#### Step 3: Add the call in `append_event`

After `self._known_agents.add(agent)` and `self._known_types.add(activity_type)` (around line 197-198), call `self._refresh_filter_popovers()` so new agents/types show up in the dropdowns in real-time.

### File: `tests/test_activity_drawer.py`

Add tests to `TestActivityDrawer`:

1. **Test that filter buttons are MenuButtons with popovers set** (regression guard for the signal-name fix):
```python
def test_filter_buttons_have_popovers(self, drawer):
    """FILTERFIX-1: filter buttons must be MenuButtons with popovers set, NOT rely on 'activate' signal."""
    from gi.repository import Gtk
    assert isinstance(drawer._agent_filter_btn, Gtk.MenuButton)
    assert isinstance(drawer._type_filter_btn, Gtk.MenuButton)
    # The popovers should be set on the buttons (this is what makes them open on click)
    assert drawer._agent_filter_btn.get_popover() is not None
    assert drawer._type_filter_btn.get_popover() is not None
```

2. **Test that appending an event updates the filter popover content**:
```python
def test_append_event_refreshes_filter_popovers(self, drawer):
    """FILTERFIX-1: new agents/types must appear in filter popovers."""
    # Initially popovers are empty
    drawer.append_event({
        "agent": "Coder",
        "activity_type": "tool_start",
        "type_label": "tool",
        "icon": "🔧",
    })
    # After appending, _known_agents should have "Coder"
    assert "Coder" in drawer._known_agents
    # The popover should now contain a checkbox for "Coder"
    popover = drawer._agent_filter_btn.get_popover()
    box = popover.get_child()
    # The box should have at least 2 children: "All agents" + "Coder"
    assert box.get_first_child() is not None
```

## Verification Commands

```bash
cd /home/q/projects/crabcakes
grep -n "connect.*activate.*filter\|MenuButton\|set_popover" ui/views/activity_drawer.py
python3 -m pytest tests/test_activity_drawer.py -q --tb=short
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Architecture Considerations

- The ActivityDrawer is a pure view (per ARCHITECTURE.md Section 3.8). Popover content is view-state only.
- No new modules or imports needed beyond `Gtk.Popover` (already used).
- ARCHITECTURE.md does NOT need updating — this is a bug fix in an existing view, not a public API change.

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Removed broken `connect("activate", ...)` calls; set popovers on MenuButtons — evidence: grep showing set_popover
- [ ] Edit 2: Refactored _show_filter_popover into _build_filter_popover_content + _refresh_filter_popovers — evidence: grep showing new method names
- [ ] Edit 3: Added _refresh_filter_popovers() call in append_event after _known_agents/types update — evidence: grep showing call site
- [ ] Edit 4: Added test_filter_buttons_have_popovers test — evidence: test pass
- [ ] Edit 5: Added test_append_event_refreshes_filter_popovers test — evidence: test pass
- [ ] Edit 6: Full test suite passes — evidence: pytest output
```
