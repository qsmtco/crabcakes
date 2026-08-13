# tests/test_work_persistence.py
# Coverage for utils/work_persistence.py — work.json source of truth,
# generated tasks.md summary, and legacy tasks.md migration (spec §3, Phase 2).

import json
import logging
import os

import pytest

from models.work_unit import WorkUnit
from utils.work_persistence import (
    load_or_migrate_work_units,
    load_work_units,
    render_tasks_summary,
    save_work_units,
    tasks_summary_path,
    work_json_path,
    write_tasks_summary,
    SOURCE_OF_TRUTH_NOTE,
)


# ── Path helpers ─────────────────────────────────────────────────────────────

def test_work_json_path(tmp_path):
    assert work_json_path(str(tmp_path)) == os.path.join(
        str(tmp_path), ".crabcakes", "work.json"
    )


def test_tasks_summary_path(tmp_path):
    assert tasks_summary_path(str(tmp_path)) == os.path.join(
        str(tmp_path), ".crabcakes", "tasks.md"
    )


# ── JSON round-trip ──────────────────────────────────────────────────────────

def test_round_trip_preserves_all_fields(tmp_path):
    project = str(tmp_path)
    units = [
        WorkUnit(
            id="00000001",
            title="Build spec engine",
            spec_path="docs/specs/SPEC-engine.md",
            status="spec-ready",
            assigned_supervisor="special:supervisor",
            assigned_builder="special:coder",
            assigned_auditor="special:debugger",
            priority="high",
            depends_on=["00000002"],
            created_at="2026-07-31T10:00:00",
            updated_at="2026-07-31T10:05:00",
            completed_at="",
            post_mortem_path="",
            blocked_reason="",
        ),
        WorkUnit(
            id="00000002",
            title="Implement parser",
            status="draft",
            priority="low",
        ),
    ]
    save_work_units(project, units)
    loaded = load_work_units(project)

    assert [w.to_dict() for w in loaded] == [w.to_dict() for w in units]


def test_round_trip_depends_on_and_empty_strings(tmp_path):
    project = str(tmp_path)
    unit = WorkUnit(
        id="00000010",
        title="t",
        spec_path="",
        status="in-progress",
        depends_on=["00000001", "00000009"],
        created_at="",
        updated_at="",
        completed_at="",
        post_mortem_path="",
        blocked_reason="",
    )
    save_work_units(project, [unit])
    loaded = load_work_units(project)
    assert loaded[0].depends_on == ["00000001", "00000009"]
    assert loaded[0].spec_path == ""
    assert loaded[0].created_at == ""
    assert loaded[0].completed_at == ""
    assert loaded[0].post_mortem_path == ""
    assert loaded[0].blocked_reason == ""


def test_counter_advances_past_loaded_ids(tmp_path):
    project = str(tmp_path)
    save_work_units(project, [
        WorkUnit(id="00000050", title="a"),
        WorkUnit(id="00000075", title="b"),
    ])
    load_work_units(project)
    fresh = WorkUnit()  # default_factory must continue past max loaded (75)
    assert int(fresh.id) > 75


# ── Missing / invalid JSON (sad path) ────────────────────────────────────────

def test_missing_file_returns_empty_no_file_created(tmp_path):
    project = str(tmp_path)
    assert load_work_units(project) == []
    # Load must NOT create .crabcakes/ or work.json
    assert not os.path.exists(os.path.join(project, ".crabcakes", "work.json"))


def test_invalid_json_returns_empty_with_warning(tmp_path, caplog):
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        f.write("{ not valid json !!!")

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        assert load_work_units(project) == []
    assert "work.json" in caplog.text


def test_load_work_units_binary_work_json_no_crash(tmp_path, caplog):
    """Binary/non-UTF8 work.json must not crash the load path: the text-mode
    open raises UnicodeDecodeError, which is NOT a json.JSONDecodeError or
    OSError, so it escaped the handler and aborted project open.

    Regression for BUG #9 (HIGH) — sibling of the BUG #1 fix on the tasks.md
    path. errors='replace' decodes the garbage to U+FFFD chars, json.load then
    raises json.JSONDecodeError (already caught), and the function returns
    None -> caller returns [] with a logged warning (spec §3.1 'never crash
    project open').
    """
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "work.json"), "wb") as f:
        f.write(b"\x80\x81\x82")

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        assert load_work_units(project) == []  # must not raise
    assert "work.json" in caplog.text


