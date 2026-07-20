"""OpenAI-compatible LLM provider (openai, openrouter, zai)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from agent.llm.cost import model_id


class OpenAIProvider:
    """Handles OpenAI, OpenRouter, and ZAI APIs (all OpenAI-compatible).

    The provider_id is set at construction so a single class serves multiple
    registry entries. The wire protocol is identical; only credentials and
    base_url differ (both passed by the caller).
    """

    def __init__(self, provider_id: str = "openai"):
        self._id = provider_id

    @property
    def provider_id(self) -> str:
        return self._id

    @property
    def response_format(self) -> str:
        return "openai"

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
        """Call OpenAI Chat Completions API (also used by OpenRouter, ZAI)."""
        from agent.runtime import _urlopen_with_ssl_retry
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model_id(model),
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if x_title:
            headers["HTTP-Referer"] = "https://github.com/qsmtco/crabcakes"
            headers["X-Title"] = x_title
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI API error {e.code} {e.reason}: {body}"
            ) from e