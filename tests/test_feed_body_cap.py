# tests/test_feed_body_cap.py
# SPEC-UI-RESPONSIVENESS-2-T2 Phase 1 (Unit D) — rendered body cap + reveal control.
#
# Origin: external live profile (Qrusher 2026-09-12) put pango text measurement at
# 60.1% of main-thread burn; 4 approval cards at 16–39 KB bodies were the worst
# offenders. The fix separates STORAGE from RENDER:
#
#   * storage: full text up to MAX_STORED_BODY (200_000) — feed.json keeps the
#     text, so copy / crabcard export / audit are lossless within that bound;
#   * render: at most RENDERED_BODY_LIMIT (2_000) chars per card, with an
#     additive `… N more characters` reveal control.
#
# GTK: this suite builds real widgets — run under
# `PYTHONDONTWRITEBYTECODE=1 xvfb-run -a python3 -m pytest tests/test_feed_body_cap.py`.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from models.feed_card import MAX_STORED_BODY, FeedCardData


def _long_body(n: int, marker: str = "") -> str:
    """Deterministic body of EXACTLY `n` characters (newlines included)."""
    unit = "line %05d: echo hello world\n"
    out = []
    total = 0
    i = 0
    while total < n:
        piece = unit % i
        out.append(piece)
        total += len(piece)
        i += 1
    text = "".join(out)[:n]
    if marker:
        text = text[: n - len(marker)] + marker
    return text


# ── Harness (mirrors tests/test_feed_handler.py MockGLib/MockFeedTab) ────────

