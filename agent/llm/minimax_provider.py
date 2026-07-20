"""MiniMax ChatCompletion v2 LLM provider."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from agent.llm.cost import model_id


class MiniMaxProvider:
    """MiniMax ChatCompletion v2 API.

    Uses the OpenAI-compatible message format but has a different endpoint
    path (/text/chatcompletion_v2), body-level error envelopes, and a different
    finish-detection mechanism.
    """

    @property
    def provider_id(self) -> str:
        return "minimax"

    @property
    def response_format(self) -> str:
        return "openai"  # response shape is OpenAI-compatible

    def call(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        timeout: float,
        x_title: str = "",
    ) -> dict:
        """Call MiniMax ChatCompletion v2 API."""
        from agent.runtime import _urlopen_with_ssl_retry
        endpoint = f"{base_url.rstrip('/')}/text/chatcompletion_v2"
        payload = {
            "model": model_id(model),
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                # MiniMax returns body-level errors with HTTP 200:
                # {"base_resp":{"status_code":1004,"status_msg":"login fail..."}}
                base_resp = result.get("base_resp", {})
                status_code = base_resp.get("status_code", 0)
                if status_code != 0:
                    status_msg = base_resp.get("status_msg", "unknown error")
                    raise RuntimeError(
                        f"MiniMax API error (status_code={status_code}): {status_msg}"
                    )
                return result
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"MiniMax API error {e.code} {e.reason}: {body}"
            ) from e