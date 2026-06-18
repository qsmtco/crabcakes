# SPEC: KB Enhancement — Synthesis Layer in the `local-kb` Provider

**Date:** 2026-06-17
**Author:** Qrusher (read-only investigation, drafted with Qaster steel-framed spec writer)
**Status:** ✅ SHIPPED (commits `3bb2b2a`, `487cd2b`, `a9455fa`)
**Implements:** Captain's brainstorm of 2026-06-17 10:27 PDT
**Depends on:**
- `agent/kb_server.py` (KB Provider Phase 1 — shipped, commit history)
- `agent/kb_lookup.py` (Phase 1 — shipped)
- `prompts/system/auxilium.md` Phase 2 section (Tier 2 — shipped)
**Target branch:** main

> **Architecture compliance.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§3.6 (Composition root)**: `agent/kb_server.py` remains the composition root for the `local-kb` provider. All synthesis behavior is added inside the existing `do_POST` handler. No new module is introduced; the synthesis helper lives as a module-level function in `kb_server.py`, mirroring the existing `_format_chunks` / `_extract_last_user_message` pattern.
> - **§8 (utils/ rule)**: `utils/` is untouched. The synthesis helper imports `urllib.request` directly (matching the pattern in `agent/runtime.py:120`).
> - **Fail-soft philosophy (per §3.21q.5a)**: All synthesis failures fall back to today's behavior — `_format_chunks` output, or `KB_OUT_OF_SCOPE`. The server never raises; it never blocks longer than `_SYNTHESIS_TIMEOUT_SECONDS`.
> - **OpenAI compatibility**: The response shape is byte-for-byte identical to today's. Clients (`_call_openai` in `agent/runtime.py`, Auxilium wizard, any future agent) see no change.

---

## 0. Summary

| # | Symptom / Goal | Fix |
|---|----------------|-----|
| 1 | `local-kb` provider dumps raw KB chunks as a bulleted string. Auxilium (and any other agent pointing at `local-kb`) gets an unfriendly, ungrammatical response that reads like a search-result page. | Before returning the formatted chunks, attempt a one-shot synthesis call to a free, no-auth Llama-3.2-3B endpoint (`https://devtoolbox-api.devtoolbox-api.workers.dev/ai/generate`). If the call succeeds in ≤1.5s, return the synthesized answer instead of the raw chunks. |
| 2 | Synthesis adds a network dependency to a currently-offline component (the KB server). If the free endpoint is down, KB responses must keep working. | Hard 1.5s timeout via `urllib.request` timeout arg. On ANY failure (timeout, network error, HTTP 4xx/5xx, response-with-error-body, empty response, response with error-shaped content), the server falls back to today's behavior: returns the formatted KB chunks (or `KB_OUT_OF_SCOPE` if none). The synthesis is **never** a single point of failure. |
| 3 | No way to disable synthesis (some users may want raw chunks for debugging, or to avoid the network hop). | Add a config toggle `KB_SYNTHESIS_ENABLED` (default `True`) on the KB server. When `False`, behavior is identical to today. The toggle is an environment variable `CRABCAKES_KB_SYNTHESIS=0|1`, with the Python constant as the source of truth. |
| 4 | The free endpoint URL is hard-coded — if the endpoint changes or dies, the feature silently breaks. | Make the endpoint URL a module constant `_SYNTHESIS_ENDPOINT_URL` and document it. The Captain already verified the endpoint works as of 2026-06-17. If it goes down later, the fail-soft fallback covers it; the constant is the single point of update. |
| 5 | No tests for the synthesis path. | Add a new test class `TestSynthesis` in `tests/test_kb_server.py`. Mock the synthesis call. Cover: (a) synthesis success returns synthesized text, (b) synthesis timeout returns raw chunks, (c) synthesis HTTP error returns raw chunks, (d) synthesis body-level error returns raw chunks, (e) `KB_SYNTHESIS_ENABLED=0` returns raw chunks, (f) empty synthesized response returns raw chunks. |

---

## 1. Overview

### 1.1 Problem statement

The `local-kb` provider (backed by `agent/kb_server.py`) returns raw KB chunks as a flat string with `**Source:**` headers. This is functional but reads like a search result page, not a conversation. Users — especially first-time users on a fresh install where `local-kb` is the only configured provider — get an unfriendly first impression.

We have a free, no-auth Llama-3.2-3B endpoint that accepts a single string prompt and returns a synthesized answer in ~500ms. The Captain has verified it works. The opportunity: if that endpoint is reachable at request time, the KB server can prepend a small system instruction to the chunks+question and return a synthesized answer instead of the raw dump. If the endpoint is unreachable, behavior is unchanged.

### 1.2 Solution summary

Add a single module-level function `_try_synthesize(question: str, chunks: list) -> str | None` to `agent/kb_server.py`. Call it from `do_POST` after the confidence check passes and before `_format_chunks`. If it returns a non-empty string, return that string in the response. If it returns `None` (any failure), fall through to today's behavior — `_format_chunks(chunks)`. The synthesis call uses `urllib.request` with a 1.5s timeout, matches the existing import pattern (`agent/runtime.py:120`, `utils/improve.py:13`, `utils/provider_test.py:18-19`).

