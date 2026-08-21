# tests/test_prompts_project_resolution.py
# Tests for per-project prompt resolution in PromptsHandler and
# InputToolbarHandler (SPEC-PROJECT-PROMPTS-DIRECTORY §2.3, §2.7ab).
#
# No GTK instantiation needed — PromptsHandler is data-only;
# InputToolbarHandler is constructed with mock main_content per existing test
# conventions.

import os
from unittest.mock import MagicMock

import pytest

from utils.prompt_paths import APP_USER_PROMPTS_DIR


# ── PromptsHandler tests ────────────────────────────────────────────────────


class TestPromptsHandlerDefault:
    def test_default_returns_app_dir(self):
        """Fresh PromptsHandler with no set_project_path → app-level dir."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)
        result = h._get_prompts_dir()
        assert result == APP_USER_PROMPTS_DIR

    def test_set_project_path_with_prompts_dir(self, tmp_path):
        """Project with .crabcakes/prompts/ resolves to the project dir."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)

        proj_prompts = tmp_path / ".crabcakes" / "prompts"
        proj_prompts.mkdir(parents=True)
        unique = proj_prompts / "unique_project_only.md"
        unique.write_text("# unique\n")

        h.set_project_path(str(tmp_path))
        assert h._get_prompts_dir() == str(proj_prompts)

        loaded = h.load_prompts()
        names = [p["name"] for p in loaded]
        assert "unique_project_only" in names

    def test_set_project_path_empty_then_none_resets(self, tmp_path):
        """'' or None resets _get_prompts_dir back to app-level fallback."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)

        proj_prompts = tmp_path / ".crabcakes" / "prompts"
        proj_prompts.mkdir(parents=True)

        h.set_project_path(str(tmp_path))
        assert h._get_prompts_dir() == str(proj_prompts)

        h.set_project_path("")
        assert h._project_path is None
        assert h._get_prompts_dir() == APP_USER_PROMPTS_DIR

        h.set_project_path(None)
        assert h._project_path is None
        assert h._get_prompts_dir() == APP_USER_PROMPTS_DIR

    def test_unseeded_project_fallback(self, tmp_path):
        """Project without .crabcakes/prompts/ falls back to app-level dir."""
        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)
        h.set_project_path(str(tmp_path))
        result = h._get_prompts_dir()
        assert result == APP_USER_PROMPTS_DIR


# ── InputToolbarHandler tests ────────────────────────────────────────────────


def _make_mock_main_content(text: str = "") -> MagicMock:
    """Same helper pattern as tests/test_input_toolbar_handler.py."""
    buf = MagicMock()
    start_iter = MagicMock()
    end_iter = MagicMock()
    buf.get_start_iter.return_value = start_iter
    buf.get_end_iter.return_value = end_iter
    buf.get_text.return_value = text
    buf.create_tag.return_value = MagicMock()
    tag_table = MagicMock()
    tag_table.lookup.return_value = None
    buf.get_tag_table.return_value = tag_table

    mc = MagicMock()
    mc.user_input.get_buffer.return_value = buf
    return mc


def _make_mock_glib() -> MagicMock:
    """Same helper pattern as tests/test_input_toolbar_handler.py."""
    glib = MagicMock()
    glib.idle_add.side_effect = lambda fn, *args: fn(*args)
    glib.timeout_add.side_effect = lambda ms, fn: 0
    glib.source_remove = MagicMock()
    return glib


class TestInputToolbarHandlerResolution:
    """InputToolbarHandler resolves load_prompt/save_as_prompt per-project."""

    def _make_handler(self, text: str = ""):
        from ui.handlers.input_toolbar_handler import InputToolbarHandler
        mc = _make_mock_main_content(text)
        glib = _make_mock_glib()
        return InputToolbarHandler(main_content=mc, GLib_module=glib)

    def test_load_prompt_resolves_project_path(self, tmp_path):
        """load_prompt("foo") finds <project>/.crabcakes/prompts/foo.md."""
        handler = self._make_handler()

        proj_prompts = tmp_path / ".crabcakes" / "prompts"
        proj_prompts.mkdir(parents=True)
        (proj_prompts / "foo.md").write_text("project foo content\n")

        handler.set_project_path(str(tmp_path))
        captured_paths = []
        original_load_file = handler.load_file

        def capture_and_forward(path):
            captured_paths.append(path)
            return original_load_file(path)

        handler.load_file = capture_and_forward
        result = handler.load_prompt("foo")

        assert result is True
        assert len(captured_paths) == 1
        assert captured_paths[0] == str(proj_prompts / "foo.md")

    def test_load_prompt_falls_back_to_app_level(self, monkeypatch):
        """With no project_path set, load_prompt resolves to app prompts dir."""
        handler = self._make_handler()
        # The real app dir may or may not have testprompt.md; we bypass
        # the isfile guard so load_file fires and we capture the path.
        monkeypatch.setattr(os.path, "isfile", lambda p: True)
        captured_paths = []

        def capture(path):
            captured_paths.append(path)
            return False

        handler.load_file = capture
        handler.load_prompt("nonexistent_prompt_zzzz")

        assert len(captured_paths) == 1
        assert captured_paths[0].startswith(APP_USER_PROMPTS_DIR)
        assert captured_paths[0].endswith("nonexistent_prompt_zzzz.md")

    def test_save_as_prompt_writes_to_project_dir(self, tmp_path):
        """save_as_prompt creates the file under <project>/.crabcakes/prompts/."""
        handler = self._make_handler("my prompt text\n")

        proj_prompts = tmp_path / ".crabcakes" / "prompts"
        proj_prompts.mkdir(parents=True)

        handler.set_project_path(str(tmp_path))
        result = handler.save_as_prompt("bar")

        assert result is not None
        assert result == str(proj_prompts / "bar.md")
        assert (proj_prompts / "bar.md").exists()
        assert (proj_prompts / "bar.md").read_text() == "my prompt text\n"

    def test_save_as_prompt_creates_unseeded_project_dir(self, tmp_path):
        """Saving into an unseeded project creates .crabcakes/prompts/ there."""
        handler = self._make_handler("unseeded content\n")

        # No .crabcakes/ at all in this project
        project_path = str(tmp_path / "my_project")
        os.makedirs(project_path)
        handler.set_project_path(project_path)

        result = handler.save_as_prompt("unseeded")

        expected = os.path.join(project_path, ".crabcakes", "prompts", "unseeded.md")
        assert result == expected
        assert os.path.isfile(expected)
        assert open(expected).read() == "unseeded content\n"

    def test_save_as_prompt_empty_project_path_uses_app_dir(self, monkeypatch, tmp_path):
        """With no project_path, save_as_prompt targets the app prompts dir.
        Patched to a temp fake app dir so we never write into the real repo."""
        from utils import prompt_paths as _pp
        fake_app = tmp_path / "fake_app_prompts"
        fake_app.mkdir()
        monkeypatch.setattr(_pp, "APP_USER_PROMPTS_DIR", str(fake_app))

        handler = self._make_handler("app fallback text\n")
        # Do NOT call set_project_path — _project_path stays None.
        result = handler.save_as_prompt("fallback_test_zzz")

        assert result is not None
        assert result.startswith(str(fake_app))
        assert result.endswith("fallback_test_zzz.md")
        assert os.path.isfile(result)
        assert open(result).read() == "app fallback text\n"

    def test_set_project_path_empty_string(self):
        """'' resets _project_path to None (fallback)."""
        handler = self._make_handler()
        handler.set_project_path("/some/project")
        handler.set_project_path("")
        assert handler._project_path is None
