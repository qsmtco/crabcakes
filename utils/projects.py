# utils/projects.py
# Loads project directories and project membership

import json
import os

PROJECTS_DIR: str = os.environ.get("CRABCAKES_PROJECTS_DIR", os.path.expanduser("~/projects"))

# Allow tests to patch this directly
_PROJECTS_DIR_REF: list[str] = [PROJECTS_DIR]  # wrap in list for mutation


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


def scan_directory(path: str) -> list[tuple[str, str, bool]]:
    """
    Return [(name, full_path, is_dir)] for one level, filtered.
    Skips __pycache__, .git, node_modules, .venv, venv, dotfiles.
    """
    if not os.path.isdir(path):
        return []
    skip: set[str] = {'__pycache__', '.git', 'node_modules', '.venv', 'venv'}
    result: list[tuple[str, str, bool]] = []
    for name in sorted(os.listdir(path)):
        if name.startswith('.') or name in skip:
            continue
        full: str = os.path.join(path, name)
        result.append((name, full, os.path.isdir(full)))
    return result


def load_members(project_name: str) -> list[str]:
    """
    Load member session keys for a project from members.json.
    Returns [] if not found or unreadable.
    """
    path: str = os.path.join(
        os.path.expanduser("~/.config/crabcakes/projects"),
        project_name,
        "members.json"
    )
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_members(project_name: str, members: list[str]) -> None:
    """
    Save member session keys for a project to members.json.
    Creates the project directory if needed.
    """
    dir_path: str = os.path.join(
        os.path.expanduser("~/.config/crabcakes/projects"),
        project_name
    )
    os.makedirs(dir_path, exist_ok=True)
    path: str = os.path.join(dir_path, "members.json")
    with open(path, "w") as f:
        json.dump(members, f)
