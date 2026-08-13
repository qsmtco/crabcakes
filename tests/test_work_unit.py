# tests/test_work_unit.py
# Coverage for models/work_unit.py — WorkUnit dataclass, WorkUnitStore,
# serialization round-trip, dependency validation, counter init.
#
# Spec: SPEC-TASK-SYSTEM-FULL-REDESIGN §2, Phase 1.

import pytest

from models.work_unit import (
    WorkUnit,
    WorkUnitStore,
    _work_init_counter,
    _work_next_id,
    _validate_dependencies,
    WORK_STATUSES,
    WORK_PRIORITIES,
)


# ── ID generation ─────────────────────────────────────────────────────────────

def test_next_id_two_distinct_zero_padded():
    first = _work_next_id()
    second = _work_next_id()
    assert first != second
    assert len(first) == 8 and first.isdigit()
    assert len(second) == 8 and second.isdigit()


def test_default_factory_advances_counter():
    a = WorkUnit()
    b = WorkUnit()
    assert a.id != b.id
    assert int(b.id) == int(a.id) + 1


def test_two_store_units_distinct_ids():
    store = WorkUnitStore()
    a = store.create(WorkUnit())
    b = store.create(WorkUnit())
    assert a.id != b.id


# ── Defaults ──────────────────────────────────────────────────────────────────

def test_all_defaults():
    w = WorkUnit()
    assert w.title == ""
    assert w.spec_path == ""
    assert w.status == "draft"
    assert w.assigned_supervisor == "special:supervisor"
    assert w.assigned_builder == "special:coder"
    assert w.assigned_auditor == "special:debugger"
    assert w.priority == "medium"
    assert w.depends_on == []
    assert w.created_at == ""
    assert w.updated_at == ""
    assert w.completed_at == ""
    assert w.post_mortem_path == ""
    assert w.blocked_reason == ""


def test_allowed_statuses_and_priorities():
    assert WORK_STATUSES == (
        "draft",
        "spec-pending",
        "spec-ready",
        "in-progress",
        "auditing",
        "done",
        "cancelled",
    )
    assert WORK_PRIORITIES == ("low", "medium", "high", "critical")


# ── to_dict / from_dict round-trip ────────────────────────────────────────────

def test_round_trip_preserves_all_fields():
    store = WorkUnitStore()
    # Seed dependencies so create() dependency validation passes.
    store.create(WorkUnit(id="00000005"))
    store.create(WorkUnit(id="00000006"))
    created = store.create(WorkUnit(
        title="Build spec engine",
        spec_path="docs/specs/SPEC-engine.md",
        status="spec-ready",
        depends_on=["00000005", "00000006"],
        priority="high",
        assigned_supervisor="special:supervisor",
        assigned_builder="special:coder",
        assigned_auditor="special:debugger",
        completed_at="2026-07-31T10:00:00",
        post_mortem_path="docs/post-mortems/2026-07-31.md",
        blocked_reason="waiting for creds",
    ))
    restored = WorkUnit.from_dict(created.to_dict())
    assert restored == created


def test_round_trip_populated_depends_on():
    w = WorkUnit(depends_on=["00000003", "00000009"])
    restored = WorkUnit.from_dict(w.to_dict())
    assert restored.depends_on == ["00000003", "00000009"]


# ── from_dict validation (sad path) ───────────────────────────────────────────

def test_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        WorkUnit.from_dict("not a dict")


def test_from_dict_non_string_field_raises():
    with pytest.raises(ValueError, match="title"):
        WorkUnit.from_dict({"id": "00000001", "title": 123})


def test_from_dict_invalid_status_raises():
    with pytest.raises(ValueError, match="status"):
        WorkUnit.from_dict({"id": "00000001", "status": "typoed"})
    with pytest.raises(ValueError, match="[sS]tatus"):
        WorkUnit.from_dict({"id": "00000001", "status": 5})


def test_from_dict_invalid_priority_raises():
    with pytest.raises(ValueError, match="priority"):
        WorkUnit.from_dict({"id": "00000001", "priority": "urgent"})
    with pytest.raises(ValueError, match="[Pp]riority"):
        WorkUnit.from_dict({"id": "00000001", "priority": 7})


def test_from_dict_accepts_valid_status_and_priority():
    w = WorkUnit.from_dict({"id": "00000001", "status": "done", "priority": "critical"})
    assert w.status == "done"
    assert w.priority == "critical"


def test_from_dict_depends_on_not_list_raises():
    with pytest.raises(ValueError, match="depends_on"):
        WorkUnit.from_dict({"id": "00000001", "depends_on": "oops"})


def test_from_dict_depends_on_non_string_raises():
    with pytest.raises(ValueError, match="depends_on"):
        WorkUnit.from_dict({"id": "00000001", "depends_on": [1, 2]})


# ── Defensive copies ──────────────────────────────────────────────────────────

def test_from_dict_defensive_copy():
    data = {"id": "00000001", "depends_on": ["00000005"]}
    w = WorkUnit.from_dict(data)
    data["depends_on"].append("00000009")
    assert w.depends_on == ["00000005"]


def test_to_dict_defensive_copy():
    w = WorkUnit(depends_on=["00000005"])
    d = w.to_dict()
    d["depends_on"].append("00000009")
    assert w.depends_on == ["00000005"]


# ── Dependency validation ─────────────────────────────────────────────────────

def test_validate_dependencies_self_reference():
    w = WorkUnit(id="00000001", depends_on=["00000001"])
    with pytest.raises(ValueError, match="itself"):
        _validate_dependencies(w, {"00000001"})


