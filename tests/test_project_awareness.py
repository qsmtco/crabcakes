# tests/test_project_awareness.py
# Tests for utils/project_awareness.py — project config directory management.
#
# Covers: init, load/save team, load/save context, awareness block building,
# tech stack detection, legacy migration.

import json
import os
import pytest

from models.team import ProjectTeam, TeamMember
from utils.project_awareness import (
    CRABCAKES_DIR_NAME,
    CONTEXT_READ_CAP,
    append_project_context,
    build_awareness_block,
    build_awareness_dict,
    build_awareness_snapshot,
    detect_tech_stack,
    get_crabcakes_dir,
    get_current_task,
    init_project_config,
    load_project_context,
    load_project_manifest,
    load_team,
    save_awareness_snapshot,
    save_project_context,
    save_team,
)


class TestGetCrabcakesDir:
    def test_returns_correct_path(self, tmp_path):
        result = get_crabcakes_dir(str(tmp_path))
        assert result == str(tmp_path / ".crabcakes")


class TestInitProjectConfig:
    def test_creates_crabcakes_directory(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes").is_dir()

    def test_creates_project_md(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "project.md").is_file()

    def test_creates_team_json(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "team.json").is_file()

    def test_creates_context_md(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "context.md").is_file()

    def test_creates_awareness_json(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        assert (tmp_path / ".crabcakes" / "awareness.json").is_file()

    def test_idempotent_double_init(self, tmp_path):
        init_project_config(str(tmp_path), "testproject")
        # Second init should not overwrite existing team.json
        save_team(str(tmp_path), ProjectTeam(members=[
            TeamMember("sk1", "Agent1"),
        ]))
        init_project_config(str(tmp_path), "testproject")
        team = load_team(str(tmp_path))
        assert len(team.members) == 1
        assert team.members[0].name == "Agent1"

    def test_creates_skeleton_project_md(self, tmp_path):
        """init_project_config generates a project.md skeleton."""
        init_project_config(str(tmp_path), "myproject")
        manifest = load_project_manifest(str(tmp_path))
        assert manifest is not None
        assert "myproject" in manifest


class TestLoadSaveTeam:
    def test_load_empty_returns_empty_team(self, tmp_path):
        team = load_team(str(tmp_path))
        assert len(team.members) == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        team = ProjectTeam(
            members=[
                TeamMember("sk1", "Agent1", "implementation", True),
                TeamMember("sk2", "Agent2", "review", False),
            ],
            pm_name="Captain",
            pm_id="cli",
        )
        save_team(str(tmp_path), team)
        loaded = load_team(str(tmp_path))
        assert len(loaded.members) == 2
        assert loaded.members[0].session_key == "sk1"
        assert loaded.members[0].can_write is True
        assert loaded.members[1].name == "Agent2"
        assert loaded.pm_name == "Captain"

    def test_corrupt_json_returns_empty_team(self, tmp_path):
        init_project_config(str(tmp_path), "test")
        team_path = tmp_path / ".crabcakes" / "team.json"
        team_path.write_text("{ this is not json }")
        team = load_team(str(tmp_path))
        assert len(team.members) == 0


class TestLoadSaveContext:
    def test_load_empty_returns_empty_string(self, tmp_path):
        assert load_project_context(str(tmp_path)) == ""

    def test_save_and_load_roundtrip(self, tmp_path):
        content = "## Notes\nWorking on the project"
        save_project_context(str(tmp_path), content)
        assert load_project_context(str(tmp_path)) == content

    def test_enforces_50kb_cap(self, tmp_path):
        big_content = "x" * (60 * 1024)
        save_project_context(str(tmp_path), big_content)
        loaded = load_project_context(str(tmp_path))
        assert len(loaded) <= 50 * 1024

    def test_append_adds_separator(self, tmp_path):
        save_project_context(str(tmp_path), "First entry")
        append_project_context(str(tmp_path), "Second entry")
        loaded = load_project_context(str(tmp_path))
        assert "First entry" in loaded
        assert "Second entry" in loaded
        assert loaded.index("First") < loaded.index("Second")


class TestBuildAwarenessBlock:
    def test_includes_manifest(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        block = build_awareness_block(str(tmp_path))
        assert "testproj" in block

    def test_includes_team_members(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        save_team(str(tmp_path), ProjectTeam(members=[
            TeamMember("sk1", "Coder", "impl", True),
        ]))
        block = build_awareness_block(str(tmp_path))
        assert "Coder" in block
        assert "sk1" in block

    def test_includes_context_memory(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        save_project_context(str(tmp_path), "## Active notes\nWorking on auth")
        block = build_awareness_block(str(tmp_path))
        assert "Working on auth" in block

    def test_truncates_large_manifest(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        manifest_path = tmp_path / ".crabcakes" / "project.md"
        manifest_path.write_text("x" * 5000)
        block = build_awareness_block(str(tmp_path))
        assert "truncated" in block


class TestBuildAwarenessSnapshot:
    def test_includes_project_name(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        snap = build_awareness_snapshot(str(tmp_path))
        assert snap["project_name"] == os.path.basename(str(tmp_path))

    def test_includes_team_size(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        save_team(str(tmp_path), ProjectTeam(members=[
            TeamMember("sk1", "Agent1"),
            TeamMember("sk2", "Agent2"),
        ]))
        snap = build_awareness_snapshot(str(tmp_path))
        assert snap["team_size"] == 2

    def test_default_tasks_zero(self, tmp_path):
        init_project_config(str(tmp_path), "testproj")
        snap = build_awareness_snapshot(str(tmp_path))
        assert snap["tasks"]["total"] == 0


class TestDetectTechStack:
    def test_python_project(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
        stack = detect_tech_stack(str(tmp_path))
        assert "python" in stack

    def test_node_project(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        stack = detect_tech_stack(str(tmp_path))
        assert "javascript" in stack
        assert "node" in stack

    def test_empty_dir_returns_empty(self, tmp_path):
        stack = detect_tech_stack(str(tmp_path))
        assert stack == []

    def test_deduplicates(self, tmp_path):
        (tmp_path / "setup.py").write_text("")
        (tmp_path / "requirements.txt").write_text("")
        stack = detect_tech_stack(str(tmp_path))
        assert stack.count("python") == 1


class TestGetCurrentTask:
    """SPEC-CONTEXT-MD-SYSTEM-FIX §3.4 — get_current_task and CURRENT_TASK injection."""

    def test_get_current_task_returns_last_heading(self, tmp_path):
        """Last '## ' heading text is returned, prefix stripped correctly."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path),
            "## 2026-07-20 — Phase A1 complete\n\n"
            "## 2026-07-21 — Phase A2 in progress\n")
        assert get_current_task(str(tmp_path)) == "2026-07-21 — Phase A2 in progress"

    def test_get_current_task_empty_context(self, tmp_path):
        """Empty context.md returns empty string."""
        init_project_config(str(tmp_path), "p")
        assert get_current_task(str(tmp_path)) == ""

    def test_get_current_task_no_headings(self, tmp_path):
        """Context with no '## ' headings returns empty string."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "just plain text\nno headings here\n")
        assert get_current_task(str(tmp_path)) == ""

    def test_current_task_in_awareness_dict(self, tmp_path):
        """build_awareness_dict populates CURRENT_TASK from the last heading."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-20 — Phase A1 complete\n")
        d = build_awareness_dict(str(tmp_path))
        assert d["CURRENT_TASK"] == "2026-07-20 — Phase A1 complete"


class TestContextReadCap:
    """SPEC-CONTEXT-MD-SYSTEM-FIX §3.4 — read cap increased from 3000 to 8000."""

    def test_read_cap_8000_allows_content_beyond_old_3000_limit(self, tmp_path):
        """PROJECT_MEMORY includes content beyond the old 3000-char limit (up to 8000)."""
        init_project_config(str(tmp_path), "p")
        # 5000 chars — would be truncated under the old 3000 cap, fits under 8000
        marker_start = "MARKER_START_"
        content = marker_start + ("x" * 5000)
        save_project_context(str(tmp_path), content)
        d = build_awareness_dict(str(tmp_path))
        # The marker near the start is always present; the point is no truncation
        # message appears because 5000 < 8000
        assert marker_start in d["PROJECT_MEMORY"]
        assert "[... context memory truncated ...]" not in d["PROJECT_MEMORY"]

    def test_read_cap_8000_truncates_above_limit(self, tmp_path):
        """Truncation boundary is exactly CONTEXT_READ_CAP chars (BUG #9 from re-audit)."""
        init_project_config(str(tmp_path), "p")
        # Exactly at cap — no truncation
        save_project_context(str(tmp_path), "x" * CONTEXT_READ_CAP)
        d = build_awareness_dict(str(tmp_path))
        assert "[... context memory truncated ...]" not in d["PROJECT_MEMORY"]
        # One over cap — truncation message present
        save_project_context(str(tmp_path), "x" * (CONTEXT_READ_CAP + 1))
        d = build_awareness_dict(str(tmp_path))
        assert "[... context memory truncated ...]" in d["PROJECT_MEMORY"]


# ═══════════════════════════════════════════════════════════════════
#  Phase CB-3: Awareness variable size caps (BUG #6 fix)
# ═══════════════════════════════════════════════════════════════════

class TestAwarenessCaps:
    """Phase CB-3 (BUG #6 fix): TEAM_ROSTER ≤ 500 chars, CURRENT_STATE ≤ 1,000 chars."""

    def test_team_roster_capped_at_500_chars(self, tmp_path):
        """A team with 30+ members produces a TEAM_ROSTER with truncation marker."""
        from utils.project_awareness import TEAM_ROSTER_MAX_CHARS
        init_project_config(str(tmp_path), "testproj")
        # 30 members × ~50 chars/entry = ~1,500 chars before cap
        members = [
            TeamMember(f"sk{i}", f"Member{i:02d}", role="agent", can_write=False)
            for i in range(30)
        ]
        save_team(str(tmp_path), ProjectTeam(members=members, pm_name="PM"))
        d = build_awareness_dict(str(tmp_path))
        marker = "[... team roster truncated ...]"
        assert marker in d["TEAM_ROSTER"], f"Expected truncation marker, got: {d['TEAM_ROSTER'][-80:]}"
        # Total length should be at most cap + marker length
        assert len(d["TEAM_ROSTER"]) <= TEAM_ROSTER_MAX_CHARS + len("\n") + len(marker), \
            f"TEAM_ROSTER length {len(d['TEAM_ROSTER'])} exceeds cap+marker"

    def test_current_state_capped_at_1000_chars(self, tmp_path):
        """CURRENT_STATE with a long project name triggers truncation."""
        from utils.project_awareness import CURRENT_STATE_MAX_CHARS
        init_project_config(str(tmp_path), "testproj")
        # Mock build_awareness_snapshot to return a very long project name
        # so that CURRENT_STATE exceeds 1000 chars
        import utils.project_awareness as pa
        orig_snapshot = pa.build_awareness_snapshot
        def long_snapshot(project_path, task_store=None):
            snap = orig_snapshot(project_path, task_store)
            snap["project_name"] = "X" * 1200
            return snap
        pa.build_awareness_snapshot = long_snapshot
        try:
            d = build_awareness_dict(str(tmp_path))
        finally:
            pa.build_awareness_snapshot = orig_snapshot
        state = d["CURRENT_STATE"]
        marker = "[... current state truncated ...]"
        assert marker in state, f"Expected truncation marker. State length was {len(state)}"
        assert len(state) <= CURRENT_STATE_MAX_CHARS + len("\n") + len(marker), \
            f"CURRENT_STATE length {len(state)} exceeds cap+marker"


class TestAwarenessCacheFixes:
    """Regression tests for audit BUG #2 (staleness) and BUG #3 (alias)."""

    def test_cache_invalidates_on_rapid_write(self, tmp_path):
        """Two writes within the same mtime tick return different CURRENT_TASK."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## Task1 complete\n")
        d1 = build_awareness_dict(str(tmp_path))
        # Write again immediately (same filesystem second)
        save_project_context(str(tmp_path), "## Task1 complete\n\n## Task2 in progress\n")
        d2 = build_awareness_dict(str(tmp_path))
        assert d2["CURRENT_TASK"] == "Task2 in progress", \
            f"Cache returned stale value: {d2['CURRENT_TASK']!r}"

    def test_returned_dict_isolated_from_cache(self, tmp_path):
        """Mutating the returned dict does not poison the cache."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## Real task\n")
        d1 = build_awareness_dict(str(tmp_path))
        d1["CURRENT_TASK"] = "TAMPERED"
        d2 = build_awareness_dict(str(tmp_path))
        assert d2["CURRENT_TASK"] == "Real task", \
            f"Cache was poisoned by caller mutation: {d2['CURRENT_TASK']!r}"

    def test_cache_invalidates_on_same_length_write(self, tmp_path):
        """Same-length different-content writes invalidate the cache (BUG #8).

        len()-based fingerprints collide here; sha1 does not.
        Forces all .crabcakes/ mtimes to the same tick so the cache hit
        depends entirely on the content fingerprint (not mtime).
        """
        init_project_config(str(tmp_path), "p")
        content_a = "## Task A complete now\n" + ("A" * 180)
        content_b = "## Task B complete now\n" + ("B" * 180)  # same length, different content
        assert len(content_a) == len(content_b)
        save_project_context(str(tmp_path), content_a)
        d1 = build_awareness_dict(str(tmp_path))
        # Grab the reference mtime BEFORE the second write
        crab_dir = os.path.join(str(tmp_path), ".crabcakes")
        all_paths = [crab_dir] + [
            os.path.join(crab_dir, f)
            for f in os.listdir(crab_dir)
            if os.path.isfile(os.path.join(crab_dir, f))
        ]
        m_ref = max(os.stat(p).st_mtime_ns for p in all_paths)
        save_project_context(str(tmp_path), content_b)
        # Pin ALL .crabcakes/ files to the same mtime so the cache sees
        # no mtime change — the only differentiator is the content fingerprint.
        for p in all_paths:
            os.utime(p, ns=(m_ref, m_ref))
        d2 = build_awareness_dict(str(tmp_path))
        assert d2["CURRENT_TASK"] == "Task B complete now", \
            f"Cache stale (BUG #8): {d2['CURRENT_TASK']!r}"


class TestAppendProjectContextLifecycle:
    """SPEC-CONTEXT-MD-SYSTEM-FIX §3.1d — append supersedure + FIFO eviction."""

    def test_append_supersedes_in_progress_entry(self, tmp_path):
        """Appending 'Phase B4 complete' marks 'Phase B4 in progress' as [SUPERSEDED]."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-19 — Phase B4 in progress\nDetails here.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase B4 complete\nDone.")
        result = load_project_context(str(tmp_path))
        assert "[SUPERSEDED]" in result, f"Expected [SUPERSEDED] marker, got: {result!r}"
        assert "Phase B4 in progress" in result  # original entry preserved
        assert "Phase B4 complete" in result     # new entry appended

    def test_append_does_not_supersede_when_no_completion_word(self, tmp_path):
        """Appending a non-completion entry does not supersede anything."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-19 — Phase B4 in progress\nWorking.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase B4 notes\nJust notes.")
        result = load_project_context(str(tmp_path))
        assert "[SUPERSEDED]" not in result, f"Should not supersede without completion word: {result!r}"

    def test_append_does_not_supersede_unrelated_phase(self, tmp_path):
        """Completing Phase B4 does not supersede Phase A1 in progress."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-19 — Phase A1 in progress\nWorking.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase B4 complete\nDone.")
        result = load_project_context(str(tmp_path))
        assert "[SUPERSEDED]" not in result, f"Should not supersede unrelated phase: {result!r}"

    def test_append_supersedes_case_insensitive(self, tmp_path):
        """'COMPLETE' (uppercase) in the new entry still triggers supersedure."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-19 — Phase B4 in progress\nWorking.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase B4 COMPLETE\nDone.")
        result = load_project_context(str(tmp_path))
        assert "[SUPERSEDED]" in result, f"Case-insensitive completion should supersede: {result!r}"

    def test_append_fifo_eviction_at_50(self, tmp_path):
        """Appending the 51st entry evicts the oldest (FIFO)."""
        init_project_config(str(tmp_path), "p")
        # Fill with 50 entries
        for i in range(50):
            append_project_context(str(tmp_path), f"## 2026-01-{i+1:02d} — Entry {i}\nBody.")
        result = load_project_context(str(tmp_path))
        assert "Entry 0" in result  # oldest still present at exactly 50
        # Append the 51st
        append_project_context(str(tmp_path), "## 2026-02-01 — Entry 50\nBody.")
        result = load_project_context(str(tmp_path))
        assert "Entry 0" not in result, f"FIFO should have evicted Entry 0: {result[:200]!r}"
        assert "Entry 50" in result  # newest present

    def test_append_preserves_non_matching_entries(self, tmp_path):
        """Entries that don't match the completing phase are untouched."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path),
            "## 2026-07-19 — Phase A1 complete\nDone A1.\n\n"
            "## 2026-07-19 — Phase B4 in progress\nWorking B4.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase B4 complete\nDone B4.")
        result = load_project_context(str(tmp_path))
        assert "Phase A1 complete" in result
        assert "Phase B4 in progress" in result
        assert "[SUPERSEDED]" in result

    def test_append_idempotent_supersedure(self, tmp_path):
        """Appending the same completion twice does not double-mark [SUPERSEDED]."""
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-19 — Phase B4 in progress\nWorking.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase B4 complete\nDone.")
        append_project_context(str(tmp_path), "## 2026-07-21 — Phase B4 complete (re-confirmed)\nDone again.")
        result = load_project_context(str(tmp_path))
        # Should only have ONE [SUPERSEDED] marker on the original entry
        assert result.count("[SUPERSEDED]") == 1, \
            f"Expected 1 [SUPERSEDED], got {result.count('[SUPERSEDED]')}: {result!r}"

    def test_append_supersedes_punctuated_phase(self, tmp_path):
        """Supersession works when new entry has colon-punctuation (BUG: format-fragility).

        're-audit: COMPLETE' must supersede 're-audit in progress' even though
        the colon makes the phase identifiers textually different.
        """
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-17 — activity-drawer re-audit in progress\nWorking.")
        append_project_context(str(tmp_path), "## 2026-07-17 — activity-drawer re-audit: COMPLETE\nDone.")
        result = load_project_context(str(tmp_path))
        assert "[SUPERSEDED]" in result, f"Colon-punctuated completion should supersede: {result!r}"

    def test_append_does_not_overmatch_phase_suffix(self, tmp_path):
        """Completing Phase A1 must NOT supersede Phase A10 (BUG: substring-overmatch).

        'phase a1' must not match 'phase a10' — word boundary required.
        """
        init_project_config(str(tmp_path), "p")
        save_project_context(str(tmp_path), "## 2026-07-19 — Phase A10 in progress\nWorking A10.")
        append_project_context(str(tmp_path), "## 2026-07-20 — Phase A1 complete\nDone A1.")
        result = load_project_context(str(tmp_path))
        assert "[SUPERSEDED]" not in result, \
            f"Phase A1 must not supersede Phase A10 (substring overmatch): {result!r}"
