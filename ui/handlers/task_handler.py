# ui/handlers/task_handler.py
# Task command implementations — extracted from window.py Phase 7.
#
# Manifest:
#   reads:   models.task (TaskStore, Task, TASK_STATUS_LABELS, PRIORITY_LABELS)
#   writes:  nothing
#   network: nothing
#   GTK:     on_display_card() callback only (cards rendered by window)
#
# Owns: 8 task commands — task, done, start, blocked, cancel, tasks, assign, priority
# Does NOT own: GTK widgets, MainContent, gateway client, TaskStore instance
#
# Dependencies injected via __init__:
#   on_display_card: callback(card: dict) — render a card in project tab chat
#   on_display_text: callback(text: str) — display text in project tab chat
#   GLib_module:      gi.repository.GLib — for thread-safe GTK dispatch (future)
#
# Architecture: pure Python. No imports from ui/, gateway/, or agent/.


from datetime import datetime, timezone

from models.command import Command, CommandResult
from models.feed_card import FeedCardData
from models.task import Task, TaskStore, TASK_STATUS_LABELS, PRIORITY_LABELS


# Module-level task store singleton — same pattern as window.py
# TaskStore is NOT persisted; lives in memory for the session.
from models import task_store


class TaskHandler:
    """
    Handles task command execution.

    All 8 commands (task, done, start, blocked, cancel, tasks, assign, priority)
    are implemented here as pure Python. No GTK, no network.

    Args:
        on_display_card: callback(card: dict) — display a card in chat.
        on_display_text: callback(text: str)  — display text in chat.
        GLib_module:      gi.repository.GLib or None.
    """

    def __init__(
        self,
        on_display_card=None,
        on_display_text=None,
        GLib_module=None,
        on_feed_card=None,  # callback(FeedCardData) — add card to project feed
    ):
        self._on_display_card = on_display_card
        self._on_display_text = on_display_text
        self._GLib = GLib_module
        self._on_feed_card = on_feed_card

    def _emit_feed_card(self, card: dict) -> None:
        """Convert task card dict to FeedCardData and fire feed callback.

        Extracts project name from the command source_session_key.
        Only fires if _on_feed_card is set and source is a project tab.
        """
        if not self._on_feed_card:
            return
        if not hasattr(card, 'get'):
            return  # guard: card is a dict, not some other type
        project_name = ""
        # project_name extracted from source_session_key in calling commands
        project_name = getattr(self, '_last_project_name', "")
        if not project_name:
            return
        feed_card = FeedCardData(
            card_type="task",
            source="agent",
            title=card.get("title", "Task"),
            body=f"Status: {card.get('status', 'unknown')} • Assigned: {card.get('assigned_to', '?')}",
            author=card.get("assigned_to", "unknown"),
            timestamp=datetime.now(timezone.utc),
            project_name=project_name,
            task_id=str(card.get("id", "")),
            metadata={"action": card.get("action", "updated")},
        )
        self._on_feed_card(feed_card)

    def _set_project_context(self, cmd: Command) -> None:
        """Store project name from command source for _emit_feed_card."""
        sk = cmd.source_session_key or ""
        if sk.startswith("project:"):
            self._last_project_name = sk.split(":", 1)[1]
        else:
            self._last_project_name = ""

    # ── Task commands ───────────────────────────────────────────────────────────

    def cmd_task(self, cmd: Command) -> CommandResult:
        """/task @agent — description → create task, assign to agent, show card."""
        if not cmd.target_session_key:
            return CommandResult(handled=True, response_text="No target agent. Usage: /task @agent — description")
        now = datetime.now().isoformat()
        task = task_store.create(Task(
            title=cmd.body,
            assigned_to=cmd.target_session_key,
            created_by=cmd.source_session_key,
            created_at=now,
            updated_at=now,
        ))
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        priority_label = PRIORITY_LABELS.get(task.priority, task.priority)
        agent_name = cmd.args[0] if cmd.args else ""
        card = {
            "type": "task",
            "action": "created",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": priority_label,
            "assigned_to": agent_name,
        }
        self._set_project_context(cmd)
        self._emit_feed_card(card)
        return CommandResult(handled=True, response_card=card)

    def cmd_done(self, cmd: Command) -> CommandResult:
        """/done <id> → mark task complete."""
        task_id = self._parse_task_id(cmd)
        if task_id is None:
            return CommandResult(handled=True, response_text="Usage: /done <task_id>")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "done"
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        self._set_project_context(cmd)
        self._emit_feed_card(card)
        return CommandResult(handled=True, response_card=card)

    def cmd_start(self, cmd: Command) -> CommandResult:
        """/start <id> → start working on task."""
        task_id = self._parse_task_id(cmd)
        if task_id is None:
            return CommandResult(handled=True, response_text="Usage: /start <task_id>")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "in_progress"
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        self._set_project_context(cmd)
        self._emit_feed_card(card)
        return CommandResult(handled=True, response_card=card)

    def cmd_blocked(self, cmd: Command) -> CommandResult:
        """/blocked <id> — reason → mark task blocked."""
        task_id = self._parse_task_id(cmd)
        if task_id is None:
            return CommandResult(handled=True, response_text="Usage: /blocked <task_id> — reason")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "blocked"
        task.blocked_reason = cmd.body
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        self._set_project_context(cmd)
        self._emit_feed_card(card)
        return CommandResult(handled=True, response_card=card)

    def cmd_cancel(self, cmd: Command) -> CommandResult:
        """/cancel <id> → cancel task."""
        task_id = self._parse_task_id(cmd)
        if task_id is None:
            return CommandResult(handled=True, response_text="Usage: /cancel <task_id>")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        task.status = "cancelled"
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": "",
        }
        self._set_project_context(cmd)
        self._emit_feed_card(card)
        return CommandResult(handled=True, response_card=card)

    def cmd_tasks(self, cmd: Command) -> CommandResult:
        """/tasks → show all tasks."""
        tasks = task_store.list_all()
        if not tasks:
            return CommandResult(handled=True, response_text="No tasks yet.")
        lines = ["📋 Tasks", ""]
        for t in tasks:
            status = TASK_STATUS_LABELS.get(t.status, t.status)
            priority = PRIORITY_LABELS.get(t.priority, t.priority)
            lines.append(f"[{t.id}] {t.title}")
            lines.append(f"    {status} | {priority}")
            lines.append("")
        return CommandResult(handled=True, response_text="\n".join(lines))

    def cmd_assign(self, cmd: Command) -> CommandResult:
        """/assign <id> @agent → reassign task."""
        task_id = self._parse_task_id(cmd)
        if task_id is None:
            return CommandResult(handled=True, response_text="Usage: /assign <task_id> @agent")
        if len(cmd.args) < 2:
            return CommandResult(handled=True, response_text="Usage: /assign <task_id> @agent")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        if cmd.target_session_key:
            task.assigned_to = cmd.target_session_key
        else:
            task.assigned_to = cmd.args[1]
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": "",
            "assigned_to": cmd.args[1] if len(cmd.args) > 1 else "",
        }
        return CommandResult(handled=True, response_card=card)

    def cmd_priority(self, cmd: Command) -> CommandResult:
        """/priority <id> <level> → set task priority."""
        valid = list(PRIORITY_LABELS.keys())
        if len(cmd.args) < 2:
            return CommandResult(handled=True, response_text=f"Usage: /priority <task_id> <{'|'.join(valid)}>")
        task_id = self._parse_task_id(cmd)
        if task_id is None:
            return CommandResult(handled=True, response_text=f"Usage: /priority <task_id> <{'|'.join(valid)}>")
        task = task_store.get(task_id)
        if not task:
            return CommandResult(handled=True, response_text=f"Task not found: {task_id}")
        level = cmd.args[1].lower()
        if level not in valid:
            return CommandResult(handled=True, response_text=f"Invalid priority. Use: {', '.join(valid)}")
        task.priority = level
        task_store.update(task)
        status_label = TASK_STATUS_LABELS.get(task.status, task.status)
        priority_label = PRIORITY_LABELS.get(task.priority, task.priority)
        card = {
            "type": "task",
            "action": "updated",
            "id": task.id,
            "title": task.title,
            "status": status_label,
            "priority": priority_label,
            "assigned_to": "",
        }
        return CommandResult(handled=True, response_card=card)

    # ── Helper ─────────────────────────────────────────────────────────────────

    def _parse_task_id(self, cmd: Command) -> str | None:
        """Extract task ID from cmd.args, stripping leading #."""
        if not cmd.args:
            return None
        return cmd.args[0].lstrip('#') or None
