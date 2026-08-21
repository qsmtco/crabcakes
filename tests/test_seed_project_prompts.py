# tests/test_seed_project_prompts.py
# Tests for utils/project_awareness.seed_project_prompts — per-project prompts
# directory seeding with copy-only-if-missing semantics.
#
# Pure Python — no GTK imports, no sandbox concerns.

import logging
import os
import tempfile

import pytest

from utils.project_awareness import seed_project_prompts
import utils.project_awareness as _pa


@pytest.fixture
def fake_app_prompts():
    """Yield a temp dir that mimics the app's prompts/ directory."""
    with tempfile.TemporaryDirectory() as d:
        # Top-level .md files (user-facing library)
        with open(os.path.join(d, "README.md"), "w") as f:
            f.write("# README\n")
        with open(os.path.join(d, "codeWriter.md"), "w") as f:
            f.write("# codeWriter\n")
        # Non-.md top-level file — should NOT be copied
        with open(os.path.join(d, "style.css"), "w") as f:
            f.write("/* css */\n")

        # App-level subdir — should NOT be copied
        os.makedirs(os.path.join(d, "system"))
        with open(os.path.join(d, "system", "coder.md"), "w") as f:
            f.write("system coder\n")

        # Whitelisted subdir — should be copied (one level deep only)
        os.makedirs(os.path.join(d, "default_agents"))
        with open(os.path.join(d, "default_agents", "coder.yaml"), "w") as f:
            f.write("coder yaml\n")
        with open(os.path.join(d, "default_agents", "supervisor.yaml"), "w") as f:
            f.write("supervisor yaml\n")
        # Nested subdir inside whitelisted dir — should NOT be copied (test 5)
        os.makedirs(os.path.join(d, "default_agents", "nested"))
        with open(os.path.join(d, "default_agents", "nested", "deep.md"), "w") as f:
            f.write("deep nested\n")

        # Top-level DIR whose NAME ends in .md — the endswith() filter alone
        # lets it through; only the isfile() check must reject it (re-audit
        # BUG #4 / mutation M6 probe).
        os.makedirs(os.path.join(d, "fakemd.md"))
        with open(os.path.join(d, "fakemd.md", "inner.md"), "w") as f:
            f.write("inner\n")

        yield d


class TestFreshProjectSeed:
    """Case 1: fresh project with no .crabcakes/ gets seeded."""

    def test_seeds_prompts_dir(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        result = seed_project_prompts(str(tmp_path))
        assert result is True

        dest = tmp_path / ".crabcakes" / "prompts"
        assert dest.is_dir()

        # Top-level .md files
        assert (dest / "README.md").read_text() == "# README\n"
        assert (dest / "codeWriter.md").read_text() == "# codeWriter\n"
        # Non-.md excluded
        assert not (dest / "style.css").exists()
        # App-level system/ excluded
        assert not (dest / "system").exists()
        # Whitelisted subdir included
        assert (dest / "default_agents" / "coder.yaml").read_text() == "coder yaml\n"
        assert (dest / "default_agents" / "supervisor.yaml").read_text() == (
            "supervisor yaml\n"
        )

    def test_creates_crabcakes_dir(self, tmp_path, monkeypatch, fake_app_prompts):
        """A project without .crabcakes/ at all gets the directory created."""
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))
        assert (tmp_path / ".crabcakes").is_dir()


class TestIdempotent:
    """Case 2: second call is a no-op and file count unchanged."""

    def test_second_call_no_overwrite(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        # Count after first seed
        dest = tmp_path / ".crabcakes" / "prompts"
        first_files = sorted(p.name for p in dest.rglob("*") if p.is_file())

        ret = seed_project_prompts(str(tmp_path))
        assert ret is True

        second_files = sorted(p.name for p in dest.rglob("*") if p.is_file())
        assert first_files == second_files


class TestLocalEditSurvives:
    """Case 3: project-local edit survives re-seed."""

    def test_modified_file_not_overwritten(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        dest = tmp_path / ".crabcakes" / "prompts"
        readme = dest / "README.md"
        assert readme.read_text() == "# README\n"

        # Simulate local edit
        readme.write_text("# CUSTOM\n")

        # Re-seed — must NOT overwrite
        seed_project_prompts(str(tmp_path))
        assert readme.read_text() == "# CUSTOM\n", (
            "Local edit was overwritten by re-seed"
        )


class TestExclusions:
    """Case 4: app-level system/ NOT copied; non-.md top-level file NOT copied."""

    def test_system_dir_not_copied(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))
        dest = tmp_path / ".crabcakes" / "prompts"
        assert not (dest / "system").exists()

    def test_non_md_top_level_not_copied(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))
        dest = tmp_path / ".crabcakes" / "prompts"
        assert not (dest / "style.css").exists()


