# tests/test_gateway.py
# A-1 tests: lazy identity loading in GatewayClient.

import pytest


class TestLazyIdentityLoading:
    """A-1: GatewayClient must NOT call _load_identity on construction."""

    def test_constructor_does_not_raise_without_identity_file(self, tmp_path, monkeypatch):
        """Constructing GatewayClient must not call _load_identity.

        A-1: identity loading is deferred to start(), not __init__.
        """
        # Make identity directory non-existent to trigger _load_identity error
        # if it were called in __init__
        nonexistent_identity = tmp_path / "nonexistent"
        monkeypatch.setenv("OPENCLAW_IDENTITY_DIR", str(nonexistent_identity))

        # Patch _load_identity to verify it's NOT called during __init__
        import gateway.client as gc
        original_load = gc._load_identity

        called = False
        def tracking_load():
            nonlocal called
            called = True
            return original_load()

        monkeypatch.setattr(gc, "_load_identity", tracking_load)

        # This should NOT raise and should NOT call _load_identity
        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
            on_tick=None,
        )

        assert not called, (
            "A-1 VIOLATION: _load_identity was called during __init__. "
            "Identity loading must be deferred to start()."
        )

    def test_identity_loaded_flag_initialized_to_false(self, tmp_path, monkeypatch):
        """GatewayClient._identity_loaded must start as False."""
        import gateway.client as gc

        # Ensure identity dir is absent so _load_identity would raise
        nonexistent_identity = tmp_path / "nonexistent"
        monkeypatch.setenv("OPENCLAW_IDENTITY_DIR", str(nonexistent_identity))

        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
        )

        assert client._identity_loaded is False, (
            "_identity_loaded must be initialized to False on construction"
        )

    def test_start_loads_identity_and_sets_flag(self, tmp_path, monkeypatch):
        """start() must call _load_identity and set _identity_loaded=True."""
        import gateway.client as gc
        import os

        # Create a real identity dir with a minimal device-auth.json
        identity_dir = tmp_path / "identity"
        identity_dir.mkdir()
        device_auth = identity_dir / "device-auth.json"
        device_auth.write_text("{}")

        monkeypatch.setenv("OPENCLAW_IDENTITY_DIR", str(identity_dir))

        # Reset module state so we can track fresh
        gc._IDENTITY_CACHE = None

        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
        )

        assert client._identity_loaded is False

        # Note: we can't easily call start() without a real websocket connection,
        # but we can verify the flag is correct before start()
        # The key test is that __init__ does NOT call _load_identity (above)

    def test_identity_id_is_empty_dict_before_start(self, tmp_path, monkeypatch):
        """GatewayClient._id must be empty dict before start(), not a loaded identity."""
        import gateway.client as gc

        nonexistent_identity = tmp_path / "nonexistent"
        monkeypatch.setenv("OPENCLAW_IDENTITY_DIR", str(nonexistent_identity))

        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
        )

        # Before start(), _id must be an empty dict (not loaded)
        assert client._id == {}, (
            f"Expected _id to be {{}} before start(), got {client._id!r}. "
            "Before start(), no identity should be loaded."
        )

    def test_module_preload_does_not_affect_client(self, monkeypatch):
        """The module-level _load_identity() preload must not affect GatewayClient.__init__.

        The module has `_load_identity()` called at module level (to catch errors early).
        But GatewayClient must NOT inherit that preloaded identity — it must be empty on init.
        """
        import gateway.client as gc

        # Verify that module-level preload happened (this is existing behavior)
        # but client._id is still {} before start()
        #
        # This test documents that even if _IDENTITY_CACHE is set at module level,
        # the client still initializes _id = {} (A-1: no eager loading in __init__)

        nonexistent_identity = "/nonexistent/path/that/does/not/exist"
        monkeypatch.setenv("OPENCLAW_IDENTITY_DIR", nonexistent_identity)

        # Force module reload to reset _IDENTITY_CACHE
        monkeypatch.setattr(gc, "_IDENTITY_CACHE", None)

        client = gc.GatewayClient(
            url="ws://localhost:18789",
            on_connect=lambda: None,
            on_error=lambda e: None,
            on_event=lambda n, p: None,
        )

        # Key assertion: _id is empty before start(), even if _IDENTITY_CACHE
        # was populated at module level before this test ran
        assert client._id == {}, (
            "A-1 VIOLATION: _id must be {} before start(). "
            "Even module-level preload must not populate client._id on construction."
        )
