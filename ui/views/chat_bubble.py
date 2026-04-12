# ui/views/chat_bubble.py
# Chat bubble widget factories — Phase 1 (inline) + Phase 2 (block-level).
#
# Security: No secrets, no file I/O, no network calls.
# Pure GTK widget construction; no GTK calls until after app activation.
#
# Public API:
#   build_role_bubble(role, text) -> Gtk.Widget
#       Creates a styled bubble widget for the given role + formatted text.
#       role: "You" (user, right-aligned) or "Agent" (agent, left-aligned)
#       text: Raw message text (may contain markdown, code blocks, quotes, etc.)
#             The bubble internally: 1) extracts blocks, 2) renders each segment.
#
# Phase 1 scope (inline):
#   - Text segments → bold, italic, code, links via format_markdown()
#   - Role label ("You:" / "Agent:") shown above message
#
# Phase 2 scope (block-level):
#   - Code blocks → syntax-highlighted, header bar with lang + copy button
#   - Blockquotes → left border, italic, muted
#   - Terminal blocks → amber left border, monospace, $ prefix
#   - Headings → scaled font size
#   - Task lists → checkbox character (☑/☐)
#
# Architecture:
#   Each bubble is a vertical Gtk.Box (content wrapper) inside a
#   container Gtk.Box that sets alignment via halign.
#   CSS classes: .chat-bubble-you  /  .chat-bubble-agent

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Pango, Gdk

from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
from utils.block_parser import extract_blocks
from utils.syntax_highlight import highlight


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def build_role_bubble(role: str, text: str) -> Gtk.Widget:
    """
    Build a styled chat bubble for the given role and raw text.

    Handles both inline (Phase 1) and block-level (Phase 2) content:
      - Parses text into segments via extract_blocks()
      - Renders each segment with the appropriate widget factory
      - Wraps everything in a role-labeled bubble box

    Args:
        role: "You" for user messages (right-aligned), "Agent" otherwise
              (left-aligned, for agent responses)
        text: Raw message text — may contain markdown, code blocks, quotes, etc.

    Returns:
        A Gtk.Widget (Gtk.Box) containing the bubble.
        Caller is responsible for adding it to the parent container.
    """
    # ── Outer container: sets horizontal alignment ─────────────────────
    container = Gtk.Box()
    container.set_halign(Gtk.Align.END if role == "You" else Gtk.Align.START)

    # ── Bubble box: vertical stack of segments + optional role label ───
    bubble = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        css_classes=["chat-bubble-you" if role == "You" else "chat-bubble-agent"],
    )
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)

    # ── Parse into segments and render each ─────────────────────────────
    segments = extract_blocks(text)
    for seg in segments:
        widget = _build_segment_widget(seg)
        if widget is not None:
            bubble.append(widget)

    container.append(bubble)
    return container


# ─────────────────────────────────────────────────────────────────────────────
# Segment widget factories
# ─────────────────────────────────────────────────────────────────────────────

def _build_segment_widget(seg: dict) -> Gtk.Widget | None:
    """Route a segment dict to the appropriate widget factory."""
    seg_type = seg.get("type", "text")

    if seg_type == "text":
        return _build_text_segment(seg)
    elif seg_type == "code":
        return _build_code_segment(seg)
    elif seg_type == "quote":
        return _build_quote_segment(seg)
    elif seg_type == "terminal":
        return _build_terminal_segment(seg)
    elif seg_type == "heading":
        return _build_heading_segment(seg)
    elif seg_type == "task":
        return _build_task_segment(seg)
    else:
        return None


def _build_text_segment(seg: dict) -> Gtk.Widget:
    """Render a plain text segment with inline markdown formatting."""
    raw = seg.get("content", "")
    if not raw.strip():
        return Gtk.Box()  # empty spacer

    # Apply markdown first (may produce <b>, <i>, <a> Pango tags),
    # then escape any remaining literal angle brackets in the original text.
    formatted = format_markdown(raw)
    safe = escape_for_pango(formatted)
    label = Gtk.Label()
    label.set_markup(safe)
    label.set_xalign(0)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.add_css_class("chat-msg-label")
    return label


