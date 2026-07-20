"""Anthropic Messages API LLM provider."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Iterator

from agent.llm.convert import convert_messages_for_anthropic, convert_tools_for_anthropic
from agent.llm.cost import model_id
from agent.llm.streaming import (
    SSEEvent,
    sse_lines,
    parse_sse_line,
    urlopen_with_ssl_retry,
)

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Anthropic Messages API.

    Requires message/tool format conversion (system message extraction,
    content-block format). Uses x-api-key header, not Bearer auth.
    """

    @property
    def provider_id(self) -> str:
        return "anthropic"

    @property
    def response_format(self) -> str:
        return "anthropic"

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
        """Call Anthropic Messages API."""
        from agent.runtime import _urlopen_with_ssl_retry
        endpoint = f"{base_url.rstrip('/')}/messages"
        # Extract system prompt and STRIP system-role messages from the messages
        # list before passing to the helper. The Anthropic API expects the system
        # prompt in payload['system'] (NOT as a user-role message), and the helper
        # would otherwise convert the system message into a user message, causing
        # the system prompt to be sent TWICE (once as system, once as first user).
        # PHASE-1 AUDIT BUG #1 fix.
        system_msg: str | None = None
        non_system_messages: list[dict] = []
        for msg in messages:
            if msg.get("role") == "system":
                if system_msg is None:
                    content = msg.get("content", "")
                    system_msg = content if isinstance(content, str) else ""
            else:
                non_system_messages.append(msg)
        # Convert messages and tools using shared helpers
        api_messages = convert_messages_for_anthropic(non_system_messages)

        payload: dict[str, Any] = {
            "model": model_id(model),
            "messages": api_messages,
            "max_tokens": 4096,
        }
        if system_msg:
            payload["system"] = system_msg
        if tools:
            payload["tools"] = convert_tools_for_anthropic(tools)

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with _urlopen_with_ssl_retry(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Anthropic API error {e.code} {e.reason}: {body}"
            ) from e