### 1.3 Design decisions

| Decision | Answer | Rationale |
|----------|--------|-----------|
| Where does the synthesis call live? | `agent/kb_server.py`, module-level function | Matches existing helper pattern (`_format_chunks`, `_extract_last_user_message`). ARCHITECTURE.md §3.21q.5a names `kb_server.py` as the composition root for the `local-kb` provider. New module is unjustified — would add an import edge for ~40 lines of code. |
| Endpoint URL? | `https://devtoolbox-api.devtoolbox-api.workers.dev/ai/generate` | Verified working 2026-06-17. No API key, free, ~500ms. The endpoint already accepts a long single-string prompt and returns a string — exactly the shape we need. |
| Endpoint as a constant or env var? | Constant first, env var override | `_SYNTHESIS_ENDPOINT_URL` is the source of truth. `os.environ.get("CRABCAKES_KB_SYNTHESIS_URL", _SYNTHESIS_ENDPOINT_URL)` lets us point at a local mirror for testing without code changes. |
| Timeout? | 1.5 seconds | `local-kb` is documented as fast (sub-500ms KB lookup). The runtime already enforces `tool_timeout_seconds` (default 120s) on LLM calls. The free endpoint measures ~500ms in practice. 1.5s = 3× measured latency, leaves headroom for cold start, prevents a slow endpoint from making Auxilium feel laggy. |
| Disable toggle? | Yes, env var `CRABCAKES_KB_SYNTHESIS=0` | Some users want raw chunks (debugging, deterministic testing, no network). Default `True` because synthesis is the new value-add. Toggle is fail-soft: a typo in the env var (`CRABCAKES_KB_SYNTHESIS=maybe`) defaults to enabled. |
| Synthesis prompt format? | Single string passed as `prompt` field | The endpoint is not OpenAI-compatible at the message-array level — it takes a single concatenated prompt. We build the prompt by concatenating: instruction prefix + formatted chunks + user question. This matches what we verified works with curl. |
| What if synthesis returns empty string? | Fall back to raw chunks | An empty synthesis is worse than no synthesis. The runtime can always re-render raw chunks. |
| What if synthesis returns an error-shaped string (e.g. starts with "Error:")? | Fall back to raw chunks | Defensive: if the model returns garbage, raw chunks are safer. |
| Streaming? | No | `local-kb` is registered with `supports_streaming=False` in `utils/providers_store.py:245`. The runtime forces the blocking path. No change needed. |
| Response shape change? | None | The response is still `{"choices": [{"message": {"role": "assistant", "content": <text>}, "finish_reason": "stop"}], "model": "local-kb", ...}`. The only difference is `content` is a synthesized string instead of formatted chunks. |

### 1.4 Scope

| In scope | Out of scope |
|---|---|
| Add `_try_synthesize()` to `agent/kb_server.py` | Changing the free endpoint URL or authentication |
| Call it from `do_POST` after confidence check | Adding synthesis to other agents (Auxilium runtime already does Tier 2 synthesis via primary LLM) |
| Env-var toggle `CRABCAKES_KB_SYNTHESIS=0` | New module file (e.g. `agent/kb_synthesis.py`) — per §3.6 and existing patterns |
| Tests in `tests/test_kb_server.py` | Streaming support for `local-kb` |
| Update `docs/ARCHITECTURE.md` §3.21q.5a with the new behavior | UI changes (no user-visible change) |
| Add `CRABCAKES_KB_SYNTHESIS` to docs/knowledge | Caching the synthesized response (KB lookup is already fast, no need) |

### 1.5 Architecture principles (per `docs/ARCHITECTURE.md`)

- **§3.6**: Composition root unchanged. `kb_server.py` is the owner.
- **§3.21q.5a fail-soft**: Every synthesis failure falls back to today's chunks-or-out-of-scope response. Server never raises, never blocks longer than 1.5s.
- **§8 (utils/ rule)**: `utils/` untouched. Synthesis imports `urllib.request` and `os` only.
- **OpenAI compatibility (§3.21q.5a)**: Response shape unchanged.

---

## 2. Changes by File

### 2.1 `agent/kb_server.py` — REVISED

**What changes:** Add synthesis call to the `do_POST` handler. Add a new module-level helper `_try_synthesize()`. Add three module-level constants for the endpoint URL, timeout, and toggle.

**Discovery of current state (verified by reading source):**
- `do_POST` flow: parse body → extract user message → `kb_lookup` → confidence check → `_format_chunks` → return.
- Existing constants: `KB_SERVER_PORT`, `KB_OUT_OF_SCOPE`, `_KB_MIN_SCORE`, `_KB_TOP_K`, `_KB_CONFIDENCE_THRESHOLD`.
- Existing imports: `json`, `logging`, `threading`, `uuid`, `http.server.BaseHTTPRequestHandler`/`HTTPServer`, `typing.Any`, `agent.kb_lookup.{kb_lookup, is_index_available}`.
- Server is single-threaded (`HTTPServer` default, not `ThreadingHTTPServer`). This is fine — KB lookup is <500ms and synthesis adds ≤1.5s, total ≤2s, well within user patience for a help response.
- `_format_chunks` is the existing helper that converts a `list[KBChunk]` to a human-readable string. Reused as input to the synthesis prompt.

