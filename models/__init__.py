# models package

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

task_store = TaskStore()

__all__ = [
    "AgentManager",
    "AgentRoutingTable",
    "Command",
    "CommandResult",
    "CommandRegistry",
    "FeedCardData",
    "StreamingBubble",
    "next_agent_color",
    "reset_color_indices",
]
