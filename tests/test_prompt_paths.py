# tests/test_prompt_paths.py
# Tests for utils/prompt_paths — per-project prompts directory resolver.
#
# Pure Python — no GTK imports, no sandbox concerns.

import os

import pytest

from utils.prompt_paths import (
    APP_LEVEL_PROMPTS_SUBDIRS,
    APP_USER_PROMPTS_DIR,
    _get_app_root,
    ensure_project_prompts_dir,
    get_project_prompts_dir,
)


class TestAppRoot:
    def test_returns_real_directory(self):
        root = _get_app_root()
        assert os.path.isdir(root), f"App root is not a dir: {root}"

    def test_is_crabcakes_repo(self):
        root = _get_app_root()
        assert os.path.isfile(os.path.join(root, "README.md")), (
            f"Expected README.md at repo root: {root}"
        )


class TestConstants:
    def test_app_user_prompts_dir_is_under_app_root(self):
        assert APP_USER_PROMPTS_DIR.startswith(_get_app_root())
        assert APP_USER_PROMPTS_DIR.endswith("prompts")

    def test_app_user_prompts_dir_exists_in_repo(self):
        """When running inside the crabcakes repo, the prompts/ dir must exist."""
        assert os.path.isdir(APP_USER_PROMPTS_DIR), (
            f"APP_USER_PROMPTS_DIR does not exist: {APP_USER_PROMPTS_DIR}"
        )

    def test_app_level_prompts_subdirs_values(self):
        assert APP_LEVEL_PROMPTS_SUBDIRS == frozenset({"system", "claude-code-clean"})

    def test_app_level_prompts_subdirs_is_frozen(self):
        with pytest.raises(AttributeError):
            APP_LEVEL_PROMPTS_SUBDIRS.add("new")


class TestGetProjectPromptsDirFallback:
    """Cases 1–3 + 5 + 6: fallback to APP_USER_PROMPTS_DIR."""

    def test_none_returns_app_dir(self):
        result = get_project_prompts_dir(None)
        assert result == APP_USER_PROMPTS_DIR

    def test_empty_string_returns_app_dir(self):
        """Empty string must behave identically to None (spec §2.2)."""
        result = get_project_prompts_dir("")
        assert result == APP_USER_PROMPTS_DIR

    def test_empty_string_short_circuits_before_isdir(self, monkeypatch):
        """Empty string must short-circuit via the falsy check, NOT fall
        through to os.path.isdir (Debugger Phase 1 audit, BUG #2).

        A buggy rewrite to `if project_path is None:` would join
        '.crabcakes/prompts' as a RELATIVE path and hit os.path.isdir.
        Making isdir raise proves the short-circuit fired first.
        """

        def raise_oserror(_path):
            raise AssertionError("os.path.isdir must not be reached for ''")

        monkeypatch.setattr(os.path, "isdir", raise_oserror)
        result = get_project_prompts_dir("")
        assert result == APP_USER_PROMPTS_DIR

    def test_nonexistent_path_returns_app_dir(self):
        result = get_project_prompts_dir("/no/such/path/ever")
        assert result == APP_USER_PROMPTS_DIR

    def test_project_without_prompts_dir_returns_app_dir(self, tmp_path):
        """A project with .crabcakes/ but no prompts/ subdir falls back."""
        os.makedirs(tmp_path / ".crabcakes")
        result = get_project_prompts_dir(str(tmp_path))
        assert result == APP_USER_PROMPTS_DIR

    def test_project_without_crabcakes_dir_returns_app_dir(self, tmp_path):
        """A plain temp dir with no .crabcakes/ at all falls back."""
        result = get_project_prompts_dir(str(tmp_path))
        assert result == APP_USER_PROMPTS_DIR

    def test_oserror_on_isdir_falls_back(self, tmp_path, monkeypatch):
        """If os.path.isdir raises, we must NOT propagate — return app dir."""
        os.makedirs(tmp_path / ".crabcakes")

        def raise_oserror(_path):
            raise OSError("permission denied")

        monkeypatch.setattr(os.path, "isdir", raise_oserror)
        result = get_project_prompts_dir(str(tmp_path))
        assert result == APP_USER_PROMPTS_DIR


