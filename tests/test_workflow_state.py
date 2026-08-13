# tests/test_workflow_state.py
# Tests for utils/workflow_state.py — workflow phase transitions.
#
# Covers: workflow.md initialization, phase advancement, invalid-phase
# validation, and the onboarding-completion manifest cleanup hook
# (SOR §2.9 / SPEC-SUPERVISOR-ONBOARDING-REFINEMENTS.md §2.10).
#
# The critical guarantee: a manifest-cleanup I/O failure must NOT block the
# workflow transition ('onboarding' → done / next phase → current).

import os

import pytest

from utils.project_awareness import generate_project_skeleton
from utils.workflow_state import (
    PHASES,
    PHASE_PROMPTS,
    _PHASE_INDEX,
    advance_phase,
    get_workflow_content,
    init_workflow,
    is_phase_done,
)
from utils.workflow_state import _read_workflow_lines as read_workflow_lines


def _assert_phase_marked(content: str, phase: str, status_marker: str) -> None:
    """Assert a phase row in workflow content carries the given status marker."""
    for line in content.splitlines():
        if line.startswith("| ") and f" | {phase} | " in line:
            assert status_marker in line, f"{phase} not marked {status_marker}: {line}"
            return
    raise AssertionError(f"phase row for {phase!r} not found in workflow content")


def _manifest_content(project_path) -> str:
    with open(os.path.join(project_path, ".crabcakes", "project.md"), encoding="utf-8") as f:
        return f.read()


class TestInitWorkflow:
    def test_init_workflow_creates_file(self, tmp_path):
        """init_workflow creates .crabcakes/workflow.md with all 7 phases;
        onboarding is current, others pending."""
        project_path = str(tmp_path)
        init_workflow(project_path)

        content = get_workflow_content(project_path)
        assert content, "workflow.md should be non-empty after init"

        # All 7 phases present
        assert len(PHASES) == 7
        for phase in PHASES:
            assert f" | {phase} | " in content, f"phase {phase} missing"

        # onboarding current, others pending
        _assert_phase_marked(content, "onboarding", "🔄 current")
        for phase in PHASES[1:]:
            _assert_phase_marked(content, phase, "⏳ pending")


class TestAdvancePhase:
    def test_advance_phase_marks_done_and_advances(self, tmp_path):
        """Advancing onboarding marks it done and discovery becomes current."""
        project_path = str(tmp_path)
        init_workflow(project_path)

        advance_phase(project_path, "onboarding")

        content = get_workflow_content(project_path)
        _assert_phase_marked(content, "onboarding", "✅ done")
        _assert_phase_marked(content, "discovery", "🔄 current")

    def test_advance_phase_invalid_name_raises(self, tmp_path):
        """advance_phase with an unknown phase raises ValueError (validation
        preserved)."""
        project_path = str(tmp_path)
        init_workflow(project_path)

        with pytest.raises(ValueError):
            advance_phase(project_path, "bogus")


class TestOnboardingCleanupHook:
    def test_onboarding_completion_invokes_manifest_cleanup(self, tmp_path):
        """Completing onboarding strips comment-only manifest sections and the
        workflow transition also succeeds."""
        project_path = str(tmp_path)
        generate_project_skeleton(project_path, "demo")
        init_workflow(project_path)

        # Skeleton manifest has comment-only sections
        before = _manifest_content(project_path)
        assert "<!--" in before

        advance_phase(project_path, "onboarding")

        # Manifest now has only the title line (all comment-only sections removed)
        after = _manifest_content(project_path)
        assert after.strip() == "# demo"
        assert "<!--" not in after

        # Workflow transition ALSO succeeded
        content = get_workflow_content(project_path)
        _assert_phase_marked(content, "onboarding", "✅ done")

    def test_non_onboarding_phase_does_not_clean_manifest(self, tmp_path):
        """Cleanup hook only fires for onboarding — advancing 'discovery' leaves
        the skeleton manifest unchanged."""
        project_path = str(tmp_path)
        generate_project_skeleton(project_path, "demo")
        init_workflow(project_path)

        before = _manifest_content(project_path)
        advance_phase(project_path, "discovery")

        after = _manifest_content(project_path)
        assert after == before, "non-onboarding phase must not clean the manifest"

    def test_cleanup_failure_does_not_block_workflow_transition(self, tmp_path, monkeypatch):
        """A clean_manifest_skeleton failure must not block the workflow
        transition (non-fatal guarantee)."""
        project_path = str(tmp_path)
        generate_project_skeleton(project_path, "demo")
        init_workflow(project_path)

        before = _manifest_content(project_path)

        def _boom(project_path):
            raise OSError("simulated cleanup failure")

        monkeypatch.setattr(
            "utils.project_awareness.clean_manifest_skeleton", _boom
        )

        # Must NOT raise despite the cleanup failure
        advance_phase(project_path, "onboarding")

        # Workflow transition still happened
        content = get_workflow_content(project_path)
        _assert_phase_marked(content, "onboarding", "✅ done")
        _assert_phase_marked(content, "discovery", "🔄 current")

        # Manifest is unchanged (cleanup failed)
        after = _manifest_content(project_path)
        assert after == before, "manifest should be unchanged after failed cleanup"


