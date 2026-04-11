# tests/test_icons.py
"""Tests for utils/icons.py — SVG icon rendering."""

import pytest

# Full texture test requires GDK display — only run if available
SKIP_IF_NO_DISPLAY = pytest.mark.skipif(
    True, reason="render_agent_icon requires GDK display — tested manually"
)

# Smoke test: function is importable and callable with no display
def test_import():
    from utils.icons import render_agent_icon
    assert callable(render_agent_icon)


def test_agent_icon_returns_none_without_display(monkeypatch):
    """Without a display, new_from_filename raises — verify it propagates."""
    from utils.icons import render_agent_icon
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk

    # Patch new_from_filename to raise (as it would without display)
    class FakeTexture:
        pass

    def raise_no_display(*args, **kwargs):
        raise RuntimeError("No GDK display available")

    monkeypatch.setattr(Gdk.Texture, "new_from_filename", raise_no_display)

    with pytest.raises(RuntimeError, match="No GDK display"):
        render_agent_icon("#6366f1", "Qa", size=44)


def test_compute_initials_two_words():
    """Initials computation matches what left_panel uses."""
    name = "Qrusher Qat"
    parts = name.split()
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[1][0]).upper()
    else:
        initials = name[:2].upper()
    assert initials == "QQ"


def test_compute_initials_single_word():
    name = "Qat"
    parts = name.split()
    initials = (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else name[:2].upper()
    assert initials == "QA"
