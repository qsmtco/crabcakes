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
import stat
import time

from models.feed_card import FeedCardData

FEED_FILENAME = "feed.json"
FEED_PREFS_FILENAME = "feed-prefs.json"
PREFS_VERSION = 2
_LOCK_RETRIES = 5          # max attempts to acquire lock
_LOCK_RETRY_DELAY = 0.05  # 50ms between retries
_logger = logging.getLogger(__name__)


# ── LOW-12 / LOW-13 helpers ──────────────────────────────────────────────────


def _atomic_write_json(path: str, data) -> None:
    """LOW-13: write JSON atomically — write to .tmp, then os.replace.

    Sets permissions to 0o600 (matches the security pattern in
    agent/runtime.py:1069-1072). Caller is responsible for the lock.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # some filesystems don't support chmod


def _atomic_write_text(path: str, content: str) -> None:
    """Atomic write of a text file. Uses .tmp + os.replace + 0o644 permissions."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def _ensure_gitignore_entry(project_path: str, entry: str) -> None:
    """LOW-12: ensure `entry` is in `<project_path>/.gitignore`.

    Creates the file if it doesn't exist. If the file exists, checks for
    the entry (whole-line match, ignoring trailing comments) and appends
    if missing. The write is atomic via _atomic_write_text.
    """
    gitignore = os.path.join(project_path, ".gitignore")
    lines: list[str] = []
    if os.path.isfile(gitignore):
        try:
            with open(gitignore, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
    # Check if entry is already present (ignore trailing comments)
    for line in lines:
        stripped = line.split("#", 1)[0].strip()
        if stripped == entry:
            return  # already present
    # Append
    lines.append(entry)
    _atomic_write_text(gitignore, "\n".join(lines) + "\n")


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
        _ensure_gitignore_entry(project_path, ".crabcakes/feed.json")
        _atomic_write_json(path, [c.to_dict() for c in cards])
    except OSError as e:
        _logger.error("save_feed: failed to write %s: %s", path, e)


def append_feed_card(project_path: str, card: FeedCardData) -> None:
    """
    Append a single card to the existing feed file.
    Locks -> loads -> appends -> saves -> unlocks. Atomic under flock.
    """
    path = _feed_path(project_path)
    _ensure_crabcakes_dir(project_path)
    _ensure_gitignore_entry(project_path, ".crabcakes/feed.json")
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
        try:
            _atomic_write_json(path, [c.to_dict() for c in cards])
        except OSError as e:
            _logger.error("append_feed_card: failed to write %s: %s", path, e)
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
    _ensure_crabcakes_dir(project_path)
    _ensure_gitignore_entry(project_path, ".crabcakes/feed.json")
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
                try:
                    _atomic_write_json(path, [cd.to_dict() for cd in cards])
                except OSError as e:
                    _logger.error("update_feed_card: failed to write %s: %s", path, e)
                    return False
                return True
        return False
    finally:
        _release_lock(fd, lock_path)


# ── Phase 5: Feed prefs (auto-accept toggle) ──────────────────────────────────


def _prefs_path(project_path: str) -> str:
    """Return the path to .crabcakes/feed-prefs.json for a project."""
    crabcakes = os.path.join(project_path, ".crabcakes")
    return os.path.join(crabcakes, FEED_PREFS_FILENAME)


def _default_prefs() -> dict:
    """Return the canonical default v2 prefs payload."""
    return {
        "version": 2,
        "auto_accept": {
            "file_changes": {
                ct: {"enabled": False, "agent_scope": "first_author"}
                for ct in ("diff", "file_created", "file_modified", "file_deleted")
            },
            "exec_command": {
                "mode": "off",
                "agent_scope": "first_author",
            },
            "snoozed_card_ids": [],
        },
    }


def load_feed_prefs(project_path: str) -> dict:
    """
    Load feed prefs from .crabcakes/feed-prefs.json.

    Handles v1 and v2 files. V1 files are migrated to v2 in-memory.
    Returns canonical v2 defaults if file is missing, malformed,
    or has an unrecognized version.
    """
    path = _prefs_path(project_path)
    if not os.path.isfile(path):
        return _default_prefs()

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("load_feed_prefs: failed to read %s: %s", path, e)
        return _default_prefs()

    if not isinstance(raw, dict):
        _logger.warning("load_feed_prefs: expected dict at %s, got %s", path, type(raw).__name__)
        return _default_prefs()

    version = raw.get("version")

    if version == 2:
        # V2 file — validate structure, overlay defaults for missing keys
        return _merge_v2_defaults(raw)

    if version == 1:
        # V1 file — migrate to v2 in-memory
        return _migrate_v1_to_v2(raw)

    _logger.warning("load_feed_prefs: unknown version %r at %s, using defaults", version, path)
    return _default_prefs()


def _migrate_v1_to_v2(raw: dict) -> dict:
    """Migrate a v1 prefs dict to v2 format.

    v1: {"version": 1, "auto_accept_enabled": bool, "auto_accept_agent": str|None}
    v2: {"version": 2, "auto_accept": {"file_changes": {...}, "exec_command": {...}, ...}}

    Migration rules:
    - If auto_accept_enabled was False: all four file-change types disabled.
    - If auto_accept_enabled was True AND auto_accept_agent is None: all four
      enabled with first_author scope (lazy lock-in preserved).
    - If auto_accept_enabled was True AND auto_accept_agent is set: all four
      enabled with agent_scope = the persisted agent name. The first_author
      lazy lock-in is bypassed because the user explicitly chose an agent.

    The agent name from v1 is significant — it represents a deliberate lock-in
    the user already made. Dropping it would silently change which agent's
    cards auto-accept after upgrade (BUG #1 in adversarial audit).
    """
    enabled = bool(raw.get("auto_accept_enabled", False))
    agent = raw.get("auto_accept_agent")
    if enabled and isinstance(agent, str) and agent:
        scope = agent  # Persist as a specific agent scope
    else:
        scope = "first_author"
    return {
        "version": 2,
        "auto_accept": {
            "file_changes": {
                ct: {"enabled": enabled, "agent_scope": scope}
                for ct in ("diff", "file_created", "file_modified", "file_deleted")
            },
            "exec_command": {"mode": "off", "agent_scope": scope},
            "snoozed_card_ids": [],
        },
    }


def _merge_v2_defaults(raw: dict) -> dict:
    """Overlay a v2 prefs dict onto defaults to fill missing keys."""
    result = _default_prefs()
    auto = raw.get("auto_accept", {})
    if isinstance(auto, dict):
        fc_raw = auto.get("file_changes", {})
        if isinstance(fc_raw, dict):
            for ct in result["auto_accept"]["file_changes"]:
                fc = fc_raw.get(ct, {})
                if isinstance(fc, dict):
                    result["auto_accept"]["file_changes"][ct]["enabled"] = bool(
                        fc.get("enabled", False)
                    )
                    result["auto_accept"]["file_changes"][ct]["agent_scope"] = str(
                        fc.get("agent_scope", "first_author")
                    )
        exec_raw = auto.get("exec_command", {})
        if isinstance(exec_raw, dict):
            result["auto_accept"]["exec_command"]["mode"] = str(
                exec_raw.get("mode", "off")
            )
            result["auto_accept"]["exec_command"]["agent_scope"] = str(
                exec_raw.get("agent_scope", "first_author")
            )
        snoozed = auto.get("snoozed_card_ids", [])
        if isinstance(snoozed, list):
            result["auto_accept"]["snoozed_card_ids"] = list(snoozed)
    return result


def save_feed_prefs(project_path: str, prefs: dict) -> None:
    """
    Save feed prefs to .crabcakes/feed-prefs.json.

    Creates .crabcakes/ directory if missing. Validates that prefs is a
    dict with version == PREFS_VERSION. Writes atomically via
    _atomic_write_json (chmod 0o600). Logs errors instead of raising.
    """
    if not isinstance(prefs, dict):
        _logger.error("save_feed_prefs: prefs must be a dict, got %s", type(prefs).__name__)
        return
    if prefs.get("version") != PREFS_VERSION:
        _logger.error("save_feed_prefs: prefs.version must be %d, got %r", PREFS_VERSION, prefs.get("version"))
        return
    try:
        _ensure_crabcakes_dir(project_path)
        path = _prefs_path(project_path)
        _atomic_write_json(path, prefs)
    except OSError as e:
        _logger.error("save_feed_prefs: failed to write prefs: %s", e)
