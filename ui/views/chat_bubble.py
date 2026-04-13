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

def build_role_bubble(role: str, text: str, on_forward_click=None, tight: bool = False, forwarded_from: str = None, session_key: str = None) -> Gtk.Widget:
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
    bubble.set_margin_top(1 if tight else 4)
    bubble.set_margin_bottom(4)

    # ── Parse into segments and render each ─────────────────────────────
    # Group all consecutive text segments into one label so the user can
    # select the entire bubble text with a single drag. Block-level segments
    # (code, quote, terminal) are kept as individual widgets.
    # If forwarded_from is set, prepend a header line.
    if forwarded_from:
        text = f"[Forwarded from {forwarded_from}]\n{text}"
    segments = extract_blocks(text)
    text_parts = []
    for seg in segments:
        if seg.get("type") == "text":
            text_parts.append(seg.get("content", ""))
        else:
            # Flush accumulated text segments first
            if text_parts:
                joined_text = "\n".join(text_parts)
                widget = _build_text_segment({"type": "text", "content": joined_text})
                bubble.append(widget)
                text_parts = []
            block_widget = _build_segment_widget(seg)
            if block_widget is not None:
                bubble.append(block_widget)
    # Flush any remaining text at the end
    if text_parts:
        joined_text = "\n".join(text_parts)
        widget = _build_text_segment({"type": "text", "content": joined_text})
        bubble.append(widget)

    # ── Action buttons (agent only, hover-to-reveal) ───────────────────
    if role != "You":
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        actions.add_css_class("chat-bubble-actions")
        actions.set_spacing(4)

        # Copy button — SVG icon, hover reveal (opacity 0.3 → 1.0)
        copy_btn = Gtk.Button()
        copy_btn.add_css_class("flat")
        copy_btn.set_tooltip_text("Copy message")
        copy_btn.set_size_request(22, 22)
        copy_btn.set_opacity(0.3)
        try:
            copy_btn.set_child(Gtk.Image.new_from_file(
                "/home/q/projects/crabcakes/ui/icons/copy.svg"))
        except Exception:
            copy_btn.set_label("📋")
        copy_btn.connect("clicked", lambda _, t=text: _copy_to_clipboard(t))
        copy_motion = Gtk.EventControllerMotion()
        copy_motion.connect("enter", lambda _c, _x, _y: copy_btn.set_opacity(1.0))
        copy_motion.connect("leave", lambda _c: copy_btn.set_opacity(0.3))
        copy_btn.add_controller(copy_motion)

        # Forward button — SVG icon, hover reveal, popover menu on click
        fwd_btn = Gtk.Button()
        fwd_btn.add_css_class("flat")
        fwd_btn.set_tooltip_text("Forward to another agent")
        fwd_btn.set_size_request(22, 22)
        fwd_btn.set_opacity(0.3)
        try:
            fwd_btn.set_child(Gtk.Image.new_from_file(
                "/home/q/projects/crabcakes/ui/icons/forward.svg"))
        except Exception:
            fwd_btn.set_label("↗")
        if on_forward_click:
            fwd_btn.connect("clicked", lambda btn, t=text, sk=session_key: on_forward_click(t, btn, sk))
        else:
            fwd_btn.connect("clicked", lambda _: print("[chat_bubble] forward (no handler)"))
        fwd_motion = Gtk.EventControllerMotion()
        fwd_motion.connect("enter", lambda _c, _x, _y: fwd_btn.set_opacity(1.0))
        fwd_motion.connect("leave", lambda _c: fwd_btn.set_opacity(0.3))
        fwd_btn.add_controller(fwd_motion)

        actions.append(copy_btn)
        actions.append(fwd_btn)
        bubble.append(actions)

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
    label.set_selectable(True)
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
    label.set_selectable(True)
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
        line_widget.set_selectable(True)
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
    label.set_selectable(True)
    label.add_css_class("chat-heading")
    label.add_css_class(f"chat-heading-{level}")
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
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_selectable(True)
    label.add_css_class("task-item")
    return label


# ─────────────────────────────────────────────────────────────────────────────
# Streaming bubble factory (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

