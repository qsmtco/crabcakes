# utils/review_log.py
# Review history persistence for structured audit reports.
#
# Manages .crabcakes/review-log.jsonl — append-only JSONL log of all
# audit reports with reviewer, target_role, and SPEC-4 dream data.
#
# Architecture: pure utility — no GTK, no network.
#
# Spec reference: SPEC-3 §3.2

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


REVIEW_LOG_FILENAME = "review-log.jsonl"
DREAM_LOG_FILENAME = "dream-log.jsonl"  # LOW-A10: dream-engine subsystem is deferred; constant kept for future use


def get_review_log_path(project_path: str) -> str:
    """Return the path to the review log for a project."""
    return os.path.join(project_path, ".crabcakes", REVIEW_LOG_FILENAME)


def get_dream_log_path(project_path: str) -> str:
    """Return the path to the dream log for a project."""
    return os.path.join(project_path, ".crabcakes", DREAM_LOG_FILENAME)


def append_review_entry(project_path: str, entry: dict) -> None:
    """Append a single entry to the review log.

    Creates .crabcakes/ directory and the log file if they don't exist.

    Args:
        project_path: Absolute path to the project root.
        entry: Dict to serialize as a JSON line. Must be JSON-serializable.
    """
    log_path = get_review_log_path(project_path)

    # Ensure .crabcakes/ directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    line = json.dumps(entry, ensure_ascii=False)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_review_log(project_path: str, since: str | None = None) -> list[dict]:
    """Read entries from the review log, oldest first.

    Args:
        project_path: Absolute path to the project root.
        since: Optional ISO timestamp — only return entries with
            timestamp > since (strictly after).

    Returns:
        List of parsed JSON dicts, oldest first. Malformed lines are skipped.
    """
    log_path = get_review_log_path(project_path)
    if not os.path.isfile(log_path):
        return []

    entries: list[dict] = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if since and _timestamp_le(
                    entry.get("timestamp", ""), since
                ):
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue  # Skip malformed lines

    return entries


def get_last_dream_timestamp(project_path: str) -> str | None:
    """Return the timestamp of the last completed dream cycle for this project.

    Reads .crabcakes/dream-log.jsonl and returns the timestamp from the
    most recent entry with status == "completed". Returns None if no
    completed dream has been recorded.
    """
    dream_log = get_dream_log_path(project_path)
    if not os.path.isfile(dream_log):
        return None

    last_ts: str | None = None
    with open(dream_log, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("status") == "completed":
                    last_ts = entry.get("timestamp")
            except json.JSONDecodeError:
                continue

    return last_ts


def _timestamp_le(ts1: str, ts2: str) -> bool:
    """Return True if ts1 <= ts2 (lexicographic after normalization).

    Normalizes both timestamps to UTC datetime before comparison to handle
    mixed formats (e.g. Z vs +00:00 vs microseconds). String comparison
    alone fails for formats like "2026-05-18T20:00:00.000000Z" vs "2026-05-18T20:00:00Z"
    because '.' < 'Z' in ASCII.
    """
    dt1 = _parse_timestamp(ts1)
    dt2 = _parse_timestamp(ts2)
    if dt1 is None or dt2 is None:
        return ts1 <= ts2  # Fall back to string comparison if parse fails
    return dt1 <= dt2


_TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%S+00:00",
)


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp to a timezone-aware UTC datetime.


    Tries multiple common formats used in JSONL logs.
    Returns None if the timestamp doesn't match any known format.
    """
    for fmt in _TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(ts, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None