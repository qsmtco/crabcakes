"""Pluggable context management strategy.

See docs/specs/SPEC-CONTEXT-MANAGEMENT-ROADMAP.md §0 and
docs/proposals/PROPOSAL-pluggable-context-strategy.md.

This module hosts the P1–P7 compaction algorithms on a ``DefaultContextStrategy``
class. ``models/conversation.py`` stays pure data (ARCHITECTURE.md §3.21l) and
retains thin delegation shims that forward to ``DefaultContextStrategy`` so
existing tests continue to pass unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from models.conversation import (
    Conversation,
    Message,
    MessageRole,
)


# ── Telemetry dataclass ────────────────────────────────────────────────────────


@dataclass
class CompactionEvent:
    """One compaction cycle's outcome. Appended to per-session history.

    Fields:
        turn: Tool-loop iteration number (1-indexed) when the event fired.
        trigger: What caused compaction.
        layer: Compaction layer that fired (1=prune, 2=trim, 3=manual).
        messages_before: len(conv.messages) at start of compaction cycle.
        messages_after: len(conv.messages) at end of compaction cycle.
        messages_removed: messages_before - messages_after.
        tokens_before: get_token_estimate() before compaction.
        tokens_after: get_token_estimate() after compaction.
        tokens_freed: tokens_before - tokens_after.
        summary_tokens_injected: tokens used by injected summary (0 if none).
        soft_ceiling: The soft_ceiling used for this cycle (in tokens).
        hard_ceiling: The hard_ceiling used for this cycle (in tokens).
        provider: Provider name (e.g. "openai").
        model: Model id (e.g. "openai/gpt-4o").
    """
    turn: int
    trigger: str
    layer: int
    messages_before: int
    messages_after: int
    messages_removed: int
    tokens_before: int
    tokens_after: int
    tokens_freed: int
    summary_tokens_injected: int
    soft_ceiling: int
    hard_ceiling: int
    provider: str
    model: str


# ── Pluggable strategy protocol ────────────────────────────────────────────────


class ContextStrategy(Protocol):
    """Pluggable compaction policy. See PROPOSAL-pluggable-context-strategy.md."""

    def compact(self, conv: Conversation, token_budget: int) -> None:
        """Reduce ``conv`` so its token estimate fits within ``token_budget``.

        The strategy may evict messages, stub tool outputs, inject summaries,
        or do nothing. It must NOT mutate fields outside ``conv.messages`` and
        ``conv._token_estimate_cache`` (per ARCHITECTURE.md §3.21l).
        """
        ...

    @property
    def last_result(self) -> CompactionEvent | None:
        """Telemetry from the most recent ``compact()`` call. ``None`` before first call.

        The strategy records what happened (see §2.8 of the spec) and the
        runtime reads this attribute after each call to update its event history.
        """
        ...


# ── Default implementation ─────────────────────────────────────────────────────


class DefaultContextStrategy:
    """Default compaction strategy. See SPEC-CONTEXT-MANAGEMENT-ROADMAP.md §0.

    Phase 1: mechanical extraction from ``Conversation``. No behavior changes.
    The ``keep_first`` and ``protect_is_summary`` parameters are accepted but
    NOT YET USED — defaults preserve the pre-extraction behavior. P2/P3
    enforcement arrives in Phase 4.
    """

    def __init__(self) -> None:
        self._last_result: CompactionEvent | None = None

    @property
    def last_result(self) -> CompactionEvent | None:
        """Telemetry from the most recent ``compact()`` call."""
        return self._last_result

    # ── Public API ────────────────────────────────────────────────────────────

    def compact(
        self,
        conv: Conversation,
        token_budget: int,
        *,
        keep_first: int = 2,                # noqa: ARG002 — Phase 4 wires this
        protect_is_summary: bool = True,    # noqa: ARG002 — Phase 4 wires this
    ) -> None:
        """Compact the conversation to fit within ``token_budget``.

        Phase 1: mechanical extraction of ``Conversation.trim_to_token_limit()``.
        ``self`` → ``conv`` throughout. No behavior changes.
        """
        # Snapshot state for telemetry BEFORE any mutation.
        messages_count_before = len(conv.messages)
        tokens_before = conv.get_token_estimate()
        conv._token_estimate_cache = None
        summary_tokens_injected = 0

        # ── Trim loop ─────────────────────────────────────────────────────────
        # Mirrors the legacy Conversation.trim_to_token_limit() body verbatim,
        # rewritten so ``self.messages`` is now ``conv.messages``. The outer
        # loop guard is ``len > 4`` (preserving the historical tail_preserve=4).
        while conv.get_token_estimate() > token_budget and len(conv.messages) > 4:
            removed = False
            # Iterate backwards to avoid index-shift issues when popping.
            for i in range(len(conv.messages) - 1, 0, -1):
                msg = conv.messages[i]
                # TOOL_RESULT: also remove the preceding ASSISTANT-with-tool_calls.
                if msg.role == MessageRole.TOOL_RESULT:
                    if (
                        i > 0
                        and conv.messages[i - 1].role == MessageRole.ASSISTANT
                        and conv.messages[i - 1].tool_calls
                    ):
                        conv.messages.pop(i)
                        conv.messages.pop(i - 1)
                        removed = True
                        break
                # ASSISTANT-with-tool-calls: also remove the following TOOL_RESULT.
                elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                    if (
                        i + 1 < len(conv.messages)
                        and conv.messages[i + 1].role == MessageRole.TOOL_RESULT
                    ):
                        conv.messages.pop(i + 1)
                        conv.messages.pop(i)
                        removed = True
                        break
            if not removed:
                # Fallback: pop the oldest message in the trimmable region
                # (indices [0, len - tail_preserve)). Safe because the outer
                # guard ``len > 4`` ensures the preserved tail is untouched.
                tail_preserve = 4
                if len(conv.messages) > tail_preserve:
                    conv.messages.pop(0)
                else:
                    break

        # ── Summary injection ─────────────────────────────────────────────────
        # Phase 4.10: fire when any messages were removed AND at least 4
        # messages remain. Skip if the summary would push the conversation
        # back over ``token_budget``.
        messages_removed = messages_count_before - len(conv.messages)
        if messages_removed > 0 and len(conv.messages) >= 4:
            summary = self._summary(conv)
            if summary:
                # Phase 1: use the legacy ``len(summary) // 4`` heuristic to
                # preserve byte-exact behavior of the pre-extraction code path.
                # Phase 4 may upgrade this to tiktoken unconditionally if no
                # behavior change is observed.
                summary_tokens = len(summary) // 4
                summary_tokens_injected = summary_tokens
                current_tokens = conv.get_token_estimate()
                if current_tokens + summary_tokens > token_budget:
                    pass  # skip — injecting would exceed budget
                else:
                    summary_msg = Message(
                        role=MessageRole.ASSISTANT,
                        content=summary,
                        is_summary=True,
                    )
                    insert_at = max(1, len(conv.messages) - 4)
                    conv.messages.insert(insert_at, summary_msg)

        # Invalidate cache and snapshot post-state for telemetry.
        conv._token_estimate_cache = None
        tokens_after = conv.get_token_estimate()

        # ── Telemetry recording (§0.4) ───────────────────────────────────────
        provider = ""
        model_value = conv.model or ""
        if "/" in model_value:
            provider, model_value = model_value.split("/", 1)

        self._last_result = CompactionEvent(
            turn=conv.step_count,
            trigger="trim",
            layer=2,  # P2/P3/P6 trim layer, per §2.8.1
            messages_before=messages_count_before,
            messages_after=len(conv.messages),
            messages_removed=messages_count_before - len(conv.messages),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_freed=tokens_before - tokens_after,
            summary_tokens_injected=summary_tokens_injected,
            soft_ceiling=token_budget,
            hard_ceiling=0,  # not known at strategy level in Phase 1
            provider=provider,
            model=model_value,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _summary(
        self,
        conv: Conversation,
        token_budget: int = 0,              # noqa: ARG002 — Phase 4 uses this
        keep_first: int = 2,                # noqa: ARG002 — Phase 4 uses this
    ) -> str:
        """Generate a summary of the oldest trimmed user messages.

        Phase 1: mechanical extraction of ``Conversation._last_exchange_summary()``.
        No behavior changes. The ``token_budget`` and ``keep_first`` parameters
        are accepted for forward compatibility with the Phase 4 spec but are
        not yet used.
        """
        if not conv.messages:
            return ""

        tail_preserve = 4
        if len(conv.messages) <= tail_preserve:
            return ""

        user_contents: list[str] = []
        for msg in conv.messages[:-tail_preserve]:
            if msg.role == MessageRole.USER:
                user_contents.append(msg.content.strip())

        if not user_contents:
            return ""

        lines = [f"Conversation so far ({len(user_contents)} prior turns):"]
        for i, content in enumerate(user_contents[:5], 1):
            preview = content[:100] + ("…" if len(content) > 100 else "")
            lines.append(f"  {i}. {preview}")
        if len(user_contents) > 5:
            lines.append(f"  … and {len(user_contents) - 5} more turns")

        return "\n".join(lines)
