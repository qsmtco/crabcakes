# ui/handlers/auxilium_wizard_handler.py
# Auxilium first-run wizard — business logic state machine.
#
# Owns: wizard state transitions, install check, gateway probe, provider config write.
# Does NOT own: GTK widgets, other handlers, agent runtime.
#
# Architecture: pure Python — no GTK imports at module level, no ui/ imports,
# no gateway/ imports, no subprocess. Follows §8.6 handler pattern and §5 callback
# pattern from ARCHITECTURE.md.
#
# Thread safety: all methods synchronous except advance_to_gateway(), which
# spawns a daemon thread for the WebSocket probe. The view (Phase 2) polls
# get_state() via a GTK timer to detect completion — no GLib coupling here.

from __future__ import annotations

import copy
import importlib.util
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ── State machine types ──────────────────────────────────────────────────────


class WizardStep(str, Enum):
    """Wizard state-machine steps, advanced sequentially."""
    INSTALL_CHECK = "install_check"
    GATEWAY_CHECK = "gateway_check"
    PROVIDER_PICK = "provider_pick"
    WRITING_CONFIG = "writing_config"
    DONE = "done"


@dataclass
class WizardState:
    """Snapshot of wizard state — consumed by the view to render the current step."""
    step: WizardStep = WizardStep.INSTALL_CHECK
    install_check: dict = field(default_factory=dict)
    gateway_check: dict = field(default_factory=dict)
    provider_pick: dict = field(default_factory=dict)


# ── Valid provider choices ───────────────────────────────────────────────────

_VALID_CHOICES = {"openrouter_free", "ollama", "bring_your_own"}


# ── Helper: wizard needed? ─────────────────────────────────────────────────────

def is_auxilium_wizard_needed(config_dir: Path) -> bool:
    """
    Return True if the user has not yet configured a provider
    and the Auxilium first-run wizard should be shown.

    'Not yet configured' = providers.yaml is missing/empty AND
    no auxilium.yaml agent config exists (AC-T1-7: existing user
    with auxilium.yaml already configured should NOT see the wizard).
    """
    # AC-T1-7: existing user with auxilium.yaml configured → skip wizard
    auxilium_yaml = config_dir / "agents" / "auxilium.yaml"
    if auxilium_yaml.is_file():
        return False

    providers_yaml = config_dir / "providers.yaml"
    if not providers_yaml.is_file():
        return True
    # File exists — check if it has any real providers
    try:
        from utils.providers_store import load_providers
        providers = load_providers()
        return len(providers) == 0
    except Exception:
        return True  # If we can't read, assume first-run


# ── Handler ──────────────────────────────────────────────────────────────────


