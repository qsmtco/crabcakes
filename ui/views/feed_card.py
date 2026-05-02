# ui/views/feed_card.py
# Feed card widget factories — Phase 1.
# Pure view — no business logic, no state mutations. All actions via callbacks.
# Architecture: the ONLY place that constructs feed card GTK widgets.
#
# Public API:
#   build_feed_card(card_data, on_review, on_accept, on_reject, on_copy) -> Gtk.Widget
#   build_feed_reference_widget(card_data, on_click) -> Gtk.Widget
#   build_empty_feed_widget() -> Gtk.Widget

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from typing import Callable

from models.feed_card import FeedCardData, CardType
from utils.escaping import escape_for_pango


# ─────────────────────────────────────────────────────────────────────────────
# Shared header builder (feed card variant)
# ─────────────────────────────────────────────────────────────────────────────

def _make_feed_card_header(
    title: str,
    card_type: str,
    card_data: FeedCardData,
    on_copy: Callable[[str], None],
) -> tuple[Gtk.Box, Gtk.Button]:
    """
    Build a feed card header bar with title + copy button.
    Color is driven by card type CSS class on the parent.

    Returns (header_box, copy_btn) — copy_btn is pre-wired.
    """
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("feed-card-header")

    title_label = Gtk.Label()
    title_label.set_text(title)
    title_label.set_halign(Gtk.Align.START)
    title_label.set_hexpand(True)

    copy_btn = Gtk.Button()
    copy_btn.add_css_class("flat")
    copy_btn.set_tooltip_text("Copy")
    copy_btn.set_size_request(22, 22)
    copy_btn.set_opacity(0.3)
    try:
        copy_btn.set_child(Gtk.Image.new_from_file(
            "/home/q/projects/crabcakes/ui/icons/copy.svg"))
    except Exception:
        copy_btn.set_label("📋")
    copy_motion = Gtk.EventControllerMotion()
    copy_motion.connect("enter", lambda _c, _x, _y: copy_btn.set_opacity(1.0))
    copy_motion.connect("leave", lambda _c: copy_btn.set_opacity(0.3))
    copy_btn.add_controller(copy_motion)
    # Body text for copy
    body_for_copy = card_data.body or title
    copy_btn.connect("clicked", lambda _, t=body_for_copy: on_copy(t))

    header.append(title_label)
    header.append(copy_btn)
    return header, copy_btn


def _format_timestamp(ts) -> str:
    """Format a datetime as a human-readable relative string."""
    from datetime import datetime, timezone
    if ts is None:
        return "just now"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    total_seconds = delta.total_seconds()
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        mins = int(total_seconds / 60)
        return f"{mins}m ago"
    if total_seconds < 86400:
        hrs = int(total_seconds / 3600)
        return f"{hrs}h ago"
    days = int(total_seconds / 86400)
    return f"{days}d ago"


# ─────────────────────────────────────────────────────────────────────────────
# Card type body renderers
# ─────────────────────────────────────────────────────────────────────────────

def _render_body(card_data: FeedCardData) -> Gtk.Widget:
    """Render the body of a feed card based on card type."""
    ct = card_data.card_type

    if ct in ("diff", "git_commit"):
        # For Phase 1, render body as plain monospace text.
        # Actual diff rendering (hunks, syntax highlight) comes in Phase 4.
        return _render_text_body(card_data.body, mono=True)

    elif ct in ("file_created", "file_modified", "file_deleted", "dir_created", "dir_deleted"):
        return _render_file_event_body(card_data)

    elif ct == "agent_action":
        return _render_text_body(card_data.body, mono=False)

    elif ct == "task":
        return _render_task_body(card_data)

    elif ct == "system":
        return _render_text_body(card_data.body, mono=True)

    else:
        return _render_text_body(card_data.body, mono=False)


