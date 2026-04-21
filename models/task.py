# models/task.py
# Task data model + in-memory task store.
#
# Phase 2 — task commands (`task, `done, `start, `blocked, `cancel,
# `tasks, `assign, `priority) built on this model.
#
# Manifest: no imports from ui/, no GTK, no network.

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Module-level sequential counter (BUG #16 fix) ────────────────────────────
# Shared by Task.default_factory and TaskStore.generate_id().
_task_next_num: int = 1


def _task_next_id() -> str:
    """Return next sequential task ID as an 8-character string."""
    global _task_next_num
    tid = _task_next_num
    _task_next_num += 1
    return str(tid).zfill(8)


# ── Task model ─────────────────────────────────────────────────────────────────

@dataclass
class Task:
    id: str = field(default_factory=_task_next_id)
    title: str = ""
    description: str = ""
    assigned_to: str = ""          # session_key or ""
    created_by: str = ""           # session_key
    status: str = "pending"        # pending | in_progress | blocked | done | cancelled
    priority: str = "medium"       # low | medium | high | critical
    created_at: str = ""           # ISO timestamp
    updated_at: str = ""
    blocked_reason: str = ""


class TaskStore:
    """Simple in-memory task store — NOT persisted.

    Owns: task creation, task lookup, update, delete.
    Sequential task IDs: counter is a module variable shared across all TaskStore instances.
    """

    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def generate_id(self) -> str:
        """Return next sequential task ID (8-char zero-padded)."""
        global _task_next_num
        tid = _task_next_num
        _task_next_num += 1
        return str(tid).zfill(8)

    def create(self, task: Task) -> Task:
        # Auto-assign sequential ID if not provided
        if not task.id:
            task.id = self.generate_id()
        self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def update(self, task: Task) -> Task:
        task.updated_at = datetime.now().isoformat()
        self._tasks[task.id] = task
        return task

    def list_all(self) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at)

    def list_by_agent(self, session_key: str) -> list[Task]:
        return [t for t in self._tasks.values() if t.assigned_to == session_key]

    def delete(self, task_id: str) -> bool:
        return bool(self._tasks.pop(task_id, None))


TASK_STATUS_LABELS = {
    "pending": "⏳ Pending",
    "in_progress": "🔄 In Progress",
    "blocked": "🚫 Blocked",
    "done": "✅ Done",
    "cancelled": "❌ Cancelled",
}

PRIORITY_LABELS = {
    "low": "🔽 Low",
    "medium": "▬ Medium",
    "high": "🔼 High",
    "critical": "🆘 Critical",
}

# ── Persistence stub (Phase 3) ─────────────────────────────────────────────────
# Will be implemented in a follow-up task:
#   - YAML file per project (tasks/project-{name}.yml)
#   - Agent ownership tracking
#   - Conflict resolution on concurrent writes
