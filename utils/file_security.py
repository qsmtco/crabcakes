# utils/file_security.py
# Shared helpers for secure file permission validation.
#
# MED-6: Validate config file ownership and permissions.
#
# Architecture: pure utility — no GTK, no network, no imports beyond stdlib.
# Standalone — does NOT import agent.* or ui.*.

import os

__all__ = ["assert_secure_file"]


def assert_secure_file(path: str, expected_owner: bool = True) -> None:
    """Raise PermissionError if file has unsafe permissions or wrong owner.

    MED-6: Config files (mcp-servers.json, config.json, device-auth.json)
    must be owned by the current user and not world/group-writable.

    Args:
        path: Absolute path to the file to check.
        expected_owner: If True (default), also check that the file is owned
            by the current user.

    Raises:
        PermissionError: If the file has unsafe permissions or wrong owner.
        FileNotFoundError: If the file does not exist.
    """
    st = os.stat(path)
    if expected_owner and st.st_uid != os.getuid():
        raise PermissionError(
            f"{path} not owned by current user: uid={st.st_uid}"
        )
    if st.st_mode & 0o077:
        raise PermissionError(
            f"{path} has unsafe permissions: {oct(st.st_mode)}"
        )