def _render_text_body(text: str, mono: bool) -> Gtk.Widget:
    """Render body text as a label (monospace or normal)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("feed-card-body")

    if not text or not text.strip():
        spacer = Gtk.Label()
        spacer.set_text(" ")
        spacer.set_size_request(-1, 8)
        box.append(spacer)
        return box

    escaped = escape_for_pango(text)
    label = Gtk.Label()
    label.set_markup(escaped)
    label.set_xalign(0)
    label.set_wrap(True)
    label.set_wrap_mode(1)  # Pango.WrapMode.WORD_CHAR
    label.set_selectable(True)
    label.set_can_focus(False)
    if mono:
        label.add_css_class("feed-body-mono")
    box.append(label)
    return box


def _render_file_event_body(card_data: FeedCardData) -> Gtk.Widget:
    """Render body for file_created/file_deleted/dir_created events."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("feed-card-body")

    # File/dir path with icon
    path = card_data.file_path or ""
    icon = "📁" if card_data.card_type == "dir_created" else "📄"
    path_label = Gtk.Label()
    path_label.set_markup(f"{icon} <b>{escape_for_pango(path)}</b>")
    path_label.set_xalign(0)
    path_label.set_wrap(False)
    path_label.set_selectable(True)
    path_label.set_can_focus(False)
    path_label.add_css_class("feed-body-path")
    box.append(path_label)

    # Body description if present
    if card_data.body and card_data.body.strip():
        desc_label = Gtk.Label()
        desc_label.set_markup(escape_for_pango(card_data.body))
        desc_label.set_xalign(0)
        desc_label.set_wrap(True)
        desc_label.set_wrap_mode(1)
        desc_label.set_selectable(True)
        desc_label.set_can_focus(False)
        desc_label.set_margin_top(4)
        desc_label.add_css_class("feed-body-desc")
        box.append(desc_label)

    return box


