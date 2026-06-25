# SPEC: Model Capacity Discovery (auto-detect context window + editable override)

**Date:** 2026-06-24
**Author:** Qaster (implementation supervisor)
**Status:** Draft — for implementation
**Implements:** User-reported gap (no UI to set `max_tokens`; hardcoded 128K ignores M3's actual 1M window)
**Depends on:** None (Phase 1 — read-only on existing files; Phase 2 is additive UI)
**Target branch:** main

> Architecture compliance: ARCHITECTURE.md §3.21q (LLM providers), §3.21q.5b (KB Provider), §4.15 (`max_tokens` resolution), §9 (view ↔ handler separation). Pure view vs pure logic split is preserved. The settings dialog stays a pure view; the handler stays the data gateway.

---

## DISCOVERY

- **`/home/q/projects/crabcakes/models/providers.py`** — `ProviderConfig` is a `@dataclass` with field `max_tokens: int = 128_000`. All fields are keyword args, no validation in `__init__`. Pure data, no I/O.
- **`/home/q/projects/crabcakes/utils/providers_store.py`** — `save_providers()` serializes each dataclass via a YAML/JSON `_serialize()` helper that calls `_to_dict()` (returns all dataclass fields). `load_providers()` reads back via `_from_dict()` (sets each dataclass field with a fallback). Atomic write via `.tmp` + `os.replace`.
- **`/home/q/projects/crabcakes/utils/provider_test.py`** — `test_connection()` returns a `TestResult` dataclass with fields `ok: bool`, `latency_ms: int`, `error: str | None`, `model_used: str`. **Currently returns NO max_tokens / context window info.** Pure network I/O, no GTK.
- **`/home/q/projects/crabcakes/ui/handlers/settings_handler.py`** — `test_provider()` (line 124) runs `test_connection()` in a daemon thread, stamps the result back onto the matching provider in `providers.yaml`, fires `on_status_changed`. Currently preserves `max_tokens=p.max_tokens` on success — does NOT update it from the test result.
- **`/home/q/projects/crabcakes/ui/views/settings_dialog.py`** — `_ProviderCard._collect_from_form()` (line 171) reads 4 form fields (name, base_url, api_key, default_model) and copies all other fields from `existing`. **There is currently NO max_tokens form widget.** `_on_test_clicked()` (line 195) triggers the test, then `_on_test_result()` (line 238) updates the status label only.
- **`/home/q/projects/crabcakes/agent/runtime.py`** — `_compute_model_max()` (line 1468) reads `provider_cfg.max_tokens` with fallback 128_000. **Already picks up any value we set on the dataclass — no runtime changes needed.** The fallback constant is `FALLBACK = 128_000`.
- **`~/.config/crabcakes/providers.yaml`** — all 3 providers currently have `max_tokens: 128000`. M3 provider should be 1_048_576 but is hardcoded to 128K.
- **`~/.config/crabcakes/agents/coder.yaml`** — `fallback_provider: glm5.2` (provider NAME, not model — per `provider_name.split('/')[0]`).
- **`/home/q/projects/crabcakes/tests/conftest.py`** — `tmp_config_dir` fixture patches `$HOME` to a tmp dir and pre-creates `~/.config/crabcakes`. Use this for all new tests.
- **`/home/q/projects/crabcakes/tests/test_provider_test.py`** — pattern for mocking `urllib.request.urlopen`, building `_mock_response(body)`, asserting `TestResult` fields. **New `TestResult.context_window` field assertions must follow this exact pattern.**
- **`/home/q/projects/crabcakes/tests/test_settings_dialog.py`** — GTK_AVAILABLE guard via `pytest.mark.skipif`, uses `tmp_config_dir` and `SettingsHandler()`. `TestSaveFlow` shows how to drive form fields and click save. **New widget tests must follow this pattern.**
- **`/home/q/projects/crabcakes/tests/test_providers_store.py`** — `_make_provider()` helper, `tmp_config_dir` fixture, atomic-write tests. **`max_tokens` field is already exercised in `TestLoadSave.test_round_trip_preserves_all_fields` — we don't need to re-test persistence.**

**Architecture owner:** `models/providers.py` (`ProviderConfig` dataclass) → `utils/providers_store.py` (YAML persistence) → `ui/handlers/settings_handler.py` (handler) → `ui/views/settings_dialog.py` (view) → `agent/runtime.py` (consumer via `_compute_model_max`).

**Existing patterns to mirror:**
1. Provider config writes — `set_provider_options` / `add_or_update` in `SettingsHandler` → `save_providers` in `utils/providers_store`. Every field flows through `ProviderConfig` → `_to_dict()` → YAML → `_from_dict()` → `ProviderConfig`.
2. Test Connection UI update — `_on_test_clicked` → `_dialog._handler.test_provider(provider, self._on_test_result)` → daemon thread → result on main thread → status label update. New: pre-fill `max_tokens` entry on success.
3. Caller auto-detect (PHASE-10 fix in `test_provider` line 130-132) — prefix-based detection when caller is empty. Pattern is "infer from API response, allow user override."
4. Test mocking — `urllib.request.urlopen` mocked at the boundary; new OpenAI `/models` probe follows the same pattern but mocks a `GET` request instead of `POST`.

---

## 1. Overview

### Problem statement

Users have no way to set a provider's `max_tokens` (context window) in the UI. The default is hardcoded to 128_000 in three places:
- `models/providers.py:ProviderConfig` field default
- `utils/providers_store.py:_from_dict()` fallback
- `agent/runtime.py:_compute_model_max()` `FALLBACK` constant

For MiniMax-M3 (1M context window) and similar large-context models, this wastes 87% of the context window — the runtime trims aggressively at 128K when 1M is available.

When a provider is added, `max_tokens` defaults to 128_000. There is no form widget to edit it. Users have to hand-edit `providers.yaml`.

### Solution summary

Two independent changes, deployed as two phases in one spec:

**Phase 1 (data + probe, no UI changes):**
1. Add `default_max_tokens: int` field to `ProviderConfig` — a per-caller fallback table (e.g. OpenAI = 128K, Anthropic = 200K, MiniMax-M3 = 1M) so fresh installs at least pick a reasonable value for known callers.
2. Extend `TestResult` with `context_window: int | None` and add a second OpenAI-compatible probe in `test_connection()` that does `GET /v1/models` after a successful `POST /chat/completions` and extracts the context window from the model object's metadata.
3. On successful Test Connection, pre-fill `max_tokens` from `TestResult.context_window` if the existing value is the 128_000 default (i.e. the user hasn't customized it).
4. User can still hand-edit `max_tokens` in YAML; the pre-fill is non-destructive.

**Phase 2 (UI):**
1. Add a `max_tokens` SpinButton to the provider card so users can edit it without leaving the UI.
2. The field is populated from the stored `max_tokens` on load, included in `_collect_from_form()`, and saved through the existing handler.
3. Test Connection's success path also pre-fills this entry field in-place (in addition to writing to YAML).

### Scope

| In scope | Out of scope |
|----------|--------------|
| New `ProviderConfig.default_max_tokens` field | Renaming existing `max_tokens` field |
| New `CALLER_DEFAULT_MAX_TOKENS` table | Auto-updating `max_tokens` on every API call (only on Test Connection) |
| OpenAI-compatible `/v1/models` GET probe in `test_connection()` | Non-OpenAI-compatible `/v1/models` responses (anthropic, zai) |
| Pre-fill `max_tokens` on Test Connection success | Pre-fill on failure (we have no data to pre-fill with) |
| `max_tokens` SpinButton in provider card | Per-model dropdown (out of scope; only the provider's default) |
| New tests in `tests/test_provider_test.py`, `tests/test_settings_dialog.py`, `tests/test_providers_store.py` | Changes to `_compute_model_max` (already handles the value correctly) |

### Architecture principles that apply

- **§3.21q — LLM providers:** `caller` field selects API adapter. The new `default_max_tokens` table is keyed by caller (mirroring `caller` resolution).
- **§4.15 — max_tokens resolution:** `_compute_model_max()` reads `provider_cfg.max_tokens` and falls back to 128K. Our spec doesn't change this; we just populate the value correctly upstream.
- **§9 — view ↔ handler:** View collects form data; handler persists and runs network ops. New SpinButton lives in the view; the Save click handler invokes `add_or_update()` as before.

---

## 2. Changes by File

### 2.1. `models/providers.py` — add `default_max_tokens` field

**What changes:** Add one new field to `ProviderConfig` dataclass. No other code in this file changes.

**Field signature:**
```python
default_max_tokens: int = 0  # 0 means "no caller-specific default; use 128_000"
```

**Rationale for `0` (not `128_000`):** Allows distinguishing "no caller-specific default" from "default is 128K". The existing `max_tokens` field stays at `128_000` as the global fallback.

**Code sample (verified against current source — `models/providers.py:18-32`):**

```python
@dataclass
class ProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""                    # API caller key (openai|minimax|anthropic|openrouter|zai)
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000           # Context window for this provider (auto-filled by Test Connection)
    default_max_tokens: int = 0         # Caller-specific default (0 = no caller-specific default)
    last_verified_at: str | None = None
    last_error: str | None = None
```

**Imports required:** None (dataclasses already imported).

**Line count estimate:** +1 line (one field). Existing field order preserved so YAML files without the new field still load via `_from_dict()` defaults.

---

### 2.2. `utils/providers_store.py` — update `_from_dict()` fallback for `default_max_tokens`

**What changes:** `_from_dict()` reads each field from the YAML dict. Add one line for the new field with a `0` default (matches the dataclass default).

**Verified current shape (`utils/providers_store.py`, lines not shown in discovery but inferred from `test_round_trip_preserves_all_fields` which already tests `max_tokens` round-trip):** Each field is read with a fallback. Adding `default_max_tokens` follows the same pattern.

**Code sample:**

```python
def _from_dict(d: dict) -> ProviderConfig:
    return ProviderConfig(
        name=d.get("name", ""),
        base_url=d.get("base_url", ""),
        api_key=d.get("api_key", ""),
        default_model=d.get("default_model", ""),
        caller=d.get("caller", ""),
        enabled=d.get("enabled", True),
        supports_tools=d.get("supports_tools", True),
        supports_streaming=d.get("supports_streaming", True),
        max_tokens=d.get("max_tokens", 128_000),
        default_max_tokens=d.get("default_max_tokens", 0),  # NEW
        last_verified_at=d.get("last_verified_at"),
        last_error=d.get("last_error"),
    )
```

**Verified (after re-read of `utils/providers_store.py:35-49,52-66`):** `_to_dict()` is an explicit dict literal that lists every field — NOT `dataclasses.asdict()`. So the new field ALSO needs to be added to `_to_dict()` to be persisted.

**Corrected code sample for `_to_dict()` (one new line):**
```python
def _to_dict(p: ProviderConfig) -> dict[str, Any]:
    """Convert a ProviderConfig to a plain dict for serialization."""
    return {
        "name": p.name,
        "base_url": p.base_url,
        "api_key": p.api_key,
        "default_model": p.default_model,
        "caller": p.caller,
        "enabled": p.enabled,
        "supports_tools": p.supports_tools,
        "supports_streaming": p.supports_streaming,
        "max_tokens": p.max_tokens,
        "default_max_tokens": p.default_max_tokens,  # NEW
        "last_verified_at": p.last_verified_at,
        "last_error": p.last_error,
    }
```

**Line count estimate:** +2 lines (one in `_to_dict`, one in `_from_dict`).

---

### 2.3. `utils/provider_test.py` — add `context_window` to `TestResult` + `/v1/models` probe

**What changes:**

1. Add `context_window: int | None = None` field to `TestResult`.
2. After successful `POST /chat/completions`, send a `GET /v1/models` request to extract the model object's context window from common field names (`context_window`, `max_context_length`, `context_length`, `max_tokens`).
3. If the GET fails (some providers don't expose `/v1/models`), set `context_window=None` and continue — `TestResult.ok` stays True.

**Verified current signature (`utils/provider_test.py:51-56`):**
```python
@dataclass
class TestResult:
    ok: bool
    latency_ms: int
    error: str | None
    model_used: str
```

**Updated signature:**
```python
@dataclass
class TestResult:
    ok: bool
    latency_ms: int
    error: str | None
    model_used: str
    context_window: int | None = None  # NEW — context window in tokens, if discoverable
```

**Why `int | None = None`:** `None` means "couldn't determine"; `0` would mean "no context window" which is nonsensical.

**Code sample — extend `test_connection()` to probe `/v1/models` after successful POST:**

This sample goes inside `test_connection()`, AFTER the existing successful POST block. The implementer should add it as a new step after `result = TestResult(...)` construction but BEFORE the return statement.

```python
# ── Probe /v1/models for context window (best-effort) ─────────────
# If the successful POST happened, try to discover the model's context
# window from the OpenAI-compatible /v1/models endpoint. Failures here
# are non-fatal — many providers don't expose this.
context_window: int | None = None
try:
    models_url = base_url.rstrip("/") + "/models"
    models_req = urllib.request.Request(models_url, method="GET")
    models_req.add_header("Authorization", f"Bearer {api_key}")
    # Anthropic uses x-api-key; harmless to include Bearer too
    with urllib.request.urlopen(models_req, timeout=10) as resp:
        models_body = json.loads(resp.read().decode("utf-8"))

    # OpenAI shape: {"data": [{"id": "model-id", "context_window": N}, ...]}
    # Some providers nest metadata differently.
    model_id = result.model_used.split("/", 1)[-1]  # strip "provider/" prefix
    for model_obj in models_body.get("data", []):
        if model_obj.get("id") == model_id:
            # Try common field names for context window
            for field in ("context_window", "max_context_length",
                          "context_length", "max_tokens", "max_model_len"):
                if field in model_obj and isinstance(model_obj[field], int):
                    context_window = int(model_obj[field])
                    break
            break
except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
        json.JSONDecodeError, KeyError, OSError, ValueError):
    # Non-fatal — leave context_window as None
    pass

result = TestResult(
    ok=True,
    latency_ms=...,
    error=None,
    model_used=model,
    context_window=context_window,  # NEW
)
```

**Exception coverage verified:** `urllib.request.urlopen` raises `urllib.error.URLError` (DNS, connection refused), `urllib.error.HTTPError` (4xx/5xx — subclass of `URLError`), `TimeoutError` (socket timeout), `socket.timeout`. JSON parsing raises `json.JSONDecodeError`. Dict access raises `KeyError`. The for-loop iteration uses `.get()` (no `KeyError`); `isinstance(..., int)` handles type mismatches. Generic `OSError` covers other socket-level errors. Generic `ValueError` covers unexpected type coercions.

**Imports required:** None new (`urllib.request`, `urllib.error`, `json`, `TimeoutError` all already imported per lines 9-15).

**Line count estimate:** +35 lines (probe block + field).

---

### 2.4. `ui/handlers/settings_handler.py` — pre-fill `max_tokens` on Test Connection success

**What changes:** Inside `test_provider()` (line 124), after the existing successful POST branch (lines 153-171), update the `ProviderConfig(...)` reconstruction to use the discovered `context_window` when:
- `result.ok is True`
- `result.context_window is not None`
- the existing `max_tokens` equals the dataclass default (128_000) — meaning the user hasn't customized it.

**Verified current reconstruction (`settings_handler.py:154-167`):**
```python
providers[i] = ProviderConfig(
    name=p.name,
    base_url=p.base_url,
    ...
    max_tokens=p.max_tokens,           # ← preserve (current behavior)
    last_verified_at=...,
    last_error=None,
)
```

**Updated code sample:**
```python
providers[i] = ProviderConfig(
    name=p.name,
    base_url=p.base_url,
    api_key=p.api_key,
    default_model=p.default_model,
    caller=p.caller,
    enabled=p.enabled,
    supports_tools=p.supports_tools,
    supports_streaming=p.supports_streaming,
    # Pre-fill max_tokens from /v1/models probe ONLY if user hasn't customized.
    # Default sentinel: 128_000 (matches ProviderConfig field default).
    max_tokens=(
        result.context_window
        if result.ok and result.context_window and p.max_tokens == 128_000
        else p.max_tokens
    ),
    default_max_tokens=p.default_max_tokens,
    last_verified_at=datetime.now(timezone.utc).isoformat(),
    last_error=None,
)
```

**Why `p.max_tokens == 128_000` as the "not customized" sentinel:**
- It's the dataclass default — any user-customized value will be different.
- We're not adding a separate "user has customized this" flag; the field IS the flag (a value ≠ 128_000 means customized).
- If the user later edits to exactly 128_000, the next Test Connection would re-pre-fill — acceptable since 128_000 is a valid value (and they can re-set it).

**Failure branch:** The existing failure branch (lines 173-186) keeps `max_tokens=p.max_tokens` unchanged. No pre-fill on failure — we have no data.

**Imports required:** None new (existing imports suffice).

**Line count estimate:** +1 line in the max_tokens expression (just making it a conditional instead of a passthrough).

---

### 2.5. `ui/views/settings_dialog.py` — add `max_tokens` SpinButton

**What changes:**

1. In `_build_widgets()` (line 33), add a new labeled row containing a `Gtk.SpinButton` for `max_tokens`.
2. In `_populate_from_provider()` (line 159), set the SpinButton value from `p.max_tokens`.
3. In `_collect_from_form()` (line 171), read the SpinButton value into the `max_tokens` field.
4. In `_is_dirty()` (line 163), include the SpinButton in the dirty check.
5. In `_on_test_result()` (line 238), pre-fill the SpinButton when `result.ok and result.context_window`.

**Code samples — each verified against current widget patterns:**

**5a. New SpinButton in `_build_widgets()` (insert after `caller_row` line 78):**
```python
# Context window (max_tokens) — editable; pre-filled by Test Connection.
# Default 128_000 matches the dataclass default and runtime fallback.
self._max_tokens_spin = Gtk.SpinButton.new_with_range(1_000, 10_000_000, 1_000)
self._max_tokens_spin.set_value(self._provider.max_tokens or 128_000)
self._max_tokens_spin.set_hexpand(True)
max_tokens_row = self._labeled("Context Window", self._max_tokens_spin)
vbox.append(max_tokens_row)
```

**Why `1_000..10_000_000`:** Lower bound 1K prevents typos of `0`; upper bound 10M covers GPT-4 1M, Claude 1M, Gemini 1M, future 10M-class models.

**5b. `_populate_from_provider()` update (line 159):**
```python
def _populate_from_provider(self) -> None:
    p = self._provider
    self._name_entry.set_text(p.name or "")
    self._base_url_entry.set_text(p.base_url or "")
    self._model_entry.set_text(p.default_model or "")
    self._api_key_entry.set_text(p.api_key or "")
    self._caller_label.set_text(
        f"  {p.caller}" if p.caller else "  (auto-detected on save)"
    )
    self._max_tokens_spin.set_value(p.max_tokens or 128_000)  # NEW
```

**5c. `_collect_from_form()` update (line 171) — current text shows truncation; full method:**
```python
def _collect_from_form(self) -> ProviderConfig:
    """Collect current form values into a ProviderConfig."""
    existing = self._provider
    return ProviderConfig(
        name=self._name_entry.get_text().strip(),
        base_url=self._base_url_entry.get_text().strip(),
        api_key=self._api_key_entry.get_text(),
        default_model=self._model_entry.get_text().strip(),
        caller=existing.caller if existing else "",
        enabled=existing.enabled if existing else True,
        supports_tools=existing.supports_tools if existing else True,
        supports_streaming=existing.supports_streaming if existing else True,
        max_tokens=int(self._max_tokens_spin.get_value()),  # NEW
        default_max_tokens=existing.default_max_tokens if existing else 0,
        last_verified_at=existing.last_verified_at if existing else None,
        last_error=existing.last_error if existing else None,
    )
```

**5d. `_is_dirty()` update (line 163) — add SpinButton to dirty check:**
```python
def _is_dirty(self) -> bool:
    """True if any entry field differs from the stored provider values."""
    p = self._provider
    return (
        self._name_entry.get_text().strip() != (p.name or "")
        or self._base_url_entry.get_text().strip() != (p.base_url or "")
        or self._model_entry.get_text().strip() != (p.default_model or "")
        or self._api_key_entry.get_text().strip() != (p.api_key or "")
        or int(self._max_tokens_spin.get_value()) != (p.max_tokens or 128_000)  # NEW
    )
```

**5e. `_on_test_result()` pre-fill (line 238):**
```python
def _on_test_result(self, result: TestResult) -> None:
    """Called on the GTK main thread with the test result."""
    if result.ok:
        self._set_status(f"✅ {result.latency_ms}ms", ok=True)
        # Pre-fill context window if discovered and user hasn't customized.
        # Sentinel: 128_000 matches the dataclass default.
        if result.context_window and (self._provider.max_tokens == 128_000):
            self._max_tokens_spin.set_value(result.context_window)
            self._status_label.set_text(
                f"✅ {result.latency_ms}ms · context: {result.context_window:,}"
            )
    else:
        error_msg = result.error or "unknown error"
        self._set_status(f"❌ {error_msg}", fail=True)
```

**Note:** The in-memory `_provider` reference is stale until the user saves (the handler does the YAML write). Updating only the SpinButton is correct: it's the visual pre-fill that the user will then save. The handler ALSO writes to YAML via `test_provider()` (Section 2.4), so on next `refresh_providers()`, the value will be loaded back from disk.

**Imports required:** `from gi.repository import Gtk` already imported (line 14).

**Line count estimate:** +30 lines across 5 methods.

---

### 2.6. `tests/test_provider_test.py` — extend with `/v1/models` probe tests

**What changes:** Add a new test class `TestModelsEndpointProbe` covering:
- `/v1/models` returns a context window → `TestResult.context_window` is populated.
- `/v1/models` returns 404 → `TestResult.context_window` is `None` (not an error).
- `/v1/models` returns malformed JSON → `TestResult.context_window` is `None`.
- Model not in list → `TestResult.context_window` is `None`.

**Code sample — first test (pattern follows existing `TestOpenAICompatible`):**
```python
class TestModelsEndpointProbe:
    def test_models_endpoint_returns_context_window(self):
        """Successful POST + GET /v1/models → context_window populated."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({
            "data": [
                {"id": "gpt-4o", "context_window": 128_000},
                {"id": "gpt-4o-mini", "context_window": 128_000},
            ],
        }).encode()

        # urlopen is called twice: once for POST, once for GET.
        # Use side_effect with a list of responses.
        chat_resp = _mock_response(chat_body)
        models_resp = _mock_response(models_body)
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, models_resp]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-xxx",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window == 128_000
```

**Second test — 404 from /v1/models is non-fatal:**
```python
    def test_models_endpoint_404_is_non_fatal(self):
        """Provider doesn't expose /v1/models → context_window is None, ok stays True."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        chat_resp = _mock_response(chat_body)
        err_404 = _http_error(404, "Not Found", "no /models here")
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[chat_resp, err_404]):
            result = test_connection(
                base_url="https://api.minimax.example.com/v1",
                api_key="sk-xxx",
                model="example/foo",
            )
        assert result.ok is True
        assert result.context_window is None
```

**Third test — model ID mismatch:**
```python
    def test_models_endpoint_model_id_mismatch(self):
        """GET returns models but the tested model isn't in the list."""
        chat_body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
        models_body = json.dumps({"data": [{"id": "different-model", "context_window": 4096}]}).encode()
        with patch("utils.provider_test.urllib.request.urlopen",
                   side_effect=[_mock_response(chat_body), _mock_response(models_body)]):
            result = test_connection(
                base_url="https://api.openai.com/v1",
                api_key="sk-xxx",
                model="openai/gpt-4o",
            )
        assert result.ok is True
        assert result.context_window is None
```

**Line count estimate:** +60 lines (3-4 tests in new class).

---

### 2.7. `tests/test_settings_dialog.py` — new `TestMaxTokensSpinButton` class

**What changes:** Add a new test class verifying the new SpinButton:
- Renders with the correct initial value (from stored provider).
- `_collect_from_form()` returns the spin value.
- `_is_dirty()` flips when spin is edited.
- Pre-fill on Test Result success.

**Code sample:**
```python
class TestMaxTokensSpinButton:
    def test_spin_button_renders(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        assert card._max_tokens_spin is not None

    def test_spin_button_populated_from_provider(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=200_000))
        d = SettingsDialog(parent=None, handler=h)
        assert d._cards[0]._max_tokens_spin.get_value() == 200_000

    def test_collect_from_form_includes_max_tokens(self, tmp_config_dir):
        h = SettingsHandler()
        d = SettingsDialog(parent=None, handler=h)
        d._on_add_provider_clicked(None)
        card = d._cards[-1]
        card._name_entry.set_text("p1")
        card._base_url_entry.set_text("https://x.example.com/v1")
        card._api_key_entry.set_text("test-key")
        card._model_entry.set_text("p1/model-v1")
        card._max_tokens_spin.set_value(500_000)
        card._on_save_clicked(None)
        saved = h.list_providers()
        assert saved[0].max_tokens == 500_000

    def test_is_dirty_flips_when_spin_edited(self, tmp_config_dir):
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        assert not card._is_dirty()
        card._max_tokens_spin.set_value(200_000)
        assert card._is_dirty()

    def test_on_test_result_prefills_spin(self, tmp_config_dir):
        """Mock TestResult with context_window; verify spin is updated."""
        from utils.provider_test import TestResult
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=128_000))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        result = TestResult(ok=True, latency_ms=200, error=None,
                            model_used="p1/model-v1", context_window=1_000_000)
        card._on_test_result(result)
        assert card._max_tokens_spin.get_value() == 1_000_000

    def test_on_test_result_does_not_overwrite_customized(self, tmp_config_dir):
        """If user has customized max_tokens, don't overwrite from probe."""
        from utils.provider_test import TestResult
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=500_000))
        d = SettingsDialog(parent=None, handler=h)
        card = d._cards[0]
        result = TestResult(ok=True, latency_ms=200, error=None,
                            model_used="p1/model-v1", context_window=1_000_000)
        card._on_test_result(result)
        assert card._max_tokens_spin.get_value() == 500_000  # preserved
```

**Line count estimate:** +60 lines (6 tests in new class).

---

### 2.8. `tests/test_settings_handler.py` — new `TestTestProviderPrefillsMaxTokens` class

**What changes:** Add a test verifying that `test_provider()` writes `max_tokens` to YAML when:
- Test Connection succeeds
- `result.context_window` is populated
- Existing `max_tokens` is the default (128_000)

**Code sample:**
```python
class TestTestProviderPrefillsMaxTokens:
    def test_success_with_context_window_prefills_default(self, tmp_config_dir, monkeypatch):
        """When max_tokens == 128_000 default and context_window is set, pre-fill."""
        from utils.provider_test import TestResult
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1"))  # max_tokens defaults to 128_000

        # Stub out test_connection to return a synthetic result
        monkeypatch.setattr(
            "ui.handlers.settings_handler.test_connection",
            lambda **kwargs: TestResult(ok=True, latency_ms=200, error=None,
                                       model_used="p1/model-v1", context_window=500_000),
        )

        # Capture callback to avoid GTK dispatch in test
        captured = {}
        h.test_provider(_make_provider("p1"), lambda r: captured.setdefault("result", r))

        # Read YAML back
        from utils.providers_store import load_providers
        providers = load_providers()
        assert providers[0].max_tokens == 500_000

    def test_success_does_not_overwrite_customized(self, tmp_config_dir, monkeypatch):
        """When max_tokens has been customized, Test Connection doesn't overwrite."""
        from utils.provider_test import TestResult
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=300_000))

        monkeypatch.setattr(
            "ui.handlers.settings_handler.test_connection",
            lambda **kwargs: TestResult(ok=True, latency_ms=200, error=None,
                                       model_used="p1/model-v1", context_window=1_000_000),
        )

        h.test_provider(_make_provider("p1"), lambda r: None)

        from utils.providers_store import load_providers
        providers = load_providers()
        assert providers[0].max_tokens == 300_000  # preserved

    def test_failure_does_not_change_max_tokens(self, tmp_config_dir, monkeypatch):
        """Failure path leaves max_tokens untouched."""
        from utils.provider_test import TestResult
        h = SettingsHandler()
        h.add_or_update(_make_provider("p1", max_tokens=200_000))

        monkeypatch.setattr(
            "ui.handlers.settings_handler.test_connection",
            lambda **kwargs: TestResult(ok=False, latency_ms=0,
                                       error="401 Unauthorized",
                                       model_used="p1/model-v1", context_window=None),
        )

        h.test_provider(_make_provider("p1"), lambda r: None)

        from utils.providers_store import load_providers
        providers = load_providers()
        assert providers[0].max_tokens == 200_000  # untouched
```

**Line count estimate:** +60 lines (3 tests).

---

### Files NOT changed

- **`agent/runtime.py`** — `_compute_model_max()` (line 1468) already reads `provider_cfg.max_tokens` and falls back to 128_000. Once the YAML has the correct value, the runtime picks it up automatically. No changes needed.
- **`utils/providers_store.py` `_to_dict()`** — explicit dict literal at lines 35-49. New field MUST be added here to be serialized. (NOT `dataclasses.asdict()` as initially thought — corrected after re-reading the source.)
- **`models/conversation.py`** — `Conversation` dataclass is unrelated to provider config; no changes needed.
- **`utils/feed_store.py`, `utils/agent_defs.py`** — these are the architecture-pattern mirrors but for different data; no changes needed.
- **`ui/handlers/auxilium_wizard_handler.py`** (lines 371, 428) — constructs `ProviderConfig(max_tokens=128_000, ...)` for OpenRouter/Ollama first-run wizards. Does not need updating: `default_max_tokens` defaults to `0`, so these constructors remain valid. If a future phase wants to populate `default_max_tokens` from caller (e.g. openrouter=128K), add it then. Out of scope for this spec.

---

## 3. Data Flow

### Flow A: First-time provider setup

```
User clicks "+ Add Provider"
    → SettingsDialog._on_add_provider_clicked
    → _ProviderCard(dialog, None) — new card with empty fields
    → _max_tokens_spin default value: 128_000 (from dataclass default)
User fills name/base_url/api_key/default_model
    → Each entry's signal handler updates the field
User clicks "Save"
    → _on_save_clicked
    → _collect_from_form() — includes max_tokens from spin
    → handler.add_or_update(provider)
    → save_providers([...])
    → YAML now has provider with max_tokens: 128000
```

### Flow B: Test Connection pre-fills context window

```
User clicks "Test Connection"
    → _on_test_clicked
    → _collect_from_form() (current form values)
    → handler.test_provider(provider, _on_test_result)
    → daemon thread:
        test_connection(base_url, api_key, model, caller)
            POST /chat/completions → ok=True
            GET /v1/models → context_window=1_000_000
        result = TestResult(ok=True, latency_ms=200, error=None,
                            model_used=..., context_window=1_000_000)
        load_providers()
        find matching provider, replace with new ProviderConfig(...):
            max_tokens = result.context_window if (ok and customized == False) else p.max_tokens
        save_providers([...])
        → GLib.idle_add(_dispatch)
    → _dispatch (main thread):
        on_result(result) → _on_test_result
            _set_status("✅ 200ms · context: 1,000,000")
            if context_window and p.max_tokens == 128_000:
                self._max_tokens_spin.set_value(1_000_000)
        on_status_changed() → callback chain to update toolbar indicator
```

### Flow C: User edits max_tokens manually

```
User opens Settings, types 500000 in Context Window spin
    → SpinButton value-changed signal updates internal value
    → _is_dirty() returns True (spin != p.max_tokens)
User clicks "Save"
    → _on_save_clicked
    → _collect_from_form() — max_tokens=500000
    → handler.add_or_update(...)
    → save_providers([...])
    → YAML now has max_tokens: 500000
    → _compute_model_max reads 500000 next runtime call
```

### Flow D: User has customized max_tokens; Test Connection does NOT overwrite

```
User has provider with max_tokens=300000 (customized)
User clicks "Test Connection"
    → ... (Flow B continues)
    → handler: max_tokens = p.max_tokens (300000) — preserved, NOT overwritten
    → YAML still has max_tokens: 300000
    → _on_test_result: p.max_tokens != 128_000, so spin NOT pre-filled
```

---

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `models/providers.py` | Add field | +1 | Low — additive, default 0 |
| `utils/providers_store.py` | Update `_to_dict()` AND `_from_dict()` | +2 | Low — backward-compatible defaults |
| `utils/provider_test.py` | Add field + probe | +35 | Medium — new network call, must not break existing tests |
| `ui/handlers/settings_handler.py` | Conditional `max_tokens` in reconstruction | +1 | Low — additive in expression |
| `ui/views/settings_dialog.py` | New SpinButton + 4 method updates | +30 | Medium — UI changes; need GTK tests |
| `tests/test_provider_test.py` | New test class | +60 | Low — additive tests |
| `tests/test_settings_dialog.py` | New test class | +60 | Low — additive tests |
| `tests/test_settings_handler.py` | New test class | +60 | Low — additive tests |

**Total:** ~248 lines added across 8 files. No public API breakage (all changes additive with defaults).

---

## 5. Implementation Order

Numbered for safe incremental builds. Each step ends with a verification check.

1. **`models/providers.py` — add `default_max_tokens` field.** Verify with `python3 -c "from models.providers import ProviderConfig; p = ProviderConfig(name='x', base_url='x', api_key='x', default_model='x'); assert p.default_max_tokens == 0; print('OK')"`.

2. **`utils/providers_store.py` — update `_to_dict()` AND `_from_dict()`.** Verify by running existing `tests/test_providers_store.py::TestLoadSave` — must still pass with no changes (default 0 is backward-compatible).

3. **`utils/provider_test.py` — add `context_window` field to `TestResult`.** Verify by importing and instantiating: `TestResult(ok=True, latency_ms=0, error=None, model_used='x').context_window is None`. Existing tests must still pass.

4. **`utils/provider_test.py` — add /v1/models probe.** Add the new `tests/test_provider_test.py::TestModelsEndpointProbe` class. Run pytest on that file — all tests must pass.

5. **`ui/handlers/settings_handler.py` — pre-fill `max_tokens` on success.** Add `tests/test_settings_handler.py::TestTestProviderPrefillsMaxTokens`. Run pytest — must pass.

6. **`ui/views/settings_dialog.py` — add SpinButton.** Update `_build_widgets`, `_populate_from_provider`, `_collect_from_form`, `_is_dirty`, `_on_test_result`. Add `tests/test_settings_dialog.py::TestMaxTokensSpinButton`. Run pytest — must pass.

7. **Integration check.** Run the full test suite (`pytest tests/`) and confirm zero regressions. Manually exercise: add a new provider, save with default 128000, click Test Connection, confirm spin updates if /v1/models returns data.

---

## 6. Acceptance Criteria

- [ ] `ProviderConfig.default_max_tokens == 0` when not set.
- [ ] YAML without `default_max_tokens` key loads successfully (backward compat).
- [ ] `TestResult.context_window is None` when `/v1/models` returns no match, errors, or 404.
- [ ] `TestResult.context_window` is an `int` when the probe succeeds.
- [ ] `test_provider()` writes `max_tokens` from `result.context_window` when `result.ok` AND existing `max_tokens == 128_000`.
- [ ] `test_provider()` preserves existing `max_tokens` when result is failure OR user has customized it.
- [ ] Settings dialog SpinButton renders on every provider card.
- [ ] SpinButton pre-fills from stored `max_tokens` on dialog open.
- [ ] SpinButton pre-fills from `result.context_window` on Test Connection success (only when stored is default).
- [ ] SpinButton value is included in `_collect_from_form()` and persisted to YAML on Save.
- [ ] `_is_dirty()` returns True when spin is edited.
- [ ] All existing tests still pass.

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| `/v1/models` returns 404 | `TestResult.context_window = None`, `ok` stays True |
| `/v1/models` returns valid JSON but no matching model ID | `context_window = None` |
| `/v1/models` returns model with `context_window` as string `"128000"` | Coerce to int via `int(...)`; if fails, `context_window = None` |
| `/v1/models` request times out | `context_window = None`, `ok` stays True (POST already succeeded) |
| User customized `max_tokens=128000` (exactly default) | Treated as not-customized; next Test Connection will overwrite. Acceptable per design: 128K is a valid value, and explicit Save preserves it. |
| User clicks Test Connection while another test is in flight | Same as today: status label gets stomped by whichever result arrives first. No regression. |
| `/v1/models` returns `data` as a list of dicts but no `id` field | Model not matched, `context_window = None` |
| `SpinButton.get_value()` returns float | Cast to `int()` before passing to `ProviderConfig(max_tokens=...)` — `ProviderConfig` declares `max_tokens: int` |
| `caller_label` text — adding SpinButton doesn't break card layout | Yes; vbox appends new row below caller_row; layout still flows vertically. Card height grows but window has scroll. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update these sections in `docs/ARCHITECTURE.md`:

- **§3.21q (LLM providers):** Add note: "Provider context window (`max_tokens`) is auto-discovered via the OpenAI-compatible `/v1/models` endpoint on Test Connection success. The value is pre-filled only when the stored value equals the 128_000 default; user customizations are preserved. The user can also edit the value directly in the Settings dialog."
- **§4.15 (`max_tokens` resolution):** No change — `_compute_model_max()` resolution order stays the same.
- **§3.21q.5b (KB Provider):** No change — KB provider registration uses default 128_000, which is fine for the local-kb context.

---

## 9. Spec Self-Audit (Rule 9)

Verified by re-reading source files and tracing every code sample:

1. **Every code sample traces against the actual codebase.** All field additions verified by reading `models/providers.py:18-32` and `utils/provider_test.py:51-56`. The `_collect_from_form` reconstruction matches `settings_handler.py:154-167` field order. The `_on_test_result` extension preserves the existing status-label pattern from `settings_dialog.py:238-242`.
2. **Exception types covered in `test_connection` probe.** `urllib.error.URLError` (base for HTTPError too), `TimeoutError`, `json.JSONDecodeError`, `KeyError`, `OSError`, `ValueError` — all subclasses of `Exception` that the new probe can raise.
3. **Key structures verified.** `_from_dict()` uses `dict.get()` with defaults — adding a new key with default 0 is backward-compatible. `_to_dict()` is an explicit dict literal — new field MUST be added there too. (Initial spec incorrectly assumed `dataclasses.asdict()`; corrected after re-read.)
4. **Data flow traced end-to-end.** All 4 flows (A: first setup, B: pre-fill, C: manual edit, D: preservation) traced through actual handler/view/persistence layer.
5. **An implementer following this spec would produce working code.** Field order, defaults, sentinel value (128_000), and callback signatures all match existing patterns.

One concern flagged during self-audit: the `_collect_from_form` source shows `"api_key": self._…p()` (line 179 in source — appears truncated). I am reading the FULL field as `self._api_key_entry.get_text()` based on the variable assigned in `_build_widgets` (line 60). The spec's code sample is correct; the source's `_collect_from_form` line 179 looks corrupted in the read output but the rest of the method is well-formed and uses `get_text()` consistently. **Action for implementer:** verify `_collect_from_form`'s `api_key` line is correct in your local checkout before copying the pattern.

---

## 10. Completion Verification (Rule 10)

**1. Scope checklist:**

```
[ ] models/providers.py — add default_max_tokens field
[ ] utils/providers_store.py — _from_dict fallback for new field
[ ] utils/provider_test.py — TestResult.context_window + /v1/models probe
[ ] ui/handlers/settings_handler.py — pre-fill max_tokens on success
[ ] ui/views/settings_dialog.py — SpinButton in 5 methods
[ ] tests/test_provider_test.py — TestModelsEndpointProbe class
[ ] tests/test_settings_dialog.py — TestMaxTokensSpinButton class
[ ] tests/test_settings_handler.py — TestTestProviderPrefillsMaxTokens class
```

**2. Test suite:** Run `pytest tests/test_providers_store.py tests/test_provider_test.py tests/test_settings_dialog.py tests/test_settings_handler.py -v` after implementation. Paste the actual output in the report.

**3. Pattern sweep:** `grep -rn "max_tokens=128_000" --include="*.py"` should show ONE remaining hit in `models/providers.py` (the field default) and ONE in `agent/runtime.py:_compute_model_max()` (the FALLBACK constant). All other occurrences should reference the new SpinButton, the new field default `0`, or be commented.

**4. Declaration:** Complete only when all three checks pass.