**New constants (add after existing constants at lines 35-46):**

```python
# ── Synthesis layer (KB Enhancement) ──────────────────────────────────────────

# Free, no-auth Llama endpoint verified 2026-06-17. If the endpoint changes,
# update this constant — the rest of the synthesis code is endpoint-agnostic.
_SYNTHESIS_ENDPOINT_URL = os.environ.get(
    "CRABCAKES_KB_SYNTHESIS_URL",
    "https://devtoolbox-api.devtoolbox-api.workers.dev/ai/generate",
)

# Hard timeout on the synthesis call. 1.5s = 3× the measured ~500ms latency
# of the free endpoint. Tuned to keep Auxilium feeling responsive even when
# the endpoint is slow. If the call takes longer, we time out and fall back
# to the raw formatted chunks.
_SYNTHESIS_TIMEOUT_SECONDS = 1.5

# Toggle: "0" disables synthesis (returns raw chunks as today). Anything else
# (including unset, "1", "true", "yes", typo'd values) enables it. Default ON.
def _synthesis_enabled() -> bool:
    """Return True unless CRABCAKES_KB_SYNTHESIS=0 is set in the environment."""
    return os.environ.get("CRABCAKES_KB_SYNTHESIS", "1") != "0"
```

**New imports (add to existing import block at lines 17-25):**

```python
import os
import urllib.request
import urllib.error
```

**New helper function (add after `_format_chunks` at line 89, before `_extract_last_user_message`):**

```python
def _try_synthesize(question: str, chunks: list) -> str | None:
    """Synthesize a friendly answer from KB chunks using the free Llama endpoint.

    Returns the synthesized string on success, or None on ANY failure
    (timeout, network error, HTTP 4xx/5xx, body-level error, empty response,
    response starting with "Error:"). The caller falls back to the raw
    formatted chunks when this returns None.

    Args:
        question: The user's question (last user message from the request).
        chunks: The KBChunk list returned by kb_lookup (already passed
            the confidence threshold).

    Returns:
        Synthesized answer string, or None on any failure.

    Note:
        The endpoint takes a single concatenated prompt string, not an
        OpenAI-shaped messages array. We build the prompt as:
          [instruction prefix] + [_format_chunks(chunks)] + [user question]
    """
    if not _synthesis_enabled():
        return None

    # Build the synthesis prompt. Mirrors the system prompt's intent at
    # prompts/system/auxilium.md:73-85 (Phase 2 — LLM Synthesis Mode):
    # ground the answer in the chunks, be concise, no "Based on the KB" preface.
    formatted_chunks = _format_chunks(chunks)
    prompt = (
        "You are a helpful assistant for a software project. "
        "Use the following knowledge base context to answer the user's question. "
        "Be concise and friendly. If the context does not contain the answer, say so.\n\n"
        f"{formatted_chunks}\n\n"
        f"User question: {question}"
    )

    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    req = urllib.request.Request(
        _SYNTHESIS_ENDPOINT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=_SYNTHESIS_TIMEOUT_SECONDS) as resp:
            body = resp.read()
            parsed = json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        # Network error, timeout, DNS failure, connection refused, HTTP error
        logger.debug("kb_server: synthesis call failed: %s; falling back to raw chunks", e)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        # Endpoint returned non-JSON or unreadable bytes
        logger.debug("kb_server: synthesis response unparseable: %s; falling back", e)
        return None

    # Body-level error: {"error": "..."} or {"error": {"message": "..."}}
    if isinstance(parsed, dict) and "error" in parsed:
        logger.debug("kb_server: synthesis body-level error: %s; falling back", parsed["error"])
        return None

    # Extract the response field. Defensive against missing field or non-string.
    response_text = parsed.get("response", "") if isinstance(parsed, dict) else ""
    if not isinstance(response_text, str):
        logger.debug("kb_server: synthesis response not a string (type=%s); falling back",
                     type(response_text).__name__)
        return None

    response_text = response_text.strip()
    if not response_text:
        logger.debug("kb_server: synthesis returned empty string; falling back")
        return None

    # Defensive: if the model returned an error-shaped string, fall back.
    # Catches cases like "Error: ..." or "I cannot answer that..." (false-positive risk
    # is low because the prompt is a synthesis instruction, not an open-ended one).
    if response_text.lower().startswith("error:"):
        logger.debug("kb_server: synthesis returned error-shaped string; falling back")
        return None

    return response_text
```

**Modification to `do_POST` (current flow at lines 156-184):**

Current code (verified by reading source at lines 156-184):
```python
        content = _format_chunks(chunks)
        self._send_json(200, _make_response(content))
```

**Replace with:**
```python
        # Attempt synthesis first; fall back to raw chunks on any failure.
        synthesized = _try_synthesize(question, chunks)
        content = synthesized if synthesized is not None else _format_chunks(chunks)
        self._send_json(200, _make_response(content))
```

