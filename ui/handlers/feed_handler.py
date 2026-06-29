# ui/handlers/feed_handler.py
# Feed state management + card lifecycle (Phase 2).
# Delegates rendering to feed_card.py, git ops to git_ops.py.
from __future__ import annotations
# All GTK via GLib.idle_add(). All git operations run in background threads.
#
# Architecture: one handler per subsystem. Does NOT import other handlers.
# Window wires cross-handler communication via callbacks set in constructor.
# No GTK calls from background threads — always via GLib.idle_add().

from dataclasses import dataclass
import logging
import re
from typing import Callable
import threading
import time


# MED-11: Validate git commit SHA to prevent argument injection
_VALID_SHA_RE = re.compile(r"^(HEAD|[0-9a-fA-F]{4,40})$")
import uuid
from datetime import datetime, timezone

from models.feed_card import AutoAcceptPrefs, FeedCardData
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
        # Per-project sequence counter for display numbers (Phase 3)
        self._project_seq: dict[str, int] = {}
        # True when loading persisted cards (skips redundant feed.json writes)
        self._active_project_name: str | None = None
        self._loading = False
        # Protects all shared dicts from concurrent access across threads
        self._lock = threading.Lock()

        # Lazy-load backlog: older cards not yet rendered.
        # Populated by on_project_opened() when total cards > PAGE_SIZE.
        # Loaded in pages by _load_more().
        self._backlog: list[FeedCardData] = []
        self._load_more_widget: Gtk.Widget | None = None
        self.PAGE_SIZE = 15

        # Echo suppression: git accept/reject triggers filesystem changes that
        # CrabWatch detects as new events. Track recently operated file paths
        # to suppress these echoes. dict[file_path] → timestamp (time.monotonic()).
        self._recent_git_paths: dict[str, float] = {}
        self._echo_suppress_seconds = 3.0

        # Phase 5: auto-accept toggle state
        # _auto_accept_enabled: master toggle persisted in feed-prefs.json
        # _auto_accept_agent: once set, only cards from this author are auto-accepted.
        #   None = agent not yet locked-in (first matching card will lock it in).
        # _show_auto_accept_warning: callback injected by Window; receives
        #   (agent_name, on_confirm, on_cancel) and is expected to show a dialog.
        # V2 auto-accept preferences (replaces _auto_accept_enabled + _auto_accept_agent
        # as the canonical state; the legacy fields below remain as derived
        # bookkeeping for the transition period and for legacy direct-set tests).
        self._prefs: AutoAcceptPrefs = AutoAcceptPrefs()
        self._auto_accept_enabled: bool = False  # derived: equals _prefs.any_enabled()
        self._auto_accept_agent: str | None = None  # runtime lock-in (not persisted)
        # Pending save-id for debounced _save_feed_prefs_idle() (set by
        # _refresh_auto_accept_state; cleared after the idle callback runs).
        self._pending_save_id = None
        self._show_auto_accept_warning: Callable | None = None  # callback injected by Window

    def set_feed_tab(self, feed_tab) -> None:
        """
        Set the FeedTab view instance.

        Called by window after FeedTab is created and before any project is opened.
        Once set, FeedHandler can add/remove cards from the FeedTab.
        """
        self._feed_tab = feed_tab
        # Phase 5: wire batch accept callback
        if self._feed_tab is not None:
            self._feed_tab.set_batch_accept_callback(
                lambda: self._on_batch_accept_clicked()
            )
            # V2: wire per-toggle callbacks (Phase 3 rebuild of the toolbar).
            # These setters only exist on the rebuilt FeedTab; legacy tests
            # using MockFeedTab don't define them, so guard with hasattr.
            if hasattr(self._feed_tab, "set_diffs_toggle_callback"):
                self._feed_tab.set_diffs_toggle_callback(self._on_diffs_toggled)
            if hasattr(self._feed_tab, "set_files_toggle_callback"):
                self._feed_tab.set_files_toggle_callback(self._on_files_toggled)
            if hasattr(self._feed_tab, "set_exec_toggle_callback"):
                self._feed_tab.set_exec_toggle_callback(self._on_exec_toggled)
            # Keep legacy callback for backward compat during the v1→v2
            # transition — legacy tests still call _on_auto_accept_toggled.
            self._feed_tab.set_auto_accept_callback(self._on_auto_accept_toggled)

    def set_show_auto_accept_warning(self, callback: Callable | None) -> None:
        """
        Install the callback invoked when the user activates auto-accept
        for any feature (diffs, files, exec). (Phase 5 + v2)

        The callback signature (as of v2) is:
            callback(category: str, agent_name: str,
                     on_confirm: Callable, on_cancel: Callable)
        where category is one of "diffs" | "files" | "exec" and agent_name
        is the human-readable name of the agent the auto-accept applies to
        (resolved by the handler's first_author fallback chain).

        The legacy v1 3-arg signature `(agent_name, on_confirm, on_cancel)`
        is still honored by the legacy wrapper `_on_auto_accept_toggled`
        during the v1→v2 transition; new v2 toggles (_on_diffs_toggled
        etc.) pass all four arguments.

        Pass None to clear. Called by Window after FeedHandler is constructed.
        """
        self._show_auto_accept_warning = callback

    def _resolve_agent_name_for_dialog(self) -> str:
        """
        Return the best human-readable agent name for the warning dialog.
        Fallback chain: _auto_accept_agent → most recent card's author → "the active agent".
        Never returns None or the string "None". (Phase 5)
        """
        if self._auto_accept_agent:
            return self._auto_accept_agent
        # Iterate cards newest-first, find most recent card with an author
        if self._active_project_name:
            card_ids = self._project_cards.get(self._active_project_name, [])
            for cid in card_ids:  # newest first
                card = self._cards.get(cid)
                if card and card.author:
                    return card.author
        return "the active agent"

    def _on_auto_accept_toggled(self, active: bool) -> None:
        """
        Legacy v1 toggle entry point (Phase 5).

        Kept as a thin wrapper around the v2 toggle methods so existing
        tests that bind to the old FeedTab.set_auto_accept_callback
        setter continue to work during the v1→v2 transition.

        ON: show warning dialog (legacy 3-arg signature), then enable all.
        OFF: disable all immediately (no dialog needed).
        """
        if active:
            if self._show_auto_accept_warning is not None:
                # Legacy 3-arg signature (agent_name, on_confirm, on_cancel).
                # Window-supplied callback in current wiring still uses this.
                self._show_auto_accept_warning(
                    self._resolve_agent_name_for_dialog(),
                    on_confirm=self._enable_auto_accept,
                    on_cancel=self._cancel_auto_accept,
                )
            else:
                # No warning callback wired (tests, headless) — enable directly
                self._enable_auto_accept()
        else:
            self._disable_auto_accept()

    def _enable_auto_accept(self) -> None:
        """Legacy v1: enable auto-accept for all file-change types + exec.

        Bug B fix: also call update_auto_accept_state(True) so the toolbar
        toggle's label flips from "Auto-Accept: OFF" to "Auto-Accept: ON".
        Previously only the in-memory flag was set; the label was stuck on
        OFF because Gtk.ToggleButton.set_active(True) does not change
        set_label() text.

        Phase 4 v2 migration: also populates self._prefs so the new
        per-type policy method (_is_card_auto_acceptable) sees a consistent
        state. Without this, a legacy test that sets _auto_accept_enabled
        directly would not trigger v2 auto-accept because _prefs.file_changes
        would still be all-False.
        """
        self._auto_accept_enabled = True
        # Mirror into v2 prefs so per-type policy sees a consistent state.
        for fc in self._prefs.file_changes.values():
            fc.enabled = True
        self._prefs.exec_command.mode = "show"
        self._refresh_auto_accept_state()

    def _cancel_auto_accept(self) -> None:
        """Legacy v1: snap the toggle back to OFF and reset in-memory state.

        Invariant fix: previously this only updated the visible toggle and
        left self._auto_accept_enabled at True, creating a silent-accept
        window where add_card() would auto-accept new cards with no
        user-visible cue. We now reset the in-memory flag so state and UI
        stay in sync.

        Does NOT persist (preserve legacy behavior — the user cancelled, so
        nothing to save).
        """
        self._auto_accept_enabled = False
        # Mirror into v2 prefs so per-type policy sees a consistent state.
        for fc in self._prefs.file_changes.values():
            fc.enabled = False
        self._prefs.exec_command.mode = "off"
        self._refresh_auto_accept_state()

    def _disable_auto_accept(self) -> None:
        """Legacy v1: disable auto-accept and persist state.

        Mirrors the Bug B fix in `_enable_auto_accept`: any code path that
        mutates `_auto_accept_enabled` must also call
        `update_auto_accept_state(...)` so the toolbar label tracks state.
        Without this call, user-click-OFF leaves the label stuck on
        "Auto-Accept: ON" even though the flag and persisted prefs are OFF.
        """
        self._auto_accept_enabled = False
        # Mirror into v2 prefs so per-type policy sees a consistent state.
        for fc in self._prefs.file_changes.values():
            fc.enabled = False
        self._prefs.exec_command.mode = "off"
        self._refresh_auto_accept_state()

    def _save_feed_prefs_idle(self) -> None:
        """
        Persist auto-accept state to .crabcakes/feed-prefs.json. (Phase 5)
        Called via GLib.idle_add so it runs on the main thread.
        """
        project_path = self._project_paths.get(self._active_project_name or "")
        if not project_path:
            return
        feed_store.save_feed_prefs(project_path, {
            "version": 1,
            "auto_accept_enabled": self._auto_accept_enabled,
            "auto_accept_agent": self._auto_accept_agent,
        })

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

        # Assign sequence number (Phase 3)
        proj = card_data.project_name
        if proj not in self._project_seq:
            self._project_seq[proj] = 0
        self._project_seq[proj] += 1
        card_data.seq_num = self._project_seq[proj]

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
                self._schedule_smart_scroll()  # one funnel for all append paths
                # Phase 5: auto-accept check (runs on main thread via idle_add)
                # Must run AFTER append_card so the widget exists in the tree
                # before handle_accept starts git ops. (Phase 5)
                if (self._auto_accept_enabled
                        and card_data.accepted is None
                        and card_data.card_type in _AUTO_ACCEPT_TYPES
                        and (self._auto_accept_agent is None or card_data.author == self._auto_accept_agent)):
                    # Lazy agent lock-in: first card after toggle ON sets the agent
                    if self._auto_accept_agent is None and card_data.author:
                        self._auto_accept_agent = card_data.author
                        self._GLib.idle_add(self._save_feed_prefs_idle)
                    self._GLib.idle_add(lambda cid=card_data.card_id: self.handle_accept(cid))
                if self._on_card_added:
                    self._on_card_added(card_id)

        # Refresh batch accept bar (Phase 5)
        self._update_batch_bar_for_active_project(card_data.project_name)

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

    def add_cards_batch(self, cards: list[FeedCardData]) -> list[str]:
        """Add multiple cards in a single main-thread pass.

        Each card still goes through the same pipeline as add_card() (id,
        sequence number, widget build, store, index, persist). The only
        difference: all widgets are appended in ONE GLib.idle_add callback
        and the smart scroll fires ONCE at the end.

        Why this matters: a single LLM response can contain N crabcards.
        Without batching, add_card() called N times enqueues N idle
        callbacks, each connecting its own one-shot vadjustment 'changed'
        handler and 150ms timeout. If cards arrive faster than GTK can
        lay them out, the proximity check reads stale values and the
        vadjustment 'changed' signal may already have fired before later
        handlers attach — leaving the feed scrolled mid-batch instead of
        at the newest card.

        Returns: list of card_ids in input order.
        """
        if not cards:
            return []

        card_ids: list[str] = []
        widget_by_id: dict[str, Gtk.Widget] = {}
        persist_data: list[tuple[FeedCardData, str]] = []  # (card, project_path)

        # Phase 1: assign ids, sequence numbers, build widgets (cheap, pure)
        with self._lock:
            for card_data in cards:
                card_id = str(uuid.uuid4())
                card_data.card_id = card_id

                proj = card_data.project_name
                if proj not in self._project_seq:
                    self._project_seq[proj] = 0

                # Sequence numbers stay monotonic per project even when
                # batching across projects — same as add_card() per-card.
                self._project_seq[proj] += 1
                card_data.seq_num = self._project_seq[proj]

                self._cards[card_id] = card_data
                if proj not in self._project_cards:
                    self._project_cards[proj] = []
                self._project_cards[proj].insert(0, card_id)

                card_ids.append(card_id)

        # Phase 2: build widgets outside the lock (pure Python, no shared state)
        for card_data, card_id in zip(cards, card_ids):
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
            widget_by_id[card_id] = widget

            # Cache project_path for the persistence phase
            project_path = (
                card_data.metadata.get("project_path", "")
                or self._project_paths.get(card_data.project_name, "")
            )
            persist_data.append((card_data, project_path))

            # Deferred snapshot per-card (same trick add_card uses)
            _cid = card_id
            self._GLib.idle_add(lambda: self._finalize_snapshot(_cid))

        with self._lock:
            for card_id, widget in widget_by_id.items():
                self._card_widgets[card_id] = widget

        # Phase 3: ONE main-thread pass to append all cards + ONE smart scroll
        def _append_all():
            if self._feed_tab is None:
                return
            for card_id in card_ids:
                widget = widget_by_id.get(card_id)
                if widget is not None:
                    self._feed_tab.append_card(widget, card_id)
            # Single scroll decision for the whole batch
            self._schedule_smart_scroll()
            if self._on_card_added:
                for card_id in card_ids:
                    self._on_card_added(card_id)

        self._GLib.idle_add(_append_all)

        # Phase 4: refresh batch bar once (cheap)
        # Use the first card's project; in practice all batched cards
        # come from the same agent response so they share project_name.
        if cards:
            self._update_batch_bar_for_active_project(cards[0].project_name)

        # Phase 5: persist all cards in one background thread
        if not self._loading:
            def _persist_all():
                for card_data, project_path in persist_data:
                    if not (project_path and hasattr(card_data, 'to_dict')):
                        continue
                    if card_data.metadata.get("_snapshot_oversized"):
                        saved = card_data.conversation_snapshot
                        card_data.conversation_snapshot = None
                        feed_store.append_feed_card(project_path, card_data)
                        card_data.conversation_snapshot = saved
                    else:
                        feed_store.append_feed_card(project_path, card_data)

            t = threading.Thread(target=_persist_all, daemon=True)
            t.start()

        return card_ids

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
                # No old widget to replace — just append (edge case).
                # Scroll here: a brand-new card appeared at the bottom and
                # the user wasn't looking at it, so smart-scroll handles
                # the "they had scrolled up" case automatically.
                self._feed_tab.append_card(_new_widget, _card_id)
                self._schedule_smart_scroll()

        self._GLib.idle_add(_replace)

    def get_cards_for_project(self, project_name: str) -> list[FeedCardData]:
        """Get all cards for a project, newest first."""
        card_ids = self._project_cards.get(project_name, [])
        return [self._cards[cid] for cid in card_ids if cid in self._cards]

    def _schedule_smart_scroll(self) -> None:
        """One funnel for all append paths. Only scrolls if the user is
        already near the bottom (within 80px), so users reading older
        cards are not yanked away.

        Safe to call when _feed_tab is None (no-op) or when no cards
        were actually appended (FeedTab handles that internally).
        """
        if self._feed_tab is None:
            return
        self._feed_tab.schedule_smart_scroll_to_bottom()

    def clear_project(self, project_name: str) -> None:
        """Remove all cards for a project (on project close)."""
        with self._lock:
            card_ids = self._project_cards.get(project_name, [])
            for cid in list(card_ids):
                self._card_widgets.pop(cid, None)
                self._cards.pop(cid, None)
            self._project_cards.pop(project_name, None)
            self._project_seq.pop(project_name, None)
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
        3. Render only the last PAGE_SIZE cards (newest)
        4. Store older cards in backlog for "Load More"
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
        # Clear backlog from previous project before starting load thread
        self._backlog = []
        self._load_more_widget = None

        def _load_and_render():
            # Mark loading mode — add_card skips persistence for already-saved cards
            self._loading = True

            # Load persisted cards from .crabcakes/feed.json
            cards = feed_store.load_feed(project_path)

            # Phase 5: load auto-accept prefs (separate file from feed.json)
            prefs = feed_store.load_feed_prefs(project_path)
            self._auto_accept_enabled = prefs.get("auto_accept_enabled", False)
            self._auto_accept_agent = prefs.get("auto_accept_agent")

            if not cards:
                self._GLib.idle_add(lambda: self._feed_tab.show_empty_state() if self._feed_tab else None)
                self._loading = False
                return

            # Seed state: set metadata
            for card in cards:
                if not card.metadata:
                    card.metadata = {}
                card.metadata["project_path"] = project_path

            # Migrate old cards: assign seq_nums to cards with seq_num=None,
            # in order of creation timestamp. This ensures every project gets
            # a clean sequence from #1 on first load after the seq_num field
            # is added. Without this migration, old projects would show a mix
            # of cards with seq badges and cards without, which is confusing.
            cards_sorted_by_timestamp = sorted(cards, key=lambda c: c.timestamp)
            next_seq = 1
            for card in cards_sorted_by_timestamp:
                if card.seq_num is None:
                    card.seq_num = next_seq
                next_seq = max(next_seq, card.seq_num + 1)

            # Rebuild sequence counter from loaded cards (now all have seq_num)
            max_seq = max((card.seq_num for card in cards if card.seq_num), default=0)
            self._project_seq[project_name] = max_seq

            # Split into recent (render now) and backlog (lazy load)
            # cards is chronological: oldest first, newest last
            if len(cards) > self.PAGE_SIZE:
                backlog = cards[:-self.PAGE_SIZE]  # older cards
                recent = cards[-self.PAGE_SIZE:]   # newest PAGE_SIZE cards
            else:
                backlog = []
                recent = cards

            # Store backlog for "Load More" (thread-safe under lock)
            with self._lock:
                self._backlog = list(reversed(backlog))  # newest-first for pop(0)

            # Build widgets for recent cards only
            widgets = {}
            with self._lock:
                # Index by project
                if project_name not in self._project_cards:
                    self._project_cards[project_name] = []

                # Index ALL cards (including backlog) so _project_cards is complete
                for card in cards:
                    if card.card_id:
                        self._project_cards[project_name].append(card.card_id)
                    self._cards[card.card_id] = card

                # Build widgets only for recent cards
                for card in recent:
                    widget = build_feed_card(
                        card,
                        on_review=self._make_review_cb(card.card_id),
                        on_accept=self._make_accept_cb(card.card_id),
                        on_reject=self._make_reject_cb(card.card_id),
                        on_copy=self._make_copy_cb(card),
                    )
                    self._card_widgets[card.card_id] = widget
                    widgets[card.card_id] = widget

            # Build "Load More" widget if backlog exists
            backlog_count = len(backlog)
            load_more_widget = None
            if backlog_count > 0:
                load_more_widget = self._build_load_more_widget(backlog_count)
                self._load_more_widget = load_more_widget

            # Add cards + load-more on main thread.
            # Use schedule_scroll_to_bottom() to defer the scroll until
            # AFTER GTK updates the vadjustment upper (layout pass).
            # Two GLib.idle_add callbacks run in the same idle batch and
            # do NOT yield to layout between them, so the second callback
            # reads a stale upper. The 'changed' signal on the vadjustment
            # fires after GTK allocates the new content height. (Bug A fix)
            def _append_and_schedule_scroll():
                if self._feed_tab is None:
                    return False

                # Prepend "Load More" at top if backlog exists
                if load_more_widget is not None:
                    self._feed_tab.prepend_card(load_more_widget, card_id="__load_more__")

                # Append recent cards (chronological: oldest first, newest last)
                for card in recent:
                    widget = widgets.get(card.card_id)
                    if widget:
                        self._feed_tab.append_card(widget, card.card_id)

                # Smart scroll: respects reading position if user scrolled up.
                # On project open the user has no prior position in this
                # project's feed, so the proximity check trivially passes.
                self._schedule_smart_scroll()

                # Phase 5: apply persisted auto-accept state to toggle visual
                if self._auto_accept_enabled is not None:
                    self._feed_tab.update_auto_accept_state(self._auto_accept_enabled)

                return False  # one-shot

            self._GLib.idle_add(_append_and_schedule_scroll)
            self._loading = False

        t = threading.Thread(target=_load_and_render, daemon=True)
        t.start()

    def on_project_closed(self, project_name: str) -> None:
        """Called when project closes. Clear cards for this project."""
        if self._active_project_name == project_name:
            self._active_project_name = None
        self.clear_project(project_name)
        self._backlog = []
        self._load_more_widget = None

        def _clear():
            if self._feed_tab is not None:
                self._feed_tab.show_empty_state()
        self._GLib.idle_add(_clear)

    # ─────────────────────────────────────────────────────────────────
    # Lazy load: "Load More" button
    # ─────────────────────────────────────────────────────────────────

    def _build_load_more_widget(self, remaining: int) -> Gtk.Widget:
        """Build the 'Load More' card that sits at the top of the feed.

        Shows count of older cards and a button to load the next page.
        Uses feed-card CSS for visual consistency.
        """
        from gi.repository import Gtk

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("feed-card")
        card.add_css_class("feed-card-load-more")

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.add_css_class("feed-card-body")
        body.set_spacing(8)

        label = Gtk.Label(label=f"📂 {remaining} older card{'s' if remaining != 1 else ''}")
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)

        btn = Gtk.Button(label="Load More")
        btn.add_css_class("feed-btn-load-more")
        btn.connect("clicked", lambda *_: self._load_more())

        body.append(label)
        body.append(btn)
        card.append(body)
        return card

    def _load_more(self) -> None:
        """Load the next PAGE_SIZE cards from backlog and prepend them."""
        if not self._backlog:
            return

        # Take next page from backlog (newest-first)
        page = self._backlog[:self.PAGE_SIZE]
        self._backlog = self._backlog[self.PAGE_SIZE:]

        # Build widgets for this page
        widgets = []
        for card in page:
            widget = build_feed_card(
                card,
                on_review=self._make_review_cb(card.card_id),
                on_accept=self._make_accept_cb(card.card_id),
                on_reject=self._make_reject_cb(card.card_id),
                on_copy=self._make_copy_cb(card),
            )
            self._card_widgets[card.card_id] = widget
            widgets.append((card.card_id, widget))

        remaining = len(self._backlog)

        def _render():
            if self._feed_tab is None:
                return

            # Remove old load-more widget
            if self._load_more_widget is not None:
                self._feed_tab.remove_card("__load_more__")

            # Prepend new cards (oldest of page first → they go above existing cards)
            for card_id, widget in widgets:
                self._feed_tab.prepend_card(widget, card_id)

            # Re-add load-more if backlog still has cards
            if remaining > 0:
                self._load_more_widget = self._build_load_more_widget(remaining)
                self._feed_tab.prepend_card(self._load_more_widget, card_id="__load_more__")
            else:
                self._load_more_widget = None

        self._GLib.idle_add(_render)

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
            accepted=accepted,  # NEW — propagate decision so badge renders (Phase 2)
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

                # Generate the commit message from the ACTUAL staged files,
                # not from card.title. card.title is user-facing text (not a
                # file path) and may not match the real diff. Same fix as
                # T2-RL2 in review_handler.
                #
                # Only catch ImportError (gitpython not installed). Other
                # exceptions are logged as warnings — the user clicked Accept
                # on a card and the card remains visible, so we don't need
                # to surface a chat message like T2-RL2 does.
                try:
                    import git as gitpython
                except ImportError:
                    staged = []
                else:
                    try:
                        repo = gitpython.Repo(project_path)
                        staged = repo.index.diff("HEAD")
                    except Exception as e:
                        _logger.warning(
                            "handle_accept: failed to read diff for %s: %s: %s",
                            project_path, type(e).__name__, e,
                        )
                        return

                if not staged:
                    # Working tree is clean — nothing to commit. Silent no-op:
                    # the user clicked Accept on a card but the underlying
                    # changes have already been accepted (or never existed).
                    # Log a warning for observability, but don't create an
                    # empty commit and don't mark the card as accepted.
                    _logger.info(
                        "handle_accept: nothing to commit for card %s (working tree clean)",
                        card_id,
                    )
                    return

                # Build a descriptive message from the actual files
                file_list = sorted({d.a_path or d.b_path for d in staged if d.a_path or d.b_path})
                if len(file_list) == 1:
                    commit_msg = f"Accept: {file_list[0]}"
                elif len(file_list) <= 3:
                    commit_msg = f"Accept: {len(file_list)} files ({', '.join(file_list)})"
                else:
                    commit_msg = f"Accept: {len(file_list)} files ({', '.join(file_list[:3])}...)"

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
            # Refresh batch accept bar (Phase 5)
            self._update_batch_bar_for_active_project()

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

                # MED-11: Validate commit_sha before git call
                if not _VALID_SHA_RE.match(sha):
                    _logger.warning(
                        "MED-11: Invalid commit SHA %r for card %s — skipping reject",
                        sha, card_id,
                    )
                    return

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
            # Refresh batch accept bar (Phase 5)
            self._update_batch_bar_for_active_project()

    def handle_batch_accept(self, card_ids: list[str]) -> None:
        """
        Accept a batch of consecutive file-change cards in one click.
        Iterates in order (top-to-bottom in the feed); each accept creates a
        git_commit card via _add_git_card() with the same flow as the singular
        handle_accept(). (Phase 5)

        Used by the batch accept bar when ≥2 file-change cards are pending.
        """
        for card_id in card_ids:
            self.handle_accept(card_id)

    def _on_batch_accept_clicked(self) -> None:
        """
        Called when user clicks the batch accept bar's "Accept All" button.
        Computes the list of consecutive pending file-change cards at the
        bottom of the feed and accepts them all. (Phase 5)
        """
        if self._feed_tab is None:
            return
        project_name = self._active_project_name
        if project_name is None:
            return
        all_cards = self.get_cards_for_project(project_name)
        if not all_cards:
            return
        actionable_types = ("diff", "file_created", "file_modified", "file_deleted")
        batch_ids: list[str] = []
        for card in all_cards:  # newest first
            if (card.card_type in actionable_types
                    and card.accepted is None
                    and card.card_id is not None):
                batch_ids.append(card.card_id)
            else:
                break
        # batch_ids is newest-first; reverse to top-to-bottom for handle_accept order
        batch_ids.reverse()
        self.handle_batch_accept(batch_ids)
        # Refresh the batch bar (count may now be 0 or 1)
        self._update_batch_bar_for_active_project()

    def _update_batch_bar_for_active_project(self, project_name: str | None = None) -> None:
        """
        Recompute the pending count for the active project and update the bar.
        (Phase 5)

        Args:
            project_name: Project to count pending cards for. If None, uses
                _active_project_name (for on_project_opened context). For
                add_card() calls, pass card_data.project_name directly.
        """
        target = project_name or self._active_project_name
        if self._feed_tab is None or target is None:
            return
        all_cards = self.get_cards_for_project(target)
        actionable_types = ("diff", "file_created", "file_modified", "file_deleted")
        count = 0
        for card in all_cards:  # newest first
            if card.card_type in actionable_types and card.accepted is None:
                count += 1
            else:
                break
        self._feed_tab.update_batch_bar(count)

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

    def add_audit_report_card(
        self,
        report: dict,
        project_name: str | None = None,
    ) -> str | None:
        """
        Construct and add a feed card for a structured audit report (SPEC-3).

        Args:
            report: dict with keys: severity, file_path, task, bug_description,
                    pattern, reviewer, target_role, project_path.
            project_name: Override project name. If None, uses report["project_path"]
                          to derive the name. If no project can be determined, returns None.

        Returns:
            card_id string on success, None if no project context available.

        Thread-safe: dispatches to main thread via GLib.idle_add() if needed.
        """
        from pathlib import Path
        from models.feed_card import FeedCardData

        severity = report.get("severity", "issue")
        icons = {"bug": "🔴", "issue": "🟡", "suggestion": "🔵"}
        icon = icons.get(severity, "⚪")

        file_path = report.get("file_path", "?")
        pattern = report.get("pattern")
        reviewer = report.get("reviewer", "unknown")
        target = report.get("target_role", "unknown")
        desc = report.get("bug_description", "")

        pattern_suffix = f" ({pattern})" if pattern else ""
        title = f"{icon} {severity.upper()}: {file_path}{pattern_suffix}"
        body = f"**{reviewer}** reviewed **{target}**: {desc}"

        resolved_project = project_name
        if not resolved_project:
            project_path = report.get("project_path")
            if project_path:
                resolved_project = Path(project_path).name

        if not resolved_project:
            _logger.warning(
                "Cannot add audit report card: no project context"
            )
            return None

        card = FeedCardData(
            card_type="audit_report",
            source="agent",
            title=title,
            body=body,
            author=reviewer,
            timestamp=datetime.now(timezone.utc),
            project_name=resolved_project,
            file_path=file_path,
            metadata={
                "severity": severity,
                "pattern": pattern,
                "target_role": target,
            },
        )
        return self.add_card(card)

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
