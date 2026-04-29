# utils/feed_store.py
# Feed card persistence — load/save to .crabcakes/feed.json (Phase 2).
# Pure functions — no GTK, no state, no side effects beyond file I/O.
# Architecture: utils/ package, may import models/ only.

import json
import logging
import os

from models.feed_card import FeedCardData

FEED_FILENAME = "feed.json"
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


def load_feed(project_path: str) -> list[FeedCardData]:
    """
    Load feed cards from .crabcakes/feed.json.

    Returns cards in chronological order (oldest first).
    Returns empty list if file doesn't exist or is invalid JSON.
    Logs errors instead of raising.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("load_feed: failed to read %s: %s", path, e)
        return []

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
    Loads -> appends -> saves. Convenience wrapper.
    """
    cards = load_feed(project_path)
    cards.append(card)
    save_feed(project_path, cards)


def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool:
    """
    Update a specific card by card_id (e.g., set accepted=True).
    Loads -> finds card -> applies updates -> saves.
    Returns True if card was found and updated, False otherwise.
    Logs errors instead of raising.
    """
    cards = load_feed(project_path)
    for i, c in enumerate(cards):
        if c.card_id == card_id:
            # Apply field updates (only allow runtime fields)
            allowed = {"accepted", "reviewed", "metadata"}
            for key, val in updates.items():
                if key in allowed and hasattr(c, key):
                    setattr(c, key, val)
            save_feed(project_path, cards)
            return True
    return False