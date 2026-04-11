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
    margin: 2px 4px;
}
.agent-row:hover {
    background: rgba(99, 102, 241, 0.15);
    border: 1px solid rgba(99, 102, 241, 0.4);
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
    margin: 1px 4px;
    transition: background 0.15s ease;
}
.lib-row:hover {
    background: rgba(99, 102, 241, 0.15);
    border: 1px solid rgba(99, 102, 241, 0.4);
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
