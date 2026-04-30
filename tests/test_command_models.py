# tests/test_command_models.py
# Unit tests for models/command.py — Command, CommandResult, CommandRegistry.
#
# Principle: test the contract — each public method's documented behavior.
# Edge cases that could break callers (CommandHandler, window.py) are covered.


import pytest
from models.command import Command, CommandResult, CommandRegistry


# ═══════════════════════════════════════════════════════════════════
#  Command dataclass
# ═══════════════════════════════════════════════════════════════════

class TestCommandDefaults:
    """Default values so callers don't have to fill in everything."""

    def test_default_args_is_empty_list(self):
        c = Command(name="ask")
        assert c.args == []
        assert isinstance(c.args, list)

    def test_default_flags_is_empty_dict(self):
        c = Command(name="ask")
        assert c.flags == {}
        assert isinstance(c.flags, dict)

    def test_default_target_session_key_is_none(self):
        c = Command(name="ask")
        assert c.target_session_key is None


class TestCommandAllFields:
    def test_all_fields_set_correctly(self):
        c = Command(
            name="delegate",
            args=["@coder"],
            flags={"priority": "high"},
            raw_text="delegate @coder — fix memory",
            source_session_key="agent:pm:1",
            target_session_key="agent:coder:1",
        )
        assert c.name == "delegate"
        assert c.args == ["@coder"]
        assert c.flags == {"priority": "high"}
        assert c.raw_text == "delegate @coder — fix memory"
        assert c.source_session_key == "agent:pm:1"
        assert c.target_session_key == "agent:coder:1"


# ═══════════════════════════════════════════════════════════════════
#  CommandResult dataclass
# ═══════════════════════════════════════════════════════════════════

class TestCommandResultDefaults:
    """Default values match the pass-through behavior described in the spec."""

    def test_handled_defaults_to_false(self):
        r = CommandResult()
        assert r.handled is False

    def test_response_text_defaults_to_none(self):
        r = CommandResult()
        assert r.response_text is None

    def test_response_card_defaults_to_none(self):
        r = CommandResult()
        assert r.response_card is None

    def test_forward_to_defaults_to_none(self):
        r = CommandResult()
        assert r.forward_to is None

    def test_forward_text_defaults_to_none(self):
        r = CommandResult()
        assert r.forward_text is None


class TestCommandResultFields:
    def test_forward_routing_fields(self):
        r = CommandResult(
            handled=True,
            forward_to="agent:coder:1",
            forward_text="please review",
        )
        assert r.handled is True
        assert r.forward_to == "agent:coder:1"
        assert r.forward_text == "please review"
        assert r.response_text is None   # forward takes priority

    def test_response_card_field(self):
        r = CommandResult(
            handled=True,
            response_card={"type": "task", "id": 3, "text": "Implement JWT"},
        )
        assert r.handled is True
        assert r.response_card["type"] == "task"


# ═══════════════════════════════════════════════════════════════════
#  CommandRegistry — register
# ═══════════════════════════════════════════════════════════════════

class TestRegistryRegister:
    """register() is the only way to add commands — called by window.py setup."""

    def test_register_then_get_returns_handler(self):
        reg = CommandRegistry()
        handler = lambda cmd: CommandResult(handled=True)
        reg.register("ask", handler)
        assert reg.get("ask") is handler

    def test_register_stores_help_text(self):
        reg = CommandRegistry()
        reg.register("ask", lambda cmd: CommandResult(), help_text="Ask an agent")
        assert reg.get_help("ask") == "Ask an agent"

    def test_aliases_registered(self):
        reg = CommandRegistry()
        handler = lambda cmd: CommandResult()
        reg.register("ask", handler, aliases=["a"])
        assert reg.get("a") is handler

    def test_multiple_aliases(self):
        reg = CommandRegistry()
        handler = lambda cmd: CommandResult()
        reg.register("ask", handler, aliases=["a", "askq"])
        assert reg.get("a") is handler
        assert reg.get("askq") is handler


# ═══════════════════════════════════════════════════════════════════
#  CommandRegistry — get
# ═══════════════════════════════════════════════════════════════════

class TestRegistryGet:
    def test_unknown_command_returns_none(self):
        reg = CommandRegistry()
        assert reg.get("nonexistent") is None

    def test_case_insensitive_canonical(self):
        reg = CommandRegistry()
        reg.register("ask", lambda cmd: CommandResult())
        assert reg.get("ASK") is not None
        assert reg.get("Ask") is not None

    def test_alias_resolves_to_canonical(self):
        reg = CommandRegistry()
        handler = lambda cmd: CommandResult()
        reg.register("ask", handler, aliases=["a"])
        assert reg.get("a") is handler
        assert reg.get("A") is handler


# ═══════════════════════════════════════════════════════════════════
#  CommandRegistry — list_commands
# ═══════════════════════════════════════════════════════════════════

class TestRegistryListCommands:
    def test_empty_registry(self):
        reg = CommandRegistry()
        assert reg.list_commands() == []

    def test_returns_sorted_list(self):
        reg = CommandRegistry()
        reg.register("z", lambda cmd: CommandResult())
        reg.register("a", lambda cmd: CommandResult())
        reg.register("m", lambda cmd: CommandResult())
        assert reg.list_commands() == ["a", "m", "z"]


# ═══════════════════════════════════════════════════════════════════
#  CommandRegistry — get_help
# ═══════════════════════════════════════════════════════════════════

class TestRegistryGetHelp:
    def test_unknown_command_returns_none(self):
        reg = CommandRegistry()
        assert reg.get_help("ask") is None

    def test_alias_resolves_to_canonical_help(self):
        reg = CommandRegistry()
        reg.register("ask", lambda cmd: CommandResult(), aliases=['a'], help_text="ask help text")
        assert reg.get_help("a") == "ask help text"
        assert reg.get_help("ASK") == "ask help text  [aliases: a]"

    def test_no_help_text_returns_empty_string(self):
        reg = CommandRegistry()
        reg.register("ask", lambda cmd: CommandResult())
        assert reg.get_help("ask") == ""
