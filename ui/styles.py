# ui/styles.py
# Single source of truth for all application CSS.
#
# Security: No secrets, no file I/O. Pure CSS string + one apply function.
#
# Architecture rule (ARCHITECTURE.md Section 9):
#   - Views call add_css_class("name") to apply styles
#   - Views NEVER call Gtk.CssProvider().load_from_data() themselves
#   - All CSS definitions live here in APP_CSS
#   - apply_styles() is called once at startup from main.py

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk


# ── Feed bar ──────────────────────────────────────────────────────────────
# Applied to the thin strip between chat notebook and control bar.

# ── Button styles ────────────────────────────────────────────────────────
# suggested-action = primary solid (Send button)
# btn-improve      = indigo tint (Improve button)
# flat             = ghost/transparent (Prompt button, toolbar mic)

# ── Input area ───────────────────────────────────────────────────────────
# input-bubble = dark rounded input field

# ── Agent cards ──────────────────────────────────────────────────────────
# agent-row, agent-name-label, agent-add-btn, agent-remove-btn

APP_CSS = """
/* ── Feed bar ─────────────────────────────────────────────────────────── */
.project-feed-bar {
    background: rgba(30, 30, 40, 0.75);
    border-radius: 4px;
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
button.suggested-action {
    background: #6366f1;
    color: #ffffff;
    border-radius: 6px;
}
button.suggested-action:hover {
    background: #4f46e5;
}

button.btn-improve {
    background: rgba(79, 70, 229, 0.2);
    color: #a5b4fc;
    border-radius: 6px;
    border: none;
    box-shadow: none;
}
button.btn-improve:hover {
    background: rgba(99, 102, 241, 0.35);
    color: #c7d2fe;
}

button.flat {
    background: transparent;
    color: #6b6b7a;
    border: 1px solid transparent;
    border-radius: 6px;
    box-shadow: none;
}
button.flat:hover {
    border: 1px solid #3f3f50;
    color: #9b9bab;
}

/* ── Input area ───────────────────────────────────────────────────────── */
.input-bubble {
    background: #111114;
    border: none;
    border-radius: 14px 14px 14px 2px;
    color: #e8e8ec;
}
.input-bubble text {
    background-color: transparent;
    color: #e8e8ec;
}
.input-bubble selection {
    background-color: #6366f1;
    color: #ffffff;
}

/* ── Agent cards ──────────────────────────────────────────────────────── */
.agent-row {
    background: rgba(255, 255, 255, 0.04);
    border-radius: 6px;
    border: 1px solid transparent;
    margin: 2px 4px;
}
.agent-row:hover {
    background: rgba(99, 102, 241, 0.15);
    border-color: rgba(99, 102, 241, 0.4);
}
.agent-name-label {
    color: #e8e8ec;
    font-size: 14px;
}
.agent-add-btn {
    background: rgba(16, 185, 129, 0.2);
    color: #6ee7b7;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 12px;
}
.agent-add-btn:hover {
    background: rgba(16, 185, 129, 0.4);
    color: #a7f3d0;
}
.agent-remove-btn {
    background: rgba(244, 63, 94, 0.2);
    color: #fda4af;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 12px;
}
.agent-remove-btn:hover {
    background: rgba(244, 63, 94, 0.4);
    color: #fecdd3;
}

/* ── Prompt library ────────────────────────────────────────────────────── */
.lib-row {
    background: transparent;
    border-radius: 6px;
    border: 1px solid transparent;
    margin: 1px 4px;
    transition: background 0.15s ease, border-color 0.15s ease;
}
.lib-row:hover {
    background: rgba(99, 102, 241, 0.15);
    border-color: rgba(99, 102, 241, 0.4);
}
.lib-row.selected {
    background: rgba(99, 102, 241, 0.25);
}
.lib-fav-star {
    color: #f59e0b;
    font-size: 16px;
}
.lib-tag {
    background: rgba(255, 255, 255, 0.06);
    color: #6b6b7a;
    font-size: 11px;
    border-radius: 4px;
    padding: 1px 4px;
}
/* Project cards */
.project-card {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    padding: 8px;
}
.project-card:hover {
    background: rgba(99, 102, 241, 0.15);
    border-color: rgba(102, 102, 241, 0.4);
}
.project-card-name {
    font-size: 13px;
    color: #e2e8f0;
    font-weight: 500;
}
.project-card-path {
    font-size: 11px;
    color: #6b6b7a;
}

/* ── Chat bubbles (Phase 1) ───────────────────────────────────────────── */
.chat-bubble-agent {
    background: rgba(255, 255, 255, 0.07);
    border-radius: 12px 12px 12px 4px;
    padding: 6px 10px 8px 10px;
    margin: 2px 12px 2px 8px;
}
.chat-bubble-you {
    background: rgba(99, 102, 241, 0.22);
    border-radius: 12px 12px 4px 12px;
    padding: 6px 10px 8px 10px;
    margin: 2px 8px 2px 12px;
}
.chat-role-label {
    font-size: 11px;
    color: #8888a0;
    margin-bottom: 2px;
}
.chat-bubble-you .chat-role-label {
    color: #9090c0;
}
.chat-msg-label {
    font-size: 14px;
    color: #d8d8e8;
}
.chat-msg-label:selected {
    background-color: #6366f1;
    color: #ffffff;
}

/* ── Bubble pending state (optimistic UI) ─────────────────────────────── */
.chat-bubble-pending {
    opacity: 0.6;
    transition: opacity 0.3s ease;
}
.chat-bubble-pending.chat-bubble-you {
    background: rgba(99, 102, 241, 0.15);
}
.chat-bubble-pending.chat-bubble-agent {
    background: rgba(255, 255, 255, 0.04);
}

/* ── Code blocks ─────────────────────────────────────────────────────── */
.code-block {
    background: rgba(30, 30, 40, 0.95);
    border-radius: 8px;
    border-left: 3px solid #3d59a1;
    margin: 4px 0;
}
.code-block-content {
    font-family: monospace;
    font-size: 13px;
    color: #a9b1d6;
    padding: 8px 12px;
    background: transparent;
}
.code-block-header {
    background: rgba(61, 89, 161, 0.3);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    padding: 4px 10px;
    font-size: 11px;
    color: #7aa2f7;
    font-family: monospace;
}
.code-copy-btn {
    background: transparent;
    color: #565f89;
    border: none;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 11px;
}
.code-copy-btn:hover {
    background: rgba(255, 255, 255, 0.08);
    color: #a9b1d6;
}

/* ── Per-language code block accents ─────────────────────────────────── */
.code-block.lang-python  { border-left-color: #61afef; }
.code-block.lang-javascript, .code-block.lang-js { border-left-color: #e5c07b; }
.code-block.lang-typescript, .code-block.lang-ts { border-left-color: #61afef; }
.code-block.lang-bash, .code-block.lang-sh, .code-block.lang-shell { border-left-color: #98c379; }
.code-block.lang-html { border-left-color: #e06c75; }
.code-block.lang-css { border-left-color: #61afef; }
.code-block.lang-rust { border-left-color: #e06c75; }
.code-block.lang-go { border-left-color: #56b6c2; }
.code-block.lang-java { border-left-color: #e5c07b; }
.code-block.lang-c, .code-block.lang-cpp { border-left-color: #61afef; }
.code-block.lang-ruby { border-left-color: #e06c75; }
.code-block.lang-php { border-left-color: #c678dd; }
.code-block.lang-swift { border-left-color: #e5c07b; }
.code-block.lang-kotlin { border-left-color: #c678dd; }
.code-block.lang-sql { border-left-color: #98c379; }
.code-block.lang-json { border-left-color: #98c379; }
.code-block.lang-yaml { border-left-color: #98c379; }
.code-block.lang-markdown { border-left-color: #61afef; }
.code-block.lang-r-lang { border-left-color: #61afef; }

/* ── Blockquotes ──────────────────────────────────────────────────────── */
.blockquote {
    border-left: 3px solid rgba(168, 85, 247, 0.6);
    padding: 4px 10px;
    margin: 4px 0;
    background: rgba(168, 85, 247, 0.06);
    border-radius: 0 4px 4px 0;
}
.blockquote-text {
    font-size: 13px;
    color: #9b9bab;
    font-style: italic;
}


/* ── Event cards (Phase 4) ──────────────────────────────────────────────── */
.bubble-file-read       { border-left: 3px solid #22c55e; }
.bubble-edit-proposal   { border-left: 3px solid #f59e0b; }
.bubble-tool-call       { border-left: 3px solid #94a3b8; }
.bubble-error           { border-left: 3px solid #ef4444; background: rgba(239,68,68,0.08); }
.bubble-thinking        { border-left: 3px solid #f59e0b; }
.bubble-streaming       { border-left: 3px solid #6366f1; }

/* ── Terminal blocks ──────────────────────────────────────────────────── */
.terminal-block {
    background: rgba(20, 20, 30, 0.95);
    border-radius: 6px;
    border-left: 3px solid #e5c07b;
    margin: 4px 0;
}
.terminal-header {
    background: rgba(229, 192, 123, 0.12);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    padding: 4px 10px;
    font-size: 11px;
    color: #e5c07b;
    font-family: monospace;
}
.terminal-content {
    font-family: monospace;
    font-size: 13px;
    color: #a9b1d6;
    padding: 8px 12px;
    background: transparent;
}

/* ── Headings inside bubbles ─────────────────────────────────────────── */
.chat-heading { font-weight: 700; color: #e8e8f0; }
.chat-heading-1 { font-size: 20px; }
.chat-heading-2 { font-size: 17px; }
.chat-heading-3 { font-size: 15px; }
.chat-heading-4 { font-size: 14px; }

/* ── Task list items ─────────────────────────────────────────────────── */
.task-item { font-size: 13px; color: #c0caf5; padding: 1px 0; }
.task-checked { color: #9ece6a; text-decoration: line-through; }
.task-unchecked { color: #f0f0f0; }
"""


def apply_styles():
    """
    Register the global CSS provider for the application.
    Call once at startup, before any windows are created.
    """
    display = Gdk.Display.get_default()
    if display is None:
        return  # headless / test environment
    provider = Gtk.CssProvider()
    provider.load_from_data(APP_CSS.encode())
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
