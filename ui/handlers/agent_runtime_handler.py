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
        self._GLib = GLib_module
        self._review_handler = review_handler

        # session_key → agent_name  (registered special agents)
        self._special_agents: dict[str, str] = {}
        # session_key → project_path (for review layer routing)
        self._session_to_project_path: dict[str, str] = {}
        # name → AgentRuntime instance (one rt per agent for isolation)
        self._runtimes: dict[str, Any] = {}

    # ── Special agent registration ──────────────────────────────────────────

    def add_special_agent(self, name: str, session_key: str) -> None:
        """
        Register a named agent backed by AgentRuntime.

        The agent will appear in the agents list (left_panel) via the
        set_special_agents() mechanism in window.py.
        """
        self._special_agents[session_key] = name
        logger.info("Registered special agent: %s (%s)", name, session_key)

    def get_special_agents(self) -> dict[str, str]:
        """Return {session_key: name} for registered special agents."""
        return dict(self._special_agents)

    def set_project_for_session(self, session_key: str, project_path: str) -> None:
        """
        Associate a special agent session with a project path.


        Called by window.py when a project tab is opened with a special agent active.
        The project path is used by the review layer to determine staging directory.
        """
        self._session_to_project_path[session_key] = project_path

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
        """
        name = self._special_agents.get(session_key)
        if name is None:
            logger.warning(
                "send_to_special_agent: %s is not a registered special agent",
                session_key,
            )
            return

        rt = self._get_runtime(name)
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
        """AgentRuntime tool call start callback. Logged for now."""
        if self._GLib is not None:
            self._GLib.idle_add(
                lambda: logger.info(
                    "Special agent tool call: %s(%s)", name, args
                )
            )
        else:
            logger.info("Special agent tool call: %s(%s)", name, args)

    def _on_tool_call_result(
        self, session_key: str, name: str, result: Any
    ) -> None:
        """
        AgentRuntime tool call result callback.

        Phase 1.5: If write_file succeeds and review mode is active for
        the project, stage the file to the shadow staging directory so
        the agent sees the write immediately but the PM can still Accept/Reject.
        """
        if self._GLib is not None:
            self._GLib.idle_add(self._do_tool_call_result, session_key, name, result)
        else:
            self._do_tool_call_result(session_key, name, result)

    def _do_tool_call_result(self, session_key: str, name: str, result: Any) -> None:
        """Main-thread portion of _on_tool_call_result.

        Phase 1.5: If write_file succeeds and review mode is active for
        the project, copy the written file to a shadow staging directory
        inside the project. This lets the PM Accept/Reject changes via
        the existing ReviewHandler even though the agent saw the write succeed.
        """
        if name != "write_file":
            return
        if not isinstance(result, str):
            return
        # Parse output string: "OK — wrote N bytes to <path>" or error message
        if not result.startswith("OK"):
            return

        # Get the project path for this session (set via set_project_for_session)
        project_path = self._session_to_project_path.get(session_key)
        if project_path is None:
            return
        if self._review_handler is None:
            return

        state = self._review_handler.get_state(project_path)
        if state is None or not state.is_active():
            return

        # Extract relative path from output like "OK — wrote 123 bytes to src/foo.py"
        output = result  # result is now the output string directly
        path_match = re.search(r"to (.+)$", output)
        if not path_match:
            return
        rel_path = path_match.group(1).strip()

        # Stage the file to the shadow staging directory
        from agent.config import load_agent_config
        cfg = load_agent_config()
        staging_dir = os.path.join(project_path, cfg.review_staging_dirname)
        os.makedirs(staging_dir, exist_ok=True)
        real_path = os.path.join(project_path, rel_path)
        staging_path = os.path.join(staging_dir, rel_path)
        os.makedirs(os.path.dirname(staging_path), exist_ok=True)
        shutil.copy2(real_path, staging_path)
        logger.info(
            "Review staging: copied %s → %s", real_path, staging_path
        )

    def _on_tool_call_approval_needed(
        self,
        session_key: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        """AgentRuntime approval-needed callback. Currently logged only."""
        logger.info(
            "Special agent approval needed: %s(%s)", tool_name, args
        )

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
        """Main-thread portion of _on_response_complete."""
        if self._crh is not None:
            self._crh.end_streaming(session_key)
            chat_box = self._mc.get_chat_box_for_session(session_key)
            if chat_box is not None:
                bubble = self._crh.render_sync(
                    "Agent", text, session_key, agent_name="Agent"
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
