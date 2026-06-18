# models package
# Pure data layer — no GTK, no network, no file I/O.
#
# Architecture rule: models/ must NEVER import from ui/, gateway/, or agent/.
# All imports are stdlib only (dataclasses, datetime, enum, typing).

from .agents import AgentManager
from .colors import (
    next_agent_color,
    reset_color_indices,
)
from .command import Command, CommandResult, CommandRegistry
from .routing import AgentRoutingTable
from .streaming import StreamingBubble
from .task import Task, TaskStore, TASK_STATUS_LABELS, PRIORITY_LABELS
from .feed_card import FeedCardData
from .activity import ActivityBubble, ToolStatus
from .conversation import Conversation, Message, MessageRole, ToolCall, ToolCallStatus
from .conversation_snapshot import ConversationSnapshot, SnapshotMessage
from .review_state import ReviewState
from .team import TeamMember, ProjectTeam

task_store = TaskStore()

__all__ = [
    # agents
    "AgentManager",
    # routing
    "AgentRoutingTable",
    # command
    "Command",
    "CommandResult",
    "CommandRegistry",
    # feed
    "FeedCardData",
    # streaming
    "StreamingBubble",
    # activity (Phase 2 — SPEC-smarter-chat-ux)
    "ActivityBubble",
    "ToolStatus",
    # conversation
    "Conversation",
    "Message",
    "MessageRole",
    "ToolCall",
    "ToolCallStatus",
    # conversation_snapshot
    "ConversationSnapshot",
    "SnapshotMessage",
    # review_state
    "ReviewState",
    # team
    "TeamMember",
    "ProjectTeam",
    # task
    "Task",
    "TaskStore",
    "task_store",
    "TASK_STATUS_LABELS",
    "PRIORITY_LABELS",
    # colors
    "next_agent_color",
    "reset_color_indices",
]
