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

        # Shared routing table — set via set_agent_routing() (maps session_key → project_name)
        # Used to route special agent responses to project chat boxes when no direct tab exists.
        self._agent_to_project = None

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
        # Accumulated streaming text: session_key → cumulative text
        # AgentRuntime sends incremental deltas; ChatRenderHandler expects cumulative.
        self._streaming_text: dict[str, str] = {}
        # Pending approval cards: approval_id (card_id) → {session_key, tool_name, args}
        # Used by Phase E to resolve approvals when PM clicks Approve/Deny.
        self._pending_approvals: dict[str, dict] = {}

        self._on_agent_start_cb: Callable[[str], None] | None = None
        self._on_agent_end_cb: Callable[[str], None] | None = None
        self._on_agent_response: Callable[[str, str, str | None], None] | None = None  # Phase 6.2
        # SPEC-activity-drawer Phase 1: command_output callback.
        # cb(session_key, command, output, exit_code, duration_ms) — drawer uses
        # command for the row label, output for click-to-expand revealer, and
        # exit_code + duration_ms for the exit badge and duration display
        # (per SPEC-activity-drawer §2.5).
        self._on_command_output: Callable[[str, str, str, int, int], None] | None = None
        # V2 exec auto-accept callback (Phase 6): returns current exec mode
        # ("off" | "show" | "silent") or None. Set by window.py wiring via
        # set_check_exec_auto_accept_callback(). When the callback returns
        # "silent", _do_approval_needed bypasses card creation and approves
        # directly via runtime.approve_exec(). See SPEC-AUTO-ACCEPT-GRANULAR-1
        # §2.5 (Silent bypass, BUG #11 fix) and GRANULAR-PHASE-6-INSTRUCTIONS.md
        # Sub-change A.
        self._on_check_exec_auto_accept: Callable[[], str | None] | None = None
        # Per-session pending exec_command text — captured in _do_tool_call_start,
        # consumed in _do_tool_call_result. Keyed by session_key (one in-flight
        # exec per session is the realistic case).
        self._pending_exec_commands: dict[str, str] = {}

        # Per-session token usage cache: session_key → (total_tokens, total_cost)
        # Populated by _on_token_usage, read by get_session_usage().
        self._session_usage: dict[str, tuple[int, float]] = {}

        # Ensure KB provider is registered, then start KB HTTP server if KB index is available
        try:
            from utils.providers_store import ensure_kb_provider
            ensure_kb_provider()
            logger.info("KB provider registration ensured")
        except Exception as e:
            logger.warning("Failed to ensure KB provider: %s", e)

        try:
            from agent.kb_server import start_kb_server, is_kb_server_running
            from agent.kb_lookup import is_index_available as _kb_index_available
            if _kb_index_available() and not is_kb_server_running():
                start_kb_server()
                logger.info("KB HTTP server started from AgentRuntimeHandler")
        except Exception as e:
            logger.warning("Failed to start KB server: %s", e)

    def set_on_agent_start(self, cb: Callable[[str], None]) -> None:
        """Set callback fired when a local agent starts processing. Signature: cb(session_key)."""
        self._on_agent_start_cb = cb

    def set_on_agent_end(self, cb: Callable[[str], None]) -> None:
        """Set callback fired when a local agent finishes processing. Signature: cb(session_key)."""
        self._on_agent_end_cb = cb

    def set_on_agent_response(self, cb: Callable[[str, str, str | None], None]) -> None:
        """Set callback for agent response command parsing hook (Phase 6.2).

        Called after an agent's final response is rendered, with the agent's
        session key, full response text, and active project name.
        """
        self._on_agent_response = cb

    def set_on_command_output(self, cb: Callable[[str, str, str, int, int], None]) -> None:
        """Set callback for command_output drawer events (SPEC-activity-drawer §2.5).

        cb(session_key, command, output, exit_code, duration_ms) — fired when
        an exec_command completes.
        - `command` is the shell command string captured at start time.
        - `output` is the last 10 lines of stdout/stderr from the ToolResult.
        - `exit_code` is the int exit code from the ToolResult (0 if not set).
        - `duration_ms` is the int tool execution time in ms.

        Wired in connection_sync_handler.sync() to the drawer's append_event
        with a dict constructed from these five arguments.
        """
        self._on_command_output = cb

    def set_check_exec_auto_accept_callback(
        self, callback: Callable[[], str | None] | None
    ) -> None:
        """Install callback that returns the current exec auto-accept mode,
        or None if exec auto-accept is off. (Phase 6 / v2)

        Per SPEC-AUTO-ACCEPT-GRANULAR-1 §2.5 + GRANULAR-PHASE-6-INSTRUCTIONS
        Sub-change A: AgentRuntimeHandler does NOT import FeedHandler
        (§8.6 R2 no handler-to-handler imports). Instead, window.py wires
        FeedHandler.get_exec_auto_accept_mode as the callback. When the
        callback returns "silent", _do_approval_needed bypasses card
        creation and approves directly via runtime.approve_exec().

        The callback signature is `() -> str | None`:
          - returns "off" | "show" | "silent" to indicate exec mode
          - returns None if FeedHandler's _prefs is not yet initialized
            (gracefully degrades to no-bypass — card is created normally)

        Trigger: invoked at the top of _do_approval_needed() on every
        approval request. The callback must be cheap (called once per
        approval); FeedHandler.get_exec_auto_accept_mode is a single
        attribute read on _prefs.exec_command.mode.
        """
        self._on_check_exec_auto_accept = callback

    def set_review_handler(self, review_handler) -> None:
        """Set ReviewHandler after construction (deferred to avoid circular deps with window._build)."""
        self._review_handler = review_handler

    def set_feed_handler(self, feed_handler) -> None:
        """Set FeedHandler. Called by window.py during _build (Phase D)."""
        self._fh = feed_handler

    def set_agent_routing(self, routing_table) -> None:
        """Set AgentRoutingTable. Called by window.py during _build.
        Used to route special agent responses to project chat boxes."""
        self._agent_to_project = routing_table

    def set_active_project(self, project_name: str, project_path: str) -> None:
        """
        Set the active project for all special agents.

        Called by window.py when a project tab opens:
          self._project_handler.set_on_project_opened(
              lambda n, p: self._agent_runtime_handler.set_active_project(n, p)
          )

        This injects project_path into all existing (hot) conversations and
        ensures new conversations get the correct project context.

        Cold agents (those that have never been instantiated in this session)
        are NOT updated here — their conversations are loaded from disk on
        first send, and the lazy reconciliation in
        `AgentRuntime._rebuild_conversation_context` fires at that point.
        See option-C+ design in
        `.crabcakes/feed.json` / the production debugger incident: the
        original bug was a cold agent seeing a stale project_path; the fix
        is to rebuild on first send, against the currently-active project.

        HIGH-5 (Phase 6): If the project has a `.crabcakes/` directory with
        rule/bug files AND is not yet trusted, show a confirmation dialog
        before injecting its content. The dialog is shown asynchronously via
        GLib.idle_add (we're called from a tab-open callback that may not be
        on the GTK main thread).
        """
        self._active_project = (project_name, project_path)

        # HIGH-5: Schedule a trust check + dialog on the main thread, BEFORE
        # we rebuild system prompts. The dialog blocks visually but doesn't
        # block the call site; subsequent prompts will pull fresh state.
        if self._GLib is not None:
            self._GLib.idle_add(self._maybe_prompt_project_trust, project_name, project_path)
        else:
            # No GLib (tests): skip the dialog and rely on the trust store.
            # If the project isn't trusted, compose_system_prompt will skip
            # the .crabcakes/ files anyway (fail-secure default).
            pass

        # Update project_path on all existing conversations.
        # For hot agents (already in memory) this updates the in-memory
        # Conversation directly. For cold agents (loaded from disk only when
        # the user sends a message) we leave the on-disk project_path in
        # place — the lazy reconciliation in _rebuild_conversation_context
        # fires the next time the agent is loaded for a send. The lazy
        # path always wins because it knows the current active project.
        for sk, agent_def in self._agents.items():
            rt = self._runtimes.get(agent_def.display_name)
            if rt is None:
                continue
            conv = rt.get_conversation(sk)
            if conv is None:
                continue  # Cold agent — lazy path handles it on next send.
            if conv.project_path != project_path:
                rt._rebuild_conversation_context(
                    sk,
                    project_path,
                    agent_role=agent_def.role,
                )
        logger.info("AgentRuntimeHandler: active project set to %s (%s)", project_name, project_path)

    def _maybe_prompt_project_trust(self, project_name: str, project_path: str) -> None:
        """HIGH-5: Show a confirmation dialog if the project has .crabcakes/
        content that hasn't been trusted yet. Runs on the GTK main thread
        (scheduled via GLib.idle_add)."""
        from utils.project_trust import (
            has_crabcakes_content,
            is_project_trusted,
            trust_project,
        )
        if not has_crabcakes_content(project_path):
            return  # nothing to gate
        if is_project_trusted(project_path):
            return  # already trusted

        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):
            logger.warning("HIGH-5: Gtk not available; skipping trust dialog")
            return

        dialog = Gtk.MessageDialog(
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Trust project “{project_name}”?",
        )
        dialog.set_property(
            "secondary-text",
            "This project contains a .crabcakes/ directory with rules and "
            "bug-journal entries. These will be injected into every agent's "
            "system prompt for this project. Only approve if you trust the "
            "project's contents — untrusted project content can attempt to "
            "manipulate agent behavior.",
        )

        def on_response(_dialog, response_id):
            try:
                if response_id == Gtk.ResponseType.YES:
                    trust_project(project_path, reason="user-approved-via-dialog")
                    logger.info("HIGH-5: user trusted project %s via dialog", project_path)
                else:
                    logger.info("HIGH-5: user declined trust for project %s", project_path)
            finally:
                _dialog.close()

        dialog.connect("response", on_response)
        dialog.show()

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

    def clear_conversation(self, session_key: str) -> bool:
        """Reset a special agent's conversation in place.

        Resets messages=[], step_count=0, total_tokens=0, total_cost=0.0,
        and invalidates the token-estimate cache. Also deletes the persisted
        conversation JSON so the next session start loads a fresh state.

        In-place reset (vs remove + recreate) avoids races with in-flight
        tool loops: a background thread may be reading conv.messages via
        the runtime's _run_loop; resetting the list is safer than
        deleting the conversation object and recreating it, because the
        object identity stays stable for the running thread.

        Returns True on success, False if the session isn't a registered
        special agent or has no runtime/conversation.

        Spec: docs/specs/STEP-COUNT-RESET-FIX.md Edit 4.
        """
        # Guard: only special-agent sessions can be cleared this way.
        # `special:coder`, `special:debugger`, `special:crabcakes`, etc.
        if not isinstance(session_key, str) or not session_key.startswith("special:"):
            logger.warning(
                "clear_conversation: refusing non-special session_key=%r",
                session_key,
            )
            return False

        agent_def = self._agents.get(session_key)
        if agent_def is None:
            logger.warning(
                "clear_conversation: no registered special agent for %s",
                session_key,
            )
            return False

        # Resolve the runtime that owns this session. Display name is the
        # key in self._runtimes; _get_runtime will lazily create one if
        # the agent has never been used yet (clear-before-first-use is a
        # legitimate no-op case).
        try:
            rt = self._get_runtime(agent_def.display_name, agent_def=agent_def)
        except Exception as exc:
            logger.error(
                "clear_conversation: failed to acquire runtime for %s: %s",
                session_key, exc,
            )
            return False

        # In-place reset. Keep the Conversation object identity so any
        # in-flight _run_loop thread continues to see the same object.
        conv = rt.get_conversation(session_key)
        if conv is not None:
            try:
                conv.messages = []
                conv.step_count = 0
                conv.total_tokens = 0
                conv.total_cost = 0.0
                # _token_estimate_cache is keyed on (len(messages), hash(system_prompt))
                # — messages are now empty, so the cache MUST be invalidated
                # or the next trim pass will read a stale value.
                conv._token_estimate_cache = None
            except Exception as exc:
                logger.error(
                    "clear_conversation: in-place reset failed for %s: %s",
                    session_key, exc,
                )
                return False
            logger.info(
                "clear_conversation: reset in-memory conversation for %s",
                session_key,
            )

        # Delete the persisted JSON so a restart doesn't restore the old
        # state. Best-effort: a missing file is fine (nothing to delete),
        # other OSErrors are logged but don't fail the whole operation —
        # the in-memory state is already cleared.
        try:
            from utils.config import get_config_dir
            import os
            conv_dir = os.path.join(get_config_dir(), "conversations")
            conv_path = os.path.join(conv_dir, f"{session_key}.json")
            os.remove(conv_path)
            logger.info(
                "clear_conversation: deleted persisted conversation %s",
                conv_path,
            )
        except FileNotFoundError:
            pass  # No persisted file — that's fine.
        except OSError as exc:
            logger.warning(
                "clear_conversation: could not delete persisted file for %s: %s",
                session_key, exc,
            )

        return True

    def get_special_agent_def(self, session_key: str) -> Any | None:
        """Return the SpecialAgentDef for a session key, or None."""
        return self._agents.get(session_key)

    def get_agent_name_for_session(self, session_key: str) -> str:
        """Return the display name of the local special agent that owns this session, or ''.

        Used by the local exec adapter (in connection_sync_handler.py) to populate
        ActivityBubble.agent_name so the activity drawer shows the right agent name
        in the [Agent] column. Mirrors the fallback chain in
        ActivityHandler._resolve_agent_name, but resolves locally via session_key
        since local exec bubbles don't have a gateway payload to read data.agentName
        from.

        Args:
            session_key: The agent's session key.

        Returns:
            The agent's display name (e.g. "Coder"), or "" if not found.
        """
        agent_def = self._agents.get(session_key)
        if agent_def is None:
            return ""
        return getattr(agent_def, "display_name", "") or ""

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
                card.accepted = approved  # NEW: propagate decision so badge renders (Phase 2)
                self._fh.update_card(approval_id, card)

    # ── AgentRuntime lifecycle ────────────────────────────────────────────────

    def _resolve_agent_model(self, agent_def: Any) -> str | None:
        """Resolve the model string for an agent definition.

        Uses agent-specific llm_name to look up the provider in providers.yaml,
        then resolves the model from the provider's default_model.

        Returns:
            Full model string like "minimax/MiniMax-M2.7", or None to use
            the runtime's default_model.
        """
        llm_name = getattr(agent_def, "llm_name", None)

        if not llm_name:
            return None

        try:
            from agent.config import load_agent_config
            config = load_agent_config()
            prov_cfg = config.providers.get(llm_name)
            if prov_cfg and prov_cfg.default_model:
                if "/" in prov_cfg.default_model:
                    return prov_cfg.default_model
                return f"{llm_name}/{prov_cfg.default_model}"
        except Exception:
            logger.warning("Cannot resolve provider default model for %s", llm_name)
        return llm_name  # fallback — runtime will try to resolve

    def _get_runtime(self, name: str, agent_def=None) -> Any:
        """
        Get or create the AgentRuntime for a named agent.

        Each named agent gets its own AgentRuntime instance to keep
        conversations isolated.

        Args:
            name: Display name of the agent.
            agent_def: Optional SpecialAgentDef. If provided, the agent's
                      llm_name overrides the global default_provider.
        """
        if name in self._runtimes:
            return self._runtimes[name]

        from agent.config import load_agent_config
        from agent.runtime import AgentRuntime

        config = load_agent_config()

        # If the agent definition specifies a provider, use it as the default
        if agent_def is not None and getattr(agent_def, 'llm_name', None):
            llm_name = agent_def.llm_name
            if llm_name in config.providers:
                config.default_provider = llm_name
                provider = config.providers[llm_name]
            else:
                provider = config.providers.get(config.default_provider)
        else:
            provider = config.providers.get(config.default_provider)

        if not provider:
            raise RuntimeError(f"No provider configured for {config.default_provider}")

        # local-kb uses a placeholder key — skip the API key check
        if provider.name != "local-kb" and not provider.api_key:
            raise RuntimeError(f"No API key configured for provider {provider.name}")

        rt = AgentRuntime(
            config=config,
            GLib=self._GLib,
            on_text_delta=self._on_text_delta,
            on_tool_call_start=self._on_tool_call_start,
            on_tool_call_result=self._on_tool_call_result,
            on_tool_call_approval_needed=self._on_tool_call_approval_needed,
            on_response_complete=self._on_response_complete,
            on_token_usage=self._on_token_usage,
            on_token_breakdown=self._on_token_breakdown,
            on_error=self._on_error,
            on_enforcement_status=self._on_enforcement_status,
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

        # Special agents require an active project — except the helper (KB-based)
        if self._active_project is None and getattr(agent_def, 'role', '') != 'helper':
            if self._GLib is not None:
                self._GLib.idle_add(self._do_error, session_key,
                                    "Open a project first. Special agents work within projects.")
            else:
                self._do_error(session_key,
                               "Open a project first. Special agents work within projects.")
            return

        if self._active_project is not None:
            project_name, project_path = self._active_project
        else:
            project_name, project_path = "(none)", None
        rt = self._get_runtime(agent_def.display_name, agent_def=agent_def)

        logger.debug("[handler] send_to_special_agent: sk=%s agent=%s project=%s text_len=%d",
                     session_key, agent_def.display_name, project_name, len(text))

        # Resolve per-agent model override (Step 4 — user-defined agents)
        agent_model = self._resolve_agent_model(agent_def)

        # Resolve per-agent SI enforcement flag
        si_enforcement = None
        if hasattr(agent_def, 'get_self_improvement_config'):
            si_cfg = agent_def.get_self_improvement_config()
            si_enforcement = si_cfg.get('enforcement')

        # Create conversation if it doesn't exist yet, with project context and filtered tools.
        # First try to load the persisted conversation from disk (preserves message history,
        # token/cost data, and other state across app restarts). Only create fresh if no
        # persisted conversation exists.
        if rt.get_conversation(session_key) is None:
            loaded = rt.load_conversation(session_key)
            if loaded:
                logger.info("send_to_special_agent: loaded persisted conversation for %s", session_key)
                # Re-apply the active project to the loaded conversation. The
                # persisted project_path and system_prompt may be stale (from a
                # previous project the user had open). This is a no-op when
                # the persisted values already match the active project.
                rt._rebuild_conversation_context(
                    session_key,
                    project_path,
                    agent_role=agent_def.role,
                )

        if rt.get_conversation(session_key) is None:
            rt.create_conversation(
                agent_name=agent_def.display_name,
                session_key=session_key,
                project_path=project_path,
                model=agent_model,               # Per-agent provider/model override
                allowed_tools=agent_def.tools,   # Phase A: filtered tool set per agent
                mcp_servers=agent_def.mcp_servers, # Phase B: MCP servers
                agent_role=agent_def.role,        # §7: explicit role from definition
                si_enforcement=si_enforcement,     # Per-agent enforcement gating
                api_key=agent_def.api_key,        # Per-agent API key override
                app_title=agent_def.app_title,  # OpenRouter X-Title header
                fallback_provider=agent_def.fallback_provider,
                # fallback_model removed in 2026-06-15 — runtime derives from provider card.
                # See SPEC-AGENT-FALLBACK-MODEL-DROPDOWN-REMOVAL.md.
            )
        else:
            # Bug fix: sync existing conversation with latest agent definition.
            # When agent is edited (e.g. api_key added), the in-memory Conversation
            # retains stale values. Update api_key/model/app_title so edits take effect
            # immediately without requiring an app restart.
            conv = rt.get_conversation(session_key)
            if conv is not None:
                if agent_def.api_key:
                    conv.api_key = agent_def.api_key
                if agent_model:
                    conv.model = agent_model
                if agent_def.app_title:
                    conv.app_title = agent_def.app_title
                # Sync fallback config (in case agent was edited)
                conv.fallback_provider = agent_def.fallback_provider
                # Sync role (in case agent's role was edited)
                if agent_def.role:
                    conv.agent_role = agent_def.role
                # Sync MCP servers (in case agent's mcp_server list was edited)
                if agent_def.mcp_servers is not None:
                    conv.mcp_servers = list(agent_def.mcp_servers)
                # Sync SI enforcement (in case agent's self_improvement was edited)
                if si_enforcement is not None:
                    conv.si_enforcement = si_enforcement
                # conv.fallback_model assignment removed in 2026-06-15 — runtime derives from provider card.

        # Reset step_count on each new user message so the agent gets a
        # fresh step_limit budget per task. step_count counts assistant turns
        # (conversation.py:190), and without this reset it accumulates across
        # all tasks until hitting step_limit=100 and killing the agent.
        conv = rt.get_conversation(session_key)
        if conv is not None:
            conv.step_count = 0

        rt.send_message(session_key, text)

    def stop_all(self) -> None:
        """Stop all agent runtimes and the KB server. Called on window shutdown."""
        # Stop the KB HTTP server
        try:
            from agent.kb_server import stop_kb_server, is_kb_server_running
            if is_kb_server_running():
                stop_kb_server()
                logger.info("KB HTTP server stopped")
        except Exception as e:
            logger.warning("Failed to stop KB server: %s", e)

        # BUG #31: Clean up MCP connections before stopping runtimes
        try:
            from utils.mcp_client import disconnect_all as mcp_disconnect_all
            mcp_disconnect_all()  # Clean up all MCP connections across all conversations
        except Exception:
            pass  # Best effort — daemon threads die on exit anyway

        for name, rt in list(self._runtimes.items()):
            rt.stop()
        self._runtimes.clear()


    def reload_agents_and_mcp(
        self,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """
        Reload agent registry and hot-reload MCP connections.

        Flow:
          1. reload_registry() — re-read YAML files from agents/
          2. Collect current agent prefixes BEFORE clearing self._agents
          3. Re-register all agents from the fresh registry
          4. disconnect_all() for all known prefixes — kill stale MCP subprocesses
          5. connect_servers() per agent — pre-warm MCP connections
          6. Call on_complete callback if provided

        Thread-safe: MCP operations are blocking; call from a background thread
        or via GLib.idle_add() if calling from a non-main thread that needs
        to update UI after completion.
        """
        from agent.special_agents import reload_registry, get_special_agents
        from utils.mcp_client import disconnect_all, connect_servers

        # 1. Reload registry from disk
        reload_registry()

        # 2. Collect current agent prefixes BEFORE clearing
        old_prefixes = list(self._agents.keys())

        # 3. Re-register all agents from fresh registry
        self._agents.clear()
        new_agents = get_special_agents()
        for agent_def in new_agents:
            self._agents[agent_def.conv_id_prefix] = agent_def

        # 4. Disconnect stale MCP connections for all known prefixes
        prefixes_to_disconnect = set(old_prefixes) | {a.conv_id_prefix for a in new_agents}
        for prefix in prefixes_to_disconnect:
            try:
                disconnect_all(conversation_key=prefix)
            except Exception as e:
                logger.warning(
                    "MCP disconnect failed for prefix %s: %s", prefix, e
                )

        # 5. Re-establish MCP connections for each agent
        for agent_def in new_agents:
            if agent_def.mcp_servers:
                try:
                    result = connect_servers(
                        server_names=agent_def.mcp_servers,
                        conversation_key=agent_def.conv_id_prefix,
                    )
                    for server_name, error in result.items():
                        if error:
                            logger.warning(
                                "MCP hot-reload: failed to connect %s for %s: %s",
                                server_name, agent_def.conv_id_prefix, error,
                            )
                except Exception as e:
                    logger.warning(
                        "MCP hot-reload: connection attempt failed for %s: %s",
                        agent_def.conv_id_prefix, e,
                    )

        logger.info("Agent registry and MCP connections reloaded")

        if on_complete:
            on_complete()

    # ── Chat box resolution ────────────────────────────────────────────────

    def _resolve_chat_box(self, session_key: str):
        """Resolve the chat box for a session key.

        If no direct tab exists (e.g. special agent messaged from project group chat),
        looks up the project via AgentRoutingTable and returns the project chat box.
        """
        chat_box = self._mc.get_chat_box_for_session(session_key)
        if chat_box is not None:
            return chat_box
        # No direct tab — check if this agent is routed to a project
        if self._agent_to_project is not None:
            project_name = self._agent_to_project.get_project(session_key)
            if project_name is not None:
                logger.debug("[handler] _resolve_chat_box: sk=%s → project:%s", session_key, project_name)
                return self._mc.get_chat_box_for_session(f"project:{project_name}")
        logger.debug("[handler] _resolve_chat_box: sk=%s → None (no tab, no routing)", session_key)
        return None

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
        """Main-thread portion of _on_text_delta.

        AgentRuntime sends incremental SSE chunks. ChatRenderHandler expects
        cumulative text (same contract as gateway). Accumulate here.
        """
        if self._crh is None:
            return
        # Accumulate incremental delta into cumulative text
        self._streaming_text[session_key] = self._streaming_text.get(session_key, "") + text
        if not self._crh.is_streaming(session_key):
            chat_box = self._resolve_chat_box(session_key)
            if chat_box is not None:
                self._crh.start_streaming(session_key, chat_box, "Agent")
                # Fire lifecycle: agent started → ActivityHandler progress bar
                if self._on_agent_start_cb:
                    self._on_agent_start_cb(session_key)
        self._crh.update_streaming(session_key, self._streaming_text[session_key])

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
            # SPEC-activity-drawer: capture the command for the command_output
            # drawer row that fires when the result comes back. Stored per-session
            # so _do_tool_call_result can resolve it.
            self._pending_exec_commands[session_key] = cmd
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
        logger.debug("[handler] _do_tool_call_result: sk=%s tool=%s result_len=%d",
                     session_key, name, len(str(result)) if result else 0)
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

        # SPEC-activity-drawer §2.5: fire command_output callback for exec_command.
        # Captures the command from start time, takes the last 10 lines of output
        # from the ToolResult, plus exit_code and duration_ms for the drawer's
        # exit badge and duration display. Output may be empty for silent commands.
        if name == "exec_command" and self._on_command_output is not None:
            cmd = self._pending_exec_commands.pop(session_key, "")
            output_text = ""
            if hasattr(result, "output") and result.output:
                output_text = result.output
            elif isinstance(result, str):
                output_text = result
            # Extract exit_code (ToolResult.exit_code is int | None; default to 0)
            exit_code = getattr(result, "exit_code", 0) or 0
            # Extract duration_ms (ToolResult.duration_ms is int; default to 0)
            duration_ms = getattr(result, "duration_ms", 0) or 0
            # Tail to last 10 lines (matches drawer's OUTPUT_LINE_CAP)
            lines = output_text.splitlines()
            tail = "\n".join(lines[-10:]) if lines else ""
            self._on_command_output(session_key, cmd, tail, exit_code, duration_ms)

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

        # V2 Silent bypass: if exec auto-accept is in silent mode, approve
        # directly without creating a feed card. The card is NOT stored
        # in _cards or _pending_approvals (no double-action possible).
        # Per SPEC-AUTO-ACCEPT-GRANULAR-1.md §2.5 BUG #11 fix: Silent mode
        # bypasses card creation entirely (no Approve/Deny buttons visible
        # on an already-executed command). Show mode still creates the
        # card for audit-trail purposes (Phase 7).
        if (self._on_check_exec_auto_accept is not None
                and self._on_check_exec_auto_accept() == "silent"):
            agent_def = self._agents.get(session_key)
            if agent_def is None:
                return
            runtime = self._runtimes.get(agent_def.runtime_id)
            if runtime is None:
                return
            # IMPORTANT: lambda captures session_key/tool_name/args by
            # closure. These are _do_approval_needed parameters (not loop
            # variables), so capture-by-closure is safe.
            # Note: spec A3 doesn't guard `self._GLib is not None`, but
            # every other call site in this class does (see _do_tool_call_start,
            # _do_text_delta, _maybe_prompt_project_trust). We follow the
            # same defensive pattern: in test mode without GTK, _GLib is None
            # and we call approve_exec directly (no main-thread dispatch needed).
            if self._GLib is not None:
                self._GLib.idle_add(
                    lambda: runtime.approve_exec(session_key, tool_name, args, True)
                )
            else:
                runtime.approve_exec(session_key, tool_name, args, True)
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

        # Clear accumulated streaming text — no longer needed
        self._streaming_text.pop(session_key, None)

        was_streaming = self._crh.is_streaming(session_key)
        project_name = self._active_project[0] if self._active_project else None

        logger.debug("[handler] _do_response_complete: sk=%s was_streaming=%s text_len=%d",
                     session_key, was_streaming, len(text or ""))

        # Phase C: Extract crabcards from streaming text before end_streaming
        if was_streaming and project_name and self._fh is not None:
            from utils.crabcard_parser import extract_crabcards
            full_text = self._crh.get_streaming_text(session_key) or ""
            if full_text:
                cleaned, cards = extract_crabcards(full_text, project_name, "Special Agent")
                if cards:
                    # Batch all cards from one response into a single main-thread
                    # pass — avoids N idle callbacks racing the vadjustment.
                    for card_data in cards:
                        card_data.project_name = project_name
                    self._fh.add_cards_batch(cards)
                    # Overwrite streaming text with cleaned version so
                    # end_streaming._finalize renders the bubble without crabcard blocks
                    self._crh.set_streaming_text(session_key, cleaned)

        # Phase B: end_streaming() finalizes the bubble (uses current sb.plain_text)
        self._crh.end_streaming(session_key)

        # Non-streaming fallback: render from text argument with crabcard extraction
        # Defensive: if response completed with empty text and no streaming bubble,
        # render a fallback message so the user sees feedback instead of silence.
        if not was_streaming and not text:
            chat_box = self._resolve_chat_box(session_key)
            if chat_box is not None:
                fallback_text = "⚠️ Agent returned no content. This may indicate a configuration error or an issue with the LLM provider."
                bubble = self._crh.render_sync(
                    "System", fallback_text, session_key, agent_name="System"
                )
                if bubble is not None:
                    chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

        if not was_streaming and text:
            if project_name and self._fh is not None:
                from utils.crabcard_parser import extract_crabcards
                cleaned, cards = extract_crabcards(text, project_name, "Special Agent")
                if cards:
                    # Batch: single idle callback, single smart scroll
                    for card_data in cards:
                        card_data.project_name = project_name
                    self._fh.add_cards_batch(cards)
                text_for_bubble = cleaned if cards else text
            else:
                text_for_bubble = text

            chat_box = self._resolve_chat_box(session_key)
            if chat_box is not None:
                bubble = self._crh.render_sync(
                    "Agent", text_for_bubble, session_key, agent_name="Agent"
                )
                if bubble is not None:
                    chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

        # Agent command parsing hook (Phase 6.2) — fire after bubble render, before lifecycle
        if self._on_agent_response is not None and text:
            project_name = self._active_project[0] if self._active_project else None
            self._on_agent_response(session_key, text, project_name)

        # Fire lifecycle: agent finished → ActivityHandler progress bar
        if self._on_agent_end_cb:
            self._on_agent_end_cb(session_key)

    def _on_token_usage(self, session_key: str, total_tokens: int, cost: float) -> None:
        """AgentRuntime token usage callback. Store and log."""
        self._session_usage[session_key] = (total_tokens, cost)
        logger.info(
            "Special agent token usage for %s: %d tokens, $%.4f",
            session_key,
            total_tokens,
            cost,
        )

    def get_session_usage(self) -> dict[str, tuple[int, float]]:
        """Return the in-memory session usage cache.

        Keyed by session_key. Values are (total_tokens, total_cost).
        Used by /cost command as fallback for agents without conversation files.
        Returns a defensive copy.
        """
        return dict(self._session_usage)

    def _on_token_breakdown(self, session_key: str, breakdown: dict) -> None:
        """§4.15 — Per-turn token budget breakdown. Logged for observability."""
        logger.info(
            "[token-breakdown] sk=%s system_prompt=%d conv=%d total=%d/%d remaining=%d (%.1f%%)",
            session_key,
            breakdown["system_prompt_tokens"],
            breakdown["conversation_tokens"],
            breakdown["total_used_tokens"],
            breakdown["model_max_tokens"],
            breakdown["remaining_tokens"],
            breakdown["usage_percent"],
        )

    def _on_error(self, session_key: str, message: str) -> None:
        """AgentRuntime error callback. Show error bubble."""
        if self._GLib is not None:
            self._GLib.idle_add(self._do_error, session_key, message)
        else:
            self._do_error(session_key, message)

    def _on_enforcement_status(self, session_key: str, tool_name: str, status: dict) -> None:
        """§F — Enforcement status callback. Log enforcement results to observability log.

        The status dict format is defined by ENFORCEMENT_LAYER_SPEC.md §8.2:
            {
                "tier": "syntax" | "tests" | "lint",
                "file": "src/auth.py",
                "passed": True | False,
                "detail": "Syntax check passed for src/auth.py",
            }

        The UI layer decides how to render this (feed card text, icons, etc.).
        This callback just provides the data — rendering is handled separately.
        """
        icon = "✅" if status["passed"] else "❌"
        logger.info(
            "[enforcement:%s] sk=%s %s %s — %s",
            status["tier"],
            session_key,
            tool_name,
            icon,
            status["detail"],
        )

    def _do_error(self, session_key: str, message: str) -> None:
        """Main-thread portion of _on_error."""
        logger.debug("[handler] _do_error: sk=%s msg=%s", session_key, message)
        self._streaming_text.pop(session_key, None)
        if self._crh is not None:
            self._crh.end_streaming(session_key)
            chat_box = self._resolve_chat_box(session_key)
            if chat_box is not None:
                bubble = self._crh.render_sync(
                    "Agent", f"[Error] {message}", session_key, agent_name="Agent"
                )
                if bubble is not None:
                    chat_box.append(bubble)
                self._mc.scroll_chat_to_bottom()

        # Fire lifecycle: agent finished (error) → ActivityHandler returns to idle
        if self._on_agent_end_cb:
            self._on_agent_end_cb(session_key)