def build_streaming_bubble(agent_name: str = "Agent") -> Gtk.Widget:
    """
    Build a streaming response bubble with an inline cursor (▍).

    The bubble starts with just the cursor and text is appended incrementally
    via update_streaming(). When streaming ends, the cursor is removed and
    the bubble is re-rendered as a final message.

    Args:
        agent_name: Display name for the agent role label.

    Returns:
        A tuple (container, label) where container goes in the chat box
        and label is the mutable text label the caller updates.
    """
    container = Gtk.Box()
    container.set_halign(Gtk.Align.START)

    bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bubble.add_css_class("chat-bubble-pending")
    bubble.add_css_class("chat-bubble-agent")
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)

    label = Gtk.Label()
    label.set_markup("<tt>▍</tt>")
    label.set_xalign(0)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_selectable(True)
    label.add_css_class("chat-msg-label")
    bubble.append(label)

    container.append(bubble)
    return container, label


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Event card factories (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────

def create_file_card(file_path: str, snippet: str = "", line_range: str = "") -> Gtk.Widget:
    """
    Build a file-read event card with 📄 icon, filename, optional line range, and snippet.

    """
    container = Gtk.Box()
    container.set_halign(Gtk.Align.START)

    bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bubble.add_css_class("chat-bubble-agent")
    bubble.add_css_class("bubble-file-read")
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)

    # Header: 📄 icon + file path + optional line range
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("code-block-header")

    icon_label = Gtk.Label(label="<b>📄 File read</b>")
    icon_label.set_markup("<b>📄 File read</b>")
    icon_label.set_xalign(0)
    path_label = Gtk.Label()
    path_label.set_markup(f"<b>{escape_for_pango(file_path)}</b>")
    path_label.set_xalign(0)
    path_label.set_hexpand(True)
    if line_range:
        lr_label = Gtk.Label(label=f"  {line_range}")
        lr_label.set_markup(f"  <span foreground=\"#9b9bab\">{escape_for_pango(line_range)}</span>")
        header.append(icon_label)
        header.append(path_label)
        header.append(lr_label)
    else:
        header.append(icon_label)
        header.append(path_label)
    bubble.append(header)

    # Snippet if provided
    if snippet:
        snippet_code = Gtk.Label()
        snippet_code.set_markup(escape_for_pango(snippet))
        snippet_code.set_xalign(0)
        snippet_code.set_wrap(True)
        snippet_code.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        snippet_code.set_selectable(True)
        snippet_code.add_css_class("code-block-content")
        snippet_code.set_margin_start(12)
        bubble.append(snippet_code)

    container.append(bubble)
    return container


def create_edit_card(file_path: str, diff: str = "") -> Gtk.Widget:
    """
    Build an edit-proposal event card with ✏️ icon, filename, and diff content.
    """
    container = Gtk.Box()
    container.set_halign(Gtk.Align.START)

    bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bubble.add_css_class("chat-bubble-agent")
    bubble.add_css_class("bubble-edit-proposal")
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)

    # Header: ✏️ icon + file path
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("code-block-header")
    icon_label = Gtk.Label()
    icon_label.set_markup("<b>✏️ Edit proposal</b>")
    icon_label.set_xalign(0)
    path_label = Gtk.Label()
    path_label.set_markup(f"<b>{escape_for_pango(file_path)}</b>")
    path_label.set_xalign(0)
    path_label.set_hexpand(True)
    header.append(icon_label)
    header.append(path_label)
    bubble.append(header)

    # Diff content
    if diff:
        diff_label = Gtk.Label()
        diff_label.set_markup(escape_for_pango(diff))
        diff_label.set_xalign(0)
        diff_label.set_wrap(True)
        diff_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        diff_label.set_selectable(True)
        diff_label.add_css_class("code-block-content")
        diff_label.set_margin_start(12)
        bubble.append(diff_label)

    container.append(bubble)
    return container


def create_tool_card(tool_name: str, detail: str = "") -> Gtk.Widget:
    """
    Build a tool-call event card with 🔧 icon and tool name.
    """
    container = Gtk.Box()
    container.set_halign(Gtk.Align.START)

    bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bubble.add_css_class("chat-bubble-agent")
    bubble.add_css_class("bubble-tool-call")
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)

    # Header: 🔧 icon + tool name
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("code-block-header")
    icon_label = Gtk.Label()
    icon_label.set_markup("<b>🔧 Tool call</b>")
    icon_label.set_xalign(0)
    name_label = Gtk.Label()
    name_label.set_markup(f"<b>{escape_for_pango(tool_name)}</b>")
    name_label.set_xalign(0)
    name_label.set_hexpand(True)
    header.append(icon_label)
    header.append(name_label)
    bubble.append(header)

    # Detail if provided
    if detail:
        detail_label = Gtk.Label()
        detail_label.set_markup(escape_for_pango(detail))
        detail_label.set_xalign(0)
        detail_label.set_wrap(True)
        detail_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        detail_label.set_selectable(True)
        detail_label.add_css_class("code-block-content")
        detail_label.set_margin_start(12)
        bubble.append(detail_label)

    container.append(bubble)
    return container


def create_error_bubble(error_msg: str) -> Gtk.Widget:
    """
    Build an error bubble with ❌ icon and error message.
    """
    container = Gtk.Box()
    container.set_halign(Gtk.Align.START)

    bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bubble.add_css_class("chat-bubble-agent")
    bubble.add_css_class("bubble-error")
    bubble.set_margin_top(4)
    bubble.set_margin_bottom(4)


    # Header: ❌ icon + error label
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    header.add_css_class("code-block-header")
    icon_label = Gtk.Label()
    icon_label.set_markup("<b>❌ Error</b>")
    icon_label.set_xalign(0)
    header.append(icon_label)
    bubble.append(header)

    # Error message
    msg_label = Gtk.Label()
    msg_label.set_markup(escape_for_pango(error_msg))
    msg_label.set_xalign(0)
    msg_label.set_wrap(True)
    msg_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    msg_label.set_selectable(True)
    msg_label.set_margin_start(12)
    bubble.append(msg_label)

    container.append(bubble)
    return container


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