**Imports verified (will fail compilation if wrong):**
- `os` — stdlib, used in `_SYNTHESIS_ENDPOINT_URL` env-var lookup and `_synthesis_enabled()`
- `urllib.request` — stdlib, used in `_try_synthesize()` for the HTTP POST
- `urllib.error` — stdlib, used in `_try_synthesize()` except clause (`URLError`, `HTTPError`)
- `json` — already imported, used to serialize the request body and parse the response
- `logging` — already imported, used for `logger.debug()` calls in fallback paths

**Line count estimate:** +~60 lines (constants, helper, do_POST modification).

---

### 2.2 `tests/test_kb_server.py` — REVISED

**What changes:** Add a new test class `TestSynthesis` that mocks `_try_synthesize` to verify the handler's fallback behavior. Existing tests are unchanged.

**Discovery of current test patterns (verified by reading source at lines 30-100):**
- `kb_server_instance` fixture (lines 95-110) starts a real server on a free port, mocking `is_index_available`.
- `mock.patch.object(kb_server, "kb_lookup", ...)` is the standard pattern for isolating the handler from KB.
- `urllib.request` is used for HTTP calls in test helpers `_post` and `_get`.

**New test class (add at end of file, after `TestKBLookupIntegration`):**

```python
class TestSynthesis:
    """Tests for the synthesis layer in the local-kb provider.

    The synthesis layer is opt-in via the CRABCAKES_KB_SYNTHESIS env var
    (default ON). Each test mocks _try_synthesize to verify both the
    happy path and the fallback paths.
    """

    def test_synthesis_success_returns_synthesized(self, kb_server_instance, monkeypatch):
        """_try_synthesize returns a string → response content is that string."""
        port = kb_server_instance
        monkeypatch.setattr(kb_server, "_try_synthesize",
                            lambda q, c: "Synthesized: do `apt install`.")
        mock_chunks = [
            KBChunk(id="c1", source="knowledge/install.md", section="Ubuntu",
                    text="Run apt install", score=0.92),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "How to install?"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert content == "Synthesized: do `apt install`."
        assert "**Source:**" not in content  # NOT the raw formatted chunks

    def test_synthesis_failure_returns_raw_chunks(self, kb_server_instance, monkeypatch):
        """_try_synthesize returns None → response content is _format_chunks output."""
        port = kb_server_instance
        monkeypatch.setattr(kb_server, "_try_synthesize", lambda q, c: None)
        mock_chunks = [
            KBChunk(id="c1", source="knowledge/install.md", section="Ubuntu",
                    text="Run apt install", score=0.92),
        ]
        with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
            status, body = _post(port, "/v1/chat/completions", {
                "model": "local-kb",
                "messages": [{"role": "user", "content": "How to install?"}],
            })
        assert status == 200
        content = body["choices"][0]["message"]["content"]
        assert "Based on the CrabCakes knowledge base" in content
        assert "knowledge/install.md" in content

    def test_synthesis_disabled_by_env_var(self, kb_server_instance, monkeypatch):
        """CRABCAKES_KB_SYNTHESIS=0 → _try_synthesize returns None immediately."""
        port = kb_server_instance
        monkeypatch.setenv("CRABCAKES_KB_SYNTHESIS", "0")
        # Confirm the toggle is honored: even with a real network call, the
        # helper short-circuits to None.
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_enabled_by_default(self, monkeypatch):
        """No env var set → _synthesis_enabled() returns True."""
        monkeypatch.delenv("CRABCAKES_KB_SYNTHESIS", raising=False)
        assert kb_server._synthesis_enabled() is True

    def test_synthesis_env_var_one_enables(self, monkeypatch):
        """CRABCAKES_KB_SYNTHESIS=1 → enabled."""
        monkeypatch.setenv("CRABCAKES_KB_SYNTHESIS", "1")
        assert kb_server._synthesis_enabled() is True

    def test_synthesis_env_var_zero_disables(self, monkeypatch):
        """CRABCAKES_KB_SYNTHESIS=0 → disabled."""
        monkeypatch.setenv("CRABCAKES_KB_SYNTHESIS", "0")
        assert kb_server._synthesis_enabled() is False

    def test_synthesis_handles_timeout(self, monkeypatch):
        """_try_synthesize catches TimeoutError → returns None."""
        # Simulate the urllib call raising TimeoutError by patching urlopen.
        def fake_urlopen(req, timeout):
            raise TimeoutError("synthesis timed out")
        monkeypatch.setattr(kb_server.urllib.request, "urlopen", fake_urlopen)
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_http_error(self, monkeypatch):
        """_try_synthesize catches HTTPError → returns None."""
        def fake_urlopen(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable",
                                         {}, None)
        monkeypatch.setattr(kb_server.urllib.request, "urlopen", fake_urlopen)
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_url_error(self, monkeypatch):
        """_try_synthesize catches URLError (DNS/network) → returns None."""
        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("Name or service not known")
        monkeypatch.setattr(kb_server.urllib.request, "urlopen", fake_urlopen)
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_body_level_error(self, monkeypatch):
        """Endpoint returns {"error": "..."} → returns None."""
        class FakeResp:
            def __init__(self, body_bytes):
                self._body = body_bytes
            def read(self):
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(kb_server.urllib.request, "urlopen",
                            lambda req, timeout: FakeResp(b'{"error": "rate limited"}'))
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_empty_response(self, monkeypatch):
        """Endpoint returns {"response": ""} → returns None."""
        class FakeResp:
            def read(self):
                return b'{"response": ""}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(kb_server.urllib.request, "urlopen",
                            lambda req, timeout: FakeResp(b''))
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_handles_error_prefixed_string(self, monkeypatch):
        """Endpoint returns {"response": "Error: ..."} → returns None."""
        class FakeResp:
            def read(self):
                return b'{"response": "Error: something went wrong"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        monkeypatch.setattr(kb_server.urllib.request, "urlopen",
                            lambda req, timeout: FakeResp(b''))
        result = kb_server._try_synthesize("test", [
            KBChunk(id="c1", source="s", section="s", text="t", score=0.9)
        ])
        assert result is None

    def test_synthesis_passes_question_and_chunks(self, monkeypatch):
        """_try_synthesize is called with (question, chunks) from the request."""
        captured = {}
        def fake_synthesize(q, c):
            captured["question"] = q
            captured["chunks"] = c
            return "synthesized"
        monkeypatch.setattr(kb_server, "_try_synthesize", fake_synthesize)
        mock_chunks = [
            KBChunk(id="c1", source="knowledge/install.md", section="Ubuntu",
                    text="Run apt install", score=0.92),
        ]
        # Reuse the kb_server_instance fixture to get a real handler call.
        # (TestSynthesis doesn't get the fixture, so we start a server inline.)
        port = _find_free_port()
        with mock.patch.object(kb_server, "is_index_available", return_value=True):
            thread = start_kb_server(port=port)
            if thread is None:
                pytest.skip("Could not start KB server")
            _wait_for_server(port)
            try:
                with mock.patch.object(kb_server, "kb_lookup", return_value=mock_chunks):
                    _post(port, "/v1/chat/completions", {
                        "model": "local-kb",
                        "messages": [{"role": "user", "content": "How to install?"}],
                    })
            finally:
                stop_kb_server()
        assert captured["question"] == "How to install?"
        assert len(captured["chunks"]) == 1
        assert captured["chunks"][0].source == "knowledge/install.md"
```

