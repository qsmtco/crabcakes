# utils/favorites.py
# Favorites persistence for prompt library.
#
# Security: No secrets. File I/O only — reads/writes favorites set to JSON.
#
# Public API:
#   load_favorites() -> set[str]  (favorite STEMS, not paths; may be empty)
#   save_favorites(set[str]) -> None
#   is_favorite(stem) -> bool
#   toggle_favorite(stem) -> bool  (True if now favorited)

import json
import os

from utils.config import get_config_dir

_FAVORITES_PATH = os.path.join(get_config_dir(), "favorites.json")


def _ensure_dir():
    """Create config directory if it doesn't exist."""
    os.makedirs(get_config_dir(), exist_ok=True)


def load_favorites() -> set[str]:
    """Load favorite prompt stems from favorites.json. Returns empty set on error.

    One-time migration: entries that look like absolute paths (contain "/")
    are stripped to their basename-without-extension, converted to stems.
    The file is rewritten with the migrated form. This is idempotent —
    running it again on already-migrated data is a no-op.
    """
    if not os.path.exists(_FAVORITES_PATH):
        return set()
    try:
        with open(_FAVORITES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return set()
    # Shape guards (Phase 4 audit BUGs #1/#2): malformed-shape JSON must
    # degrade to empty set, never raise out of load_favorites().
    if not isinstance(data, dict):
        return set()
    favs = data.get("favorites", [])
    if not isinstance(favs, list):
        return set()
    # Migration: paths → stems (one-time, idempotent). Non-string entries
    # are DROPPED (not crashed on): a favorites.json like [1, null, "foo"]
    # keeps "foo" instead of killing the whole Prompts tab with a TypeError
    # from "/" in <int>. The resulting rewrite also cleans the junk out of
    # the file.
    migrated = [
        os.path.splitext(os.path.basename(p))[0] if "/" in p else p
        for p in favs
        if isinstance(p, str)
    ]
    if migrated != favs:
        save_favorites(set(migrated))
    return set(migrated)


def save_favorites(favorites: set[str]) -> None:
    """Persist favorites set to favorites.json."""
    _ensure_dir()
    with open(_FAVORITES_PATH, "w", encoding="utf-8") as f:
        json.dump({"favorites": sorted(favorites)}, f)


def is_favorite(stem: str) -> bool:
    """True if *stem* (prompt name without .md) is favorited."""
    return stem in load_favorites()


def toggle_favorite(stem: str) -> bool:
    """Toggle *stem* in favorites. Returns True if now favorited."""
    favs = load_favorites()
    if stem in favs:
        favs.discard(stem)
        save_favorites(favs)
        return False
    favs.add(stem)
    save_favorites(favs)
    return True
