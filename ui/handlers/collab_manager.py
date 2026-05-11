# ui/handlers/collab_manager.py
# CollabManager — Agent-to-Agent consultation thread lifecycle.
#
# Architecture: Handler pattern (§8.6 ARCHITECTURE.md).
# No imports from ui/ submodules — receives dependencies via constructor/setters.
# Thread safety: state protected by _lock. GTK via GLib.idle_add().
#
# Thread lifecycle:
#   1. start_relay()              — create thread, send relay, post intent card
#   2. capture_response()          — append response, check convergence
#   3. _close_thread_internal()    — convergence detected, post closing card

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from models.feed_card import FeedCardData

# ── A2A Thread State ───────────────────────────────────────────────────────────

@dataclass
class A2AThread:
    thread_id: str
    project_name: str
    initiator_sk: str          # session key of agent that started the consultation
    target_sk: str              # session key of the consulted agent
    responses: list[dict] = field(default_factory=list)  # [{"text": ..., "from": ...}]
    turn: int = 0               # current turn count (starts at 1 after first relay response)
    active: bool = True         # False after convergence closes the thread
    initiator_name: str = ""    # display name for card/prefix
    target_name: str = ""       # display name for card/prefix


# ── CollabManager ───────────────────────────────────────────────────────────────

class CollabManager:
    """
    Manages ephemeral agent-to-agent consultation threads within a project.

    Thread lifecycle:
      1. start_relay()          — create thread, post intent card, send relay message
      2. capture_response()     — append response, check convergence, relay back if active
      3. close_thread()         — convergence or hard wall, post closing card, clean up

    Response routing:
      ChatHandler and AgentRuntimeHandler call is_pending_relay() to check whether
      an arriving response belongs to an active A2A thread. If so, they route it here
      via capture_response().
    """

    def __init__(
        self,
        *,
        GLib,                              # gi.repository.GLib
        feed_handler,                      # FeedHandler — for posting cards
        agent_runtime_handler=None,        # AgentRuntimeHandler — for special agent routing
        gw=None,                           # GatewayClient — for gateway agent routing
        agent_mgr=None,                    # AgentManager — for name resolution
    ):
        self._GLib = GLib
        self._feed_handler = feed_handler
        self._agent_runtime_handler = agent_runtime_handler
        self._gw = gw
        self._agent_mgr = agent_mgr

        self._threads: dict[str, A2AThread] = {}    # thread_id → A2AThread
        self._pending_relays: set[str] = set()       # session_keys with pending responses
        self._sk_to_thread: dict[str, str] = {}      # session_key → thread_id
        self._lock = threading.Lock()

    # ── Setters ─────────────────────────────────────────────────────────────

    def set_agent_runtime_handler(self, handler) -> None:
        self._agent_runtime_handler = handler

    def set_gateway_client(self, gw) -> None:
        self._gw = gw

    def set_agent_mgr(self, agent_mgr) -> None:
        self._agent_mgr = agent_mgr

    def set_feed_handler(self, feed_handler) -> None:
        self._feed_handler = feed_handler

    # ── Text Sanitization ──────────────────────────────────────────────────

    @staticmethod
    def _strip_thinking_tokens(text: str) -> str:
        """Remove <thinking>...</thinking> blocks from LLM response text.

        These blocks contain internal reasoning that should never be relayed
        to other agents or written to feed cards."""
        import re
        cleaned = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
        # Collapse multiple whitespace into single space, strip edges
        return re.sub(r'\s+', ' ', cleaned).strip()

    @staticmethod
    def _strip_thread_mentions(text: str, thread: 'A2AThread') -> str:
        """Remove @mentions of agents already participating in this thread.

        Prevents echo loops: when Coder's response mentions @Debugger (the
        other participant), that mention is stripped so it doesn't trigger
        a new relay. Mentions of agents NOT in the thread are preserved,
        allowing multi-agent chains.
        """
        import re
        # Collect names of both participants
        names = set()
        for name in (thread.initiator_name, thread.target_name):
            if name:
                names.add(name)
                # Also add the lowercase form for case-insensitive matching
                names.add(name.lower())

        if not names:
            return text

        # Build pattern matching any participant name after @
        pattern = r'@(' + '|'.join(re.escape(n) for n in names) + r')\b'
        return re.sub(pattern, r'\1', text)

    # ── Thread Identity ─────────────────────────────────────────────────────

    @staticmethod
    def _build_thread_id(project_name: str, initiator_sk: str, target_sk: str) -> str:
        """Deterministic thread ID — order: initiator first, target second."""
        return f"a2a:{project_name}:{initiator_sk}:{target_sk}"

    # ── Agent Name Resolution ───────────────────────────────────────────────

    def _resolve_agent_name(self, session_key: str) -> str:
        """Resolve session_key to display name for relay prefixes and feed cards."""
        # Special agents
        if self._agent_runtime_handler is not None:
            special = self._agent_runtime_handler.get_special_agents()
            if session_key in special:
                return special[session_key]
        # Gateway agents
        if self._agent_mgr is not None:
            name = self._agent_mgr.get_name(session_key)
            if name:
                return name
        return session_key.split(":")[-1]  # fallback

    # ── Thread Lifecycle ────────────────────────────────────────────────────

    def start_relay(
        self,
        project_name: str,
        initiator_sk: str,
        target_sk: str,
        question_text: str,
    ) -> str | None:
        """
        Start an A2A consultation thread.

        Returns thread_id on success, None if a thread already exists for this pair.

        Actions:
          1. Build thread_id, check for duplicate active thread
          2. Atomically: create A2AThread, register pending relay (single lock acquisition)
          3. Post intent card to project feed
          4. Send relay message to target agent via correct transport
        """
        thread_id = self._build_thread_id(project_name, initiator_sk, target_sk)

        # Atomically: check duplicate + create thread + register pending relay.
        # Lock held for entire operation — no TOCTOU gap between thread creation
        # and pending_relay registration.
        with self._lock:
            existing = self._threads.get(thread_id)
            if existing is not None and existing.active:
                return None  # duplicate thread

            initiator_name = self._resolve_agent_name(initiator_sk)
            target_name = self._resolve_agent_name(target_sk)

            thread = A2AThread(
                thread_id=thread_id,
                project_name=project_name,
                initiator_sk=initiator_sk,
                target_sk=target_sk,
                initiator_name=initiator_name,
                target_name=target_name,
            )
            self._threads[thread_id] = thread
            self._pending_relays.add(target_sk)
            self._sk_to_thread[target_sk] = thread_id

        # Post intent card (outside lock — GTK)
        clean_question = self._strip_thinking_tokens(question_text)
        self._post_intent_card(thread, clean_question)

        # Send relay message (stripped of thinking tokens)
        relay_text = self._build_relay_message(initiator_sk, clean_question, project_name)
        self._send_relay(target_sk, relay_text)

        return thread_id

    def capture_response(self, session_key: str, text: str) -> None:
        """
        Called when a response arrives for a session key in _pending_relays.

        Actions:
          1. Look up thread via _sk_to_thread
          2. Append response to thread.responses, increment turn
          3. Sanitize relay text: strip thinking tokens + in-thread mentions
          4. If turn >= 15 or convergence: close thread
          5. If not converged: relay sanitized response back to initiator
        """
        from converge.converge import should_stop

        thread_id: str | None = None
        with self._lock:
            thread_id = self._sk_to_thread.get(session_key)

        if thread_id is None:
            return

        with self._lock:
            thread = self._threads.get(thread_id)
            if thread is None or not thread.active:
                return

            # Sanitize: strip thinking tokens, then strip mentions of thread participants
            clean_text = self._strip_thinking_tokens(text)
            clean_text = self._strip_thread_mentions(clean_text, thread)

            thread.responses.append({"text": clean_text, "from": session_key})
            thread.turn += 1

            if thread.turn >= 15 or should_stop(thread.responses, thread.turn):
                self._close_thread_internal(thread_id)
                return

            # Not converged — relay sanitized response back to initiator for next turn
            initiator = thread.initiator_sk
            relay_text = self._build_relay_message(session_key, clean_text, thread.project_name)

            # Add initiator to pending relays
            self._pending_relays.add(initiator)
            self._sk_to_thread[initiator] = thread_id

        self._send_relay(initiator, relay_text)

    def close_thread(self, thread_id: str) -> None:
        """Public entry point — thread-safe wrapper around _close_thread_internal."""
        with self._lock:
            self._close_thread_internal(thread_id)

    # ── Internal ────────────────────────────────────────────────────────────

    def _close_thread_internal(self, thread_id: str) -> None:
        """Close a thread: set inactive, clean up registries, post closing card."""
        thread = self._threads.get(thread_id)
        if thread is None:
            return

        if not thread.active:
            return  # already closed

        thread.active = False

        # Remove session keys from tracking
        for sk in (thread.target_sk, thread.initiator_sk):
            self._pending_relays.discard(sk)
            self._sk_to_thread.pop(sk, None)

        # Post closing card (called with lock held; GLib.idle_add is non-blocking)
        self._post_closing_card(thread)

    def clear_project(self, project_name: str) -> None:
        """
        Close all A2A threads for a project.

        Called from ProjectHandler.on_project_closed() so no stale threads
        remain when a project is deactivated.
        """
        with self._lock:
            to_close = [
                tid for tid, t in self._threads.items()
                if t.project_name == project_name and t.active
            ]
        for tid in to_close:
            self._close_thread_internal(tid)

    # ── Transport ───────────────────────────────────────────────────────────

    def _send_relay(self, target_sk: str, text: str) -> None:
        """
        Route relay message through the correct transport layer.

        Special agent  → AgentRuntimeHandler.send_to_special_agent()
        Gateway agent  → GatewayClient.send_message() (if connected)
        """
        is_special = (
            self._agent_runtime_handler is not None
            and target_sk in self._agent_runtime_handler.get_special_agents()
        )
        if is_special:
            self._agent_runtime_handler.send_to_special_agent(target_sk, text)
        else:
            if self._gw is not None and self._gw.is_connected():
                self._gw.send_message(target_sk, text)
            # Offline gateway agent → silently skip (per spec §12.2)

    def _build_relay_message(self, from_sk: str, text: str, project_name: str) -> str:
        """Build relay message with [A2A relay from ...] prefix."""
        from_name = self._resolve_agent_name(from_sk)
        return f"[A2A relay from {from_name} in {project_name}] {text}"

    # ── Feed Cards ──────────────────────────────────────────────────────────

    def _post_intent_card(self, thread: A2AThread, question_text: str) -> None:
        """Post an intent card to the project feed showing consultation start.

        question_text is pre-sanitized by the caller (start_relay)."""
        if self._feed_handler is None:
            return

        topic = question_text[:80].strip()
        card = FeedCardData(
            card_type="agent_action",
            source="system",
            title=f"Consulting @{thread.target_name} on {topic}",
            body=f"Initiated by @{thread.initiator_name}",
            author="System",
            timestamp=datetime.now(timezone.utc),
            project_name=thread.project_name,
            metadata={"action": "consultation_start", "thread_id": thread.thread_id},
        )
        if self._GLib is not None:
            self._GLib.idle_add(self._feed_handler.add_card, card)
        else:
            self._feed_handler.add_card(card)

    def _post_closing_card(self, thread: A2AThread) -> None:
        """Post a closing card to the project feed showing consultation end."""
        if self._feed_handler is None:
            return

        card = FeedCardData(
            card_type="agent_action",
            source="system",
            title="Consultation complete",
            body=f"Exchange between @{thread.initiator_name} and @{thread.target_name} ({thread.turn} turns)",
            author="System",
            timestamp=datetime.now(timezone.utc),
            project_name=thread.project_name,
            metadata={"action": "consultation_close", "thread_id": thread.thread_id},
        )
        if self._GLib is not None:
            self._GLib.idle_add(self._feed_handler.add_card, card)
        else:
            self._feed_handler.add_card(card)

    # ── Response Routing ────────────────────────────────────────────────────

    def is_pending_relay(self, session_key: str) -> bool:
        """Check if a session key has a pending A2A response. Called by
        ChatHandler and AgentRuntimeHandler to decide routing."""
        return session_key in self._pending_relays

    # ── Static Mention Detection ─────────────────────────────────────────────

    @staticmethod
    def detect_a2a_mention(
        text: str,
        source_sk: str,
        project_name: str,
        command_handler,
    ) -> dict | None:
        """
        Detect @AgentName in text and resolve to session key.

        Returns {"target_sk": ..., "question": ...} or None.

        Mirrors spec §7.2 — uses CommandHandler for @mention resolution,
        which searches both gateway and special agents (Phase 1).
        """
        import re
        mention_match = re.search(r'@([A-Za-z][A-Za-z0-9_]+)', text)
        if not mention_match:
            return None

        agent_name = mention_match.group(1)

        if command_handler is None:
            return None

        from models.command import MentionResolution
        resolution = command_handler.resolve_inline_mention(f"@{agent_name}", source_sk)

        # Duck-type: works with real MentionResolution and test fakes
        target_sk = getattr(resolution, 'target_session_key', None)
        is_broadcast = getattr(resolution, 'is_broadcast', False)

        if (
            target_sk
            and target_sk != source_sk
            and not is_broadcast
        ):
            return {
                "target_sk": target_sk,
                "question": text,
            }
        return None