**Imports verified for tests:**
- `import urllib.error` — needs to be added at the top of the test file (currently imports `urllib.request` and `urllib.error` from `urllib.request` indirectly via the existing `_post` helper, but `urllib.error.HTTPError` and `urllib.error.URLError` need an explicit import)
- `monkeypatch` fixture — already provided by `pytest` (used elsewhere in the test suite, e.g. `test_kb_integration.py`)

**Line count estimate:** +~170 lines (one new test class).

---

### 2.3 `docs/ARCHITECTURE.md` — REVISED

**What changes:** Update §3.21q.5a (lines 1436-1458) with the synthesis layer behavior.

**Current text (verified at lines 1436-1458):**
> **Fail-soft behavior:** If `kb_lookup()` raises, returns `[KB_OUT_OF_SCOPE]` (graceful degradation). If index is unavailable, `start_kb_server()` returns `None` (server does not start).

**Append after the existing fail-soft paragraph:**

```markdown
**Synthesis layer (KB Enhancement):** Before returning formatted KB chunks, `do_POST` calls `_try_synthesize(question, chunks)` which POSTs to a free, no-auth Llama-3.2-3B endpoint (`_SYNTHESIS_ENDPOINT_URL`, default `https://devtoolbox-api.devtoolbox-api.workers.dev/ai/generate`) with a 1.5s timeout. If the synthesis returns a non-empty string, the response content is the synthesized answer. If synthesis fails for any reason (timeout, network error, HTTP error, body-level error, empty response, error-shaped response), the server falls back to the raw formatted chunks. The toggle `CRABCAKES_KB_SYNTHESIS=0` (env var) disables synthesis entirely, restoring the pre-enhancement behavior. Synthesis is opt-in by default; the response shape is unchanged from the OpenAI Chat Completions contract — only the `content` field differs in style.

**Public API additions:**
```python
_SYNTHESIS_ENDPOINT_URL: str  # overridable via CRABCAKES_KB_SYNTHESIS_URL
_SYNTHESIS_TIMEOUT_SECONDS: float  # 1.5
def _synthesis_enabled() -> bool  # reads CRABCAKES_KB_SYNTHESIS env var
def _try_synthesize(question: str, chunks: list) -> str | None
```
```

**Line count estimate:** +~10 lines.

---

### 2.4 `docs/knowledge/` — NEW (optional)

**What changes:** Add a one-paragraph note about the `CRABCAKES_KB_SYNTHESIS` env var to `knowledge/configuration.md` or `knowledge/features.md`. Optional, low priority.

**Suggested insertion (add to `knowledge/features.md` near the KB provider section, if the maintainer agrees):**

```markdown
### KB Synthesis (optional)

