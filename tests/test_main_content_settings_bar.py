# tests/test_main_content_settings_bar.py
# Unit tests for ui/views/main_content.py — project settings bar logic.
#
# SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-3 §5 Step 3 (Phase I.5).
# Covers:
#   - _clear_settings_bar()           (sibling-walk cleanup)
#   - update_project_settings()       (empty hides; non-empty shows)
#   - gear-preservation (BUG #5)      (set_project_settings_text /
#                                       set_feed_bar_text re-append gear)
#   - xml_escape_text hardening (BUG #6) (project_name / branch literal)
#   - _resolve_agent_display_name()   (BUG #7 .get() + truthiness fallback)
#   - click-handler None guards
#
# CRITICAL: GTK widget construction segfaults in this sandbox. We swap the
# module-global `Gtk` for lightweight fakes so the REAL method bodies execute
# without constructing any real GTK widgets.

import pytest
from unittest.mock import MagicMock

from ui.views.main_content import MainContent


# ── Fake Gtk classes (no real GTK construction) ──────────────────────────────


class _Align:
    START = 1
    END = 2
    FILL = 3


class _Orientation:
    HORIZONTAL = 1
    VERTICAL = 2


class _FakeWidget:
    """Base: records a parent link and exposes the sibling-walk contract."""

    def __init__(self, *args, **kwargs):
        self._parent = None
        self.css_classes = []

    def add_css_class(self, cls):
        self.css_classes.append(cls)

    def get_parent(self):
        return self._parent


class _FakeBox(_FakeWidget):
    """Fake Gtk.Box. Implements append/remove/get_first_child as a list.

    Mirror semantics of the real sibling-walk: remove() dethreads the widget
    and clears its parent back-reference. Does NOT implement __iter__ (the
    real Gtk.Box lacks it too — the bug class was `in`/`list()` misuse).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.children = []
        self.visible = None
        self.hexpand = False
        self.halign = None

    def append(self, widget):
        widget._parent = self
        self.children.append(widget)

    def remove(self, widget):
        if widget in self.children:
            self.children.remove(widget)
            widget._parent = None

    def get_first_child(self):
        return self.children[0] if self.children else None

    def set_visible(self, v):
        self.visible = v

    def set_hexpand(self, v):
        self.hexpand = v

    def set_halign(self, v):
        self.halign = v

    # no-op int setters used by the bar code
    def set_valign(self, *a):
        pass

    def set_size_request(self, *a):
        pass

    def set_margin_top(self, *a):
        pass

    def set_margin_bottom(self, *a):
        pass

    def set_margin_start(self, *a):
        pass

    def set_margin_end(self, *a):
        pass


class _FakeLabel(_FakeBox):
    """Fake Gtk.Label — captures set_markup/set_text payloads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.markup = None
        self.plain_text = None

    def set_markup(self, m):
        self.markup = m

    def set_text(self, t):
        self.plain_text = t


