# tests/test_agent_context_prompts.py
# Unit tests for per-project prompts in agent file context.
# SPEC-PROJECT-PROMPTS-DIRECTORY §2.9

import os
import time

import pytest

from agent.context import (
    build_file_context,
    _load_project_prompts_context,
)


class TestLoadProjectPromptsContext:
    """Tests for _load_project_prompts_context — pure extraction."""

    def test_no_prompts_dir_returns_empty(self, tmp_path):
        """_load_project_prompts_context returns "" when .crabcakes/prompts/ does not exist."""
        project = tmp_path / "project"
        project.mkdir()
        # No .crabcakes/prompts/
        result = _load_project_prompts_context(str(project))
        assert result == ""

    def test_two_prompts_included_with_headers(self, tmp_path):
        """Two .md files become ## .crabcakes/prompts/{stem} sections with content."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "steelFramedCodeWriter.md").write_text("# SF content", encoding="utf-8")
        (prompts_dir / "README.md").write_text("# Readme", encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert "## .crabcakes/prompts/steelFramedCodeWriter" in result
        assert "# SF content" in result
        assert "## .crabcakes/prompts/README" in result
        assert "# Readme" in result

    def test_stem_no_extension(self, tmp_path):
        """Section header must be the stem, not the full path or extension."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "foo.md").write_text("bar", encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert "## .crabcakes/prompts/foo\n\nbar" in result
        assert ".crabcakes/prompts/foo.md" not in result
        assert ".crabcakes/prompts/" in result  # path prefix present
        assert result.count("## .crabcakes/prompts/") == 1

    def test_non_md_files_ignored(self, tmp_path):
        """Non-.md files in .crabcakes/prompts/ are silently ignored."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "keep.md").write_text("keep me", encoding="utf-8")
        (prompts_dir / "ignore.txt").write_text("ignore me", encoding="utf-8")
        (prompts_dir / "ignore.json").write_text('{"x":1}', encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert "## .crabcakes/prompts/keep" in result
        assert "ignore me" not in result
        assert "ignore" not in result or "keep" in result
        assert result.count("## .crabcakes/prompts/") == 1

    def test_unreadable_dir_returns_empty(self, tmp_path, monkeypatch):
        """OSError from os.listdir is swallowed; function returns ''."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "x.md").write_text("x", encoding="utf-8")

        def _broken_listdir(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(os, "listdir", _broken_listdir)

        result = _load_project_prompts_context(str(tmp_path))
        assert result == ""


class TestFileCap:
    """Tests for the 30-file cap."""

    def test_thirty_first_files_included(self, tmp_path):
        """Exactly 30 files: all included."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        for i in range(30):
            (prompts_dir / f"prompt_{i:03d}.md").write_text(f"content {i}", encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        for i in range(30):
            assert f"## .crabcakes/prompts/prompt_{i:03d}" in result
        assert result.count("## .crabcakes/prompts/") == 30

    def test_thirty_first_excluded(self, tmp_path):
        """31 files: first 30 (sorted) included, 31st excluded."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        for i in range(31):
            (prompts_dir / f"prompt_{i:03d}.md").write_text(f"content {i}", encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert "## .crabcakes/prompts/prompt_029" in result
        assert "## .crabcakes/prompts/prompt_030" not in result
        assert result.count("## .crabcakes/prompts/") == 30


class TestSizeCap:
    """Tests for the 20KB cap per file."""

    def test_large_file_skipped(self, tmp_path):
        """A file > 20KB is skipped; smaller files are still included."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "small.md").write_text("small content", encoding="utf-8")
        # 21KB file
        (prompts_dir / "large.md").write_text("x" * (21 * 1024), encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert "## .crabcakes/prompts/small" in result
        assert "## .crabcakes/prompts/large" not in result

    def test_oversized_files_do_not_burn_cap_slots(self, tmp_path):
        """Phase 7 audit BUG #5: size filter runs BEFORE the 30-count cap, so
        oversized files never consume slots. 35 files: 5 oversized (sorted
        first) + 30 small — all 30 small files must appear despite the cap."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        # Oversized files sort FIRST alphabetically (aaa_big_*)
        for i in range(5):
            (prompts_dir / f"aaa_big_{i}.md").write_text("x" * (21 * 1024), encoding="utf-8")
        for i in range(30):
            (prompts_dir / f"z_small_{i:02d}.md").write_text(f"c{i}", encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert result.count("## .crabcakes/prompts/") == 30
        for i in range(30):
            assert f"## .crabcakes/prompts/z_small_{i:02d}" in result
        for i in range(5):
            assert f"aaa_big_{i}" not in result


class TestSubdirectoryExclusion:
    """Tests that subdirectories under prompts/ are not traversed."""

    def test_subdir_files_ignored(self, tmp_path):
        """Files in .crabcakes/prompts/default_agents/ are not included."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "top.md").write_text("top-level", encoding="utf-8")
        subdir = prompts_dir / "default_agents"
        subdir.mkdir()
        (subdir / "nested.md").write_text("nested", encoding="utf-8")

        result = _load_project_prompts_context(str(tmp_path))

        assert "## .crabcakes/prompts/top" in result
        assert "nested" not in result


class TestBuildFileContextIntegration:
    """Tests for build_file_context integration with per-project prompts."""

    def test_prompts_included_in_build_file_context(self, tmp_path):
        """build_file_context includes prompt sections alongside project docs."""
        # Create minimal project structure
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "architecture.md").write_text("# Arch", encoding="utf-8")

        prompts_dir = crab_dir / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "steelFramedCodeWriter.md").write_text("# SF", encoding="utf-8")

        result = build_file_context(str(tmp_path))

        assert "## Project prompts" in result or "## .crabcakes/prompts/" in result
        assert "## .crabcakes/prompts/steelFramedCodeWriter" in result
        assert "# SF" in result

    def test_core_docs_before_prompts_in_ordering(self, tmp_path):
        """Core .crabcakes/ docs appear before prompts sections in output."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "architecture.md").write_text("# Arch Content", encoding="utf-8")

        prompts_dir = crab_dir / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "z.md").write_text("# Z Prompt", encoding="utf-8")

        result = build_file_context(str(tmp_path))

        # Core docs block should appear before prompts block
        core_idx = result.find("## .crabcakes/architecture.md")
        prompts_idx = result.find("## .crabcakes/prompts/z")
        assert core_idx != -1, "Core doc section should be present"
        assert prompts_idx != -1, "Prompts section should be present"
        assert core_idx < prompts_idx, "Core docs must appear before prompts"


class TestCacheInvalidation:
    """Tests that _project_root_mtime tracks prompts for cache invalidation."""

    def test_new_prompt_invalidates_cache(self, tmp_path):
        """Adding a new prompt file invalidates the old cached context."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "architecture.md").write_text("# Arch", encoding="utf-8")

        prompts_dir = crab_dir / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "a.md").write_text("A", encoding="utf-8")

        # First call — populates cache
        ctx1 = build_file_context(str(tmp_path))
        assert "## .crabcakes/prompts/a" in ctx1

        # Add a new prompt
        new_file = prompts_dir / "b.md"
        new_file.write_text("B", encoding="utf-8")
        # Force mtime forward — time.sleep(0.05) is unreliable on 1-second-
        # resolution filesystems (Phase 7 audit BUG #7, timing-dependent)
        os.utime(new_file, (time.time() + 2, time.time() + 2))

        # Second call — cache must be invalidated
        ctx2 = build_file_context(str(tmp_path))
        assert "## .crabcakes/prompts/b" in ctx2
        assert "## .crabcakes/prompts/a" in ctx2

    def test_modified_prompt_invalidates_cache(self, tmp_path):
        """Modifying an existing prompt file invalidates the cache."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "architecture.md").write_text("# Arch", encoding="utf-8")

        prompts_dir = crab_dir / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "x.md"
        prompt_file.write_text("old", encoding="utf-8")

        # First call — populates cache
        ctx1 = build_file_context(str(tmp_path))
        assert "old" in ctx1

        # Modify the prompt — different length + forced mtime so the change
        # is detectable even on 1-second-resolution filesystems (Phase 7
        # audit BUG #7, stale-mtime trap class)
        prompt_file.write_text("new content, longer than before", encoding="utf-8")
        os.utime(prompt_file, (time.time() + 2, time.time() + 2))

        # Second call — cache must be invalidated
        ctx2 = build_file_context(str(tmp_path))
        assert "new" in ctx2
        assert "old" not in ctx2
