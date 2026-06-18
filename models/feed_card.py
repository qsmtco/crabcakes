# models/feed_card.py
# Feed card data models — pure Python, no GTK, no git, no network.
#
# Architecture: foundation that ui/ depends on — not the other way around.
# Zero imports from ui/, gateway/, agent/, subprocess.
#
# Files that import these:
#   - ui/handlers/feed_handler.py (FeedHandler owns card lifecycle)
#   - ui/handlers/chat_render_handler.py (crabcard extraction)
#   - ui/views/feed_card.py (factory — reads FeedCardData to build widgets)
#   - utils/crabcard_parser.py (parses raw text → FeedCardData)
#   - tests/ (unit tests)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from models.conversation_snapshot import ConversationSnapshot

# Supported card types — exhaustive list for Phase 1
CardType = Literal[
    "git_commit",
    "diff",
    "file_created",
    "file_modified",
    "file_deleted",
    "dir_created",
    "dir_deleted",
    "agent_action",
    "task",
    "system",
    "audit_report",
]

# Supported sources
CardSource = Literal["agent", "system", "git", "crabwatch"]


@dataclass
class FeedCardData:
    """Structured data for a project feed card.

    No GTK, no git calls, no network. Pure data container.
    """
    card_type: CardType
    source: CardSource
    title: str
    body: str
    author: str
    timestamp: datetime
    project_name: str

    # Optional context fields
    file_path: str | None = None
    commit_sha: str | None = None
    additions: int | None = None
    deletions: int | None = None
    task_id: str | None = None
    metadata: dict = field(default_factory=dict)

    # Conversation snapshot (set by FeedHandler at card creation time)
    conversation_snapshot: ConversationSnapshot | None = None

    # Runtime fields (set by FeedHandler, not by source)
    card_id: str | None = None
    reviewed: bool = False
    accepted: bool | None = None  # True=accepted, False=rejected, None=pending
    seq_num: int | None = None  # Sequential display number (per project)

    @staticmethod
    def css_class_for_type(card_type: CardType) -> str:
        """Return CSS class name for a card type."""
        mapping: dict[CardType, str] = {
            "git_commit": "feed-card-git",
            "diff": "feed-card-diff",
            "file_created": "feed-card-file-new",
            "file_modified": "feed-card-file-mod",
            "file_deleted": "feed-card-file-del",
            "dir_created": "feed-card-dir-new",
            "dir_deleted": "feed-card-dir-del",
            "agent_action": "feed-card-agent",
            "task": "feed-card-task",
            "system": "feed-card-system",
            "audit_report": "feed-card-audit",
        }
        return mapping.get(card_type, "feed-card-system")

    @staticmethod
    def is_actionable(card_type: CardType, metadata: dict | None = None) -> bool:
        """True if this card type requires user action (Accept/Reject/Approve/Deny)."""
        # Approval-request cards (exec_command needing approval)
        if metadata and metadata.get("needs_approval"):
            return True
        # File-change cards that have git backing (can be accepted/rejected)
        if card_type in ("diff", "file_created", "file_modified", "file_deleted"):
            return True
        return False

    @staticmethod
    def is_informational(card_type: CardType, metadata: dict | None = None) -> bool:
        """True if this card is purely informational — no buttons needed."""
        # Approval cards are actionable, not informational
        if metadata and metadata.get("needs_approval"):
            return False
        # git_commit: result of accept/reject — informational
        if card_type == "git_commit":
            return True
        # agent_action with status=running/complete/error: tool execution log.
        # Also include status=None: a crabcard-parsed or manually-created
        # agent_action card with no status field is still informational (a
        # tool execution log), not actionable. Without this, the card would
        # show Accept/Reject buttons that do nothing.
        if card_type == "agent_action":
            status = metadata.get("status") if metadata else None
            if status in (None, "running", "complete", "error"):
                return True
        # system events, audit reports, tasks: informational
        if card_type in ("system", "audit_report", "task", "dir_created", "dir_deleted"):
            return True
        return False

    # ── Serialization (for feed.json persistence) ───────────────────────

    def _serialize_metadata_with_snapshot(self) -> dict:
        """Serialize metadata dict, injecting snapshot if present."""
        meta = dict(self.metadata) if self.metadata else {}
        if self.conversation_snapshot is not None:
            meta["snapshot"] = self.conversation_snapshot.to_dict()
        else:
            meta.pop("snapshot", None)
        return meta

    def to_dict(self) -> dict:
        """
        Serialize to a JSON-compatible dict. Includes all fields.
        Runtime fields (card_id, reviewed, accepted) are included so that
        FeedHandler can persist state changes (accept/reject) back to feed.json.
        """
        return {
            "card_type": self.card_type,
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "author": self.author,
            "timestamp": self.timestamp.isoformat(),
            "project_name": self.project_name,
            "file_path": self.file_path,
            "commit_sha": self.commit_sha,
            "additions": self.additions,
            "deletions": self.deletions,
            "task_id": self.task_id,
            "metadata": self._serialize_metadata_with_snapshot(),
            "card_id": self.card_id,
            "reviewed": self.reviewed,
            "accepted": self.accepted,
            "seq_num": self.seq_num,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FeedCardData":
        """
        Deserialize from a dict (e.g., loaded from feed.json).
        Handles both legacy dicts (no card_id/running fields) and current format.
        """
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        # Deserialize snapshot from metadata if present
        metadata = data.get("metadata", {})
        snapshot = None
        if metadata and "snapshot" in metadata:
            from models.conversation_snapshot import ConversationSnapshot
            snapshot = ConversationSnapshot.from_dict(metadata["snapshot"])

        return cls(
            card_type=data["card_type"],
            source=data["source"],
            title=data["title"],
            body=data.get("body", ""),
            author=data.get("author", "unknown"),
            timestamp=ts,
            project_name=data["project_name"],
            file_path=data.get("file_path"),
            commit_sha=data.get("commit_sha"),
            additions=data.get("additions"),
            deletions=data.get("deletions"),
            task_id=data.get("task_id"),
            metadata=metadata,
            card_id=data.get("card_id"),
            reviewed=data.get("reviewed", False),
            accepted=data.get("accepted"),
            seq_num=data.get("seq_num"),
            conversation_snapshot=snapshot,
        )