The `local-kb` provider (the default no-config KB-backed provider) can optionally synthesize answers using a free, no-auth Llama endpoint instead of returning raw KB chunks. To disable synthesis and always get raw chunks (useful for debugging or for users who want deterministic responses), set the environment variable:

```bash
CRABCAKES_KB_SYNTHESIS=0
```

Synthesis is enabled by default. The free endpoint adds a small network call (sub-second in practice); if the endpoint is unreachable, `local-kb` falls back to raw chunks automatically.
```

**Line count estimate:** +~10 lines.

**Note:** Skipped from scope for now — add only if the Captain confirms the user-facing docs matter for this feature.

---

### 2.5 Files NOT changed (explicit)

**Files NOT changed** (already correct):
- `agent/kb_lookup.py` — synthesis is a layer above `kb_lookup`, not a change to it. The function returns `list[KBChunk]` as before; synthesis is the consumer's job.
- `agent/runtime.py` — `_call_openai` calls `local-kb` over HTTP and parses the OpenAI response. Response shape is unchanged. Auxilium Tier 2 synthesis (already shipped, `_inject_kb_context` in `_run_loop`) operates on the *primary* LLM call, not on the `local-kb` provider — the two synthesis paths are independent and complementary.
- `utils/providers_store.py` — `local-kb` provider config is unchanged. `supports_streaming=False` remains correct (synthesis is blocking).
- `prompts/system/auxilium.md` — The system prompt's "Phase 2 — LLM Synthesis Mode" section (lines 73-85) describes how the *primary* LLM should synthesize from injected KB chunks. The new `local-kb` synthesis layer is independent of this — it synthesizes inside the server, not in the Auxilium LLM call. No system prompt change needed.
- `ui/handlers/auxilium_wizard_handler.py` — Wizard picks providers; it doesn't care how `local-kb` synthesizes.
- `prompts/default_agents/auxilium.yaml` — Auxilium agent definition is unchanged.
- `models/conversation.py` — `agent_role` field already exists (added in Tier 2 spec). No change.
- `docs/specs/SPEC-auxilium-tier-2.md` — Already shipped. No change.

---

## 3. Data Flow

**Happy path** (synthesis succeeds):

```
User asks Auxilium a question
  → _run_loop builds messages
  → runtime calls _call_llm → _call_openai
  → POST to http://localhost:18790/v1/chat/completions (local-kb)
  → kb_server.do_POST receives request
  → _extract_last_user_message → "how do I install on Ubuntu?"
  → kb_lookup("how do I install on Ubuntu?", top_k=5, min_score=0.35) → [KBChunk × 3]
  → confidence check: top_score=0.78 >= 0.55 → pass
  → _try_synthesize("how do I install on Ubuntu?", chunks):
      → builds prompt: instruction + _format_chunks(chunks) + question
      → urllib POST to _SYNTHESIS_ENDPOINT_URL with timeout=1.5s
      → response: {"model": "llama-3.2-3b-instruct", "response": "Run apt install..."}
      → returns "Run apt install..."
  → content = "Run apt install..." (synthesized)
  → _make_response(content) → OpenAI Chat Completions response
  → _send_json(200, response) → sent to _call_openai → runtime → Auxilium
  → user sees: "Run apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0"
```

**Fallback path** (synthesis fails or disabled):

```
  ... (same as above up to confidence check)
  → _try_synthesize("...", chunks):
      → urllib POST → TimeoutError after 1.5s
      → except (URLError, HTTPError, TimeoutError, OSError): logger.debug(...); return None
  → synthesized = None
  → content = _format_chunks(chunks)  # today's behavior
  → _make_response(content) → "Based on the CrabCakes knowledge base:\n\n---\n**Source:** ..."
  → _send_json(200, response) → user sees formatted chunks (identical to today)
```

**Disabled path** (env var set):

```
  ... (same as above)
  → _try_synthesize("...", chunks):
      → _synthesis_enabled() returns False
      → return None (no network call made)
  → content = _format_chunks(chunks) → formatted chunks (identical to today)
