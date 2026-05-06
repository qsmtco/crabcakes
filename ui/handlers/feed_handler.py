# ui/handlers/feed_handler.py
# Feed state management + card lifecycle (Phase 2).
# Delegates rendering to feed_card.py, git ops to git_ops.py.
# All GTK via GLib.idle_add(). All git operations run in background threads.
#
# Architecture: one handler per subsystem. Does NOT import other handlers.
# Window wires cross-handler communication via callbacks set in constructor.
# No GTK calls from background threads — always via GLib.idle_add().

from dataclasses import dataclass
import logging
from typing import Callable
import threading
import time
import uuid
from datetime import datetime, timezone

from models.feed_card import FeedCardData
from ui.views.feed_card import build_feed_card, update_card_badge
from utils import git_ops
from utils import feed_store
from utils import conversation_store
from models.conversation_snapshot import ConversationSnapshot

_logger = logging.getLogger(__name__)


class FeedHandler:
    """
    Manages project feed state and coordinates card lifecycle.

    Card lifecycle: add_card() → build widget → prepend to FeedTab
    Button actions: handle_review/accept/reject → GLib.idle_add for GTK
    Git operations: run in background threads, callback to main thread on completion

    Args:
        GLib:                    gi.repository.GLib module — for idle_add dispatch
        feed_tab:                FeedTab instance — for card prepend/remove
        on_populate_input:       Callable[[str], None] — fill input box for Review
        on_send_to_agent:        Callable[[str, str], None] — send message to agent
        on_tab_switch:           Callable[[], None] — switch to feed tab
        on_card_added:           Callable[[str], None] | None — card_id after add
    """

    def __init__(
        self,
        *,
        GLib,                        # gi.repository.GLib
        on_send_to_agent,             # callback(session_key, text) — send to agent
        on_card_added=None,           # callback(card_id) | None
        on_approve_exec=None,         # callback(approval_id, approved: bool) | None — Phase E
        get_chat_box_for_session=None,  # callback(session_key) -> Gtk.Box | None
    ):
        self._GLib = GLib
        self._feed_tab = None         # set via set_feed_tab() after FeedTab is created
        self._on_send_to_agent = on_send_to_agent
        self._on_card_added = on_card_added
        self._on_approve_exec = on_approve_exec  # Phase E
        self._get_chat_box_for_session = get_chat_box_for_session

        # Card storage: card_id → FeedCardData
        self._cards: dict[str, FeedCardData] = {}
        # Widget storage: card_id → Gtk.Widget
        self._card_widgets: dict[str, Gtk.Widget] = {}
        # Project → [card_ids] index (newest first)
        self._project_cards: dict[str, list[str]] = {}
        # Project name → project path lookup (for persistence)
        self._project_paths: dict[str, str] = {}
        # True when loading persisted cards (skips redundant feed.json writes)
        self._active_project_name: str | None = None
        self._loading = False
        # Protects all shared dicts from concurrent access across threads
        self._lock = threading.Lock()

        # Echo suppression: git accept/reject triggers filesystem changes that
        # CrabWatch detects as new events. Track recently operated file paths
        # to suppress these echoes. dict[file_path] → timestamp (time.monotonic()).
        self._recent_git_paths: dict[str, float] = {}
        self._echo_suppress_seconds = 3.0

    def set_feed_tab(self, feed_tab) -> None:
        """
        Set the FeedTab view instance.

        Called by window after FeedTab is created and before any project is opened.
        Once set, FeedHandler can add/remove cards from the FeedTab.
        """
        self._feed_tab = feed_tab

    # ─────────────────────────────────────────────────────────────────
    # Card lifecycle
    # ─────────────────────────────────────────────────────────────────

    def add_card(self, card_data: FeedCardData) -> str:
        """
        Add a card to the project feed.

        1. Assign unique card_id (uuid4)
        2. Store in self._cards[card_id]
        3. Index under project_name
        4. Build widget via build_feed_card()
        5. Prepend to feed_tab
        6. Persist to feed.json via feed_store.append_feed_card()
        7. Return card_id

        Thread-safe: GTK operations via GLib.idle_add().
        """
        card_id = str(uuid.uuid4())
        card_data.card_id = card_id

        # ── Create conversation snapshot (deferred) ───────────────────────
        # Must run AFTER the bubble is appended to the chat box, because
        # _maybe_create_snapshot reads messages from the chat box widgets.
        # At this point render_sync() just returned the bubble but it hasn't
        # been appended yet (that happens in _handle_final_response after
        # render_sync returns). idle_add defers to the next main-loop cycle.
        _card_id = card_id
        self._GLib.idle_add(lambda: self._finalize_snapshot(_card_id))

        # Store data under lock (protects against concurrent _load_and_render)
        with self._lock:
            self._cards[card_id] = card_data

            # Index under project
            proj = card_data.project_name
            if proj not in self._project_cards:
                self._project_cards[proj] = []
            self._project_cards[proj].insert(0, card_id)  # newest first

        # Build widget (pure Python, no shared state) — done outside lock
        # Phase E: approval cards use approve/deny callbacks instead of accept/reject
        if card_data.metadata.get("needs_approval"):
            on_approve, on_deny = self._make_approve_exec_cb(card_id)
            widget = build_feed_card(
                card_data,
                on_review=self._make_review_cb(card_id),
                on_accept=on_approve,
                on_reject=on_deny,
                on_copy=self._make_copy_cb(card_data),
            )
        else:
            widget = build_feed_card(
                card_data,
                on_review=self._make_review_cb(card_id),
                on_accept=self._make_accept_cb(card_id),
                on_reject=self._make_reject_cb(card_id),
                on_copy=self._make_copy_cb(card_data),
            )

        with self._lock:
            self._card_widgets[card_id] = widget

        # Get project path from card metadata (set by on_project_opened load path),
        # or fall back to _project_paths if the card came from the parser (metadata empty).
        project_path = card_data.metadata.get("project_path", "") or self._project_paths.get(card_data.project_name, "")

        # Append to feed tab on main thread (newest at bottom), then persist
        def _append():
            if self._feed_tab is not None:
                self._feed_tab.append_card(widget, card_id)
                self._feed_tab.scroll_to_bottom()
                if self._on_card_added:
                    self._on_card_added(card_id)

        def _persist():
            if project_path and hasattr(card_data, 'to_dict') and not self._loading:
                # Skip snapshot persistence if oversized
                if card_data.metadata.get("_snapshot_oversized"):
                    # Temporarily remove snapshot for persistence
                    saved = card_data.conversation_snapshot
                    card_data.conversation_snapshot = None
                    feed_store.append_feed_card(project_path, card_data)
                    card_data.conversation_snapshot = saved
                else:
                    feed_store.append_feed_card(project_path, card_data)

        self._GLib.idle_add(_append)
        # Persist in background to avoid blocking UI.
        # Skip persistence when _loading=True (cards already on disk from load).
        if project_path and not self._loading:
            t = threading.Thread(target=_persist, daemon=True)
            t.start()

        return card_id

    def remove_card(self, card_id: str) -> None:
        """Remove a card from the feed."""
        with self._lock:
            if card_id not in self._cards:
                return
            proj = self._cards[card_id].project_name
            if proj in self._project_cards and card_id in self._project_cards[proj]:
                self._project_cards[proj].remove(card_id)
            self._cards.pop(card_id, None)
            widget = self._card_widgets.pop(card_id, None)

        def _remove():
            if self._feed_tab is not None:
                self._feed_tab.remove_card(card_id)

        self._GLib.idle_add(_remove)

    def get_card(self, card_id: str) -> FeedCardData | None:
        """Get card data by ID."""
        return self._cards.get(card_id)

    def update_card(self, card_id: str, card_data: FeedCardData) -> None:
        """
        Update an existing card's data and re-render its widget.

        Used by AgentRuntimeHandler Phase D to update tool call cards with results.

        Steps:
        1. Update in-memory FeedCardData in self._cards
        2. Rebuild widget via build_feed_card()
        3. Replace old widget in self._card_widgets
        4. Replace widget in FeedTab
        5. Persist to feed_store

        Thread-safe: GTK operations via GLib.idle_add().
        """
        if card_id not in self._cards:
            logger.warning("update_card: card %s not found", card_id)
            return

        # Update in-memory data
        with self._lock:
            self._cards[card_id] = card_data

        old_widget = self._card_widgets.get(card_id)

        # Rebuild widget (same construction as add_card)
        # Phase E: approval cards use approve/deny callbacks instead of accept/reject
        if card_data.metadata.get("needs_approval"):
            on_approve, on_deny = self._make_approve_exec_cb(card_id)
            new_widget = build_feed_card(
                card_data,
                on_review=self._make_review_cb(card_id),
                on_accept=on_approve,
                on_reject=on_deny,
                on_copy=self._make_copy_cb(card_data),
            )
        else:
            new_widget = build_feed_card(
                card_data,
                on_review=self._make_review_cb(card_id),
                on_accept=self._make_accept_cb(card_id),
                on_reject=self._make_reject_cb(card_id),
                on_copy=self._make_copy_cb(card_data),
            )

        # Update widget storage
        with self._lock:
            self._card_widgets[card_id] = new_widget

        # Persist to feed_store (update_feed_card updates JSON)
        project_path = self._project_paths.get(card_data.project_name, "")
        if project_path:
            from utils.feed_store import update_feed_card
            updates = {
                "body": card_data.body,
                "metadata": card_data.metadata,
            }
            update_feed_card(project_path, card_id, updates)

        # Replace widget in FeedTab on main thread
        _card_id = card_id
        _old_widget = old_widget
        _new_widget = new_widget

        def _replace():
            if self._feed_tab is None:
                return
            if _old_widget is not None:
                self._feed_tab.replace_card(_card_id, _new_widget)
            else:
                # No old widget to replace — just append (edge case)
                self._feed_tab.append_card(_new_widget, _card_id)

        self._GLib.idle_add(_replace)

    def get_cards_for_project(self, project_name: str) -> list[FeedCardData]:
        """Get all cards for a project, newest first."""
        card_ids = self._project_cards.get(project_name, [])
        return [self._cards[cid] for cid in card_ids if cid in self._cards]

    def clear_project(self, project_name: str) -> None:
        """Remove all cards for a project (on project close)."""
        with self._lock:
            card_ids = self._project_cards.get(project_name, [])
            for cid in list(card_ids):
                self._card_widgets.pop(cid, None)
                self._cards.pop(cid, None)
            self._project_cards.pop(project_name, None)
        for cid in card_ids:
            if self._feed_tab:
                self._feed_tab.remove_card(cid)

    # ─────────────────────────────────────────────────────────────────
    # Project lifecycle hooks
    # ─────────────────────────────────────────────────────────────────

    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """
        Called when a project opens.

        1. Clear previous project's cards if switching projects
        2. Load cards from .crabcakes/feed.json via feed_store.load_feed()
        3. Render all cards (chronological order → oldest at top, newest at bottom)
        4. Switch to Project Feed tab (default tab on open)
        5. Auto-scroll to bottom (newest card visible)
        6. If no cards, show empty state widget
        """
        # Clear previous project if switching — prevents card bleed between projects
        prev = self._active_project_name
        if prev and prev != project_name:
            self.clear_project(prev)
        self._active_project_name = project_name
        # Store project_path for persistence on new card adds
        self._project_paths[project_name] = project_path

        def _load_and_render():
            # Mark loading mode — add_card skips persistence for already-saved cards
            self._loading = True

            # Load persisted cards from .crabcakes/feed.json
            cards = feed_store.load_feed(project_path)

            if not cards:
                self._GLib.idle_add(lambda: self._feed_tab.show_empty_state() if self._feed_tab else None)
                self._loading = False
                return

            # Seed state: set metadata
            for card in cards:
                if not card.metadata:
                    card.metadata = {}
                card.metadata["project_path"] = project_path

            # Build all widgets (pure Python — no GTK yet) while holding lock
            widgets = {}
            with self._lock:
                # Index by project (newest first)
                if project_name not in self._project_cards:
                    self._project_cards[project_name] = []
                for card in cards:
                    if card.card_id:
                        self._project_cards[project_name].append(card.card_id)

                # Build and store widgets/data under lock
                for card in cards:
                    widget = build_feed_card(
                        card,
                        on_review=self._make_review_cb(card.card_id),
                        on_accept=self._make_accept_cb(card.card_id),
                        on_reject=self._make_reject_cb(card.card_id),
                        on_copy=self._make_copy_cb(card),
                    )
                    self._card_widgets[card.card_id] = widget
                    self._cards[card.card_id] = card
                    widgets[card.card_id] = widget

            # Switch to feed tab on main thread (default tab on project open)

            # Add each card to the feed on main thread
            def _add_card_widget(card):
                widget = widgets.get(card.card_id)
                if widget and self._feed_tab:
                    self._feed_tab.append_card(widget, card.card_id)

            for card in cards:  # chronological: oldest first, newest last (bottom)
                self._GLib.idle_add(lambda c=card: _add_card_widget(c))

            # Auto-scroll to bottom (newest card visible) on main thread
            self._GLib.idle_add(lambda: self._feed_tab.scroll_to_bottom() if self._feed_tab else None)

            self._loading = False

        t = threading.Thread(target=_load_and_render, daemon=True)
        t.start()

    def on_project_closed(self, project_name: str) -> None:
        """Called when project closes. Clear cards for this project."""
        if self._active_project_name == project_name:
            self._active_project_name = None
        self.clear_project(project_name)

        def _clear():
            if self._feed_tab is not None:
                self._feed_tab.show_empty_state()
        self._GLib.idle_add(_clear)

    # ─────────────────────────────────────────────────────────────────
    # Button action handlers
    # ─────────────────────────────────────────────────────────────────

    def handle_review(self, card_id: str, card_widget=None) -> None:
        """Review button clicked — toggle context panel visibility."""
        card = self._cards.get(card_id)
        if card is None:
            return

        card.reviewed = True

        if card_widget is not None and hasattr(card_widget, '_context_panel'):
            panel = card_widget._context_panel
            panel.set_visible(not panel.get_visible())

    def _add_git_card(self, original_card: FeedCardData, result) -> None:
        """Create a git_commit feed card after accept or reject."""
        if result is None or not hasattr(result, 'success') or not result.success:
            return
        accepted = original_card.accepted is True
        action = "Accepted" if accepted else "Rejected"
        git_card = FeedCardData(
            card_type="git_commit",
            source="git",
            title=f"{action}: {original_card.title}",
            body=result.stdout.strip() if result.stdout else "",
            author="PM",
            timestamp=datetime.now(timezone.utc),
            project_name=original_card.project_name,
            commit_sha=result.sha if hasattr(result, 'sha') and result.sha else None,
            file_path=original_card.file_path,
        )
        self.add_card(git_card)

    def handle_accept(self, card_id: str) -> None:
        """
        Accept button clicked.

        For git-backed cards (diff, file_created, file_deleted):
          1. Stage + commit in background thread
          2. Mark card.accepted = True on main thread
          3. Visual feedback via CSS class

        For other card types:
          1. Mark card.accepted = True
        """
        card = self._cards.get(card_id)
        if card is None:
            return

        if card.card_type in ("diff", "file_created", "file_modified", "file_deleted"):
            project_path = card.metadata.get("project_path", "") or self._project_paths.get(card.project_name, "")
            if not project_path:
                return

            def _git_accept():
                result_stage = git_ops.stage_all(project_path)
                if not result_stage.success:
                    _logger.warning("handle_accept: git stage failed for %s", project_path)
                    return
                commit_msg = f"Accept: {card.title}"
                result_commit = git_ops.commit(project_path, commit_msg)
                if result_commit.success:
                    card.accepted = True
                    card.metadata["project_path"] = project_path
                    # Persist to feed.json
                    feed_store.update_feed_card(project_path, card_id, {"accepted": True})
                    # Update visual on main thread
                    def _mark():
                        self._update_card_visual(card_id, accepted=True)
                    self._GLib.idle_add(_mark)
                    self._GLib.idle_add(lambda: self._add_git_card(card, result_commit))

            # Record path for echo suppression BEFORE starting git thread.
            # CrabWatch will fire events when git modifies the filesystem;
            # on_filesystem_event() checks _recent_git_paths to suppress echoes.
            if card.file_path:
                self._recent_git_paths[card.file_path] = time.monotonic()

            t = threading.Thread(target=_git_accept, daemon=True)
            t.start()
        else:
            card.accepted = True
            self._update_card_visual(card_id, accepted=True)

    def handle_reject(self, card_id: str) -> None:
        """
        Reject button clicked.

        For git-backed cards:
          1. Revert changes in background thread
          2. Mark card.accepted = False
          3. Notify agent via on_send_to_agent

        For other cards:
          1. Mark card.accepted = False
        """
        card = self._cards.get(card_id)
        if card is None:
            return

        if card.card_type in ("diff", "file_created", "file_modified", "file_deleted"):
            project_path = card.metadata.get("project_path", "") or self._project_paths.get(card.project_name, "")
            if not project_path:
                return

            def _git_reject():
                fp = card.file_path
                sha = card.commit_sha or "HEAD"
                result_reject = git_ops.checkout_paths(project_path, sha, [fp]) if fp else None

                def _mark():
                    card.accepted = False
                    card.metadata["project_path"] = project_path
                    self._update_card_visual(card_id, accepted=False)
                    # Persist to feed.json
                    feed_store.update_feed_card(project_path, card_id, {"accepted": False})
                    # Notify agent
                    msg = f"[PM] Rejected change: {card.title}"
                    self._on_send_to_agent(f"project:{card.project_name}", msg)
                    # Add git card
                    self._add_git_card(card, result_reject)
                self._GLib.idle_add(_mark)

            # Record path for echo suppression BEFORE starting git thread.
            if card.file_path:
                self._recent_git_paths[card.file_path] = time.monotonic()

            t = threading.Thread(target=_git_reject, daemon=True)
            t.start()
        else:
            card.accepted = False
            self._update_card_visual(card_id, accepted=False)

    def handle_copy(self, text: str) -> None:
        """Copy card body text to clipboard."""
        def _copy():
            import gi
            gi.require_version('Gtk', '4.0')
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            if display is None:
                return
            clipboard = display.get_clipboard()
            clipboard.set(text)
        self._GLib.idle_add(_copy)

    # ─────────────────────────────────────────────────────────────────
    # CrabWatch integration (Phase 5 stub — no-op now)
    # ─────────────────────────────────────────────────────────────────

    def on_filesystem_event(self, card_data: FeedCardData) -> None:
        """
        Entry point for CrabWatch file change events.
        Same as add_card() but source is always 'system' or 'crabwatch'.

        Includes echo suppression: if this file_path was involved in a recent
        git accept/reject (within _echo_suppress_seconds), the event is dropped
        to avoid duplicate cards for changes the PM just approved/rejected.
        """
        # Echo suppression — check if this path was recently part of a git op
        fp = card_data.file_path
        if fp and fp in self._recent_git_paths:
            elapsed = time.monotonic() - self._recent_git_paths[fp]
            if elapsed < self._echo_suppress_seconds:
                _logger.debug(
                    "on_filesystem_event: suppressed echo for %s (%.1fs after git op)",
                    fp, elapsed,
                )
                return
            # Expired — clean up
            del self._recent_git_paths[fp]

        card_data.source = "system"
        # ── Create diff snapshot for system cards (NEW) ────────────────
        project_path = self._project_paths.get(card_data.project_name, "")
        if project_path and card_data.file_path:
            snapshot = conversation_store.snapshot_from_git_diff(project_path, card_data.file_path)
            card_data.conversation_snapshot = snapshot
        self.add_card(card_data)

    def _finalize_snapshot(self, card_id: str) -> bool:
        """Deferred snapshot creation — runs via GLib.idle_add after bubble is in chat box."""
        card = self._cards.get(card_id)
        if card is not None:
            self._maybe_create_snapshot(card)
            # Re-render the card widget if it exists and snapshot was created
            if card.conversation_snapshot is not None:
                widget = self._card_widgets.get(card_id)
                if widget is not None and hasattr(widget, '_context_panel'):
                    # Panel already built without snapshot — update it
                    panel = widget._context_panel
                    # Clear old content
                    child = panel.get_first_child()
                    while child is not None:
                        next_child = child.get_next_sibling()
                        panel.remove(child)
                        child = next_child
                    # Rebuild panel content with snapshot data
                    self._rebuild_context_panel(panel, card.conversation_snapshot)
        return False  # Don't repeat

    def _rebuild_context_panel(self, panel, snapshot):
        """Rebuild the contents of a context panel from a snapshot."""
        from ui.views.feed_card import build_context_panel
        # We can't replace the panel in-place easily, so we rebuild its children.
        # build_context_panel returns a new box — copy its children into the existing panel.
        new_panel = build_context_panel(snapshot)
        child = new_panel.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            new_panel.remove(child)
            panel.append(child)
            child = next_child

    def _maybe_create_snapshot(self, card_data: FeedCardData) -> None:
        """
        Create a conversation snapshot for the card if applicable.

        - Agent cards: extract conversation from chat box
        - System/crabwatch cards: extract git diff
        """
        snapshot = None

        if card_data.source == "agent" and self._get_chat_box_for_session:
            # Use tab_key (the chat box key, e.g. "project:crabwatch") not session_key
            # (the agent's gateway key, e.g. "agent:qaster:...") for the lookup.
            # Falls back to session_key for non-project chats where both are the same.
            lookup_key = card_data.metadata.get("tab_key", "") or card_data.metadata.get("session_key", "")
            chat_box = self._get_chat_box_for_session(lookup_key)
            if chat_box is not None:
                messages_raw = self._extract_messages_from_chat_box(chat_box)
                snapshot = conversation_store.snapshot_from_messages(
                    messages_raw, lookup_key, total_available=len(messages_raw)
                )

        elif card_data.source in ("system", "crabwatch"):
            project_path = card_data.metadata.get("project_path", "") or self._project_paths.get(card_data.project_name, "")
            if project_path and card_data.file_path:
                snapshot = conversation_store.snapshot_from_git_diff(project_path, card_data.file_path)

        if snapshot is not None:
            card_data.conversation_snapshot = snapshot
            # Check size limit — skip persistence if too large
            if conversation_store.snapshot_exceeds_size_limit(snapshot):
                _logger.warning(
                    "Snapshot for card %s exceeds %dKB — rendered in-memory but not persisted",
                    card_data.card_id, conversation_store.MAX_SNAPSHOT_SIZE_KB,
                )
                # Remove from metadata so to_dict() won't persist it,
                # but keep on card_data for in-memory rendering.
                # We achieve this by NOT setting metadata["snapshot"] —
                # to_dict() serializes from conversation_snapshot field.
                # Instead, we'll handle this in _persist by stripping snapshot.
                card_data.metadata["_snapshot_oversized"] = True

    # ─────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────

    def _make_review_cb(self, card_id: str):
        def cb(cid=card_id, widget=None):
            self.handle_review(cid, widget)
        return cb

    def _extract_messages_from_chat_box(self, chat_box) -> list[tuple[str, str]]:
        """
        Extract (role, text) pairs from a Gtk.Box containing chat bubbles.

        Walks child widgets and reads _crabcakes_role / _crabcakes_text
        attributes set by build_role_bubble(). Returns oldest-first.

        This is the ONLY place GTK widget methods are called for snapshot
        extraction — keeping utils/conversation_store.py GTK-free.
        """
        all_children = []
        child = chat_box.get_first_child()
        while child is not None:
            all_children.append(child)
            child = child.get_next_sibling()

        messages = []
        for widget in all_children:
            role = getattr(widget, "_crabcakes_role", None)
            text = getattr(widget, "_crabcakes_text", None)
            if role is not None and text is not None:
                messages.append((role, text))
        return messages

    def _make_accept_cb(self, card_id: str):
        def cb(cid=card_id):
            self.handle_accept(cid)
        return cb

    def _make_reject_cb(self, card_id: str):
        def cb(cid=card_id):
            self.handle_reject(cid)
        return cb

    def handle_approve_exec(self, card_id: str, approved: bool) -> None:
        """
        Phase E: Handle Approve/Deny click on a pending exec approval card.

        For cards with needs_approval=True, this is called instead of
        handle_accept/handle_reject. Delegates to on_approve_exec callback
        (AgentRuntimeHandler.approve_exec) to resolve the pending approval.
        """
        card = self._cards.get(card_id)
        if card is None:
            return
        if card.metadata.get("needs_approval") != True:
            # Not an approval card — fall through to handle_accept/handle_reject
            return

        if self._on_approve_exec is not None:
            self._on_approve_exec(card_id, approved)
        else:
            _logger.warning("handle_approve_exec: no on_approve_exec callback registered")

    def _make_approve_exec_cb(self, card_id: str) -> tuple[Callable, Callable]:
        """
        Phase E: Return (approve_cb, deny_cb) for an approval card.

        Called when building an approval card to wire Accept/Deny buttons
        to handle_approve_exec with approved=True/False.
        """
        def on_approve(cid=card_id):
            self.handle_approve_exec(cid, True)
        def on_deny(cid=card_id):
            self.handle_approve_exec(cid, False)
        return on_approve, on_deny

    def _make_copy_cb(self, card_data: FeedCardData):
        body = card_data.body or card_data.title
        def cb(text=body):
            self.handle_copy(text)
        return cb

    def _update_card_visual(self, card_id: str, accepted: bool) -> None:
        """Apply accepted/rejected CSS class + badge to card widget."""
        widget = self._card_widgets.get(card_id)
        if widget is None:
            return
        # accepted=True → add feed-card-accepted, remove feed-card-rejected
        # accepted=False → add feed-card-rejected, remove feed-card-accepted
        cls_add = "feed-card-accepted" if accepted else "feed-card-rejected"
        cls_rem = "feed-card-rejected" if accepted else "feed-card-accepted"
        widget.add_css_class(cls_add)
        widget.remove_css_class(cls_rem)

        # Update badge in footer (ACCEPTED/REJECTED label)
        update_card_badge(widget, accepted)

        # Update card data
        card = self._cards.get(card_id)
        if card:
            card.accepted = accepted