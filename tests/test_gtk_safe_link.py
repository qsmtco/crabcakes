# tests/test_gtk_safe_link.py
# Unit tests for HIGH-6 link-scheme guard.
#
# Tests the pure-Python scheme check (utils.gtk_safe_link._is_safe_scheme +
# on_activate_link). The Gtk widget factory is tested separately via the
# integration tests in tests/test_chat_render_handler.py.

from utils.gtk_safe_link import (
    _is_safe_scheme,
    on_activate_link,
    _ALLOWED_LINK_SCHEMES,
)


class TestIsSafeScheme:
    def test_https_allowed(self):
        assert _is_safe_scheme("https://example.com/page") is True

    def test_http_allowed(self):
        assert _is_safe_scheme("http://example.com/") is True

    def test_mailto_allowed(self):
        assert _is_safe_scheme("mailto:user@example.com") is True

    def test_https_with_query_and_fragment(self):
        assert _is_safe_scheme("https://example.com/a?b=c#d") is True

    def test_javascript_blocked(self):
        assert _is_safe_scheme("javascript:alert(1)") is False

    def test_data_blocked(self):
        assert _is_safe_scheme("data:text/html,<script>alert(1)</script>") is False

    def test_file_blocked(self):
        assert _is_safe_scheme("file:///etc/passwd") is False

    def test_smb_blocked(self):
        assert _is_safe_scheme("smb://server/share") is False

    def test_ftp_blocked(self):
        assert _is_safe_scheme("ftp://server/file") is False

    def test_ssh_blocked(self):
        assert _is_safe_scheme("ssh://server") is False

    def test_custom_scheme_blocked(self):
        assert _is_safe_scheme("myapp://open") is False
        assert _is_safe_scheme("obsidian://vault") is False

    def test_vbscript_blocked(self):
        assert _is_safe_scheme("vbscript:msgbox(1)") is False

    def test_empty_blocked(self):
        assert _is_safe_scheme("") is False

    def test_scheme_case_insensitive(self):
        # urlparse lowercases scheme, but test the raw form too
        assert _is_safe_scheme("HTTPS://example.com/") is True
        assert _is_safe_scheme("JAVASCRIPT:alert(1)") is False

    def test_relative_url_allowed(self):
        # Relative URLs are allowed (they don't navigate outside the app)
        assert _is_safe_scheme("/local/path") is True
        assert _is_safe_scheme("#anchor") is True
        assert _is_safe_scheme("relative/path") is True


class TestOnActivateLink:
    """Tests for the activate-link signal handler. This handler returns True
    to block navigation, False to allow."""

    def test_returns_false_for_safe_url(self):
        assert on_activate_link(None, "https://example.com/") is False
        assert on_activate_link(None, "http://example.com/") is False
        assert on_activate_link(None, "mailto:user@example.com") is False

    def test_returns_true_for_unsafe_url(self):
        assert on_activate_link(None, "javascript:alert(1)") is True
        assert on_activate_link(None, "file:///etc/passwd") is True
        assert on_activate_link(None, "data:text/html,<x>") is True

    def test_label_arg_is_ignored(self):
        # The label argument is required by GTK's signal signature but unused
        assert on_activate_link("any-label-obj", "https://example.com/") is False
        assert on_activate_link(object(), "javascript:foo") is True


class TestAllowedLinkSchemesConsistency:
    """Guard against drift between markdown.py and gtk_safe_link.py allowlists."""

    def test_allowlist_matches_markdown(self):
        from utils.markdown import _ALLOWED_LINK_SCHEMES as md_allowlist
        assert md_allowlist == _ALLOWED_LINK_SCHEMES, (
            "HIGH-6: _ALLOWED_LINK_SCHEMES drifted between utils.markdown "
            f"({md_allowlist}) and utils.gtk_safe_link ({_ALLOWED_LINK_SCHEMES}). "
            "Both must agree or the render-time allowlist and the activate-link "
            "guard will diverge."
        )