class AuxiliumWizardHandler:
    """
    Business-logic state machine for the Auxilium first-run wizard.

    Drives the wizard through 5 steps: install check → gateway probe →
    provider selection → config write → done. The view (Phase 2) calls
    these methods in response to user actions and polls get_state() to render.

    Args:
        config_dir: Path to CrabCakes config directory (e.g. ~/.config/crabcakes/).
        on_complete: Fired when the wizard finishes successfully (config written).
        on_error: Fired on unrecoverable error with a user-facing message.
        on_step_changed: Optional callback fired on every state transition.
            NOTE: Because this handler is GTK-free, this callback fires from
            whatever thread triggers the transition. For the gateway probe
            (background thread), the view must poll get_state() — see the
            module docstring.
    """

    def __init__(
        self,
        config_dir: Path,
        on_complete: Callable[[], None],
        on_error: Callable[[str], None],
        on_step_changed: Callable[[WizardState], None] | None = None,
    ):
        self._config_dir = config_dir
        self._on_complete = on_complete
        self._on_error = on_error
        self._on_step_changed = on_step_changed
        self._state = WizardState()
        self._state_lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────

    def get_state(self) -> WizardState:
        """Return a deep copy of the current wizard state.

        Used by the view to render. Returns a deep copy so callers cannot
        mutate the handler's internal state.
        """
        with self._state_lock:
            return copy.deepcopy(self._state)

    def start(self) -> None:
        """
        Begin the wizard. Synchronously runs the install check (no I/O —
        just importlib probe + sys info), sets state, fires on_step_changed.
        """
        self._state.install_check = self._run_install_check()
        self._state.step = WizardStep.INSTALL_CHECK
        self._fire_step_changed()

    def advance_to_gateway(self) -> None:
        """
        Transition from INSTALL_CHECK to GATEWAY_CHECK. Starts a background
        daemon thread that probes the gateway WebSocket with a 3-second timeout.
        The view polls get_state() to detect completion — the thread does NOT
        call on_step_changed directly (GTK-thread safety without GLib coupling).
        """
        self._state.step = WizardStep.GATEWAY_CHECK
        self._state.gateway_check = {"ok": False, "url": "", "error": "Probing..."}
        self._fire_step_changed()

        thread = threading.Thread(
            target=self._probe_gateway,
            daemon=True,
            name="auxilium-wizard-gateway",
        )
        thread.start()

    def advance_to_provider(self) -> None:
        """
        Transition from GATEWAY_CHECK to PROVIDER_PICK. Synchronous, no I/O.
        """
        self._state.step = WizardStep.PROVIDER_PICK
        self._fire_step_changed()

    def set_provider_choice(
        self,
        choice: str,
        provider: str,
        model: str,
        api_key: str | None,
    ) -> None:
        """
        Validate the provider selection and write providers.yaml.

        For Ollama: api_key is set to "ollama" (placeholder — Ollama doesn't
        enforce keys). For other choices, the caller must supply a real key.

        On success: fires on_complete (terminates the wizard).
        On error: fires on_error(msg) and stays on PROVIDER_PICK.
        """
        # 1. Validate choice
        if choice not in _VALID_CHOICES:
            self._on_error(
                f"Invalid provider choice '{choice}'. "
                f"Must be one of: {', '.join(sorted(_VALID_CHOICES))}"
            )
            return

        # 2. Ollama doesn't need a key
        if choice == "ollama":
            api_key = "ollama"

        # 3. Ensure api_key is a string (None → empty for bring_your_own check)
        effective_key = api_key or ""
        if choice != "ollama" and not effective_key:
            self._on_error("An API key is required for this provider choice.")
            return

        self._state.step = WizardStep.WRITING_CONFIG

        try:
            from models.providers import ProviderConfig
            from utils.providers_store import save_providers

            pc = self._build_provider_config(
                choice, provider, model, effective_key
            )
            save_providers([pc])

            self._state.provider_pick = {
                "choice": choice,
                "provider": pc.name,
                "model": pc.default_model,
                "api_key": effective_key,
            }
            self._state.step = WizardStep.DONE
            self._fire_step_changed()
            self._on_complete()

        except Exception as e:
            logger.exception("Failed to write provider config")
            self._state.step = WizardStep.PROVIDER_PICK
            self._on_error(f"Failed to save provider configuration: {e}")

    # ── Internal: install check ──────────────────────────────────────────

    @staticmethod
    def _run_install_check() -> dict:
        """
        Detect platform, Python version, and required/optional dependencies.
        Pure stdlib — no I/O, no subprocess.
        """
        platform = sys.platform  # "linux", "darwin", "win32"
        python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        def _has(mod: str) -> bool:
            try:
                return importlib.util.find_spec(mod) is not None
            except (ModuleNotFoundError, ValueError):
                return False

        gtk4 = _has("gi")
        websockets = _has("websockets")
        cryptography = _has("cryptography")

        missing: list[str] = []
        if not gtk4:
            missing.append("gi (PyGObject + GTK4)")
        if not websockets:
            missing.append("websockets")

        warnings: list[str] = []
        if not cryptography:
            warnings.append("cryptography (optional — for encrypted connections)")

        ok = len(missing) == 0

        return {
            "ok": ok,
            "platform": platform,
            "python": python,
            "gtk4": gtk4,
            "websockets": websockets,
            "missing": missing,
            "warnings": warnings,
        }

    # ── Internal: gateway probe ──────────────────────────────────────────

    def _probe_gateway(self) -> None:
        """
        Background thread: open a WebSocket to the gateway with 3s timeout.
        Updates self._state.gateway_check on completion. Does NOT fire
        on_step_changed — the view polls get_state() via timer.
        """
        url = self._read_gateway_url()

        try:
            import websockets.sync.client as ws_sync
        except ImportError:
            with self._state_lock:
                self._state.gateway_check = {
                    "ok": False,
                    "url": url,
                    "error": "websockets module not installed",
                }
            return

        try:
            with ws_sync.connect(url, open_timeout=3.0, close_timeout=1.0) as _ws:
                # Connection succeeded — gateway is reachable
                pass
            with self._state_lock:
                self._state.gateway_check = {"ok": True, "url": url, "error": ""}
        except TimeoutError:
            with self._state_lock:
                self._state.gateway_check = {
                    "ok": False,
                    "url": url,
                    "error": f"Connection timed out after 3s",
                }
        except OSError as e:
            with self._state_lock:
                self._state.gateway_check = {
                    "ok": False,
                    "url": url,
                    "error": f"Connection refused: {e}",
                }
        except Exception as e:
            with self._state_lock:
                self._state.gateway_check = {
                    "ok": False,
                    "url": url,
                    "error": f"Unexpected error: {e}",
                }

    def _read_gateway_url(self) -> str:
        """
        Read gateway URL from config. Checks self._config_dir / agent.json
        FIRST (the handler's own config context), then falls back to
        utils.config.get_gateway_url() (global default), then defaults
        to ws://localhost:18789.
        """
        # 1. Check handler's config_dir for agent.json
        agent_json = self._config_dir / "agent.json"
        if agent_json.is_file():
            try:
                with open(agent_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                url = data.get("gateway_url")
                if url:
                    return url
            except (OSError, json.JSONDecodeError):
                pass

        # 2. Fall back to global config
        try:
            from utils.config import get_gateway_url
            return get_gateway_url()
        except Exception:
            pass

        return "ws://localhost:18789"

    # ── Internal: provider config builder ────────────────────────────────

    @staticmethod
    def _build_provider_config(
        choice: str,
        provider: str,
        model: str,
        api_key: str,
    ) -> "ProviderConfig":
        """
        Build a ProviderConfig based on the wizard choice.
        Verified against models/providers.py ProviderConfig dataclass.
        """
        from models.providers import ProviderConfig

        if choice == "openrouter_free":
            return ProviderConfig(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                default_model=model or "openrouter/free",
                caller="openrouter",
                supports_tools=True,
                supports_streaming=True,
                max_tokens=128_000,
            )

        elif choice == "ollama":
            return ProviderConfig(
                name="ollama",
                base_url="http://localhost:11434/v1",
                api_key="ollama",
                default_model=model or "llama3.2:7b",
                caller="openai",  # Ollama uses OpenAI-compatible API
                supports_tools=True,
                supports_streaming=True,
                max_tokens=32_000,
            )

        elif choice == "bring_your_own":
            # Determine caller from provider name
            caller_map = {
                "openai": "openai",
                "anthropic": "anthropic",
                "google": "openai",  # Gemini uses OpenAI-compatible endpoint
                "google_gemini": "openai",
                "minimax": "minimax",
                "zai": "zai",
            }
            caller = caller_map.get(provider.lower(), "openai")

            # Build base URLs for known providers
            base_url_map = {
                "openai": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com/v1",
                "google": "https://generativelanguage.googleapis.com/v1beta/openai",
                "google_gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
                "minimax": "https://api.minimax.chat/v1",
                "zai": "https://api.z.ai/api/paas/v4",
            }
            base_url = base_url_map.get(provider.lower(), f"https://api.{provider}.com/v1")

            # Per-provider default models for BYOK when model is empty
            default_model_map = {
                "openai": "gpt-4o-mini",
                "anthropic": "claude-3-5-haiku-20241022",
                "google": "gemini-2.0-flash",
                "google_gemini": "gemini-2.0-flash",
                "minimax": "MiniMax-M3",
                "zai": "glm-4-flash",
            }
            resolved_model = model or default_model_map.get(provider.lower(), "")

            return ProviderConfig(
                name=provider,
                base_url=base_url,
                api_key=api_key,
                default_model=resolved_model,
                caller=caller,
                supports_tools=True,
                supports_streaming=True,
                max_tokens=128_000,
            )

        # Should never reach here — validated in set_provider_choice
        raise ValueError(f"Unknown provider choice: {choice}")

    # ── Internal: callback dispatch ──────────────────────────────────────

    def _fire_step_changed(self) -> None:
        """Fire on_step_changed callback if registered."""
        if self._on_step_changed is not None:
            self._on_step_changed(copy.deepcopy(self._state))
