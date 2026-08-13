# tests/test_task_redesign_prompts.py
# Static-content assertions for the SPEC-TASK-SYSTEM-FULL-REDESIGN §7.2/§7.3 prompt
# and doc updates: cc-spec-planning exists, cc-task-planning is a redirect,
# workflow guide + command reference say Spec Planning / /work / generated tasks.md.

import os
from pathlib import Path

_PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def _read(name: str) -> str:
    p = _PROMPTS / name
    assert p.is_file(), f"missing prompt file: {p}"
    with open(p, encoding="utf-8") as f:
        return f.read()


class TestSpecPlanningPrompt:
    def test_file_exists(self):
        assert (_PROMPTS / "cc-spec-planning.md").is_file()

    def test_contains_key_concepts(self):
        content = _read("cc-spec-planning.md")
        assert "Work Unit" in content
        assert "spec_path" in content
        assert "/work" in content
        assert "cc-spec-planning" in content

    def test_requires_spec_path(self):
        content = _read("cc-spec-planning.md")
        assert "spec_path" in content
        assert "spec-ready" in content

    def test_uses_work_not_flat_task_prose(self):
        content = _read("cc-spec-planning.md")
        # Must instruct /work usage, not flat /task prose as the mechanism.
        assert "/work" in content
        # The word "task" may appear in "flat /task prose" warning, but
        # cc-spec-planning must not be a task-add recipe.
        assert "work.json" in content


class TestTaskPlanningRedirect:
    def test_is_redirect_to_spec_planning(self):
        content = _read("cc-task-planning.md")
        assert "cc-spec-planning.md" in content
        assert "Task Planning → Spec Planning" in content or "renamed to **Spec Planning**" in content

    def test_no_conflicting_full_instructions(self):
        content = _read("cc-task-planning.md")
        # A redirect should not contain the old flat-task recipe.
        assert "## What You Do" not in content
        assert "/task add" not in content


class TestWorkflowGuide:
    def test_says_spec_planning(self):
        content = _read("cc-workflow-guide.md")
        assert "Spec Planning" in content
        # Phase 3 must not be presented as "Task Planning".
        assert "| 3 | Task Planning" not in content

    def test_references_spec_planning_prompt_and_work_start(self):
        content = _read("cc-workflow-guide.md")
        assert "cc-spec-planning" in content
        assert "/work start" in content

    def test_generated_tasks_md(self):
        content = _read("cc-workflow-guide.md")
        assert "generated" in content
        assert "work.json" in content

    def test_no_flat_task_engine(self):
        content = _read("cc-workflow-guide.md")
        assert "TaskStore" not in content
        assert "task add" not in content


class TestCrabcakesCommands:
    def test_documents_work_and_aliases(self):
        content = _read("system/crabcakes-commands.md")
        assert "/work" in content
        assert "legacy" in content.lower() or "Legacy" in content
        assert "/task" in content  # documented as a legacy alias

    def test_work_subcommands_documented(self):
        content = _read("system/crabcakes-commands.md")
        for sub in ["list", "start", "done", "blocked", "unblock", "cancel",
                    "assign", "priority", "spec-ready", "status"]:
            assert f"/work {sub}" in content or f"/work {sub} " in content, sub

    def test_t_alias_gone_note(self):
        content = _read("system/crabcakes-commands.md")
        assert "gone" in content or "no longer" in content or "removed" in content


class TestNoStaleTaskPlanning:
    """§10: no stale task-planning-only instructions in these 4 files."""

    FILES = [
        "cc-spec-planning.md",
        "cc-task-planning.md",
        "cc-workflow-guide.md",
        "system/crabcakes-commands.md",
    ]

    def test_no_stale_active_task_planning(self):
        # "task-planning" may appear ONLY in migration/redirect/compat context,
        # never as an active phase name or as the prompt to load.
        active_markers = [
            "## Task Planning Phase",
            "### Task Planning (`cc-task-planning`)",
            "| 3 | Task Planning |",
            "proposes a task breakdown, creates tasks via",
        ]
        for name in self.FILES:
            content = _read(name)
            for marker in active_markers:
                assert marker not in content, f"{name} contains stale marker: {marker!r}"