def test_wrong_shape_missing_work_units_returns_empty(tmp_path, caplog):
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1}, f)  # no work_units key

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        assert load_work_units(project) == []


def test_wrong_shape_work_units_not_list_returns_empty(tmp_path, caplog):
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "work_units": {"00000001": {}}}, f)

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        assert load_work_units(project) == []


def test_valid_empty_store_returns_empty(tmp_path):
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "work_units": []}, f)

    assert load_work_units(project) == []


def test_malformed_record_skipped_good_records_load(tmp_path, caplog):
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    payload = {
        "version": 1,
        "work_units": [
            {"id": "00000001", "title": "good", "status": "done"},
            {"id": 123, "title": "bad type"},          # non-string id -> ValueError
            {"id": "00000003", "status": "bogus-status"},  # bad status -> ValueError
        ],
    }
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f)

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        loaded = load_work_units(project)

    assert [w.id for w in loaded] == ["00000001"]
    assert loaded[0].title == "good"
    assert "malformed" in caplog.text or "skipping" in caplog.text


# ── Atomic save / summary failure isolation ──────────────────────────────────

def test_atomic_save_summary_failure_preserves_json(tmp_path, monkeypatch, caplog):
    """work.json must be durably written BEFORE the summary; a summary
    failure must not corrupt/delete/roll back the JSON source of truth."""
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)

    # Sentinel: proves the atomic replace actually happened (sentinel replaced
    # by valid JSON), and that the JSON survived the summary failure.
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        f.write("SENTINEL")

    def boom(*args, **kwargs):
        raise ValueError("summary render exploded")

    monkeypatch.setattr("utils.work_persistence.render_tasks_summary", boom)
    unit = WorkUnit(id="00000001", title="durable", priority="high")

    with caplog.at_level(logging.ERROR, logger="utils.work_persistence"):
        save_work_units(project, [unit])

    # work.json: sentinel gone, valid JSON with our unit, no leftover .tmp
    with open(os.path.join(crab, "work.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == 1
    assert data["work_units"][0]["id"] == "00000001"
    assert not os.path.exists(os.path.join(crab, "work.json.tmp"))
    # The summary failure was logged, not swallowed silently
    assert "summary write failed" in caplog.text


def test_save_creates_crabcakes_dir(tmp_path):
    project = str(tmp_path)  # no .crabcakes yet
    save_work_units(project, [WorkUnit(id="00000001", title="x")])
    assert os.path.isfile(os.path.join(project, ".crabcakes", "work.json"))
    assert os.path.isfile(os.path.join(project, ".crabcakes", "tasks.md"))


# ── Deterministic summary ────────────────────────────────────────────────────

def test_render_tasks_summary_deterministic(tmp_path):
    units = [
        WorkUnit(id="00000002", title="B", created_at="2026-07-31T10:00:00"),
        WorkUnit(id="00000001", title="A", created_at="2026-07-30T09:00:00"),
    ]
    first = render_tasks_summary(units)
    second = render_tasks_summary(list(reversed(units)))
    assert first == second  # iterable ordering must not matter


def test_render_tasks_summary_header_and_spec_indicator():
    units = [
        WorkUnit(
            id="00000001",
            title="Has spec",
            spec_path="docs/specs/SPEC-x.md",
            status="spec-ready",
            priority="high",
        ),
        WorkUnit(id="00000002", title="No spec", status="draft", priority="low"),
    ]
    text = render_tasks_summary(units)
    assert "# Work Units" in text
    assert SOURCE_OF_TRUTH_NOTE in text
    # spec indicator distinguishes missing (⚠) vs present (✓)
    assert "⚠ no spec" in text
    assert "✓ docs/specs/SPEC-x.md" in text
    # Every unit appears with ID + title + status + priority + assignments
    for unit in units:
        assert unit.id in text
        assert unit.title in text
        assert unit.assigned_supervisor in text
        assert unit.assigned_builder in text
        assert unit.assigned_auditor in text
    # status line renders the human label (not the raw status string)
    assert "Spec Ready" in text
    assert "Draft" in text


# ── Generated-summary non-readback ───────────────────────────────────────────

def test_load_reads_only_work_json_not_tasks_md(tmp_path):
    project = str(tmp_path)
    save_work_units(project, [WorkUnit(id="00000001", title="from json")])

    # Mutate tasks.md — load_work_units must ignore it entirely
    with open(tasks_summary_path(project), "w", encoding="utf-8") as f:
        f.write("## Task 99999999: forged — 🔄 in_progress\n")
    loaded = load_work_units(project)
    assert [w.id for w in loaded] == ["00000001"]
    assert loaded[0].title == "from json"

    # Mutate again to a completely different value — still no change
    with open(tasks_summary_path(project), "w", encoding="utf-8") as f:
        f.write("garbage that is not even markdown")
    assert [w.id for w in load_work_units(project)] == ["00000001"]


# ── write_tasks_summary best-effort ─────────────────────────────────────────

def test_write_tasks_summary_creates_dir_and_file(tmp_path):
    project = str(tmp_path)
    write_tasks_summary(project, [WorkUnit(id="00000001", title="t")])
    assert os.path.isfile(tasks_summary_path(project))
    with open(tasks_summary_path(project), "r", encoding="utf-8") as f:
        assert SOURCE_OF_TRUTH_NOTE in f.read()


def test_write_tasks_summary_oserror_logged_no_raise(tmp_path, monkeypatch, caplog):
    project = str(tmp_path)

    def boom(path, content):
        raise OSError("disk full")

    monkeypatch.setattr("utils.work_persistence._atomic_write_text", boom)
    with caplog.at_level(logging.ERROR, logger="utils.work_persistence"):
        # best-effort: must NOT raise
        write_tasks_summary(project, [WorkUnit(id="00000001")])
    assert "failed to write" in caplog.text
    assert not os.path.exists(tasks_summary_path(project))


def test_write_tasks_summary_dotcrabcakes_is_file(tmp_path, caplog):
    """Corrupt project state (.crabcakes is a regular file) must not crash
    write_tasks_summary: _ensure_crabcakes_dir raises RuntimeError, which is
    logged and swallowed (spec §3.1 'never crash project open').

    Regression companion for BUG #3 — same widen to (OSError, RuntimeError).
    """
    project = str(tmp_path)
    with open(os.path.join(project, ".crabcakes"), "w", encoding="utf-8") as f:
        f.write("not a directory")

    with caplog.at_level(logging.ERROR, logger="utils.work_persistence"):
        write_tasks_summary(project, [WorkUnit(id="00000001", title="t")])  # no raise
    assert not os.path.exists(tasks_summary_path(project))


def test_save_with_dotcrabcakes_is_file(tmp_path, caplog):
    """Corrupt project state (.crabcakes is a regular file) must not crash
    save_work_units: _ensure_crabcakes_dir raises RuntimeError; log and
    return silently (spec §3.1 'never crash project open').

    Regression for BUG #3 (HIGH)."""
    project = str(tmp_path)
    with open(os.path.join(project, ".crabcakes"), "w", encoding="utf-8") as f:
        f.write("not a directory")

    with caplog.at_level(logging.ERROR, logger="utils.work_persistence"):
        save_work_units(project, [WorkUnit(id="00000001", title="t")])  # must not raise
    # Nothing could be written — .crabcakes is not a directory
    assert not os.path.exists(os.path.join(project, ".crabcakes", "work.json"))


# ── Legacy migration (spec §3.2) ─────────────────────────────────────────────

LEGACY_EXAMPLE = """## Task 00000003: File watcher core — 🔄 in_progress
- **Priority:** high
- **Assigned:** special:coder

## Task 00000004: API integration — 🚫 blocked
- **Priority:** medium
- **Notes:** waiting for credentials
"""


def _seed_tasks_md(project: str, content: str) -> None:
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab, exist_ok=True)
    with open(os.path.join(crab, "tasks.md"), "w", encoding="utf-8") as f:
        f.write(content)


def test_migrate_legacy_tasks_md(tmp_path):
    project = str(tmp_path)
    _seed_tasks_md(project, LEGACY_EXAMPLE)

    migrated = load_or_migrate_work_units(project)

    assert len(migrated) == 2
    by_id = {w.id: w for w in migrated}
    assert by_id["00000003"].title == "File watcher core"
    assert by_id["00000003"].status == "in-progress"
    assert by_id["00000003"].priority == "high"
    assert by_id["00000003"].spec_path == ""
    assert by_id["00000003"].blocked_reason == ""
    assert by_id["00000004"].title == "API integration"
    assert by_id["00000004"].status == "in-progress"
    assert by_id["00000004"].priority == "medium"
    assert by_id["00000004"].spec_path == ""
    assert by_id["00000004"].blocked_reason == "waiting for credentials"

    # work.json written
    assert os.path.isfile(os.path.join(project, ".crabcakes", "work.json"))
    # tasks.md regenerated (now carries the source-of-truth note)
    with open(os.path.join(project, ".crabcakes", "tasks.md"), "r", encoding="utf-8") as f:
        regenerated = f.read()
    assert SOURCE_OF_TRUTH_NOTE in regenerated


def test_migrate_legacy_status_mapping_all(tmp_path):
    content = (
        "## Task 00000001: p — 📝 pending\n"
        "## Task 00000002: i — 🔄 in_progress\n"
        "## Task 00000003: b — 🚫 blocked\n"
        "- **Notes:** stuck on creds\n"
        "## Task 00000004: d — ✅ done\n"
        "## Task 00000005: c — ❌ cancelled\n"
    )
    project = str(tmp_path)
    _seed_tasks_md(project, content)

    migrated = load_or_migrate_work_units(project)
    by_id = {w.id: w for w in migrated}

    assert by_id["00000001"].status == "draft"        # pending -> draft (no spec)
    assert by_id["00000002"].status == "in-progress"
    assert by_id["00000003"].status == "in-progress"  # blocked -> in-progress
    assert by_id["00000003"].blocked_reason == "stuck on creds"
    assert by_id["00000004"].status == "done"
    assert by_id["00000005"].status == "cancelled"


def test_migration_idempotent(tmp_path):
    project = str(tmp_path)
    _seed_tasks_md(project, LEGACY_EXAMPLE)

    first = load_or_migrate_work_units(project)
    second = load_or_migrate_work_units(project)

    assert len(first) == 2
    assert len(second) == 2  # no duplicates from re-migration
    assert [w.id for w in second] == [w.id for w in first]


def test_migration_no_recognizable_tasks_writes_nothing(tmp_path):
    project = str(tmp_path)
    prose = "# Random notes\n\nSome prose that is not a task.\n- **Priority:** high\n"
    _seed_tasks_md(project, prose)

    assert load_or_migrate_work_units(project) == []
    # No work.json may be written
    assert not os.path.exists(os.path.join(project, ".crabcakes", "work.json"))
    # Original tasks.md untouched
    with open(os.path.join(project, ".crabcakes", "tasks.md"), "r", encoding="utf-8") as f:
        assert f.read() == prose


def test_migration_heading_with_unparseable_body_no_crash(tmp_path):
    project = str(tmp_path)
    _seed_tasks_md(project, (
        "## Task 00000007: Weird — 🌀 mysterious_status\n"
        "this body is garbage\n"
        "| not a bullet |\n"
        "just prose\n"
    ))

    migrated = load_or_migrate_work_units(project)  # must not raise
    assert any(w.id == "00000007" for w in migrated)
    assert migrated[0].status == "draft"             # unrecognized -> draft default
    assert migrated[0].title == "Weird"


def test_migration_canceled_us_spelling(tmp_path):
    """US spelling 'canceled' (single l) in the legacy status label must map
    to the canonical legacy status 'cancelled' -> Work Unit status 'cancelled'.

    Regression for the BUG #6 test gap — the alias existed in
    _LEGACY_STATUS_ALIASES but had no covering test."""
    project = str(tmp_path)
    _seed_tasks_md(
        project,
        "## Task 00000011: US spelling — ❌ canceled\n",
    )

    migrated = load_or_migrate_work_units(project)

    assert len(migrated) == 1
    assert migrated[0].id == "00000011"
    assert migrated[0].status == "cancelled"
    assert migrated[0].title == "US spelling"


def test_load_or_migrate_binary_tasks_md_no_crash(tmp_path, caplog):
    """Binary/non-UTF8 tasks.md must not crash the legacy migration path:
    the text-mode open raises UnicodeDecodeError, which escaped the
    OSError-only handler and aborted project open.

    Regression for BUG #1 (HIGH). errors='replace' lets the garbage decode
    to U+FFFD replacement chars that the heading regex never matches, so
    the result is [] with nothing written.
    """
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "tasks.md"), "wb") as f:
        f.write(b"\x80\x81\x82\xff\xfe")

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        assert load_or_migrate_work_units(project) == []  # must not raise
    # Nothing recognizable -> nothing written (Step 3 contract)
    assert not os.path.exists(os.path.join(crab, "work.json"))
    assert os.path.isfile(os.path.join(crab, "tasks.md"))


