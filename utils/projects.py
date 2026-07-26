# utils/projects.py
# Loads project directories.
#
# Membership management moved to utils/project_awareness.py (Project Awareness System).
# Legacy load_members/save_members removed.

import os
import mimetypes

from utils.config import get_projects_dir

# Allow tests to patch this directly without patching the module-level constant.
# Wrapped in a list so tests can mutate _PROJECTS_DIR_REF[0] in-place rather than
# rebinding the name (which wouldn't affect already-imported references).
_PROJECTS_DIR_REF: list[str] = [get_projects_dir()]


def load_projects() -> list[tuple[str, str]]:
    """
    Load all directories from the projects root path.
    Returns [(directory_name, full_path)].
    """
    projects_dir = _PROJECTS_DIR_REF[0]
    if not os.path.isdir(projects_dir):
        return []
    result: list[tuple[str, str]] = []
    for name in sorted(os.listdir(projects_dir)):
        full_path = os.path.join(projects_dir, name)
        if os.path.isdir(full_path):
            result.append((name, full_path))
    return result


def scan_directory(path: str) -> list[tuple[str, str, bool, int, int]]:
    """
    Return [(name, full_path, is_dir, size_bytes, mtime_ns)] for one level, filtered.
    Skips __pycache__, .git, node_modules, .venv, venv, dotfiles.
    
    size_bytes: int (0 for directories, 0 on stat error)
    mtime_ns: int (nanosecond precision, 0 on stat error)
    """
    if not os.path.isdir(path):
        return []
    skip: set[str] = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}
    result: list[tuple[str, str, bool, int, int]] = []
    for name in sorted(os.listdir(path)):
        if name.startswith('.') or name in skip:
            continue
        full: str = os.path.join(path, name)
        try:
            st = os.stat(full)
            result.append((name, full, os.path.isdir(full), st.st_size, st.st_mtime_ns))
        except OSError:
            result.append((name, full, os.path.isdir(full), 0, 0))
    return result


# Backwards-compatible aliases — delegate to project_awareness.
# These are thin wrappers so existing code that imports load_members/save_members
# from utils.projects continues to work during the transition.
#
# NOTE: These are DEPRECATED. New code should use project_awareness.load_team()
# and project_awareness.save_team() directly.

def load_members(project_name: str) -> list[str]:
    """
    DEPRECATED: Use project_awareness.load_team() instead.
    Returns session keys for backward compatibility.
    """
    from utils.project_awareness import load_team as _load_team
    for name, path in load_projects():
        if name == project_name:
            team = _load_team(path)
            return team.get_session_keys()
    return []


def save_members(project_name: str, members: list[str]) -> None:
    """
    DEPRECATED: Use project_awareness.save_team() instead.
    Saves session keys for backward compatibility.
    """
    from utils.project_awareness import load_team as _load_team, save_team as _save_team
    from models.team import TeamMember
    for name, path in load_projects():
        if name == project_name:
            team = _load_team(path)
            new_members = []
            for sk in members:
                existing = team.get_member(sk)
                new_members.append(existing if existing else TeamMember(session_key=sk, name=""))
            team.members = new_members
            _save_team(path, team)
            return
