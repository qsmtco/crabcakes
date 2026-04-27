# utils/project_awareness.py
# Project awareness system — manages .crabcakes/ directory per project.
#
# Manifest:
#   - Reads: .crabcakes/* (project.md, team.json, context.md, awareness.json)
#   - Reads: git state via utils/git_ops.py
#   - Reads: package.json, pyproject.toml, etc. for tech stack detection
#   - Writes: .crabcakes/* (team.json, awareness.json, context.md)
#   - No GTK, no network, no secrets
#
# Architecture: pure Python utility. No imports from ui/, agent/, gateway/.
# File I/O only — reads/writes within the project's .crabcakes/ directory.
#
# Public API:
#   get_crabcakes_dir(project_path) -> str
#   init_project_config(project_path, project_name, pm_name, pm_id) -> None
#   load_project_manifest(project_path) -> str | None
#   load_team(project_path) -> ProjectTeam
#   save_team(project_path, team) -> None
#   load_project_context(project_path) -> str
#   save_project_context(project_path, content) -> None
#   build_awareness_snapshot(project_path, task_store) -> dict
#   save_awareness_snapshot(project_path, snapshot) -> None
#   is_project_onboarded(project_path) -> bool
#   build_awareness_block(project_path, task_store) -> str
#   detect_tech_stack(project_path) -> list[str]
#   generate_project_skeleton(project_path, project_name) -> None

import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.task import TaskStore

from models.team import ProjectTeam, TeamMember
from utils.config import get_projects_config_dir

_logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

CRABCAKES_DIR_NAME = ".crabcakes"
MANIFEST_FILENAME = "project.md"
TEAM_FILENAME = "team.json"
AWARENESS_FILENAME = "awareness.json"
CONTEXT_FILENAME = "context.md"

MAX_CONTEXT_SIZE = 50 * 1024  # 50 KB cap for context.md


# ── Path helpers ─────────────────────────────────────────────────────────────


def get_crabcakes_dir(project_path: str) -> str:
    """Return the .crabcakes/ directory path for a project."""
    return os.path.join(project_path, CRABCAKES_DIR_NAME)


def _ensure_crabcakes_dir(project_path: str) -> str:
    """Create .crabcakes/ directory if it doesn't exist. Returns the path.
    Raises RuntimeError if .crabcakes exists as a file (not a directory).
    """
    d = get_crabcakes_dir(project_path)
    if os.path.isfile(d):
        raise RuntimeError(
            f"Cannot create .crabcakes/ directory: "
            f"a file named '.crabcakes' already exists at {project_path}"
        )
    os.makedirs(d, exist_ok=True)
    return d


# ── Initialization ───────────────────────────────────────────────────────────


