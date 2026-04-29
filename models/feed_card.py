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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

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

    # Runtime fields (set by FeedHandler, not by source)
    card_id: str | None = None
    reviewed: bool = False
    accepted: bool | None = None  # True=accepted, False=rejected, None=pending

    @staticmethod
    def css_class_for_type(card_type: CardType) -> str:
        """Return CSS class name for a card type."""
        mapping: dict[CardType, str] = {
            "git_commit": "feed-card-git",
            "diff": "feed-card-diff",
            "file_created": "feed-card-file-new",
            "file_modified": "feed-card-file-new",
            "file_deleted": "feed-card-file-del",
            "dir_created": "feed-card-dir-new",
            "dir_deleted": "feed-card-dir-del",
            "agent_action": "feed-card-agent",
            "task": "feed-card-task",
            "system": "feed-card-system",
        }
        return mapping.get(card_type, "feed-card-system")

    # ── Serialization (for feed.json persistence) ───────────────────────

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
            "metadata": self.metadata,
            "card_id": self.card_id,
            "reviewed": self.reviewed,
            "accepted": self.accepted,
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
            metadata=data.get("metadata", {}),
            card_id=data.get("card_id"),
            reviewed=data.get("reviewed", False),
            accepted=data.get("accepted"),
        )