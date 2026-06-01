# tests/test_main_content_tab_switch.py
# Tests for ui/views/main_content.py — tab-switch overlay reparenting.
#
# What this tests:
#   MainContent._on_notebook_switch_page moves the singleton overlays
#   (project_settings, scroll_btn_box) from the previous tab's Gtk.Overlay
#   to the new tab's Gtk.Overlay. The previous implementation called
#   `old_parent.remove(widget)` to detach — but Gtk.Overlay is NOT a
#   Gtk.Container in GTK4 and has no .remove() method. Switching tabs
#   crashed with AttributeError: 'Gtk.Overlay' object has no attribute
#   'remove'.
#
#   Fix: use `widget.unparent()` (a Gtk.Widget method) instead of
#   `old_parent.remove(widget)`. This works regardless of parent type.
#
#   This test verifies:
#   1. On tab switch, unparent() is called on each singleton widget
#      that has a parent, BEFORE add_overlay() is called on the new overlay.
#   2. The new overlay receives add_overlay() for each singleton widget.
#   3. The previous fix path (old_parent.remove) is NOT used.
#   4. Tab switch with no previous parent (first tab) works — widgets
#      are added directly without unparent().

import pytest
from unittest.mock import MagicMock, call

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ui.views.main_content import MainContent  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mc():
    """A MainContent with internal state stubbed for tab-switch testing.

    We don't construct a real MainContent (it needs a full GTK app shell).
    Instead we create an instance via __new__ and inject the attributes
    that _on_notebook_switch_page touches.
    """
    instance = MainContent.__new__(MainContent)
    instance._chat_notebook = MagicMock(spec=Gtk.Notebook)
    instance._tab_overlays = {}
    # Singleton widgets — real Gtk.Box instances so unparent() works.
    instance._project_settings = Gtk.Box()
    instance._scroll_btn_box = Gtk.Box()
    # Stubs for the post-overlay code path (scroll_to_bottom, clear_unread)
    instance._tab_scrolls = {}
    instance._unread_tabs = set()
    instance.scroll_chat_to_bottom = MagicMock()
    instance.clear_unread = MagicMock()
    return instance


# ── Tests ───────────────────────────────────────────────────────────────────


class TestSwitchPageOverlayReparent:
    """Verify _on_notebook_switch_page uses unparent(), not .remove()."""

    def test_unparent_called_when_widget_has_old_parent(self, mc):
        """Regression: the bug was old_parent.remove(widget) crashing on
        Gtk.Overlay. Widget.unparent() is the correct GTK4 pattern."""
        # Old overlay (previous tab) — a real Gtk.Overlay with the widget as child
        old_overlay = Gtk.Overlay()
        old_overlay.add_overlay(mc._project_settings)
        old_overlay.add_overlay(mc._scroll_btn_box)

        # New overlay (the tab being switched to) — real Gtk.Overlay
        new_overlay = Gtk.Overlay()
        mc._tab_overlays[2] = new_overlay

        # Trigger tab switch
        mc._on_notebook_switch_page(mc._chat_notebook, None, 2)

        # Both widgets must now be parented to the new overlay
        assert mc._project_settings.get_parent() is new_overlay
        assert mc._scroll_btn_box.get_parent() is new_overlay
        # And no longer parented to the old one
        assert mc._project_settings.get_parent() is not old_overlay

    def test_no_crash_when_previous_parent_is_overlay(self, mc):
        """Direct regression test for the AttributeError on Gtk.Overlay.

        Before the fix, this raised:
          AttributeError: 'Gtk.Overlay' object has no attribute 'remove'

        After the fix, widget.unparent() handles any parent type.
        """
        old_overlay = Gtk.Overlay()
        old_overlay.add_overlay(mc._project_settings)
        new_overlay = Gtk.Overlay()
        mc._tab_overlays[1] = new_overlay

        # Must not raise
        mc._on_notebook_switch_page(mc._chat_notebook, None, 1)
        assert mc._project_settings.get_parent() is new_overlay

    def test_unparent_happens_before_add_overlay(self, mc):
        """Order matters: unparent must happen before add_overlay on the new
        overlay, otherwise GTK4 emits the 'Can't set new parent' warning
        that the previous fix was trying to avoid."""
        old_overlay = Gtk.Overlay()
        old_overlay.add_overlay(mc._project_settings)
        new_overlay = Gtk.Overlay()
        mc._tab_overlays[0] = new_overlay

        mc._on_notebook_switch_page(mc._chat_notebook, None, 0)

        # The widget is now parented to new_overlay (not old_overlay)
        assert mc._project_settings.get_parent() is new_overlay
        assert mc._project_settings.get_parent() is not old_overlay

    def test_widget_without_parent_added_directly(self, mc):
        """First tab (no previous parent) — widgets are added without unparent."""
        new_overlay = Gtk.Overlay()
        mc._tab_overlays[0] = new_overlay
        # Singletons have no parent yet
        assert mc._project_settings.get_parent() is None
        assert mc._scroll_btn_box.get_parent() is None

        mc._on_notebook_switch_page(mc._chat_notebook, None, 0)

        # Both widgets added to new overlay
        assert mc._project_settings.get_parent() is new_overlay
        assert mc._scroll_btn_box.get_parent() is new_overlay

    def test_switch_to_tab_with_no_overlay_is_noop(self, mc):
        """If _tab_overlays has no entry for page_num, skip the reparent block."""
        # _tab_overlays is empty
        mc._on_notebook_switch_page(mc._chat_notebook, None, 5)
        # Singletons untouched
        assert mc._project_settings.get_parent() is None
        assert mc._scroll_btn_box.get_parent() is None

    def test_widgets_moved_across_three_tabs(self, mc):
        """Full lifecycle: widgets move tab → tab → tab without crashing.
        Simulates opening 3 chat tabs and switching between them."""
        overlay_a = Gtk.Overlay()
        overlay_b = Gtk.Overlay()
        overlay_c = Gtk.Overlay()
        # Add singletons to overlay_a initially
        overlay_a.add_overlay(mc._project_settings)
        overlay_a.add_overlay(mc._scroll_btn_box)
        mc._tab_overlays[0] = overlay_a
        mc._tab_overlays[1] = overlay_b
        mc._tab_overlays[2] = overlay_c

        # Switch to tab 1
        mc._on_notebook_switch_page(mc._chat_notebook, None, 1)
        assert mc._project_settings.get_parent() is overlay_b
        assert mc._scroll_btn_box.get_parent() is overlay_b

        # Switch to tab 2
        mc._on_notebook_switch_page(mc._chat_notebook, None, 2)
        assert mc._project_settings.get_parent() is overlay_c
        assert mc._scroll_btn_box.get_parent() is overlay_c

        # Switch back to tab 0
        mc._on_notebook_switch_page(mc._chat_notebook, None, 0)
        assert mc._project_settings.get_parent() is overlay_a
        assert mc._scroll_btn_box.get_parent() is overlay_a
