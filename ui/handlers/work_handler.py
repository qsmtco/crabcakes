# ui/handlers/work_handler.py
# Work Unit command implementations — replaces ui/handlers/task_handler.py.
#
# Spec: SPEC-TASK-SYSTEM-FULL-REDESIGN §4 (Work Commands and Handler), Phase 3.
# Architecture: GTK-free command handler. May import models.work_unit,
# models.command, models.feed_card, utils.work_persistence,
# utils.project_awareness only. NO imports from agent/ or gateway/.
# agent_runtime_handler is received via constructor injection only.
#
# Owns: /work, /task, /tasks, /start, /done, /blocked, /unblock, /cancel,
#       /assign, /priority, /spec-ready, /status command semantics.
# Does NOT own: GTK widgets, gateway client, WorkUnitStore instance,
#       persistence lifecycle (injected + utils), AgentRuntime.

import logging
import os
from datetime import datetime

from models.command import Command, CommandResult
from models.feed_card import FeedCardData
from models.work_unit import (
    WorkUnit,
    WorkUnitStore,
    WORK_PRIORITIES,
    WORK_PRIORITY_LABELS,
    WORK_STATUS_LABELS,
)
from utils.project_awareness import load_team
from utils.work_persistence import (
    load_or_migrate_work_units,
    save_work_units,
)

_logger = logging.getLogger(__name__)


