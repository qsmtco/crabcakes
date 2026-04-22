# ui/handlers/review_handler.py
# Review session logic — checkpoint, check changes, accept, reject.
# Coordinates git_ops, diff_parser, and GTK views.
# All GTK via GLib.idle_add(). No git calls on the main thread.

import threading
from typing import Callable

from models.review_state import ReviewState
from utils import git_ops
from utils.diff_parser import parse_diff


class ReviewHandler:
    """
    Handles review session lifecycle for project tabs.

    Args:
        GLib: gi.repository.GLib — for idle_add dispatch to main thread
        main_content: MainContent instance — for ReviewBar insertion
        project_handler: ProjectHandler — for getting project paths
        on_review_started: Callable[[str, Gtk.Widget], None] — (project_name, review_bar)
        on_review_ended: Callable[[str], None] — project_name
        on_display_card: Callable[[dict], None] — display a card in project tab chat
        on_display_text: Callable[[str], None] — display text in project tab chat
    """

    def __init__(
        self,
        *,
        GLib,
        main_content,
        project_handler,
        on_review_started: Callable,
        on_review_ended: Callable,
        on_display_card: Callable,
        on_display_text: Callable,
    ):
        self._GLib = GLib
        self._mc = main_content
        self._ph = project_handler
        self._on_review_started = on_review_started
        self._on_review_ended = on_review_ended
        self._on_display_card = on_display_card
        self._on_display_text = on_display_text

        # Per-project review states: project_name -> ReviewState
        self._states: dict[str, ReviewState] = {}

        # Chat handler reference for sending rejection messages (set via set_chat_handler)
        self._chat_handler = None

        # Gateway client for sending messages to agents (set via set_gateway_client)
        self._gw = None

    def set_chat_handler(self, chat_handler):
        """Set ChatHandler reference for rejection message sending."""
        self._chat_handler = chat_handler

    def set_gateway_client(self, gw):
        """Set GatewayClient reference for sending messages to agents."""
        self._gw = gw

    # ── Mode management ─────────────────────────────────────────────────

    def set_review_mode(self, project_name: str, mode: str) -> None:
        """Set review mode for a project. 'off' or 'review'."""
        state = self._states.get(project_name)
        if state is None:
            return
        state.review_mode = mode

        if mode == "off":
            # Remove review bar if present
            self._GLib.idle_add(lambda: self._mc.set_review_bar(None))
            self._on_review_ended(project_name)
        elif mode == "review":
            # Create and show review bar
            self._GLib.idle_add(lambda: self._show_review_bar(project_name, state))

    def get_review_mode(self, project_name: str) -> str:
        """Current review mode for a project."""
        state = self._states.get(project_name)
        return state.review_mode if state else "off"

    def _show_review_bar(self, project_name: str, state: ReviewState) -> None:
        """Create and insert the ReviewBar into MainContent."""
        from ui.views.review_bar import ReviewBar

        bar = ReviewBar(
            on_mode_changed=lambda m: self.set_review_mode(project_name, m),
            on_start_clicked=lambda: self.start_review(project_name),
            on_check_clicked=lambda: self.check_changes(project_name),
        )
        bar.set_review_mode(state.review_mode)

        # Set accept/reject callbacks
        bar.set_accept_callback(lambda: self.accept_changes(project_name, "approved"))
        bar.set_reject_callback(lambda: self.reject_changes(project_name, "rejected"))

        if state.is_active():
            bar.set_state_reviewing(state.checkpoint_sha or "")
        else:
            bar.set_state_idle()

        self._mc.set_review_bar(bar)
        self._on_review_started(project_name, bar)

    # ── Review session lifecycle ────────────────────────────────────────

    def start_review(self, project_name: str) -> None:
        """Start a review session: git add -A && git commit → checkpoint SHA."""
        state = self._states.get(project_name)
        if state is None:
            return

        if not state.can_checkpoint():
            self._GLib.idle_add(lambda: self._on_display_text(f"Cannot start review: mode={state.review_mode}, checkpoint={'exists' if state.checkpoint_sha else 'none'}"))
            return

        project_path = state.project_path

        def _do():
            # Ensure it's a git repo
            if not git_ops.is_repo(project_path):
                init_result = git_ops.init_repo(project_path)
                if not init_result.success:
                    self._GLib.idle_add(lambda: self._on_display_text(f"Failed to init git repo: {init_result.error}"))
                    return

            # Stage all
            stage_result = git_ops.stage_all(project_path)
            if not stage_result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to stage files: {stage_result.error}"))
                return

            # Commit checkpoint
            commit_result = git_ops.commit(project_path, "[review] checkpoint")
            if not commit_result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to create checkpoint: {commit_result.error}"))
                return

            sha = commit_result.sha

            def _update_state():
                state.checkpoint_sha = sha
                state.is_dirty = False
                state.last_check_files = []
                bar = self._mc.get_review_bar()
                if bar is not None:
                    bar.set_state_reviewing(sha)
                    bar.set_loading(False)
                self._on_display_text(f"🔍 Review session started — checkpoint {sha[:7]}")

            self._GLib.idle_add(_update_state)

        threading.Thread(target=_do, daemon=True).start()

    def check_changes(self, project_name: str) -> None:
        """Check what changed since checkpoint: git diff <sha>."""
        state = self._states.get(project_name)
        if state is None:
            return

        if not state.is_active():
            self._GLib.idle_add(lambda: self._on_display_text("No active review session. Use `review` to start one."))
            return

        project_path = state.project_path
        sha = state.checkpoint_sha

        def _do():
            diff_result = git_ops.diff_against(project_path, sha)
            if not diff_result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to diff: {diff_result.error}"))
                return

            parsed = parse_diff(diff_result.stdout)

            if not parsed.files:
                self._GLib.idle_add(lambda: self._on_display_text("No changes detected since checkpoint."))
                return

            def _update_ui():
                state.last_check_files = [f.display_path for f in parsed.files]
                state.is_dirty = True
                bar = self._mc.get_review_bar()
                if bar:
                    bar.set_state_has_changes(len(parsed.files), parsed.total_additions, parsed.total_deletions)
                    bar.set_loading(False)

                # Display summary card
                self._on_display_card({
                    "type": "diff_summary",
                    "parsed_diff": parsed,
                })

                # Display per-file diff cards
                for file_diff in parsed.files:
                    self._on_display_card({
                        "type": "diff_file",
                        "file_diff": file_diff,
                    })

            self._GLib.idle_add(_update_ui)

        threading.Thread(target=_do, daemon=True).start()

    def accept_changes(self, project_name: str, message: str) -> None:
        """Accept all changes: git add -A && git commit -m <message>."""
        state = self._states.get(project_name)
        if state is None:
            return

        project_path = state.project_path
        checkpoint_sha = state.checkpoint_sha

        def _do():
            # Stage all
            stage_result = git_ops.stage_all(project_path)
            if not stage_result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to stage: {stage_result.error}"))
                return

            # Commit
            full_message = f"[review] accepted: {message}"
            commit_result = git_ops.commit(project_path, full_message)
            if not commit_result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to commit: {commit_result.error}"))
                return

            def _update_state():
                state.checkpoint_sha = None
                state.is_dirty = False
                state.last_check_files = []
                bar = self._mc.get_review_bar()
                if bar:
                    bar.set_state_idle()
                    bar.set_loading(False)
                self._on_review_ended(project_name)
                self._on_display_text(f"✅ Changes accepted and committed as: {message}")

            self._GLib.idle_add(_update_state)

        threading.Thread(target=_do, daemon=True).start()

    def reject_changes(self, project_name: str, reason: str) -> None:
        """Reject all changes: git checkout <sha> -- ."""
        state = self._states.get(project_name)
        if state is None:
            return

        if not state.is_active():
            self._GLib.idle_add(lambda: self._on_display_text("No active review session to reject."))
            return

        project_path = state.project_path
        sha = state.checkpoint_sha

        def _do():
            # Revert all files to checkpoint
            result = git_ops.checkout_paths(project_path, sha, ["."])
            if not result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to revert: {result.error}"))
                return

            # Send rejection message to all project members
            self._send_rejection_messages(project_name, reason, sha)

            def _update_state():
                state.checkpoint_sha = None
                state.is_dirty = False
                state.last_check_files = []
                bar = self._mc.get_review_bar()
                if bar:
                    bar.set_state_idle()
                    bar.set_loading(False)
                self._on_review_ended(project_name)
                self._on_display_text(f"❌ Changes rejected — files reverted to checkpoint {sha[:7]}")

            self._GLib.idle_add(_update_state)

        threading.Thread(target=_do, daemon=True).start()

    def reject_file(self, project_name: str, file_path: str) -> None:
        """Reject a single file: git checkout <sha> -- <file_path>."""
        state = self._states.get(project_name)
        if state is None or not state.is_active():
            return

        project_path = state.project_path
        sha = state.checkpoint_sha

        def _do():
            result = git_ops.checkout_paths(project_path, sha, [file_path])
            if not result.success:
                self._GLib.idle_add(lambda: self._on_display_text(f"Failed to revert {file_path}: {result.error}"))
                return

            self._GLib.idle_add(lambda: self._on_display_text(f"↩ {file_path} reverted to checkpoint"))

        threading.Thread(target=_do, daemon=True).start()

    def _send_rejection_messages(self, project_name: str, reason: str, sha: str) -> None:
        """Send rejection reason to all project members via gateway."""
        if self._gw is None:
            return
        members = self._ph.get_project_members(project_name)
        message = f"Changes rejected: {reason}. Files reverted to checkpoint {sha[:7]}."
        for member in members:
            try:
                self._gw.send_message(member, message)
            except Exception:
                pass  # Don't fail the whole operation if one message fails

    def get_state(self, project_name: str) -> ReviewState | None:
        """Get current review state for a project."""
        return self._states.get(project_name)

    # ── Project lifecycle hooks ─────────────────────────────────────────

    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """Called when a project tab opens. Initializes ReviewState."""
        if project_name not in self._states:
            self._states[project_name] = ReviewState(
                project_path=project_path,
                review_mode="off",
            )
        else:
            # Update project path in case it changed
            self._states[project_name].project_path = project_path

    def on_project_closed(self, project_name: str) -> None:
        """Called when a project tab closes. Cleans up ReviewState."""
        self._states.pop(project_name, None)

    def on_project_members_changed(self, project_name: str, members: list[str]) -> None:
        """Called when project membership changes. Updates rejection message targets."""
        # State is already keyed by project_name; no action needed here
        pass
