# utils/work_persistence.py
# Work Unit persistence layer — .crabcakes/work.json is the source of truth;
# .crabcakes/tasks.md is a generated summary; legacy tasks.md migrates once.
#
# Spec: SPEC-TASK-SYSTEM-FULL-REDESIGN §3 (Persistence and Migration), Phase 2.
# Architecture: pure Python utility. May import models.work_unit and
# utils.project_awareness only. NO imports from ui/, gateway/, or agent/.

import json
import logging
import os
import re
from typing import Iterable

from models.work_unit import (
    WorkUnit,
    WORK_PRIORITIES,
    WORK_PRIORITY_LABELS,
    WORK_STATUS_LABELS,
    _work_init_counter,
)
from utils.project_awareness import _ensure_crabcakes_dir, get_crabcakes_dir

_logger = logging.getLogger(__name__)


# ── Format constants ─────────────────────────────────────────────────────────

WORK_JSON_FILENAME = "work.json"
TASKS_SUMMARY_FILENAME = "tasks.md"
WORK_JSON_VERSION = 1

SOURCE_OF_TRUTH_NOTE = (
    "Generated from `.crabcakes/work.json`; "
    "edit work units through `/work` commands."
)

# Legacy tasks.md section headings (spec §3.2 example):
#   ## Task 00000003: File watcher core — 🔄 in_progress
_LEGACY_TASK_HEADING_RE = re.compile(r"^##\s+Task\s+(\d+)\s*:\s*(.+)$")
_LEGACY_PRIORITY_RE = re.compile(r"^-\s*\*\*Priority:\*\*\s*(.+?)\s*$")
_LEGACY_ASSIGNED_RE = re.compile(r"^-\s*\*\*Assigned:\*\*\s*(.+?)\s*$")
_LEGACY_NOTES_RE = re.compile(r"^-\s*\*\*Notes:\*\*\s*(.+?)\s*$")

