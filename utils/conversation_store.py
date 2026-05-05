# utils/conversation_store.py
# Snapshot creation utilities — creates ConversationSnapshot data objects
# from plain Python data (message lists) and git diffs.
#
# Architecture: utils/ package — may import from models/ only. No GTK, no network.
# Zero GTK imports or GTK method calls. The caller (ui/handlers/) is responsible
# for extracting message data from GTK widgets before calling these functions.
#
# Files that import these:
#   - ui/handlers/feed_handler.py (creates snapshots at card creation time)

import logging
import sys

from models.conversation_snapshot import ConversationSnapshot, SnapshotMessage

_logger = logging.getLogger(__name__)

# ── Configurable limits ────────────────────────────────────────────────────
# ⚠️ SNAPSHOT MESSAGE LIMIT — Captain decision: 5 messages max.
# Adjust this constant to capture more/fewer messages per snapshot.
MAX_SNAPSHOT_MESSAGES: int = 5

# Maximum characters per individual message before truncation.
MAX_CHARS_PER_MESSAGE: int = 2000

# ⚠️ SNAPSHOT SIZE CAP — Captain decision: 50KB.
# Snapshots exceeding this are rendered in-memory but NOT persisted to feed.json.
MAX_SNAPSHOT_SIZE_KB: int = 50
MAX_SNAPSHOT_SIZE_BYTES: int = MAX_SNAPSHOT_SIZE_KB * 1024


def snapshot_from_messages(
    messages_raw: list[tuple[str, str]],
    session_key: str,
    total_available: int | None = None,
    max_messages: int = MAX_SNAPSHOT_MESSAGES,
    max_chars_per_message: int = MAX_CHARS_PER_MESSAGE,
) -> ConversationSnapshot:
    """
    Create a conversation snapshot from a list of (role, text) message pairs.

    The caller extracts messages from GTK widgets (or any source) and passes
    them as plain Python tuples. This function is pure Python — no GTK dependency.

    Args:
        messages_raw: List of (role, text) tuples, oldest first.
        session_key: Session key for context.
        total_available: Total messages available (may exceed len(messages_raw)).
            If None, uses len(messages_raw).
        max_messages: Max messages to include (default: MAX_SNAPSHOT_MESSAGES).
            Takes from the END (most recent) of messages_raw.
        max_chars_per_message: Truncate messages longer than this.

    Returns:
        ConversationSnapshot with snapshot_type="conversation".
    """
    total = total_available if total_available is not None else len(messages_raw)

    # Take the last max_messages (most recent)
    recent = messages_raw[-max_messages:] if len(messages_raw) > max_messages else messages_raw

    messages: list[SnapshotMessage] = []
    for role, text in recent:
        if not role or not text:
            continue
        # Truncate long messages
        if len(text) > max_chars_per_message:
            text = text[:max_chars_per_message] + "…"
        messages.append(SnapshotMessage(role=role, text=text))

    return ConversationSnapshot(
        snapshot_type="conversation",
        messages=messages,
        session_key=session_key,
        total_messages=total,
    )


def snapshot_from_git_diff(
    project_path: str,
    file_path: str,
) -> ConversationSnapshot:
    """
    Create a snapshot from git diff for a file change.

    Uses git_ops to get the diff. If the repo has no HEAD (new repo),
    returns a snapshot noting no diff is available.

    Args:
        project_path: Absolute path to the project root.
        file_path: Relative path to the changed file.

    Returns:
        ConversationSnapshot with snapshot_type="diff".
    """
    from utils import git_ops

    diff_text = ""

    # Try diff of working tree against HEAD (unstaged + staged changes)
    result = git_ops.diff_working_tree(project_path, file_path)
    if result.success and result.stdout.strip():
        diff_text = result.stdout
    else:
        # Maybe no commits yet or file is untracked
        status_result = git_ops.status(project_path)
        if status_result.success:
            # Check if file appears in status output (untracked or modified)
            if file_path in status_result.stdout:
                diff_text = f"(Unstaged/untracked changes for {file_path})"
            else:
                diff_text = ""
        else:
            diff_text = ""

    # Cap diff text size
    if len(diff_text) > MAX_CHARS_PER_MESSAGE * 5:  # ~10KB for diffs
        diff_text = diff_text[:MAX_CHARS_PER_MESSAGE * 5] + "\n… (truncated)"

    # Binary file detection
    if "Binary files" in diff_text and len(diff_text) < 200:
        diff_text = "Binary file changed."

    return ConversationSnapshot(
        snapshot_type="diff",
        diff_text=diff_text,
    )


def snapshot_exceeds_size_limit(snapshot: ConversationSnapshot) -> bool:
    """Check if a snapshot exceeds the MAX_SNAPSHOT_SIZE_BYTES limit."""
    import json
    try:
        data = snapshot.to_dict()
        size = len(json.dumps(data).encode("utf-8"))
        return size > MAX_SNAPSHOT_SIZE_BYTES
    except Exception:
        return False
