# tests/test_settings_handler.py
# Tests for ui/handlers/settings_handler.py — Settings dialog logic.
#
# Pattern: synchronous tests by passing GLib_module=None; test_provider uses
# threading.Event to wait for the daemon thread to finish.
#
# No GTK imports — pure handler logic.

import threading

import pytest

from models.providers import ProviderConfig
from ui.handlers.settings_handler import SettingsHandler
from utils.provider_test import TestResult
from utils.providers_store import load_providers


def _make_provider(name: str = "test", **overrides) -> ProviderConfig:
    """Create a test ProviderConfig with sensible defaults.

    Default model uses the 'openai' prefix so the auto-detect
    caller-validation (caller-validation spec) accepts it. Callers
    that need to exercise different prefixes should pass
    `default_model=...` explicitly.
    """
    defaults = dict(
        name=name,
        base_url=f"https://api.{name}.example.com/v1",
        api_key=f"sk-{name}-key",
        default_model="openai/test-model-v1",
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


class TestListProviders:
    def test_empty_when_no_yaml(self, tmp_config_dir):
        h = SettingsHandler()
        assert h.list_providers() == []

    def test_returns_saved_providers(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("a"))
        h.add_or_update(_make_provider("b"))
        names = [p.name for p in h.list_providers()]
        assert names == ["a", "b"]


class TestAddOrUpdate:
    def test_adds_new_provider(self, tmp_config_dir):
        changed = []
        h = SettingsHandler(on_providers_changed=lambda plist: changed.append(plist))
        h.add_or_update(_make_provider("newprov"))
        assert len(h.list_providers()) == 1
        assert changed and len(changed[0]) == 1

    def test_replaces_existing_same_name(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p", api_key="old-key"))
        h.add_or_update(_make_provider("p", api_key="new-key"))
        providers = h.list_providers()
        assert len(providers) == 1
        assert providers[0].api_key == "new-key"

    def test_empty_name_raises(self, tmp_config_dir):
        h = SettingsHandler()
        with pytest.raises(ValueError, match="name"):
            h.add_or_update(ProviderConfig(
                name="", base_url="https://x", api_key="k", default_model="m",
            ))

    def test_empty_base_url_raises(self, tmp_config_dir):
        h = SettingsHandler()
        with pytest.raises(ValueError, match="Base URL"):
            h.add_or_update(ProviderConfig(
                name="p", base_url="", api_key="k", default_model="m",
            ))

    def test_empty_api_key_raises(self, tmp_config_dir):
        h = SettingsHandler()
        with pytest.raises(ValueError, match="API key"):
            h.add_or_update(ProviderConfig(
                name="p", base_url="https://x", api_key="", default_model="m",
            ))

    def test_empty_default_model_raises(self, tmp_config_dir):
        h = SettingsHandler()
        with pytest.raises(ValueError, match="Default model"):
            h.add_or_update(ProviderConfig(
                name="p", base_url="https://x", api_key="k", default_model="",
            ))

    def test_fires_status_changed_on_add(self, tmp_config_dir):
        statuses = []
        h = SettingsHandler(on_status_changed=lambda b: statuses.append(b))
        h.add_or_update(_make_provider("p"))
        # New provider has last_verified_at=None → status is False
        assert statuses == [False]


class TestRemove:
    def test_removes_existing(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p"))
        h.remove("p")
        assert h.list_providers() == []

    def test_no_op_when_not_found(self, tmp_config_dir):
        h = SettingsHandler()
        h.remove("ghost")  # must not raise
        assert h.list_providers() == []

    def test_fires_callbacks(self, tmp_config_dir):
        changed, statuses = [], []
        h = SettingsHandler(
            on_providers_changed=lambda p: changed.append(p),
            on_status_changed=lambda b: statuses.append(b),
        )
        h.add_or_update(_make_provider("p"))
        changed.clear()
        statuses.clear()
        h.remove("p")
        assert changed and changed[0] == []
        assert statuses == [False]


class TestTestProvider:
    def test_success_stamps_last_verified_at(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=42, error=None, model_used=kw["model"]))

        captured = []
        callback = threading.Event()
        def on_result(r):
            captured.append(r)
            callback.set()

        h = SettingsHandler()  # GLib_module=None → synchronous dispatch
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, on_result)

        assert callback.wait(timeout=2.0), "test_provider callback never fired"
        assert captured[0].ok is True
        # Provider in yaml should now have last_verified_at set
        providers = h.list_providers()
        assert providers[0].last_verified_at is not None
        assert providers[0].last_error is None

    def test_failure_stamps_last_error(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=False, latency_ms=10, error="401 unauthorized", model_used=kw["model"]))

        captured, callback = [], threading.Event()
        def on_result(r):
            captured.append(r)
            callback.set()

        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, on_result)
        assert callback.wait(timeout=2.0)

        assert captured[0].ok is False
        providers = h.list_providers()
        assert providers[0].last_error == "401 unauthorized"
        assert providers[0].last_verified_at is None  # unchanged

    def test_test_connection_raises_wrapped_as_failure(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        def boom(**kw):
            raise ValueError("unknown provider")
        monkeypatch.setattr(sh, "test_connection", boom)

        captured, callback = [], threading.Event()
        def on_result(r):
            captured.append(r)
            callback.set()

        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, on_result)
        assert callback.wait(timeout=2.0)
        assert captured[0].ok is False
        assert "unknown provider" in captured[0].error

    def test_fires_status_changed_on_success(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=1, error=None, model_used=kw["model"]))

        statuses = []
        status_event = threading.Event()
        def on_result(r):
            pass  # just acknowledge

        h = SettingsHandler(on_status_changed=lambda b: (statuses.append(b), status_event.set()))
        p = _make_provider("p")
        h.add_or_update(p)
        statuses.clear()
        status_event.clear()  # reset so we wait for the test_provider's callback
        h.test_provider(p, on_result)
        assert status_event.wait(timeout=2.0), "on_status_changed never fired"
        # After successful test, status should be True
        assert True in statuses

    def test_preserves_caller_on_success(self, tmp_config_dir, monkeypatch):
        """Regression: test_provider's success-path must not strip the caller field.
        Without the fix, _worker rebuilds ProviderConfig without caller=, silently
        dropping it on save and breaking subsequent runtime calls.
        """
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=42, error=None, model_used=kw["model"]))

        callback = threading.Event()
        h = SettingsHandler()
        # caller="minimax" is set explicitly (not auto-detected from default_model).
        p = _make_provider("p", caller="minimax")
        h.add_or_update(p)
        h.test_provider(p, lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = h.list_providers()
        assert providers[0].caller == "minimax", (
            f"test_provider stripped caller on success; got {providers[0].caller!r}"
        )
        # Verify the success path also ran (last_verified_at is set)
        assert providers[0].last_verified_at is not None

    def test_preserves_caller_on_failure(self, tmp_config_dir, monkeypatch):
        """Regression: test_provider's failure-path must not strip the caller field.
        Both success and failure branches rebuild ProviderConfig — both must preserve caller.
        """
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=False, latency_ms=10, error="401 unauthorized", model_used=kw["model"]))

        callback = threading.Event()
        h = SettingsHandler()
        p = _make_provider("p", caller="minimax")
        h.add_or_update(p)
        h.test_provider(p, lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = h.list_providers()
        assert providers[0].caller == "minimax", (
            f"test_provider stripped caller on failure; got {providers[0].caller!r}"
        )
        assert providers[0].last_error == "401 unauthorized"

    def test_auto_detects_caller_from_model_prefix(self, tmp_config_dir, monkeypatch):
        """Self-heal: when caller is empty and default_model has a slash,
        the worker auto-fills caller from the prefix. This lets broken YAML
        entries (post-regression state) recover on next Test Connection.
        Caller validation (caller-validation spec) also lowercases the
        prefix to match the taxonomy.
        """
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=1, error=None, model_used=kw["model"]))

        callback = threading.Event()
        h = SettingsHandler()
        # Note: caller defaults to "" (ProviderConfig default). Mimics a broken YAML entry.
        p = _make_provider("minimax-M3", default_model="minimax-M3/model-v1")
        h.add_or_update(p)
        # Sanity: add_or_update's auto-detect should already have set caller,
        # lowercased to match the taxonomy (caller-validation spec).
        assert h.list_providers()[0].caller == "minimax"

        # Now simulate the broken-state scenario: caller explicitly empty.
        broken = _make_provider("minimax-M3", caller="")
        h.test_provider(broken, lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = h.list_providers()
        assert providers[0].caller == "minimax", (
            f"test_provider did not auto-detect caller; got {providers[0].caller!r}"
        )


class TestStatusHasVerified:
    def test_false_when_no_providers(self, tmp_config_dir):
        h = SettingsHandler()
        assert h.status_has_verified() is False

    def test_false_when_no_verified(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p"))  # last_verified_at=None
        assert h.status_has_verified() is False

    def test_true_after_verification(self, tmp_config_dir, monkeypatch):
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=1, error=None, model_used=kw["model"]))

        callback = threading.Event()
        h = SettingsHandler()
        p = _make_provider("p")
        h.add_or_update(p)
        h.test_provider(p, lambda r: callback.set())
        assert callback.wait(timeout=2.0)
        assert h.status_has_verified() is True


