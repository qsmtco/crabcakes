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
    advance_phase,
    get_workflow_content,
    init_workflow,
    is_phase_done,
)


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
