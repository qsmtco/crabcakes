# ui/views/activity_drawer.py
# ActivityDrawer — collapsible activity event panel below the chat.
# Implements: docs/specs/SPEC-activity-drawer.md
#
# Pure view — no business logic, no gateway calls, no state beyond its
# widget tree. Receives activity events via append_event() and lifecycle
# events via on_agent_start()/on_agent_end(). Data comes as a flat dict
# (see models/activity.py:ActivityBubble.to_drawer_row()).
#
# Architecture: per docs/ARCHITECTURE.md §3.7b (view), §13 principles 2/3/4.

from __future__ import annotations

from typing import Callable

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import GLib, Gtk, Pango


# ── Module-level helpers (mirrored from models/activity.py) ──────
# These are duplicated here to avoid a circular import between
# ui/views/ and models/ when only the type label / duration formatter
# is needed. Both modules use the SAME logic — keep in sync.

def _type_label(activity_type: str) -> str:
    """See models/activity.py._type_label for full docstring."""
    if activity_type == "command_output":
        return "exec"
    if activity_type == "lifecycle_start":
        return "lifecycle"
    if activity_type == "plan":
        return "plan"
    if activity_type == "approval_request":
        return "approval"
    if activity_type == "patch":
        return "patch"
    return activity_type


def _format_duration(ms: int) -> str:
    """See models/activity.py._format_duration for full docstring."""
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    minutes, secs = divmod(ms // 1000, 60)
    return f"{minutes}m {secs}s"


class ActivityDrawer(Gtk.Box):
    """Collapsible activity event panel below the chat.

    Pure view — no business logic, no gateway calls, no state mutations
    beyond its own widget tree. Receives activity events via append_event()
    and lifecycle events via on_agent_start()/on_agent_end().

    Architecture (per ARCHITECTURE.md §3.7b / §13):
    - Lives in ui/views/ — no imports from gateway/, agent/
    - Receives data via callbacks set by ActivityHandler / window.py._build()
    - No GLib.idle_add() — append_event() must be called on the GTK main thread
      (ActivityHandler already does GLib dispatch before firing callbacks)
    """

    MAX_ROWS = 100  # global cap; oldest 25 trimmed at once when exceeded
    TRIM_BATCH = 25  # rows to remove per trim
    DEFAULT_VISIBLE_PX = 200  # max_content_height for the inner ScrolledWindow
    OUTPUT_LINE_CAP = 10  # lines of stdout/stderr shown in click-to-expand

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("activity-drawer")

        # ── State ─────────────────────────────────────────────────────
        # Filter state — independent AND filters
        # _visible_agents: set of agent names that pass the filter; empty set = all
        # _visible_types: set of activity types that pass the filter; empty set = all
        # Default = both empty (no filtering, all rows pass)
        self._visible_agents: set[str] = set()
        self._visible_types: set[str] = set()

        # Per-agent counter state — the (agent, type) key of the last appended row,
        # so the next matching event mutates that row's count in place.
        self._last_row_key: tuple[str, str] | None = None
        self._last_row_widget: Gtk.Box | None = None  # backing widget for in-place mutation

        # Per-agent counter dict — {agent_name: {"count": int, "duration_ms": int, "last_command": str}}
        # Popped on that agent's lifecycle_end so its next start begins a fresh counter.
        self._agent_counters: dict[str, dict] = {}

        # Known agent list — collected from events as they arrive. Used to populate
        # the agent filter dropdown. NOTE: not currently cleared on clear_events() —
        # the filter and known-sets persist across clears (a separate bug, see
        # FILTERFIX-1 audit post-mortem).
        self._known_agents: set[str] = set()

        # Known type list — same idea, for the type filter dropdown.
        self._known_types: set[str] = set()

        # Lifecycle separator tracking — when a separator was last inserted, what agent
        # and which side (start, end). Used to prevent double-separator inserts.
        self._last_separator_agent: tuple[str, str] | None = None  # (agent, "start"|"end")

        # Row counter for the header label (total events ever appended, not visible)
        self._total_count: int = 0

        # Currently expanded row widgets (click-to-expand state) — we re-collapse
        # on clear_events() to free the revealers.
        self._expanded_rows: set[Gtk.Revealer] = set()

        # ── Build widgets ────────────────────────────────────────────
        self._build_header()
        self._build_list()

        # Start collapsed (header-only visible) per proposal §10.1
        self._expanded = False
        self._apply_expanded_state()

    # ── Construction helpers ──────────────────────────────────────

    def _build_header(self) -> None:
        """Build the drawer header bar: toggle, count label, clear button, filter menus."""
        self._header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._header.add_css_class("activity-drawer-header")

        # Toggle button (▼/▶)
        self._toggle_btn = Gtk.Button(label="▶ Activity")
        self._toggle_btn.connect("clicked", self._on_toggle_clicked)
        self._header.append(self._toggle_btn)

        # Count label — shows "0 events" initially
        self._count_label = Gtk.Label(label="0 events")
        self._count_label.set_xalign(0.0)
        self._count_label.set_hexpand(True)
        self._header.append(self._count_label)

        # Agent filter dropdown — menu button. Label is "Agent: all" by default.
        # FILTERFIX-1: Gtk.MenuButton in GTK4 has no custom signals (no "activate",
        # "clicked", or "toggled"). The popover-opening is handled AUTOMATICALLY
        # by Gtk.MenuButton once a popover is set via set_popover(). The previous
        # implementation connected "activate" which never fires, so the dropdowns
        # were dead. Build the popover eagerly, store the inner box for refresh.
        self._agent_filter_btn = Gtk.MenuButton(label="Agent: all")
        self._agent_popover = Gtk.Popover()
        self._agent_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._agent_popover_box.set_margin_top(4)
        self._agent_popover_box.set_margin_bottom(4)
        self._agent_popover_box.set_margin_start(4)
        self._agent_popover_box.set_margin_end(4)
        self._agent_popover.set_child(self._agent_popover_box)
        self._agent_filter_btn.set_popover(self._agent_popover)
        self._header.append(self._agent_filter_btn)

        # Type filter dropdown — same pattern as agent filter.
        self._type_filter_btn = Gtk.MenuButton(label="Type: all")
        self._type_popover = Gtk.Popover()
        self._type_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._type_popover_box.set_margin_top(4)
        self._type_popover_box.set_margin_bottom(4)
        self._type_popover_box.set_margin_start(4)
        self._type_popover_box.set_margin_end(4)
        self._type_popover.set_child(self._type_popover_box)
        self._type_filter_btn.set_popover(self._type_popover)
        self._header.append(self._type_filter_btn)

        # Clear button
        self._clear_btn = Gtk.Button(label="Clear")
        self._clear_btn.connect("clicked", self._on_clear_clicked)
        self._header.append(self._clear_btn)

        self.append(self._header)

    def _build_list(self) -> None:
        """Build the scrollable row list inside a Gtk.ScrolledWindow."""
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # set_max_content_height caps the scrolled area; GTK 4.10+ required.
        # This project ships GTK 4.14 (verified by Gtk.get_major_version() at runtime).
        self._scrolled.set_max_content_height(self.DEFAULT_VISIBLE_PX)
        self._scrolled.set_propagate_natural_height(True)
        # Hide the scrolled window when the drawer is collapsed
        self._scrolled.set_visible(False)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._scrolled.set_child(self._list)

        self.append(self._scrolled)

    # ── Public API (called by ActivityHandler via callbacks) ─────

    def append_event(self, row: dict) -> None:
        """Append an activity event row from a to_drawer_row() dict.

        Per-agent counter-collapse: if the last row's (agent, activity_type) matches
        the new event's (agent, activity_type), mutate the existing row in place
        (count++, duration sum, last_command refresh). Otherwise append a new row.

        If the row does not pass the current filter, do nothing (do not append,
        do not count).

        Must be called on the GTK main thread.

        Args:
            row: dict from ActivityBubble.to_drawer_row()
        """
        agent = row.get("agent", "Agent")
        activity_type = row.get("activity_type", "")
        key = (agent, activity_type)

        # Filter check — drop the row if filtered out
        if not self._passes_filter(agent, activity_type):
            self._total_count += 1  # still counted in total, just not visible
            self._update_count_label()
            return

        # Track known agents/types for the filter dropdowns.
        # FILTERFIX-1 audit: capture whether the sets actually changed BEFORE
        # the .add() calls — once added, we can't tell if it was new. Refreshing
        # on every event is O(N widgets) per event; a 50-event session from the
        # same agent would destroy and recreate ~18 widgets per event for no
        # observable change.
        new_agent = agent not in self._known_agents
        new_type = activity_type not in self._known_types
        self._known_agents.add(agent)
        self._known_types.add(activity_type)
        # FILTERFIX-1: refresh the popover content so newly-seen agents/types
        # appear in the dropdowns in real-time. Only do the (expensive) rebuild
        # if the set actually changed.
        if new_agent or new_type:
            self._refresh_filter_popovers()

        # Counter-collapse check
        if self._last_row_key == key and self._last_row_widget is not None:
            self._mutate_counter_row(self._last_row_widget, row)
            self._total_count += 1
            self._update_count_label()
            return

        # Append new row
        row_widget = self._build_row_widget(row, count=1)
        self._list.append(row_widget)
        self._last_row_key = key
        self._last_row_widget = row_widget

        # BUGFIX-3: Track this event in the agent's running counter so that
        # on_agent_end() can produce an accurate summary even when no counter-
        # collapse happens (mixed event types from the same agent). The
        # counter-collapse path (_mutate_counter_row) only initializes on
        # the first collapse, so agents with no collapsed sequences would
        # otherwise show "ended" instead of the real count and total duration.
        # Use count=0 (not 1): this is the actual event count, not an anchor.
        # _mutate_counter_row's setdefault is a no-op once this entry exists,
        # so its count += 1 correctly adds collapsed events on top.
        agent_counter = self._agent_counters.setdefault(
            agent, {"count": 0, "total_duration_ms": 0, "last_command": ""}
        )
        agent_counter["count"] += 1
        agent_counter["total_duration_ms"] += row.get("duration_ms", 0)
        if row.get("command"):
            agent_counter["last_command"] = row["command"]

        self._total_count += 1
        self._update_count_label()
        self._trim_old_rows_if_needed()
        self._auto_scroll_to_bottom()

    def on_agent_start(self, session_key: str, agent_name: str) -> None:
        """Called when an agent turn starts (lifecycle phase=start).

        Inserts a subtle separator row. Breaks the per-agent counter chain for
        that agent (next event from that agent starts a fresh counter).

        Must be called on the GTK main thread.
        """
        # Prevent double-separator for the same agent
        if self._last_separator_agent == (agent_name, "start"):
            return

        sep = self._build_separator_widget(
            f"\u2500\u2500 {agent_name} started \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
        )
        self._list.append(sep)

        # Break this agent's counter chain
        self._last_row_key = None
        self._last_row_widget = None
        self._last_separator_agent = (agent_name, "start")

    def on_agent_end(self, session_key: str, agent_name: str) -> None:
        """Called when an agent turn ends (lifecycle phase=end).

        Inserts a summary separator row with per-agent stats.
        Pops this agent's counter state from _agent_counters.

        Must be called on the GTK main thread.
        """
        if self._last_separator_agent == (agent_name, "end"):
            return

        counter = self._agent_counters.pop(agent_name, None)
        if counter is not None and counter.get("count", 0) > 0:
            summary = (
                f"\u2500\u2500 {agent_name}: {counter['count']} events in "
                f"{_format_duration(int(counter.get('total_duration_ms', 0)))} \u2500\u2500\u2500\u2500"
            )
        else:
            summary = f"\u2500\u2500 {agent_name}: ended \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"

        sep = self._build_separator_widget(summary)
        self._list.append(sep)

        # Break this agent's counter chain
        self._last_row_key = None
        self._last_row_widget = None
        self._last_separator_agent = (agent_name, "end")

    def clear_events(self) -> None:
        """Remove all rows and reset all state.

        Called by the Clear button or by the window on lifecycle reset.
        """
        # Remove all rows
        while True:
            row = self._list.get_row_at_index(0)
            if row is None:
                break
            self._list.remove(row)

        # Reset state
        self._last_row_key = None
        self._last_row_widget = None
        self._agent_counters.clear()
        self._last_separator_agent = None
        self._total_count = 0
        self._expanded_rows.clear()
        self._update_count_label()
        self._auto_scroll_to_bottom()

    def toggle(self) -> None:
        """Programmatically toggle expanded/collapsed state.

        Public so the window or a keyboard shortcut can trigger it.
        """
        self._expanded = not self._expanded
        self._apply_expanded_state()

    # ── Row construction ────────────────────────────────────────

    def _build_row_widget(self, row: dict, count: int) -> Gtk.Box:
        """Build a single row widget from a to_drawer_row() dict.

        Returns a Gtk.Box (one row of the Gtk.ListBox). The widget stores
        metadata on itself for in-place mutation.

        The row format is:
        [timestamp] [agent] [icon] [type_label] [×count] [file_path/command] [exit_badge] [duration]

        For exec/command_output rows, the box also contains a Gtk.Revealer that
        expands on click to show the last OUTPUT_LINE_CAP lines of the output.
        """
        # Outer row box
        row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        row_box.add_css_class("activity-drawer-row")
        # Add type-specific CSS class for color/styling
        activity_type = row.get("activity_type", "")
        row_box.add_css_class(f"activity-drawer-row-{activity_type}")

        # Single-line summary
        summary = self._format_summary(row, count=count)
        label = Gtk.Label(label=summary)
        label.set_xalign(0.0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        row_box.append(label)

        # Click-to-expand for exec/command_output
        if activity_type in ("command_output", "tool_end", "tool_error") and row.get("output"):
            revealer_tup = self._build_revealer(row, activity_type)
            if revealer_tup is not None:
                revealer, toggle = revealer_tup
                row_box.append(revealer)
                # Make the summary clickable — clicking the row toggles the revealer
                gesture = Gtk.GestureClick.new()
                gesture.connect("pressed", lambda g, n, x, y, t=toggle: t())
                row_box.add_controller(gesture)

        # Store metadata on the row box for in-place mutation
        # We attach via setattr (Gtk.Box allows arbitrary attribute assignment in Python).
        row_box._row_meta = {  # type: ignore[attr-defined]
            "agent": row.get("agent", "Agent"),
            "activity_type": activity_type,
            "summary_label": label,
        }
        return row_box

    def _format_summary(self, row: dict, count: int) -> str:
        """Format a single-line summary for the row.

        Format: HH:MM  [Agent]  icon  type  [×N]  detail  [exit]  duration

        Where:
        - HH:MM is the row's timestamp
        - [Agent] is the agent display name in brackets
        - icon is the emoji prefix
        - type is the type label
        - ×N is the count (only if N > 1)
        - detail is file_path for file events, command for exec, raw_text for others
        - exit is \u2713 0 / \u2717 N for command_output with exit_code
        - duration is the formatted duration
        """
        parts: list[str] = []
        ts = row.get("timestamp", "")
        if ts:
            parts.append(ts)
        agent = row.get("agent", "Agent")
        parts.append(f"[{agent}]")
        icon = row.get("icon", "")
        if icon:
            parts.append(icon)
        type_label = row.get("type_label", "") or _type_label(row.get("activity_type", ""))
        parts.append(type_label)
        if count > 1:
            parts.append(f"\u00d7{count}")

        # Detail: file_path > command > raw_text
        file_path = row.get("file_path", "")
        command = row.get("command", "")
        if file_path:
            parts.append(file_path)
        elif command:
            parts.append(command)
        else:
            raw = row.get("raw_text", "")
            if raw:
                parts.append(raw)

        # Exit badge
        exit_code = row.get("exit_code")
        if exit_code is not None:
            if exit_code == 0:
                parts.append("\u2713 0")
            else:
                parts.append(f"\u2717 {exit_code}")

        # Duration
        duration = row.get("duration", "")
        if duration and duration != "0ms":
            parts.append(duration)

        return "  ".join(parts)

    def _build_revealer(self, row: dict, activity_type: str) -> tuple[Gtk.Revealer, Callable[[], None]] | None:
        """Build a Gtk.Revealer for click-to-expand output display.

        Returns (revealer, toggle_callable) or None if no output to show.
        The toggle_callable is bound to the row's click gesture so clicking
        the summary toggles expansion.

        The revealer contains a multi-line label with the last OUTPUT_LINE_CAP
        lines of the row's `output` field. If output is empty, returns None.
        """
        output = row.get("output", "")
        if not output:
            return None

        # Tail the output to the last N lines
        all_lines = output.splitlines()
        if not all_lines:
            return None
        lines = all_lines[-self.OUTPUT_LINE_CAP:]
        if len(all_lines) > self.OUTPUT_LINE_CAP:
            truncated_count = len(all_lines) - self.OUTPUT_LINE_CAP
            text = f"... {truncated_count} lines earlier ...\n" + "\n".join(lines)
        else:
            text = "\n".join(lines)

        output_label = Gtk.Label(label=text)
        output_label.set_xalign(0.0)
        output_label.set_yalign(0.0)
        output_label.set_wrap(True)
        output_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        output_label.set_selectable(True)
        output_label.add_css_class("activity-drawer-output")

        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_reveal_child(False)
        revealer.set_child(output_label)

        def toggle() -> None:
            new_state = not revealer.get_reveal_child()
            revealer.set_reveal_child(new_state)
            if new_state:
                self._expanded_rows.add(revealer)
            else:
                self._expanded_rows.discard(revealer)

        return revealer, toggle

    def _mutate_counter_row(self, row_widget: Gtk.Box, new_row: dict) -> None:
        """Update an existing row widget in place when counter-collapse fires.

        Updates the summary label text, the agent's running totals in
        _agent_counters, and the stored metadata.
        """
        meta = getattr(row_widget, "_row_meta", None)
        if meta is None:
            return

        agent = meta.get("agent", new_row.get("agent", "Agent"))
        # Update the agent's running counter
        counter = self._agent_counters.setdefault(
            agent, {"count": 1, "total_duration_ms": 0, "last_command": ""}
        )
        counter["count"] += 1
        counter["total_duration_ms"] += new_row.get("duration_ms", 0)
        counter["last_command"] = new_row.get("command", "")

        # Update the summary label
        label = meta.get("summary_label")
        if label is not None:
            label.set_text(self._format_summary(new_row, count=counter["count"]))

    def _build_separator_widget(self, text: str) -> Gtk.Box:
        """Build a subtle separator row (lifecycle marker).

        Returns a Gtk.Box with a single centered label. No interaction.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("activity-drawer-separator")

        label = Gtk.Label(label=text)
        label.set_xalign(0.5)
        label.set_hexpand(True)
        box.append(label)

        return box

    def _trim_old_rows_if_needed(self) -> None:
        """Trim the oldest TRIM_BATCH rows when total exceeds MAX_ROWS.

        Skips separator rows when counting toward the cap (separators are
        not events). Uses Gtk.ListBox.get_row_at_index to iterate.
        """
        to_remove: list[Gtk.ListBoxRow] = []
        non_sep_count = 0
        idx = 0
        while True:
            lb_row = self._list.get_row_at_index(idx)
            if lb_row is None:
                break
            child = lb_row.get_child()
            if child is None or "activity-drawer-separator" in child.get_css_classes():
                idx += 1
                continue
            non_sep_count += 1
            if non_sep_count > self.MAX_ROWS:
                to_remove.append(lb_row)
                if len(to_remove) >= self.TRIM_BATCH:
                    break
            idx += 1
        # BUGFIX-2: Track removed rows in a set for the post-trim cleanup check.
        removed_set = set(to_remove)
        for r in to_remove:
            self._list.remove(r)
        # BUGFIX-2: If the last counter-collapsed row was among those trimmed,
        # _last_row_widget now points at a detached (unparented) Gtk.Box. The
        # next counter-collapse call (_mutate_counter_row) would then mutate
        # a dead widget and potentially crash PyGObject. Clear the references
        # in that case. Use get_parent() to walk from the child Box up to its
        # ListBoxRow wrapper, then check membership in the removed set.
        if self._last_row_widget is not None:
            parent_row = self._last_row_widget.get_parent()
            if parent_row in removed_set:
                self._last_row_key = None
                self._last_row_widget = None

    def _auto_scroll_to_bottom(self) -> None:
        """Scroll the drawer's internal scrolled window to the bottom."""
        vadj = self._scrolled.get_vadjustment()
        if vadj is not None:
            upper = vadj.get_upper()
            page_size = vadj.get_page_size()
            vadj.set_value(upper - page_size)

    def _update_count_label(self) -> None:
        """Update the count label to show 'N events' or 'N visible / M total' if filtering."""
        if not self._visible_agents and not self._visible_types:
            # No filter active
            self._count_label.set_text(f"{self._total_count} events")
        else:
            visible = self._count_visible_rows()
            self._count_label.set_text(f"{visible} visible / {self._total_count} total")

    def _count_visible_rows(self) -> int:
        """Count rows that pass the current filter (for the visible/total label)."""
        count = 0
        idx = 0
        while True:
            lb_row = self._list.get_row_at_index(idx)
            if lb_row is None:
                break
            child = lb_row.get_child()
            if child is not None:
                meta = getattr(child, "_row_meta", None)
                if meta is not None:
                    if self._passes_filter(meta["agent"], meta["activity_type"]):
                        count += 1
            idx += 1
        return count

    def _passes_filter(self, agent: str, activity_type: str) -> bool:
        """True if this (agent, activity_type) passes the current filter state.

        AND semantics: both an empty set and a containing set pass.
        - If _visible_agents is empty, all agents pass.
        - If _visible_agents is non-empty, agent must be in it.
        - Same for _visible_types.

        BUGFIX-9: Coerce non-string inputs to strings before membership tests.
        `agent in self._visible_agents` would raise TypeError if agent is e.g.
        None or an int (set membership requires hashable types and the `in`
        operator on a set[str] with a non-string key raises TypeError in
        modern Python). Defensive coercion keeps the filter robust against
        malformed payloads.
        """
        if not isinstance(agent, str):
            agent = str(agent) if agent is not None else "Agent"
        if not isinstance(activity_type, str):
            activity_type = str(activity_type) if activity_type is not None else ""
        if self._visible_agents and agent not in self._visible_agents:
            return False
        if self._visible_types and activity_type not in self._visible_types:
            return False
        return True

    # ── Event handlers ──────────────────────────────────────────

    def _on_toggle_clicked(self, _btn) -> None:
        self.toggle()

    def _apply_expanded_state(self) -> None:
        """Apply the current _expanded flag to the toggle label and scrolled visibility."""
        if self._expanded:
            self._toggle_btn.set_label("\u25bc Activity")
            self._scrolled.set_visible(True)
        else:
            self._toggle_btn.set_label("\u25b6 Activity")
            self._scrolled.set_visible(False)

    def _on_clear_clicked(self, _btn) -> None:
        self.clear_events()

    def _build_filter_popover_content(
        self,
        box: Gtk.Box,
        kind: str,
        all_values: set[str],
        visible_set: set[str],
        label_widget: Gtk.Widget,
        new_label_fn: Callable[[str], str],
    ) -> None:
        """Clear `box` and rebuild the checkbox list for a filter popover.

        The popovers are created once in _build_header and the inner boxes
        are stored. This function is called from _refresh_filter_popovers to
        update the content in place when new agents/types are seen.
        """
        # Clear existing children
        while True:
            child = box.get_first_child()
            if child is None:
                break
            box.remove(child)

        # "All" toggle — clears the filter set
        all_check = Gtk.CheckButton(label=f"All {kind}s")
        all_check.set_active(not visible_set)
        all_check.connect("toggled", lambda btn, k=kind: self._on_filter_all_toggled(btn, k))
        box.append(all_check)

        # Per-value checkboxes
        for value in sorted(all_values):
            cb = Gtk.CheckButton(label=value)
            cb.set_active(value in visible_set)
            cb.connect("toggled", self._on_filter_value_toggled, kind, value, label_widget, new_label_fn)
            box.append(cb)

    def _refresh_filter_popovers(self) -> None:
        """Rebuild the checkbox content of both filter popovers.

        Called from append_event after _known_agents / _known_types are
        updated, so newly-seen agents/types appear in the dropdowns.
        """
        self._build_filter_popover_content(
            self._agent_popover_box, "agent", self._known_agents,
            self._visible_agents, self._agent_filter_btn,
            new_label_fn=lambda n: f"Agent: {n}" if n else "Agent: all",
        )
        self._build_filter_popover_content(
            self._type_popover_box, "type", self._known_types,
            self._visible_types, self._type_filter_btn,
            new_label_fn=lambda n: f"Type: {n}" if n else "Type: all",
        )

    def _on_filter_all_toggled(self, btn: Gtk.CheckButton, kind: str) -> None:
        """When 'All' is toggled, clear the filter set for that kind."""
        if btn.get_active():
            if kind == "agent":
                self._visible_agents.clear()
            else:
                self._visible_types.clear()
            self._refresh_row_visibility()

    def _on_filter_value_toggled(
        self,
        btn: Gtk.CheckButton,
        kind: str,
        value: str,
        label_widget: Gtk.Widget,
        new_label_fn: Callable[[str], str],
    ) -> None:
        """When a value checkbox is toggled, update the filter set and re-evaluate."""
        if kind == "agent":
            target = self._visible_agents
        else:
            target = self._visible_types

        if btn.get_active():
            target.add(value)
        else:
            target.discard(value)

        # Update the label
        if target:
            label_widget.set_label(new_label_fn(", ".join(sorted(target))))
        else:
            label_widget.set_label(new_label_fn(""))

        self._refresh_row_visibility()

    def _refresh_row_visibility(self) -> None:
        """Walk all rows, set visibility based on _passes_filter, update count label."""
        idx = 0
        while True:
            lb_row = self._list.get_row_at_index(idx)
            if lb_row is None:
                break
            child = lb_row.get_child()
            if child is not None:
                meta = getattr(child, "_row_meta", None)
                if meta is not None:
                    visible = self._passes_filter(meta["agent"], meta["activity_type"])
                    lb_row.set_visible(visible)
            idx += 1
        self._update_count_label()
