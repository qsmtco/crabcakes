# models/work_unit.py
# Work Unit data model + in-memory work unit store.
#
# Spec: SPEC-TASK-SYSTEM-FULL-REDESIGN §2 — Work Units as atomic, spec-backed
# implementation units, replacing flat Tasks as the primary model.
#
# Architecture rule: models/ must NEVER import from ui/, gateway/, or agent/.
# Stdlib only (dataclasses, datetime, typing). No file I/O — persistence lives
# in utils/work_persistence.py (Phase 2).

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


# ── Module-level sequential counter ─────────────────────────────────────────
# Mirrors models/task.py (_task_next_num / _task_next_id). Shared by
# WorkUnit.default_factory. The persistence layer calls _work_init_counter()
# after loading units from disk to avoid restart collisions.
_work_next_num: int = 1


def _work_next_id() -> str:
    """Return the next sequential Work Unit ID as an 8-char zero-padded string."""
    global _work_next_num
    wid = _work_next_num
    _work_next_num += 1
    return str(wid).zfill(8)


# ── Allowed constants ─────────────────────────────────────────────────────────

WORK_STATUSES = (
    "draft",
    "spec-pending",
    "spec-ready",
    "in-progress",
    "auditing",
    "done",
    "cancelled",
)

WORK_PRIORITIES = ("low", "medium", "high", "critical")

WORK_STATUS_LABELS = {
    "draft": "📝 Draft",
    "spec-pending": "✍️ Spec Pending",
    "spec-ready": "📄 Spec Ready",
    "in-progress": "🔄 In Progress",
    "auditing": "🔍 Auditing",
    "done": "✅ Done",
    "cancelled": "❌ Cancelled",
}

WORK_PRIORITY_LABELS = {
    "low": "🔽 Low",
    "medium": "▬ Medium",
    "high": "🔼 High",
    "critical": "🆘 Critical",
}


# ── Work Unit model ───────────────────────────────────────────────────────────

@dataclass
class WorkUnit:
    id: str = field(default_factory=_work_next_id)
    title: str = ""
    spec_path: str = ""
    status: str = "draft"
    assigned_supervisor: str = "special:supervisor"
    assigned_builder: str = "special:coder"
    assigned_auditor: str = "special:debugger"
    priority: str = "medium"
    depends_on: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    post_mortem_path: str = ""
    blocked_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "spec_path": self.spec_path,
            "status": self.status,
            "assigned_supervisor": self.assigned_supervisor,
            "assigned_builder": self.assigned_builder,
            "assigned_auditor": self.assigned_auditor,
            "priority": self.priority,
            "depends_on": list(self.depends_on),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "post_mortem_path": self.post_mortem_path,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkUnit":
        if not isinstance(data, dict):
            raise ValueError("Work Unit record must be an object")

        def string_field(name: str, default: str = "") -> str:
            value = data.get(name, default)
            if not isinstance(value, str):
                raise ValueError(f"Work Unit field {name!r} must be a string")
            return value

        def enum_field(name: str, allowed, default: str) -> str:
            value = string_field(name, default)
            if value not in allowed:
                raise ValueError(
                    f"Work Unit {name!r} must be one of {allowed}, got {value!r}"
                )
            return value

        depends_on = data.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(item, str) for item in depends_on
        ):
            raise ValueError("Work Unit field 'depends_on' must be a list of strings")

        return cls(
            id=string_field("id"),
            title=string_field("title"),
            spec_path=string_field("spec_path"),
            status=enum_field("status", WORK_STATUSES, "draft"),
            assigned_supervisor=string_field(
                "assigned_supervisor", "special:supervisor"
            ),
            assigned_builder=string_field("assigned_builder", "special:coder"),
            assigned_auditor=string_field("assigned_auditor", "special:debugger"),
            priority=enum_field("priority", WORK_PRIORITIES, "medium"),
            depends_on=list(depends_on),
            created_at=string_field("created_at"),
            updated_at=string_field("updated_at"),
            completed_at=string_field("completed_at"),
            post_mortem_path=string_field("post_mortem_path"),
            blocked_reason=string_field("blocked_reason"),
        )


# ── Counter initialization (persistence load path) ────────────────────────────
def _work_init_counter(work_units: Iterable[WorkUnit]) -> None:
    """Advance the ID counter past the highest loaded ID.

    Unparseable IDs are ignored. Called by the persistence layer after loading
    units from disk so newly created Work Units do not collide with existing ones.
    """
    global _work_next_num
    maximum = 0
    for work in work_units:
        try:
            maximum = max(maximum, int(work.id))
        except (TypeError, ValueError):
            continue
    _work_next_num = maximum + 1


# ── Dependency validation ─────────────────────────────────────────────────────
def _validate_dependencies(work: WorkUnit, existing_ids: set[str]) -> None:
    """Reject self-references and unknown dependency IDs.

    Phase 1 scope: reject self-reference and references to IDs not currently
    known to the store. Full cycle detection across units is deferred to a
    later phase (persistence/handler).
    """
    for dep in work.depends_on:
        if dep == work.id:
            raise ValueError(
                f"Work Unit {work.id!r} cannot depend on itself"
            )
        if dep not in existing_ids:
            raise ValueError(
                f"Work Unit {work.id!r} depends on unknown Work Unit {dep!r}"
            )


# ── Store ─────────────────────────────────────────────────────────────────────

class WorkUnitStore:
    """Pure in-memory Work Unit store — NOT persisted.

    Owns: creation, lookup, update, list, delete over loaded project-scoped
    records. File I/O is the responsibility of utils/work_persistence.py
    (Phase 2); this store only mutates its internal dict.
    """

    def __init__(self):
        self._work: dict[str, WorkUnit] = {}

    def create(self, work: WorkUnit) -> WorkUnit:
        if not work.id:
            work.id = _work_next_id()
        _validate_dependencies(work, set(self._work.keys()))
        now = datetime.now().isoformat()
        if not work.created_at:
            work.created_at = now
        if not work.updated_at:
            work.updated_at = now
        self._work[work.id] = work
        return work

    def get(self, work_id: str) -> WorkUnit | None:
        return self._work.get(work_id)

    def update(self, work: WorkUnit) -> WorkUnit:
        _validate_dependencies(work, set(self._work.keys()))
        work.updated_at = datetime.now().isoformat()
        self._work[work.id] = work
        return work

    def list_all(self) -> list[WorkUnit]:
        return sorted(
            self._work.values(),
            key=lambda w: (w.created_at, w.id),
        )

    def list_by_status(self, status: str) -> list[WorkUnit]:
        return [w for w in self.list_all() if w.status == status]

    def delete(self, work_id: str) -> bool:
        return bool(self._work.pop(work_id, None))

    def replace_all(self, work_units: Iterable[WorkUnit]) -> None:
        """Replace the internal dict contents. Used by the load path.

        Does NOT reset the counter; the persistence layer calls
        _work_init_counter() separately.
        """
        self._work = {w.id: w for w in work_units}
