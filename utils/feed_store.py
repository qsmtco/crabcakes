# utils/feed_store.py
# Feed card persistence — load/save to .crabcakes/feed.json (Phase 2).
# Pure functions — no GTK, no state, no side effects beyond file I/O.
# Architecture: utils/ package, may import models/ only.
#
# Thread safety: fcntl.flock() advisory lock on feed.json prevents concurrent
# load→modify→save cycles from corrupting the file. Lock is held for the
# entire read-modify-write window. Bounded, non-blocking acquire (2 s
# deadline, returns None on timeout — never blocks unbounded).
#
# SPEC-UI-RESPONSIVENESS-2 §2.2 — update journal. Card updates no longer
# rewrite the whole feed: `append_card_update` appends ONE JSONL line to
# `.crabcakes/feed-updates.jsonl` (O(1)), and `load_feed` merges that journal
# over the snapshot. `compact_feed` folds the journal into the snapshot and
# truncates it (triggered from `update_feed_card` at the threshold and,
# rate-limited, from `append_feed_card`). Updates are therefore recorded
# without the card having to exist yet — the journal is the source of truth
# for pending changes, replay is idempotent, and a torn final line is
# tolerated.
#
# UNIFORM LOCK RULE (§2.2.3): every mutation — snapshot OR journal — holds the
# FEED flock (`feed.json.lock`) for its whole critical section. fcntl.flock is
# per-inode, so a separate journal lock would give no mutual exclusion and a
# journal append could be truncated away mid-fold by a concurrent compaction
# (lost update despite a True return). ONE inode, every mutation.
#
# §2.3 — sliding-window pruning. `compact_feed(window=N)` keeps the newest N
# cards and prunes the rest, except PINNED cards (a recorded accept/reject,
# needs_review/needs_approval, or git_commit) which are never pruned.
# `window=None` prunes nothing. Triggers: journal threshold, the rate-limited
# post-append check, and the FeedHandler's one-time open-time request for a
# legacy oversized feed. `load_feed` never compacts.
#
# DOCUMENTED DEVIATION from the "pure functions — no state" contract above:
# `_compact_last` / `_compact_rl_lock` keep per-project compaction
# timestamps so the append-triggered compaction is rate-limited. This is
# file-I/O orchestration state only (no GTK, no handler state), guarded by
# its own lock, and never evicted (≈100 B per project).

import fcntl
import json
import logging
import os
import stat
import threading
import time

from models.feed_card import FeedCardData

FEED_FILENAME = "feed.json"
FEED_PREFS_FILENAME = "feed-prefs.json"
JOURNAL_FILENAME = "feed-updates.jsonl"
PREFS_VERSION = 2
_LOCK_RETRY_DELAY = 0.05  # 50ms between non-blocking acquire attempts
JOURNAL_COMPACT_THRESHOLD = 500   # lines; compact when exceeded
_LOCK_TIMEOUT_SEC = 2.0           # bounded lock deadline (was unbounded)
_COMPACT_MIN_INTERVAL = 60.0      # seconds between append-triggered compacts
FEED_WINDOW_DEFAULT = 2000        # newest N cards retained at compaction
_logger = logging.getLogger(__name__)

# Documented deviation from this module's "pure functions" docstring: the
# compact rate-limit needs per-project last-compact timestamps. Guarded by
# _compact_rl_lock; no GTK, no handler state — file-I/O orchestration only.
_compact_last: dict[str, float] = {}
_compact_rl_lock = threading.Lock()

# The fields a journal record (or a legacy update payload) may set on a card.
# D3 (SPEC-UI-RESPONSIVENESS-2): "body" added — update_card persists
# {"body", "metadata"}, and the old 3-field allowed set silently dropped the
# body, leaving stale bodies on disk after tool results.
_UPDATABLE_FIELDS = frozenset({"accepted", "reviewed", "metadata", "body"})


