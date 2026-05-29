# utils/config.py — Centralized configuration path resolution
#
# Manifest: reads environment variables only, no file I/O, no network
# Single source of truth for all config and data directory paths.
#
# Architecture: this module is intentionally dependency-free. No GTK, no network.
# Any package that needs a config path should call helpers from here instead
# of computing paths inline. If the config root location ever changes, update
# this module and all callers are automatically correct.

import os


def get_config_dir() -> str:
    """Return the CrabCakes config directory.

    Respects $XDG_CONFIG_HOME if set, otherwise ~/.config/crabcakes.
    Does NOT create the directory.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return os.path.join(xdg, "crabcakes")
    return os.path.join(os.path.expanduser("~"), ".config", "crabcakes")


def get_config_file() -> str:
    """Return path to config.json (API keys, base URLs, etc.)."""
    return os.path.join(get_config_dir(), "config.json")


def get_projects_config_dir() -> str:
    """Return path to projects config directory (members.json files live here).

    Located inside the CrabCakes config dir, NOT inside the browsable projects root.
    """
    return os.path.join(get_config_dir(), "projects")


def get_projects_dir() -> str:
    """Return the browsable projects directory (actual project folders).

    Controlled by $CRABCAKES_PROJECTS_DIR, defaults to ~/projects.
    This is the root that the FileTree widget navigates.
    """
    return os.environ.get(
        "CRABCAKES_PROJECTS_DIR",
        os.path.join(os.path.expanduser("~"), "projects"),
    )


def get_gateway_url() -> str:
    """Return the OpenClaw gateway WebSocket URL.

    Controlled by $CRABCAKES_GATEWAY_URL, defaults to ws://localhost:18789.
    """
    return os.environ.get("CRABCAKES_GATEWAY_URL", "ws://localhost:18789")


def get_identity_dir() -> str:
    """Return the OpenClaw device identity directory.

    This is an OpenClaw-owned path, not a CrabCakes path.
    Defaults to ~/.openclaw/identity/.
    """
    return os.path.join(os.path.expanduser("~"), ".openclaw", "identity")


# Command system configuration
# Backtick prefix — triggers command parsing in ChatHandler.on_send().
# Zero collision with gateway commands (/approve, /status, etc.) which use /.
COMMAND_PREFIX = "/"

