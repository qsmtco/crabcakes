# tests/test_command_handler.py
# Unit tests for ui/handlers/command_handler.py.
#
# Philosophy: test the parsing and routing logic with fake collaborators
# (no GTK, no gateway, no AgentManager — fake objects instead).
#
# Coverage:
#   1. Prefix detection (backtick vs wrong prefix, empty prefix, set_prefix)
#   2. Command lookup (known, unknown, alias, case-insensitive)
#   3. Flag parsing (value, no value, consecutive, followed by flag)
#   4. @mention resolution (exact, partial, empty, no match, multiple)
#   5. Body extraction (after em-dash " — ")
#   6. Error handling in handler → error response_text
#   7. set_gateway_client / set_agent_manager setters
#   8. Command flow end-to-end
#   9. Internal _parse_flags and _parse_mentions unit tests


import pytest
import sys
sys.path.insert(0, '.')

from ui.handlers.command_handler import CommandHandler
from models.command import Command, CommandResult


# ═══════════════════════════════════════════════════════════════════
#  Fake Collaborators
# ═══════════════════════════════════════════════════════════════════

class FakeAgentManager:
    def __init__(self, names_to_keys: dict[str, str]):
        # names_to_keys: {name: session_key}
        self._name_to_key = dict(names_to_keys)
        self._key_to_name = {v: k for k, v in names_to_keys.items()}

    def get_names_ref(self) -> dict[str, str]:
        return dict(self._key_to_name)   # session_key → name

    def get_name(self, sk: str) -> str:
        return self._key_to_name.get(sk, "")


class FakeProjectHandler:
    def __init__(self, active_proj: str = "testproj", members: list[str] | None = None):
        self._active = active_proj
        self._members = members or ["agent:a:1", "agent:b:2"]

    def get_active_project_name(self) -> str | None:
        return self._active

    def get_project_members(self, proj: str) -> list[str]:
        return self._members


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def empty_handler():
    return CommandHandler(
        gateway_client=None,
        agent_manager=None,
        project_handler=None,
        GLib_module=None,
    )


@pytest.fixture
def configured_handler():
    """Handler with AgentManager + ProjectHandler wired, plus echo command."""
    agnt = FakeAgentManager({
        "Debugger": "agent:debugger:1",
        "Coder": "agent:coder:2",
        "Qat": "agent:qat:3",
        "QDebug": "agent:qdebug:4",   # second agent with "q" — for @q partial-match test
    })
    proj = FakeProjectHandler("testproj", ["agent:a:1", "agent:b:2"])
    h = CommandHandler(
        gateway_client=None,
        agent_manager=agnt,
        project_handler=proj,
        GLib_module=None,
    )
    def echo(cmd: Command) -> CommandResult:
        return CommandResult(handled=True, response_text=f"echo: {cmd.name}")
    h.register_command("echo", echo, aliases=["e"], help_text="Echo test")
    return h


# ═══════════════════════════════════════════════════════════════════
#  Prefix detection
# ═══════════════════════════════════════════════════════════════════

class TestPrefixDetection:
    def test_plain_text_not_a_command(self, empty_handler):
        result = empty_handler.process_input("agent:1", "hello world")
        assert result.handled is False

    def test_wrong_prefix_not_a_command(self, empty_handler):
        result = empty_handler.process_input("agent:1", "/echo hello")
        assert result.handled is False

    def test_only_backtick_prefix_not_command(self, empty_handler):
        result = empty_handler.process_input("agent:1", "`")
        assert result.handled is False

    def test_only_backtick_whitespace_not_command(self, empty_handler):
        result = empty_handler.process_input("agent:1", "`   ")
        assert result.handled is False

    def test_set_prefix_changes_detection(self, empty_handler):
        empty_handler.set_prefix("/")
        from models.command import CommandResult
        empty_handler.register_command("echo", lambda c: CommandResult(handled=True, response_text="ok"))
        result = empty_handler.process_input("agent:1", "/echo hello")
        assert result.handled is True


# ═══════════════════════════════════════════════════════════════════
#  Command lookup
# ═══════════════════════════════════════════════════════════════════

