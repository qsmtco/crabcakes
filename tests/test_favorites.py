"""
Tests for utils/favorites.py
"""
import json
import os
import pytest
from utils import favorites as fav_mod


class TestLoadFavorites:
    def test_missing_file_returns_empty_set(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set()

    def test_empty_json_array_returns_empty_set(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({"favorites": []}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set()

    def test_roundtrip(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        stems = ["steelFramedCodeWriter", "coder"]
        with open(fake_path, "w") as f:
            json.dump({"favorites": stems}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set(stems)

    def test_corrupted_json_returns_empty_set(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            f.write("not valid json{")
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set()


class TestMigration:
    """One-time path→stem migration (SPEC §2.8)."""

    def test_migrates_paths_to_stems(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({
                "favorites": [
                    "/old/app/prompts/steelFramedCodeWriter.md",
                    "/x/y/READMD.md",
                ]
            }, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)

        result = fav_mod.load_favorites()
        assert result == {"steelFramedCodeWriter", "READMD"}

        # File must have been REWRITTEN with the migrated form
        with open(fake_path) as f:
            data = json.load(f)
        for entry in data["favorites"]:
            assert "/" not in entry

    def test_migration_idempotent(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({"favorites": ["steelFramedCodeWriter"]}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)

        # First load — already stems, no rewrite needed
        first_mtime = os.path.getmtime(fake_path)
        fav_mod.load_favorites()
        second_mtime = os.path.getmtime(fake_path)
        assert first_mtime == second_mtime, "File was rewritten when already stems"

    def test_migration_weird_entries_preserved(self, tmp_config_dir, monkeypatch):
        """Empty string stays empty string; unusual casing preserved."""
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({"favorites": ["/a/b/Crazy.MD", ""]}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)

        result = fav_mod.load_favorites()
        assert "Crazy" in result
        assert "" in result

    def test_migration_non_string_entries_dropped_no_crash(
        self, tmp_config_dir, monkeypatch
    ):
        """Phase 4 audit BUG #1: non-string entries (int/None/bool) must be
        DROPPED without crashing — valid stems alongside junk survive."""
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({"favorites": [1, None, True, "valid_stem"]}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)

        result = fav_mod.load_favorites()
        assert result == {"valid_stem"}
        # The rewrite cleaned the junk out of the file
        with open(fake_path) as f:
            data = json.load(f)
        assert data["favorites"] == ["valid_stem"]

    def test_non_dict_top_level_returns_empty_set(self, tmp_config_dir, monkeypatch):
        """Phase 4 audit BUG #2: valid JSON that is not a top-level dict
        (list/int/null/string) must return empty set, not AttributeError."""
        fake_path = str(tmp_config_dir / "favorites.json")
        for bad in ("[1, 2]", "42", "null", '"favorites"'):
            with open(fake_path, "w") as f:
                f.write(bad)
            monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
            assert fav_mod.load_favorites() == set()


class TestToggleFavorite:
    def test_toggle_adds_new_favorite(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({"favorites": []}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.toggle_favorite("foo")
        assert result is True
        with open(fake_path) as f:
            data = json.load(f)
        assert "foo" in data["favorites"]

    def test_toggle_removes_existing_favorite(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, "w") as f:
            json.dump({"favorites": ["foo"]}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.toggle_favorite("foo")
        assert result is False
        with open(fake_path) as f:
            data = json.load(f)
        assert "foo" not in data["favorites"]


class TestCrossProjectPersistence:
    """A favorite set in project A shows starred when scanning project B."""

    def test_favorite_persists_across_project_dirs(self, tmp_path, monkeypatch):
        # Two separate project dirs, same prompt name
        proj_a = tmp_path / "projA" / ".crabcakes" / "prompts"
        proj_b = tmp_path / "projB" / ".crabcakes" / "prompts"
        proj_a.mkdir(parents=True)
        proj_b.mkdir(parents=True)
        (proj_a / "helper.md").write_text("# Helper\n")
        (proj_b / "helper.md").write_text("# Helper\n")

        # Patch APP_USER_PROMPTS_DIR to a fake empty dir so load_prompts only
        # sees whatever project is wired. ALSO isolate favorites storage —
        # without this, toggle_favorite reads/writes the REAL user
        # favorites.json (found live: the test seeded 'helper' into the
        # real config on a prior run, then failed because it was already
        # favorited — non-hermetic).
        fake_app = tmp_path / "fake_app_prompts"
        fake_app.mkdir()
        monkeypatch.setattr(
            "utils.prompt_paths.APP_USER_PROMPTS_DIR", str(fake_app)
        )
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", str(tmp_path / "favorites.json"))

        from ui.handlers.prompts_handler import PromptsHandler
        h = PromptsHandler(on_refresh_ui=None)

        # Wire to project A
        h.set_project_path(str(tmp_path / "projA"))
        prompts_a = h.load_prompts()
        helper_a = [p for p in prompts_a if p["name"] == "helper"][0]
        # Not yet favorited
        assert not helper_a["is_favorite"]

        # Toggle favorite using project A's filepath
        h.toggle_favorite(str(proj_a / "helper.md"))

        # Switch to project B
        h.set_project_path(str(tmp_path / "projB"))
        prompts_b = h.load_prompts()
        helper_b = [p for p in prompts_b if p["name"] == "helper"][0]
        # Same stem is now favorited in project B
        assert helper_b["is_favorite"]