# ── LOW-12 / LOW-13 helpers ──────────────────────────────────────────────────


def _atomic_write_json(path: str, data, compact: bool = False) -> None:
    """LOW-13: write JSON atomically — write to .tmp, then os.replace.

    Sets permissions to 0o600 (matches the security pattern in
    agent/runtime.py:1069-1072). Caller is responsible for the lock.

    `compact=True` (SPEC-UI-RESPONSIVENESS-2 §2.2.9) drops the `indent=2`
    pretty-printing for feed snapshots — a 9,500-card feed is far smaller and
    cheaper to serialize. Deliberately NO `default=`: a non-serializable value
    must raise (surfacing in the caller's log and taking the legacy/False
    path) rather than be silently stringified into the feed. Prefs callers
    keep the default `indent=2` (small, human-editable files).
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f)
        else:
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

    Known pre-existing limitation (audit-accepted, not fixed here): this
    read-modify-write is not protected by the feed flock, so two processes
    can race it. Every existing caller has the same exposure; per-project
    gitignore locking would be scope creep.
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


def _journal_path(project_path: str) -> str:
    """Return the path to .crabcakes/feed-updates.jsonl for a project."""
    crabcakes = os.path.join(project_path, ".crabcakes")
    return os.path.join(crabcakes, JOURNAL_FILENAME)


def _ensure_crabcakes_dir(project_path: str) -> None:
    """Create .crabcakes directory if it doesn't exist."""
    crabcakes = os.path.join(project_path, ".crabcakes")
    if not os.path.isdir(crabcakes):
        os.makedirs(crabcakes, exist_ok=True)


def _acquire_lock(path: str, timeout: float = _LOCK_TIMEOUT_SEC) -> tuple | None:
    """Acquire the feed lock. Returns (fd, lock_path) or None on timeout.

    Never blocks unbounded: non-blocking attempts inside a deadline loop.
    Callers MUST handle None — read paths fall back to a lock-free read,
    write paths skip and log (the journal/queue keeps the data safe for the
    next attempt). The old implementation's final `fcntl.flock(fd, LOCK_EX)`
    could park a thread indefinitely; the profiler caught the main thread
    there 9× (SPEC-UI-RESPONSIVENESS-2 §1.1).
    """
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd, lock_path
        except (OSError, BlockingIOError):
            time.sleep(_LOCK_RETRY_DELAY)
    os.close(fd)
    _logger.warning("feed lock busy >%.1fs: %s", timeout, lock_path)
    return None


