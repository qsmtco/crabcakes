# ui/handlers/agent_runtime_handler.py
# Phase 1.4 — Wires AgentRuntime into CrabCakes UI as a special agent.
#
# Responsibility: Owns the AgentRuntime lifecycle + dispatches its callbacks
#                 to the chat render pipeline.
#                 Provides the add_special_agent() API for window.py to register
#                 special agents (e.g. "Coder") that run without a gateway.
#
# Thread safety: All GTK operations are dispatched via GLib.idle_add when
#               GLib is provided. AgentRuntime callbacks are already dispatched
#               by the runtime; this handler just routes them to the render layer.
#
# Owner: window.py (composition root) — instantiates, owns reference.

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime, timezone
from models.feed_card import FeedCardData
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from gi.repository import GLib
    from agent.config import AgentConfig

logger = logging.getLogger(__name__)


class AgentRuntimeHandler:
    """
    Wires AgentRuntime into the CrabCakes UI.

    Provides add_special_agent() to register named agents that route through
    AgentRuntime instead of the gateway. Handles the callbacks from AgentRuntime
    and routes them to ChatRenderHandler for display.

    Args:
        main_content:       MainContent instance — for get_chat_box_for_session()
        chat_render_handler: ChatRenderHandler — for start/update/end_streaming
        GLib_module:        gi.repository.GLib or None
    """

    def __init__(
        self,
        main_content,          # MainContent
        chat_render_handler,  # ChatRenderHandler
        GLib_module: "GLib | None" = None,
        review_handler=None,   # ReviewHandler — optional, for Phase 1.5 review layer
    ):
        self._mc = main_content
        self._crh = chat_render_handler
        self._fh = None  # FeedHandler — set via set_feed_handler() (Phase D)
        self._GLib = GLib_module
        self._review_handler = review_handler

        # Registered agents: session_key → SpecialAgentDef (full definition)
        self._agents: dict[str, Any] = {}
        # Active project: (name, path) or None
        self._active_project: tuple[str, str] | None = None
        # name → AgentRuntime instance (one rt per agent for isolation)
        self._runtimes: dict[str, Any] = {}
        # Tool call → feed card ID mapping: session_key → card_id
        # Used by Phase D to update feed cards when tool calls complete.
        # Keyed by session_key only — tool_name stored in card metadata.
        self._tool_card_ids: dict[str, str] = {}
        # Pending approval cards: approval_id (card_id) → {session_key, tool_name, args}
        # Used by Phase E to resolve approvals when PM clicks Approve/Deny.
        self._pending_approvals: dict[str, dict] = {}

    def set_review_handler(self, review_handler) -> None:
        """Set ReviewHandler after construction (deferred to avoid circular deps with window._build)."""
        self._review_handler = review_handler

    def set_feed_handler(self, feed_handler) -> None:
        """Set FeedHandler. Called by window.py during _build (Phase D)."""
        self._fh = feed_handler

    def set_active_project(self, project_name: str, project_path: str) -> None:
        """
        Set the active project for all special agents.

        Called by window.py when a project tab opens:
          self._project_handler.set_on_project_opened(
              lambda n, p: self._agent_runtime_handler.set_active_project(n, p)
          )

        This injects project_path into all existing conversations and ensures
        new conversations get the correct project context (fixes Phase A root cause).
        """
        self._active_project = (project_name, project_path)
        # Update project_path on all existing conversations
        for sk, agent_def in self._agents.items():
            rt = self._runtimes.get(agent_def.display_name)
            if rt is None:
                continue
            conv = rt.get_conversation(sk)
            if conv is not None and conv.project_path != project_path:
                conv.project_path = project_path
                # Rebuild system prompt with new project context
                from agent.context import build_system_prompt
                tool_names = agent_def.tools
                conv.system_prompt = build_system_prompt(
                    agent_def.display_name, project_path, tool_names
                )
        logger.info("AgentRuntimeHandler: active project set to %s (%s)", project_name, project_path)

    def clear_active_project(self) -> None:
        """
        Clear the active project. Called by window.py when the project tab closes.

          self._project_handler.set_on_project_closed(
              lambda name: self._agent_runtime_handler.clear_active_project()
          )
        """
        self._active_project = None
        logger.info("AgentRuntimeHandler: active project cleared")

    # ── Special agent registration ──────────────────────────────────────────

    def add_special_agent(self, agent_def: Any) -> None:
        """
        Register a special agent backed by AgentRuntime.

        Args:
            agent_def: SpecialAgentDef — the full agent definition.

        The agent appears in the agents list via set_special_agents() in window.py.
        """
        self._agents[agent_def.conv_id_prefix] = agent_def
        logger.info("Registered special agent: %s (%s)", agent_def.display_name, agent_def.conv_id_prefix)

    def get_special_agents(self) -> dict[str, str]:
        """Return {session_key: display_name} for registered special agents."""
        return {sk: ad.display_name for sk, ad in self._agents.items()}

    def get_special_agent_def(self, session_key: str) -> Any | None:
        """Return the SpecialAgentDef for a session key, or None."""
        return self._agents.get(session_key)

    def approve_exec(self, approval_id: str, approved: bool) -> None:
        """
        Resolve a pending exec_command approval.

        Called when the PM clicks Approve or Deny on a pending-approval feed card.
        approval_id is the card_id of the approval card.

        The handler-level approval_id (card_id) maps to the runtime's
        (session_key, tool_name, args) via self._pending_approvals.
        """
        pending = self._pending_approvals.pop(approval_id, None)
        if pending is None:
            logger.warning("approve_exec: no pending approval for %s", approval_id)
            return

        session_key = pending["session_key"]
        tool_name = pending["tool_name"]
        args = pending["args"]

        # Find the runtime that owns this session and forward the approval
        for name, rt in self._runtimes.items():
            if rt.get_conversation(session_key) is not None:
                rt.approve_exec(session_key, tool_name, args, approved)
                break

        # Update the card status in the feed
        if self._fh is not None:
            card = self._fh.get_card(approval_id)
            if card is not None:
                card.metadata["status"] = "approved" if approved else "denied"
                self._fh.update_card(approval_id, card)

    # ── AgentRuntime lifecycle ────────────────────────────────────────────────

    def _get_runtime(self, name: str) -> Any:
        """
        Get or create the AgentRuntime for a named agent.

        Each named agent gets its own AgentRuntime instance to keep
        conversations isolated.
        """
        if name in self._runtimes:
            return self._runtimes[name]

        from agent.config import load_agent_config
        from agent.runtime import AgentRuntime

        config = load_agent_config()
        provider = config.providers.get(config.default_provider)
        if not provider:
            raise RuntimeError(f"No provider configured for {config.default_provider}")
        if not provider.api_key:
            raise RuntimeError(f"No API key configured for provider {config.default_provider}")

        rt = AgentRuntime(
            config=config,
            GLib=self._GLib,
            on_text_delta=self._on_text_delta,
            on_tool_call_start=self._on_tool_call_start,
            on_tool_call_result=self._on_tool_call_result,
            on_tool_call_approval_needed=self._on_tool_call_approval_needed,
            on_response_complete=self._on_response_complete,
            on_token_usage=self._on_token_usage,
            on_error=self._on_error,
        )
        rt.start()
        self._runtimes[name] = rt
        logger.info("Created AgentRuntime for special agent: %s", name)
        return rt

    # ── Public: send a message to a special agent ────────────────────────────

    def send_to_special_agent(self, session_key: str, text: str) -> None:
        """
        Send a user message to a special agent for processing.

        Called by ChatHandler.on_send() when the target tab is a special agent.

        Requires an active project — special agents are project-scoped.
        """
        agent_def = self._agents.get(session_key)
        if agent_def is None:
            logger.warning(
                "send_to_special_agent: %s is not a registered special agent",
                session_key,
            )
            return

        # Special agents require an active project
        if self._active_project is None:
            self._dispatch(self._do_error, session_key,
                           "Open a project first. Special agents work within projects.")
            return

        project_name, project_path = self._active_project
        rt = self._get_runtime(agent_def.display_name)

        # Create conversation if it doesn't exist yet, with project context and filtered tools
        if rt.get_conversation(session_key) is None:
            rt.create_conversation(
                agent_name=agent_def.display_name,
                session_key=session_key,
                project_path=project_path,
                allowed_tools=agent_def.tools,  # Phase A: filtered tool set per agent
            )

        rt.send_message(session_key, text)

    def stop_all(self) -> None:
        """Stop all agent runtimes. Called on window shutdown."""
        for name, rt in list(self._runtimes.items()):
            rt.stop()
        self._runtimes.clear()

    # ── AgentRuntime callbacks (dispatched to render pipeline) ───────────────

    def _on_text_delta(self, session_key: str, text: str) -> None:
        """
        AgentRuntime text delta callback.
        → Start or update a streaming bubble in the UI.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_text_delta, session_key, text)
        else:
            self._do_text_delta(session_key, text)

    def _do_text_delta(self, session_key: str, text: str) -> None:
        """Main-thread portion of _on_text_delta."""
        if self._crh is None:
            return
        if not self._crh.is_streaming(session_key):
            chat_box = self._mc.get_chat_box_for_session(session_key)
            if chat_box is not None:
                self._crh.start_streaming(session_key, chat_box, "Agent")
        self._crh.update_streaming(session_key, text)

    def _on_tool_call_start(
        self, session_key: str, name: str, args: dict[str, Any]
    ) -> None:
        """
        AgentRuntime tool call start callback.

        Phase D: Create an agent_action feed card so the PM sees tool activity.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_tool_call_start, session_key, name, args)
        else:
            self._do_tool_call_start(session_key, name, args)

    def _do_tool_call_start(self, session_key: str, name: str, args: dict) -> None:
        """Main-thread portion of _on_tool_call_start.

        Phase D: Create an agent_action feed card with running state.
        """
        if self._fh is None or self._active_project is None:
            logger.debug("_do_tool_call_start: no feed handler or no active project")
            return

        agent_def = self._agents.get(session_key)
        agent_name = agent_def.display_name if agent_def else "Agent"
        project_name, _ = self._active_project

        # Build human-readable title from tool name and args
        if name == "read_file":
            title = f"{agent_name} is reading {args.get('path', '?')}"
        elif name == "write_file":
            title = f"{agent_name} is writing {args.get('path', '?')}"
        elif name == "exec_command":
            cmd = args.get("command", "?")
            title = f"{agent_name} is running: {cmd[:60]}"
        elif name == "list_files":
            title = f"{agent_name} is listing {args.get('path', '.')}"
        elif name == "search_files":
            title = f"{agent_name} is searching for \"{args.get('pattern', '?')}\""
        elif name == "web_search":
            title = f"{agent_name} is searching the web"
        elif name == "web_fetch":
            title = f"{agent_name} is fetching {args.get('url', '?')[:50]}"
        else:
            title = f"{agent_name} is calling {name}"

        from models.feed_card import FeedCardData
        card = FeedCardData(
            card_type="agent_action",
            source="agent",
            title=title,
            body="⏳ Running...",  # replaced when result arrives
            author=agent_name,
            timestamp=datetime.now(timezone.utc),
            project_name=project_name,
            metadata={
                "tool_name": name,
                "tool_args": args,
                "session_key": session_key,
                "status": "running",
            },
        )
        card_id = self._fh.add_card(card)
        # Store so _do_tool_call_result can update the card
        self._tool_card_ids[session_key] = card_id

    def _on_tool_call_result(
        self, session_key: str, name: str, result: Any
    ) -> None:
        """
        AgentRuntime tool call result callback.

        Phase D: Update the agent_action feed card with the result.
        Phase 1.5 review staging: If write_file succeeds and review mode is active,
        stage the file to the shadow staging directory.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_tool_call_result, session_key, name, result)
        else:
            self._do_tool_call_result(session_key, name, result)

    def _do_tool_call_result(self, session_key: str, name: str, result: Any) -> None:
        """Main-thread portion of _on_tool_call_result.

        Phase D: Update the feed card with the tool result, then flag for review.
        Phase 1.5 review staging: If write_file succeeds and review mode is active,
        copy the written file to a shadow staging directory inside the project.
        """
        # Phase D: Update the feed card with the result
        card_id = self._tool_card_ids.pop(session_key, None)
        if card_id is not None and self._fh is not None:
            card = self._fh.get_card(card_id)
            if card is not None:
                # Extract output from result (ToolResult or string)
                if hasattr(result, 'output'):
                    output_text = result.output or ""
                    error_text = result.error or ""
                    success = result.success
                    duration = getattr(result, 'duration_ms', 0)
                else:
                    output_text = str(result) if result else ""
                    error_text = ""
                    success = True
                    duration = 0

                # Truncate display
                display = output_text[:2000] if output_text else ""
                if error_text:
                    display = f"❌ {error_text}\n{display}"

                card.body = display
                card.metadata["status"] = "complete" if success else "error"
                card.metadata["duration_ms"] = duration

                # Flag for review if write_file/exec_command in active review session
                if name in ("write_file", "exec_command") and self._review_handler is not None:
                    proj_name, proj_path = self._active_project or (None, None)
                    if proj_path:
                        state = self._review_handler.get_state(proj_name)
                        if state and state.is_active():
                            card.metadata["needs_review"] = True

                # Persist the updated card data and re-render the widget
                self._fh.update_card(card_id, card)

        # Phase 1.5 review staging — if write_file succeeds and review is active,
        # copy the written file to a shadow staging directory so the PM can Accept/Reject
        if name != "write_file" or not isinstance(result, str) or not result.startswith("OK"):
            return

        proj_name, proj_path = self._active_project or (None, None)
        if proj_path is None or self._review_handler is None:
            return

        state = self._review_handler.get_state(proj_name)
        if state is None or not state.is_active():
            return

        # Extract relative path from output like "OK — wrote 123 bytes to src/foo.py"
        path_match = re.search(r"to (.+)$", result)
        if not path_match:
            return
        rel_path = path_match.group(1).strip()

        from agent.config import load_agent_config
        cfg = load_agent_config()
        staging_dir = os.path.join(proj_path, cfg.review_staging_dirname)
        os.makedirs(staging_dir, exist_ok=True)
        real_path = os.path.join(proj_path, rel_path)
        staging_path = os.path.join(staging_dir, rel_path)
        os.makedirs(os.path.dirname(staging_path), exist_ok=True)
        shutil.copy2(real_path, staging_path)
        logger.info("Review staging: copied %s → %s", real_path, staging_path)

    def _on_tool_call_approval_needed(
        self,
        session_key: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        """
        AgentRuntime approval-needed callback.

        Phase E: Create a pending-approval feed card so the PM can Approve/Deny.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_approval_needed, session_key, tool_name, args)
        else:
            self._do_approval_needed(session_key, tool_name, args)

    def _do_approval_needed(self, session_key: str, tool_name: str, args: dict) -> None:
        """Main-thread portion of _on_tool_call_approval_needed.

        Phase E: Create a pending-approval feed card. Store the approval info
        so approve_exec() can resolve it when the PM clicks Approve/Deny.
        """
        if self._active_project is None:
            # No active project — special agents require a project
            logger.info("Approval requested but no active project for %s", session_key)
            return

        if self._fh is None:
            logger.warning("_do_approval_needed: no feed handler available")
            return

        agent_def = self._agents.get(session_key)
        agent_name = agent_def.display_name if agent_def else "Agent"
        project_name, _ = self._active_project
        command = args.get("command", "unknown")

        card = FeedCardData(
            card_type="agent_action",
            source="agent",
            title=f"⚠️ {agent_name} requests approval to run command",
            body=f"$ {command}",
            author=agent_name,
            timestamp=datetime.now(timezone.utc),
            project_name=project_name,
            metadata={
                "tool_name": tool_name,
                "tool_args": args,
                "session_key": session_key,
                "status": "pending_approval",
                "needs_approval": True,
            },
        )
        card_id = self._fh.add_card(card)

        # Store approval info so approve_exec() can resolve it
        self._pending_approvals[card_id] = {
            "session_key": session_key,
            "tool_name": tool_name,
            "args": args,
        }

    def _on_response_complete(self, session_key: str, text: str) -> None:
        """
        AgentRuntime response complete callback.
        → End streaming and render the final text bubble.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_response_complete, session_key, text)
        else:
            self._do_response_complete(session_key, text)

    def _do_response_complete(self, session_key: str, text: str) -> None:
        """Main-thread portion of _on_response_complete.

        Phase B: Prevent duplicate bubbles.
        Phase C: Extract crabcard blocks from streaming text and route to the feed.

        When streaming was active: extract crabcards from sb.plain_text BEFORE
        end_streaming(), then overwrite sb.plain_text with cleaned text so
        _finalize() renders the bubble without crabcard blocks.

        When streaming was not active: extract from the text arg (non-streaming path).
        """
        if self._crh is None:
            return

        was_streaming = self._crh.is_streaming(session_key)
        project_name = self._active_project[0] if self._active_project else None

        # Phase C: Extract crabcards from streaming text before end_streaming
        if was_streaming and project_name and self._fh is not None:
            from utils.crabcard_parser import extract_crabcards
            full_text = self._crh.get_streaming_text(session_key) or ""
            if full_text:
                cleaned, cards = extract_crabcards(full_text, project_name, "Special Agent")
                if cards:
                    for card_data in cards:
                        card_data.project_name = project_name
                        self._fh.add_card(card_data)
                    # Overwrite streaming text with cleaned version so
                    # end_streaming._finalize renders the bubble without crabcard blocks
                    self._crh.set_streaming_text(session_key, cleaned)

        # Phase B: end_streaming() finalizes the bubble (uses current sb.plain_text)
        self._crh.end_streaming(session_key)

        # Non-streaming fallback: render from text argument with crabcard extraction
        if not was_streaming and text:
            if project_name and self._fh is not None:
                from utils.crabcard_parser import extract_crabcards
                cleaned, cards = extract_crabcards(text, project_name, "Special Agent")
                if cards:
                    for card_data in cards:
                        card_data.project_name = project_name
                        self._fh.add_card(card_data)
                text_for_bubble = cleaned if cards else text
            else:
                text_for_bubble = text

            chat_box = self._mc.get_chat_box_for_session(session_key)
            if chat_box is not None:
                bubble = self._crh.render_sync(
                    "Agent", text_for_bubble, session_key, agent_name="Agent"
                )
                if bubble is not None:
                    chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

    def _on_token_usage(self, session_key: str, total_tokens: int, cost: float) -> None:
        """AgentRuntime token usage callback. Logged for now."""
        logger.info(
            "Special agent token usage for %s: %d tokens, $%.4f",
            session_key,
            total_tokens,
            cost,
        )

    def _on_error(self, session_key: str, message: str) -> None:
        """AgentRuntime error callback. Show error bubble."""
        if self._GLib is not None:
            self._GLib.idle_add(self._do_error, session_key, message)
        else:
            self._do_error(session_key, message)

    def _do_error(self, session_key: str, message: str) -> None:
        """Main-thread portion of _on_error."""
        if self._crh is not None:
            self._crh.end_streaming(session_key)
            chat_box = self._mc.get_chat_box_for_session(session_key)
            if chat_box is not None:
                bubble = self._crh.render_sync(
                    "Agent", f"[Error] {message}", session_key, agent_name="Agent"
                )
                if bubble is not None:
                    chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()
