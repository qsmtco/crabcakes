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


_BODY_SEP = re.compile(r'\s+[—–]\s+')   # em-dash/en-dash with spaces — body separator (NOT regular hyphen)


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
        self._special_agents: dict[str, str] = {}  # {session_key: display_name}

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_gateway_client(self, gw) -> None:
        """Inject the live GatewayClient after connect. Called by window.py."""
        self._gw = gw

    def set_agent_manager(self, agent_mgr) -> None:
        """Inject the live AgentManager after connect. Called by window.py."""
        self._agent_mgr = agent_mgr

    def set_special_agents(self, agents: dict[str, str]) -> None:
        """Set special agent registry for @mention resolution.
        Called by window.py after AgentRuntimeHandler is created.
        Dict format: {session_key: display_name} e.g. {"special:coder": "Coder"}"""
        self._special_agents = agents

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

    def cmd_help(self, cmd: Command) -> CommandResult:
        """Handle `help [command] — returns command list card."""
        if cmd.args:
            name = cmd.args[0].lstrip("@")
            help_text = self.get_help(name)
            if help_text is None:
                help_text = f"Unknown command: `{name}"
            else:
                help_text = f"`{name}` — {help_text}"
            return CommandResult(handled=True, response_text=help_text)
        lines = [" CrabCakes Commands", ""]
        for name in self._registry.list_commands():
            alias_list = [al for al, cn in self._registry.list_aliases().items() if cn == name]
            alias_str = f" (`{', `'.join(alias_list)}`)" if alias_list else ""
            lines.append(f"  `{name}`{alias_str}")
        lines.extend(["", f"Type `help <command> for details."])
        return CommandResult(handled=True, response_text="\n".join(lines))

    def get_help(self, name: str) -> str | None:   # BUG #10 fix: public API for help
        """Return help text for a command, or None if not registered."""
        return self._registry.get_help(name)

    def get_command_names(self) -> set[str]:
        """Return registered command names as a set.

        Used by AgentCommandHandler to determine if a scanned backtick token
        is a known command (vs. arbitrary quoted text that looks like a command).
        Spec §4.4: returns set[str] for O(1) membership checks.
        """
        return set(self._registry.list_commands())

    def resolve_inline_mention(self, text: str, session_key: str = "") -> "MentionResolution":
        """Resolve @mentions from plain text (no backtick prefix required).

        This is the public API used by ChatHandler for inline @ routing in
        project tabs. Reuses the same parsing and resolution logic as the
        backtick command path but without requiring a command prefix.

        Args:
            text:         Raw input text from the user.
            session_key:  Source session key for project context resolution.

        Returns:
            MentionResolution with target info and cleaned text.
        """
        from models.command import MentionResolution

        if not isinstance(text, str) or not text.strip():
            return MentionResolution(clean_text=text)

        tokens = text.split()
        mentions, remaining = self._parse_mentions(tokens)

        if not mentions:
            # No @mention found — not our concern, return clean
            return MentionResolution(clean_text=text)

        if len(mentions) > 1:
            return MentionResolution(
                clean_text=text,
                error=f"Only one @mention allowed. Found: {', '.join(mentions)}",
            )

        # Resolve the single mention
        resolved = self._resolve_mention(mentions[0], session_key)

        if isinstance(resolved, CommandResult):
            # Error from resolution
            return MentionResolution(
                clean_text=" ".join(remaining),
                error=resolved.response_text,
            )
        elif isinstance(resolved, list):
            # Broadcast (@ alone → all project members)
            return MentionResolution(
                broadcast_targets=resolved,
                clean_text=" ".join(remaining),
                is_broadcast=True,
            )
        elif isinstance(resolved, str):
            # Single agent target
            return MentionResolution(
                target_session_key=resolved,
                clean_text=" ".join(remaining),
            )

        # Shouldn't reach here, but defensive
        return MentionResolution(clean_text=text, error="Unexpected resolution result")

    def process_input(self, session_key: str, text: str,
                       skip_dispatch: bool = False) -> CommandResult:
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

        # Bug #1 fix: if first token starts with @, treat as implicit "ask" command.
        # This allows `@Agent message` to work like `ask @Agent — message.
        if cmd_name.startswith("@"):
            rest_tokens = [cmd_name] + rest_tokens
            cmd_name = "ask"

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
        if len(pre_body_mentions) > 1:
            # Bug #3 fix: reject multiple @mentions explicitly
            return CommandResult(
                handled=True,
                response_text=f"Only one @mention allowed. Found: {', '.join(pre_body_mentions)}",
            )
        if pre_body_mentions:
            resolved = self._resolve_mention(pre_body_mentions[0], session_key)
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
            if len(body_mentions) > 1:
                return CommandResult(
                    handled=True,
                    response_text=f"Only one @mention allowed. Found: {', '.join(body_mentions)}",
                )
            if body_mentions:
                resolved = self._resolve_mention(body_mentions[0], session_key)
                if isinstance(resolved, str):
                    cmd.target_session_key = resolved
                elif isinstance(resolved, list):
                    if resolved:
                        cmd.target_session_key = resolved[0]
                else:
                    return resolved

        # Bug #2 fix: if no em-dash body was extracted but args remain after
        # @mention stripping, use them as the body text.
        if not cmd.body and cmd.args:
            cmd.body = " ".join(cmd.args)

        # Execute handler — guard against non-CommandResult returns
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
        # (skip when called from AgentCommandHandler — it handles routing itself)
        if result.handled and not skip_dispatch:
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

    _EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-z]{2,}$', re.IGNORECASE)

    def _parse_mentions(self, tokens: list[str]) -> tuple[list[str], list[str]]:
        """Extract @mentions from tokens, returning (mentions, remaining_args).

        Finds the first contiguous run of @tokens. All other tokens (before,
        between, and after) are preserved in remaining in original order.
        Only the first run is collected; subsequent @tokens after a break
        are treated as regular args.

        Skips tokens that look like email addresses (defensive).

        Returns:
            mentions:  List of @mention tokens from the first run.
            remaining: All non-collected tokens in original order.
        """
        mentions: list[str] = []
        remaining: list[str] = []
        state = "pre"  # pre | collecting | post

        for tok in tokens:
            if tok.startswith("@") and state != "post":
                # Skip email-like tokens
                if self._EMAIL_RE.match(tok[1:]):
                    remaining.append(tok)
                    state = "post"
                    continue
                mentions.append(tok)
                state = "collecting"
            else:
                remaining.append(tok)
                if state == "collecting":
                    state = "post"  # non-@ token ends the mention run

        return mentions, remaining

    def _resolve_mention(self, mention: str, session_key: str = "") -> str | list[str] | CommandResult:
        """Resolve @mention to session_key(s).

        - @        → all project members (list) OR error if no project_handler
        - @name    → exact or partial name match via AgentManager
        - No match → CommandResult error (handled=True, response_text=error)

        Args:
            mention:      The @token to resolve (e.g. "@Qaster" or "@")
            session_key:  Source session key for project context resolution.
                          Used to determine which project @ broadcast targets.
        """
        name = mention[1:]  # strip leading @

        if not name:
            # Empty @ → project broadcast
            proj_name = self._resolve_project_from_session(session_key)
            if proj_name and self._project_handler is not None:
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
            # Try prefix match (starts-with, not contains)
            if len(name) >= 2:
                matches = [sk for sk, n in names_ref.items() if n.lower().startswith(name.lower())]
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    get_name = getattr(self._agent_mgr, 'get_name', lambda sk: sk)
                    names = [get_name(sk) for sk in matches]
                    return CommandResult(
                        handled=True,
                        response_text=f"Multiple agents match @{name}: {', '.join(names)}",
                    )

        # Search special agents (Coder, Debugger, etc.)
        for sk, display_name in self._special_agents.items():
            if display_name.lower() == name.lower():
                return sk
        if len(name) >= 2:
            matches = [sk for sk, dn in self._special_agents.items()
                       if dn.lower().startswith(name.lower())]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                names = [self._special_agents[sk] for sk in matches]
                return CommandResult(
                    handled=True,
                    response_text=f"Multiple agents match @{name}: {', '.join(names)}",
                )

        return CommandResult(
            handled=True,
            response_text=f"Unknown agent: @{name}",
        )

    def _resolve_project_from_session(self, session_key: str) -> str | None:
        """Resolve project name from a session key.

        For project tabs (session_key starts with "project:"), extracts
        the project name from the key. Falls back to the global active
        project name for backward compatibility.

        Args:
            session_key: Source session key to resolve project from.

        Returns:
            Project name or None.
        """
        # Project tab: extract directly from session key
        if session_key.startswith("project:"):
            return session_key.split(":", 1)[1]
        # Fallback: global active project (backward compat)
        if self._project_handler is not None:
            return self._project_handler.get_active_project_name()
        return None

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
