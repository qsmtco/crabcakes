# models/activity.py
# ActivityBubble dataclass — Phase 2 of SPEC-smarter-chat-ux.
#
# Pure data container. No GTK, no gateway calls, no state.
# ActivityHandler populates these from gateway events.
# ChatHandler renders them via build_role_bubble() with role="System".

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# Supported activity types — exhaustive list from gateway event catalog
ActivityType = Literal[
    "lifecycle_start",   # agent started
    "tool_start",        # tool call began
    "tool_end",          # tool call completed
    "tool_error",        # tool call failed
    "plan",              # plan update from update_plan
    "approval_request",  # exec approval needed
    "command_output",    # shell command finished
    "patch",             # file edit summary
]


class ToolStatus(Enum):
    """Status of a tool invocation — used for icon selection."""
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


@dataclass
class ActivityBubble:
    """
    Structured data for an activity bubble — ephemeral system-styled status indicator.

    Populated by ActivityHandler from gateway events.
    Rendered by ChatHandler via build_role_bubble(role="System", text=...).

    Attributes:
        type:       Which activity type this bubble represents
        session_key: Which session/tab this belongs to
        tool_name:  For tool_* types — which tool (e.g. "web_search")
        duration_ms: For tool_end / command_output — elapsed time
        status:     For tool_* — RUNNING / SUCCESS / ERROR
        icon:       Emoji icon prefix (e.g. "🔧", "✅", "❌")
        title:      For plan type — plan title
        steps:      For plan type — list of step descriptions
        command:    For approval_request — the command needing approval
        approval_id: For approval_request — gateway approval ID
        reason:     For approval_request — why approval is needed
        exit_code:  For command_output — shell exit code
        added:      For patch — number of files added
        modified:   For patch — number of files modified
        deleted:    For patch — number of files deleted
        raw_text:   Human-readable one-line description for the bubble text
    """

    type: ActivityType
    session_key: str
    tool_name: str = ""
    duration_ms: int = 0
    status: ToolStatus = ToolStatus.RUNNING
    icon: str = "▶"
    title: str = ""
    steps: list[str] = field(default_factory=list)
    command: str = ""
    approval_id: str = ""
    reason: str = ""
    exit_code: int = 0
    added: int = 0
    modified: int = 0
    deleted: int = 0
    raw_text: str = ""
    # SPEC-activity-drawer Phase 1: enrichment fields for the drawer view.
    # Defaulted to "" so existing call sites that don't supply them still work.
    agent_name: str = ""      # Display name of the agent that emitted the event (e.g. "Coder")
    file_path: str = ""       # Relative file path for read/write/edit events
    output: str = ""          # Last N lines of stdout/stderr for command_output click-to-expand

    def format_text(self) -> str:
        """
        Build the human-readable one-line text for this activity bubble.

        Called by ChatHandler when rendering. All formatting lives here —
        keeping ActivityBubble focused on data, ChatHandler focused on GTK.

        No emoji icons — uses subtle unicode and clean formatting.
        """
        if self.type == "lifecycle_start":
            return "thinking..."
        elif self.type == "tool_start":
            name = _friendly_tool_name(self.tool_name)
            return f"{name}"
        elif self.type == "tool_end":
            name = _friendly_tool_name(self.tool_name)
            ms = self.duration_ms
            if ms > 0:
                return f"{name}  {ms:,}ms"
            return f"{name}  done"
        elif self.type == "tool_error":
            name = _friendly_tool_name(self.tool_name)
            return f"{name}  failed"
        elif self.type == "plan":
            text = f"plan: {self.title}"
            if self.steps:
                text += f"  {len(self.steps)} steps"
            return text
        elif self.type == "approval_request":
            cmd = self.command
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            return f"approve: {cmd}"
        elif self.type == "command_output":
            name = _friendly_tool_name(self.tool_name)
            ms = self.duration_ms
            if self.exit_code != 0:
                return f"{name}  exit {self.exit_code}  {ms:,}ms"
            return f"{name}  {ms:,}ms"
        elif self.type == "patch":
            parts = []
            if self.added:
                parts.append(f"+{self.added}")
            if self.modified:
                parts.append(f"~{self.modified}")
            if self.deleted:
                parts.append(f"-{self.deleted}")
            label = " ".join(parts) if parts else "no changes"
            return f"{self.tool_name}  {label}"
        else:
            return self.raw_text or self.type

    def to_drawer_row(self) -> dict:
        """
        Build the dict the ActivityDrawer view consumes.

        The drawer (ui/views/activity_drawer.py) expects a flat dict with these
        keys (see _format_summary and _build_row_widget):
            agent, agent_name, session_key, activity_type, icon, type_label,
            title, command, file_path, output, exit_code, duration, duration_ms,
            timestamp, raw_text, added, modified, deleted

        Notes:
        - The drawer reads `agent` (not `agent_name`); we map agent_name → agent.
        - `type_label` is a human label derived from activity_type.
        - `duration` is a pre-formatted string (e.g. "1.2s"); duration_ms is the raw int.
        - `timestamp` is HH:MM:SS formatted for header display; None until set by caller.

        Returns:
            A new dict. Safe to mutate by the caller.
        """
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        return {
            "agent": self.agent_name or "Agent",
            "agent_name": self.agent_name,
            "session_key": self.session_key,
            "activity_type": self.type,
            "icon": self.icon,
            "type_label": _type_label(self.type),
            "title": self.title,
            "command": self.command,
            "file_path": self.file_path,
            "output": self.output,
            "exit_code": self.exit_code if self.type == "command_output" else None,
            "duration": _format_duration(self.duration_ms) if self.duration_ms else "",
            "duration_ms": self.duration_ms,
            "timestamp": ts,
            "raw_text": self.raw_text,
            "added": self.added,
            "modified": self.modified,
            "deleted": self.deleted,
        }