def _build_code_segment(seg: dict) -> Gtk.Widget:
    """
    Render a code block with syntax highlighting, language label, and copy button.

    Structure:
      code-block (css class with lang variant)
      ├── header: [lang-label] [Copy]
      └── content: syntax-highlighted monospace label
    """
    lang = seg.get("lang", "").lower().strip()
    code = seg.get("content", "")

    # ── Outer block box ───────────────────────────────────────────────
    block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    block.add_css_class("code-block")
    if lang:
        block.add_css_class(f"lang-{lang}")

    # ── Header bar ────────────────────────────────────────────────────
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("code-block-header")

    lang_label = Gtk.Label()
    lang_label.set_text(lang or "code")
    lang_label.set_xalign(0)
    lang_label.set_hexpand(True)

    copy_btn = Gtk.Button(label="Copy")
    copy_btn.add_css_class("code-copy-btn")
    copy_btn.connect("clicked", lambda _: _copy_to_clipboard(code))

    header.append(lang_label)
    header.append(copy_btn)
    block.append(header)

    # ── Content: syntax-highlighted code ──────────────────────────────
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    content.add_css_class("code-block-content")

    highlighted = highlight(code, lang) if code.strip() else html_escape(code)
    code_label = Gtk.Label()
    code_label.set_markup(highlighted)
    code_label.set_xalign(0)
    code_label.set_wrap(True)
    code_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    code_label.set_selectable(True)

    content.append(code_label)
    block.append(content)

    return block


def _build_quote_segment(seg: dict) -> Gtk.Widget:
    """Render a blockquote with left border and italic muted text."""
    content = seg.get("content", "")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.add_css_class("blockquote")

    # Apply markdown first, then escape remaining angle brackets.
    formatted = format_markdown(content)
    safe = escape_for_pango(formatted)
    label = Gtk.Label()
    label.set_markup(safe)
    label.set_xalign(0)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.add_css_class("blockquote-text")
    box.append(label)
    return box


def _build_terminal_segment(seg: dict) -> Gtk.Widget:
    """
    Render a terminal block with amber left border and $ prefix on lines.
    """
    content = seg.get("content", "")

    block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    block.add_css_class("terminal-block")

    # Header with amber styling
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("terminal-header")
    term_label = Gtk.Label()
    term_label.set_text("$ terminal")
    term_label.set_xalign(0)
    term_label.set_hexpand(True)
    header.append(term_label)
    block.append(header)

    # Content lines — each prefixed with $ (or plain for continuation)
    content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    content_box.add_css_class("terminal-content")

    for line in content.split('\n'):
        line_widget = Gtk.Label()
        safe_line = escape_for_pango(line)
        line_widget.set_markup(f"<tt><span foreground=\"#e5c07b\">$</span> {safe_line}</tt>")
        line_widget.set_xalign(0)
        line_widget.set_wrap(True)
        line_widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        content_box.append(line_widget)

    block.append(content_box)
    return block


def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")

    label = Gtk.Label()
    label.set_markup(escape_for_pango(content))
    label.set_xalign(0)
    label.add_css_class(f"chat-heading chat-heading-{level}")
    return label


def _build_task_segment(seg: dict) -> Gtk.Widget:
    """Render a task list item with checkbox character."""
    content = seg.get("content", "")
    # Replace [ ] / [x] with ☐ / ☑ checkbox characters
    content = content.replace('[ ]', '☐').replace('[x]', '☑').replace('[X]', '☑')
    safe = escape_for_pango(content)
    label = Gtk.Label()
    label.set_markup(safe)
    label.set_xalign(0)
    label.add_css_class("task-item")
    return label


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str):
    """Copy text to the system clipboard using GTK4 clipboard API."""
    display = Gdk.Display.get_default()
    if display is None:
        return
    clipboard = display.get_clipboard()
    clipboard.set(text)


def html_escape(text: str) -> str:
    """Simple HTML escaping for code blocks (no Pango markup)."""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;"))