class TestTestProviderPrefillsMaxTokens:
    def test_success_with_context_window_prefills_default(self, tmp_config_dir, monkeypatch):
        """When max_tokens == 128_000 default and context_window is set, pre-fill."""
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=200, error=None,
                       model_used=kw["model"], context_window=500_000))

        callback = threading.Event()
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))  # max_tokens defaults to 128_000

        h.test_provider(_make_provider("p1"), lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = load_providers()
        assert providers[0].max_tokens == 500_000

    def test_success_does_not_overwrite_customized(self, tmp_config_dir, monkeypatch):
        """When max_tokens has been customized, Test Connection doesn't overwrite."""
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=200, error=None,
                       model_used=kw["model"], context_window=1_000_000))

        callback = threading.Event()
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=300_000))

        h.test_provider(_make_provider("p1"), lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = load_providers()
        assert providers[0].max_tokens == 300_000  # preserved

    def test_failure_does_not_change_max_tokens(self, tmp_config_dir, monkeypatch):
        """Failure path leaves max_tokens untouched."""
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=False, latency_ms=0,
                       error="401 Unauthorized",
                       model_used=kw["model"], context_window=None))

        callback = threading.Event()
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=200_000))

        h.test_provider(_make_provider("p1"), lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = load_providers()
        assert providers[0].max_tokens == 200_000  # untouched

    def test_success_without_context_window_preserves_max_tokens(self, tmp_config_dir, monkeypatch):
        """When context_window is None, max_tokens stays unchanged."""
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=200, error=None,
                       model_used=kw["model"], context_window=None))

        callback = threading.Event()
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=200_000))

        h.test_provider(_make_provider("p1"), lambda r: callback.set())
        assert callback.wait(timeout=2.0), "test_provider callback never fired"

        providers = load_providers()
        assert providers[0].max_tokens == 200_000  # unchanged

    # BUG #7 regression: when auxilium wizard sets default_max_tokens=N AND
    # max_tokens == N (the sentinel value), Test Connection's pre-fill check
    # `p.max_tokens == 128_000` must NOT overwrite — because default_max_tokens
    # is non-zero, indicating a deliberate wizard-set choice.

    def test_wizard_default_max_tokens_protects_against_overwrite(self, tmp_config_dir, monkeypatch):
        """BUG #7: provider with default_max_tokens != 0 must NOT be overwritten
        by Test Connection pre-fill even when max_tokens == 128_000 sentinel."""
        from models.providers import ProviderConfig
        from ui.handlers import settings_handler as sh
        monkeypatch.setattr(sh, "test_connection", lambda **kw:
            TestResult(ok=True, latency_ms=200, error=None,
                       model_used=kw["model"], context_window=1_000_000))

        callback = threading.Event()
        h = SettingsHandler()
        # Simulate auxilium wizard output for openrouter: sentinel max_tokens=128K
        # but default_max_tokens=128_000 (the wizard stamped it)
        wizard_provider = ProviderConfig(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="***",
            default_model="openrouter/free",
            caller="openrouter",
            max_tokens=128_000,
            default_max_tokens=128_000,  # wizard stamped this
        )
        h.add_or_update(wizard_provider)

        h.test_provider(wizard_provider, lambda r: callback.set())
        assert callback.wait(timeout=2.0)

        providers = load_providers()
        # max_tokens must remain 128_000 (the wizard's deliberate choice).
        # Before the BUG #7 fix, the pre-fill check would have overwritten
        # to 1_000_000.
        assert providers[0].max_tokens == 128_000, (
            f"BUG #7: wizard default was overwritten: max_tokens={providers[0].max_tokens}"
        )