# Legacy status label (after emoji strip) -> canonical legacy status.
_LEGACY_STATUS_ALIASES = {
    "pending": "pending",
    "in_progress": "in_progress",
    "in-progress": "in_progress",
    "in progress": "in_progress",
    "blocked": "blocked",
    "done": "done",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

# Canonical legacy status -> Work Unit status (spec §3.2).
_LEGACY_TO_WORK_STATUS = {
    "pending": "draft",        # NOT spec-ready — no spec exists
    "in_progress": "in-progress",
    "blocked": "in-progress",  # + blocked_reason from Notes
    "done": "done",
    "cancelled": "cancelled",
}


# ── Path helpers ─────────────────────────────────────────────────────────────


def work_json_path(project_path: str) -> str:
    """Return <project>/.crabcakes/work.json."""
    return os.path.join(get_crabcakes_dir(project_path), WORK_JSON_FILENAME)


def tasks_summary_path(project_path: str) -> str:
    """Return <project>/.crabcakes/tasks.md."""
    return os.path.join(get_crabcakes_dir(project_path), TASKS_SUMMARY_FILENAME)


# ── Atomic writes (repo convention: .tmp + os.replace) ───────────────────────


def _atomic_write_json(path: str, payload: dict) -> None:
    """Write JSON atomically via a temp file + os.replace (crash-safe)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def _atomic_write_text(path: str, content: str) -> None:
    """Write text atomically via a temp file + os.replace (crash-safe)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


# ── Loading ──────────────────────────────────────────────────────────────────


def _load_valid_work_json(project_path: str) -> list[WorkUnit] | None:
    """Parse .crabcakes/work.json into Work Units.

    Returns the loaded list when the file parses into the versioned shape
    (possibly an empty list for a valid empty store), or None when the file
    is missing, invalid JSON, or has the wrong top-level shape. Invalid files
    are logged as warnings and never raised.
    """
    path = work_json_path(project_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("load_work_units: cannot read %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        _logger.warning(
            "load_work_units: %s top level is not an object — returning empty", path
        )
        return None
    if data.get("version") != WORK_JSON_VERSION:
        _logger.warning(
            "load_work_units: %s has unsupported version %r — returning empty",
            path,
            data.get("version"),
        )
        return None
    raw_units = data.get("work_units")
    if not isinstance(raw_units, list):
        _logger.warning(
            "load_work_units: %s 'work_units' is not a list — returning empty", path
        )
        return None

    loaded: list[WorkUnit] = []
    for index, record in enumerate(raw_units):
        try:
            loaded.append(WorkUnit.from_dict(record))
        except ValueError as e:
            # Best-effort: one bad record must not abort the whole load.
            _logger.warning(
                "load_work_units: skipping malformed record %d in %s: %s",
                index,
                path,
                e,
            )
            continue
    return loaded


def load_work_units(project_path: str) -> list[WorkUnit]:
    """Load persisted Work Units from .crabcakes/work.json.

    Missing file, invalid JSON, or a wrong top-level shape returns [] with a
    logged warning — never raises. Malformed records are skipped best-effort.

    After a successful load the module ID counter is advanced past the loaded
    IDs (via _work_init_counter) so new Work Units do not collide after a
    restart. The counter is NOT touched on the empty paths (missing/invalid/
    shape errors) — no IDs were loaded, so there is nothing to advance past.
    """
    loaded = _load_valid_work_json(project_path)
    if loaded is None:
        return []
    if loaded:
        _work_init_counter(loaded)
    return loaded


# ── Saving ───────────────────────────────────────────────────────────────────


def save_work_units(project_path: str, work_units: Iterable[WorkUnit]) -> None:
    """Persist Work Units to .crabcakes/work.json, then regenerate tasks.md.

    The JSON write is atomic (temp file + os.replace) and completes BEFORE the
    summary write. A failed summary write is logged and never corrupts or
    rolls back the JSON source of truth.

    A corrupt project state (.crabcakes is a regular file) raises RuntimeError
    from _ensure_crabcakes_dir — that is caught, logged, and the save is a
    silent no-op (spec §3.1: never crash project open).
    """
    units = list(work_units)
    try:
        _ensure_crabcakes_dir(project_path)
    except (OSError, RuntimeError) as e:
        _logger.error(
            "save_work_units: cannot prepare .crabcakes for %s: %s",
            project_path,
            e,
        )
        return
    payload = {
        "version": WORK_JSON_VERSION,
        "work_units": [w.to_dict() for w in units],
    }
    _atomic_write_json(work_json_path(project_path), payload)
    try:
        write_tasks_summary(project_path, units)
    except Exception as e:  # defensive: summary must never corrupt work.json
        _logger.error(
            "save_work_units: summary write failed at %s "
            "(work.json preserved): %s",
            tasks_summary_path(project_path),
            e,
        )


# ── Generated summary ────────────────────────────────────────────────────────


def render_tasks_summary(work_units: Iterable[WorkUnit]) -> str:
    """Render a deterministic, stable human-readable summary of every Work Unit.

    Includes ID, title, status, priority, spec indicator/path, and assignment
    fields. Sorted by created_at ascending then id — the same order as
    WorkUnitStore.list_all(). The summary is for humans only: NO
    implementation path may parse this generated output after it is written;
    .crabcakes/work.json is the source of truth.
    """
    units = sorted(work_units, key=lambda w: (w.created_at, w.id))
    parts = ["# Work Units", "", SOURCE_OF_TRUTH_NOTE]
    for w in units:
        parts.append("")
        parts.append(f"## {w.id} — {w.title}".rstrip())
        parts.append(
            f"- **Status:** {WORK_STATUS_LABELS.get(w.status, w.status)}"
        )
        parts.append(
            f"- **Priority:** {WORK_PRIORITY_LABELS.get(w.priority, w.priority)}"
        )
        if w.spec_path:
            parts.append(f"- **Spec:** ✓ {w.spec_path}")
        else:
            parts.append("- **Spec:** ⚠ no spec")
        parts.append(f"- **Supervisor:** {w.assigned_supervisor}")
        parts.append(f"- **Builder:** {w.assigned_builder}")
        parts.append(f"- **Auditor:** {w.assigned_auditor}")
        if w.blocked_reason:
            parts.append(f"- **Blocked reason:** {w.blocked_reason}")
    return "\n".join(parts) + "\n"


def write_tasks_summary(project_path: str, work_units: Iterable[WorkUnit]) -> None:
    """Render and write the generated summary to .crabcakes/tasks.md.

    Best-effort: creates .crabcakes/ if needed and logs (does not raise) on
    OSError or RuntimeError (e.g. corrupt project state where .crabcakes is
    a regular file). Never touches work.json.
    """
    content = render_tasks_summary(work_units)
    try:
        _ensure_crabcakes_dir(project_path)
        _atomic_write_text(tasks_summary_path(project_path), content)
    except (OSError, RuntimeError) as e:
        _logger.error(
            "write_tasks_summary: failed to write %s: %s",
            tasks_summary_path(project_path),
            e,
        )


# ── Legacy migration ─────────────────────────────────────────────────────────


def _split_title_status(rest: str) -> tuple[str, str]:
    """Split 'title — status' on the LAST em/en-dash or spaced-hyphen separator."""
    for sep in (" — ", " – ", " - "):
        parts = rest.rsplit(sep, 1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    return rest.strip(), ""


def _normalize_legacy_status(status_text: str) -> str:
    """Strip a leading emoji/space run from a legacy status label and canonicalize.

    Recognizes the spec §3.2 statuses by their text after the emoji.
    Returns the canonical legacy status or "" when unrecognized.
    """
    if not status_text:
        return ""
    cleaned = re.sub(r"^\W+", "", status_text, flags=re.UNICODE).strip().lower()
    return _LEGACY_STATUS_ALIASES.get(cleaned, "")


def _parse_legacy_tasks_markdown(content: str) -> list[WorkUnit]:
    """Best-effort parse of legacy .crabcakes/tasks.md into Work Units.

    Recognizes sections of the form (spec §3.2 example):

        ## Task 00000003: File watcher core — 🔄 in_progress
        - **Priority:** high
        - **Assigned:** special:coder
        - **Notes:** waiting for credentials

    Section that doesn't match the heading regex are skipped (defensive —
    never crash on arbitrary markdown). A matching heading with an
    unparseable body still yields a unit with defaults; markdown is never
    fabricated into completed work. Unrecognized statuses default to 'draft'.
    Legacy 'blocked' units get blocked_reason from Notes.
    """
    units: list[WorkUnit] = []
    current: dict | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        tid, title, status_text = current["heading"]
        status = _normalize_legacy_status(status_text)
        work_status = _LEGACY_TO_WORK_STATUS.get(status, "draft")
        priority = current.get("priority", "medium").strip().lower()
        if priority not in WORK_PRIORITIES:
            priority = "medium"
        unit = WorkUnit(
            id=str(int(tid)).zfill(8),
            title=title,
            spec_path="",
            status=work_status,
            priority=priority,
            assigned_builder=current.get("assigned", "special:coder"),
        )
        if status == "blocked" and current.get("notes"):
            unit.blocked_reason = current["notes"]
        units.append(unit)
        current = None

    for line in content.splitlines():
        stripped = line.strip()
        m = _LEGACY_TASK_HEADING_RE.match(stripped)
        if m:
            flush()
            tid, rest = m.group(1), m.group(2)
            title, status_text = _split_title_status(rest)
            current = {"heading": (tid, title, status_text)}
            continue
        if current is not None:
            pm = _LEGACY_PRIORITY_RE.match(stripped)
            if pm:
                current["priority"] = pm.group(1)
                continue
            am = _LEGACY_ASSIGNED_RE.match(stripped)
            if am:
                current["assigned"] = am.group(1)
                continue
            nm = _LEGACY_NOTES_RE.match(stripped)
            if nm:
                current["notes"] = nm.group(1)
                continue
            # Unrecognized bullet/prose in a matching section — ignored.
    flush()
    return units


def load_or_migrate_work_units(project_path: str) -> list[WorkUnit]:
    """Load the authoritative work.json, or best-effort migrate a legacy
    .crabcakes/tasks.md exactly once (spec §3.2).

    1. A valid versioned work.json is authoritative: load it, regenerate
       tasks.md from it, return the units (an existing file always wins,
       even when empty — stale tasks.md is never parsed).
    2. An absent work.json (no file) → parse legacy tasks.md best-effort;
       recognizable sections are persisted to work.json and tasks.md is
       regenerated exactly once. A present-but-invalid work.json is logged
       and returns [] WITHOUT migration (existing work.json is not assumed
       migratable; the legacy source is used only when work.json is absent).
    3. No recognizable tasks → [] and nothing is written.
    """
    json_path = work_json_path(project_path)

    # Step 1: existing, valid versioned JSON wins.
    if _load_valid_work_json(project_path) is not None:
        loaded = load_work_units(project_path)
        try:
            write_tasks_summary(project_path, loaded)
        except Exception as e:  # defensive: summary must never break project open
            _logger.error(
                "load_or_migrate_work_units: summary regenerate failed at %s "
                "(work.json preserved): %s",
                tasks_summary_path(project_path),
                e,
            )
        return loaded

    # Present but invalid → warning already logged; never migrate over it.
    if os.path.isfile(json_path):
        return []

    # Step 2: work.json absent → best-effort legacy migration.
    summary_path = tasks_summary_path(project_path)
    if not os.path.isfile(summary_path):
        return []
    try:
        with open(summary_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        _logger.warning(
            "load_or_migrate_work_units: cannot read %s: %s", summary_path, e
        )
        return []

    migrated = _parse_legacy_tasks_markdown(content)
    if not migrated:
        return []  # Step 3: nothing recognizable — write nothing.

    # Step 4: one-shot persist. work.json FIRST (original tasks.md untouched
    # until the JSON is durably written), then regenerate the summary.
    try:
        _ensure_crabcakes_dir(project_path)
        _atomic_write_json(
            json_path,
            {"version": WORK_JSON_VERSION, "work_units": [w.to_dict() for w in migrated]},
        )
    except (OSError, RuntimeError) as e:
        _logger.warning(
            "load_or_migrate_work_units: failed to persist migration to %s: %s",
            json_path,
            e,
        )
        return []
    try:
        write_tasks_summary(project_path, migrated)
    except Exception as e:  # defensive: summary must never break project open
        _logger.error(
            "load_or_migrate_work_units: summary write failed at %s "
            "(work.json preserved): %s",
            tasks_summary_path(project_path),
            e,
        )
    _work_init_counter(migrated)  # advance past migrated ids before next create
    return migrated