def test_validate_dependencies_unknown_id():
    w = WorkUnit(id="00000001", depends_on=["99999999"])
    with pytest.raises(ValueError, match="unknown"):
        _validate_dependencies(w, {"00000001"})


def test_validate_dependencies_accepts_known_ids():
    w = WorkUnit(id="00000001", depends_on=["00000002", "00000003"])
    _validate_dependencies(w, {"00000001", "00000002", "00000003"})


def test_create_rejects_self_dependency():
    store = WorkUnitStore()
    with pytest.raises(ValueError, match="itself"):
        store.create(WorkUnit(id="00000001", depends_on=["00000001"]))


def test_create_rejects_unknown_dependency():
    store = WorkUnitStore()
    with pytest.raises(ValueError, match="unknown"):
        store.create(WorkUnit(id="00000001", depends_on=["99999999"]))


def test_update_rejects_dependency_self_reference():
    store = WorkUnitStore()
    w = store.create(WorkUnit(title="x"))
    w.depends_on = [w.id]
    with pytest.raises(ValueError, match="itself"):
        store.update(w)


def test_update_rejects_unknown_dependency():
    store = WorkUnitStore()
    w = store.create(WorkUnit(id="00000001", title="x"))
    w.depends_on = ["99999999"]
    with pytest.raises(ValueError, match="unknown"):
        store.update(w)


# ── Store ordering ────────────────────────────────────────────────────────────

def test_list_all_sorts_by_created_at_then_id():
    store = WorkUnitStore()
    # Inject directly to control created_at precisely (create() auto-stamps).
    store._work["00000010"] = WorkUnit(id="00000010", created_at="2026-07-31T12:00:00")
    store._work["00000003"] = WorkUnit(id="00000003", created_at="2026-07-30T09:00:00")
    store._work["00000007"] = WorkUnit(id="00000007", created_at="")
    assert store.list_all() == [
        store.get("00000007"),
        store.get("00000003"),
        store.get("00000010"),
    ]


def test_list_all_empty_created_at_sorts_first():
    store = WorkUnitStore()
    store._work["00000001"] = WorkUnit(id="00000001", created_at="")
    store._work["00000002"] = WorkUnit(id="00000002", created_at="2026-07-31T00:00:00")
    assert store.list_all()[0].id == "00000001"


def test_list_all_id_tiebreaker_same_created_at():
    store = WorkUnitStore()
    store._work["00000002"] = WorkUnit(id="00000002", created_at="2026-07-31T00:00:00")
    store._work["00000001"] = WorkUnit(id="00000001", created_at="2026-07-31T00:00:00")
    ids = [w.id for w in store.list_all()]
    assert ids == ["00000001", "00000002"]


def test_list_by_status_filters():
    store = WorkUnitStore()
    store.create(WorkUnit(id="00000001", status="draft"))
    store.create(WorkUnit(id="00000002", status="done"))
    store.create(WorkUnit(id="00000003", status="done"))
    result = store.list_by_status("done")
    assert [w.id for w in result] == ["00000002", "00000003"]


# ── Store create / update / get ───────────────────────────────────────────────

def test_create_assigns_id_when_empty_and_stamps_timestamps():
    store = WorkUnitStore()
    w = store.create(WorkUnit(title="t"))
    assert w.id and len(w.id) == 8
    assert w.created_at != ""
    assert w.updated_at != ""


def test_create_keeps_explicit_id():
    store = WorkUnitStore()
    w = store.create(WorkUnit(id="00000042"))
    assert w.id == "00000042"
    assert store.get("00000042") is w


def test_create_preserves_existing_created_at():
    store = WorkUnitStore()
    w = store.create(WorkUnit(id="00000001", created_at="2026-07-29T10:00:00"))
    assert w.created_at == "2026-07-29T10:00:00"


def test_create_stamps_updated_at_when_empty_even_with_created_at():
    store = WorkUnitStore()
    w = store.create(WorkUnit(id="00000001", created_at="2026-07-29T10:00:00"))
    assert w.updated_at != ""


def test_get_missing_returns_none():
    store = WorkUnitStore()
    assert store.get("99999999") is None


def test_update_stamps_updated_at():
    store = WorkUnitStore()
    w = store.create(WorkUnit(id="00000001", created_at="2026-07-29T10:00:00"))
    w.updated_at = ""
    store.update(w)
    assert w.updated_at != ""


def test_delete_returns_bool_and_removes_only_match():
    store = WorkUnitStore()
    store.create(WorkUnit(id="00000001"))
    store.create(WorkUnit(id="00000002"))
    assert store.delete("00000001") is True
    assert store.delete("00000001") is False
    assert store.get("00000001") is None
    assert store.get("00000002") is not None


def test_replace_all_swaps_contents():
    store = WorkUnitStore()
    store.create(WorkUnit(id="00000001"))
    store.create(WorkUnit(id="00000002"))
    store.replace_all([WorkUnit(id="00000009", title="replacement")])
    assert [w.id for w in store.list_all()] == ["00000009"]
    assert store.get("00000001") is None


# ── _work_init_counter ────────────────────────────────────────────────────────

def test_init_counter_advances_past_loaded_ids():
    loaded = [WorkUnit(id="00000100"), WorkUnit(id="00000250")]
    _work_init_counter(loaded)
    assert int(_work_next_id()) == 251


def test_init_counter_ignores_unparseable_ids():
    loaded = [WorkUnit(id="not-a-number"), WorkUnit(id="00000010")]
    _work_init_counter(loaded)
    assert int(_work_next_id()) == 11


def test_singleton_reexport():
    from models import work_store, WorkUnit, WorkUnitStore
    assert work_store is not None
    assert WorkUnit is WorkUnit
    assert isinstance(work_store, WorkUnitStore)
