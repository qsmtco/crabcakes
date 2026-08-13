# tests/test_work_handler.py
# Coverage for ui/handlers/work_handler.py — Work Unit commands (spec §4),
# Phase 3. GTK-free: fake project_handler + fake agent_runtime_handler,
# real WorkUnitStore, tempfile project roots.

import os

import pytest

from models.command import Command, CommandResult
from models.work_unit import WorkUnit, WorkUnitStore
from ui.handlers.work_handler import WorkHandler


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeProjectHandler:
    """Minimal ProjectHandler stand-in exposing the APIs WorkHandler uses."""

    def __init__(self, project_name="test-proj", project_path=None, members=None):
        self._name = project_name
        self._path = project_path
        self._members = members if members is not None else []

    def get_active_project_name(self) -> str | None:
        return self._name

    def get_active_project_path(self) -> str | None:
        return self._path

    def get_project_members(self, project_name: str) -> list[str]:
        return list(self._members)


class FakeRuntimeHandler:
    """Records send_to_special_agent calls; can be told to raise."""

    def __init__(self, raise_on_send=False):
        self.calls: list[tuple[str, str]] = []
        self._raise = raise_on_send

    def send_to_special_agent(self, session_key: str, text: str) -> None:
        if self._raise:
            raise RuntimeError("boom: unknown special session")
        self.calls.append((session_key, text))


def _cmd(name="work", args=None, body="", source="project:test-proj", target=None):
    return Command(
        name=name,
        args=args or [],
        body=body,
        source_session_key=source,
        target_session_key=target,
    )


def _make_handler(
    project_name="test-proj",
    project_path=None,
    members=None,
    runtime=None,
    work_store=None,
):
    """Wire a WorkHandler with fakes and a project root directory.

    Returns (handler, store, runtime, project_dir). The runtime is the passed
    fake (or a fresh FakeRuntimeHandler). project_dir is the resolved path the
    handler is bound to (the passed project_path, or a fresh TemporaryDirectory
    when none is given).
    """
    import tempfile

    tmp = None
    if project_path is None:
        tmp = tempfile.TemporaryDirectory()
        project_path = tmp.name
    store = work_store if work_store is not None else WorkUnitStore()
    ph = FakeProjectHandler(project_name, project_path, members)
    rt = runtime if runtime is not None else FakeRuntimeHandler()
    handler = WorkHandler(project_handler=ph, work_store=store, agent_runtime_handler=rt)
    handler.load_for_project(project_path)
    return handler, store, rt, project_path


