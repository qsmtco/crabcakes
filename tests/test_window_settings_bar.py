# tests/test_window_settings_bar.py
# Window integration tests — project settings bar (SPEC ...-FIX-3 §5 Step 5,
# Phase I.5). Covers Debugger BUG #6: the token-guarded, path-keyed branch
# worker lifecycle, plus the Round 3 lifecycle/cache guarantees.
#
#   - branch scheduling on cache miss (Round 2 BUG #1/#2/#7)
#   - result discarded on token/path/active-project mismatch (BUG #2/#5)
#   - path-keyed cache hit skips scheduling (BUG #5/#6)
#   - open/close invalidate in-flight state (Round 3 BUG #1/#2)
#   - no optimistic auto-accept rebuild (Round 3 BUG #4)
#   - solo-target validation + change callback (Round 3 BUG #3)
#
# CRITICAL: GTK widget construction segfaults in this sandbox. MainWindow is
# instantiated via __new__ with mocked handlers; no real GTK widgets or real
# branch threads are ever constructed (threading.Thread is faked).

import pytest
from unittest.mock import MagicMock

from ui import window as wm
from models import AgentRoutingTable
from ui.handlers.project_handler import ProjectHandler


# ── Fakes used to avoid real GTK / real threads ─────────────────────────────


class _FakeThread:
    """Captures the worker target/args instead of running a real thread."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        """Record that the worker was started (no real OS thread spawned)."""
        self.started = True


@pytest.fixture(autouse=True)
def _fake_thread(monkeypatch):
    """Replace threading.Thread so _schedule_branch_refresh never spawns a
    real OS thread (which would try to import GTK / run get_branch)."""
    monkeypatch.setattr(
        "threading.Thread",
        lambda *args, **kwargs: _FakeThread(*args, **kwargs),
    )


class _FakeProjects:
    """Minimal projects store exposing load_projects for _get_project_path."""

    def __init__(self):
        self._projects = {}

    def save_project(self, name, path):
        self._projects[name] = path

    def load_projects(self):
        return list(self._projects.items())


@pytest.fixture
def real_ph():
    """A real ProjectHandler backed by a FakeProjects store with one project."""
    class _GLib:
        def idle_add(self, *a, **k):
            return 1

    fp = _FakeProjects()
    fp.save_project("RealProject", "/real")
    ph = ProjectHandler(
        left_panel=MagicMock(),
        projects_module=fp,
        agent_to_project=AgentRoutingTable(),
        GLib_module=_GLib(),
    )
    return ph


@pytest.fixture
def win(monkeypatch):
    """A MainWindow with mocked handlers + a fake main_content.

    All branch-worker state fields are set to their __init__ defaults and the
    four dependency handles are MagicMocks so the real method bodies execute
    without GTK/widgets/threads.
    """
    w = wm.MainWindow.__new__(wm.MainWindow)
    w._cached_branch_by_path = {}
    w._branch_request_token = 0
    w._branch_active_token = None
    w._branch_request_path = None

    ph = MagicMock()
    ph.get_active_project_path.return_value = "/a"
    ph.get_active_project_name.return_value = "A"
    ph.get_solo_target.return_value = None
    ph.get_project_members.return_value = ["m1", "m2"]
    ph.set_solo_target = MagicMock()

    fh = MagicMock()
    fh.get_auto_accept_level.return_value = "off"

    w._project_handler = ph
    w._feed_handler = fh
    w._main_content = MagicMock()
    return w


# ── Tests ────────────────────────────────────────────────────────────────────


class TestBranchWorkerScheduling:
    def test_branch_worker_scheduled_on_cache_miss(self, win):
        """Cold open (empty cache, no in-flight): a worker is scheduled and
        the request token is set (Round 2 BUG #1/#2/#7)."""
        win._on_feed_bar_update("A", 2)
        assert win._branch_active_token is not None
        assert win._branch_request_token >= 1
        assert win._branch_request_path == "/a"

    def test_cache_hit_skips_scheduling(self, win):
        """Populated path-keyed cache for the active path -> NO new worker
        is scheduled (Round 3 BUG #5/#6 — needs_resolution suppressed)."""
        win._cached_branch_by_path["/a"] = "main"
        win._branch_request_token = 0
        win._on_feed_bar_update("A", 2)
        assert win._branch_active_token is None
        assert win._branch_request_token == 0
        # And the cached branch is pushed to the bar.
        args = win._main_content.update_project_settings.call_args
        assert args[0][4] == "main"


class TestBranchResultDiscard:
    def _arm_result(self, win, token, path):
        win._branch_request_token = token
        win._branch_active_token = token
        win._branch_request_path = path
        win._cached_branch_by_path = {}

    def test_branch_result_discarded_on_token_mismatch(self, win):
        """Result for an old token (superseded) must not write the cache
        (Round 2 BUG #7)."""
        self._arm_result(win, token=1, path="/a")
        win._branch_request_token = 2  # a newer request superseded it
        win._on_branch_result(1, "/a", "A", 2, None, "off", "main")
        assert win._cached_branch_by_path == {}
        # In-flight marker still cleared so a future request can start.
        assert win._branch_active_token is None

    def test_branch_result_discarded_on_path_mismatch(self, win):
        """Result captured for path /a arriving with a different captured
        path must be discarded (BUG #2)."""
        self._arm_result(win, token=1, path="/a")
        win._branch_request_path = "/b"
        win._on_branch_result(1, "/a", "A", 2, None, "off", "main")
        assert win._cached_branch_by_path == {}

    def test_branch_result_discarded_on_active_project_mismatch(self, win):
        """Active project changed (A -> B) since scheduling: a result for A
        is discarded and must not write the cache (Round 3 BUG #2)."""
        self._arm_result(win, token=1, path="/a")
        win._project_handler.get_active_project_name.return_value = "B"
        win._project_handler.get_active_project_path.return_value = "/b"
        win._on_branch_result(1, "/a", "A", 2, None, "off", "main")
        assert win._cached_branch_by_path == {}
        # Bar must NOT have been rebuilt with A's branch.
        win._main_content.update_project_settings.assert_not_called()


class TestBranchResultAccept:
    def test_branch_result_commits_when_current(self, win):
        """All checks pass -> branch is cached by path and the bar rebuilds
        with the resolved branch (BUG #2/#5)."""
        win._branch_request_token = 1
        win._branch_active_token = 1
        win._branch_request_path = "/a"
        win._on_branch_result(1, "/a", "A", 2, None, "off", "main")
        assert win._cached_branch_by_path["/a"] == "main"
        args = win._main_content.update_project_settings.call_args
        assert args[0][0] == "A"
        assert args[0][1] == 2
        assert args[0][4] == "main"


class TestProjectLifecycleInvalidation:
    def test_project_closed_invalidates_in_flight(self, win):
        """Project close bumps the token and clears in-flight state
        (Round 3 BUG #1) — without clearing the path-keyed cache."""
        win._branch_request_token = 1
        win._branch_active_token = 1
        win._branch_request_path = "/a"
        win._cached_branch_by_path["/a"] = "main"
        win._on_project_closed("A")
        assert win._branch_request_token == 2
        assert win._branch_active_token is None
        assert win._branch_request_path is None
        # Cache persists (path-keyed reuse, BUG #5).
        assert win._cached_branch_by_path["/a"] == "main"

    def test_project_opened_retriggers_update(self, win):
        """Project open/switch invalidates in-flight state AND re-runs
        _on_feed_bar_update so the newly active project is scheduled
        (Round 4 build-time fix)."""
        win._branch_request_token = 5
        win._branch_active_token = 5
        win._branch_request_path = "/old"
        win._project_opened_path = None
        win._on_project_opened("B", "/b")
        # Token invalidated (bumped) AND the retriggered _on_feed_bar_update
        # scheduled a fresh worker for B (cache miss) — so the token advanced
        # beyond the old in-flight value.
        assert win._branch_request_token > 5
        assert win._branch_active_token is not None
        # _on_feed_bar_update was re-invoked for B.
        calls = [c.args for c in win._main_content.update_project_settings.call_args_list]
        assert calls, "open should retrigger an update_project_settings call"


class TestAutoAcceptCycle:
    def test_autoaccept_cycle_no_optimistic_rebuild(self, win):
        """_on_autoaccept_cycle_clicked calls set_auto_accept_level but does
        NOT rebuild the bar itself — the post-confirm callback handles it
        (Round 3 BUG #4)."""
        win._feed_handler = MagicMock()
        win._project_handler.get_active_project_name.return_value = "A"
        win._on_feed_bar_update = MagicMock()
        win._on_autoaccept_cycle_clicked("off")
        win._feed_handler.set_auto_accept_level.assert_called_once_with("diffs")
        win._on_feed_bar_update.assert_not_called()

    def test_autoaccept_cycle_off_to_diffs(self, win):
        """off -> diffs is the first step of the cycle."""
        win._feed_handler = MagicMock()
        win._project_handler.get_active_project_name.return_value = "A"
        win._on_autoaccept_cycle_clicked("off")
        win._feed_handler.set_auto_accept_level.assert_called_once_with("diffs")


class TestSoloValidation:
    def test_solo_target_validation_rejects_unknown_project(self, real_ph):
        """set_solo_target('nonexistent', 'x') is a no-op (Round 3 BUG #3)."""
        real_ph.set_solo_target("nonexistent", "x")
        assert "nonexistent" not in real_ph._solo_targets
        assert real_ph.get_solo_target("nonexistent") is None

    def test_solo_target_noop_on_same_value(self, real_ph):
        """Setting the same solo value again does not re-fire the callback
        (BUG #4 redundancy guard)."""
        calls = []
        real_ph.set_on_solo_target_changed(calls.append)
        real_ph.set_solo_target("RealProject", "agent:x")
        real_ph.set_solo_target("RealProject", "agent:x")  # same -> no-op
        assert real_ph.get_solo_target("RealProject") == "agent:x"
        assert calls == ["RealProject"]

    def test_solo_target_fires_callback_on_change(self, real_ph):
        """A real change fires the callback with the project name."""
        calls = []
        real_ph.set_on_solo_target_changed(calls.append)
        real_ph.set_solo_target("RealProject", "agent:x")
        assert calls == ["RealProject"]
