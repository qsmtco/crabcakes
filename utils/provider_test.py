# utils/provider_test.py
# Test Connection — verify an LLM provider API key by sending a minimal request.
# Pure network I/O — no GTK, no logging, returns a result dataclass.
#
# Manifest:
#   - Reads: nothing
#   - Writes: nothing
#   - Network: yes (HTTPS POST to provider)
#   - Imports: stdlib urllib, json, time; dataclasses
#
# Architecture: standalone — does NOT import agent.* or ui.*.
# Mirrors agent/runtime.py provider call patterns without pulling in the runtime.

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# Provider names that use the OpenAI-compatible chat/completions endpoint
_OPENAI_COMPATIBLE = {"openai", "openrouter", "zai", "minimax"}


# Prevent pytest from collecting test_connection as a test function
__test__ = False


@dataclass
class TestResult:  # noqa: N801 — pytest safe: has __init__, won't be collected as test class
    """Result of a Test Connection attempt."""
    ok: bool
    latency_ms: int           # round-trip time; 0 on failure
    error: str | None         # provider's error message; None on success
    model_used: str           # the model string that was passed in


def _model_id(model: str) -> str:
    """Strip the provider prefix from a model string.
    'openrouter/qwen/qwen3.7-max' -> 'qwen/qwen3.7-max'
    'MiniMax-M2.7' -> 'MiniMax-M2.7' (no slash → returned as-is)
    """
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _provider_name(model: str) -> str:
    """Extract provider name from model string.
    'openrouter/qwen/qwen3.7-max' -> 'openrouter'
    'MiniMax-M2.7' -> 'MiniMax-M2.7'
    """
    if "/" in model:
        return model.split("/", 1)[0]
    return model


def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
) -> TestResult:
    """
    Send a 1-token completion to the provider. Returns TestResult.

    Provider detection: model.split("/")[0] if "/" in model, else default.
    OpenAI-compatible: POST {base_url}/chat/completions with Bearer auth.
    Anthropic: POST {base_url}/messages with x-api-key auth.
    MiniMax: same as OpenAI-compatible but checks body-level errors.

    On MiniMax, a body-level error (HTTP 200 with base_resp.status_code != 0)
    is treated as failure — mirroring agent/runtime._call_minimax.
    """
    provider = _provider_name(model).lower()
    bare_model = _model_id(model)

    if provider in _OPENAI_COMPATIBLE:
        return _test_openai_compat(base_url, api_key, model, bare_model, provider, timeout_seconds)
    elif provider == "anthropic":
        return _test_anthropic(base_url, api_key, model, bare_model, timeout_seconds)
    else:
        raise ValueError(f"No adapter for provider: {provider}")


# Prevent pytest from collecting this as a test function
test_connection.__test__ = False  # type: ignore[attr-defined]


def _test_openai_compat(
    base_url: str,
    api_key: str,
    model: str,
    bare_model: str,
    provider: str,
    timeout_seconds: float,
) -> TestResult:
    """Test an OpenAI-compatible provider (openai, openrouter, zai, minimax)."""
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": bare_model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    return _do_request(endpoint, body, headers, model, provider, timeout_seconds)


def _test_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    bare_model: str,
    timeout_seconds: float,
) -> TestResult:
    """Test an Anthropic provider."""
    endpoint = f"{base_url.rstrip('/')}/messages"
    payload = {
        "model": bare_model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    return _do_request(endpoint, body, headers, model, "anthropic", timeout_seconds)


def _do_request(
    endpoint: str,
    body: bytes,
    headers: dict[str, str],
    model: str,
    provider: str,
    timeout_seconds: float,
) -> TestResult:
    """Execute the HTTP request and return a TestResult."""
    start = time.monotonic()
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read()
            elapsed_ms = int((time.monotonic() - start) * 1000)

            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as e:
                return TestResult(
                    ok=False,
                    latency_ms=elapsed_ms,
                    error=f"Invalid JSON response: {str(e)[:150]}",
                    model_used=model,
                )

            # MiniMax body-level error check (HTTP 200 with base_resp.status_code != 0)
            if provider == "minimax":
                base_resp = result.get("base_resp")
                if isinstance(base_resp, dict):
                    status_code = base_resp.get("status_code", 0)
                    if status_code != 0:
                        status_msg = base_resp.get("status_msg", "unknown error")
                        return TestResult(
                            ok=False,
                            latency_ms=elapsed_ms,
                            error=f"status_code={status_code}: {status_msg}",
                            model_used=model,
                        )

            return TestResult(
                ok=True,
                latency_ms=elapsed_ms,
                error=None,
                model_used=model,
            )

    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            error_body = "(could not read body)"
        return TestResult(
            ok=False,
            latency_ms=elapsed_ms,
            error=f"HTTP {e.code}: {error_body}",
            model_used=model,
        )

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return TestResult(
            ok=False,
            latency_ms=elapsed_ms,
            error=str(e)[:200],
            model_used=model,
        )
