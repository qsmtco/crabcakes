# ui/handlers/file_tree_handler.py
# File tree logic: git status caching, sort preference persistence.
# No GTK imports. Communicates with view via callbacks.

import os
import json

from utils.git_ops import status_porcelain


class FileTreeHandler:
    """Manages file tree logic: git status caching, sort preference persistence.

    No GTK imports. Communicates with view via callbacks set on the view instance.
    """

    # Valid sort modes (BUG #13 whitelist)
    _VALID_SORT_MODES = frozenset({
        "name_asc", "name_desc", "modified_asc", "modified_desc",
        "size_asc", "size_desc"
    })

    def __init__(self, project_path: str = ""):
        self._project_path = project_path
        self._git_status_cache: dict[str, str] = {}
        self._git_status_dirty = True
        self._sort_mode = "name_asc"
        self._prefs_path = ""
        if project_path:
            self._prefs_path = os.path.join(project_path, ".crabcakes", "file_tree_prefs.json")
            self._load_prefs()

    def refresh_git_status(self) -> dict[str, str]:
        """Run git status --porcelain, cache result, return parsed map.

        Returns empty dict if not a git repo or on any error.
        Cached until invalidate_git_status() is called.
        """
        if not self._git_status_dirty:
            return self._git_status_cache
        self._git_status_cache = status_porcelain(self._project_path)
        self._git_status_dirty = False
        return self._git_status_cache

    def invalidate_git_status(self) -> None:
        """Mark git status cache as dirty — next refresh will re-run git status."""
        self._git_status_dirty = True

    def get_sort_mode(self) -> str:
        return self._sort_mode

    def set_sort_mode(self, mode: str) -> None:
        """Set sort mode, save to persistence. Validates against whitelist (BUG #13)."""
        if mode not in self._VALID_SORT_MODES:
            return
        if mode != self._sort_mode:
            self._sort_mode = mode
            self._save_prefs()

    def set_project_path(self, path: str) -> None:
        """Called when project switches. Invalidates caches, loads prefs."""
        self._project_path = path
        self.invalidate_git_status()
        if path:
            self._prefs_path = os.path.join(path, ".crabcakes", "file_tree_prefs.json")
            self._load_prefs()
        else:
            self._prefs_path = ""
            self._sort_mode = "name_asc"

    def _load_prefs(self) -> None:
        """Load sort preference from disk. Validates mode against whitelist (BUG #13)."""
        if not self._prefs_path or not os.path.exists(self._prefs_path):
            self._sort_mode = "name_asc"
            return
        try:
            with open(self._prefs_path) as f:
                data = json.load(f)
                loaded = data.get("sort_mode", "name_asc")
                if loaded in self._VALID_SORT_MODES:
                    self._sort_mode = loaded
                else:
                    self._sort_mode = "name_asc"
        except Exception:
            self._sort_mode = "name_asc"

    def _save_prefs(self) -> None:
        """Save sort mode to per-project prefs file."""
        if not self._prefs_path:
            return
        os.makedirs(os.path.dirname(self._prefs_path), exist_ok=True)
        with open(self._prefs_path, "w") as f:
            json.dump({"sort_mode": self._sort_mode}, f)
