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
        with open(fake_path, 'w') as f:
            json.dump({'favorites': []}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set()

    def test_roundtrip(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        paths = ['/path/to/prompt1.md', '/path/to/prompt2.md']
        with open(fake_path, 'w') as f:
            json.dump({'favorites': paths}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set(paths)

    def test_corrupted_json_returns_empty_set(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, 'w') as f:
            f.write('not valid json{')
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.load_favorites()
        assert result == set()


class TestToggleFavorite:
    def test_toggle_adds_new_favorite(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, 'w') as f:
            json.dump({'favorites': []}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.toggle_favorite('/path/to/prompt.md')
        assert result is True
        with open(fake_path) as f:
            data = json.load(f)
        assert '/path/to/prompt.md' in data['favorites']

    def test_toggle_removes_existing_favorite(self, tmp_config_dir, monkeypatch):
        fake_path = str(tmp_config_dir / "favorites.json")
        with open(fake_path, 'w') as f:
            json.dump({'favorites': ['/path/to/prompt.md']}, f)
        monkeypatch.setattr(fav_mod, "_FAVORITES_PATH", fake_path)
        result = fav_mod.toggle_favorite('/path/to/prompt.md')
        assert result is False
        with open(fake_path) as f:
            data = json.load(f)
        assert '/path/to/prompt.md' not in data['favorites']
