# ui/handlers/command_handler.py
# Command handler — parses backtick commands, routes results.
#
# Manifest:
#   reads:   nothing
#   writes:  nothing
#   network: gateway_client.send_message() for forward_routing
#   GTK:     on_display_card(), on_display_text() callbacks only
#
# Owns:
#   - Command prefix detection and parsing
#   - @mention → session_key resolution via AgentManager
#   - --flag parsing
#   - CommandRegistry (owns the handler map)
#   - Result routing: forward / display_card / display_text
#
# Does NOT own:
#   - GTK widgets (only calls back to window for display)
#   - Other handlers (window wires cross-handler communication)
#   - Gateway connection lifecycle
#
# Thread safety: All GTK operations dispatched via GLib.idle_add().
# Public entry point process_input() may be called from main thread (PM input)
# or from gateway background thread — GLib dispatch handles both.


import re
from typing import Callable

from models.command import Command, CommandResult, CommandRegistry
from utils.config import COMMAND_PREFIX   # BUG #9 fix: config is source of truth


_BODY_SEP = re.compile(r'\s+[-—–]\s+')   # hyphen/em-dash/en-dash with spaces — body separator


class CommandHandler:
    """Parses and executes backtick commands.

    Architecture:
        - process_input() is the single public entry point called by ChatHandler
        - Owns a CommandRegistry for handler lookup
        - Resolves @mentions via AgentManager
        - Returns CommandResult; ChatHandler and window act on the result

    Integration with ChatHandler:
        ChatHandler.on_send() calls process_input() before its own send logic.
        If result.handled is True, ChatHandler skips gateway send —
        CommandHandler dispatched the forward/display itself.
    """

    def __init__(
        self,
        gateway_client,           # GatewayClient — for send_message()
        agent_manager,            # AgentManager — for @mention resolution
        project_handler,          # ProjectHandler — for project member lookups
        GLib_module=None,         # gi.repository.GLib or None
        on_display_card=None,     # callback(card_dict) — render a card in chat
        on_display_text=None,     # callback(session_key, text) — display text in chat
    ):
        self._gw = gateway_client
        self._agent_mgr = agent_manager
        self._project_handler = project_handler
        self._GLib = GLib_module
        self._on_display_card = on_display_card
        self._on_display_text = on_display_text
        self._prefix = COMMAND_PREFIX   # BUG #9 fix: read from config at construction
        self._registry = CommandRegistry()

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_gateway_client(self, gw) -> None:
        """Inject the live GatewayClient after connect. Called by window.py."""
        self._gw = gw

    def set_agent_manager(self, agent_mgr) -> None:
        """Inject the live AgentManager after connect. Called by window.py."""
        self._agent_mgr = agent_mgr

    def register_command(
        self,
        name: str,
        handler: Callable[[Command], CommandResult],
        *,
        aliases: list[str] | None = None,
        help_text: str = "",
    ) -> None:
        """Register a command handler. Called by window during setup."""
        self._registry.register(name, handler, aliases=aliases, help_text=help_text)

    def set_prefix(self, char: str) -> None:
        """Change the command prefix character. Default: backtick."""
        self._prefix = char

    def get_help(self, name: str) -> str | None:   # BUG #10 fix: public API for help
        """Return help text for a command, or None if not registered."""
        return self._registry.get_help(name)

    def process_input(self, session_key: str, text: str) -> CommandResult:
        """Parse and execute a command from input text.

        Decision tree:
          - Text does not start with prefix → not a command, pass through
          - Command not found in registry    → pass through (unknown command)
          - Command found                  → execute handler → return result

        Called by ChatHandler.on_send() before gateway send.
        May be called from background threads — all GTK calls go through
        GLib.idle_add().

        Returns:
            CommandResult with the routing decision.
            handled=False means: not a command OR unknown command → pass through.
        """
        # BUG #2 fix: type safety — text must be a string
        if not isinstance(text, str):
            return CommandResult(handled=False)

        if not text.startswith(self._prefix):
            return CommandResult(handled=False)

        raw = text[len(self._prefix):].strip()
        if not raw:
            return CommandResult(handled=False)

        # Split off body (after " — " em-dash separator)
        body = ""
        parts = _BODY_SEP.split(raw, maxsplit=1)
        if len(parts) == 2:
            raw, body = parts[0], parts[1].strip()

        # First token = command name
        tokens = raw.split()
        if not tokens:
            return CommandResult(handled=False)
        cmd_name = tokens[0].lower()
        rest_tokens = tokens[1:]

        # Look up handler
        handler = self._registry.get(cmd_name)
        if handler is None:
            return CommandResult(handled=False)

        # Parse --flags from remaining tokens
        flags, remaining_args = self._parse_flags(rest_tokens)

        # Build Command — body is the text after the em-dash separator.
        # @mentions are resolved and stripped from args during mention parsing.
        cmd = Command(
            name=cmd_name,
            args=remaining_args,      # @mention tokens stripped by _parse_mentions
            flags=flags,
            raw_text=text[len(self._prefix):].strip(),
            body=body,               # BUG #1 fix: store body in Command
            source_session_key=session_key,
            target_session_key=None,
        )

        # BUG #6 fix: strip @mentions from args.
        # _parse_flags splits --flags from args but leaves @tokens.
        # _parse_mentions returns args with @tokens removed (remaining).
        # Use 'remaining' as cmd.args after mention resolution.
        pre_body_mentions, post_mention_args = self._parse_mentions(rest_tokens)
        cmd.args = post_mention_args
        if pre_body_mentions:
            resolved = self._resolve_mention(pre_body_mentions[0])
            if isinstance(resolved, str):
                cmd.target_session_key = resolved
            elif isinstance(resolved, list):
                # BUG #4 fix: empty @ → broadcast to all project members.
                # Store first as target and set broadcast_targets so ChatHandler fans out.
                if resolved:
                    cmd.target_session_key = resolved[0]
                    cmd.is_broadcast = True
                    cmd.broadcast_targets = resolved   # full list for fan-out
            else:
                return resolved

        # Body-position @mentions (after — separator) only if no pre-body mentions.
        if body and not pre_body_mentions:
            body_mentions, _ = self._parse_mentions(body.split())
            if body_mentions:
                resolved = self._resolve_mention(body_mentions[0])
                if isinstance(resolved, str):
                    cmd.target_session_key = resolved
                elif isinstance(resolved, list):
                    if resolved:
                        cmd.target_session_key = resolved[0]
                else:
                    return resolved

        # Execute handler — BUG #3 fix: guard against non-CommandResult returns
        try:
            result = handler(cmd)
        except Exception as exc:
            return CommandResult(
                handled=True,
                response_text=f"Error: {exc}",
            )

        if not isinstance(result, CommandResult):
            return CommandResult(
                handled=True,
                response_text=f"Error: handler returned {type(result).__name__}",
            )

        # Dispatch GTK side effects via GLib if needed
        if result.handled:
            self._dispatch_result(result, session_key)

        return result

    # ── Internal ─────────────────────────────────────────────────────────────

    def _parse_flags(self, tokens: list[str]) -> tuple[dict[str, str], list[str]]:
        """Extract --flag value pairs from tokens.

        Returns (flags_dict, remaining_tokens) with --flags removed.
        --verbose (no value) stores as flags["verbose"] = "".
        --flag value stores as flags["flag"] = "value".
        """
        flags: dict[str, str] = {}
        out: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.startswith("--") and len(tok) > 2:
                key = tok[2:]
                if key in flags:   # BUG #11 fix: warn on duplicate flag
                    import logging
                    logging.warning(f"Duplicate flag --{key}, overwriting previous value")
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    flags[key] = tokens[i + 1]
                    i += 2
                else:
                    flags[key] = ""
                    i += 1
            else:
                out.append(tok)
                i += 1
        return flags, out

    def _parse_mentions(self, tokens: list[str]) -> tuple[list[str], list[str]]:
        mentions: list[str] = []
        remaining: list[str] = []
        seen_any_mention = False
        for tok in tokens:
            if tok.startswith("@"):
                mentions.append(tok)
                seen_any_mention = True
        if not seen_any_mention:
            return [], list(tokens)
        # Second pass: collect remaining args (tokens after first non-@ following mentions)
        seen_mention = False
        for tok in tokens:
            if tok.startswith("@"):
                seen_mention = True
            elif seen_mention:
                remaining.append(tok)
        return mentions, remaining

    def _resolve_mention(self, mention: str) -> str | list[str] | CommandResult:
        """Resolve @mention to session_key(s).

        - @        → all project members (list) OR error if no project_handler
        - @name    → exact or partial name match via AgentManager
        - No match → CommandResult error (handled=True, response_text=error)
        """
        name = mention[1:]  # strip leading @

        if not name:
            # Empty @ → project broadcast
            if self._project_handler is not None:
                proj_name = self._project_handler.get_active_project_name()
                if proj_name:
                    members = self._project_handler.get_project_members(proj_name)
                    if members:
                        return members
            return CommandResult(
                handled=True,
                response_text="No active project for @ broadcast.",
            )

        # Exact match via AgentManager
        if self._agent_mgr is not None:
            # AgentManager.get_names_ref() → {session_key: name}
            names_ref = self._agent_mgr.get_names_ref()
            # Try exact name match first
            for sk, n in names_ref.items():
                if n.lower() == name.lower():
                    return sk
            # Try partial match (first contains)
            matches = [sk for sk, n in names_ref.items() if name.lower() in n.lower()]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                # BUG #7 fix: use getattr to avoid crash if agent_mgr lacks get_name()
                get_name = getattr(self._agent_mgr, 'get_name', lambda sk: sk)
                names = [get_name(sk) for sk in matches]
                return CommandResult(
                    handled=True,
                    response_text=f"Multiple agents match @{name}: {', '.join(names)}",
                )

        return CommandResult(
            handled=True,
            response_text=f"Unknown agent: @{name}",
        )

    def _dispatch_result(self, result: CommandResult, session_key: str) -> None:
        """Dispatch GTK side effects of a handled CommandResult.

        Note: forward_to/forward_text routing is handled by ChatHandler, not here.
        This avoids double-send (ChatHandler already calls _gw.send_message for
        forward commands after process_input returns).
        """
        def _do():
            try:
                if result.response_card and self._on_display_card:
                    self._on_display_card(result.response_card)
                if result.response_text and self._on_display_text:
                    self._on_display_text(session_key, result.response_text)
            except Exception as exc:
                import logging
                logging.exception("Error dispatching command result")

        if self._GLib is not None:
            self._GLib.idle_add(_do)
        else:
            _do()

    def _dispatch(self, fn: Callable) -> None:
        """Call fn on the GTK main thread. Direct call if GLib not available."""
        if self._GLib is not None:
            def _wrap():
                fn()
                return False
            self._GLib.idle_add(_wrap)
        else:
            fn()