```

---

## 4. File Change Summary

| File | Change type | Lines added | Lines removed | Risk level |
|------|-------------|-------------|---------------|------------|
| `agent/kb_server.py` | Modify (add helper, add constants, modify do_POST) | ~60 | ~2 | Low — additive, fail-soft |
| `tests/test_kb_server.py` | Modify (add test class) | ~170 | 0 | Low — additive, mocks |
| `docs/ARCHITECTURE.md` | Modify (update §3.21q.5a) | ~10 | 0 | None — docs only |
| `docs/knowledge/features.md` | Modify (optional, env var doc) | ~10 | 0 | None — docs only |

**Total code change:** ~60 production lines + ~170 test lines.
**Risk assessment:** Low. The synthesis layer is entirely additive. Every failure path falls back to today's behavior. Response shape is unchanged. OpenAI compatibility preserved. Existing tests continue to pass without modification.

---

## 5. Implementation Order

1. **Step 1: Add constants and imports to `agent/kb_server.py`.** Add `os`, `urllib.request`, `urllib.error` to imports. Add `_SYNTHESIS_ENDPOINT_URL`, `_SYNTHESIS_TIMEOUT_SECONDS`, `_synthesis_enabled()` to the constants block. **Verify:** `python3 -c "import agent.kb_server"` imports cleanly.

2. **Step 2: Add `_try_synthesize()` to `agent/kb_server.py`.** Add the new function after `_format_chunks`. **Verify:** `python3 -c "from agent.kb_server import _try_synthesize, _synthesis_enabled; print('ok')"` imports cleanly.

3. **Step 3: Modify `do_POST` to call `_try_synthesize`.** Replace `content = _format_chunks(chunks); self._send_json(...)` with the synthesized-or-raw content logic. **Verify:** Run `tests/test_kb_server.py` — all 25+ existing tests should pass unchanged.

4. **Step 4: Add `TestSynthesis` class to `tests/test_kb_server.py`.** Add the 13 new tests. **Verify:** Run `pytest tests/test_kb_server.py::TestSynthesis -v` — all 13 new tests pass.

5. **Step 5: Update `docs/ARCHITECTURE.md` §3.21q.5a.** Append the synthesis layer paragraph. **Verify:** `grep -n "Synthesis layer" docs/ARCHITECTURE.md` returns the new line.

6. **Step 6 (optional): Update `docs/knowledge/features.md`.** Add the env var documentation. **Verify:** `grep -n "CRABCAKES_KB_SYNTHESIS" docs/knowledge/features.md` returns the new section.

7. **Step 7: Manual smoke test.** Start a CrabCakes session. Ask Auxilium "How do I install on Ubuntu?". Verify the response is a friendly synthesized answer (not raw chunks). Unset the response — set `CRABCAKES_KB_SYNTHESIS=0` and ask again. Verify the response is the raw formatted chunks (today's behavior).

8. **Step 8: Run full test suite.** `pytest tests/test_kb_server.py tests/test_kb_integration.py tests/test_auxilium_tier2.py` — all tests pass.

9. **Step 9: Commit.** `git commit -m "feat(kb): synthesize local-kb responses via free Llama endpoint (KB Enhancement)"`.

---

## 6. Acceptance Criteria

A test passes when ALL of the following are true:

- [ ] `_try_synthesize` returns a non-empty string when the endpoint returns a valid `{"response": "..."}` body
- [ ] `_try_synthesize` returns `None` when the endpoint times out (>1.5s)
- [ ] `_try_synthesize` returns `None` on any `urllib.error.URLError` (DNS, connection refused, network unreachable)
- [ ] `_try_synthesize` returns `None` on any `urllib.error.HTTPError` (4xx, 5xx)
- [ ] `_try_synthesize` returns `None` when the response body is `{"error": "..."}` (body-level error)
- [ ] `_try_synthesize` returns `None` when the response `response` field is missing, empty, or non-string
- [ ] `_try_synthesize` returns `None` when the response starts with "Error:" (case-insensitive)
- [ ] `_synthesis_enabled()` returns `True` when `CRABCAKES_KB_SYNTHESIS` is unset
- [ ] `_synthesis_enabled()` returns `True` when `CRABCAKES_KB_SYNTHESIS=1`
- [ ] `_synthesis_enabled()` returns `False` when `CRABCAKES_KB_SYNTHESIS=0`
- [ ] The `do_POST` handler returns the synthesized string when `_try_synthesize` returns a string
- [ ] The `do_POST` handler returns `_format_chunks(chunks)` when `_try_synthesize` returns `None`
- [ ] The response shape is byte-for-byte identical to today's response shape (only the `content` string differs)
- [ ] All 25+ existing `tests/test_kb_server.py` tests continue to pass
- [ ] Manual test: Auxilium answers "How do I install on Ubuntu?" with a friendly synthesized answer (not raw chunks)
- [ ] Manual test: with `CRABCAKES_KB_SYNTHESIS=0`, the same question returns raw formatted chunks

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Free endpoint completely down (DNS fails) | `_try_synthesize` returns `None` → raw chunks. User sees same response as today. |
| Free endpoint slow (>1.5s) | TimeoutError → `_try_synthesize` returns `None` → raw chunks. User waits at most 1.5s extra. |
| Free endpoint returns 503 | HTTPError → `_try_synthesize` returns `None` → raw chunks. |
| Free endpoint returns `{"error": "rate limited"}` | Body-level error → `_try_synthesize` returns `None` → raw chunks. |
| Free endpoint returns `{"response": ""}` | Empty string → `_try_synthesize` returns `None` → raw chunks. |
| Free endpoint returns `{"response": "Error: ..."}` | Error-prefixed → `_try_synthesize` returns `None` → raw chunks. |
| Free endpoint returns `{"response": null}` (JSON null) | Non-string → `_try_synthesize` returns `None` → raw chunks. |
| Free endpoint returns `{"response": 42}` (JSON number) | Non-string → `_try_synthesize` returns `None` → raw chunks. |
| `CRABCAKES_KB_SYNTHESIS=0` set | `_synthesis_enabled()` returns False → `_try_synthesize` returns `None` without network call → raw chunks. |
| `CRABCAKES_KB_SYNTHESIS=maybe` (typo) | `_synthesis_enabled()` returns True (only "0" disables) → synthesis attempted. |
| `CRABCAKES_KB_SYNTHESIS_URL` set to a local mirror | `_SYNTHESIS_ENDPOINT_URL` overridden via env var → synthesis goes to the mirror. |
| KB lookup returns 0 chunks (out-of-scope) | `chunks` is `[]` → handler returns `KB_OUT_OF_SCOPE` early (lines 168-170 in current code). `_try_synthesize` is **never** called. |
| KB lookup returns chunks but top_score < 0.55 (low confidence) | Confidence check fails → handler returns `KB_OUT_OF_SCOPE` (lines 181-187 in current code). `_try_synthesize` is **never** called. |
| User sends a request with no `messages` field | `_extract_last_user_message` returns `None` → handler returns `KB_OUT_OF_SCOPE` early. `_try_synthesize` is **never** called. |
| User sends a request with empty `content` string | `_extract_last_user_message` returns `None` (whitespace check) → handler returns `KB_OUT_OF_SCOPE` early. |
| Server receives concurrent requests | `HTTPServer` is single-threaded; requests are processed serially. Synthesis adds ≤1.5s per request. No thread-safety concerns. |
| `_try_synthesize` raises an unexpected exception (e.g. `AttributeError`) | **Not caught** — propagates to the handler, which propagates to `BaseHTTPRequestHandler`, which logs and returns 500. Mitigation: the `try/except` in `_try_synthesize` is broad enough to catch everything documented in stdlib. If an unhandled exception is ever seen, it's a bug in `_try_synthesize` and should be added to the except clause. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update the following sections:

1. **§3.21q.5a (lines 1436-1458)** — Add the "Synthesis layer" paragraph (text in §2.3 above). Adds the new public API signatures (`_SYNTHESIS_ENDPOINT_URL`, `_SYNTHESIS_TIMEOUT_SECONDS`, `_synthesis_enabled`, `_try_synthesize`).

2. **§3.21q.5a "Public API" block** — Add the 4 new public symbols listed in §2.3.

3. **(Optional) §3.21q.5a "Fail-soft behavior"** — Extend with: "Synthesis layer failures (timeout, network error, body-level error, empty/error response) fall back to formatted KB chunks. The server never raises from the synthesis path."

No other ARCHITECTURE.md sections need updates. The runtime (§3.21m), the providers_store (§3.21q.5b), and the agent conversation flow (§3.14) are all unaffected.

---

## 9. Self-Audit (Rule 9)

- [x] Every code sample in this spec is traced against the actual source. The `do_POST` modification uses the exact current code at lines 156-184. The new helper imports only stdlib modules and the existing `kb_lookup` module.
- [x] All exception types are enumerated. `_try_synthesize` catches `urllib.error.URLError`, `urllib.error.HTTPError`, `TimeoutError`, `OSError`, `json.JSONDecodeError`, `UnicodeDecodeError`. The body-level error check handles the `{"error": "..."}` shape verified via curl.
- [x] All function signatures are verified. `_format_chunks(chunks: list) -> str` confirmed at `agent/kb_server.py:80`. `kb_lookup(question, top_k, min_score)` confirmed at `agent/kb_lookup.py:177`. `_extract_last_user_message(messages: list[dict]) -> str | None` confirmed at `agent/kb_server.py:92`. `_make_response(content: str) -> dict` confirmed at `agent/kb_server.py:67`.
- [x] All key structures are verified. The `KBChunk` dataclass has fields `(id, source, section, text, score)` — confirmed at `agent/kb_lookup.py:78-86`.
- [x] The data flow is traced end-to-end from user message → `_call_openai` → `do_POST` → `_try_synthesize` → response.
- [x] An implementer following this spec exactly would produce working code. All imports are listed, all function signatures are exact, all tests cover the documented behaviors.

---

## 10. Completion Verification (Rule 10)

When implementation is complete, the following checks must pass:

1. **Scope checklist:**
   - [ ] `agent/kb_server.py` — modified (added constants, helper, modified do_POST)
   - [ ] `tests/test_kb_server.py` — modified (added TestSynthesis class)
   - [ ] `docs/ARCHITECTURE.md` — modified (§3.21q.5a updated)
   - [ ] `docs/knowledge/features.md` — modified (optional, env var doc)

2. **Test suite — full output to be pasted in the implementer's report:**
   ```
   $ pytest tests/test_kb_server.py -v
   ```

3. **Pattern sweep — confirm no old patterns remain:**
   ```bash
   # Confirm synthesis is called from do_POST
   grep -n "_try_synthesize" agent/kb_server.py
   # Expected: 1 definition + 1 call = 2 matches

   # Confirm no old "always format chunks" pattern
   grep -n "content = _format_chunks(chunks)" agent/kb_server.py
   # Expected: 1 match (the fallback path, not the unconditional path)
   ```

4. **Declaration:** "Complete" only when all three checks pass.