def init_project_config(
    project_path: str,
    project_name: str = "",
    pm_name: str = "",
    pm_id: str = "",
) -> None:
    """
    Initialize .crabcakes/ for a project. Creates directory and skeleton files.

    Migration logic:
      1. If .crabcakes/ exists → do nothing (already initialized)
      2. If crabcakes.md at project root → copy to .crabcakes/project.md
      3. If legacy members.json in ~/.config/crabcakes/projects/<name>/ → migrate
      4. Otherwise → generate skeleton
    """
    crab_dir = get_crabcakes_dir(project_path)
    # Guard: .crabcakes must not be a file
    if os.path.isfile(crab_dir):
        raise RuntimeError(
            f"Cannot create .crabcakes/ directory: "
            f"a file named '.crabcakes' already exists at {project_path}"
        )
    if os.path.isdir(crab_dir):
        # Already initialized — check team.json exists
        team_path = os.path.join(crab_dir, TEAM_FILENAME)
        if os.path.isfile(team_path):
            return
        # team.json missing — might be partial init, create it
        team = _migrate_or_empty_team(project_path, project_name, pm_name, pm_id)
        save_team(project_path, team)
        return

    _ensure_crabcakes_dir(project_path)

    # Migrate or create project.md
    manifest_path = os.path.join(crab_dir, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        _migrate_or_create_manifest(project_path, project_name)

    # Migrate or create team.json
    team = _migrate_or_empty_team(project_path, project_name, pm_name, pm_id)
    save_team(project_path, team)

    # Create empty context.md
    context_path = os.path.join(crab_dir, CONTEXT_FILENAME)
    if not os.path.isfile(context_path):
        with open(context_path, "w", encoding="utf-8") as f:
            f.write("")

    # Create initial awareness.json
    snapshot = build_awareness_snapshot(project_path)
    save_awareness_snapshot(project_path, snapshot)


def _migrate_or_empty_team(
    project_path: str,
    project_name: str,
    pm_name: str = "",
    pm_id: str = "",
) -> ProjectTeam:
    """
    Try to migrate from legacy members.json. Fall back to empty team.
    """
    # Try legacy path: ~/.config/crabcakes/projects/<name>/members.json
    if project_name:
        legacy_dir = os.path.join(get_projects_config_dir(), project_name)
        legacy_path = os.path.join(legacy_dir, "members.json")
        if os.path.isfile(legacy_path):
            try:
                with open(legacy_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    members = []
                    for sk in raw:
                        if isinstance(sk, str) and sk:
                            members.append(TeamMember(
                                session_key=sk,
                                name="",  # name unknown at migration time
                                role="",
                                can_write=False,
                            ))
                    return ProjectTeam(
                        members=members,
                        pm_name=pm_name,
                        pm_id=pm_id,
                    )
            except (json.JSONDecodeError, OSError):
                pass

    return ProjectTeam(pm_name=pm_name, pm_id=pm_id)


def _migrate_or_create_manifest(project_path: str, project_name: str) -> None:
    """
    Try to migrate crabcakes.md from project root. Generate skeleton if not found.
    """
    # Check for old crabcakes.md at project root
    old_path = os.path.join(project_path, "crabcakes.md")
    new_path = os.path.join(get_crabcakes_dir(project_path), MANIFEST_FILENAME)

    if os.path.isfile(old_path):
        try:
            with open(old_path, "r", encoding="utf-8") as f:
                content = f.read()
            with open(new_path, "w", encoding="utf-8") as f:
                f.write(content)
            return
        except OSError:
            pass

    # Generate skeleton
    generate_project_skeleton(project_path, project_name)


def generate_project_skeleton(project_path: str, project_name: str) -> None:
    """
    Create .crabcakes/project.md with a basic structure.
    """
    name = project_name or os.path.basename(project_path)
    crab_dir = _ensure_crabcakes_dir(project_path)
    manifest_path = os.path.join(crab_dir, MANIFEST_FILENAME)

    skeleton = f"""# {name}

## Purpose
<!-- Describe what this project does and why it exists. -->

## Stack
<!-- List languages, frameworks, key dependencies. -->
<!-- Detected: {', '.join(detect_tech_stack(project_path)) or 'unknown'} -->

## Entry Points
<!-- Main files and modules. -->

## Conventions
<!-- Tests: how to run them. Lint: how to check. Style: formatting rules. -->

## Notes
<!-- Any project-specific context. -->
"""
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(skeleton)


# ── Manifest ─────────────────────────────────────────────────────────────────


def load_project_manifest(project_path: str) -> str | None:
    """
    Read .crabcakes/project.md. Returns raw markdown, or None if not found.
    """
    path = os.path.join(get_crabcakes_dir(project_path), MANIFEST_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def is_project_onboarded(project_path: str) -> bool:
    """True if project has been onboarded (has real content in project.md or context.md).

    Detection: strip HTML comments from project.md. If no content lines remain
    beyond section headers, and context.md is empty, the project hasn't been onboarded.
    """
    manifest = load_project_manifest(project_path)
    if manifest is None:
        return False
    # Strip HTML comments — if nothing remains, it's still a skeleton
    stripped = re.sub(r'<!--.*?-->', '', manifest, flags=re.DOTALL).strip()
    # Check for any real content beyond section headers
    content_lines = [l for l in stripped.split('\n') if l.strip() and not l.startswith('#')]
    if content_lines:
        return True
    # Also check context.md
    context = load_project_context(project_path)
    return bool(context.strip())


# ── Team ──────────────────────────────────────────────────────────────────────


def load_team(project_path: str) -> ProjectTeam:
    """
    Read .crabcakes/team.json. Returns empty ProjectTeam if not found.
    """
    path = os.path.join(get_crabcakes_dir(project_path), TEAM_FILENAME)
    if not os.path.isfile(path):
        return ProjectTeam()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ProjectTeam.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return ProjectTeam()


def save_team(project_path: str, team: ProjectTeam) -> None:
    """
    Write ProjectTeam to .crabcakes/team.json.
    Logs error instead of raising on I/O failure.
    """
    try:
        _ensure_crabcakes_dir(project_path)
        path = os.path.join(get_crabcakes_dir(project_path), TEAM_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(team.to_dict(), f, indent=2)
    except OSError as e:
        _logger.error("save_team: failed to write team.json at %s: %s", project_path, e)


# ── Context memory ────────────────────────────────────────────────────────────


def load_project_context(project_path: str) -> str:
    """
    Read .crabcakes/context.md. Returns empty string if not found.
    """
    path = os.path.join(get_crabcakes_dir(project_path), CONTEXT_FILENAME)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def save_project_context(project_path: str, content: str) -> None:
    """
    Write content to .crabcakes/context.md. Enforces 50KB cap by truncating
    oldest content (from the top) if exceeded.
    Logs error instead of raising on I/O failure.
    """
    try:
        _ensure_crabcakes_dir(project_path)
        path = os.path.join(get_crabcakes_dir(project_path), CONTEXT_FILENAME)

        # Enforce size cap — trim from top (oldest content)
        if len(content) > MAX_CONTEXT_SIZE:
            content = content[len(content) - MAX_CONTEXT_SIZE:]

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        _logger.error("save_project_context: failed at %s: %s", project_path, e)


def append_project_context(project_path: str, entry: str) -> None:
    """
    Append an entry to .crabcakes/context.md. Adds separator if file has content.
    """
    existing = load_project_context(project_path)
    separator = "\n\n" if existing.strip() else ""
    save_project_context(project_path, existing + separator + entry)


# ── Awareness snapshot ────────────────────────────────────────────────────────


def build_awareness_snapshot(
    project_path: str,
    task_store: "TaskStore | None" = None,
) -> dict:
    """
    Build the awareness.json dict from live state.
    Gathers: git state, task summary, team size, tech stack, review mode.
    """
    # Git state
    git_info = _get_git_info(project_path)

    # Task summary
    task_info = _get_task_info(task_store)

    # Team info
    team = load_team(project_path)

    # Tech stack
    tech_stack = detect_tech_stack(project_path)

    return {
        "project_name": os.path.basename(project_path),
        "project_path": project_path,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": git_info,
        "tasks": task_info,
        "team_size": len(team.members),
        "review_mode": "off",  # updated by ReviewHandler when review starts
        "tech_stack": tech_stack,
    }


def save_awareness_snapshot(project_path: str, snapshot: dict) -> None:
    """Write awareness.json. Logs error instead of raising on I/O failure."""
    try:
        _ensure_crabcakes_dir(project_path)
        path = os.path.join(get_crabcakes_dir(project_path), AWARENESS_FILENAME)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except OSError as e:
        _logger.error("save_awareness_snapshot: failed at %s: %s", project_path, e)


def _get_git_info(project_path: str) -> dict:
    """Extract git state for awareness snapshot."""
    try:
        from utils.git_ops import get_head_sha, get_branch, log, status

        sha_result = get_head_sha(project_path)
        if not sha_result.success:
            return {"available": False}

        log_result = log(project_path, count=5)
        recent = []
        if log_result.success and log_result.stdout:
            for line in log_result.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split(" ", 1)
                    recent.append({
                        "sha": parts[0] if parts else "",
                        "message": parts[1] if len(parts) > 1 else "",
                    })

        status_result = status(project_path)
        dirty = status_result.success and bool(status_result.stdout.strip())

        branch_result = get_branch(project_path)
        branch = branch_result.stdout.strip() if branch_result.success else "unknown"

        return {
            "available": True,
            "branch": branch,
            "head_sha": sha_result.sha or "",
            "recent_commits": recent,
            "dirty": dirty,
        }
    except Exception:
        return {"available": False}


def _get_task_info(task_store: "TaskStore | None") -> dict:
    """Extract task summary for awareness snapshot."""
    if task_store is None:
        return {"total": 0, "in_progress": 0, "blocked": 0, "pending": 0, "done": 0}

    all_tasks = task_store.list_all()
    return {
        "total": len(all_tasks),
        "in_progress": sum(1 for t in all_tasks if t.status == "in_progress"),
        "blocked": sum(1 for t in all_tasks if t.status == "blocked"),
        "pending": sum(1 for t in all_tasks if t.status == "pending"),
        "done": sum(1 for t in all_tasks if t.status == "done"),
    }


# ── Awareness block builder (for injection) ──────────────────────────────────


def build_awareness_block(
    project_path: str,
    task_store: "TaskStore | None" = None,
) -> str:
    """
    Assemble the full awareness text block for agent injection.

    Combines:
      1. Project manifest header (purpose, stack)
      2. Team roster (who's working on this project)
      3. Dynamic state summary (git, tasks, review mode)
      4. Persistent context memory (cross-session notes)

    Returns formatted string suitable for system prompt injection or gateway message.
    """
    parts: list[str] = []

    # 1. Project manifest
    manifest = load_project_manifest(project_path)
    if manifest:
        # Take first ~2000 chars of manifest (avoid flooding context)
        truncated = manifest[:2000]
        if len(manifest) > 2000:
            truncated += "\n[... project manifest truncated ...]"
        parts.append(f"## Project Manifest\n\n{truncated}")

    # 2. Team roster
    team = load_team(project_path)
    if team.members:
        lines = ["## Team"]
        if team.pm_name:
            lines.append(f"PM: {team.pm_name}")
        for m in team.members:
            role_str = f" — {m.role}" if m.role else ""
            write_str = " [write]" if m.can_write else ""
            lines.append(f"- {m.name} ({m.session_key}){role_str}{write_str}")
        parts.append("\n".join(lines))
    elif team.pm_name:
        parts.append(f"## Team\nPM: {team.pm_name}\nNo other members yet.")

    # 3. Dynamic state
    snapshot = build_awareness_snapshot(project_path, task_store)
    state_lines = ["## Current State"]
    state_lines.append(f"Project: {snapshot.get('project_name', 'unknown')}")
    state_lines.append(f"Path: {snapshot.get('project_path', '')}")

    git = snapshot.get("git", {})
    if git.get("available"):
        state_lines.append(f"Git: {git.get('head_sha', '?')[:7]} ({'dirty' if git.get('dirty') else 'clean'})")
        recent = git.get("recent_commits", [])
        if recent:
            for c in recent[:3]:
                state_lines.append(f"  {c.get('sha', '?')[:7]} {c.get('message', '')}")
    else:
        state_lines.append("Git: not available")

    tasks = snapshot.get("tasks", {})
    if tasks.get("total", 0) > 0:
        state_lines.append(
            f"Tasks: {tasks.get('in_progress', 0)} in progress, "
            f"{tasks.get('blocked', 0)} blocked, "
            f"{tasks.get('pending', 0)} pending, "
            f"{tasks.get('done', 0)} done"
        )

    state_lines.append(f"Review mode: {snapshot.get('review_mode', 'off')}")
    parts.append("\n".join(state_lines))

    # 4. Persistent context
    context = load_project_context(project_path)
    if context.strip():
        # Take first ~3000 chars of context
        truncated = context[:3000]
        if len(context) > 3000:
            truncated += "\n[... context memory truncated ...]"
        parts.append(f"## Project Memory\n\n{truncated}")

    return "\n\n".join(parts)


# ── Tech stack detection ─────────────────────────────────────────────────────


def detect_tech_stack(project_path: str) -> list[str]:
    """
    Detect technologies from project files.
    Returns list of detected tech identifiers.
    """
    stack: list[str] = []

    detectors = {
        "package.json": ["javascript", "node"],
        "pyproject.toml": ["python"],
        "setup.py": ["python"],
        "requirements.txt": ["python"],
        "Pipfile": ["python"],
        "Cargo.toml": ["rust"],
        "go.mod": ["go"],
        "Gemfile": ["ruby"],
        "pom.xml": ["java"],
        "build.gradle": ["java"],
        "CMakeLists.txt": ["c/c++"],
        "Makefile": ["c/c++"],
    }

    try:
        entries = os.listdir(project_path)
    except OSError:
        return stack

    for entry in entries:
        if entry in detectors:
            stack.extend(detectors[entry])

    # Check for GTK via Python imports
    for indicator in ["pyproject.toml", "setup.py", "requirements.txt"]:
        indicator_path = os.path.join(project_path, indicator)
        if os.path.isfile(indicator_path):
            try:
                with open(indicator_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().lower()
                if "pygobject" in content or "pygtk" in content or "gi.require_version" in content:
                    if "gtk4" not in stack:
                        stack.append("gtk4")
                if "websockets" in content and "websocket" not in stack:
                    stack.append("websocket")
            except OSError:
                pass

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in stack:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


# ── Awareness dict (for prompt_loader template variables) ────────────────


def build_awareness_dict(project_path: str) -> dict[str, str]:
    """Return awareness data as a dict of template variables.

    Keys: PROJECT_NAME, TEAM_ROSTER, CURRENT_STATE, PROJECT_MEMORY, WORKFLOW_STATUS.
    Parallel to build_awareness_block() but returns structured data
    instead of formatted text.
    """
    parts: dict[str, str] = {}

    # Project name
    manifest = load_project_manifest(project_path)
    name_match = re.search(r"^#\s+(.+)$", manifest, re.MULTILINE) if manifest else None
    parts["PROJECT_NAME"] = name_match.group(1).strip() if name_match else os.path.basename(project_path)

    # Team roster
    team = load_team(project_path)
    if team.members:
        lines = []
        if team.pm_name:
            lines.append(f"PM: {team.pm_name}")
        for m in team.members:
            role_str = f" — {m.role}" if m.role else ""
            write_str = " [write]" if m.can_write else ""
            lines.append(f"- {m.name} ({m.session_key}){role_str}{write_str}")
        parts["TEAM_ROSTER"] = "\n".join(lines)
    else:
        parts["TEAM_ROSTER"] = "No team members yet."

    # Current state
    snapshot = build_awareness_snapshot(project_path)
    state_lines = [f"Project: {snapshot.get('project_name', 'unknown')}"]
    state_lines.append(f"Path: {snapshot.get('project_path', '')}")
    git = snapshot.get("git", {})
    if git.get("available"):
        state_lines.append(f"Git: {git.get('head_sha', '?')[:7]} ({'dirty' if git.get('dirty') else 'clean'})")
    else:
        state_lines.append("Git: not available")
    state_lines.append(f"Review mode: {snapshot.get('review_mode', 'off')}")
    parts["CURRENT_STATE"] = "\n".join(state_lines)

    # Project memory
    context = load_project_context(project_path)
    if context.strip():
        truncated = context[:3000]
        if len(context) > 3000:
            truncated += "\n[... context memory truncated ...]"
        parts["PROJECT_MEMORY"] = truncated
    else:
        parts["PROJECT_MEMORY"] = ""

    # Workflow status — lazy import to avoid circular dependency
    try:
        from utils.workflow_state import get_workflow_content
        wf = get_workflow_content(project_path)
        parts["WORKFLOW_STATUS"] = wf if wf.strip() else "(workflow.md not yet initialized)"
    except Exception:
        parts["WORKFLOW_STATUS"] = "(workflow state unavailable)"

    return parts
