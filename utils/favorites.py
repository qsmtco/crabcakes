# utils/favorites.py
# Favorites persistence for prompt library.
#
# Security: No secrets. File I/O only — reads/writes favorites set to JSON.
#
# Public API:
#   load_favorites() -> set[str]  (filepath set, may be empty)
#   save_favorites(set[str]) -> None
#   is_favorite(filepath) -> bool
#   toggle_favorite(filepath) -> bool  (True if now favorited)

import json
import os

from utils.config import get_config_dir

_FAVORITES_PATH = os.path.join(get_config_dir(), "favorites.json")


def _ensure_dir():
    """Create config directory if it doesn't exist."""
    os.makedirs(get_config_dir(), exist_ok=True)


def load_favorites() -> set[str]:
    """Load favorite filepaths from favorites.json. Returns empty set on error."""
    if not os.path.exists(_FAVORITES_PATH):
        return set()
    try:
        with open(_FAVORITES_PATH, 'r') as f:
            data = json.load(f)
        favs = data.get('favorites', [])
        return set(favs) if isinstance(favs, list) else set()
    except (json.JSONDecodeError, OSError):
        return set()


def save_favorites(favorites: set[str]) -> None:
    """Persist favorites set to favorites.json."""
    _ensure_dir()
    with open(_FAVORITES_PATH, 'w') as f:
        json.dump({'favorites': sorted(favorites)}, f)


def is_favorite(filepath: str) -> bool:
    """True if filepath is in favorites."""
    return filepath in load_favorites()


def toggle_favorite(filepath: str) -> bool:
    """Toggle filepath in favorites. Returns True if now favorited."""
    favs = load_favorites()
    if filepath in favs:
        favs.discard(filepath)
        save_favorites(favs)
        return False
    else:
        favs.add(filepath)
        save_favorites(favs)
        return True