class WorkHandler:
    """Handles Work Unit commands.

    All command methods return CommandResult and never raise out of
    process_input(). Mutations persist immediately via utils/work_persistence.

    Args:
        project_handler: injected ProjectHandler — resolve active project via
            get_active_project_name() / get_active_project_path() /
            get_project_members(name).
        work_store: shared WorkUnitStore (injected by window.py).
        agent_runtime_handler: optional; used by /work start to hand off to the
            assigned Supervisor via send_to_special_agent(session_key, text).
        on_display_card: callback(card: dict) — render a card in chat.
        on_display_text: callback(text: str) — display text in chat.
        on_feed_card: callback(FeedCardData) — add card to project feed.
        GLib_module: gi.repository.GLib or None (thread-safe dispatch, reserved).
    """

    def __init__(
        self,
        project_handler,
        work_store,
        agent_runtime_handler=None,
        on_display_card=None,
        on_display_text=None,
        on_feed_card=None,
        GLib_module=None,
    ):
        self._project_handler = project_handler
        self._work_store = work_store
        self._agent_runtime_handler = agent_runtime_handler
        self._on_display_card = on_display_card
        self._on_display_text = on_display_text
        self._on_feed_card = on_feed_card
        self._GLib = GLib_module
        self._project_path: str | None = None

    # ── Lifecycle (spec §3.3) ────────────────────────────────────────────────

    def load_for_project(self, project_path: str) -> None:
        """Load (or migrate) work units for a project and bind the store.

        Called by window.py on project open.
        """
        self._project_path = project_path
        loaded = load_or_migrate_work_units(project_path)
        self._work_store.replace_all(loaded)

    def close_project(self) -> None:
        """Release the active project binding (does NOT delete persisted data)."""
        self._project_path = None

    # ── Project / identity helpers ───────────────────────────────────────────

    def _require_project(self) -> tuple[str | None, CommandResult | None]:
        """Return (project_path, None) or (None, error_result) when no project."""
        if self._project_path is None:
            return None, CommandResult(
                handled=True, response_text="Open a project first."
            )
        return self._project_path, None

    def _resolve_work_unit_id(self, cmd: Command) -> str | None:
        """Extract the Work Unit ID from cmd.args[0]/[1], stripping a leading #.

        Accepts the 8-digit form and the #-prefixed form. Returns None if no
        usable ID is present.
        """
        for arg in cmd.args:
            if arg.startswith("#"):
                return arg.lstrip("#") or None
            if arg.isdigit():
                return arg
        return None

    def _is_pm(self, cmd: Command) -> bool:
        """PM identity per spec §4.6: project-tab session or team pm_id."""
        sk = cmd.source_session_key or ""
        if sk.startswith("project:"):
            return True
        team = load_team(self._project_path) if self._project_path else None
        if team is not None and team.pm_id and sk == team.pm_id:
            return True
        return False

    def _is_supervisor_or_pm(self, cmd: Command, unit: WorkUnit) -> bool:
        """True when the caller is the PM or the unit's assigned Supervisor."""
        if self._is_pm(cmd):
            return True
        return bool(cmd.source_session_key) and cmd.source_session_key == unit.assigned_supervisor

    def _project_name(self) -> str:
        """Resolve the active project name through the project handler."""
        if self._project_handler is None:
            return ""
        name = self._project_handler.get_active_project_name()
        return name or ""

    def _emit_feed_card(self, unit: WorkUnit, action: str, project_name: str) -> None:
        """Fire an on_feed_card callback with a task card for this unit."""
        if self._on_feed_card is None:
            return
        status_label = WORK_STATUS_LABELS.get(unit.status, unit.status)
        priority_label = WORK_PRIORITY_LABELS.get(unit.priority, unit.priority)
        card = FeedCardData(
            card_type="task",
            source="agent",
            title=unit.title or f"Work Unit {unit.id}",
            body=(
                f"Status: {status_label} • Priority: {priority_label} • "
                f"Supervisor: {unit.assigned_supervisor}"
            ),
            author=unit.assigned_supervisor,
            timestamp=datetime.now().astimezone(),
            project_name=project_name,
            task_id=unit.id,
            metadata={"action": action},
        )
        self._on_feed_card(card)

    # ── Persistence helper (spec §4) ─────────────────────────────────────────

    def _persist(self) -> CommandResult | None:
        """Persist the store state and regenerate the summary.

        save_work_units persists work.json AND regenerates tasks.md internally
        (utils/work_persistence.py). Returns an error CommandResult when no
        project is bound, else None on success.
        """
        if self._project_path is None:
            return CommandResult(
                handled=True, response_text="Open a project first."
            )
        units = self._work_store.list_all()
        save_work_units(self._project_path, units)
        return None

    # ── Path containment (spec §4.4 step 3) ─────────────────────────────────

    def _spec_path_within_project(self, project_path: str, spec_path: str) -> tuple[bool, str]:
        """Validate that spec_path is relative and resolves safely under root.

        Returns (ok, resolved_path_or_errmsg). Rejects absolute paths, '..'
        traversal, and symlinks escaping the project root via
        os.path.realpath + os.path.normcase + separator comparison.
        """
        if not spec_path:
            return False, "Spec path is empty."
        if os.path.isabs(spec_path):
            return False, f"Spec path must be relative: {spec_path}"
        resolved = os.path.realpath(os.path.join(project_path, spec_path))
        root = os.path.realpath(project_path)
        root_norm = os.path.normcase(root)
        resolved_norm = os.path.normcase(resolved)
        if resolved_norm != root_norm and not resolved_norm.startswith(
            root_norm + os.sep
        ):
            return False, f"Spec path escapes the project root: {spec_path}"
        return True, resolved

    # ── /work (canonical + legacy) ──────────────────────────────────────────

    def cmd_work(self, cmd: Command) -> CommandResult:
        """Canonical /work command.

        /work with no subcommand (or /task) creates a draft Work Unit.
        Subcommands delegate to their cmd_work_* methods.
        """
        # Legacy form: /task maps ONLY to draft creation.
        if cmd.name == "task":
            return self._create_draft(cmd)

        args = list(cmd.args)
        if not args:
            return self._create_draft(cmd)

        sub = args[0].lower()
        # /work list
        if sub == "list":
            return self.cmd_work_list(cmd)
        # /work start #N
        if sub == "start":
            return self.cmd_work_start(cmd)
        # /work done/blocked/cancel/assign/priority/spec-ready/status/unblock
        if sub in {"done", "blocked", "cancel", "assign", "priority", "spec-ready", "status", "unblock"}:
            return {
                "done": self.cmd_work_done,
                "blocked": self.cmd_work_blocked,
                "cancel": self.cmd_work_cancel,
                "assign": self.cmd_work_assign,
                "priority": self.cmd_work_priority,
                "spec-ready": self.cmd_work_spec_ready,
                "status": self.cmd_work_status,
                "unblock": self.cmd_work_unblock,
            }[sub](cmd)
        # Master spec §4.2: /work My title (unquoted) → draft with joined args.
        return self._create_draft(cmd)

    def _create_draft(self, cmd: Command) -> CommandResult:
        """Create a draft Work Unit from cmd.body (quoted) or cmd.args (unquoted)."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        if cmd.body and cmd.body.strip():
            title = cmd.body.strip()
        else:
            title = " ".join(cmd.args).strip() if cmd.args else ""
        if not title:
            return CommandResult(
                handled=True,
                response_text="Usage: /work <title> or /work \"title with spaces\"",
            )
        unit = WorkUnit(
            title=title,
            status="draft",
            spec_path="",
        )
        self._work_store.create(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "created", project_name)
        return CommandResult(
            handled=True,
            response_text=(
                f"Created Work Unit #{unit.id}: {unit.title} "
                f"({WORK_STATUS_LABELS['draft']})."
            ),
        )

    # ── /work list ───────────────────────────────────────────────────────────

    def cmd_work_list(self, cmd: Command) -> CommandResult:
        """/work list (alias /tasks) — show all Work Units."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        units = self._work_store.list_all()
        if not units:
            return CommandResult(handled=True, response_text="No work units yet.")
        lines = ["📋 Work Units", ""]
        for w in units:
            status = WORK_STATUS_LABELS.get(w.status, w.status)
            priority = WORK_PRIORITY_LABELS.get(w.priority, w.priority)
            spec = "✓" if self._spec_indicator(project_path, w) else "⚠"
            lines.append(f"[{w.id}] {w.title}")
            lines.append(f"    {status} | {priority} | Spec {spec}")
            lines.append(f"    Supervisor: {w.assigned_supervisor} | "
                         f"Builder: {w.assigned_builder} | Auditor: {w.assigned_auditor}")
            if w.blocked_reason:
                lines.append(f"    Blocked: {w.blocked_reason}")
            lines.append("")
        return CommandResult(handled=True, response_text="\n".join(lines))

    def _spec_indicator(self, project_path: str, unit: WorkUnit) -> bool:
        """True when the unit's spec_path is non-empty AND resolves to a real
        file safely under the project root (spec §4.2 '✓ present')."""
        if not unit.spec_path:
            return False
        ok, resolved = self._spec_path_within_project(project_path, unit.spec_path)
        return ok and os.path.isfile(resolved)

    # ── /work start (spec §4.4) ──────────────────────────────────────────────

    def cmd_work_start(self, cmd: Command) -> CommandResult:
        """/work start #N — trigger the implementation loop via Supervisor."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work start #N"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        # Caller authorization (spec §4.6): lifecycle triggers require
        # PM or assigned Supervisor — an unrelated member must not be able
        # to start the implementation loop / fire the Supervisor handoff.
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may start a Work Unit.",
            )

        # Step 3: spec validation
        if not unit.spec_path:
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} has no spec. Write the spec first.",
            )
        ok, resolved = self._spec_path_within_project(project_path, unit.spec_path)
        if not ok:
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} spec path invalid: {resolved}",
            )
        if not os.path.isfile(resolved):
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} has no spec. Write the spec first.",
            )

        # Step 3.5: dependency check
        unresolved = []
        for dep in unit.depends_on:
            dep_unit = self._work_store.get(dep)
            if dep_unit is None:
                unresolved.append(f"#{dep} (not found)")
            elif dep_unit.status != "done":
                unresolved.append(f"#{dep} (status: {dep_unit.status})")
        if unresolved:
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} has unresolved dependencies: "
                    f"{', '.join(unresolved)}. Resolve dependencies first."
                ),
            )

        # Step 4: status check
        if unit.blocked_reason:
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} is blocked: {unit.blocked_reason}. "
                    "Use /work unblock #N to restore readiness."
                ),
            )
        if unit.status != "spec-ready":
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} must be spec-ready to start "
                    f"(current: {WORK_STATUS_LABELS.get(unit.status, unit.status)}). "
                    "Use /work spec-ready #N first."
                ),
            )

        # Step 5: supervisor membership
        project_name = self._project_name()
        members = []
        if self._project_handler is not None:
            members = self._project_handler.get_project_members(project_name) or []
        if unit.assigned_supervisor not in members:
            return CommandResult(
                handled=True,
                response_text="Add the Supervisor agent to begin implementation.",
            )

        # Step 6: set in-progress + persist BEFORE sending
        unit.status = "in-progress"
        unit.blocked_reason = ""
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err

        # Step 7-9: handoff
        message = (
            f"Load prompts/implementationLoop.md. This work unit's spec is "
            f"at {unit.spec_path}. Begin the implementation loop."
        )
        if self._agent_runtime_handler is None:
            # No runtime handler injected — cannot dispatch. Roll back.
            unit.status = "spec-ready"
            self._work_store.update(unit)
            self._persist()
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} is ready but no runtime is available "
                    "to begin the implementation loop."
                ),
            )
        try:
            self._agent_runtime_handler.send_to_special_agent(
                unit.assigned_supervisor, message
            )
        except Exception as e:  # noqa: BLE001 — must not escape process_input()
            _logger.error(
                "cmd_work_start: send_to_special_agent failed for unit #%s: %s",
                target,
                e,
            )
            unit.status = "spec-ready"
            self._work_store.update(unit)
            self._persist()
            return CommandResult(
                handled=True,
                response_text=(
                    f"Failed to hand off Work Unit #{target} to the Supervisor: {e}"
                ),
            )

        self._emit_feed_card(unit, "started", project_name)
        status_label = WORK_STATUS_LABELS.get(unit.status, unit.status)
        return CommandResult(
            handled=True,
            response_text=(
                f"Work Unit #{unit.id} is {status_label}. "
                f"Handed off to Supervisor {unit.assigned_supervisor}."
            ),
        )

    # ── /work done ───────────────────────────────────────────────────────────

    def cmd_work_done(self, cmd: Command) -> CommandResult:
        """/work done #N — PM or assigned Supervisor only (spec §4.3)."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work done #N"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may mark a Work Unit done.",
            )
        if unit.status == "cancelled":
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} is cancelled and cannot be marked done.",
            )
        # Source-status invariant (spec §4.3): done is only valid from
        # in-progress or auditing.
        if unit.status not in ("in-progress", "auditing"):
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} has status "
                    f"{WORK_STATUS_LABELS.get(unit.status, unit.status)}; "
                    "only in-progress or auditing units can be marked done."
                ),
            )
        # Spec invariant (spec §2.1): done requires a non-empty spec_path AND
        # an existing spec file safely under the project root.
        if not unit.spec_path:
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} has no spec. Write the spec first.",
            )
        ok, resolved = self._spec_path_within_project(project_path, unit.spec_path)
        if not ok:
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} spec path invalid: {resolved}",
            )
        if not os.path.isfile(resolved):
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} has no spec. Write the spec first.",
            )
        unit.status = "done"
        unit.completed_at = datetime.now().isoformat()
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "done", project_name)
        return CommandResult(
            handled=True,
            response_text=f"Work Unit #{unit.id} marked done ({WORK_STATUS_LABELS['done']}).",
        )

    # ── /work blocked ────────────────────────────────────────────────────────

    def cmd_work_blocked(self, cmd: Command) -> CommandResult:
        """/work blocked #N — reason → in-progress + blocked_reason (spec §4.3)."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work blocked #N — reason"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may block a Work Unit.",
            )
        reason = ""
        if cmd.body and cmd.body.strip():
            reason = cmd.body.strip()
        else:
            reason = " ".join(cmd.args[2:]).strip() if len(cmd.args) > 2 else ""
        if not reason:
            return CommandResult(
                handled=True,
                response_text="Usage: /work blocked #N — reason (reason required)",
            )
        unit.status = "in-progress"
        unit.blocked_reason = reason
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "blocked", project_name)
        return CommandResult(
            handled=True,
            response_text=(
                f"Work Unit #{unit.id} is in-progress with blocker: {reason}"
            ),
        )

    # ── /work unblock ────────────────────────────────────────────────────────

    def cmd_work_unblock(self, cmd: Command) -> CommandResult:
        """/work unblock #N — clear blocker; restore spec-ready or revert to draft."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work unblock #N"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may unblock a Work Unit.",
            )
        if unit.status != "in-progress" or not unit.blocked_reason:
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} is not blocked "
                    f"(status: {WORK_STATUS_LABELS.get(unit.status, unit.status)})."
                ),
            )
        # Re-validate spec path (spec §4.3)
        if not unit.spec_path:
            unit.blocked_reason = ""
            unit.status = "draft"
            unit.updated_at = datetime.now().isoformat()
            self._work_store.update(unit)
            self._persist()
            return CommandResult(
                handled=True,
                response_text="Spec file no longer exists. Work unit reverted to draft.",
            )
        ok, resolved = self._spec_path_within_project(project_path, unit.spec_path)
        if not ok or not os.path.isfile(resolved):
            unit.blocked_reason = ""
            unit.status = "draft"
            unit.updated_at = datetime.now().isoformat()
            self._work_store.update(unit)
            self._persist()
            return CommandResult(
                handled=True,
                response_text="Spec file no longer exists. Work unit reverted to draft.",
            )
        unit.blocked_reason = ""
        unit.status = "spec-ready"
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "unblocked", project_name)
        return CommandResult(
            handled=True,
            response_text=f"Work Unit #{unit.id} unblocked — restored to spec-ready.",
        )

    # ── /work cancel ─────────────────────────────────────────────────────────

    def cmd_work_cancel(self, cmd: Command) -> CommandResult:
        """/work cancel #N — PM only (spec §4.3, §4.6)."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work cancel #N"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_pm(cmd):
            return CommandResult(
                handled=True,
                response_text="Only the PM may cancel a Work Unit.",
            )
        if unit.status == "done":
            return CommandResult(
                handled=True,
                response_text=f"Work unit #{target} is done and cannot be cancelled.",
            )
        unit.status = "cancelled"
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "cancelled", project_name)
        return CommandResult(
            handled=True,
            response_text=f"Work Unit #{unit.id} cancelled ({WORK_STATUS_LABELS['cancelled']}).",
        )

    # ── /work assign ─────────────────────────────────────────────────────────

    def cmd_work_assign(self, cmd: Command) -> CommandResult:
        """/work assign #N @agent — set supervisor/builder/auditor (spec §4.5).

        Role is derived from the resolved target when available; otherwise
        falls back to the raw @mention token. Updates exactly ONE field.
        """
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work assign #N @agent"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may assign a Work Unit.",
            )

        # Resolve the target agent token: prefer the mention-resolved session
        # key, else the raw @mention arg.
        target_agent = cmd.target_session_key or ""
        raw_arg = ""
        for arg in cmd.args[1:]:
            if arg.startswith("@"):
                raw_arg = arg.lstrip("@")
                break
        if not target_agent and not raw_arg:
            # A non-@ bare token (e.g. "someone") is present but cannot be
            # resolved to a role — ambiguous.
            if len(cmd.args) > 1:
                return CommandResult(
                    handled=True,
                    response_text=(
                        "Cannot determine assignment role. "
                        "Use @supervisor, @builder, or @auditor."
                    ),
                )
            return CommandResult(
                handled=True,
                response_text="Usage: /work assign #N @agent (supervisor|builder|auditor)",
            )

        role = ""
        if target_agent:
            # BUG #16 fix: prefer the resolved target session for BOTH role
            # and value — never mix a role from the raw @mention with a value
            # from the resolved target (inconsistent internal state).
            role = self._role_from_session(target_agent, unit)
            if not role:
                # BUG #18: a target session that matches no current assignment
                # field cannot be resolved to a role. Refusing is safer than
                # falling back to the raw @mention token's role, which would
                # store the target as the value under a different role label
                # (role/value mismatch). Do NOT fall back here.
                return CommandResult(
                    handled=True,
                    response_text=(
                        "Cannot determine assignment role. "
                        "Use @supervisor, @builder, or @auditor."
                    ),
                )
        else:
            role = self._role_from_token(raw_arg)

        if not role:
            return CommandResult(
                handled=True,
                response_text=(
                    "Cannot determine assignment role. "
                    "Use @supervisor, @builder, or @auditor."
                ),
            )

        # Exactly ONE field updated
        if role == "supervisor":
            unit.assigned_supervisor = target_agent or raw_arg
        elif role == "builder":
            unit.assigned_builder = target_agent or raw_arg
        elif role == "auditor":
            unit.assigned_auditor = target_agent or raw_arg
        else:
            return CommandResult(
                handled=True,
                response_text=f"Unknown assignment role: {role}",
            )
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "assigned", project_name)
        return CommandResult(
            handled=True,
            response_text=f"Work Unit #{unit.id} {role} assigned.",
        )

    def _role_from_token(self, token: str) -> str:
        """Map a raw mention token / display name to a role (or '')."""
        t = (token or "").strip().lower()
        for role, alias in (
            ("supervisor", "supervisor"),
            ("builder", "builder"),
            ("auditor", "auditor"),
        ):
            if role in t or alias in t:
                return role
        # session-key style special:supervisor etc.
        if "supervisor" in t:
            return "supervisor"
        if "builder" in t or "coder" in t:
            return "builder"
        if "auditor" in t or "debugger" in t:
            return "auditor"
        return ""

    def _role_from_session(self, session_key: str, unit: WorkUnit) -> str:
        """Infer role by matching against the unit's current assignments."""
        if session_key == unit.assigned_supervisor:
            return "supervisor"
        if session_key == unit.assigned_builder:
            return "builder"
        if session_key == unit.assigned_auditor:
            return "auditor"
        return ""

    # ── /work priority ───────────────────────────────────────────────────────

    def cmd_work_priority(self, cmd: Command) -> CommandResult:
        """/work priority #N <level> — set priority."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work priority #N <level>"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may set a Work Unit priority.",
            )
        level = ""
        for arg in cmd.args[1:]:
            if not arg.startswith("#") and arg.lower() in WORK_PRIORITIES:
                level = arg.lower()
                break
        if not level:
            return CommandResult(
                handled=True,
                response_text=f"Invalid priority. Use: {', '.join(WORK_PRIORITIES)}",
            )
        unit.priority = level
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "priority", project_name)
        return CommandResult(
            handled=True,
            response_text=(
                f"Work Unit #{unit.id} priority set to "
                f"{WORK_PRIORITY_LABELS.get(level, level)}."
            ),
        )

    # ── /work spec-ready ─────────────────────────────────────────────────────

    def cmd_work_spec_ready(self, cmd: Command) -> CommandResult:
        """/work spec-ready #N — validate spec path and mark ready (spec §4.3)."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work spec-ready #N"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may mark a Work Unit spec-ready.",
            )
        if unit.status not in ("draft", "spec-pending"):
            return CommandResult(
                handled=True,
                response_text=(
                    f"Work unit #{target} has status "
                    f"{WORK_STATUS_LABELS.get(unit.status, unit.status)}; "
                    "only draft or spec-pending units can be marked spec-ready."
                ),
            )
        if not unit.spec_path:
            return CommandResult(
                handled=True,
                response_text="Usage: set the spec_path first (e.g. /work spec-ready #N docs/specs/SPEC-x.md).",
            )
        ok, resolved = self._spec_path_within_project(project_path, unit.spec_path)
        if not ok:
            return CommandResult(
                handled=True,
                response_text=f"Spec path invalid: {resolved}",
            )
        if not os.path.isfile(resolved):
            return CommandResult(
                handled=True,
                response_text=f"Spec file not found: {unit.spec_path}",
            )
        unit.status = "spec-ready"
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err

        # Warn (not refuse) when Supervisor isn't in the project team.
        project_name = self._project_name()
        members = []
        if self._project_handler is not None:
            members = self._project_handler.get_project_members(project_name) or []
        warning = ""
        if unit.assigned_supervisor not in members:
            warning = (
                " Spec marked ready, but Supervisor is not in the project team. "
                "Add Supervisor before /work start."
            )
        self._emit_feed_card(unit, "spec-ready", project_name)
        return CommandResult(
            handled=True,
            response_text=f"Work Unit #{unit.id} marked spec-ready.{warning}",
        )

    # ── /work status (spec §4.3 transition table) ───────────────────────────

    def cmd_work_status(self, cmd: Command) -> CommandResult:
        """/work status #N <status> — explicit transition table (spec §4.3)."""
        project_path, err = self._require_project()
        if err is not None:
            return err
        target = self._resolve_work_unit_id(cmd)
        if target is None:
            return CommandResult(
                handled=True, response_text="Usage: /work status #N <status>"
            )
        unit = self._work_store.get(target)
        if unit is None:
            return CommandResult(
                handled=True, response_text=f"Work unit #{target} not found."
            )

        # Extract requested status from args after the id
        requested = ""
        for arg in cmd.args[1:]:
            if arg.lower() in WORK_STATUS_LABELS:
                requested = arg.lower()
                break
        if not requested:
            return CommandResult(
                handled=True,
                response_text=(
                    "Usage: /work status #N <status> — one of: "
                    "draft, spec-pending, auditing, cancelled"
                ),
            )
        if not self._is_supervisor_or_pm(cmd, unit):
            return CommandResult(
                handled=True,
                response_text="Only the PM or assigned Supervisor may change Work Unit status.",
            )

        # ── Explicit transition table (spec §4.3) ──
        current = unit.status
        if requested == "spec-ready":
            return CommandResult(
                handled=True,
                response_text="Cannot set spec-ready via /work status. Use /work spec-ready #N.",
            )
        if requested == "in-progress":
            return CommandResult(
                handled=True,
                response_text="Cannot set in-progress via /work status. Use /work start #N.",
            )
        if requested == "done":
            return CommandResult(
                handled=True,
                response_text="Cannot set done via /work status. Use /work done #N.",
            )
        if requested == "draft":
            if current == "done":
                return CommandResult(
                    handled=True,
                    response_text=f"Work unit #{target} is done and cannot be reverted to draft.",
                )
        elif requested == "spec-pending":
            if current != "draft":
                return CommandResult(
                    handled=True,
                    response_text=(
                        f"Cannot move Work Unit #{target} from "
                        f"{WORK_STATUS_LABELS.get(current, current)} to spec-pending. "
                        "Only draft units can become spec-pending."
                    ),
                )
        elif requested == "auditing":
            if not self._is_supervisor_only(cmd, unit):
                return CommandResult(
                    handled=True,
                    response_text="Only the assigned Supervisor may set a Work Unit to auditing.",
                )
            if current != "in-progress":
                return CommandResult(
                    handled=True,
                    response_text=(
                        f"Cannot move Work Unit #{target} from "
                        f"{WORK_STATUS_LABELS.get(current, current)} to auditing. "
                        "Only in-progress units can be audited."
                    ),
                )
        elif requested == "cancelled":
            if not self._is_pm(cmd):
                return CommandResult(
                    handled=True,
                    response_text="Only the PM may cancel a Work Unit.",
                )
            if current == "done":
                return CommandResult(
                    handled=True,
                    response_text=f"Work unit #{target} is done and cannot be cancelled.",
                )
        else:
            return CommandResult(
                handled=True,
                response_text=f"Unknown status: {requested}",
            )

        unit.status = requested
        unit.updated_at = datetime.now().isoformat()
        self._work_store.update(unit)
        persist_err = self._persist()
        if persist_err is not None:
            return persist_err
        project_name = self._project_name()
        self._emit_feed_card(unit, "status", project_name)
        return CommandResult(
            handled=True,
            response_text=(
                f"Work Unit #{unit.id} status → "
                f"{WORK_STATUS_LABELS.get(requested, requested)}."
            ),
        )

    def _is_supervisor_only(self, cmd: Command, unit: WorkUnit) -> bool:
        """True when the caller is exactly the unit's assigned Supervisor (not PM)."""
        return bool(cmd.source_session_key) and cmd.source_session_key == unit.assigned_supervisor