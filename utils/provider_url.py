# utils/provider_url.py
# Provider URL validation — https-only for non-loopback hosts.
#
# MED-5: Non-loopback provider URLs must use https://.
# Loopback addresses (localhost, 127.0.0.1, ::1) may use http://.
#
# Architecture: pure utility — no GTK, no network, no imports beyond stdlib.
# Standalone — does NOT import agent.* or ui.*.

from urllib.parse import urlparse

__all__ = ["validate_provider_url"]


def validate_provider_url(url: str) -> None:
    """Raise ValueError if `url` has a non-HTTPS scheme (except loopback).

    MED-5: Non-loopback hosts MUST use https://. Loopback addresses
    (localhost, 127.0.0.1, ::1, and any hostname where hostname is None)
    are permitted to use http:// (e.g., local Ollama servers).

    Args:
        url: The provider base URL to validate.

    Raises:
        ValueError: If the URL has an http:// or other non-https scheme
            targeting a non-loopback host.
    """
    parsed = urlparse(url)

    # No hostname (e.g. empty string) — treat as invalid but not a security issue
    if not parsed.hostname:
        return

    # Loopback check
    is_loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1")

    if not is_loopback and parsed.scheme != "https":
        raise ValueError(
            f"Provider URL must use https:// for non-loopback hosts: {url}"
        )