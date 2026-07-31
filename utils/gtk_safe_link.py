# utils/gtk_safe_link.py
# HIGH-6: GTK widget helper that creates labels with an `activate-link` handler
# that gates navigation on the link scheme. Non-allowlisted schemes are blocked
# from opening (the signal returns True to prevent default navigation).
#
# Architecture: utils/ is pure Python — but this file is allowed to import GTK
# because callers are GTK-bound. The activate-link handler is the actual guard:
# it intercepts <a href="..."> clicks and decides whether to allow navigation.
#
# Schemes that ARE allowed (no prompt, just open):
#   - http, https, mailto  (matches the markdown _ALLOWED_LINK_SCHEMES set)
#
# Schemes that are BLOCKED (returns True from activate-link to cancel):
#   - file://, smb://, ftp://, ssh://
#   - javascript:, data:
#   - any custom URI scheme (foo://, app://, etc.)
#   - relative paths that resolve to file:// (we block those too, defensively)
#
# This is HIGH-6 defense-in-depth on top of the render-time allowlist in
# utils/markdown.py. The render-time check converts non-allowlisted URLs to
# escaped text; the activate-link handler catches anything that slips through
# (e.g. a URL embedded in a different attribute, future formatting additions).

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# Must match utils/markdown._ALLOWED_LINK_SCHEMES
_ALLOWED_LINK_SCHEMES = frozenset({"http", "https", "mailto"})


def _is_safe_scheme(url: str) -> bool:
    """Return True if `url` is a URL with a safe scheme (or relative)."""
    if not isinstance(url, str) or not url:
        return False
    # Allow relative URLs (no scheme) — they navigate within the app's webview,
    # which isn't a code-execution vector the same way custom schemes are.
    if not url[0].isalpha():
        return True  # relative path like "/foo" or "#anchor"
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    scheme = (parsed.scheme or "").lower()
    if not scheme:
        return True  # scheme-less relative URL
    return scheme in _ALLOWED_LINK_SCHEMES


def on_activate_link(_label, uri: str) -> bool:
    """Gtk.Label `activate-link` signal handler (HIGH-6).

    Return True to BLOCK navigation (the link will not open).
    Return False to allow GTK to open the link via the default handler.

    Blocking rule: only allow schemes in _ALLOWED_LINK_SCHEMES.
    Fail-closed: non-string URIs are blocked (defense against TypeError
    causing fail-open in PyGObject's exception handling).
    """
    if not isinstance(uri, str):
        logger.warning("HIGH-6: non-string URI in activate-link: %r", uri)
        return True  # block (fail-closed)
    if _is_safe_scheme(uri):
        return False  # allow
    # Non-allowlisted scheme — block + log
    logger.warning(
        "HIGH-6: blocked navigation to non-allowlisted scheme: %s", uri
    )
    return True  # block


def make_safe_label(
    markup: str,
    *,
    xalign: float = 0,
    wrap: bool = True,
    selectable: bool = True,
    css_class: str | None = None,           # backward compat: single class
    css_classes: list[str] | None = None,   # NEW (Bug #5): multiple classes
) -> "Gtk.Label":
    """Create a Gtk.Label wired with the HIGH-6 activate-link guard.

    Caller passes already-formatted Pango markup (output of escape_for_pango +
    format_markdown). This helper:
      1. Creates the Gtk.Label.
      2. Sets the markup.
      3. Connects `activate-link` to on_activate_link (the HIGH-6 guard).
      4. Sets xalign / wrap / selectable / css_class / css_classes as specified.

    Use this in place of `Gtk.Label() + set_markup()` for any label that
    renders user- or agent-authored text.

    Args:
        markup: The Pango markup string to display (output of escape_for_pango
            + format_markdown).
        xalign: Horizontal alignment (0=left, 0.5=center, 1=right). Default 0.
        wrap: Whether to wrap text. Default True.
        selectable: Whether the text is selectable. Default True.
        css_class: A single CSS class to add. Backward compat with existing
            callers.
        css_classes: A list of CSS classes to add. Use this when you need to
            apply multiple classes (e.g., ["chat-heading", "chat-heading-2"]).
            GTK4's add_css_class() treats strings as single class names —
            spaces are NOT separators. See Bug #5 in spec-markdown-header-fix.md.

    Returns:
        A configured Gtk.Label with the markup applied and the activate-link
        handler connected (HIGH-6 defense-in-depth: non-allowlisted schemes
        like javascript: are blocked).
    """
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Pango  # noqa: F401

    label = Gtk.Label()
    label.set_markup(markup)
    label.set_xalign(xalign)
    if wrap:
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        # Bound the natural width — prevents Pango unbounded-width explosion
        # which causes truncation of long messages in the chat viewport.
        label.set_max_width_chars(120)
    label.set_can_focus(False)
    label.set_selectable(selectable)
    if css_class:
        label.add_css_class(css_class)
    if css_classes:
        # Guard against non-list iterables (Bug #5 type guard, tightened per
        # adversarial audit): str/bytes iterate char-by-char, dict iterates
        # keys, generators are one-shot. Only list and tuple are valid.
        if not isinstance(css_classes, (list, tuple)):
            raise TypeError(
                f"css_classes must be a list or tuple, got {type(css_classes).__name__}. "
                "Use css_class='single' for one class, or "
                "css_classes=['a', 'b'] for multiple."
            )
        for cls in css_classes:
            if not isinstance(cls, str) or not cls:
                raise ValueError(f"Invalid CSS class: {cls!r}")
            label.add_css_class(cls)
    # HIGH-6: gate navigation on scheme allowlist
    label.connect("activate-link", on_activate_link)
    return label
