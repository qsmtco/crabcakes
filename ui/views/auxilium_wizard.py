# ui/views/auxilium_wizard.py
# Auxilium first-run wizard view — GTK4 widget embedded in the Auxilium chat tab.
#
# Owns: rendering of 3 step frames (install check, gateway check, provider picker).
# Does NOT own: business logic (handler does install checks, gateway probes, config writes).
#
# Architecture: PURE VIEW per §8.2 and §5 callback pattern. No imports of other
# ui/views/* or ui/handlers/* — the handler is received in __init__.
# Embeds as a Gtk.Box (not Gtk.Window) in the Auxilium chat tab's chat_box,
# replacing the welcome bubble.

from __future__ import annotations

import logging
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

logger = logging.getLogger(__name__)

# Stack page names — match WizardStep values
_PAGE_INSTALL = "install_check"
_PAGE_GATEWAY = "gateway_check"
_PAGE_PROVIDER = "provider_pick"


class AuxiliumWizard(Gtk.Box):
    """
    GTK4 view for the Auxilium first-run wizard.

    Embeds in the Auxilium chat tab (replaces the welcome bubble when
    the user has no provider configured). Renders 3 step frames in a
    Gtk.Stack, dispatches user actions to the handler, and polls the
    handler for gateway probe completion via GLib.timeout_add.

    Args:
        handler: AuxiliumWizardHandler instance (from Phase 1).
        on_install_check_complete: Fired when user clicks Continue on step 1.
        on_gateway_check_complete: Fired when user clicks Continue on step 2.
        on_provider_selected: Fired when user clicks Finish on step 3.
    """

    def __init__(
        self,
        handler,
        on_install_check_complete: Callable[[], None],
        on_gateway_check_complete: Callable[[], None],
        on_provider_selected: Callable[[], None],
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("auxilium-wizard")
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_spacing(16)

        self._handler = handler
        self._on_install_check_complete = on_install_check_complete
        self._on_gateway_check_complete = on_gateway_check_complete
        self._on_provider_selected = on_provider_selected

        # Gateway poll timer source ID (for cleanup)
        self._gateway_poll_id: int | None = None

        # Provider picker form state
        self._selected_choice: str = "openrouter_free"
        self._provider_key_entry: Gtk.Entry | None = None
        self._provider_dropdown: Gtk.DropDown | None = None
        self._provider_key_entry: Gtk.Entry | None = None
        self._provider_dropdown: Gtk.DropDown | None = None

        # ── Step indicator ──────────────────────────────────────────────
        self._step_dots: list[Gtk.Widget] = []
        indicator = self._build_step_indicator()
        self.append(indicator)

        # ── Stack with 3 frames ──────────────────────────────────────────
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.add_named(self._build_install_frame(), _PAGE_INSTALL)
        self._stack.add_named(self._build_gateway_frame(), _PAGE_GATEWAY)
        self._stack.add_named(self._build_provider_frame(), _PAGE_PROVIDER)
        self.append(self._stack)

        # ── Button bar ───────────────────────────────────────────────────
        self._btn_back = Gtk.Button(label="Back")
        self._btn_back.set_visible(False)
        self._btn_back.connect("clicked", lambda *_: self._go_back())

        self._btn_continue = Gtk.Button(label="Continue")
        self._btn_continue.add_css_class("suggested-action")
        self._btn_continue.connect("clicked", lambda *_: self._on_continue_clicked())

        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        btn_bar.set_spacing(12)
        btn_bar.set_halign(Gtk.Align.END)
        btn_bar.append(self._btn_back)
        btn_bar.append(self._btn_continue)
        self.append(btn_bar)

        # ── Initial render from handler state ────────────────────────────
        self._sync_to_handler_state()

    # ── Public property ──────────────────────────────────────────────────

    @property
    def current_step(self) -> str:
        """Return the current step name (matches WizardStep values)."""
        return self._stack.get_visible_child_name() or _PAGE_INSTALL

    # ── Step indicator ───────────────────────────────────────────────────

    def _build_step_indicator(self) -> Gtk.Box:
        """Build the 3-dot step indicator at the top."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.set_halign(Gtk.Align.CENTER)
        box.set_spacing(8)

        for i in range(3):
            dot = Gtk.Label(label="●")
            dot.add_css_class("auxilium-wizard-step-dot")
            self._step_dots.append(dot)
            box.append(dot)

        return box

    def _update_step_indicator(self, step_index: int) -> None:
        """Update which dot is active/done."""
        for i, dot in enumerate(self._step_dots):
            dot.remove_css_class("auxilium-wizard-step-dot-active")
            dot.remove_css_class("auxilium-wizard-step-dot-done")
            if i < step_index:
                dot.add_css_class("auxilium-wizard-step-dot-done")
            elif i == step_index:
                dot.add_css_class("auxilium-wizard-step-dot-active")

    # ── Frame 1: Install check ───────────────────────────────────────────

    def _build_install_frame(self) -> Gtk.Box:
        """Build the install check frame."""
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("auxilium-wizard-frame")
        frame.set_spacing(8)

        title = Gtk.Label(label="Environment Check")
        title.add_css_class("auxilium-wizard-title")
        title.set_halign(Gtk.Align.START)
        frame.append(title)

        self._install_info = Gtk.Label(label="Checking...")
        self._install_info.set_halign(Gtk.Align.START)
        self._install_info.set_wrap(True)
        frame.append(self._install_info)

        return frame

    def _render_install_check(self, info: dict) -> None:
        """Populate the install check frame with results."""
        lines = []
        lines.append(f"Platform: {info.get('platform', '?')}")
        lines.append(f"Python: {info.get('python', '?')}")
        lines.append(f"GTK4: {'✓' if info.get('gtk4') else '✗'}")
        lines.append(f"WebSockets: {'✓' if info.get('websockets') else '✗'}")

        missing = info.get("missing", [])
        if missing:
            lines.append(f"\nMissing: {', '.join(missing)}")

        warnings = info.get("warnings", [])
        if warnings:
            lines.append(f"Warnings: {', '.join(warnings)}")

        lines.append(f"\nStatus: {'✓ All good' if info.get('ok') else '⚠ Issues found'}")
        self._install_info.set_text("\n".join(lines))

    # ── Frame 2: Gateway check ───────────────────────────────────────────

    def _build_gateway_frame(self) -> Gtk.Box:
        """Build the gateway check frame."""
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("auxilium-wizard-frame")
        frame.set_spacing(8)

        title = Gtk.Label(label="Gateway Connection")
        title.add_css_class("auxilium-wizard-title")
        title.set_halign(Gtk.Align.START)
        frame.append(title)

        self._gateway_spinner = Gtk.Spinner()
        self._gateway_spinner.set_visible(False)
        frame.append(self._gateway_spinner)

        self._gateway_info = Gtk.Label(label="Checking gateway...")
        self._gateway_info.set_halign(Gtk.Align.START)
        self._gateway_info.set_wrap(True)
        frame.append(self._gateway_info)

        return frame

    def _start_gateway_poll(self) -> None:
        """Start polling handler for gateway probe completion."""
        # Show spinner
        self._gateway_spinner.start()
        self._gateway_spinner.set_visible(True)
        self._gateway_info.set_text("Probing gateway...")

        # Clean up any existing timer
        if self._gateway_poll_id is not None:
            GLib.source_remove(self._gateway_poll_id)

        self._gateway_poll_id = GLib.timeout_add(250, self._poll_gateway)

    def _poll_gateway(self) -> bool:
        """
        Timer callback: check if gateway probe finished.
        Returns True to keep polling, False to stop.
        """
        state = self._handler.get_state()
        gw = state.gateway_check

        # Check if the probe has completed (error is non-empty and not "Probing...")
        if gw.get("error") == "Probing..." or (not gw.get("error") and not gw.get("ok") and not gw):
            return True  # still probing

        # Probe finished — update UI
        self._gateway_spinner.stop()
        self._gateway_spinner.set_visible(False)

        if gw.get("ok"):
            self._gateway_info.set_text(f"✓ Gateway reachable at {gw.get('url', '?')}")
        else:
            error = gw.get("error", "Unknown error")
            self._gateway_info.set_text(f"⚠ Gateway check failed: {error}")

        self._gateway_poll_id = None
        return False  # stop polling

    # ── Frame 3: Provider picker ─────────────────────────────────────────

    def _build_provider_frame(self) -> Gtk.Box:
        """Build the provider picker frame with 3 radio choices."""
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("auxilium-wizard-frame")
        frame.set_spacing(8)

        title = Gtk.Label(label="Choose a Provider")
        title.add_css_class("auxilium-wizard-title")
        title.set_halign(Gtk.Align.START)
        frame.append(title)

        subtitle = Gtk.Label(label="Pick how Auxilium should connect to an LLM.")
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        frame.append(subtitle)

        # Radio group
        self._radio_openrouter = Gtk.CheckButton(label="OpenRouter free tier (online, needs key)")
        self._radio_openrouter.set_active(True)
        self._radio_openrouter.connect("toggled", lambda _: self._on_choice_changed("openrouter_free"))

        self._radio_ollama = Gtk.CheckButton(label="Ollama (local, free, offline)")
        self._radio_ollama.set_group(self._radio_openrouter)
        self._radio_ollama.connect("toggled", lambda _: self._on_choice_changed("ollama"))

        self._radio_byok = Gtk.CheckButton(label="Bring your own key")
        self._radio_byok.set_group(self._radio_openrouter)
        self._radio_byok.connect("toggled", lambda _: self._on_choice_changed("bring_your_own"))

        frame.append(self._radio_openrouter)
        frame.append(self._radio_ollama)
        frame.append(self._radio_byok)

        # API key entry (shown for openrouter_free and bring_your_own)
        self._key_label = Gtk.Label(label="API Key:")
        self._key_label.set_halign(Gtk.Align.START)
        self._key_label.set_margin_top(8)
        frame.append(self._key_label)

        self._provider_key_entry = Gtk.Entry()
        self._provider_key_entry.set_placeholder_text("Paste your API key")
        self._provider_key_entry.set_visibility(False)  # password mode
        self._provider_key_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        frame.append(self._provider_key_entry)

        # Provider dropdown (shown for bring_your_own only)
        self._provider_label = Gtk.Label(label="Provider:")
        self._provider_label.set_halign(Gtk.Align.START)
        self._provider_label.set_margin_top(8)
        frame.append(self._provider_label)

        self._provider_dropdown = Gtk.DropDown.new_from_strings(
            ["openai", "anthropic", "google"]
        )
        frame.append(self._provider_dropdown)

        # Initial visibility
        self._update_provider_form()

        return frame

    def _on_choice_changed(self, choice: str) -> None:
        """Radio button toggled — update form visibility."""
        self._selected_choice = choice
        self._update_provider_form()

    def _update_provider_form(self) -> None:
        """Show/hide form fields based on selected provider choice."""
        is_openrouter = self._selected_choice == "openrouter_free"
        is_byok = self._selected_choice == "bring_your_own"
        is_ollama = self._selected_choice == "ollama"

        # API key field: shown for openrouter and byok, hidden for ollama
        self._key_label.set_visible(not is_ollama)
        self._provider_key_entry.set_visible(not is_ollama)

        # Provider dropdown: shown only for byok
        self._provider_label.set_visible(is_byok)
        self._provider_dropdown.set_visible(is_byok)

        # Update key placeholder
        if is_openrouter:
            self._provider_key_entry.set_placeholder_text("Paste your OpenRouter API key")
        elif is_byok:
            self._provider_key_entry.set_placeholder_text("Paste your API key")

    # ── Navigation ───────────────────────────────────────────────────────

    def _sync_to_handler_state(self) -> None:
        """Read handler state and render the appropriate frame."""
        state = self._handler.get_state()

        if state.step.value == "install_check" or not state.install_check:
            self._show_frame(0)
            if state.install_check:
                self._render_install_check(state.install_check)
        elif state.step.value == "gateway_check":
            self._show_frame(1)
            # Check if gateway result is already populated
            gw = state.gateway_check
            if gw.get("error") and gw.get("error") != "Probing...":
                # Already done
                self._gateway_spinner.stop()
                self._gateway_spinner.set_visible(False)
                if gw.get("ok"):
                    self._gateway_info.set_text(f"✓ Gateway reachable at {gw.get('url', '?')}")
                else:
                    self._gateway_info.set_text(f"⚠ Gateway check failed: {gw.get('error', '?')}")
            else:
                self._start_gateway_poll()
        elif state.step.value in ("provider_pick", "writing_config", "done"):
            self._show_frame(2)

    def _show_frame(self, step_index: int) -> None:
        """Switch the stack to the given frame and update indicator/buttons."""
        page_names = [_PAGE_INSTALL, _PAGE_GATEWAY, _PAGE_PROVIDER]
        self._stack.set_visible_child_name(page_names[step_index])
        self._update_step_indicator(step_index)

        # Back button: hidden on first frame
        self._btn_back.set_visible(step_index > 0)

        # Continue button label
        labels = ["Continue", "Continue", "Finish"]
        self._btn_continue.set_label(labels[step_index])

    def _go_back(self) -> None:
        """Go back one frame (install ← gateway ← provider)."""
        current = self._get_frame_index()
        if current > 0:
            self._show_frame(current - 1)

    def _get_frame_index(self) -> int:
        """Return the current frame index (0-2)."""
        name = self._stack.get_visible_child_name()
        if name == _PAGE_GATEWAY:
            return 1
        if name == _PAGE_PROVIDER:
            return 2
        return 0

    def _on_continue_clicked(self) -> None:
        """Continue/Finish button clicked — dispatch based on current frame."""
        idx = self._get_frame_index()

        if idx == 0:
            # Install check → advance to gateway
            self._on_install_check_complete()
        elif idx == 1:
            # Gateway check → advance to provider
            self._on_gateway_check_complete()
        elif idx == 2:
            # Provider pick → finish
            self._on_finish_clicked()
            return  # finish has its own validation; don't re-sync mid-validation

        # Re-sync view to handler state after a state transition.
        # The handler has now advanced; switch the visible frame to match.
        self._sync_to_handler_state()

    def _on_finish_clicked(self) -> None:
        """Finish button: validate form and call handler.set_provider_choice."""
        choice = self._selected_choice

        if choice == "ollama":
            provider = "ollama"
            model = "llama3.2:7b"
            api_key = None
        elif choice == "openrouter_free":
            provider = "openrouter"
            model = "openrouter/free"
            api_key = self._provider_key_entry.get_text().strip()
            if not api_key:
                self._provider_key_entry.grab_focus()
                return
        else:  # bring_your_own
            selected = self._provider_dropdown.get_selected_item()
            provider = selected.get_string() if selected else "openai"
            model = ""
            api_key = self._provider_key_entry.get_text().strip()
            if not api_key:
                self._provider_key_entry.grab_focus()
                return

        self._handler.set_provider_choice(choice, provider, model, api_key)
        self._on_provider_selected()

    # ── Cleanup ──────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Remove the gateway poll timer. Call before destroying the widget."""
        if self._gateway_poll_id is not None:
            GLib.source_remove(self._gateway_poll_id)
            self._gateway_poll_id = None
        self._gateway_spinner.stop()