class TestSpecPlanningRename:
    """SPEC §7.1: task-planning → spec-planning rename."""

    def test_phases_contains_spec_planning_not_task_planning(self):
        assert "spec-planning" in PHASES
        assert "task-planning" not in PHASES

    def test_phases_index_maps_spec_planning_to_3(self):
        assert _PHASE_INDEX["spec-planning"] == 3

    def test_phase_prompts_spec_planning_points_to_cc_spec_planning(self):
        assert PHASE_PROMPTS["spec-planning"] == "`prompts/cc-spec-planning.md`"

    def test_phase_prompts_has_no_task_planning_key(self):
        assert "task-planning" not in PHASE_PROMPTS

    def test_advance_phase_onboarding_sets_discovery_current(self, tmp_path):
        """Onboarding transition is unchanged — it sets index 1 (discovery),
        NOT spec-planning."""
        project_path = str(tmp_path)
        init_workflow(project_path)
        advance_phase(project_path, "onboarding")
        content = get_workflow_content(project_path)
        _assert_phase_marked(content, "onboarding", "✅ done")
        _assert_phase_marked(content, "discovery", "🔄 current")

    def test_advance_through_architecture_sets_spec_planning_current(self, tmp_path):
        """Full lifecycle: after advancing onboarding→done, discovery→done,
        architecture→done, the next current phase is spec-planning."""
        project_path = str(tmp_path)
        init_workflow(project_path)
        for done_phase in ["onboarding", "discovery", "architecture"]:
            advance_phase(project_path, done_phase)
            _assert_phase_marked(content := get_workflow_content(project_path), done_phase, "✅ done")
        _assert_phase_marked(get_workflow_content(project_path), "spec-planning", "🔄 current")

    def test_init_workflow_writes_spec_planning(self, tmp_path):
        """Fresh init writes spec-planning (not task-planning) in the table."""
        project_path = str(tmp_path)
        init_workflow(project_path)
        content = get_workflow_content(project_path)
        assert " | spec-planning | " in content
        assert "task-planning" not in content


def _write_legacy_task_planning_workflow(project_path: str, status: str, started: str,
                                         completed: str, notes: str) -> None:
    """Write a workflow.md that contains an old task-planning row (index 3)."""
    import os
    os.makedirs(os.path.join(project_path, ".crabcakes"), exist_ok=True)
    rows = [
        "## Phase History",
        "| # | Phase | Prompt | Status | Started | Completed | Notes |",
        "|---|-------|--------|--------|---------|-----------|-------|",
        "| 0 | onboarding | `prompts/system/project-onboarding.md` | ✅ done | 2026-01-01 | 2026-01-02 | onboarding notes |",
        "| 1 | discovery | `prompts/cc-discovery.md` | ✅ done | 2026-01-03 | 2026-01-04 | discovery notes |",
        "| 2 | architecture | `prompts/cc-architecture-design.md` | ✅ done | 2026-01-05 | 2026-01-06 | arch notes |",
        f"| 3 | task-planning | `prompts/cc-task-planning.md` | {status} | {started} | {completed} | {notes} |",
        "| 4 | implementation | `prompts/implementationLoop.md` | ⏳ pending | — | — | ... |",
        "| 5 | testing | `prompts/steelFramedCodeWriter.md` | ⏳ pending | — | — | ... |",
        "| 6 | ship | `prompts/cc-workflow-guide.md` | ⏳ pending | — | — | ... |",
    ]
    with open(os.path.join(project_path, ".crabcakes", "workflow.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")


class TestLegacyTaskPlanningMigration:
    """SPEC §7.1: old task-planning rows migrate to spec-planning on read,
    preserving status/started/completed/notes."""

    def test_legacy_row_migrates_to_spec_planning_preserving_data(self, tmp_path):
        _write_legacy_task_planning_workflow(
            str(tmp_path), "🔄 current", "2026-03-01", "—", "in progress notes"
        )

        lines = read_workflow_lines(str(tmp_path))

        # Row rewritten to spec-planning
        target = [l for l in lines if " spec-planning " in l]
        assert len(target) == 1
        row = target[0]
        assert "task-planning" not in row
        assert "`prompts/cc-spec-planning.md`" in row
        # Data preserved
        assert "🔄 current" in row
        assert "2026-03-01" in row
        assert "in progress notes" in row

        # Persisted on disk
        content = get_workflow_content(str(tmp_path))
        assert "task-planning" not in content
        assert " spec-planning " in content
        assert "in progress notes" in content

    def test_migration_idempotent_no_double_migrate(self, tmp_path):
        _write_legacy_task_planning_workflow(
            str(tmp_path), "✅ done", "2026-03-01", "2026-03-05", "archived note"
        )

        read_workflow_lines(str(tmp_path))  # first read migrates + persists
        first = get_workflow_content(str(tmp_path))
        second = get_workflow_content(str(tmp_path))
        read_workflow_lines(str(tmp_path))  # second read must NOT re-migrate

        assert first.count(" spec-planning ") == 1
        assert first == second
        assert "task-planning" not in second
        # Notes survive unchanged (not duplicated / not corrupted)
        assert "archived note" in second

    def test_legacy_not_present_is_untouched(self, tmp_path):
        project_path = str(tmp_path)
        init_workflow(project_path)  # already spec-planning
        before = get_workflow_content(project_path)
        read_workflow_lines(project_path)
        after = get_workflow_content(project_path)
        assert before == after
