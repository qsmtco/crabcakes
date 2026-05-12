# utils/feed_store.py
# Feed card persistence — load/save to .crabcakes/feed.json (Phase 2).
# Pure functions — no GTK, no state, no side effects beyond file I/O.
# Architecture: utils/ package, may import models/ only.
#
# Thread safety: fcntl.flock() advisory lock on feed.json prevents concurrent
# load→modify→save cycles from corrupting the file. Lock is held for the
# entire read-modify-write window. Non-blocking acquire with retry.

import fcntl
import json
import logging
import os
import time

from models.feed_card import FeedCardData

FEED_FILENAME = "feed.json"
_LOCK_RETRIES = 5          # max attempts to acquire lock
_LOCK_RETRY_DELAY = 0.05  # 50ms between retries
_logger = logging.getLogger(__name__)


def _feed_path(project_path: str) -> str:
    """Return the path to .crabcakes/feed.json for a project."""
    crabcakes = os.path.join(project_path, ".crabcakes")
    return os.path.join(crabcakes, FEED_FILENAME)


def _ensure_crabcakes_dir(project_path: str) -> None:
    """Create .crabcakes directory if it doesn't exist."""
    crabcakes = os.path.join(project_path, ".crabcakes")
    if not os.path.isdir(crabcakes):
        os.makedirs(crabcakes, exist_ok=True)


def _acquire_lock(path: str) -> tuple:
    """Acquire an advisory flock on the feed file. Returns (fd, lock_file_path).

    Uses a separate .lock file so we don't conflict with readers of feed.json.
    Non-blocking with retries to avoid deadlocking.
    """
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    for attempt in range(_LOCK_RETRIES):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd, lock_path
        except (OSError, BlockingIOError):
            if attempt < _LOCK_RETRIES - 1:
                time.sleep(_LOCK_RETRY_DELAY)
    # Final attempt — blocking (should rarely reach here)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd, lock_path


def _release_lock(fd: int, lock_path: str) -> None:
    """Release flock and close fd."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def load_feed(project_path: str) -> list[FeedCardData]:
    """
    Load feed cards from .crabcakes/feed.json.

    Returns cards in chronological order (oldest first).
    Returns empty list if file doesn't exist or is invalid JSON.
    Logs errors instead of raising.

    Thread safety: acquires shared lock during read to avoid reading
    a partially-written file.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return []

    fd = None
    lock_path = None
    try:
        fd, lock_path = _acquire_lock(path)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("load_feed: failed to read %s: %s", path, e)
        return []
    finally:
        if fd is not None:
            _release_lock(fd, lock_path)

    if not isinstance(raw, list):
        _logger.warning("load_feed: expected list at %s, got %s", path, type(raw).__name__)
        return []

    cards = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            cards.append(FeedCardData.from_dict(item))
        except (KeyError, TypeError) as e:
            _logger.warning("load_feed: skipped malformed card: %s", e)
            continue

    return cards


def save_feed(project_path: str, cards: list[FeedCardData]) -> None:
    """
    Save feed cards to .crabcakes/feed.json.

    Serializes each card via FeedCardData.to_dict().
    Creates .crabcakes/ directory if it doesn't exist.
    Logs errors instead of raising.

    Note: Callers doing load→modify→save should use _with_lock() helpers
    (append_feed_card, update_feed_card) to prevent races.
    Standalone saves are safe only when no concurrent writers exist.
    """
    try:
        _ensure_crabcakes_dir(project_path)
        path = _feed_path(project_path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f, indent=2)
    except OSError as e:
        _logger.error("save_feed: failed to write %s: %s", path, e)


def append_feed_card(project_path: str, card: FeedCardData) -> None:
    """
    Append a single card to the existing feed file.
    Locks -> loads -> appends -> saves -> unlocks. Atomic under flock.
    """
    path = _feed_path(project_path)
    _ensure_crabcakes_dir(project_path)
    fd, lock_path = _acquire_lock(path)
    try:
        # Read
        raw_cards = []
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_cards = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                _logger.warning("append_feed_card: failed to read %s: %s", path, e)
                raw_cards = []
        # Parse
        cards = []
        for item in (raw_cards if isinstance(raw_cards, list) else []):
            if isinstance(item, dict):
                try:
                    cards.append(FeedCardData.from_dict(item))
                except (KeyError, TypeError):
                    continue
        # Append + Write
        cards.append(card)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f, indent=2)
    finally:
        _release_lock(fd, lock_path)


def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool:
    """
    Update a specific card by card_id (e.g., set accepted=True).
    Locks -> loads -> finds card -> applies updates -> saves -> unlocks.
    Returns True if card was found and updated, False otherwise.
    Logs errors instead of raising.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return False
    fd, lock_path = _acquire_lock(path)
    try:
        # Read
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_cards = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _logger.warning("update_feed_card: failed to read %s: %s", path, e)
            return False
        # Parse
        cards = []
        for item in (raw_cards if isinstance(raw_cards, list) else []):
            if isinstance(item, dict):
                try:
                    cards.append(FeedCardData.from_dict(item))
                except (KeyError, TypeError):
                    continue
        # Update
        for c in cards:
            if c.card_id == card_id:
                allowed = {"accepted", "reviewed", "metadata"}
                for key, val in updates.items():
                    if key in allowed and hasattr(c, key):
                        setattr(c, key, val)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([cd.to_dict() for cd in cards], f, indent=2)
                return True
        return False
    finally:
        _release_lock(fd, lock_path)