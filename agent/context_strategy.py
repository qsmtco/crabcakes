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

        # Phase 4: P2/P3-aware trim parameters. Defined before the trim loop
        # so both the loop guard and the summary injection block can reference
        # them. tail_preserve matches the legacy value (4); min_messages
        # combines keep_first + tail_preserve to enforce the lower bound.
        tail_preserve = 4
        min_messages = keep_first + tail_preserve

        # ── Layer 1: prune_tool_outputs (P4) ──────────────────────────────
        # Cheap lossless compaction: stub old tool result content in-place.
        # Runs before the trim loop (Layer 2) to preserve conversation structure
        # while reducing token usage. Returns tokens freed; we just call it for
        # its side effect.
        self.prune_tool_outputs(conv, token_budget, protect_turns=2)
        # Re-snapshot tokens_after after Layer 1 for telemetry accuracy.
        tokens_after_layer1 = conv.get_token_estimate()

        # ── Trim loop ─────────────────────────────────────────────────────────
        # Phase 4: delegates candidate selection to ``_select_prune_candidate``,
        # which implements P2 (keep_first) and P3 (protect_is_summary) as a
        # single two-pass scan (non-protected first, then protected).
        while conv.get_token_estimate() > token_budget and len(conv.messages) > min_messages:
            idx = self._select_prune_candidate(
                conv, keep_first, tail_preserve, protect_is_summary
            )
            if idx is None:
                break
            msg = conv.messages[idx]
            # CB-6: remove TOOL_RESULT + ASSISTANT-with-tool_calls as a pair.
            if msg.role == MessageRole.TOOL_RESULT:
                conv.messages.pop(idx)
                if (
                    idx > 0
                    and conv.messages[idx - 1].role == MessageRole.ASSISTANT
                    and conv.messages[idx - 1].tool_calls
                    and (idx - 1) >= keep_first
                ):
                    conv.messages.pop(idx - 1)
                elif (
                    idx > 0
                    and conv.messages[idx - 1].role == MessageRole.ASSISTANT
                    and conv.messages[idx - 1].tool_calls
                ):
                    # Parent ASSISTANT is in keep_first region — can't remove.
                    # _select_prune_candidate should have filtered this, but
                    # break defensively to prevent CB-6 violations.
                    break
            elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                trimmable_end = len(conv.messages) - tail_preserve
                if (
                    idx + 1 < len(conv.messages)
                    and conv.messages[idx + 1].role == MessageRole.TOOL_RESULT
                    and (idx + 1) < trimmable_end
                ):
                    conv.messages.pop(idx + 1)
                    conv.messages.pop(idx)
                else:
                    conv.messages.pop(idx)
            else:
                conv.messages.pop(idx)
            conv._token_estimate_cache = None

        # ── Summary injection ─────────────────────────────────────────────────
        # Phase 4.10: fire when any messages were removed AND at least 4
        # messages remain. Skip if the summary would push the conversation
        # back over ``token_budget``.
        messages_removed = messages_count_before - len(conv.messages)
        if messages_removed > 0 and len(conv.messages) >= min_messages:
            summary = self._summary(conv, token_budget=token_budget, keep_first=keep_first)
            if summary:
                current_tokens = conv.get_token_estimate()
                fitted = self._fit_summary(conv, summary, token_budget, current_tokens)
                if fitted is not None:
                    from models.conversation import _tiktoken_encoding_for
                    encoding = _tiktoken_encoding_for(conv.model)
                    if encoding is not None:
                        summary_tokens_injected = len(encoding.encode(fitted))
                    else:
                        summary_tokens_injected = len(fitted) // 4
                    summary_msg = Message(
                        role=MessageRole.ASSISTANT,
                        content=fitted,
                        is_summary=True,
                    )
                    insert_at = max(keep_first, len(conv.messages) - tail_preserve)
                    conv.messages.insert(insert_at, summary_msg)

        # Invalidate cache and snapshot post-state for telemetry.
        conv._token_estimate_cache = None
        tokens_after = conv.get_token_estimate()

        # ── Telemetry recording (§0.4) ───────────────────────────────────────
        provider = ""
        model_value = conv.model or ""
        if "/" in model_value:
            provider, model_value = model_value.split("/", 1)

        # Determine which layer(s) fired for telemetry.
        # Layer 1 (prune_tool_outputs) fired iff tokens decreased between
        # the initial snapshot and the post-Layer-1 snapshot. Layer 2
        # (trim loop) fired iff any messages were removed. If neither
        # fired, default to layer=2 (matches pre-Phase-5 behavior).
        layer = 0
        if tokens_after_layer1 < tokens_before:
            layer = 1
        if messages_count_before > len(conv.messages):
            layer = max(layer, 2)
        if layer == 0:
            layer = 2  # default: no compaction occurred, report as layer 2

        self._last_result = CompactionEvent(
            turn=conv.step_count,
            trigger="trim",
            layer=layer,
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

    # ── Layer 1: prune_tool_outputs (Phase 5: P4 cheap lossless stubbing)

    def prune_tool_outputs(
        self,
        conv: Conversation,
        target_tokens: int,
        protect_turns: int = 2,
    ) -> int:
        """Stub old tool results to free token budget. Returns tokens freed.

        Cheap lossless Layer 1 compaction. Walks backward from the end,
        skipping the protect_turns most recent TOOL_RESULT messages. For
        each unprotected TOOL_RESULT, replaces content with a short stub:

          "[compacted — {tool_name} output, {N} chars removed]"

        Stops when get_token_estimate() <= target_tokens.
        Idempotent: detects already-stubbed messages by their
        "[compacted —" prefix and skips them.

        **Cache invalidation contract:** This method mutates ``msg.content``
        in place. The token estimate cache is keyed on
        ``(len(messages), hash(system_prompt))`` — neither changes when we
        mutate content. So we MUST invalidate the cache after each stub;
        otherwise the loop's ``get_token_estimate()`` calls would return
        the pre-stub cached value, causing the loop to over-stub.

        Args:
            target_tokens: Stop pruning when token estimate drops to this.
            protect_turns: Number of most recent TOOL_RESULT messages to skip.

        Returns:
            Number of tokens freed (estimate before - estimate after).
        """
        tokens_before = conv.get_token_estimate()
        if tokens_before <= target_tokens:
            return 0

        # Find TOOL_RESULT indices, most-recent-first.
        tool_result_indices: list[int] = []
        for i in range(len(conv.messages) - 1, -1, -1):
            if conv.messages[i].role == MessageRole.TOOL_RESULT:
                tool_result_indices.append(i)

        # Skip the protect_turns most recent tool results.
        prunable = tool_result_indices[protect_turns:]

        for idx in prunable:
            if conv.get_token_estimate() <= target_tokens:
                break
            msg = conv.messages[idx]
            # Idempotence: skip already-stubbed messages.
            if msg.content.startswith("[compacted \u2014"):
                continue
            # Find the tool name from the parent ASSISTANT message's tool_calls.
            tool_name = "tool"
            if idx > 0:
                parent = conv.messages[idx - 1]
                if parent.role == MessageRole.ASSISTANT and parent.tool_calls:
                    # Match by tool_call_id to find the specific tool name.
                    for tc in parent.tool_calls:
                        if tc.call_id == msg.tool_call_id:
                            tool_name = tc.tool_name
                            break
            original_len = len(msg.content)
            msg.content = f"[compacted \u2014 {tool_name} output, {original_len} chars removed]"
            msg.tokens_used = 0
            # CRITICAL: invalidate cache after each mutation. The cache key
            # (len(messages), hash(system_prompt)) is unchanged by content
            # mutation, so a stale cache would return pre-stub tokens.
            conv._token_estimate_cache = None

        # Final invalidation for symmetry (also covers any external mutation
        # paths that might have been added later). This is a no-op if the loop
        # already invalidated, but cheap and defensive.
        conv._token_estimate_cache = None
        tokens_after = conv.get_token_estimate()
        return tokens_before - tokens_after

    # ── Phase 6: P5 _find_split_index + P6 _fit_summary ──────────────────────

    def _find_split_index(
        self,
        conv: Conversation,
        budget_tokens: int,
        keep_first: int = 2,
    ) -> int:
        """Find the message index where the head ends and the tail begins.

        Walks backward from the end, accumulating tokens, until half the
        budget is consumed. Then walks back further to land on an assistant
        message boundary (role-anchored, Aider pattern).

        Also enforces CB-6 (tool-call pairing) at the split boundary.

        Args:
            budget_tokens: Total token budget for the conversation.
            keep_first: Minimum index for the split (never split before this).

        Returns:
            Message index >= keep_first where the head can be summarized
            and the tail kept verbatim.
        """
        if len(conv.messages) <= keep_first:
            return keep_first

        half_budget = budget_tokens // 2
        tail_tokens = 0
        split = len(conv.messages)

        for i in range(len(conv.messages) - 1, keep_first - 1, -1):
            msg = conv.messages[i]
            msg_tokens = msg.tokens_used or (len(msg.content) // 4)
            if tail_tokens + msg_tokens >= half_budget:
                break
            tail_tokens += msg_tokens
            split = i

        # Role-anchor walk-back: walk back until messages[split - 1] is ASSISTANT.
        while split > keep_first:
            prev_msg = conv.messages[split - 1]
            if prev_msg.role == MessageRole.ASSISTANT:
                break
            split -= 1

        # CB-6 forward check: if messages[split] is a TOOL_RESULT whose
        # parent ASSISTANT-with-tool-calls is in the head, move split forward
        # to include this TOOL_RESULT in the head (gets summarized with parent).
        while split < len(conv.messages):
            msg_at_split = conv.messages[split]
            if msg_at_split.role == MessageRole.TOOL_RESULT:
                if split > keep_first:
                    adjacent_parent = conv.messages[split - 1]
                    if (
                        adjacent_parent.role == MessageRole.ASSISTANT
                        and adjacent_parent.tool_calls
                        and any(tc.call_id == msg_at_split.tool_call_id for tc in adjacent_parent.tool_calls)
                    ):
                        split += 1
                        continue
                # Search backward for true parent in head.
                if msg_at_split.tool_call_id:
                    for j in range(split - 1, keep_first - 1, -1):
                        candidate = conv.messages[j]
                        if (
                            candidate.role == MessageRole.ASSISTANT
                            and candidate.tool_calls
                            and any(tc.call_id == msg_at_split.tool_call_id for tc in candidate.tool_calls)
                        ):
                            split = j
                            break
                    else:
                        break
                else:
                    break
            else:
                break

        return max(split, keep_first)

    def _fit_summary(
        self,
        conv: Conversation,
        summary: str,
        token_budget: int,
        current_tokens: int,
    ) -> str | None:
        """Fit a summary into the remaining token budget by truncating.

        Tries 5 iterations, each reducing the summary to 80% of its previous
        length. If none fit, returns a minimal stub. If even the stub doesn't
        fit, returns None.

        Uses tiktoken (via ``_tiktoken_encoding_for()``) when available for
        accurate token counts; falls back to the ``chars // 4`` heuristic.
        """
        available_tokens = token_budget - current_tokens
        if available_tokens <= 0:
            return None

        # Use tiktoken when available for accurate token counting.
        from models.conversation import _tiktoken_encoding_for
        encoding = _tiktoken_encoding_for(conv.model)

        def _count_tokens(s: str) -> int:
            if encoding is not None:
                return len(encoding.encode(s))
            return len(s) // 4

        # Try progressively smaller versions.
        fitted = summary
        for _attempt in range(5):
            fitted_tokens = _count_tokens(fitted)
            if fitted_tokens <= available_tokens:
                return fitted
            fitted = fitted[:int(len(fitted) * 0.8)]

        # Final fallback: minimal stub.
        stub = "[Context reset — earlier conversation was too large to summarize]"
        if _count_tokens(stub) <= available_tokens:
            return stub
        return None

    # ── Prune candidate selector (Phase 4: P2 keep_first + P3 protect_is_summary)

    def _select_prune_candidate(
        self,
        conv: Conversation,
        keep_first: int,
        tail_preserve: int,
        protect_is_summary: bool,
    ) -> int | None:
        """Find the index of the best message to remove for budget trimming.

        Scans the trimmable region [keep_first, len - tail_preserve) for:
        1. First pass: non-protected messages (not is_summary when protect_is_summary=True)
        2. Second pass: protected messages (if no non-protected candidates)

        Prefers TOOL_RESULT + ASSISTANT-with-tool_calls pairs (CB-6 aware).
        Falls back to oldest non-protected message.

        CB-6 invariant at keep_first boundary: When a TOOL_RESULT candidate is
        at index ``keep_first``, its parent ASSISTANT-with-tool-calls at
        ``keep_first - 1`` is in the keep_first region and cannot be removed.
        This method skips those candidates.

        Returns the index of the message to remove, or None if the
        trimmable region is empty.
        """
        trimmable_end = len(conv.messages) - tail_preserve
        if trimmable_end <= keep_first:
            return None

        # Build the candidate list, non-protected first.
        non_protected: list[int] = []
        protected: list[int] = []
        for i in range(keep_first, trimmable_end):
            msg = conv.messages[i]
            is_protected = protect_is_summary and msg.is_summary
            if is_protected:
                protected.append(i)
            else:
                non_protected.append(i)

        # Try non-protected first, then protected.
        for candidate_pool in (non_protected, protected):
            if not candidate_pool:
                continue
            # Prefer TOOL_RESULT + ASSISTANT-with-tool_calls pairs (CB-6 aware).
            for i in candidate_pool:
                msg = conv.messages[i]
                if msg.role == MessageRole.TOOL_RESULT:
                    if (
                        i > 0
                        and conv.messages[i - 1].role == MessageRole.ASSISTANT
                        and conv.messages[i - 1].tool_calls
                        and (i - 1) >= keep_first
                    ):
                        return i
                elif msg.role == MessageRole.ASSISTANT and msg.tool_calls:
                    if (
                        i + 1 < len(conv.messages)
                        and conv.messages[i + 1].role == MessageRole.TOOL_RESULT
                        and (i + 1) < trimmable_end
                    ):
                        return i
            # No CB-6 pairs found — return the first candidate (oldest).
            return candidate_pool[0]

        return None

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _summary(
        self,
        conv: Conversation,
        token_budget: int = 0,
        keep_first: int = 2,
    ) -> str:
        """Generate a summary of the oldest trimmed user messages.

        Phase 6: Uses _find_split_index() to compute a smarter split point
        instead of the naive messages[:-4] slice. The split index lands on
        an assistant message boundary (role-anchored) and respects CB-6.
        """
        if not conv.messages:
            return ""

        tail_preserve = 4
        if len(conv.messages) <= tail_preserve:
            return ""

        if token_budget > 0:
            # P5: smart split when a budget is provided (called from compact()).
            split = self._find_split_index(conv, token_budget, keep_first=keep_first)
            split = max(keep_first, min(split, len(conv.messages) - tail_preserve))
        else:
            # Legacy shim compatibility: when called via _last_exchange_summary()
            # with no max_tokens, fall back to messages[:-tail_preserve]. The smart
            # split uses token_budget to size the tail, but with no budget it would
            # default to conv.get_token_estimate() — which makes split land at
            # keep_first for small conversations (because all msgs fit in half).
            # That breaks the Phase 1 tests that rely on messages[:-tail_preserve]
            # semantics. Deviation from spec Step 3's literal fallback.
            split = len(conv.messages) - tail_preserve

        head_messages = conv.messages[:split]

        user_contents: list[str] = []
        for msg in head_messages:
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
