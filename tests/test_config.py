# tests/test_config.py
# Tests for utils/config.py — centralized path resolution.

import os
import pytest
from unittest.mock import patch


class TestGetConfigDir:
    def test_defaults_to_config_crabcakes(self):
        """Default config dir is ~/.config/crabcakes when XDG_CONFIG_HOME is unset."""
        with patch.dict(os.environ, {}, clear=True):
            from utils.config import get_config_dir
            result = get_config_dir()
            assert "crabcakes" in result
            assert result.endswith("crabcakes")

    def test_respects_xdg_config_home(self):
        """$XDG_CONFIG_HOME, if set, takes precedence over ~/.config."""
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/xdg"}):
            from utils.config import get_config_dir
            # Force re-import to pick up env change
            import importlib
            import utils.config
            importlib.reload(utils.config)
            from utils.config import get_config_dir
            assert get_config_dir() == "/custom/xdg/crabcakes"
            importlib.reload(utils.config)  # restore for other tests


class TestGetConfigFile:
    def test_joins_config_json(self):
        """get_config_file() appends config.json to config dir."""
        with patch.dict(os.environ, {}, clear=True):
            from utils.config import get_config_file
            assert get_config_file().endswith("config.json")


class TestGetProjectsConfigDir:
    def test_joins_projects_inside_config_dir(self):
        """get_projects_config_dir() is config_dir/projects, not ~/projects."""
        with patch.dict(os.environ, {}, clear=True):
            from utils.config import get_projects_config_dir, get_config_dir
            result = get_projects_config_dir()
            assert result.endswith("projects")
            assert get_config_dir() in result


class TestGetProjectsDir:
    def test_defaults_to_home_projects(self):
        """Default projects dir is ~/projects when CRABCAKES_PROJECTS_DIR is unset."""
        with patch.dict(os.environ, {}, clear=True):
            from utils.config import get_projects_dir
            result = get_projects_dir()
            assert result.endswith("projects")

    def test_respects_crabcakes_projects_dir_env(self):
        """$CRABCAKES_PROJECTS_DIR overrides the default."""
        with patch.dict(os.environ, {"CRABCAKES_PROJECTS_DIR": "/opt/my-projects"}):
            import importlib
            import utils.config
            importlib.reload(utils.config)
            from utils.config import get_projects_dir
            assert get_projects_dir() == "/opt/my-projects"
            importlib.reload(utils.config)


class TestGetGatewayUrl:
    def test_defaults_to_localhost(self):
        """Default gateway URL is ws://localhost:18789."""
        with patch.dict(os.environ, {}, clear=True):
            from utils.config import get_gateway_url
            assert get_gateway_url() == "ws://localhost:18789"

    def test_respects_crabcakes_gateway_url_env(self):
        """$CRABCAKES_GATEWAY_URL overrides the default."""
        with patch.dict(os.environ, {"CRABCAKES_GATEWAY_URL": "ws://my.server:9999"}):
            import importlib
            import utils.config
            importlib.reload(utils.config)
            from utils.config import get_gateway_url
            assert get_gateway_url() == "ws://my.server:9999"
            importlib.reload(utils.config)


class TestGetIdentityDir:
    def test_defaults_to_openclaw_identity(self):
        """Default identity dir is ~/.openclaw/identity."""
        with patch.dict(os.environ, {}, clear=True):
            from utils.config import get_identity_dir
            result = get_identity_dir()
            assert ".openclaw" in result
            assert result.endswith(".openclaw/identity")