class TestCommandLookup:
    def test_unknown_command_passes_through(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`unknowncmd arg")
        assert result.handled is False

    def test_known_command_handled(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo hello")
        assert result.handled is True

    def test_alias_resolves(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`e hello")
        assert result.handled is True

    def test_case_insensitive(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`ECHO hello")
        assert result.handled is True


# ═══════════════════════════════════════════════════════════════════
#  Flag parsing
# ═══════════════════════════════════════════════════════════════════

class TestFlagParsing:
    def test_no_flags(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo hi")
        assert result.handled is True

    def test_flag_no_value(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo --verbose")
        assert result.handled is True

    def test_flag_with_value(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo --verbose true")
        assert result.handled is True

    def test_multiple_flags(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo --verbose true --detail high")
        assert result.handled is True


# ═══════════════════════════════════════════════════════════════════
#  Body extraction
# ═══════════════════════════════════════════════════════════════════

class TestBodyExtraction:
    def test_body_extracted(self, configured_handler):
        def capture(cmd: Command) -> CommandResult:
            return CommandResult(handled=True, response_text=cmd.raw_text)
        configured_handler.register_command("bodytest", capture)
        result = configured_handler.process_input("agent:1", "`bodytest — actual body text")
        assert result.handled is True
        assert "actual body text" in result.response_text


# ═══════════════════════════════════════════════════════════════════
#  @mention resolution
# ═══════════════════════════════════════════════════════════════════

class TestMentionResolution:
    def test_exact_name_resolves(self, configured_handler):
        # Body contains @Debugger → resolved to session_key, command handled
        result = configured_handler.process_input("agent:1", "`echo @Debugger — hi")
        assert result.handled is True

    def test_partial_name_resolves(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo @debug — hi")
        assert result.handled is True

    def test_empty_mention_no_project(self):
        """Empty @ with no project handler → error response_text."""
        agnt = FakeAgentManager({})
        h = CommandHandler(
            gateway_client=None, agent_manager=agnt,
            project_handler=None, GLib_module=None,
        )
        h.register_command("cmd", lambda c: CommandResult(handled=True, response_text="ok"))
        result = h.process_input("agent:1", "`cmd @ — message")
        assert result.handled is True
        assert "No active project" in result.response_text

    def test_unknown_mention_returns_error(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo @Nobody — hi")
        assert result.handled is True
        assert "Unknown agent" in result.response_text

    def test_multiple_partial_matches_returns_error(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo @q — hi")
        assert result.handled is True
        assert "Multiple agents" in result.response_text


# ═══════════════════════════════════════════════════════════════════
#  Error handling
# ═══════════════════════════════════════════════════════════════════

class TestErrorHandling:
    def test_handler_exception_returns_error_response(self, configured_handler):
        def bad(cmd: Command) -> CommandResult:
            raise RuntimeError("boom")
        configured_handler.register_command("bad", bad)
        result = configured_handler.process_input("agent:1", "`bad")
        assert result.handled is True
        assert "Error" in result.response_text
        assert "boom" in result.response_text


# ═══════════════════════════════════════════════════════════════════
#  Setters
# ═══════════════════════════════════════════════════════════════════

class TestSetters:
    def test_set_gateway_client(self, empty_handler):
        class FakeGW:
            pass
        gw = FakeGW()
        empty_handler.set_gateway_client(gw)
        assert empty_handler._gw is gw

    def test_set_agent_manager(self, empty_handler):
        class FakeAM:
            pass
        am = FakeAM()
        empty_handler.set_agent_manager(am)
        assert empty_handler._agent_mgr is am


# ═══════════════════════════════════════════════════════════════════
#  Command flow end-to-end
# ═══════════════════════════════════════════════════════════════════

class TestCommandFlow:
    def test_response_text_not_forwarded_to_gateway(self, configured_handler):
        result = configured_handler.process_input("agent:1", "`echo hello")
        assert result.handled is True
        assert result.response_text == "echo: echo"
        assert result.forward_to is None


# ═══════════════════════════════════════════════════════════════════
#  _parse_flags internal unit
# ═══════════════════════════════════════════════════════════════════

class TestParseFlagsInternal:
    def test_flag_consumes_value(self, empty_handler):
        flags, rest = empty_handler._parse_flags(["--verbose", "true", "arg"])
        assert flags == {"verbose": "true"}
        assert rest == ["arg"]

    def test_flag_without_value(self, empty_handler):
        # Design: --flag greedily takes the next non-flag token as its value
        flags, rest = empty_handler._parse_flags(["--verbose", "arg"])
        assert flags == {"verbose": "arg"}
        assert rest == []

    def test_consecutive_flags(self, empty_handler):
        flags, rest = empty_handler._parse_flags(["--a", "1", "--b", "2"])
        assert flags == {"a": "1", "b": "2"}
        assert rest == []

    def test_flag_followed_by_flag(self, empty_handler):
        # --verbose --detail high: --verbose has no value, --detail takes "high"
        flags, rest = empty_handler._parse_flags(["--verbose", "--detail", "high"])
        assert flags == {"verbose": "", "detail": "high"}
        assert rest == []

    def test_no_flags(self, empty_handler):
        flags, rest = empty_handler._parse_flags(["arg1", "arg2"])
        assert flags == {}
        assert rest == ["arg1", "arg2"]


# ═══════════════════════════════════════════════════════════════════
#  _parse_mentions internal unit
# ═══════════════════════════════════════════════════════════════════

class TestParseMentionsInternal:
    def test_single_mention(self, empty_handler):
        mentions, rest = empty_handler._parse_mentions(["@debugger", "arg1"])
        assert mentions == ["@debugger"]
        assert rest == ["arg1"]

    def test_multiple_consecutive_mentions(self, empty_handler):
        mentions, rest = empty_handler._parse_mentions(["@a", "@b", "arg1"])
        assert mentions == ["@a", "@b"]
        assert rest == ["arg1"]

    def test_non_mention_breaks_mention_run(self, empty_handler):
        # Non-@ token ends the mention run; subsequent @ are remaining args
        mentions, rest = empty_handler._parse_mentions(["@a", "stop", "@b"])
        assert mentions == ["@a", "@b"]
        assert rest == ["stop"]

    def test_no_mentions(self, empty_handler):
        mentions, rest = empty_handler._parse_mentions(["arg1", "arg2"])
        assert mentions == []
        assert rest == ["arg1", "arg2"]

    def test_empty_list(self, empty_handler):
        mentions, rest = empty_handler._parse_mentions([])
        assert mentions == []
        assert rest == []