class MockGLib:
    """GLib double that runs idle_add callbacks immediately."""

    def idle_add(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return 0


class MockFeedTab:
    def __init__(self):
        self.cards = []
        self.replaced = []

    def append_card(self, widget, card_id=None):
        self.cards.append((widget, card_id))

    prepend_card = append_card

    def remove_card(self, card_id):
        self.cards = [(w, c) for w, c in self.cards if c != card_id]

    def show_empty_state(self):
        pass

    def replace_card(self, card_id, new_widget):
        self.replaced.append((card_id, new_widget))
        for i, (w, c) in enumerate(self.cards):
            if c == card_id:
                self.cards[i] = (new_widget, card_id)
                break

    def schedule_scroll_to_bottom(self):
        pass

    def schedule_smart_scroll_to_bottom(self):
        pass

    def update_batch_bar(self, pending_count):
        pass

    def set_batch_accept_callback(self, callback):
        pass

    def update_auto_accept_state(self, active):
        pass

    def set_auto_accept_callback(self, callback):
        pass


def _make_feed_handler():
    from ui.handlers.feed_handler import FeedHandler
    h = FeedHandler(GLib=MockGLib(), on_send_to_agent=MagicMock())
    tab = MockFeedTab()
    h.set_feed_tab(tab)
    return h, tab


def _card(body: str, **overrides) -> FeedCardData:
    fields = dict(
        card_type="agent_action",
        source="agent",
        title="Coder is calling read_file",
        body=body,
        author="Coder",
        timestamp=datetime.now(timezone.utc),
        project_name="proj",
        metadata={"status": "running"},
    )
    fields.update(overrides)
    return FeedCardData(**fields)


def _walk(widget):
    """Yield every widget in the tree (pre-order)."""
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def _buttons(widget):
    from gi.repository import Gtk
    return [w for w in _walk(widget) if isinstance(w, Gtk.Button)]


def _button_by_label(widget, label):
    for btn in _buttons(widget):
        if btn.get_label() == label:
            return btn
    return None


def _body_box(card_widget):
    """The body container box: the '_body_box' seam when present, else child 1."""
    box = getattr(card_widget, "_body_box", None)
    if box is not None:
        return box
    header = card_widget.get_first_child()
    return header.get_next_sibling() if header is not None else None


def _reveal_button(card_widget):
    """The reveal control inside the body box, or None.

    Action-row buttons live outside the body box, so any button carrying the
    view's reveal CSS class found here is the reveal control.
    """
    box = _body_box(card_widget)
    if box is None:
        return None
    for btn in _buttons(box):
        if "feed-body-reveal" in btn.get_css_classes():
            return btn
    return None


# ═══════════════════════════════════════════════════════════════════
#  1. Render cap + exact hidden count + reveal retrieves the full text
# ═══════════════════════════════════════════════════════════════════

class TestRenderCapAndReveal:
    """RED on current code: the whole 22,714-char body is handed to Pango."""

    def test_oversized_render_is_capped_with_exact_hidden_count(self):
        from ui.views.feed_card import RENDERED_BODY_LIMIT, build_feed_card

        full = _long_body(22_714)
        card = _card(full)
        widget = build_feed_card(
            card, on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )

        label = widget._body_label
        assert label is not None, "fixture precondition: body seam exposed"
        shown = label.get_text()
        assert len(shown) <= RENDERED_BODY_LIMIT, (
            f"rendered body is {len(shown)} chars — must be <= {RENDERED_BODY_LIMIT}"
        )
        assert shown == full[:RENDERED_BODY_LIMIT], "the visible text must be the head"

        hidden = len(full) - RENDERED_BODY_LIMIT
        assert hidden == 20_714
        reveal = _reveal_button(widget)
        assert reveal is not None, "an oversized body must offer a reveal control"
        assert reveal.get_label() == f"… {hidden} more characters", (
            f"indicator must show the EXACT hidden count, got {reveal.get_label()!r}"
        )

        # the reveal action retrieves the FULL text in the same label
        reveal.emit("clicked")
        assert label.get_text() == full, "reveal must restore the complete body"

    def test_small_body_has_no_reveal_control(self):
        from ui.views.feed_card import RENDERED_BODY_LIMIT, build_feed_card

        short = _long_body(RENDERED_BODY_LIMIT)
        card = _card(short)
        widget = build_feed_card(
            card, on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        assert widget._body_label.get_text() == short
        assert _reveal_button(widget) is None, (
            "a body at exactly the limit must not grow a reveal control"
        )

    def test_reveal_is_sticky_for_the_same_text(self):
        from ui.views.feed_card import build_feed_card

        full = _long_body(9_000)
        card = _card(full)
        widget = build_feed_card(
            card, on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        _reveal_button(widget).emit("clicked")
        assert widget._body_label.get_text() == full

        # an update carrying the SAME text must not collapse back to truncated
        from ui.views.feed_card import update_card_in_place
        assert update_card_in_place(widget, card) is True
        assert widget._body_label.get_text() == full, (
            "sticky reveal: the same text must stay revealed across updates"
        )


# ═══════════════════════════════════════════════════════════════════
#  2. Storage is untouched by rendering
# ═══════════════════════════════════════════════════════════════════

class TestStorageUnaffectedByRender:
    def test_stored_body_unchanged_by_widget_build_and_update(self):
        h, tab = _make_feed_handler()
        full = _long_body(22_714)
        card = _card(full)
        card_id = h.add_card(card)

        stored = h.get_card(card_id)
        assert len(stored.body) == 22_714, "widget build must not touch storage"

        # in-place refresh of the same oversized body (the tool-result shape)
        h.update_card(card_id, stored)
        assert len(h.get_card(card_id).body) == 22_714, (
            "in-place update must not write the rendered/truncated text to storage"
        )
        assert h.get_card(card_id).body == full


# ═══════════════════════════════════════════════════════════════════
#  3. Approval cards: reachable pre-decision, affordance untouched
# ═══════════════════════════════════════════════════════════════════

class TestApprovalCardReachability:
    def test_approval_card_reveal_tooltip_and_reachability_pre_decision(self):
        from ui.views.feed_card import build_feed_card

        command = _long_body(22_714, marker="--data @secret.heredoc")
        card = _card(
            f"$ {command}",
            title="⚠️ Coder requests approval to run command",
            metadata={"tool_name": "exec_command",
                      "needs_approval": True,
                      "status": "pending_approval"},
        )
        widget = build_feed_card(
            card, on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )

        reveal = _reveal_button(widget)
        assert reveal is not None
        assert reveal.get_tooltip_text() == (
            "Full command text — view before approving"
        ), "pending-approval reveal must carry the review tooltip"

        # full text is reachable BEFORE deciding
        before = widget._body_label.get_text()
        reveal.emit("clicked")
        assert widget._body_label.get_text() == card.body
        assert widget._body_label.get_text().endswith("--data @secret.heredoc")
        assert len(before) <= 2000

        # Edit D: the approve/deny affordance is untouched and still actionable
        approve = _button_by_label(widget, "Approve")
        deny = _button_by_label(widget, "Deny")
        assert approve is not None and deny is not None
        assert approve.get_sensitive() and deny.get_sensitive()

        # the reveal control lives in the body box, NOT on top of the action row
        body_box = _body_box(widget)
        actions = None
        for w in _walk(widget):
            from gi.repository import Gtk
            if isinstance(w, Gtk.Box) and "feed-card-actions" in w.get_css_classes():
                actions = w
                break
        assert actions is not None, "approval cards must keep their action row"
        assert reveal not in list(_walk(actions)), (
            "the reveal control must not sit inside the action row"
        )
        assert reveal in list(_walk(body_box))


# ═══════════════════════════════════════════════════════════════════
#  4. In-place update re-evaluates truncation
# ═══════════════════════════════════════════════════════════════════

class TestInPlaceUpdateReEvaluatesTruncation:
    def test_in_place_update_resets_to_truncated_on_new_oversized_body(self):
        from ui.views.feed_card import RENDERED_BODY_LIMIT, build_feed_card

        first = _long_body(9_000)
        card = _card(first)
        widget = build_feed_card(
            card, on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        _reveal_button(widget).emit("clicked")
        assert widget._body_label.get_text() == first

        # a NEW oversized body arrives (tool result) — truncate again, fresh count
        second = _long_body(5_000, marker="END-OF-SECOND")
        card.body = second
        from ui.views.feed_card import update_card_in_place
        assert update_card_in_place(widget, card) is True

        assert widget._body_label.get_text() == second[:RENDERED_BODY_LIMIT]
        reveal = _reveal_button(widget)
        assert reveal is not None
        assert reveal.get_label() == "… 3000 more characters", (
            f"fresh hidden count expected, got {reveal.get_label()!r}"
        )
        reveal.emit("clicked")
        assert widget._body_label.get_text() == second

    def test_in_place_update_to_short_body_clears_expanded_state(self):
        from ui.views.feed_card import build_feed_card, update_card_in_place

        card = _card(_long_body(9_000))
        widget = build_feed_card(
            card, on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        _reveal_button(widget).emit("clicked")

        card.body = "read_file → 12 lines"
        assert update_card_in_place(widget, card) is True

        assert widget._body_label.get_text() == "read_file → 12 lines"
        reveal = _reveal_button(widget)
        assert reveal is None or not reveal.get_visible(), (
            "a short body must not keep a stale reveal control"
        )
        # …and no stale expanded state leaks back on the next update
        card.body = _long_body(4_000)
        assert update_card_in_place(widget, card) is True
        assert widget._body_label.get_text() == _long_body(4_000)[:2000], (
            "the reset must be real: the next oversized body starts truncated"
        )

    def test_spacer_body_oversized_update_falls_back_to_rebuild(self):
        """An empty body renders a spacer label; hosting a 22k body in it would
        skip the wrap config, so the update must rebuild instead (Edit B)."""
        h, tab = _make_feed_handler()
        card = _card("")
        card_id = h.add_card(card)
        widget = h._card_widgets[card_id]
        assert getattr(widget, "_body_label", None) is not None

        stored = h.get_card(card_id)
        stored.body = _long_body(22_714)
        h.update_card(card_id, stored)

        new_widget = h._card_widgets[card_id]
        assert new_widget is not widget, "the spacer case must fall back to rebuild"
        assert [cid for cid, _w in tab.replaced] == [card_id]
        assert len(new_widget._body_label.get_text()) == 2000


# ═══════════════════════════════════════════════════════════════════
#  5 + 6. Storage-side cap (the RED-first anchor for Edit C)
# ═══════════════════════════════════════════════════════════════════

def _make_runtime_handler(feed_handler):
    from agent.special_agents import SpecialAgentDef
    from ui.handlers.agent_runtime_handler import AgentRuntimeHandler

    class _FakeGLib:
        def idle_add(self, fn, *args, **kwargs):
            fn(*args, **kwargs)
            return 0

    rt = AgentRuntimeHandler(MagicMock(), MagicMock(), GLib_module=_FakeGLib())
    rt._fh = feed_handler
    rt._active_project = ("proj", "/tmp/proj")
    rt._agents = {
        "special:coder": SpecialAgentDef(
            conv_id_prefix="special:coder", display_name="Coder", role="coder",
            emoji="🛠️", tools=["read_file"], can_write=True,
        )
    }
    rt._pending_tool_args = {}
    rt._ended_sessions = set()
    rt._pending_exec_commands = {}
    return rt


class TestStorageCap:
    def test_tool_result_stores_full_output_not_2000(self):
        """RED anchor: today `_do_tool_call_result` stores `output[:2000]`."""
        h, _tab = _make_feed_handler()
        rt = _make_runtime_handler(h)

        card_id = h.add_card(_card("⏳ Running...",
                                   metadata={"status": "running",
                                             "tool_name": "read_file"}))
        rt._tool_card_ids["special:coder"] = card_id

        output = "O" * 5_000
        rt._do_tool_call_result("special:coder", "read_file", output, success=True)

        stored = h.get_card(card_id)
        assert len(stored.body) == 5_000, (
            f"tool-result storage still truncates: {len(stored.body)} chars stored"
        )
        assert stored.body == output

    def test_tool_result_storage_cap_200k_with_warning(self, caplog):
        h, _tab = _make_feed_handler()
        rt = _make_runtime_handler(h)

        card_id = h.add_card(_card("⏳ Running...",
                                   metadata={"status": "running",
                                             "tool_name": "read_file"}))
        rt._tool_card_ids["special:coder"] = card_id

        with caplog.at_level(logging.WARNING):
            rt._do_tool_call_result("special:coder", "read_file", "Z" * 250_000,
                                    success=True)

        stored = h.get_card(card_id)
        assert len(stored.body) == MAX_STORED_BODY == 200_000
        assert any(
            "storage" in r.getMessage().lower() and "200000" in r.getMessage().replace(",", "")
            for r in caplog.records
        ), [r.getMessage() for r in caplog.records]

    def test_model_storage_cap_applies_to_every_construction_site(self, caplog):
        """The sweep is enforced at the model, so a new `body=` site cannot
        bypass the cap (audit-report / git-stdout / crabcard paths all funnel here)."""
        with caplog.at_level(logging.WARNING):
            card = FeedCardData(
                card_type="audit_report", source="agent", title="Report",
                body="R" * 250_000, author="Debugger",
                timestamp=datetime.now(timezone.utc), project_name="proj",
            )
        assert len(card.body) == MAX_STORED_BODY
        assert any("storage" in r.getMessage().lower() for r in caplog.records)

    def test_approval_card_body_is_capped_at_storage(self):
        card = FeedCardData(
            card_type="agent_action", source="agent",
            title="⚠️ approval", body="$ " + "C" * 250_000, author="Coder",
            timestamp=datetime.now(timezone.utc), project_name="proj",
            metadata={"needs_approval": True},
        )
        assert len(card.body) == MAX_STORED_BODY


# ═══════════════════════════════════════════════════════════════════
#  7. Copy keeps the FULL stored body (Edit D)
# ═══════════════════════════════════════════════════════════════════

class TestCopyPreserved:
    def test_copy_callback_returns_full_stored_body(self):
        h, _tab = _make_feed_handler()
        copied = []
        h.handle_copy = copied.append

        full = _long_body(22_714, marker="FINAL-LINE")
        card = _card(full)
        cb = h._make_copy_cb(card)

        cb()
        assert copied == [full], "copy must carry the stored body, not the rendered text"
        assert len(copied[0]) == 22_714 and copied[0].endswith("FINAL-LINE")

    def test_copy_from_built_widget_carries_full_body(self):
        """The header copy button is built at render time — it must still hand
        over the full stored body, not the 2k slice."""
        from ui.views.feed_card import build_feed_card

        copied = []
        full = _long_body(22_714)
        widget = build_feed_card(
            _card(full), on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=copied.append,
        )
        copy_btn = None
        for btn in _buttons(widget):
            if btn.get_tooltip_text() == "Copy":
                copy_btn = btn
                break
        assert copy_btn is not None
        copy_btn.emit("clicked")
        assert copied == [full]


# ═══════════════════════════════════════════════════════════════════
#  Sweep: every other body-bearing card type is capped too
# ═══════════════════════════════════════════════════════════════════

class TestAllBodyRenderersCapped:
    @pytest.mark.parametrize("card_type", [
        "diff", "git_commit", "agent_action", "system", "audit_report",
        "unknown_type", "task",
    ])
    def test_text_and_task_renderers_are_capped(self, card_type):
        from ui.views.feed_card import build_feed_card

        widget = build_feed_card(
            _card(_long_body(6_000), card_type=card_type),
            on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        assert _reveal_button(widget) is not None, (
            f"{card_type} body must be capped and offer a reveal control"
        )
        # every rendered label in the card is bounded by the render limit
        from gi.repository import Gtk
        for label in (w for w in _walk(widget) if isinstance(w, Gtk.Label)):
            assert len(label.get_text()) <= 2000, (
                f"{card_type}: a label rendered {len(label.get_text())} chars"
            )

    def test_file_event_body_is_capped(self):
        from ui.views.feed_card import build_feed_card

        widget = build_feed_card(
            _card(_long_body(6_000), card_type="file_modified",
                  file_path="src/foo.py", author="system"),
            on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        assert _reveal_button(widget) is not None

    def test_git_commit_stdout_body_is_capped(self):
        """feed_handler._add_git_card stores raw `result.stdout` — the other
        unbounded producer found in the sweep."""
        from ui.views.feed_card import build_feed_card

        widget = build_feed_card(
            _card(_long_body(30_000), card_type="git_commit", author="PM"),
            on_review=MagicMock(), on_accept=MagicMock(),
            on_reject=MagicMock(), on_copy=MagicMock(),
        )
        reveal = _reveal_button(widget)
        assert reveal is not None
        assert reveal.get_label() == f"… {30_000 - 2000} more characters"
