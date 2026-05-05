# models/conversation_snapshot.py
# Conversation snapshot data models — pure Python, no GTK, no git, no network.
#
# Architecture: foundation that ui/ depends on — not the other way around.
# Zero imports from ui/, gateway/, agent/.
#
# Files that import these:
#   - utils/conversation_store.py (snapshot creation)
#   - models/feed_card.py (snapshot field on FeedCardData)
#   - ui/views/feed_card.py (context panel rendering)

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

SnapshotType = Literal["conversation", "diff"]


@dataclass
class SnapshotMessage:
    """A single message in a conversation snapshot."""
    role: str           # "User" | "Agent" | "System"
    text: str           # Message content (plain text, truncated if long)
    timestamp: str | None = None   # ISO format, optional

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotMessage":
        return cls(
            role=data.get("role", "System"),
            text=data.get("text", ""),
            timestamp=data.get("timestamp"),
        )


@dataclass
class ConversationSnapshot:
    """
    A frozen snapshot of conversation context that produced a feed card.

    For agent cards: contains the last N messages from the chat session.
    For system cards: contains a git diff string.
    """
    snapshot_type: SnapshotType  # "conversation" | "diff"
    messages: list[SnapshotMessage] = field(default_factory=list)  # for "conversation"
    diff_text: str = ""                                            # for "diff"
    session_key: str = ""         # session that produced this card
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # How many messages were available (may be > len(messages) if truncated)
    total_messages: int = 0

    def to_dict(self) -> dict:
        return {
            "snapshot_type": self.snapshot_type,
            "messages": [m.to_dict() for m in self.messages],
            "diff_text": self.diff_text,
            "session_key": self.session_key,
            "captured_at": self.captured_at.isoformat(),
            "total_messages": self.total_messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationSnapshot":
        ts = data.get("captured_at")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        return cls(
            snapshot_type=data.get("snapshot_type", "conversation"),
            messages=[SnapshotMessage.from_dict(m) for m in data.get("messages", [])],
            diff_text=data.get("diff_text", ""),
            session_key=data.get("session_key", ""),
            captured_at=ts,
            total_messages=data.get("total_messages", 0),
        )