class _FakeButton(_FakeBox):
    """Fake Gtk.Button — records connect() for click handlers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connections = []
        self._child = None

    def set_child(self, widget):
        self._child = widget

    def connect(self, sig, cb):
        self.connections.append((sig, cb))
        return 0

    def set_has_frame(self, *a):
        pass

    def set_focus_on_click(self, *a):
        pass


class _FakeGtk:
    Orientation = _Orientation
    Align = _Align

    @staticmethod
    def Box(*args, **kwargs):
        return _FakeBox(*args, **kwargs)

    @staticmethod
    def Label(*args, **kwargs):
        return _FakeLabel(*args, **kwargs)

    @staticmethod
    def Button(*args, **kwargs):
        return _FakeButton(*args, **kwargs)


# ── Fixture: swap module-global Gtk for fakes ────────────────────────────────


@pytest.fixture
def fake_gtk(monkeypatch):
    monkeypatch.setattr("ui.views.main_content.Gtk", _FakeGtk)
    return _FakeGtk


@pytest.fixture
def mc(fake_gtk):
    """A MainContent with only the settings-bar state injected via __new__.

    The real method bodies (the units under test) execute against the fake
    Gtk classes. No real GTK widgets are constructed.
    """
    instance = MainContent.__new__(MainContent)
    instance._project_settings = _FakeBox()
    # Mirror the __init__ gear construction using the fake Gtk.
    instance._settings_btn = _FakeGtk.Button(label="⚙")
    instance._on_settings_clicked = None
    instance._on_agent_cycle = None
    instance._on_autoaccept_cycle = None
    instance._agent_mgr = None
    instance._agent_runtime_handler = None
    return instance


# ── Tests ────────────────────────────────────────────────────────────────────


class TestClearSettingsBar:
    def test_clear_settings_bar_sibling_walk(self, mc):
        """_clear_settings_bar removes all children via get_first_child/remove.

        Regression guard for the gtk-container-membership bug class: the
        helper must NOT use `for child in list(box)` or `widget in box`.
        """
        a, b, c = _FakeBox(), _FakeBox(), _FakeBox()
        mc._project_settings.append(a)
        mc._project_settings.append(b)
        mc._project_settings.append(c)
        assert len(mc._project_settings.children) == 3

        mc._clear_settings_bar()

        assert len(mc._project_settings.children) == 0
        # Each removed widget lost its parent back-reference.
        assert a.get_parent() is None
        assert b.get_parent() is None
        assert c.get_parent() is None


class TestUpdateProjectSettings:
    def test_update_project_settings_hides_on_empty(self, mc):
        """Falsy project_name -> set_visible(False) and bar cleared."""
        mc.update_project_settings("", 0, None, "off", None)
        assert mc._project_settings.visible is False
        assert len(mc._project_settings.children) == 0

    def test_update_project_settings_shows_on_nonempty(self, mc):
        """Valid args -> set_visible(True) and info_box + gear appended.

        The bar ends with exactly two top-level children: the info_box and
        the singleton gear button (which _clear_settings_bar removed)."""
        mc.update_project_settings("proj", 2, None, "off", "main")

        assert mc._project_settings.visible is True
        children = mc._project_settings.children
        assert len(children) == 2
        assert children[1] is mc._settings_btn, (
            "gear must be re-appended last (BUG #5)"
        )
        info_box = children[0]
        assert isinstance(info_box, _FakeBox)


class TestGearPreservation:
    def test_gear_preserved_in_set_project_settings_text(self, mc):
        """set_project_settings_text re-appends the gear (BUG #5)."""
        mc.set_project_settings_text("legacy")
        # label + gear
        assert mc._settings_btn.get_parent() is mc._project_settings
        assert len(mc._project_settings.children) == 2
        assert mc._project_settings.children[1] is mc._settings_btn

    def test_gear_preserved_in_set_feed_bar_text(self, mc):
        """set_feed_bar_text re-appends the gear (BUG #5)."""
        mc.set_feed_bar_text("status")
        assert mc._settings_btn.get_parent() is mc._project_settings
        assert len(mc._project_settings.children) == 2
        assert mc._project_settings.children[1] is mc._settings_btn

    def test_gear_preserved_through_repeated_calls(self, mc):
        """Repeated rebuilds never lose the gear."""
        for _ in range(3):
            mc.set_project_settings_text("x")
            assert mc._settings_btn.get_parent() is mc._project_settings
        mc.set_feed_bar_text("y")
        assert mc._settings_btn.get_parent() is mc._project_settings


class TestXmlEscapeHardening:
    def test_xml_escape_for_project_name(self, mc):
        """Project name '<b>injected</b>' renders escaped, NOT as a tag (BUG #6)."""
        mc.update_project_settings("<b>injected</b>", 1, None, "off", None)
        info_box = mc._project_settings.children[0]
        name_label = info_box.children[0]
        assert name_label.markup is not None
        assert "<b>injected</b>" not in name_label.markup
        assert "&lt;b&gt;injected&lt;/b&gt;" in name_label.markup

    def test_xml_escape_for_branch(self, mc):
        """Branch '<script>' renders escaped (BUG #6)."""
        mc.update_project_settings("proj", 1, None, "off", "<script>")
        info_box = mc._project_settings.children[0]
        branch_label = info_box.children[-1]
        assert branch_label.markup is not None
        assert "<script>" not in branch_label.markup
        assert "&lt;script&gt;" in branch_label.markup


class TestResolveAgentDisplayName:
    def test_resolve_agent_display_name_fallback(self, mc):
        """No _agent_mgr / _agent_runtime_handler -> session_key as-is."""
        assert mc._resolve_agent_display_name("special:coder") == "special:coder"

    def test_resolve_agent_display_name_empty_value_fallback(self, mc):
        """ARTH.get_special_agents() returning {'special:x': ''} must fall
        through to session_key, NOT return '' (Round 3 BUG #7)."""
        arth = MagicMock()
        arth.get_special_agents.return_value = {"special:x": ""}
        mc._agent_runtime_handler = arth
        assert mc._resolve_agent_display_name("special:x") == "special:x"

    def test_resolve_agent_display_name_none_value_fallback(self, mc):
        """ARTH.get_special_agents() returning {'special:x': None} must fall
        through to session_key (BUG #7 truthiness)."""
        arth = MagicMock()
        arth.get_special_agents.return_value = {"special:x": None}
        mc._agent_runtime_handler = arth
        assert mc._resolve_agent_display_name("special:x") == "special:x"

    def test_resolve_agent_display_name_uses_agent_mgr_first(self, mc):
        """_agent_mgr name wins over the ARTH fallback."""
        mgr = MagicMock()
        mgr.get_name.return_value = "Coder"
        mc._agent_mgr = mgr
        arth = MagicMock()
        arth.get_special_agents.return_value = {"special:coder": "Other"}
        mc._agent_runtime_handler = arth
        assert mc._resolve_agent_display_name("special:coder") == "Coder"


class TestClickHandlersGuard:
    def test_click_handlers_guard_none(self, mc):
        """Each click handler with callback set to None is a no-op (no
        AttributeError / TypeError)."""
        mc._on_agent_cycle = None
        mc._on_autoaccept_cycle = None
        mc._on_settings_clicked = None
        mc._on_agent_label_clicked("special:x")   # must not raise
        mc._on_autoaccept_label_clicked("off")    # must not raise
        mc._on_settings_btn_clicked(None)         # must not raise

    def test_click_handlers_fire_when_wired(self, mc):
        """Wired callbacks are invoked with the expected argument."""
        agent_calls = []
        auto_calls = []
        settings_calls = []
        mc.set_on_agent_cycle(lambda sk: agent_calls.append(sk))
        mc.set_on_autoaccept_cycle(lambda lvl: auto_calls.append(lvl))
        mc.set_on_settings_clicked(lambda: settings_calls.append("clicked"))

        mc._on_agent_label_clicked("special:x")
        mc._on_autoaccept_label_clicked("files")
        mc._on_settings_btn_clicked(None)

        assert agent_calls == ["special:x"]
        assert auto_calls == ["files"]
        assert settings_calls == ["clicked"]