def test_load_or_migrate_summary_valueerror_no_crash(tmp_path, monkeypatch, caplog):
    """A non-OSError (ValueError/TypeError) escaping write_tasks_summary in
    the MIGRATION path must not crash project open — the JSON was already
    durably written.

    Regression for BUG #2 (HIGH): the migration write_tasks_summary call
    had no try/except, so the raise escaped even though work.json existed.
    """
    project = str(tmp_path)
    _seed_tasks_md(project, "## Task 00000003: durable — 🔄 in_progress\n")

    def boom(*args, **kwargs):
        raise ValueError("summary render exploded in migration")

    monkeypatch.setattr("utils.work_persistence.write_tasks_summary", boom)

    with caplog.at_level(logging.ERROR, logger="utils.work_persistence"):
        migrated = load_or_migrate_work_units(project)  # must not raise

    assert [w.id for w in migrated] == ["00000003"]
    # work.json durably written BEFORE the summary — must survive
    assert os.path.isfile(os.path.join(project, ".crabcakes", "work.json"))
    with open(os.path.join(project, ".crabcakes", "work.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["work_units"][0]["id"] == "00000003"


def test_migration_valid_json_wins_over_stale_tasks_md(tmp_path):
    project = str(tmp_path)
    _seed_tasks_md(project, LEGACY_EXAMPLE)
    crab = os.path.join(project, ".crabcakes")
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "work_units": [
            {"id": "00000042", "title": "json wins", "status": "done"},
        ]}, f)

    result = load_or_migrate_work_units(project)

    assert [w.id for w in result] == ["00000042"]  # from JSON, not legacy md
    # tasks.md regenerated FROM the JSON (source-of-truth note present)
    with open(os.path.join(crab, "tasks.md"), "r", encoding="utf-8") as f:
        summary = f.read()
    assert SOURCE_OF_TRUTH_NOTE in summary
    assert "json wins" in summary
    assert "File watcher core" not in summary


def test_migration_invalid_json_does_not_migrate(tmp_path, caplog):
    project = str(tmp_path)
    crab = os.path.join(project, ".crabcakes")
    os.makedirs(crab)
    with open(os.path.join(crab, "work.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    _seed_tasks_md(project, LEGACY_EXAMPLE)

    with caplog.at_level(logging.WARNING, logger="utils.work_persistence"):
        result = load_or_migrate_work_units(project)

    # Invalid work.json must NOT trigger legacy migration over it; the
    # existing file always wins (spec §8) and the load is a safe empty.
    assert result == []
    # Original legacy tasks.md untouched (never overwritten)
    with open(os.path.join(crab, "tasks.md"), "r", encoding="utf-8") as f:
        assert f.read() == LEGACY_EXAMPLE