def _seed_spec(project_path, rel="docs/specs/SPEC-x.md", content="# Spec\n"):
    """Create a spec file under the project root; return its rel path."""
    full = os.path.join(project_path, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return rel


def _spec_ready_unit(store, spec_path, supervisor="special:supervisor", depends_on=None):
    """Create + return a spec-ready unit with a real spec file present."""
    unit = WorkUnit(
        title="Implement X",
        status="spec-ready",
        spec_path=spec_path,
        assigned_supervisor=supervisor,
        depends_on=depends_on or [],
    )
    store.create(unit)
    return unit


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def test_load_for_project_binds_store(tmp_path):
    """load_for_project reads persisted work.json and binds it to the store."""
    from utils.work_persistence import save_work_units

    store = WorkUnitStore()
    h = WorkHandler(project_handler=FakeProjectHandler(), work_store=store)
    # Seed via the persistence layer so disk is authoritative
    draft = WorkUnit(title="loaded", status="draft")
    store.create(draft)
    save_work_units(str(tmp_path), store.list_all())
    h.load_for_project(str(tmp_path))

    # The store contains the persisted draft (round-trip through disk)
    assert h._project_path == str(tmp_path)
    assert [w.id for w in store.list_all()] == [draft.id]


def test_close_project_clears_binding():
    store = WorkUnitStore()
    h = WorkHandler(project_handler=FakeProjectHandler(), work_store=store)
    h.load_for_project("/tmp/fake")
    assert h._project_path == "/tmp/fake"
    h.close_project()
    assert h._project_path is None
    # Store data untouched
    assert store.list_all() == []


def test_window_lifecycle_wiring_loads_on_open_closes_on_close(tmp_path):
    """Mirror the window.py wiring (SPEC §3.3, §11): set_on_project_opened →
    load_for_project(path), set_on_project_closed → close_project(). Verified
    via a fake project handler with APPEND-semantics callbacks, so multiple
    handlers can register without clobbering each other."""
    from utils.work_persistence import save_work_units

    class FakeProjectHandlerWithCallbacks:
        """Minimal ProjectHandler stand-in mirroring the window.py contract:
        set_on_* appends to a list; open_project/close_project fire all cbs."""

        def __init__(self):
            self._on_project_opened = []
            self._on_project_closed = []

        def set_on_project_opened(self, cb):
            self._on_project_opened.append(cb)

        def set_on_project_closed(self, cb):
            self._on_project_closed.append(cb)

        def open_project(self, name, path):
            for cb in self._on_project_opened:
                cb(name, path)

        def close_project(self, name):
            for cb in self._on_project_closed:
                cb(name)

    store = WorkUnitStore()
    # Seed a unit on disk so load_for_project has something to bind.
    seed = WorkUnit(title="seed", status="draft")
    store.create(seed)
    save_work_units(str(tmp_path), store.list_all())
    store.replace_all([])  # clear in-memory to prove load re-binds from disk

    wh = WorkHandler(
        project_handler=FakeProjectHandlerWithCallbacks(),
        work_store=store,
    )
    ph = FakeProjectHandlerWithCallbacks()
    # This is EXACTLY the window.py wiring block (Phase 5):
    ph.set_on_project_opened(lambda n, p: wh.load_for_project(p))
    ph.set_on_project_closed(lambda name: wh.close_project())

    # No project bound yet
    assert wh._project_path is None
    assert store.list_all() == []

    # Open → load_for_project binds the store from disk
    ph.open_project("test-proj", str(tmp_path))
    assert wh._project_path == str(tmp_path)
    assert [w.id for w in store.list_all()] == [seed.id]

    # Close → close_project releases the binding, data untouched
    ph.close_project("test-proj")
    assert wh._project_path is None
    assert [w.id for w in store.list_all()] == [seed.id]

    # Append semantics: a THIRD handler can register without clobbering work.
    opened = []
    ph.set_on_project_opened(lambda n, p: opened.append(n))
    ph.open_project("test-proj", str(tmp_path))
    assert opened == ["test-proj"]
    assert wh._project_path == str(tmp_path)  # work cb still fired


def test_project_scope_error_no_state_mutation():
    """No active project → clear error, no mutation, no crash."""
    store = WorkUnitStore()
    h = WorkHandler(project_handler=FakeProjectHandler(), work_store=store)
    # Never call load_for_project — no binding

    res = h.cmd_work(_cmd(args=["Hello", "world"]))
    assert res.handled is True
    assert res.response_text == "Open a project first."
    assert store.list_all() == []


def test_work_unknown_subcommand_becomes_title(tmp_path):
    """Master spec §4.2: /work with unrecognized first arg → draft with
    joined args (not a usage error)."""
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work(_cmd(args=["frobnicate", "the", "widget"]))
    units = store.list_all()
    assert len(units) == 1
    assert units[0].title == "frobnicate the widget"
    assert units[0].status == "draft"
    assert "Created Work Unit" in res.response_text


# ── /work create ──────────────────────────────────────────────────────────────

def test_work_create_quoted_body(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work(_cmd(body="My quoted title"))
    assert res.handled is True
    units = store.list_all()
    assert len(units) == 1
    assert units[0].title == "My quoted title"
    assert units[0].status == "draft"
    assert units[0].spec_path == ""
    assert "Created Work Unit" in res.response_text
    # Persisted under the project root
    assert os.path.isfile(os.path.join(proj, ".crabcakes", "work.json"))


def test_work_create_unquoted_args(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work(_cmd(args=["My", "unquoted", "title"]))
    units = store.list_all()
    assert len(units) == 1
    assert units[0].title == "My unquoted title"
    assert units[0].status == "draft"
    assert "Created Work Unit" in res.response_text
    # Persisted
    assert os.path.isfile(os.path.join(proj, ".crabcakes", "work.json"))


def test_work_create_empty_title_usage_error(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work(_cmd(args=[]))
    assert "Usage" in res.response_text
    assert store.list_all() == []


def test_task_legacy_creates_draft_ignores_subcommand(tmp_path):
    """/task maps ONLY to draft creation; subcommand-looking args are title."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work(_cmd(name="task", args=["start", "#1"]))
    units = store.list_all()
    assert len(units) == 1
    assert units[0].status == "draft"
    assert units[0].title == "start #1"  # title, not a subcommand
    assert "Created Work Unit" in res.response_text


# ── /work routing ─────────────────────────────────────────────────────────────

def test_work_subcommand_routing_done(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(title="t", status="in-progress", spec_path=spec)
    store.create(u)
    res = h.cmd_work(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "done"
    assert res.handled is True


def test_work_unknown_subcommand_routing_list(tmp_path):
    """A bare subcommand-like arg that IS a known subcommand routes."""
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work(_cmd(args=["list"]))
    assert res.response_text == "No work units yet."


# ── /work list ────────────────────────────────────────────────────────────────

def test_work_list_empty(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work_list(_cmd())
    assert res.response_text == "No work units yet."


def test_work_list_populated_shows_fields_and_spec(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    _seed_spec(str(tmp_path), "docs/specs/SPEC-a.md")
    u1 = WorkUnit(title="has spec", status="spec-ready", spec_path="docs/specs/SPEC-a.md")
    u2 = WorkUnit(title="no spec", status="draft")
    store.create(u1)
    store.create(u2)
    res = h.cmd_work_list(_cmd())
    assert "has spec" in res.response_text
    assert "no spec" in res.response_text
    assert "✓" in res.response_text
    assert "⚠" in res.response_text
    assert "Supervisor:" in res.response_text
    assert "Builder:" in res.response_text
    assert "Auditor:" in res.response_text


# ── /work start happy path ────────────────────────────────────────────────────

def test_work_start_happy_path(tmp_path):
    members = ["special:supervisor", "special:coder"]
    h, store, rt, proj = _make_handler(
        project_path=str(tmp_path), members=members
    )
    spec = _seed_spec(str(tmp_path))
    u = _spec_ready_unit(store, spec)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))

    assert store.get(u.id).status == "in-progress"
    assert res.handled is True
    assert f"#{u.id}" in res.response_text
    # EXACTLY ONE send, with the exact implementation-loop message
    assert len(rt.calls) == 1
    sk, text = rt.calls[0]
    assert sk == "special:supervisor"
    assert text == (
        "Load prompts/implementationLoop.md. This work unit's spec is at "
        f"{spec}. Begin the implementation loop."
    )
    # Persisted to disk
    assert os.path.isfile(os.path.join(proj, ".crabcakes", "work.json"))


def test_work_start_uses_8digit_id_without_hash(tmp_path):
    members = ["special:supervisor"]
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path), members=members)
    spec = _seed_spec(str(tmp_path))
    u = _spec_ready_unit(store, spec)
    res = h.cmd_work_start(_cmd(args=["start", u.id]))
    assert store.get(u.id).status == "in-progress"
    assert len(rt.calls) == 1


# ── /work start sad paths ─────────────────────────────────────────────────────

def test_work_start_missing_unit(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work_start(_cmd(args=["start", "#99999999"]))
    assert "not found" in res.response_text
    assert rt.calls == []


def test_work_start_missing_unit_id_usage(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work_start(_cmd(args=["start"]))
    assert "Usage" in res.response_text


def test_work_start_missing_spec_message(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="no spec", status="spec-ready", spec_path="")
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert res.response_text == f"Work unit #{u.id} has no spec. Write the spec first."
    assert rt.calls == []


def test_work_start_spec_file_missing(tmp_path):
    """spec_path non-empty but the file doesn't exist → same exact message."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="stale spec",
        status="spec-ready",
        spec_path="docs/specs/MISSING.md",
    )
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert res.response_text == f"Work unit #{u.id} has no spec. Write the spec first."
    assert rt.calls == []


def test_work_start_absolute_spec_path_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="abs", status="spec-ready", spec_path="/etc/passwd"
    )
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert "invalid" in res.response_text.lower() or "escape" in res.response_text.lower()
    assert store.get(u.id).status == "spec-ready"  # no state change
    assert rt.calls == []


def test_work_start_dotdot_traversal_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="traversal", status="spec-ready", spec_path="../../etc/passwd"
    )
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert "invalid" in res.response_text.lower() or "escape" in res.response_text.lower()
    assert rt.calls == []


def test_work_start_symlink_escape_rejected(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    # Create a symlink inside the project pointing outside
    outside = os.path.join(str(tmp_path), "..", "symlink_outside")
    os.makedirs(outside, exist_ok=True)
    os.symlink(outside, os.path.join(str(tmp_path), "escape"))
    u = WorkUnit(
        title="symlink", status="spec-ready", spec_path="escape/SPEC-x.md"
    )
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert "invalid" in res.response_text.lower() or "escape" in res.response_text.lower()
    assert store.get(u.id).status == "spec-ready"
    assert rt.calls == []


def test_work_start_unresolved_dependencies_exact_message(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    done_unit = WorkUnit(title="done dep", status="done")
    live_unit = WorkUnit(title="live dep", status="in-progress")
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(
        title="depends",
        status="spec-ready",
        spec_path=spec,
        depends_on=[live_unit.id, "00000099"],  # dangling dep allowed via replace_all
    )
    # Phase 1 _validate_dependencies blocks unknown deps at create(); seed via
    # replace_all to model a persisted unit with a now-missing dependency.
    store.replace_all([done_unit, live_unit, u])
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert res.response_text == (
        f"Work unit #{u.id} has unresolved dependencies: "
        f"#{live_unit.id} (status: in-progress), #00000099 (not found). "
        "Resolve dependencies first."
    )
    assert store.get(u.id).status == "spec-ready"  # no state change
    assert rt.calls == []


def test_work_start_wrong_status(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(title="draft unit", status="draft", spec_path=spec)
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert "must be spec-ready" in res.response_text
    assert store.get(u.id).status == "draft"
    assert rt.calls == []


def test_work_start_blocked_reason_nonempty(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(
        title="blocked", status="spec-ready", spec_path=spec,
        blocked_reason="waiting on creds",
    )
    store.create(u)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert "blocked" in res.response_text.lower()
    assert store.get(u.id).status == "spec-ready"
    assert rt.calls == []


def test_work_start_supervisor_not_in_members_exact_message(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path), members=["special:coder"])
    spec = _seed_spec(str(tmp_path))
    u = _spec_ready_unit(store, spec)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert res.response_text == "Add the Supervisor agent to begin implementation."
    assert store.get(u.id).status == "spec-ready"
    assert rt.calls == []


def test_work_start_send_raises_rolls_back(tmp_path):
    members = ["special:supervisor"]
    rt = FakeRuntimeHandler(raise_on_send=True)
    h, store, rt2, tmp = _make_handler(
        project_path=str(tmp_path), members=members, runtime=rt
    )
    spec = _seed_spec(str(tmp_path))
    u = _spec_ready_unit(store, spec)
    res = h.cmd_work_start(_cmd(args=["start", f"#{u.id}"]))
    assert store.get(u.id).status == "spec-ready"  # rolled back
    assert res.handled is True
    assert "Failed to hand off" in res.response_text  # no exception escaped


# ── BUG #14: /work start requires PM/Supervisor auth (spec §4.6) ─────────────

def test_work_start_caller_auth_required(tmp_path):
    """An unrelated project member (e.g. special:debugger) must NOT be able
    to trigger the implementation loop / Supervisor handoff."""
    members = ["special:supervisor", "special:coder", "special:debugger"]
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path), members=members)
    spec = _seed_spec(str(tmp_path))
    u = _spec_ready_unit(store, spec)
    res = h.cmd_work_start(_cmd(
        args=["start", f"#{u.id}"], source="special:debugger"
    ))
    assert store.get(u.id).status == "spec-ready"  # NOT flipped to in-progress
    assert rt.calls == []  # NO handoff fired
    assert "Only the PM or assigned Supervisor" in res.response_text


# ── /work done ────────────────────────────────────────────────────────────────

def test_work_done_happy(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(title="t", status="in-progress", spec_path=spec)
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"], source="project:test-proj"))
    assert store.get(u.id).status == "done"
    assert store.get(u.id).completed_at  # stamped
    assert "marked done" in res.response_text


def test_work_done_supervisor_authorized(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress", spec_path=spec,
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_done(_cmd(
        args=["done", f"#{u.id}"], source="special:supervisor"
    ))
    assert store.get(u.id).status == "done"
    assert res.handled is True


def test_work_done_unrelated_agent_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_done(_cmd(
        args=["done", f"#{u.id}"], source="special:debugger"
    ))
    assert store.get(u.id).status == "in-progress"
    assert "Only the PM or assigned Supervisor" in res.response_text


def test_work_done_refuses_cancelled(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="cancelled")
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "cancelled"  # not silently changed
    assert "cancelled" in res.response_text.lower()


def test_work_done_missing_unit(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    res = h.cmd_work_done(_cmd(args=["done", "#00000001"]))
    assert "not found" in res.response_text


# ── BUG #12: /work done must validate source status + spec (spec §2.1, §4.3) ─

def test_work_done_from_draft_refused(tmp_path):
    """done is only valid from in-progress or auditing (spec §4.3)."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="draft")
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "draft"
    assert store.get(u.id).completed_at == ""
    assert "in-progress" in res.response_text or "auditing" in res.response_text


def test_work_done_from_spec_ready_refused(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="spec-ready")
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "spec-ready"
    assert store.get(u.id).completed_at == ""
    assert "in-progress" in res.response_text or "auditing" in res.response_text


def test_work_done_empty_spec_path_refused(tmp_path):
    """done requires non-empty spec_path (spec §2.1)."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress", spec_path="")
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "in-progress"
    assert res.response_text == f"Work unit #{u.id} has no spec. Write the spec first."
    assert store.get(u.id).completed_at == ""


def test_work_done_missing_spec_file_refused(tmp_path):
    """done requires the spec file to exist at the project root (spec §2.1)."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress", spec_path="docs/specs/MISSING.md"
    )
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "in-progress"
    assert store.get(u.id).completed_at == ""
    assert "no spec" in res.response_text.lower() or "spec" in res.response_text.lower()


def test_work_done_happy_with_spec_present(tmp_path):
    """done from in-progress WITH a real spec file succeeds (regression guard)."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(title="t", status="in-progress", spec_path=spec)
    store.create(u)
    res = h.cmd_work_done(_cmd(args=["done", f"#{u.id}"]))
    assert store.get(u.id).status == "done"
    assert store.get(u.id).completed_at
    assert "marked done" in res.response_text


# ── /work blocked ─────────────────────────────────────────────────────────────

def test_work_blocked_requires_reason(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    res = h.cmd_work_blocked(_cmd(args=["blocked", f"#{u.id}"]))
    assert "reason required" in res.response_text.lower()
    assert store.get(u.id).blocked_reason == ""


def test_work_blocked_sets_in_progress_and_reason_not_blocked_status(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="spec-ready")
    store.create(u)
    res = h.cmd_work_blocked(_cmd(args=["blocked", f"#{u.id}"], body="waiting on creds"))
    assert store.get(u.id).status == "in-progress"  # NOT a "blocked" status
    assert store.get(u.id).blocked_reason == "waiting on creds"
    assert "in-progress" in res.response_text


def test_work_blocked_reason_from_args(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    res = h.cmd_work_blocked(_cmd(args=["blocked", f"#{u.id}", "waiting", "on", "creds"]))
    assert store.get(u.id).blocked_reason == "waiting on creds"
    assert res.handled is True


# ── BUG #13: /work blocked requires PM/Supervisor auth (spec §4.6) ───────────

def test_work_blocked_unrelated_agent_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="spec-ready",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_blocked(_cmd(
        args=["blocked", f"#{u.id}"], body="stuck", source="special:debugger"
    ))
    assert store.get(u.id).status == "spec-ready"  # no state change
    assert store.get(u.id).blocked_reason == ""
    assert "Only the PM or assigned Supervisor" in res.response_text


# ── /work unblock ─────────────────────────────────────────────────────────────

def test_work_unblock_spec_exists_restores_spec_ready(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress", spec_path=spec,
        blocked_reason="stuck",
    )
    store.create(u)
    res = h.cmd_work_unblock(_cmd(args=["unblock", f"#{u.id}"]))
    assert store.get(u.id).status == "spec-ready"
    assert store.get(u.id).blocked_reason == ""
    assert "spec-ready" in res.response_text


def test_work_unblock_spec_missing_reverts_to_draft_exact_message(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress",
        spec_path="docs/specs/REMOVED.md",
        blocked_reason="stuck",
    )
    store.create(u)
    res = h.cmd_work_unblock(_cmd(args=["unblock", f"#{u.id}"]))
    assert store.get(u.id).status == "draft"
    assert store.get(u.id).blocked_reason == ""
    assert res.response_text == "Spec file no longer exists. Work unit reverted to draft."


def test_work_unblock_spec_empty_reverts_to_draft(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress", spec_path="", blocked_reason="stuck",
    )
    store.create(u)
    res = h.cmd_work_unblock(_cmd(args=["unblock", f"#{u.id}"]))
    assert store.get(u.id).status == "draft"
    assert res.response_text == "Spec file no longer exists. Work unit reverted to draft."


def test_work_unblock_other_state_refused(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="done")
    store.create(u)
    res = h.cmd_work_unblock(_cmd(args=["unblock", f"#{u.id}"]))
    assert "not blocked" in res.response_text.lower() or "not blocked" in res.response_text
    assert store.get(u.id).status == "done"


def test_work_unblock_unrelated_agent_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress",
        spec_path="docs/specs/SPEC-x.md",
        blocked_reason="stuck",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_unblock(_cmd(
        args=["unblock", f"#{u.id}"], source="special:debugger"
    ))
    assert store.get(u.id).status == "in-progress"
    assert "Only the PM or assigned Supervisor" in res.response_text


# ── /work cancel ──────────────────────────────────────────────────────────────

def test_work_cancel_pm_ok(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_cancel(_cmd(args=["cancel", f"#{u.id}"], source="project:test-proj"))
    assert store.get(u.id).status == "cancelled"
    assert res.handled is True


def test_work_cancel_pm_via_team_pm_id(tmp_path):
    import json

    from utils.project_awareness import get_crabcakes_dir
    from models.team import ProjectTeam
    from utils.project_awareness import save_team

    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    save_team(str(tmp_path), ProjectTeam(pm_id="pm-42"))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_cancel(_cmd(args=["cancel", f"#{u.id}"], source="pm-42"))
    assert store.get(u.id).status == "cancelled"
    assert res.handled is True


def test_work_cancel_non_pm_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_cancel(_cmd(
        args=["cancel", f"#{u.id}"], source="special:supervisor"
    ))
    assert store.get(u.id).status == "in-progress"
    assert "Only the PM" in res.response_text


def test_work_cancel_done_refused(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="done")
    store.create(u)
    res = h.cmd_work_cancel(_cmd(args=["cancel", f"#{u.id}"], source="project:test-proj"))
    assert store.get(u.id).status == "done"
    assert "cannot be cancelled" in res.response_text.lower()


# ── /work assign ──────────────────────────────────────────────────────────────

def test_work_assign_supervisor_by_mention(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    # raw @supervisor mention (no resolved session key in this fake)
    res = h.cmd_work_assign(_cmd(args=["assign", f"#{u.id}", "@supervisor"]))
    assert store.get(u.id).assigned_supervisor == "supervisor"
    assert res.handled is True
    # exactly one field changed
    assert store.get(u.id).assigned_builder == "special:coder"
    assert store.get(u.id).assigned_auditor == "special:debugger"


def test_work_assign_builder_by_target_session(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    res = h.cmd_work_assign(_cmd(
        args=["assign", f"#{u.id}", "special:coder"],
        target="special:coder",
    ))
    assert store.get(u.id).assigned_builder == "special:coder"
    assert res.handled is True


def test_work_assign_ambiguous_returns_error(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    # No @mention, no resolved target → cannot determine role
    res = h.cmd_work_assign(_cmd(args=["assign", f"#{u.id}", "someone"]))
    assert "Cannot determine assignment role" in res.response_text
    assert store.get(u.id).assigned_supervisor == "special:supervisor"


# ── BUG #13: /work assign requires PM/Supervisor auth (spec §4.6) ────────────

def test_work_assign_unrelated_agent_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_assign(_cmd(
        args=["assign", f"#{u.id}", "@supervisor"],
        source="special:debugger",
    ))
    assert store.get(u.id).assigned_supervisor == "special:supervisor"  # no change
    assert store.get(u.id).assigned_builder == "special:coder"
    assert "Only the PM or assigned Supervisor" in res.response_text


# ── BUG #16: conflicting target_session_key + @mention must not mix ──────────

def test_work_assign_conflicting_target_and_mention(tmp_path):
    """When both a resolved target session and a raw @mention are present,
    prefer the resolved target for BOTH role and value — never store a role
    derived from one and a value from the other (inconsistent state)."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    # @mention says supervisor, resolved target is special:coder.
    # target_session_key wins for both role and value.
    res = h.cmd_work_assign(_cmd(
        args=["assign", f"#{u.id}", "@supervisor"],
        target="special:coder",
    ))
    unit = store.get(u.id)
    # special:coder maps to builder — so value special:coder + role supervisor
    # would be the bug. Correct: prefer target session → role from session.
    assert res.handled is True
    # (special:coder is the default builder; target-session-first means it
    # maps to builder role, NOT supervisor.)
    assert unit.assigned_builder == "special:coder"
    assert unit.assigned_supervisor == "special:supervisor"


# ── BUG #18: target session present but matches no role must REFUSE ─────────

def test_work_assign_target_no_role_match_refused(tmp_path):
    """When a resolved target_session_key is present but does NOT match any
    current assignment field (supervisor/builder/auditor), the code must NOT
    fall back to the raw @mention token for the role while keeping the target
    as the value — that reintroduces BUG #16's role/value mismatch. Refuse
    instead, leaving all assignment fields unchanged."""
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t")
    store.create(u)
    before = {
        "supervisor": u.assigned_supervisor,
        "builder": u.assigned_builder,
        "auditor": u.assigned_auditor,
    }
    # target_session_key='special:outsider' matches no assignment field;
    # raw @mention says '@supervisor'. The old code would store
    # assigned_supervisor='special:outsider' (value) with role='supervisor'
    # (token) — the inconsistency. Now it must refuse.
    res = h.cmd_work_assign(_cmd(
        args=["assign", f"#{u.id}", "@supervisor"],
        target="special:outsider",
    ))
    assert "Cannot determine assignment role" in res.response_text
    unit = store.get(u.id)
    # NO state change
    assert unit.assigned_supervisor == before["supervisor"]
    assert unit.assigned_builder == before["builder"]
    assert unit.assigned_auditor == before["auditor"]


# ── /work priority ────────────────────────────────────────────────────────────

def test_work_priority_valid(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", priority="medium")
    store.create(u)
    res = h.cmd_work_priority(_cmd(args=["priority", f"#{u.id}", "high"]))
    assert store.get(u.id).priority == "high"
    assert "High" in res.response_text


def test_work_priority_invalid(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", priority="medium")
    store.create(u)
    res = h.cmd_work_priority(_cmd(args=["priority", f"#{u.id}", "ultra"]))
    assert "Invalid priority" in res.response_text
    assert store.get(u.id).priority == "medium"


# ── BUG #13: /work priority requires PM/Supervisor auth (spec §4.6) ──────────

def test_work_priority_unrelated_agent_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", priority="medium",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_priority(_cmd(
        args=["priority", f"#{u.id}", "high"], source="special:debugger"
    ))
    assert store.get(u.id).priority == "medium"  # no state change
    assert "Only the PM or assigned Supervisor" in res.response_text


# ── /work spec-ready ──────────────────────────────────────────────────────────

def test_work_spec_ready_draft_to_ready(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path), members=["special:supervisor"])
    spec = _seed_spec(str(tmp_path), "docs/specs/SPEC-y.md")
    u = WorkUnit(title="t", status="draft", spec_path=spec)
    store.create(u)
    res = h.cmd_work_spec_ready(_cmd(args=["spec-ready", f"#{u.id}"]))
    assert store.get(u.id).status == "spec-ready"
    assert res.handled is True


def test_work_spec_ready_spec_pending_to_ready(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path), members=["special:supervisor"])
    spec = _seed_spec(str(tmp_path), "docs/specs/SPEC-z.md")
    u = WorkUnit(title="t", status="spec-pending", spec_path=spec)
    store.create(u)
    res = h.cmd_work_spec_ready(_cmd(args=["spec-ready", f"#{u.id}"]))
    assert store.get(u.id).status == "spec-ready"
    assert res.handled is True


def test_work_spec_ready_missing_spec_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="draft", spec_path="docs/specs/NOPE.md")
    store.create(u)
    res = h.cmd_work_spec_ready(_cmd(args=["spec-ready", f"#{u.id}"]))
    assert "Spec file not found" in res.response_text
    assert store.get(u.id).status == "draft"


def test_work_spec_ready_traversal_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="draft", spec_path="../../etc/passwd")
    store.create(u)
    res = h.cmd_work_spec_ready(_cmd(args=["spec-ready", f"#{u.id}"]))
    assert "invalid" in res.response_text.lower() or "escape" in res.response_text.lower()
    assert store.get(u.id).status == "draft"


def test_work_spec_ready_supervisor_not_in_team_warns_not_refuses(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path), members=["special:coder"])
    spec = _seed_spec(str(tmp_path), "docs/specs/SPEC-w.md")
    u = WorkUnit(title="t", status="draft", spec_path=spec)
    store.create(u)
    res = h.cmd_work_spec_ready(_cmd(args=["spec-ready", f"#{u.id}"]))
    assert store.get(u.id).status == "spec-ready"  # marked ready
    assert "Supervisor is not in the project team" in res.response_text
    assert "Add Supervisor before /work start" in res.response_text


def test_work_spec_ready_wrong_source_status_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    spec = _seed_spec(str(tmp_path), "docs/specs/SPEC-v.md")
    u = WorkUnit(title="t", status="in-progress", spec_path=spec)
    store.create(u)
    res = h.cmd_work_spec_ready(_cmd(args=["spec-ready", f"#{u.id}"]))
    assert "only draft or spec-pending" in res.response_text
    assert store.get(u.id).status == "in-progress"


# ── /work status transition table (spec §4.3) ─────────────────────────────────

def test_status_draft_from_spec_ready(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="spec-ready")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "draft"]))
    assert store.get(u.id).status == "draft"
    assert res.handled is True


def test_status_spec_pending_from_draft(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="draft")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "spec-pending"]))
    assert store.get(u.id).status == "spec-pending"
    assert res.handled is True


def test_status_spec_pending_from_non_draft_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "spec-pending"]))
    assert "Only draft units" in res.response_text
    assert store.get(u.id).status == "in-progress"


def test_status_auditing_from_in_progress_supervisor_only(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_status(_cmd(
        args=["status", f"#{u.id}", "auditing"], source="special:supervisor"
    ))
    assert store.get(u.id).status == "auditing"
    assert res.handled is True


def test_status_auditing_pm_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="in-progress",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "auditing"]))
    assert "Only the assigned Supervisor" in res.response_text
    assert store.get(u.id).status == "in-progress"


def test_status_auditing_from_wrong_status(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(
        title="t", status="draft",
        assigned_supervisor="special:supervisor",
    )
    store.create(u)
    res = h.cmd_work_status(_cmd(
        args=["status", f"#{u.id}", "auditing"], source="special:supervisor"
    ))
    assert "Only in-progress units" in res.response_text
    assert store.get(u.id).status == "draft"


def test_status_cancelled_pm_only(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "cancelled"]))
    assert store.get(u.id).status == "cancelled"
    assert res.handled is True


def test_status_cancelled_non_pm_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_status(_cmd(
        args=["status", f"#{u.id}", "cancelled"], source="special:supervisor"
    ))
    assert store.get(u.id).status == "in-progress"
    assert "Only the PM" in res.response_text


def test_status_spec_ready_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="draft")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "spec-ready"]))
    assert "Use /work spec-ready #N" in res.response_text
    assert store.get(u.id).status == "draft"


def test_status_in_progress_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="spec-ready")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "in-progress"]))
    assert "Use /work start #N" in res.response_text
    assert store.get(u.id).status == "spec-ready"


def test_status_done_rejected(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="in-progress")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "done"]))
    assert "Use /work done #N" in res.response_text
    assert store.get(u.id).status == "in-progress"


def test_status_unrelated_agent_denied(tmp_path):
    h, store, rt, tmp = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="spec-ready")
    store.create(u)
    res = h.cmd_work_status(_cmd(
        args=["status", f"#{u.id}", "draft"], source="special:debugger"
    ))
    assert store.get(u.id).status == "spec-ready"
    assert "Only the PM or assigned Supervisor" in res.response_text


def test_status_unknown_requested_status_usage(tmp_path):
    h, store, rt, proj = _make_handler(project_path=str(tmp_path))
    u = WorkUnit(title="t", status="draft")
    store.create(u)
    res = h.cmd_work_status(_cmd(args=["status", f"#{u.id}", "bogus"]))
    assert "Usage: /work status" in res.response_text
    assert store.get(u.id).status == "draft"