def _render_task_body(card_data: FeedCardData) -> Gtk.Widget:
    """Render body for task cards."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("feed-card-body")

    # Task title
    title_label = Gtk.Label()
    title_label.set_markup(f"<b>📋 {escape_for_pango(card_data.title)}</b>")
    title_label.set_xalign(0)
    title_label.set_wrap(True)
    title_label.set_wrap_mode(1)
    title_label.set_selectable(True)
    title_label.set_can_focus(False)
    box.append(title_label)

    # Body (task description or status)
    if card_data.body and card_data.body.strip():
        body_label = Gtk.Label()
        body_label.set_markup(escape_for_pango(card_data.body))
        body_label.set_xalign(0)
        body_label.set_wrap(True)
        body_label.set_wrap_mode(1)
        body_label.set_selectable(True)
        body_label.set_can_focus(False)
        body_label.set_margin_top(4)
        box.append(body_label)

    # Task ID if present
    if card_data.task_id:
        id_label = Gtk.Label()
        id_label.set_markup(f"<span foreground='#9b9bab'>ID: {escape_for_pango(card_data.task_id)}</span>")
        id_label.set_xalign(0)
        id_label.set_margin_top(2)
        box.append(id_label)

    return box


# ─────────────────────────────────────────────────────────────────────────────
# Main card factory
# ─────────────────────────────────────────────────────────────────────────────

def build_feed_card(
    card_data: FeedCardData,
    *,
    on_review: Callable[[str], None],
    on_accept: Callable[[str], None],
    on_reject: Callable[[str], None],
    on_copy: Callable[[str], None],
) -> Gtk.Widget:
    """
    Build a complete feed card widget from FeedCardData.

    Returns a Gtk.Box containing:
      - Header: colored bar with title + copy button (via css_class_for_type)
      - Body: content area with card-specific rendering
      - Footer: author • timestamp + Review/Accept/Reject buttons

    All callbacks receive (card_id: str) except on_copy which receives (text: str).
    """
    card_id = card_data.card_id or ""

    # Root card box
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    card.add_css_class("feed-card")
    card.add_css_class(FeedCardData.css_class_for_type(card_data.card_type))

    # Set accepted/rejected visual state
    if card_data.accepted is True:
        card.add_css_class("feed-card-accepted")
    elif card_data.accepted is False:
        card.add_css_class("feed-card-rejected")

    # ── Header ─────────────────────────────────────────────────────────
    header, _copy_btn = _make_feed_card_header(
        card_data.title,
        card_data.card_type,
        card_data,
        on_copy,
    )
    card.append(header)

    # ── Body ───────────────────────────────────────────────────────────
    body_widget = _render_body(card_data)
    card.append(body_widget)

    # ── Footer: author • timestamp ─────────────────────────────────────
    footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    footer.add_css_class("feed-card-footer")

    ts_str = _format_timestamp(card_data.timestamp)
    meta_text = f"{card_data.author} • {ts_str}"
    meta_label = Gtk.Label(label=meta_text)
    meta_label.set_halign(Gtk.Align.START)
    meta_label.set_hexpand(True)

    footer.append(meta_label)

    # Accepted/rejected badge
    if card_data.accepted is True:
        badge = Gtk.Label(label="ACCEPTED")
        badge.add_css_class("feed-accepted-badge")
        footer.append(badge)
    elif card_data.accepted is False:
        badge = Gtk.Label(label="REJECTED")
        badge.add_css_class("feed-rejected-badge")
        footer.append(badge)

    card.append(footer)

    # ── Action buttons ─────────────────────────────────────────────────
    actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    actions.add_css_class("feed-card-actions")
    actions.set_spacing(6)

    btn_review = Gtk.Button(label="Review")
    btn_review.add_css_class("feed-btn-review")
    btn_review.connect("clicked", lambda _, cid=card_id: on_review(cid))

    btn_accept = Gtk.Button(label="Accept")
    btn_accept.add_css_class("feed-btn-accept")
    btn_accept.connect("clicked", lambda _, cid=card_id: on_accept(cid))

    btn_reject = Gtk.Button(label="Reject")
    btn_reject.add_css_class("feed-btn-reject")
    btn_reject.connect("clicked", lambda _, cid=card_id: on_reject(cid))

    actions.append(btn_review)
    actions.append(btn_accept)
    actions.append(btn_reject)
    card.append(actions)

    return card


# ─────────────────────────────────────────────────────────────────────────────
# Feed reference widget (inline in chat bubbles)
# ─────────────────────────────────────────────────────────────────────────────

def build_feed_reference_widget(
    card_data: FeedCardData,
    *,
    on_click: Callable[[], None],
) -> Gtk.Widget:
    """
    Build a small inline widget that replaces a crabcard block in chat bubbles.

    Returns a Gtk.Box containing:
      - 📋 icon
      - Card title text
      - Clickable — on_click switches to Project Feed tab

    CSS class: .feed-reference
    """
    ref = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    ref.add_css_class("feed-reference")
    ref.set_spacing(4)

    icon = Gtk.Label(label="📋")
    icon.set_valign(Gtk.Align.CENTER)

    title = Gtk.Label()
    title.set_text(card_data.title)
    title.set_halign(Gtk.Align.START)
    title.set_valign(Gtk.Align.CENTER)
    title.add_css_class("feed-ref-title")

    ref.append(icon)
    ref.append(title)

    # Make the whole box clickable
    click = Gtk.GestureClick()
    ref.add_controller(click)
    click.connect("pressed", lambda _, n, x, y: on_click())

    return ref


# ─────────────────────────────────────────────────────────────────────────────
# Empty state widget
# ─────────────────────────────────────────────────────────────────────────────

def build_empty_feed_widget() -> Gtk.Widget:
    """
    Build the empty state widget shown when the feed has no cards.

    Returns a Gtk.Box with centered text: "No activity yet"
    CSS class: .feed-empty
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("feed-empty")
    box.set_valign(Gtk.Align.CENTER)
    box.set_halign(Gtk.Align.CENTER)

    icon = Gtk.Label(label="📭")
    icon.set_valign(Gtk.Align.CENTER)
    icon.set_halign(Gtk.Align.CENTER)
    icon.set_margin_bottom(12)
    icon.set_size_request(48, 48)

    msg = Gtk.Label()
    msg.set_text("No activity yet")
    msg.set_valign(Gtk.Align.CENTER)
    msg.set_halign(Gtk.Align.CENTER)
    msg.add_css_class("feed-empty-text")

    hint = Gtk.Label()
    hint.set_text("Agent actions will appear here")
    hint.set_valign(Gtk.Align.CENTER)
    hint.set_halign(Gtk.Align.CENTER)
    hint.set_margin_top(4)
    hint.add_css_class("feed-empty-hint")

    box.append(icon)
    box.append(msg)
    box.append(hint)

    return box