class TestGetProjectPromptsDirProjectPath:
    """Case 4: project with .crabcakes/prompts/ resolves to the project dir."""

    def test_project_with_prompts_dir_returns_project_path(self, tmp_path):
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "hello.md").write_text("hi")

        result = get_project_prompts_dir(str(tmp_path))
        expected = str(prompts_dir)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_project_with_prompts_dir_is_preferred_over_app_dir(self, tmp_path):
        """Even when the project path looks weird, if the dir exists it's chosen."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        result = get_project_prompts_dir(str(tmp_path))
        assert result != APP_USER_PROMPTS_DIR
        assert result.endswith(".crabcakes/prompts")

    def test_project_prompts_dir_is_file_not_dir(self, tmp_path):
        """If .crabcakes/prompts exists but is a file, fall back to app dir."""
        os.makedirs(tmp_path / ".crabcakes")
        (tmp_path / ".crabcakes" / "prompts").write_text("not a dir")
        result = get_project_prompts_dir(str(tmp_path))
        assert result == APP_USER_PROMPTS_DIR

    def test_relative_project_path(self, tmp_path):
        """Relative paths work as long as the resolved dir exists."""
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        # Use relative path from cwd
        rel = os.path.relpath(str(tmp_path))
        result = get_project_prompts_dir(rel)
        # The function joins project_path with the suffix; it does NOT abspath.
        expected = os.path.join(rel, ".crabcakes", "prompts")
        assert result == expected


class TestEnsureProjectPromptsDir:
    """Direct coverage for the write-side resolver (Phase 3 re-audit
    BUGs #1–#3): creation semantics, falsy fallback, idempotency,
    makedirs-failure behavior, NUL-byte grace."""

    def test_unseeded_project_dir_is_created(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        result = ensure_project_prompts_dir(str(project))
        assert result == str(project / ".crabcakes" / "prompts")
        assert (project / ".crabcakes" / "prompts").is_dir()

    def test_seeded_project_returns_existing_dir(self, tmp_path):
        prompts_dir = tmp_path / ".crabcakes" / "prompts"
        prompts_dir.mkdir(parents=True)
        result = ensure_project_prompts_dir(str(tmp_path))
        assert result == str(prompts_dir)

    def test_falsy_project_path_returns_app_dir_without_creating(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        for falsy in (None, ""):
            result = ensure_project_prompts_dir(falsy)
            assert result == APP_USER_PROMPTS_DIR
        assert not (tmp_path / ".crabcakes").exists()

    def test_idempotent_second_call(self, tmp_path):
        first = ensure_project_prompts_dir(str(tmp_path))
        second = ensure_project_prompts_dir(str(tmp_path))
        assert first == second
        assert (tmp_path / ".crabcakes" / "prompts").is_dir()

    def test_makedirs_failure_returns_project_path_not_app(
        self, tmp_path, monkeypatch
    ):
        """M4-class regression guard: on makedirs failure the function must
        return the PROJECT path (caller's write fails loudly) — never the
        app dir (which would silently pollute the app library)."""
        project = tmp_path / "proj"
        project.mkdir()

        def boom(path, exist_ok=False):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(
            "utils.prompt_paths.os.makedirs", boom, raising=True
        )
        result = ensure_project_prompts_dir(str(project))
        assert result == str(project / ".crabcakes" / "prompts")
        assert result != APP_USER_PROMPTS_DIR

    def test_nul_byte_path_does_not_raise(self):
        """Re-audit BUG #1: NUL byte raises ValueError inside makedirs —
        must be swallowed like the read resolver does (graceful)."""
        result = ensure_project_prompts_dir("/tmp/foo\x00bar")
        assert result == os.path.join("/tmp/foo\x00bar", ".crabcakes", "prompts")
