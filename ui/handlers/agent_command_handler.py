# ui/handlers/agent_command_handler.py
# Agent Response Command Parser — agent-initiated A2A with relay (Phase 6.2).
#
# Manifest:
#   reads:   nothing
#   writes:  nothing
#   network: gateway_client.send_message() for gateway agent routing
#   GTK:     none (callbacks dispatched by callers on main thread)
#
# Architecture:
#   - Follows handler pattern: receives all dependencies via setters
#   - Never imports from ui/handlers/
#   - Thread safety: on_agent_response() is called from main thread via
#     GLib.idle_add() in both ChatHandler._handle_final_response() and
#     AgentRuntimeHandler._do_response_complete() — no additional dispatch needed.
#
# Wire points (window.py):
#   - set_command_handler()      → CommandHandler instance
#   - set_agent_runtime_handler() → AgentRuntimeHandler instance
#   - set_gateway_client()       → GatewayClient instance (may be None offline)
#   - set_agent_manager()        → AgentManager instance
#   - set_agent_routing()        → AgentRoutingTable instance
#   - set_project_handler()       → ProjectHandler instance
#   - set_awareness_sent()       → shared _awareness_sent set from ChatHandler

import re
import logging

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Max nested command chains before cutoff.
_MAX_CHAIN_DEPTH = 3

# Max commands parsed from a single agent response.
_MAX_COMMANDS_PER_RESPONSE = 3

# Regex for single-backtick-quoted content: `command text`
_BACKTICK_COMMAND = re.compile(r"`([^`\n]+?)(?:`|$)")


