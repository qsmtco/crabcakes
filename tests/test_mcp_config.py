# tests/test_mcp_config.py
# Tests for utils/mcp_config.py — MCP server configuration loader.

import pytest
from unittest.mock import patch, mock_open
from utils.mcp_config import (
    MCPServerConfig,
    MCPConfigError,
    get_mcp_servers_path,
    load_mcp_servers,
    get_server_config,
    is_server_enabled,
    get_enabled_servers,
    _clear_cache,
)


class TestGetMcpServersPath:
    def test_joins_mcp_servers_json(self):
        """get_mcp_servers_path() returns path ending in mcp-servers.json."""
        with patch("utils.mcp_config.get_config_dir", return_value="/custom/crabcakes"):
            _clear_cache()
            result = get_mcp_servers_path()
            assert result == "/custom/crabcakes/mcp-servers.json"


class TestLoadMcpServers:
    def setup_method(self):
        _clear_cache()

    def test_raises_file_not_found_if_missing(self):
        """Raises FileNotFoundError if config file doesn't exist."""
        with patch("os.path.exists", return_value=False):
            with pytest.raises(FileNotFoundError):
                load_mcp_servers(use_cache=False)

    def test_raises_on_top_level_non_dict(self):
        """BUG #5: Raises if top-level JSON is not a dict."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='["not", "a", "dict"]')):
                with pytest.raises(MCPConfigError, match="Expected JSON object"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_servers_non_dict(self):
        """BUG #4: Raises if servers is not a dict."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": ["bad"]}')):
                with pytest.raises(MCPConfigError, match="'servers' must be an object"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_invalid_server_name_with_slash(self):
        """BUG #6: Raises if server name contains /."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": {"github/repo": {"command": "npx"}}}')):
                with pytest.raises(MCPConfigError, match="Invalid server name"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_invalid_server_name_with_space(self):
        """BUG #6: Raises if server name contains whitespace."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": {"bad name": {"command": "npx"}}}')):
                with pytest.raises(MCPConfigError, match="Invalid server name"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_server_non_dict(self):
        """BUG #3: Raises if server config is not a dict."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": {"bad": 123}}')):
                with pytest.raises(MCPConfigError, match="expected object"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_args_not_list(self):
        """BUG #1: Raises if args is not a list."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": {"test": {"command": "npx", "args": "not_list"}}}')):
                with pytest.raises(MCPConfigError, match="'args' must be array"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_empty_command_for_stdio(self):
        """BUG #7: Raises if command is empty for stdio transport."""
        config = MCPServerConfig(name="test", command="", transport="stdio")
        with pytest.raises(MCPConfigError, match="requires non-empty command"):
            config.to_stdio_params()

    def test_parses_valid_config(self):
        """Successfully parses valid MCP server config."""
        config_json = '{"servers": {"fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "@mcp/server"], "enabled": true}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                servers = load_mcp_servers(use_cache=False)
                assert "fetch" in servers
                assert servers["fetch"].command == "npx"

    def test_default_values(self):
        """Missing fields get sensible defaults."""
        config_json = '{"servers": {"test": {"command": "cmd"}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                servers = load_mcp_servers(use_cache=False)
                assert servers["test"].transport == "stdio"
                assert servers["test"].enabled is True
                assert servers["test"].description == ""

    def test_disabled_server(self):
        """Disabled servers are included but marked disabled."""
        config_json = '{"servers": {"disabled": {"command": "cmd", "enabled": false}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                servers = load_mcp_servers(use_cache=False)
                assert servers["disabled"].enabled is False

    def test_raises_on_enabled_string(self):
        """BUG #9/#16 FIXED: Raises if enabled is a string."""
        config_json = '{"servers": {"test": {"command": "cmd", "enabled": "false"}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                with pytest.raises(MCPConfigError, match="'enabled' must be boolean"):
                    load_mcp_servers(use_cache=False)

    def test_raises_on_enabled_number(self):
        """Raises if enabled is a number."""
        config_json = '{"servers": {"test": {"command": "cmd", "enabled": 1}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                with pytest.raises(MCPConfigError, match="'enabled' must be boolean"):
                    load_mcp_servers(use_cache=False)

    def test_caching(self):
        """BUG #10: Config is cached after first load."""
        config_json = '{"servers": {"test": {"command": "cmd"}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)) as mock_file:
                servers1 = load_mcp_servers()
                servers2 = load_mcp_servers()
                assert mock_file.call_count == 1

    def test_unknown_transport_raises(self):
        """Unknown transport raises MCPConfigError."""
        config_json = '{"servers": {"test": {"command": "cmd", "transport": "invalid"}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                with pytest.raises(MCPConfigError, match="unknown transport"):
                    load_mcp_servers(use_cache=False)


class TestToStdioParams:
    def test_basic_conversion(self):
        """Basic conversion to StdioServerParameters."""
        config = MCPServerConfig(
            name="fetch",
            command="npx",
            args=["-y", "@mcp/server-fetch"],
        )
        params = config.to_stdio_params()
        assert params.command == "npx"
        assert params.args == ["-y", "@mcp/server-fetch"]

    def test_env_var_substitution_allowlisted_var_is_substituted(self):
        """MED-12: ${VAR} substitution works for ALLOWLISTED vars.

        Pins the MED-12 allowlist contract (utils/mcp_config.py):
        PATH/HOME/LANG/VIRTUAL_ENV/PYTHONPATH are forwarded. PATH is used
        here because it exists in every environment.
        """
        import os
        original = os.environ.get("PATH", "")
        config = MCPServerConfig(
            name="test",
            command="cmd",
            env={"PATH": "${PATH}"},
        )
        params = config.to_stdio_params()
        assert params is not None
        assert params.env["PATH"] == original, (
            "allowlisted ${PATH} must be substituted from the process environment"
        )

    def test_env_var_refused_when_not_in_med12_allowlist(self, caplog):
        """MED-12: non-allowlisted ${VAR} is refused, with the warning logged.

        A credential-style var (TEST_MCP_TOKEN) must NOT be forwarded: the
        key is omitted from env, the MED-12 warning fires, and when every
        requested var is refused the result degrades to env=None (the
        StdioServerParameters still constructs).
        """
        import logging
        import os
        test_env = os.environ.get("TEST_MCP_TOKEN", "")
        os.environ["TEST_MCP_TOKEN"] = "secret123"
        try:
            config = MCPServerConfig(
                name="test",
                command="cmd",
                env={"TOKEN": "${TEST_MCP_TOKEN}"},
            )
            with caplog.at_level(logging.WARNING, logger="utils.mcp_config"):
                params = config.to_stdio_params()
            assert "MED-12" in caplog.text and "TEST_MCP_TOKEN" in caplog.text, (
                f"expected the MED-12 refusal warning; got {caplog.records!r}"
            )
            assert params is not None
            # Security invariant: a refused var must never reach the server env.
            # Deliberately NOT asserting `env is None` (that is only today's
            # degrade choice — a future `env={}` refactor stays secure).
            # Audit suggestion from TEST-DEBT-3: decouple the control from the
            # implementation detail.
            assert "TOKEN" not in (params.env or {}), (
                f"refused var leaked into the server env: {params.env!r}"
            )
        finally:
            if test_env:
                os.environ["TEST_MCP_TOKEN"] = test_env
            else:
                del os.environ["TEST_MCP_TOKEN"]

    def test_none_env_passes_through(self):
        """None env results in None."""
        config = MCPServerConfig(name="test", command="cmd")
        params = config.to_stdio_params()
        assert params.env is None


class TestGetServerConfig:
    def setup_method(self):
        _clear_cache()

    def test_returns_none_if_not_found(self):
        """Returns None for non-existent server."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": {}}')):
                result = get_server_config("missing")
                assert result is None


class TestIsServerEnabled:
    def setup_method(self):
        _clear_cache()

    def test_false_for_missing(self):
        """Returns False for missing server."""
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data='{"servers": {}}')):
                assert is_server_enabled("missing") is False


class TestGetEnabledServers:
    def setup_method(self):
        _clear_cache()

    def test_filters_disabled(self):
        """Only returns enabled server names."""
        config_json = '{"servers": {"one": {"command": "cmd", "enabled": true}, "two": {"command": "cmd", "enabled": false}}}'
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_json)):
                result = get_enabled_servers()
                assert result == ["one"]