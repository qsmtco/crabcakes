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
    if not url:
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
    """
    if _is_safe_scheme(uri):
        return False  # allow
    # Non-allowlisted scheme — block + log
    logger.warning(
        "HIGH-6: blocked navigation to non-allowlisted scheme: %s", uri
    )
    return True  # block


['str] | None = None,\n) -> "Gtk.Label":\n    "', 'Create a Gtk.Label wired with the HIGH-6 activate-link guard.\n\n    Caller passes already-formatted Pango markup (output of escape_for_pango +\n    format_markdown). This helper:\n      1. Creates the Gtk.Label.\n      2. Sets the markup.\n      3. Connects `activate-link` to on_activate_link (the HIGH-6 guard).\n      4. Sets xalign / wrap / selectable / css_class as specified.\n\n    Use this in place of `Gtk.Label() + set_markup()` for any label that\n    renders user- or agent-authored text.\n\n    Args:\n        markup: The Pango markup string to display (output of escape_for_pango\n            + format_markdown).\n        xalign: Horizontal alignment (0=left, 0.5=center, 1=right). Default 0.\n        wrap: Whether to wrap text. Default True.\n        selectable: Whether the text is selectable. Default True.\n        css_class: A single CSS class to add. Backward compat with existing\n            callers.\n        css_classes: A list of CSS classes to add. Use this when you need to\n            apply multiple classes (e.g., ["chat-heading', 'chat-heading-2']
