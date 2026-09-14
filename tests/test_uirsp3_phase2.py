# tests/test_uirsp3_phase2.py
# UIRESP3 Phase 2 — bound the idle pulse (Edit A) and drop the hidden
# progress bar from traversal (Edit B). Spec §5 Phase-2 test rows.
#
# The state machine runs in-process with the conftest fake_glib fixture
# (armed timers never fire; tests invoke the recorded 250ms callback
# directly, so no real event loop and no sleeps). FeedBar row uses a real
# Gtk.ProgressBar under xvfb. The 60 s budget row is marked slow/manual:
# it needs the live app plus a real minute — the suite stays fast and
# hermetic; the measurement is executed and reported by hand.
#
# HEADLESS: Gtk.ProgressBar needs xvfb (marked per the suite's convention).

import os
import sys
from unittest.mock import MagicMock

import gi
gi.require_version('Gtk', '4.0')  # noqa: F401 — must precede any gi.repository import

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.handlers.activity_handler import ActivityHandler
from ui.views.feedbar import FeedBar


@pytest.fixture
def handler(fake_glib):
    """ActivityHandler whose feedbar is a Mock (state machine in isolation).

    _active_session() reads main_content.get_current_session_key() — None
    here, so every _is_ui_active() gate passes and transitions land.
    """
    feedbar = MagicMock()
    h = ActivityHandler(feedbar=feedbar, main_content=MagicMock(),
                        GLib_module=fake_glib)
    return h, feedbar, fake_glib


def _enter_idle(h, fake_glib):
    """Drive the machine into idle and return the armed 250ms tick callback.

    The initial state is already 'idle', so we transition through 'reasoning'
    first — _set_state early-returns on same-state, and only a real
    transition arms the ticker.
    """
    h._set_state("reasoning", None)
    h._set_state("idle", None)
    assert fake_glib.armed, "idle must arm the status ticker"
    source_id, delay_ms, tick_cb = fake_glib.armed[-1]
    assert delay_ms == 250, "the status ticker is the 250ms source"
    return tick_cb


# ── Row 1: the idle tick terminates within budget ────────────────────────────


def test_idle_tick_terminates(handler):
    h, feedbar, fake_glib = handler
    tick_cb = _enter_idle(h, fake_glib)

    seen = []
    for i in range(60):  # far beyond the 20-tick budget
        alive = tick_cb()
        seen.append(bool(alive))

    assert seen[:19] == [True] * 19, "ticks 1..19 keep the source alive"
    assert seen[19] is False, "the 20th tick must return False (source dies)"
    assert not any(seen[20:]), "a dead source must not be re-armed by ticks"
    assert h._idle_ticks >= 20
    # Clean-exit requirement: the bar is left hidden/idle, not mid-pulse.
    feedbar.set_progress_pulse.assert_any_call(False)


def test_idle_tick_budget_is_about_five_seconds(handler):
    """20 ticks × 250 ms ≈ 5 s — the documented budget."""
    h, feedbar, fake_glib = handler
    tick_cb = _enter_idle(h, fake_glib)
    ticks_alive = 0
    while tick_cb() is True:
        ticks_alive += 1
        assert ticks_alive < 100, "runaway idle ticker — budget not enforced"
    assert ticks_alive == 19, "19 keep-alive ticks then death (≈5s at 250ms)"


# ── Row 2: the counter resets on every state transition ──────────────────────


def test_idle_ticks_reset_on_state_change(handler):
    h, feedbar, fake_glib = handler
    tick_cb = _enter_idle(h, fake_glib)

    for _ in range(25):  # exhaust the budget
        tick_cb()
    assert h._idle_ticks >= 20

    # A transition must reset the budget: leave idle and come back.
    h._set_state("reasoning", None)
    assert h._idle_ticks == 0, "_set_state must reset the counter"
    h._set_state("idle", None)
    assert h._idle_ticks == 0

    tick_cb = _enter_idle(h, fake_glib)
    assert tick_cb() is True, "a fresh idle entry gets a full pulse budget"


# ── Row 3: active states are untouched ──────────────────────────────────────


def test_active_states_unaffected(handler):
    h, feedbar, fake_glib = handler
    for state in ("reasoning", "streaming", "tool_use"):
        h._set_state(state, None)
        source_id, delay_ms, tick_cb = fake_glib.armed[-1]
        # 20 active ticks: every one re-arms (True) and drives _live_update.
        results = [tick_cb() for _ in range(20)]
        assert all(r is True for r in results), (
            f"{state}: live-update branch must keep ticking"
        )
        # _live_update's skip-gating is the behavior that must NOT change —
        # with an unchanged signature it skips the feedbar rebuild.
        # (Mock feedbar: rebuild count stays bounded by signature changes.)

    # Pulse is never touched by the active branch.
    feedbar.pulse_progress.assert_not_called()


# ── Row 4: hidden bar is OUT of traversal (not visible-but-transparent) ─────


def test_hidden_progress_bar_not_visible():
    """set_progress_hidden(True) must remove the bar from layout/render:
    visible False (traversal) AND opacity 0 (the fade), per UIRESP3 Edit B."""
    bar = FeedBar()
    bar._progress_bar.set_visible(True)  # start from a visible state

    bar.set_progress_hidden(True)
    assert bar._progress_bar.get_visible() is False, (
        "hidden bar must be invisible — opacity alone leaves it in traversal"
    )
    assert bar._progress_bar.get_opacity() == 0.0, "fade (opacity) kept"

    bar.set_progress_hidden(False)
    assert bar._progress_bar.get_visible() is True, (
        "unhiding must restore visibility as well as opacity"
    )
    assert bar._progress_bar.get_opacity() == 1.0

    # The show paths must also restore visibility (bar can be hidden when
    # they fire — e.g. idle → sending).
    bar.set_progress_hidden(True)
    bar.set_progress_fraction(0.5)
    assert bar._progress_bar.get_visible() is True, (
        "set_progress_fraction must restore visibility"
    )
    bar.set_progress_hidden(True)
    bar.set_progress_pulse(True)
    assert bar._progress_bar.get_visible() is True, (
        "set_progress_pulse(True) must restore visibility"
    )
    bar.set_progress_hidden(True)
    bar.set_progress_opacity(0.5)
    assert bar._progress_bar.get_visible() is True, (
        "set_progress_opacity(>0) must restore visibility"
    )


# ── Row 5: the §7 main-thread budget (slow/manual — live app + real minute) ──


@pytest.mark.slow
@pytest.mark.manual
def test_main_thread_idle_budget():
    """§7: main-thread CPU < 10% sustained over 60 s with the app idle.

    SLOW/MANUAL — stated reason: requires the LIVE app process (a real PID
    via --pid) and a genuine 60 s sampling window; it cannot run headless in
    CI against a fixture. Executed by hand with the committed probe:
        python3 scripts/crab_perf_probe.py --pid <pid> --duration 60
    Results are pasted in the unit report. This row SKIPS (with this reason)
    in automated runs so the suite stays green; it is discoverable via
    `pytest -m slow -m manual -rs`.
    """
    pytest.skip(
        "manual measurement row — run scripts/crab_perf_probe.py against the "
        "live app and paste the output (see module docstring)"
    )