class TestMissingSource:
    """Case 5: missing app user-prompts dir returns False without raising."""

    def test_returns_false_when_source_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", "/no/such/prompts/dir")
        result = seed_project_prompts(str(tmp_path))
        assert result is False


class TestUnwritableDest:
    """Case 6: os.makedirs raising OSError returns False, no exception."""

    def test_makedirs_raises_returns_false(self, tmp_path, monkeypatch, fake_app_prompts):
        def boom(*a, **k):
            raise OSError("permission denied")

        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        monkeypatch.setattr(_pa.os, "makedirs", boom)
        result = seed_project_prompts(str(tmp_path))
        assert result is False


class TestDeletedFileRecreated:
    """Case 7: deleted seeded file is recreated on re-seed."""

    def test_deleted_file_recreated(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        dest = tmp_path / ".crabcakes" / "prompts"
        readme = dest / "README.md"
        readme.unlink()
        assert not readme.exists()

        seed_project_prompts(str(tmp_path))
        assert readme.exists(), "Deleted file was not re-created by re-seed"
        assert readme.read_text() == "# README\n"


class TestExtraLocalFilePreserved:
    """Case 8: a file created locally (not in app set) survives re-seed."""

    def test_extra_file_preserved(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        dest = tmp_path / ".crabcakes" / "prompts"
        extra = dest / "my_custom.md"
        extra.write_text("extra content\n")

        seed_project_prompts(str(tmp_path))
        assert extra.read_text() == "extra content\n", (
            "Extra local file was not preserved"
        )


class TestRealRepoSmoke:
    """Case 9: seed against the real repo's prompts/ dir returns True and
    copies at least README.md plus one file from default_agents/."""

    def test_real_app_prompts_seed(self, tmp_path):
        # Uses real APP_USER_PROMPTS_DIR (no monkeypatch)
        result = seed_project_prompts(str(tmp_path))
        assert result is True

        dest = tmp_path / ".crabcakes" / "prompts"
        assert dest.is_dir()

        # Must have at least README.md (top-level .md) and >0 files
        files = list(dest.rglob("*"))
        md_files = [f for f in files if f.is_file() and f.suffix == ".md"]
        assert len(md_files) >= 1, f"No .md files found in seeded dir: {files}"


# ── Audit fix tests (Phase 2 FIX-1) ──────────────────────────────────────────


class TestListdirOSError:
    """Test 1 (FIX1): top-level listdir OSError must return False, not raise."""

    def test_listdir_oserror_returns_false(self, tmp_path, monkeypatch, fake_app_prompts):
        # Patch on a valid non-empty project path so the new guard (FIX2)
        # doesn't short-circuit first.
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        monkeypatch.setattr(_pa.os, "listdir", lambda p: (_ for _ in ()).throw(OSError("boom")))
        result = seed_project_prompts(str(tmp_path))
        assert result is False


class TestEmptyProjectPath:
    """Test 2 (FIX2): empty string must return False and NOT create .crabcakes/."""

    def test_empty_string_returns_false(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        monkeypatch.chdir(tmp_path)
        result = seed_project_prompts("")
        assert result is False
        assert not (tmp_path / ".crabcakes").exists(), (
            ".crabcakes/ created in cwd for empty project_path"
        )


class TestDestDirectoryAtFileName:
    """Test 3 (FIX3): a directory at a seeded filename is skipped with warning."""

    def test_dest_directory_at_file_name_skips_with_warning(
        self, tmp_path, monkeypatch, fake_app_prompts, caplog
    ):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        dest = tmp_path / ".crabcakes" / "prompts"
        # Replace README.md with a directory of the same name
        (dest / "README.md").unlink()
        os.makedirs(str(dest / "README.md"))

        # Re-seed — must not raise and must NOT try to copy into the dir
        with caplog.at_level(logging.WARNING):
            result = seed_project_prompts(str(tmp_path))
        assert result is True
        assert (dest / "README.md").is_dir(), "Directory was replaced by file"
        # Nothing was placed inside it
        assert not list((dest / "README.md").iterdir())
        # The two-tier dest check must fire its specific branch (re-audit
        # BUG #1): a revert to the old exists-only check would skip silently
        # and this assertion would fail.
        assert any(
            "dest exists but is not a file" in rec.getMessage()
            for rec in caplog.records
        ), "Two-tier dest check did not log its skip warning"


class TestSubdirDestDirectoryAtFileName:
    """Re-audit BUG #2: same dir-at-file-name case, inside the whitelisted
    subdir — proves the subdir block's two-tier check fires too (M3b)."""

    def test_subdir_dest_directory_at_file_name_skips(
        self, tmp_path, monkeypatch, fake_app_prompts, caplog
    ):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        dest_sub = tmp_path / ".crabcakes" / "prompts" / "default_agents"
        (dest_sub / "coder.yaml").unlink()
        os.makedirs(str(dest_sub / "coder.yaml"))

        with caplog.at_level(logging.WARNING):
            result = seed_project_prompts(str(tmp_path))
        assert result is True
        assert (dest_sub / "coder.yaml").is_dir(), "Subdir dir was replaced"
        assert not list((dest_sub / "coder.yaml").iterdir())
        assert any(
            "dest exists but is not a file" in rec.getMessage()
            for rec in caplog.records
        ), "Subdir two-tier dest check did not log its skip warning"


class TestSourceIsAFile:
    """Test 4: APP_USER_PROMPTS_DIR being a file (not dir) returns False.

    Re-audit BUG #3: caplog assertion proves the SOURCE check fired (the
    'app user-prompts dir missing' warning), not the listdir catch — the
    test must discriminate between the two guards.
    """

    def test_source_is_a_file_returns_false(self, tmp_path, monkeypatch, caplog):
        fake_file = tmp_path / "not_a_dir.txt"
        fake_file.write_text("nope")
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", str(fake_file))
        with caplog.at_level(logging.WARNING):
            result = seed_project_prompts(str(tmp_path / "project"))
        assert result is False
        assert any(
            "app user-prompts dir missing" in rec.getMessage()
            for rec in caplog.records
        ), "Source-is-file returned False via a guard other than the source check"


class TestNestedSubdirNotRecursed:
    """Test 5: nested subdirectories inside whitelisted dirs are NOT recursed."""

    def test_nested_subdir_not_recursed(self, tmp_path, monkeypatch, fake_app_prompts):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        seed_project_prompts(str(tmp_path))

        dest = tmp_path / ".crabcakes" / "prompts"
        # The fixture has default_agents/nested/deep.md — must NOT appear
        assert not (dest / "default_agents" / "nested").exists(), (
            "Nested subdir was recursed into whitelisted subdir"
        )


class TestTopLevelDirNamedMdNotCopied:
    """Test 6: a top-level directory is not treated as a .md file to copy.

    Re-audit BUG #4: the isfile filter means NO copy is attempted for a
    directory, so NO 'copy failed' warning may appear. Under mutation M6
    (isfile→exists) the code WOULD attempt the copy and log that warning —
    this negative assertion is what discriminates correct from mutated code.
    """

    def test_top_level_dir_named_md_not_copied(
        self, tmp_path, monkeypatch, fake_app_prompts, caplog
    ):
        monkeypatch.setattr(_pa, "APP_USER_PROMPTS_DIR", fake_app_prompts)
        with caplog.at_level(logging.WARNING):
            seed_project_prompts(str(tmp_path))

        dest = tmp_path / ".crabcakes" / "prompts"
        # The fixture has a top-level "fakemd.md" DIRECTORY — its name passes
        # the endswith(".md") filter, so only isfile() can reject it
        assert not (dest / "fakemd.md").exists(), (
            "Top-level directory with a .md name was copied as if it were a file"
        )
        # No copy may have been ATTEMPTED for the dir (the isfile filter must
        # reject it before shutil.copy2 is ever called).
        assert not any(
            "copy" in rec.getMessage() and "fakemd" in rec.getMessage()
            for rec in caplog.records
        ), "Copy was attempted for a top-level directory (isfile filter bypassed)"