def _type_label(activity_type: str) -> str:
    """
    Map an ActivityType literal to a short human label for the drawer row.

    Mirrors the helper in ui/views/activity_drawer.py — both modules use the
    same logic. Keep in sync if you change one.

    Returns the input verbatim if no mapping exists.
    """
    if not activity_type:
        return ""
    mapping = {
        "command_output": "exec",
        "lifecycle_start": "lifecycle",
        "lifecycle_end": "lifecycle",
        "plan": "plan",
        "approval_request": "approval",
        "patch": "patch",
        "tool_start": "tool",
        "tool_end": "tool",
        "tool_error": "tool",
    }
    return mapping.get(activity_type, activity_type)


def _format_duration(ms: int) -> str:
    """
    Format a duration in milliseconds as a short human string.

    Mirrors the helper in ui/views/activity_drawer.py — both modules use the
    same logic. Keep in sync if you change one.

    Rules:
    - ms < 1000      → "Nms"            (e.g. "847ms")
    - ms < 60_000    → "N.Ns"           (e.g. "1.2s")
    - ms >= 60_000   → "Nm Ns"          (e.g. "1m 23s")
    - ms <= 0        → ""               (no duration to show)
    """
    if ms is None or ms <= 0:
        return ""
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    minutes, secs = divmod(ms // 1000, 60)
    return f"{minutes}m {secs}s"


def _friendly_tool_name(name: str) -> str:
    """Convert tool_name to a cleaner display name."""
    # Map of known tool names to friendly labels
    _names = {
        "web_search": "search",
        "web_fetch": "fetch",
        "exec": "exec",
        "read": "read",
        "write": "write",
        "edit": "edit",
        "image": "image",
        "image_generate": "generate image",
        "music_generate": "generate music",
        "video_generate": "generate video",
        "memory_search": "memory",
        "memory_get": "recall",
        "cron": "schedule",
        "sessions_spawn": "spawn",
        "sessions_send": "message",
        "sessions_list": "sessions",
        "update_plan": "plan",
        "session_status": "status",
    }
    return _names.get(name, name.replace("_", " "))
