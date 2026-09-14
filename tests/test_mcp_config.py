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

    def test_env_var_substitution_forwards_credential_var(self, caplog):
        """MED-12 (denylist rework): non-denylisted ${VAR} IS forwarded.

        PM-approved behaviour change: credential-style vars the user
        deliberately names in their own config (TEST_MCP_TOKEN here) are
        substituted from the process environment. Only DENYLISTED vars
        (utils/mcp_config.py::_MCP_DANGEROUS_ENV_VARS) are refused.
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
            assert params is not None
            assert params.env is not None and params.env.get("TOKEN") == "secret123", (
                f"non-denylisted credential var must be forwarded; got {params.env!r}"
            )
            assert "MED-12" not in caplog.text, (
                f"forwarding a non-denylisted var must not warn; got {caplog.records!r}"
            )
        finally:
            if test_env:
                os.environ["TEST_MCP_TOKEN"] = test_env
            else:
                del os.environ["TEST_MCP_TOKEN"]

    def test_env_var_refused_when_denylisted(self, caplog):
        """MED-12: denylisted ${VAR} is refused, with the warning logged.

        LD_PRELOAD (loader-hijack vector) must NOT reach the MCP server env:
        the key is omitted and the MED-12 denylist warning fires. The
        security invariant is asserted as `"LD_PRELOAD" not in
        (params.env or {})` — deliberately decoupled from the env=None
        degrade choice (a future `env={}` refactor stays secure; audit
        suggestion from TEST-DEBT-3).
        """
        import logging
        import os
        test_env = os.environ.get("LD_PRELOAD", "")
        os.environ["LD_PRELOAD"] = "/tmp/dummy.so"
        try:
            config = MCPServerConfig(
                name="test",
                command="cmd",
                env={"LD_PRELOAD": "${LD_PRELOAD}"},
            )
            with caplog.at_level(logging.WARNING, logger="utils.mcp_config"):
                params = config.to_stdio_params()
            assert "MED-12" in caplog.text and "LD_PRELOAD" in caplog.text, (
                f"expected the MED-12 refusal warning; got {caplog.records!r}"
            )
            assert "denylist" in caplog.text.lower(), (
                "warning must name the denylist contract (allowlist-era text "
                f"is stale): {caplog.records!r}"
            )
            assert params is not None
            # Security invariant: a refused var must never reach the server env.
            assert "LD_PRELOAD" not in (params.env or {}), (
                f"denylisted var leaked into the server env: {params.env!r}"
            )
        finally:
            if test_env:
                os.environ["LD_PRELOAD"] = test_env
            else:
                del os.environ["LD_PRELOAD"]

    def test_env_var_refused_when_denylisted_gconv_path(self, caplog):
        """MED-12: GCONV_PATH (glibc iconv module hijack) is denylisted.

        Audit finding (BUG #1): the loader-hijack taxonomy includes glibc's
        iconv module path — a directory containing a malicious gconv-modules
        file is read by the iconv loader at runtime (CVE-2014-5119 lineage,
        enumerated in ATR-2026-02300).
        """
        import logging
        import os
        test_env = os.environ.get("GCONV_PATH", "")
        os.environ["GCONV_PATH"] = "/tmp/evil-gconv"
        try:
            config = MCPServerConfig(
                name="test",
                command="cmd",
                env={"GCONV_PATH": "${GCONV_PATH}"},
            )
            with caplog.at_level(logging.WARNING, logger="utils.mcp_config"):
                params = config.to_stdio_params()
            assert "MED-12" in caplog.text and "GCONV_PATH" in caplog.text, (
                f"expected the MED-12 refusal warning; got {caplog.records!r}"
            )
            assert "GCONV_PATH" not in (params.env or {}), (
                f"denylisted var leaked into the server env: {params.env!r}"
            )
        finally:
            if test_env:
                os.environ["GCONV_PATH"] = test_env
            else:
                del os.environ["GCONV_PATH"]

    def test_env_var_refused_when_denylisted_rubylib(self, caplog):
        """MED-12: RUBYLIB (Ruby load-path prepend) is denylisted.

        Audit finding (BUG #1): RUBYOPT was already covered; RUBYLIB is the
        direct path-injection counterpart (the Ruby analogue of PYTHONPATH).
        """
        import logging
        import os
        test_env = os.environ.get("RUBYLIB", "")
        os.environ["RUBYLIB"] = "/tmp/evil-ruby"
        try:
            config = MCPServerConfig(
                name="test",
                command="cmd",
                env={"RUBYLIB": "${RUBYLIB}"},
            )
            with caplog.at_level(logging.WARNING, logger="utils.mcp_config"):
                params = config.to_stdio_params()
            assert "MED-12" in caplog.text and "RUBYLIB" in caplog.text, (
                f"expected the MED-12 refusal warning; got {caplog.records!r}"
            )
            assert "RUBYLIB" not in (params.env or {}), (
                f"denylisted var leaked into the server env: {params.env!r}"
            )
        finally:
            if test_env:
                os.environ["RUBYLIB"] = test_env
            else:
                del os.environ["RUBYLIB"]

    def test_mixed_env_forwards_only_allowed(self, caplog):
        """MED-12: mixed env (one denylisted + one allowed) forwards only the allowed one."""
        import logging
        import os
        test_ld = os.environ.get("LD_PRELOAD", "")
        os.environ["LD_PRELOAD"] = "/tmp/dummy.so"
        try:
            config = MCPServerConfig(
                name="test",
                command="cmd",
                env={
                    "LD_PRELOAD": "${LD_PRELOAD}",
                    "PATH": "${PATH}",
                },
            )
            with caplog.at_level(logging.WARNING, logger="utils.mcp_config"):
                params = config.to_stdio_params()
            assert params is not None
            assert params.env == {"PATH": os.environ["PATH"]}, (
                f"only the non-denylisted var may be forwarded; got {params.env!r}"
            )
            assert "LD_PRELOAD" in caplog.text, "denylist refusal must be logged"
        finally:
            if test_ld:
                os.environ["LD_PRELOAD"] = test_ld
            else:
                del os.environ["LD_PRELOAD"]

    def test_denylist_match_is_case_sensitive(self, caplog):
        """MED-12: the denylist matches exact-case (POSIX env semantics).

        A lowercase ${ld_preload} is a DIFFERENT variable from ${LD_PRELOAD};
        the dynamic loader ignores lowercase, so forwarding it is safe. This
        pins the exact-case contract: refusal only for the exact denylisted
        spelling. (If the PM ever wants case-insensitive refusal, this test
        inverts alongside a .upper() on the check in utils/mcp_config.py.)
        """
        import logging
        import os
        test_lower = os.environ.get("ld_preload", "")
        os.environ["ld_preload"] = "/tmp/dummy-lower.so"
        try:
            config = MCPServerConfig(
                name="test",
                command="cmd",
                env={"lower": "${ld_preload}"},
            )
            with caplog.at_level(logging.WARNING, logger="utils.mcp_config"):
                params = config.to_stdio_params()
            assert params is not None
            assert params.env is not None and params.env.get("lower") == "/tmp/dummy-lower.so", (
                f"lowercase non-denylisted var must be forwarded; got {params.env!r}"
            )
            assert "MED-12" not in caplog.text, (
                f"case-sensitive match must not refuse lowercase; got {caplog.records!r}"
            )
        finally:
            if test_lower:
                os.environ["ld_preload"] = test_lower
            else:
                del os.environ["ld_preload"]

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