"""
Workflow state tracker for CrabCakes projects.

Manages .crabcakes/workflow.md — tracks which workflow phases are done,
which is current, and timestamps.

Phase names: "onboarding", "discovery", "architecture", "task-planning",
"implementation", "testing", "ship"

Usage:
    from utils.workflow_state import init_workflow, advance_phase, get_current_phase
    init_workflow("/path/to/project")
    advance_phase("/path/to/project", "discovery")
    phase = get_current_phase("/path/to/project")
"""

import os
import re
from datetime import datetime, timezone

from utils.project_awareness import get_crabcakes_dir

# ── Phase ordering ────────────────────────────────────────────────────────────

PHASES = [
    "onboarding",
    "discovery",
    "architecture",
    "task-planning",
    "implementation",
    "testing",
    "ship",
]

# Map phase name → index
_PHASE_INDEX = {name: i for i, name in enumerate(PHASES)}

# ── Phase row helpers ─────────────────────────────────────────────────────────


def _make_phase_row(
    idx: int,
    name: str,
    status: str,
    started: str,
    completed: str,
    notes: str,
) -> str:
    """Return one table row line (WITHOUT trailing newline — join handles that)."""
    return f"| {idx} | {name} | {status} | {started} | {completed} | {notes} |"


def _initial_workflow_content() -> str:
    """Return the initial workflow.md content as a single string with proper newlines."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [
        "## Phase History",
        "| # | Phase | Status | Started | Completed | Notes |",
        "|---|-------|--------|---------|-----------|-------|",
    ]
    rows += [
        _make_phase_row(i, name, "🔄 current" if i == 0 else "⏳ pending", now, "—", "...")
        for i, name in enumerate(PHASES)
    ]
    # Header lines 0-2 have no trailing newlines from _make_phase_row.
    # Join with \n so header lines get one; last line (last phase row) also gets one.
    return "\n".join(rows) + "\n"


# ── Read / write helpers ──────────────────────────────────────────────────────


def _read_workflow_lines(project_path: str) -> list[str] | None:
    """Read workflow.md as lines, stripping trailing newlines from each."""
    path = os.path.join(get_crabcakes_dir(project_path), "workflow.md")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # splitlines() strips trailing newlines from every line.
        # This is safe because _write_workflow_lines adds them back via join.
        return content.splitlines()
    except OSError:
        return None


def _write_workflow_lines(project_path: str, lines: list[str]) -> None:
    """Write lines to workflow.md, each line followed by \n (last line too)."""
    path = os.path.join(get_crabcakes_dir(project_path), "workflow.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _find_phase_line_idx(lines: list[str], phase_idx: int, phase_name: str) -> int | None:
    """Find the table row index in lines matching phase by index and name."""
    for i, line in enumerate(lines):
        m = re.match(r"\|\s*(\d+)\s*\|\s*(\w+)\s*\|", line)
        if m and int(m.group(1)) == phase_idx and m.group(2) == phase_name:
            return i
    return None


def _replace_phase_row(
    lines: list[str],
    phase_idx: int,
    phase_name: str,
    new_status: str,
    new_completed: str,
) -> list[str]:
    """Find the matching phase row and replace its status + completed columns."""
    new_lines = list(lines)
    row_idx = _find_phase_line_idx(lines, phase_idx, phase_name)
    if row_idx is None:
        return new_lines

    line = lines[row_idx].rstrip("\n")
    parts = [p.strip() for p in line.split("|")]
    # parts[0]=="" (leading |), parts[1]==idx, parts[2]==name,
    # parts[3]==status, parts[4]==started, parts[5]==completed, parts[6]==notes
    started = parts[4]
    notes = parts[6] if len(parts) > 6 else "..."
    now_str = new_completed or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_lines[row_idx] = _make_phase_row(phase_idx, phase_name, new_status, started, now_str, notes)
    return new_lines


# ── Public API ───────────────────────────────────────────────────────────────


def init_workflow(project_path: str) -> None:
    """
    Create .crabcakes/workflow.md with all phases. Onboarding is current;
    all others are pending. Safe to call on an already-initialized project.
    """
    workflow_path = os.path.join(get_crabcakes_dir(project_path), "workflow.md")
    if os.path.isfile(workflow_path):
        return
    os.makedirs(os.path.dirname(workflow_path), exist_ok=True)
    with open(workflow_path, "w", encoding="utf-8") as f:
        f.write(_initial_workflow_content())


def get_current_phase(project_path: str) -> str:
    """
    Return the name of the current (in-progress) phase.
    Returns PHASES[0] ("onboarding") if workflow.md doesn't exist.
    """
    lines = _read_workflow_lines(project_path)
    if not lines:
        return PHASES[0]

    for line in lines:
        if re.match(r"\|\s*\d+\s*\|\s*\w+\s*\|\s*🔄\s*current\s*\|", line):
            m = re.search(r"\|\s*\d+\s*\|\s*(\w+)\s*\|\s*🔄\s*current\s*\|", line)
            if m:
                return m.group(1)

    # Fallback: first non-done phase
    for name in PHASES:
        if not is_phase_done(project_path, name):
            return name
    return PHASES[-1]


def is_phase_done(project_path: str, phase_name: str) -> bool:
    """
    Return True if the named phase is marked ✅ done in workflow.md.
    Returns False if not done or if workflow.md doesn't exist.
    """
    lines = _read_workflow_lines(project_path)
    if not lines:
        return False

    phase_idx = _PHASE_INDEX.get(phase_name, -1)
    for line in lines:
        m = re.match(r"\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*✅\s*done\s*\|", line)
        if m and int(m.group(1)) == phase_idx and m.group(2) == phase_name:
            return True
    return False


def advance_phase(project_path: str, phase_name: str) -> None:
    """
    Mark the named phase as ✅ done and set the next phase to 🔄 current.

    Initializes workflow.md if it doesn't exist.
    Raises ValueError if phase_name is not a valid phase.
    """
    if phase_name not in _PHASE_INDEX:
        raise ValueError(f"Unknown phase: {phase_name!r}. Valid: {PHASES}")

    lines = _read_workflow_lines(project_path)
    if lines is None:
        init_workflow(project_path)
        lines = _read_workflow_lines(project_path)
    if lines is None:
        return

    phase_idx = _PHASE_INDEX[phase_name]
    next_idx = phase_idx + 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Mark current phase done and set next to current
    lines = _replace_phase_row(lines, phase_idx, phase_name, "✅ done", now)
    if next_idx < len(PHASES):
        next_name = PHASES[next_idx]
        lines = _replace_phase_row(lines, next_idx, next_name, "🔄 current", "—")

    _write_workflow_lines(project_path, lines)


def get_workflow_content(project_path: str) -> str:
    """
    Return the raw content of .crabcakes/workflow.md.
    Returns empty string if the file doesn't exist.
    """
    path = os.path.join(get_crabcakes_dir(project_path), "workflow.md")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