class AgentCommandHandler:
    """Parses backtick commands from agent response text, routes them to target
    agents, and relays responses back to the asking agent.

    Wired via window.py. Receives all dependencies through setters.
    """

    def __init__(self, *, GLib_module=None):
        self._command_handler = None       # CommandHandler
        self._agent_runtime_handler = None  # AgentRuntimeHandler
        self._gw = None                     # GatewayClient
        self._agent_mgr = None              # AgentManager
        self._agent_to_project = None       # AgentRoutingTable
        self._project_handler = None        # ProjectHandler
        self._awareness_sent: set[str] | None = None  # Shared set from ChatHandler

        # Chain depth: session_key → depth counter
        self._chain_depth: dict[str, int] = {}

        # Pending asks: target_session_key → source_session_key
        # When Agent A asks Agent B, we record _pending_asks[B] = A.
        # When B responds, we relay B's answer back to A.
        # Only set for response-expecting commands (ask, delegate). `tell` is
        # one-way and does NOT create a pending ask.
        self._pending_asks: dict[str, str] = {}

    # ── Setters (wired by window.py) ─────────────────────────────────────────

    def set_command_handler(self, handler) -> None:
        """CommandHandler — provides process_input() and get_command_names()."""
        self._command_handler = handler

    def set_agent_runtime_handler(self, handler) -> None:
        """AgentRuntimeHandler — for special agent routing."""
        self._agent_runtime_handler = handler

    def set_gateway_client(self, gw) -> None:
        """GatewayClient — for gateway agent routing. May be None if offline."""
        self._gw = gw

    def set_agent_manager(self, mgr) -> None:
        """AgentManager — for display name resolution."""
        self._agent_mgr = mgr

    def set_agent_routing(self, routing_table) -> None:
        """AgentRoutingTable — for project→agent lookups."""
        self._agent_to_project = routing_table

    def set_project_handler(self, handler) -> None:
        """ProjectHandler — for project_path (awareness prefix in agent-initiated
        gateway messages)."""
        self._project_handler = handler

    def set_awareness_sent(self, awareness_set: set[str]) -> None:
        """Shared _awareness_sent set from ChatHandler — for first-time
        project awareness prefix injection on gateway agent sends."""
        self._awareness_sent = awareness_set

    # ── Core entry point ──────────────────────────────────────────────────────

    def on_agent_response(self, session_key: str, text: str,
                          project_name: str | None) -> None:
        """Called after an agent's final response is rendered.

        Two responsibilities:
        1. RELAY: If this agent has a pending ask (someone asked it a question),
           relay its response back to the asking agent.
        2. COMMAND SCAN: Scan the response text for backtick commands.
           If found, parse and route them to target agents.

        Args:
            session_key: The responding agent's session key
                         (e.g. "special:coder" or "agent:qaster:...")
            text: The agent's full response text
            project_name: Active project name, or None
        """
        if not text:
            return

        # ── Step 1: Relay answer back to asking agent ────────────────────────

        source_sk = self._pending_asks.pop(session_key, None)
        if source_sk is not None:
            self._relay_response(source_sk, session_key, text, project_name)

        # ── Step 2: Scan for new commands ─────────────────────────────────────

        # Command scanning is only available when command_handler is set
        if not self._command_handler:
            # No command handler — clear depth and return (relay already done above)
            self._chain_depth.pop(session_key, None)
            return

        # Chain depth guard — prevent runaway command chains.
        # Must check BEFORE any command processing to respect the limit.
        depth = self._chain_depth.get(session_key, 0)
        if depth >= _MAX_CHAIN_DEPTH:
            logger.warning(
                "[agent-cmd] Chain depth limit (%d) reached for %s — dropping commands",
                _MAX_CHAIN_DEPTH, session_key
            )
            self._chain_depth.pop(session_key, None)
            return

        # Strip fenced code blocks to avoid false positives
        clean_text = self._strip_fenced_blocks(text)

        # Extract and filter backtick commands
        matches = _BACKTICK_COMMAND.findall(clean_text)

        # Process commands if any are found
        if matches:
            known_commands = self._command_handler.get_command_names()
            command_count = 0

            for raw_match in matches:
                if command_count >= _MAX_COMMANDS_PER_RESPONSE:
                    logger.warning(
                        "[agent-cmd] Per-response command limit (%d) reached — skipping remaining",
                        _MAX_COMMANDS_PER_RESPONSE
                    )
                    break

                # Reconstruct in canonical command format for process_input.
                # Canonical form: `cmd @Agent — body text
                # This prevents em-dashes in the body from being misinterpreted
                # as the body separator.
                first_word = raw_match.strip().split()[0].lower() if raw_match.strip() else ""

                # Implicit ask: @AgentName → treat as "ask"
                if first_word.startswith("@"):
                    first_word = "ask"

                if first_word not in known_commands:
                    continue  # Not a recognized command — skip

                # Parse the raw match into command + @agent + rest, then
                # rebuild with explicit em-dash separator.
                match_tokens = raw_match.strip().split()
                cmd_token = match_tokens[0]  # e.g. "ask" or "tell"
                rest_tokens = match_tokens[1:]

                # Find the @agent token and separate it from the body text
                agent_token = ""
                body_tokens = []
                for tok in rest_tokens:
                    if not agent_token and tok.startswith("@"):
                        agent_token = tok
                    else:
                        body_tokens.append(tok)

                if agent_token:
                    body_text = " ".join(body_tokens)
                    candidate = f"`{cmd_token} {agent_token} — {body_text}"
                else:
                    candidate = f"`{raw_match}"

                result = self._command_handler.process_input(session_key, candidate,
                                                             skip_dispatch=True)
                if result.handled and result.forward_to and result.forward_text:
                    self._route_command(result, project_name, depth, source_sk=session_key,
                                        command_name=first_word)
                    command_count += 1
                elif result.handled and result.broadcast_targets and result.forward_text:
                    for target in result.broadcast_targets:
                        self._route_to_target(
                            target, result.forward_text, project_name
                        )
                    command_count += 1

    # ── Relay ─────────────────────────────────────────────────────────────────

    def _relay_response(self, source_sk: str, target_sk: str,
                        text: str, project_name: str | None) -> None:
        """Relay an agent's response back to the agent that asked it a question.

        Args:
            source_sk: Session key of the agent that asked the question (recipient)
            target_sk: Session key of the agent that answered (responder)
            text: The responder's full response text
            project_name: Active project name, or None
        """
        # Resolve display name of the answering agent
        display_name = self._resolve_display_name(target_sk)
        relay_text = f"[{display_name} responded]: {text}"

        logger.info(
            "[agent-cmd] Relaying response from %s (%s) back to %s",
            display_name, target_sk, source_sk
        )

        # Clear chain depth for source — the relay is a new context message,
        # not a command chain hop from source
        self._chain_depth.pop(source_sk, None)

        self._route_to_target(source_sk, relay_text, project_name)

    # ── Routing ───────────────────────────────────────────────────────────────

    def _route_command(self, result, project_name: str | None,
                       current_depth: int, source_sk: str,
                       command_name: str = "") -> None:
        """Route a single CommandResult to the target agent and record pending ask.

        Only records a pending ask for response-expecting commands (ask, delegate).
        `tell` is one-way and does NOT set up a relay.
        """
        target_sk = result.forward_to

        # Resolve display_name → session_key for special agents.
        # CommandHandler returns display_name (e.g. "Debugger"), not session_key.
        resolved_sk = self._resolve_special_agent_sk(target_sk)
        is_special = resolved_sk is not None

        # Use resolved_sk if special agent, else original target_sk
        record_key = resolved_sk if is_special else target_sk
        depth_key = resolved_sk if is_special else target_sk

        # Record pending ask ONLY for response-expecting commands
        if command_name != "tell":
            self._pending_asks[record_key] = source_sk

        # Increment chain depth for the target
        self._chain_depth[depth_key] = current_depth + 1

        # Route the message to the target — prefix with asking agent's identity
        # so the target knows who's asking (not the human, but another agent)
        route_key = resolved_sk if is_special else target_sk
        sender_name = self._resolve_display_name(source_sk)
        forward_text = f"[{sender_name} asks]: {result.forward_text}"
        self._route_to_target(route_key, forward_text, project_name)

    def _route_to_target(self, target_sk: str, text: str,
                         project_name: str | None) -> None:
        """Send message to a target agent via the correct transport."""
        # Check if target_sk is already a session key (direct lookup in special_agents).
        # This handles relay calls where source_sk is already a session key like "special:coder".
        if self._agent_runtime_handler is not None and \
           target_sk in self._agent_runtime_handler.get_special_agents():
            self._agent_runtime_handler.send_to_special_agent(target_sk, text)
            return

        # Try resolving display_name → session_key (CommandHandler returns display names)
        resolved_sk = self._resolve_special_agent_sk(target_sk)
        if resolved_sk is not None:
            self._agent_runtime_handler.send_to_special_agent(resolved_sk, text)
            return

        # Fallback to gateway routing for gateway agents
        if self._gw is not None and self._gw.is_connected():
            # Inject awareness prefix for first-time (project, agent) pairs
            prefix = ""
            if project_name and self._awareness_sent is not None:
                key = f"{project_name}:{target_sk}"
                if key not in self._awareness_sent:
                    prefix = self._build_awareness_prefix(project_name)
                    self._awareness_sent.add(key)
            self._gw.send_message(target_sk, prefix + text)
        else:
            logger.debug(
                "[agent-cmd] Cannot route to %s — no gateway connection", target_sk
            )

    def _resolve_special_agent_sk(self, display_name: str) -> str | None:
        """Resolve a display name (e.g. "Debugger") to a special agent session key.

        CommandHandler.process_input() returns display_name as forward_to, not
        session_key. Reverse-map to find the session_key for routing.
        """
        if self._agent_runtime_handler is None:
            return None
        specials = self._agent_runtime_handler.get_special_agents()
        display_to_sk = {v: k for k, v in specials.items()}
        return display_to_sk.get(display_name)

    def _resolve_display_name(self, session_key: str) -> str:
        """Resolve a session key to a human-readable display name."""
        if self._agent_runtime_handler is not None:
            specials = self._agent_runtime_handler.get_special_agents()
            if session_key in specials:
                return specials[session_key]
        if self._agent_mgr is not None:
            name = self._agent_mgr.get_name(session_key)
            if name:
                return name
        return session_key.split("/")[-1]

    def _build_awareness_prefix(self, project_name: str) -> str:
        """Build project awareness prefix for gateway agent messages.

        NOTE: Duplicated from ChatHandler because handlers cannot import each other.
        """
        if not self._project_handler:
            return ""
        project_path = self._project_handler.get_active_project_path()
        if not project_path:
            return ""
        parts: list[str] = []
        try:
            from utils.project_awareness import build_awareness_block
            block = build_awareness_block(project_path)
            if block.strip():
                parts.append(block.strip())
        except Exception:
            pass  # Awareness is best-effort
        try:
            from utils.prompt_loader import load_prompt_template
            collab = load_prompt_template("collab")
            if collab and collab.strip():
                parts.append(collab.strip())
        except Exception:
            pass
        if not parts:
            return ""
        return "\n\n".join(parts) + "\n\n"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_fenced_blocks(text: str) -> str:
        """Remove fenced code blocks (```...```) from text.

        Prevents false-positive command detection on code examples.
        Handles both ```language\ncode``` and ```inline``` forms.
        """
        return re.sub(r"```.*?```", "", text, flags=re.DOTALL)