def _release_lock(fd: int, lock_path: str) -> None:
    """Release flock and close fd."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# ── Shared parse / merge helpers (§2.2.4) ────────────────────────────────────


def _parse_cards(raw) -> list[FeedCardData]:
    """Parse a raw JSON value into cards (shared by load_feed/compact_feed)."""
    if not isinstance(raw, list):
        _logger.warning(
            "feed_store: expected list, got %s", type(raw).__name__
        )
        return []
    cards: list[FeedCardData] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            cards.append(FeedCardData.from_dict(item))
        except (KeyError, TypeError) as e:
            _logger.warning("feed_store: skipped malformed card: %s", e)
            continue
    return cards


def _apply_overlay(cards: list[FeedCardData], overlay: dict) -> None:
    """Merge a journal overlay onto parsed cards (shared load/compact rules).

    `metadata` merges per-key (`card.metadata.update(val)`) so an update that
    carries only the changed keys does not wipe the rest; a non-dict metadata
    value is skipped with a WARNING (type-trust guard, audit r3 #10). Scalars
    are setattr'd (allowed set `_UPDATABLE_FIELDS`). Records for cards absent
    from the snapshot are stale (pruned) and dropped at DEBUG.
    """
    if not overlay:
        return
    by_id = {c.card_id: c for c in cards if c.card_id}
    for card_id, updates in overlay.items():
        card = by_id.get(card_id)
        if card is None:
            _logger.debug(
                "journal: dropping stale record for absent card %s", card_id
            )
            continue
        if not isinstance(updates, dict):
            continue
        for key, val in updates.items():
            if key == "metadata":
                if isinstance(val, dict):
                    card.metadata.update(val)
                else:
                    _logger.warning(
                        "journal: non-dict metadata for card %s skipped", card_id
                    )
                continue
            if key in _UPDATABLE_FIELDS and hasattr(card, key):
                setattr(card, key, val)


# ── Journal primitives (§2.2.4) ──────────────────────────────────────────────


def _tail_is_complete_record(tail: bytes) -> bool:
    """True when the journal's final (newline-less) chunk is complete JSON.

    Distinguishes "the record's bytes landed but the crash beat the `\\n`"
    (worth preserving) from "the crash landed mid-write" (garbage that must
    be removed — see `append_card_update`).
    """
    try:
        record = json.loads(tail.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(record, dict)


def append_card_update(project_path: str, card_id: str, updates: dict) -> bool:
    """Append one update record to the journal — O(1), no full-file rewrite.

    Record shape: `{"card_id": str, "updates": dict}`. One `write()` of
    `json.dumps(record) + "\\n"`, under the feed flock so a concurrent
    compaction can never truncate between our append and its fold. Returns
    True when the line was written.

    A payload that cannot be serialized (TypeError/ValueError, e.g. a
    non-JSON-native object or a circular reference) or an OSError returns
    False with a WARNING so the caller falls back to the legacy RMW — which
    serializes via `to_dict()` and therefore may still succeed. A non-dict
    `metadata` value is dropped from the record with a WARNING (never
    journaled garbage).

    Torn tail (crash mid-append): `_replay_journal` stops at the first
    unparseable line, so a damaged final record would otherwise shadow every
    record appended after it — and those updates would then be silently lost
    at the next compaction, which folds with the same replay rule. This
    writer therefore repairs the tail before appending: if the final chunk
    is a COMPLETE record missing only its newline it is preserved (a `\\n` is
    written first); if it is garbage it is truncated away. Either way the new
    record is replayable.
    """
    if not project_path or not card_id:
        _logger.warning(
            "append_card_update: empty project_path/card_id — update dropped"
        )
        return False

    jp = _journal_path(project_path)
    _ensure_crabcakes_dir(project_path)
    if not os.path.isfile(jp):
        _ensure_gitignore_entry(project_path, ".crabcakes/" + JOURNAL_FILENAME)

    record_updates = dict(updates)
    if "metadata" in record_updates and not isinstance(record_updates["metadata"], dict):
        _logger.warning(
            "append_card_update: non-dict metadata for card %s dropped", card_id
        )
        record_updates.pop("metadata")

    try:
        # No `default=`: a non-serializable value must fall back to the
        # legacy path (which serializes via to_dict), never be stringified.
        line = json.dumps({"card_id": card_id, "updates": record_updates})
    except (TypeError, ValueError) as e:
        _logger.warning(
            "append_card_update: non-serializable update for card %s (%s) — "
            "falling back to the legacy write path", card_id, e,
        )
        return False

    acquired = _acquire_lock(_feed_path(project_path))
    if acquired is None:
        _logger.warning(
            "append_card_update: feed lock busy for %s — update not recorded",
            _feed_path(project_path),
        )
        return False
    fd, lock_path = acquired
    try:
        # Tail repair is BEST-EFFORT: a failure to inspect the file must never
        # block the append (a lone record on its own line is still valid).
        needs_sep = False
        try:
            if os.path.isfile(jp):
                with open(jp, "r+b") as jf:
                    content = jf.read()
                    if content:
                        last_nl = content.rfind(b"\n")
                        tail = content[last_nl + 1:]
                        if tail:
                            if _tail_is_complete_record(tail):
                                needs_sep = True   # keep it; just add the newline
                            else:
                                _logger.warning(
                                    "journal: repairing torn tail in %s "
                                    "(%d bytes dropped)", jp, len(tail),
                                )
                                jf.truncate(last_nl + 1)
        except (OSError, ValueError):
            needs_sep = False
        with open(jp, "a", encoding="utf-8") as f:
            if needs_sep:
                f.write("\n")
            f.write(line + "\n")
    except OSError as e:
        _logger.warning(
            "append_card_update: failed to write %s: %s", jp, e
        )
        return False
    finally:
        _release_lock(fd, lock_path)
    return True


def _replay_journal(project_path: str) -> dict[str, dict]:
    """Fold the journal into `{card_id: merged_updates}`.

    A missing journal is not an error (empty overlay). Reading stops at the
    first unparseable line — a torn tail from a crash mid-append — with a
    single WARNING; every earlier record is still applied. Later records for
    the same card merge over earlier ones per-key.
    """
    jp = _journal_path(project_path)
    if not os.path.isfile(jp):
        return {}

    overlay: dict[str, dict] = {}
    try:
        with open(jp, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    _logger.warning(
                        "journal: torn tail in %s — prior records applied", jp
                    )
                    break
                if not isinstance(record, dict):
                    _logger.warning("journal: skipping non-dict record in %s", jp)
                    continue
                card_id = record.get("card_id")
                updates = record.get("updates")
                if not isinstance(card_id, str) or not card_id:
                    _logger.warning(
                        "journal: skipping record without card_id in %s", jp
                    )
                    continue
                if not isinstance(updates, dict):
                    _logger.warning(
                        "journal: skipping non-dict updates for %s", card_id
                    )
                    continue
                overlay.setdefault(card_id, {}).update(updates)
    except OSError as e:
        _logger.warning("journal: failed to read %s: %s", jp, e)
        return {}
    return overlay


def _journal_line_count(project_path: str) -> int:
    """Count non-empty journal lines (bounded by threshold + in-flight)."""
    jp = _journal_path(project_path)
    if not os.path.isfile(jp):
        return 0
    try:
        with open(jp, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def load_feed(project_path: str) -> list[FeedCardData]:
    """
    Load feed cards from .crabcakes/feed.json, replaying the update journal.

    Returns cards in chronological order (oldest first).
    Returns empty list if file doesn't exist or is invalid JSON.
    Logs errors instead of raising.

    Thread safety: the snapshot and the journal are read under ONE lock hold,
    so a concurrent compaction can never truncate the journal between the two
    reads (it holds the same lock). The lock timeout scales with the file size
    (a large feed needs patience against a multi-second compaction); on
    timeout the read proceeds lock-free with a WARNING — `os.replace` makes a
    partially-written snapshot impossible, and the next load re-reads
    consistently.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return []

    fd = None
    lock_path = None
    overlay: dict[str, dict] = {}
    try:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        timeout = min(60.0, 10.0 + size / 1_000_000)
        acquired = _acquire_lock(path, timeout=timeout)
        if acquired is None:
            # Accepted residual (§2.2.3): this lock-free fallback also reads
            # the journal below without a lock, so it can observe an in-flight
            # append tail (or miss a just-landed record) while another
            # process holds the feed lock. Bounded and self-healing — the
            # next load re-reads consistently once the lock is free. NO code
            # change: acquiring the journal path separately here would
            # re-introduce the split-lock bug (two inodes, no exclusion).
            _logger.warning(
                "load_feed: lock busy >%.1fs, lock-free read of %s", timeout, path
            )
        else:
            fd, lock_path = acquired
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        overlay = _replay_journal(project_path)   # same lock window
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("load_feed: failed to read %s: %s", path, e)
        return []
    finally:
        if fd is not None:
            _release_lock(fd, lock_path)

    cards = _parse_cards(raw)
    _apply_overlay(cards, overlay)
    return cards


def save_feed(project_path: str, cards: list[FeedCardData]) -> None:
    """
    Save feed cards to .crabcakes/feed.json.

    Serializes each card via FeedCardData.to_dict().
    Creates .crabcakes/ directory if it doesn't exist.
    Logs errors instead of raising.

    Thread safety (§2.2.3): gains the feed flock — an unlocked whole-file
    write would race every other mutation. On lock timeout the write is
    skipped with a WARNING (never unbounded, never corrupting). Callers doing
    load→modify→save should still prefer append_feed_card /
    update_feed_card. `path` is bound before the try so the error log can
    never raise NameError when directory creation itself fails.
    """
    path = _feed_path(project_path)
    fd = None
    lock_path = None
    try:
        _ensure_crabcakes_dir(project_path)
        _ensure_gitignore_entry(project_path, ".crabcakes/feed.json")
        acquired = _acquire_lock(path)
        if acquired is None:
            _logger.warning("save_feed: lock busy for %s — write skipped", path)
            return
        fd, lock_path = acquired
        _atomic_write_json(path, [c.to_dict() for c in cards], compact=True)
    except OSError as e:
        _logger.error("save_feed: failed to write %s: %s", path, e)
    finally:
        if fd is not None:
            _release_lock(fd, lock_path)


def append_feed_card(project_path: str, card: FeedCardData) -> None:
    """
    Append a single card to the existing feed file.
    Locks -> loads -> appends -> saves -> unlocks. Atomic under flock.

    The lock is released BEFORE the post-append compaction check so the two
    never nest (`compact_feed` takes the same lock) — invariant 8.
    """
    path = _feed_path(project_path)
    _ensure_crabcakes_dir(project_path)
    _ensure_gitignore_entry(project_path, ".crabcakes/feed.json")
    acquired = _acquire_lock(path)
    if acquired is None:
        _logger.warning(
            "append_feed_card: lock busy for %s — card not appended", path
        )
        return
    fd, lock_path = acquired
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
        cards = _parse_cards(raw_cards)
        # Append + Write
        cards.append(card)
        try:
            _atomic_write_json(path, [c.to_dict() for c in cards], compact=True)
        except OSError as e:
            _logger.error("append_feed_card: failed to write %s: %s", path, e)
    finally:
        _release_lock(fd, lock_path)
    # Post-append size check, lock released (D6): an append-only feed would
    # otherwise never trigger a compaction.
    _maybe_compact(project_path)


def _maybe_compact(project_path: str) -> None:
    """Rate-limited post-append compaction trigger.

    At most one append-triggered compact per project per
    `_COMPACT_MIN_INTERVAL` (60 s): under a sustained high append rate a
    compact that takes seconds would otherwise re-trigger on nearly every
    append (the count re-crosses the soft bound while the compact runs —
    audit r3 #5). Called with NO lock held; `compact_feed` takes its own.
    Concurrent callers serialize on the flock and a loser's fold is a
    harmless no-op.

    The rate-limit timestamp is recorded BEFORE the size check — a compact
    that finds the feed under the bound still spends the interval, which
    prevents re-check thrash.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return
    now = time.monotonic()
    with _compact_rl_lock:
        if now - _compact_last.get(project_path, 0.0) < _COMPACT_MIN_INTERVAL:
            return
        _compact_last[project_path] = now
    try:
        with open(path, "r", encoding="utf-8") as f:
            n = len(json.load(f))
    except (OSError, json.JSONDecodeError, TypeError):
        return
    if n > FEED_WINDOW_DEFAULT * 1.25:
        compact_feed(project_path, window=FEED_WINDOW_DEFAULT)


def _is_pinned_card(card: FeedCardData) -> bool:
    """§2.3.2 retention pin — a card that must NEVER be pruned.

    Pinned when any of: an accept/reject decision is already recorded
    (`accepted is not None` — pruning it would orphan the decision and the
    seq narrative); it is still actionable (`metadata.needs_review` /
    `metadata.needs_approval` — `update_feed_card` would silently return
    False after pruning); or it is a `git_commit` card (cheap, few, and
    referenced by review history).
    """
    if card.accepted is not None:
        return True
    if card.card_type == "git_commit":
        return True
    meta = card.metadata or {}
    return bool(meta.get("needs_review") or meta.get("needs_approval"))


def compact_feed(project_path: str, window: int | None = None) -> int:
    """Fold the journal into feed.json, applying the sliding window.

    Returns the number of cards pruned (`0` when `window is None` or when
    nothing falls outside the retention rules).

    Runs under ONE feed-flock hold: read the snapshot inline via the shared
    `_parse_cards` (deliberately NOT via `load_feed` — that would re-enter
    the lock), apply the overlay with the same merge rules as `load_feed`,
    write the merged snapshot atomically (compact JSON), then truncate the
    journal. Crash-safety ordering: the snapshot replace happens FIRST and
    the journal truncate SECOND, so a crash between them leaves an unfolded
    journal whose replay is idempotent. On success the rate-limit timestamp
    is recorded so every trigger path shares one budget.

    `window` = the number of NEWEST cards retained by list order (§2.3.2).
    Cards outside that slice are pruned UNLESS pinned (`_is_pinned_card`):
    an accepted/rejected decision, a needs_review/needs_approval card, or a
    git_commit card. Pruning preserves chronological order (pinned older
    cards keep their original position — they are not re-appended). A
    WARNING reports the prune count and how many cards the pins rescued.
    """
    path = _feed_path(project_path)
    jp = _journal_path(project_path)
    if not os.path.isfile(path):
        return 0

    acquired = _acquire_lock(path)
    if acquired is None:
        _logger.warning(
            "compact_feed: lock busy for %s — compaction skipped", path
        )
        return 0
    fd, lock_path = acquired
    try:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _logger.warning("compact_feed: failed to read %s: %s", path, e)
            return 0

        cards = _parse_cards(raw)
        overlay = _replay_journal(project_path)
        _apply_overlay(cards, overlay)

        pruned = 0
        if window is not None:
            # §2.3.2: keep the newest `window` by list order, then ALSO keep
            # any pinned card from outside that slice. Chronological order is
            # preserved — a rescued old card keeps its position rather than
            # being re-appended at the end.
            slice_start = max(0, len(cards) - window)
            kept = [
                c for i, c in enumerate(cards)
                if i >= slice_start or _is_pinned_card(c)
            ]
            pruned = len(cards) - len(kept)
            if pruned:
                pinned_kept = sum(
                    1 for i, c in enumerate(cards)
                    if i < slice_start and _is_pinned_card(c)
                )
                _logger.warning(
                    "compact_feed: pruned %d oldest cards (%d outside-window "
                    "cards pinned) from %s (window=%s)",
                    pruned, pinned_kept, project_path, window,
                )
            cards = kept

        try:
            _atomic_write_json(path, [c.to_dict() for c in cards], compact=True)
        except OSError as e:
            _logger.error("compact_feed: failed to write %s: %s", path, e)
            return 0

        # Truncate SECOND: the snapshot is durable and replay is idempotent,
        # so a crash here is safe (the folded journal simply replays again).
        try:
            with open(jp, "w", encoding="utf-8"):
                pass
        except OSError as e:
            _logger.warning("compact_feed: failed to truncate %s: %s", jp, e)
    finally:
        _release_lock(fd, lock_path)

    with _compact_rl_lock:
        _compact_last[project_path] = time.monotonic()
    return pruned


def update_feed_card(project_path: str, card_id: str, updates: dict) -> bool | None:
    """Record a card update. True = safely recorded (journaled or written).

    Hot path is O(1): append one journal line, and compact when the journal
    exceeds `JOURNAL_COMPACT_THRESHOLD`. Card existence is NOT checked on the
    hot path — it cannot be known in O(1), and the update does not need it
    (replay applies the record whenever the card appears). Stale records for
    cards that never exist are dropped at replay/compaction.

    Returns:
      True  — recorded (journal line written, or the legacy write succeeded).
              A compaction failure does NOT affect this: the journal line is
              already durable, so the fold is retried naturally by the next
              threshold crossing (audit r3 #1).
      False — write failure (journal append failed AND the legacy write
              failed: lock timeout or OSError). The Phase-1 writer defers and
              retries.
      None  — the legacy path ran and the card was not found (pruned between
              enqueue and drain). The writer logs INFO and drops it; retrying
              a gone card is futile.
    """
    ok = append_card_update(project_path, card_id, updates)
    if ok:
        try:
            if _journal_line_count(project_path) >= JOURNAL_COMPACT_THRESHOLD:
                # Phase 3 supplies the retention rules (§2.3): the fold now
                # applies the sliding window + pins.
                compact_feed(project_path, window=FEED_WINDOW_DEFAULT)
        except Exception:  # noqa: BLE001 — compaction is orthogonal to durability
            _logger.warning(
                "update_feed_card: post-append compaction failed for %s "
                "(will retry at next threshold)", project_path,
            )
        return True
    return _update_feed_card_legacy(project_path, card_id, updates)


def _update_feed_card_legacy(
    project_path: str, card_id: str, updates: dict
) -> bool | None:
    """Legacy read-modify-write fallback for a failed journal append.

    Preserves the pre-journal semantics (lock → load → find → setattr over
    `_UPDATABLE_FIELDS` → atomic write), with a tri-state return (audit r4
    #14/#18): True = found + written; False = write failure (lock timeout /
    OSError / non-serializable payload); None = card not found. `TypeError`
    is caught alongside `OSError` so a non-serializable payload can never
    crash the caller or leave a corrupt file — the `.tmp` write fails before
    `os.replace`, so the snapshot is untouched.
    """
    path = _feed_path(project_path)
    if not os.path.isfile(path):
        return None  # no snapshot → the card cannot exist
    _ensure_crabcakes_dir(project_path)
    _ensure_gitignore_entry(project_path, ".crabcakes/feed.json")
    acquired = _acquire_lock(path)
    if acquired is None:
        _logger.warning(
            "_update_feed_card_legacy: lock busy for %s — write skipped", path
        )
        return False
    fd, lock_path = acquired
    try:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_cards = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            _logger.warning("update_feed_card: failed to read %s: %s", path, e)
            return False
        cards = _parse_cards(raw_cards)
        for c in cards:
            if c.card_id == card_id:
                for key, val in updates.items():
                    if key in _UPDATABLE_FIELDS and hasattr(c, key):
                        setattr(c, key, val)
                try:
                    _atomic_write_json(
                        path, [cd.to_dict() for cd in cards], compact=True
                    )
                except (OSError, TypeError) as e:
                    _logger.error(
                        "update_feed_card: failed to write %s: %s", path, e
                    )
                    return False
                return True
        return None
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
                    scope = str(fc.get("agent_scope", "first_author"))
                    # Guard: migrate stale "system" scope (from v1 migration
                    # or test artifacts) to "all_agents". "system" is not a
                    # valid scope value — _agent_scope_matches treats it as a
                    # literal agent name, causing every auto-accept check to
                    # silently fail. See deep-dive report 2026-06-30.
                    if scope == "system":
                        scope = "all_agents"
                    result["auto_accept"]["file_changes"][ct]["agent_scope"] = scope
        exec_raw = auto.get("exec_command", {})
        if isinstance(exec_raw, dict):
            result["auto_accept"]["exec_command"]["mode"] = str(
                exec_raw.get("mode", "off")
            )
            exec_scope = str(exec_raw.get("agent_scope", "first_author"))
            if exec_scope == "system":
                exec_scope = "all_agents"
            result["auto_accept"]["exec_command"]["agent_scope"] = exec_scope
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
