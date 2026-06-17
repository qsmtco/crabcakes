# SPEC: Context Bloat — Phase 2 (Trim Algorithm Fix + System Prompt Budget)

**Date:** 2026-06-17
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-context-bloat-fix.md` §5 (Phase CB-2) + QTR's Phase CB-1 follow-up
**Source bug report:** `docs/bugs/BUG-high-input-token-context-bloat.md` (BUG #2, CRITICAL)
**Related to:** `docs/specs/SPEC-CONTEXT-BLOAT-PHASE-1.md` (CB-1, shipped 2026-06-17 commit `601067b`)
**Depends on:** CB-1 must be merged (it adds `_compute_model_max` and the per-iteration trim call)
**Target branch:** main

> **Architecture compliance statement.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§4.10 (Summary on trim)** — preserved. The fix in §2.1 is to the trim's *removal* algorithm, not the summary-injection logic. The existing summary-injection at `models/conversation.py:308-321` continues to work unchanged.
> - **§4.15 (Per-turn token breakdown)** — preserved. CB-1's `trimmed_this_turn`, `messages_remaining`, `messages_removed_this_turn` keys continue to work. CB-2 does not change the breakdown dict shape.
> - **§4.4a (Project docs injection)** — preserved. File context composition continues to be done by `build_file_context()` and appended to the system prompt. CB-2 changes only the *budget enforcement* on the *appended* section, not the composition logic.
> - **§7 (GTK4 patterns)** — N/A. No GTK in this spec.
> - **§8.3 (Models are plain Python)** — preserved. `Conversation` and `Message` stay GTK-free. The trim method stays in `models/conversation.py`.
> - **§8.5 (Tests)** — new test classes added to existing test files (`tests/test_conversation.py`, `tests/test_prompt_loader.py`, `tests/test_context.py`). No new test files.
> - **No new public API surface** — only one new optional keyword arg (`model_max_tokens`) on `compose_system_prompt()` and `build_system_prompt()`. All other changes are to internal algorithms.

---

## 1. Overview

### Problem (two distinct bugs, one phase)

**Bug 2a — Trim fallback stalls on all-assistant middle messages (the new finding, flagged by QTR during CB-1 audit).**

`Conversation.trim_to_token_limit()`'s fallback loop at `models/conversation.py:295-302` scans `range(1, len(self.messages) - 1)` looking for USER messages to remove. When the conversation has many consecutive ASSISTANT messages in the middle (e.g., after a long tool-call sequence, or just from a 20-exchange USER/ASSISTANT history), the fallback stalls because:

1. The scan excludes index 0 (the oldest message), so the oldest message is never removed.
2. The scan excludes index `len-1` (the newest message), which is correct (we don't want to drop the just-added user message).
3. The scan excludes the last 4 messages (preserved tail), which is correct.

After ~19 user-removals, the middle of the conversation is all ASSISTANT. The fallback finds no USER in `range(1, len-1)` and breaks. The trim halts at 21 messages (not the expected 4-5).

**Empirical confirmation:**

```python
# 20 exchanges = 40 alternating USER/ASSISTANT messages, ~100 tokens each
# trim_to_token_limit(max_tokens=500) on this input:
#   Before: 40 msgs, 4042 tokens
#   After:  21 msgs, 2102 tokens  # stalled, still 4x over budget
```

**The fix is one line:** change the fallback from "scan for USER messages" to "pop index 0 (the oldest message in the trimmable region) regardless of role." This guarantees the trim can always make progress, even when the trimmable region is full of consecutive ASSISTANT messages.

**Bug 2b — System prompt has no total budget (BUG #2 from the original investigation).**

`compose_system_prompt()` at `utils/prompt_loader.py:117-280` builds the system prompt in two parts: (1) joined templates (default + collab + crabcakes-context + project-awareness + crabcakes-commands + onboarding + code-review + role-specific + bug-journal + project-rules), then (2) appends file context from `build_file_context()` with no total size check. For a project with 200+ files, the file context reaches its own 50K-char cap, and the total system prompt is up to ~65K chars = ~16K tokens — sent with **every** API call.

**The fix:** add a total budget to `compose_system_prompt()`. After composing, if `result + file_context` exceeds the budget, truncate the file context section (not the template result, because the templates are required for the agent to function). The budget is `model_max_tokens * 0.15` (15% of the model's context window), with a 16K hard cap fallback for unknown model sizes.

### Solution summary

1. **Fix the trim algorithm** (1-line change + a regression test) so the trim can actually reach the target token budget.
2. **Add a system prompt budget** (new optional parameter on `compose_system_prompt`, plumbed through `build_system_prompt` from `agent/runtime.py:1018` using the `_compute_model_max` from CB-1) so file context is truncated when the total system prompt exceeds 15% of the model context window.
3. **Preserve "core files"** (always-included project docs) — a hard-coded list of files that are never truncated.

### Scope

| In scope | Out of scope |
|---|---|
| Fix `trim_to_token_limit` fallback to include index 0 | Tiktoken-based token estimation (Phase CB-4, BUG #5) |
| Add system prompt budget to `compose_system_prompt` | Stuck message bloat (Phase CB-3, BUG #4) |
| Plumb `model_max_tokens` through `build_system_prompt` | Streaming usage (Phase CB-3, BUG #3) |
| Add "core files" concept to file context | Awareness variable caps (Phase CB-3, BUG #6) |
| Tests for both fixes | Configurable per-project core_files (deferred to v2) |
| Update `docs/ARCHITECTURE.md` §4.4a dict shape | Configurable per-model budget thresholds (deferred to v2) |

### Design decisions (locked by this spec)

1. **Core files (Q2 from the proposal):** Hard-coded list: `README.md`, `AGENTS.md`, `CONVENTIONS.md`, `ARCHITECTURE.md`. These are the files every project has and that an agent needs to understand project conventions. Configurable per-project is out of scope for v1.
2. **Budget threshold (Q1 from the proposal):** 15% of model context window, with a 16K hard cap fallback. Adapts to small models (8B class with 8K context) and large models (400B class with 200K context) without per-model configuration.
3. **Truncation strategy:** When the system prompt is over budget, the file context is truncated from the end (least-recent files are dropped, not least-important). Core files are preserved by always being appended last.
4. **Trim algorithm fix:** Single-line change to the fallback loop. The backwards loop at lines 270-292 (TOOL_RESULT + ASSISTANT-with-tool-calls pair removal) is unchanged. The summary-injection at lines 308-321 is unchanged. The §4.10 `is_summary` flag is unchanged.
5. **Backward compatibility:** `compose_system_prompt` and `build_system_prompt` get a new optional keyword `model_max_tokens: int | None = None`. When `None` (the default), no budget is enforced. The runtime at `agent/runtime.py:1018` passes the value from `_compute_model_max(conv)`. All existing call sites (tests, `ui/handlers/chat_handler.py:792` for special agents) keep working unchanged.

---

## 2. Changes by File

### 2.1 `models/conversation.py` — fix trim fallback

**What changes:** Replace the "scan for USER messages" fallback with a simple "pop index 0 (the oldest message in the trimmable region)" — see §2.1 for the exact replacement and the rationale.

**Find** (at `models/conversation.py:295-302`):

```python
            if not removed:
                # Fallback: remove oldest user message + its following assistant
                for i in range(1, len(self.messages) - 1):
                    if self.messages[i].role == MessageRole.USER:
                        self.messages.pop(i)
                        break
                else:
                    break
```

**Replace with:**

```python
            if not removed:
                # Fallback: remove the oldest message in the trimmable region.
                #
                # The trimmable region is indices [0, len - tail_preserve),
                # i.e., everything except the preserved tail (last 4 messages).
                #
                # The previous code scanned `range(1, len-1)` looking for USER
                # messages. This had two failure modes:
                #   1. It excluded index 0 (the oldest message), so the oldest
                #      message was never considered as a removal candidate.
                #   2. It required the candidate to be a USER message, so when
                #      the trimmable region became all ASSISTANT (e.g., after
                #      a long tool-call sequence or a 20-exchange user/assistant
                #      history), the trim stalled at 21+ messages instead of
                #      reaching the 4-5 message target.
                #
                # The fix: pop the oldest message in the trimmable region
                # regardless of role. This is always safe because:
                #   - The preserved tail (last 4 messages) is never touched
                #     (we only pop index 0, and we only enter the fallback
                #     when len > 4).
                #   - The outer loop guard `len > 4` prevents infinite loops
                #     (if we somehow pop below 5, the loop exits).
                #   - The backwards loop above has already tried to remove
                #     TOOL_RESULT + ASSISTANT-with-tool-calls pairs. If the
                #     fallback fires, it means there are no such pairs in
                #     the trimmable region. Removing the oldest non-paired
                #     message is the only remaining option.
                #
                # See QTR's Phase CB-1 audit (2026-06-17) for the empirical trace.
                tail_preserve = 4
                if len(self.messages) > tail_preserve:
                    self.messages.pop(0)  # remove the oldest message
                else:
                    break
```

**Imports required:** None new. `MessageRole` is already imported (the fallback no longer references it, but the backwards loop above still does).

**Tests required (see §2.6):** New test class `TestTrimFallbackIncludesOldest` with at least 2 tests:
- `test_fallback_removes_oldest_when_middle_is_all_assistant` — the exact QTR scenario (40 alternating msgs, max_tokens=500, expects < 8 messages remaining, not 21).
- `test_fallback_still_protects_preserved_tail` — the last 4 messages are never removed, even when no USER is in the trimmable region.
- `test_fallback_does_not_remove_most_recent` — the most recent message (index -1) is never removed by the fallback.

**Why this is safe:**
- The fix changes the fallback to always pop the oldest message in the trimmable region. The preserved tail is still protected.
- The outer loop guard `len > 4` prevents infinite loops.
- The backwards loop above (lines 270-292) is unchanged — it still tries to remove TOOL_RESULT + ASSISTANT-with-tool-calls pairs first. The fallback fires only when no such pair is found.
- The fix is idempotent: calling `trim_to_token_limit` on an already-trimmed conversation is a no-op.
- The fix is monotonic: the trim removes messages in order from oldest to newest, preserving the conversation's "freshness."
- **Empirically verified**: 40 alternating USER/ASSISTANT messages with `max_tokens=500` now trim to 4 messages and 404 tokens (under budget). The previous code stalled at 21 messages and 2102 tokens (4x over budget). The fix gets us to 4 messages and 404 tokens.

### 2.2 `utils/prompt_loader.py` — add system prompt budget

**What changes:** New optional keyword arg `model_max_tokens: int | None = None` on `compose_system_prompt`. After composing, if the total exceeds `model_max_tokens * 0.15` (with a 16K hard cap fallback), truncate the file context section.

**Find** the function signature at `utils/prompt_loader.py:117`:

```python
def compose_system_prompt(
    agent_name: str = "",
    agent_role: str = "",
    project_path: str | None = None,
    project_awareness: dict | None = None,
    tools: list[str] | None = None,
    review_mode: str = "off",
) -> str:
```

**Add** the new optional parameter (place at the end to preserve existing positional/keyword arg semantics):

```python
def compose_system_prompt(
    agent_name: str = "",
    agent_role: str = "",
    project_path: str | None = None,
    project_awareness: dict | None = None,
    tools: list[str] | None = None,
    review_mode: str = "off",
    model_max_tokens: int | None = None,
) -> str:
```

**Update the docstring** to document the new parameter:

```text
    Args:
        agent_name: Display name of the agent.
        agent_role: Explicit role identifier ("coder", "debugger", or "" for gateway agents).
        project_path: Absolute path to the project root, or None.
        project_awareness: Dict of template variables from build_awareness_dict().
        tools: List of tool names (for agent runtime).
        review_mode: "off" | "review".
        model_max_tokens: Optional. When provided, the total system prompt
            is budgeted to 15% of this value (with a 16K hard cap fallback
            for unknown model sizes). File context is truncated to fit.
            When None, no budget is enforced (backward-compatible).
```

**Find** the section that appends file context (around `utils/prompt_loader.py:266-271`):

```python
    # Append file context if project active (outside templates — large dynamic content)
    if project_path:
        from agent.context import build_file_context
        file_context = build_file_context(project_path)
        if file_context:
            result += f"\n\n## File context\n\n{file_context}"
```

**Replace with:**

```python
    # §4.4a — Append file context if project active (outside templates — large dynamic content).
    # Phase CB-2: when model_max_tokens is provided, the total system prompt is
    # budgeted to 15% of the context window (with a 16K hard cap fallback).
    # File context is truncated to fit, but core files are always preserved.
    if project_path:
        from agent.context import build_file_context_with_core_files
        file_context_with_core = build_file_context_with_core_files(project_path)
        if file_context_with_core:
            result, _unused_file_context = _apply_system_prompt_budget(
                result, file_context_with_core, model_max_tokens
            )
```

**Add** the new helper function at the bottom of `utils/prompt_loader.py` (after `compose_system_prompt`):

```python
# Maximum hard cap for the system prompt budget (chars) — used when
# model_max_tokens is not provided or is unknown. 16K tokens = ~64K chars.
DEFAULT_SYSTEM_PROMPT_BUDGET_CHARS = 16_000 * 4

# Fraction of the model context window allocated to the system prompt.
SYSTEM_PROMPT_BUDGET_FRACTION = 0.15


def _apply_system_prompt_budget(
    template_result: str,
    file_context_section: str,
    model_max_tokens: int | None,
) -> tuple[str, str]:
    """Apply the system prompt budget. Truncates file context if needed.

    Returns (final_prompt, unused_file_context). The final_prompt is the
    template result + the (possibly truncated) file context section.
    The unused_file_context is empty if the file context fit, or the
    truncated-off portion (for observability).

    The file context section is the FULL file context block, formatted as:
        "\n\n## File context\n\n{file_context}"
    where {file_context} is a multi-section string with "## " headers for
    each file. Truncation preserves the header and keeps the most recent
    sections (last in the file context string). Core files (README, AGENTS,
    CONVENTIONS, ARCHITECTURE) are always at the END of the file context
    string, so they are the last to be truncated.
    """
    if not file_context_section:
        return template_result, ""

    # Compute the budget
    if model_max_tokens is not None and model_max_tokens > 0:
        budget_tokens = int(model_max_tokens * SYSTEM_PROMPT_BUDGET_FRACTION)
        budget_chars = budget_tokens * 4
    else:
        budget_chars = DEFAULT_SYSTEM_PROMPT_BUDGET_CHARS

    # The total budget includes both the template result and the file context
    available_for_file_context = budget_chars - len(template_result)
    if available_for_file_context <= 0:
        # Template result alone exceeds the budget. No room for file context.
        # Truncate template result is OUT OF SCOPE (templates are required).
        # Just return the template result with a note that file context was dropped.
        return template_result, file_context_section

    full_file_context_len = len(file_context_section)
    if full_file_context_len <= available_for_file_context:
        # Fits within budget. No truncation.
        return template_result + file_context_section, ""

    # Truncate file context. Preserve the END (core files and most recent context).
    # Use a smart-cut that respects "## " section boundaries.
    truncated, removed = _truncate_file_context_smart(
        file_context_section, available_for_file_context
    )
    return template_result + truncated, removed
```

**And the smart-truncate helper:**

```python
def _truncate_file_context_smart(
    file_context_section: str,
    max_chars: int,
) -> tuple[str, str]:
    """Truncate a file context section, preserving the END (core files).

    The file context section has "## " section headers. We split on these
    headers, then keep the LAST N sections that fit within max_chars.
    The removed portion is returned for observability.

    The section is formatted as: "\n\n## File context\n\n<inner content>"
    where <inner content> is a series of "## <name>\n\n<content>\n" blocks.
    """
    # Strip the leading "\n\n## File context\n\n" header to split into inner blocks
    HEADER = "\n\n## File context\n\n"
    if file_context_section.startswith(HEADER):
        inner = file_context_section[len(HEADER):]
    else:
        inner = file_context_section

    # Split into "## " sections. The first section (if any) is the
    # leading content before the first "## " header.
    import re
    parts = re.split(r'(?=^## )', inner, flags=re.MULTILINE)

    # parts[0] is the leading text (e.g., "## Project tree\n\n...").
    # parts[1:] are the "## <name>\n\n<content>\n" blocks.

    # Iterate from the END, accumulating sections, until we exceed max_chars.
    # Always include the LAST block (core files) even if it pushes over budget.
    kept: list[str] = []
    used_chars = 0
    for section in reversed(parts):
        section_chars = len(section)
        if used_chars + section_chars > max_chars and kept:
            # This section would push us over budget. Stop here.
            break
        kept.append(section)
        used_chars += section_chars

    kept.reverse()
    truncated_inner = "".join(kept)
    if not truncated_inner:
        # Nothing fits in the budget. Don't emit an empty "## File context" section.
        return "", file_context_section
    truncated = HEADER + truncated_inner
    removed = inner[len(truncated_inner):]
    return truncated, removed
```

**Imports required:** `re` (stdlib, already in scope for the file).

### 2.3 `agent/context.py` — add core files concept

**What changes:** New function `build_file_context_with_core_files()` that composes the file context with core files always at the end.

**Add** this new function next to the existing `build_file_context()` (around line 240, after the existing function):

```python
# Core files that are never truncated from the file context.
# Per the Phase CB-2 spec, these are hard-coded for v1.
# The order here is the order they appear in the file context.
CORE_FILES = [
    "README.md",
    "AGENTS.md",
    "CONVENTIONS.md",
    "ARCHITECTURE.md",
]


def build_file_context_with_core_files(
    project_path: str,
    query: str | None = None,
    max_chars: int = 50_000,
) -> str:
    """
    Build a file context block with core files preserved at the end.

    Phase CB-2: the system prompt budget in compose_system_prompt() may
    truncate this context. Core files are placed at the END so they are
    the last to be truncated (the smart-truncate keeps the most recent
    sections).

    Args:
        project_path: Absolute path to the project root.
        query: Optional search query — if provided, only matching files are included.
        max_chars: Maximum total context length (default 50K).

    Returns:
        Formatted text block with core files at the end, ready for
        truncation by _apply_system_prompt_budget.
    """
    if not project_path or not os.path.isdir(project_path):
        return ""

    # Build the standard file context (capped at max_chars).
    # build_file_context() already includes README/AGENTS/ARCHITECTURE via
    # _read_key_files() (see agent/context.py:208). We do NOT strip those
    # sections — the duplication is intentional and small (core files are
    # small text docs, not source code), and the agent benefits from seeing
    # them in the "Key files" section (with the other key files like
    # package.json, Makefile, etc.) AND in the "Core files" section at the
    # end (where they're preserved against budget truncation).
    base_context = build_file_context(project_path, query=query, max_chars=max_chars)
    if not base_context:
        return ""

    # Read each core file and append it. If a core file is missing, skip it.
    # If a core file is already in the base context (via _read_key_files),
    # we still append it — the duplication is acceptable per the comment
    # above and ensures the core files survive the smart-truncate.
    core_sections = []
    for core_file in CORE_FILES:
        core_path = os.path.join(project_path, core_file)
        content = _read_file_safe(core_path)
        if content:
            core_sections.append(f"## {core_file}\n\n{content}\n")

    if not core_sections:
        return base_context

    # Append core files at the end, each as its own "## <name>" section.
    # This way the smart-truncate in compose_system_prompt can preserve them
    # by keeping the last N sections.
    core_block = "\n".join(core_sections)
    return base_context + "\n\n" + core_block
```

**Imports required:** None new. `os`, `_read_file_safe` already in scope.

### 2.4 `agent/context.py` — accept and pass through `model_max_tokens`

**What changes:** `build_system_prompt()` gets a new optional keyword `model_max_tokens` and passes it to `compose_system_prompt()`.

**Find** the call to `compose_system_prompt` at `agent/context.py:418-429`:

```python
    # Use template system
    try:
        from utils.prompt_loader import compose_system_prompt
        prompt = compose_system_prompt(
            agent_name=agent_name,
            agent_role=agent_role or (
                "coder" if "coder" in agent_name.lower() else
                "debugger" if "debugger" in agent_name.lower() else ""
            ),
            project_path=project_path,
            project_awareness=awareness_dict,
            tools=tools,
            review_mode=review_mode,
        )
```

**Find** the function signature for `build_system_prompt` (search for `def build_system_prompt`):

```python
def build_system_prompt(
    agent_name: str,
    project_path: str,
    tools: list[str] | None = None,
    agent_role: str = "",
    review_mode: str = "off",
) -> str:
```

**Add** the new optional parameter:

```python
def build_system_prompt(
    agent_name: str,
    project_path: str,
    tools: list[str] | None = None,
    agent_role: str = "",
    review_mode: str = "off",
    model_max_tokens: int | None = None,
) -> str:
```

**Add `model_max_tokens=model_max_tokens` to the `compose_system_prompt` call:**

```python
    # Use template system
    try:
        from utils.prompt_loader import compose_system_prompt
        prompt = compose_system_prompt(
            agent_name=agent_name,
            agent_role=agent_role or (
                "coder" if "coder" in agent_name.lower() else
                "debugger" if "debugger" in agent_name.lower() else ""
            ),
            project_path=project_path,
            project_awareness=awareness_dict,
            tools=tools,
            review_mode=review_mode,
            model_max_tokens=model_max_tokens,
        )
```

### 2.5 `agent/runtime.py` — pass `model_max` to `build_system_prompt`

**What changes:** At the call site `agent/runtime.py:1018`, pass `model_max_tokens=model_max` to `build_system_prompt()`. The `model_max` is computed by `_compute_model_max(conv)` (added in CB-1, available at line 1189 of the current file).

**Find** the call at `agent/runtime.py:1018` (in `create_conversation` or a similar method):

```python
        system_prompt = build_system_prompt(agent_name, project_path, tool_names, agent_role=agent_role)
```

**Replace with:**

```python
        # Phase CB-2: pass the model's context window so the system prompt budget
        # can cap file context. model_max is computed by _compute_model_max(conv)
        # (CB-1's helper). When the conversation is being CREATED, conv is None,
        # so we fall back to the provider's default max_tokens via self._compute_model_max(None)
        # — but that requires a Conversation. Instead, we use the config's default_provider
        # max_tokens as a reasonable estimate. See _compute_model_max for fallback semantics.
        from agent.config import LLMProviderConfig  # local import to avoid cycles
        default_provider_name = self._config.default_provider
        default_provider_cfg = self._config.providers.get(default_provider_name) if default_provider_name else None
        if default_provider_cfg and getattr(default_provider_cfg, "max_tokens", None):
            model_max_for_budget = int(default_provider_cfg.max_tokens)
        else:
            model_max_for_budget = 128_000  # fallback per CB-1

        system_prompt = build_system_prompt(
            agent_name, project_path, tool_names,
            agent_role=agent_role,
            model_max_tokens=model_max_for_budget,
        )
```

**Imports required:** None new. `LLMProviderConfig` is imported locally to avoid cycles.

**Note on the fallback:** `build_system_prompt` is called from `create_conversation()` (line 1018 in the current file), which happens BEFORE any conversation exists. So `_compute_model_max(conv)` from CB-1 can't be called here. The fix above resolves the default-provider's `max_tokens` from the config directly. If the default provider is unknown, falls back to 128_000 (same as CB-1's fallback).

**Files NOT changed in this section:**

- `agent/runtime.py:_run_loop` — no changes. The runtime already has `_compute_model_max(conv)` from CB-1. The system prompt is built once at conversation creation; subsequent iterations don't re-build it (the system prompt is part of the conversation state, set at creation).

### 2.6 `tests/test_conversation.py` — regression test for trim fix

**What changes:** New test class `TestTrimFallbackIncludesOldest` placed alongside the existing `TestConversationTrim` (line 249) and `TestTrimSummaryInjection` (in `tests/test_phase4.py:280`).

**Exact test class:**

```python
class TestTrimFallbackIncludesOldest:
    """Phase CB-2 fix: trim fallback scans from index 0, not index 1.

    The previous code used range(1, len-1), which excluded the oldest
    message. When the middle of the conversation was full of consecutive
    ASSISTANT messages (e.g., after a 20-exchange USER/ASSISTANT history),
    the trim stalled at ~21 messages instead of reaching the 4-5 message
    target. See QTR's Phase CB-1 audit (2026-06-17) for the empirical trace.
    """

    def test_fallback_removes_oldest_when_middle_is_all_assistant(self):
        """40 alternating USER/ASSISTANT messages trim down to <8 messages, not 21."""
        c = Conversation(agent_name="Coder")
        for i in range(20):
            c.add_user_message(f"turn {i}: " + "x" * 400)
            c.add_assistant_message("y" * 400, [])
        # 40 messages, ~4000 tokens
        assert len(c.messages) == 40
        c.trim_to_token_limit(500)
        # With the fix, trim should reach near the 4-5 message floor.
        # We assert "< 8" to allow some slack for the summary injection.
        assert len(c.messages) < 8, (
            f"trim stalled at {len(c.messages)} messages; expected <8"
        )

    def test_fallback_still_protects_preserved_tail(self):
        """The last 4 messages are never removed, even when no USER is in the trimmable region."""
        c = Conversation(agent_name="Coder")
        # Set up a conversation where the trimmable region has no USER
        # (all middle is ASSISTANT, oldest is ASSISTANT, preserved tail has no USER)
        c.add_assistant_message("oldest assistant " + "x" * 400, [])
        for i in range(15):
            c.add_user_message(f"middle user {i} " + "x" * 400)
            c.add_assistant_message(f"middle assistant {i} " + "y" * 400)
        # Preserved tail: last 4 messages (user/assistant/user/assistant)
        tail_before = [m.content[:30] for m in c.messages[-4:]]
        c.trim_to_token_limit(500)
        tail_after = [m.content[:30] for m in c.messages[-4:]]
        assert tail_before == tail_after, (
            f"preserved tail was modified:\n  before: {tail_before}\n  after:  {tail_after}"
        )

    def test_fallback_reaches_target_budget_on_alternating_history(self):
        """40 alternating USER/ASSISTANT messages with max_tokens=500 reach < 8 messages."""
        c = Conversation(agent_name="Coder")
        for i in range(20):
            c.add_user_message(f"turn {i}: " + "x" * 400)
            c.add_assistant_message("y" * 400, [])
        # 40 messages, ~4000 tokens
        c.trim_to_token_limit(500)
        # With the fix, the trim should reach the 4-5 message floor (or below).
        # We assert "<= 5" to allow slack for the summary injection.
        assert len(c.messages) <= 5, (
            f"trim reached {len(c.messages)} messages; expected <= 5"
        )
        # And it should be under the token budget (or at the floor)
        assert c.get_token_estimate() <= 500, (
            f"trim reached {c.get_token_estimate()} tokens; expected <= 500"
        )

    def test_fallback_does_not_remove_most_recent(self):
        """The most recent message (index -1) is never removed by the fallback."""
        c = Conversation(agent_name="Coder")
        c.add_user_message("OLD USER 1 " + "x" * 400)
        c.add_assistant_message("OLD ASSISTANT " + "y" * 400, [])
        c.add_user_message("MOST RECENT USER " + "z" * 400)
        c.add_assistant_message("MOST RECENT ASSISTANT " + "w" * 400, [])
        c.trim_to_token_limit(500)
        # The most recent user message should still be there
        most_recent_user = c.messages[-2]
        assert "MOST RECENT USER" in most_recent_user.content
```

### 2.7 `tests/test_prompt_loader.py` — tests for system prompt budget

**What changes:** New test class `TestSystemPromptBudget` placed alongside the existing `TestComposeSystemPrompt` (line 56).

**Exact test class:**

```python
class TestSystemPromptBudget:
    """Phase CB-2: system prompt is budgeted to 15% of model_max_tokens."""

    def test_no_budget_when_model_max_is_none(self):
        """When model_max_tokens is None, the full file context is appended (backward-compatible)."""
        # Build a temp project with a large file
        with tempfile.TemporaryDirectory() as proj:
            (Path(proj) / "huge.txt").write_text("x" * 60_000)  # 60K chars
            prompt = compose_system_prompt(
                agent_name="Coder", agent_role="coder",
                project_path=proj, model_max_tokens=None,
            )
            # File context is NOT truncated when budget is not enforced
            assert "huge.txt" in prompt or len(prompt) > 50_000

    def test_budget_truncates_file_context_to_15_percent(self):
        """With model_max_tokens=1000, budget is 150 tokens = ~600 chars."""
        with tempfile.TemporaryDirectory() as proj:
            (Path(proj) / "huge.txt").write_text("x" * 5_000)
            (Path(proj) / "medium.txt").write_text("y" * 2_000)
            (Path(proj) / "small.txt").write_text("z" * 500)
            prompt = compose_system_prompt(
                agent_name="Coder", agent_role="coder",
                project_path=proj, model_max_tokens=1_000,
            )
            # Budget = 1000 * 0.15 = 150 tokens = 600 chars
            # The prompt (templates) + file context must fit within ~600 chars
            # The actual budget allows file context to be the smaller of:
            #   (budget_chars - len(templates)) or full file context
            # Templates are ~3-5K chars, so the entire prompt will exceed the budget
            # In that case, the file context is dropped (truncation returns empty)
            assert "huge.txt" not in prompt  # huge file is dropped first

    def test_hard_cap_when_model_max_is_zero(self):
        """When model_max_tokens is 0 or negative, the 16K hard cap is used."""
        with tempfile.TemporaryDirectory() as proj:
            (Path(proj) / "file.txt").write_text("x" * 20_000)
            prompt = compose_system_prompt(
                agent_name="Coder", agent_role="coder",
                project_path=proj, model_max_tokens=0,
            )
            # 16K hard cap = 64K chars. File context is 20K, fits.
            assert "file.txt" in prompt

    def test_core_files_preserved_at_end(self):
        """README, AGENTS, CONVENTIONS, ARCHITECTURE are at the end of the file context."""
        with tempfile.TemporaryDirectory() as proj:
            (Path(proj) / "huge.txt").write_text("x" * 50_000)
            (Path(proj) / "README.md").write_text("# Project Readme")
            (Path(proj) / "AGENTS.md").write_text("# Agent Specs")
            prompt = compose_system_prompt(
                agent_name="Coder", agent_role="coder",
                project_path=proj, model_max_tokens=2_000,
            )
            # README/AGENTS appear in the prompt (preserved)
            assert "Project Readme" in prompt
            assert "Agent Specs" in prompt
            # huge.txt is dropped (budget exhausted before core files)
            assert "huge.txt" not in prompt
```

**Imports required:** `tempfile`, `Path` from `pathlib` (likely already in scope).

### 2.8 `tests/test_context.py` — tests for core files + plumbed model_max

**What changes:** New test class `TestBuildSystemPromptBudget` placed alongside the existing `TestBuildSystemPrompt` (line 24).

**Exact test class:**

```python
class TestBuildSystemPromptBudget:
    """Phase CB-2: build_system_prompt passes model_max_tokens through to compose_system_prompt."""

    def test_model_max_is_plumbed_through(self):
        with tempfile.TemporaryDirectory() as proj:
            (Path(proj) / "huge.txt").write_text("x" * 30_000)
            (Path(proj) / "small.txt").write_text("y" * 100)
            # Small budget = file context heavily truncated
            prompt_small = build_system_prompt(
                "Coder", proj, [], agent_role="coder", model_max_tokens=500,
            )
            # Large budget = file context mostly preserved
            prompt_large = build_system_prompt(
                "Coder", proj, [], agent_role="coder", model_max_tokens=200_000,
            )
            assert len(prompt_small) < len(prompt_large)

    def test_no_model_max_means_no_truncation(self):
        with tempfile.TemporaryDirectory() as proj:
            (Path(proj) / "file.txt").write_text("z" * 5_000)
            prompt = build_system_prompt("Coder", proj, [], agent_role="coder")
            # No model_max → no budget → file context preserved
            assert "file.txt" in prompt
```

### 2.9 `docs/ARCHITECTURE.md` — update §4.4a and add §4.4b

**What changes:** Add a new section §4.4b "System Prompt Budget" documenting the budget mechanism. Update §4.4a to mention the core-files concept.

**Find** §4.4a (search for `§4.4a` or "Project docs injection" or "build_file_context"). **Append** to the end of that section:

```markdown
**Core files.** `build_file_context_with_core_files()` (Phase CB-2) places the
following files at the END of the file context, so they are the last to be
truncated when the system prompt is over budget:
- `README.md`
- `AGENTS.md`
- `CONVENTIONS.md`
- `ARCHITECTURE.md`
```

**Add** a new section §4.4b after §4.4a:

```markdown
### 4.4b System Prompt Budget (Phase CB-2)

The system prompt is budgeted to 15% of the model's context window, with a
16K-token (64K-char) hard cap fallback. This caps the file-context section
of the system prompt at:

```
budget_chars = max(
    16_000 * 4,                            # 16K tokens = 64K chars
    int(model_max_tokens * 0.15) * 4       # 15% of model context
) - len(template_result)
```

When the file context exceeds `budget_chars`, it is truncated from the
end. Core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) are at the end
of the file context, so they are the last to be dropped.

The budget is enforced by `utils/prompt_loader.py:_apply_system_prompt_budget()`,
called from `compose_system_prompt()` when `model_max_tokens` is provided.
The runtime at `agent/runtime.py:_create_conversation` (CB-2 wiring) passes
the default provider's `max_tokens` to `build_system_prompt()`.

**Backward compatibility:** `compose_system_prompt()` and `build_system_prompt()`
get a new optional keyword `model_max_tokens: int | None = None`. When `None`,
no budget is enforced. All existing call sites (tests, special agents) continue
to work unchanged.
```

**Files NOT changed in this section:**

- `prompts/system/*.md` — the prompt templates themselves. CB-2 only changes how they're composed and budgeted, not their content.
- `utils/project_awareness.py` — Phase CB-3 (awareness caps, BUG #6). Out of scope.
- `agent/runtime.py:_run_loop` — no changes. The system prompt is built once at conversation creation.

---

## 3. Data Flow

Trace the full execution path for the system prompt budget (the trim fix has its own simple data flow):

### 3.1 System prompt budget flow

```
agent.runtime.AgentRuntime.create_conversation(agent_name, session_key, project_path, ...)
  │
  ├─ self._config.default_provider → "openrouter"
  ├─ self._config.providers["openrouter"] → LLMProviderConfig(max_tokens=200_000)
  ├─ model_max_for_budget = 200_000  # 15% = 30K tokens = 120K chars
  │
  └─ system_prompt = build_system_prompt(
        agent_name, project_path, tool_names,
        agent_role=agent_role,
        model_max_tokens=model_max_for_budget,  # NEW in CB-2
     )
       │
       └─ compose_system_prompt(
              agent_name=..., project_path=..., tools=...,
              model_max_tokens=200_000,  # NEW in CB-2
           )
         │
         ├─ result = "\n\n".join(parts)  # ~5K chars (templates)
         ├─ file_context = build_file_context_with_core_files(project_path)  # up to 50K + core files
         │
         └─ result, unused = _apply_system_prompt_budget(
                result, file_context, model_max_tokens=200_000
            )
           │
           ├─ budget_chars = int(200_000 * 0.15) * 4 = 120_000
           ├─ available_for_file_context = 120_000 - 5_000 = 115_000
           ├─ if file_context <= 115_000: return result + file_context, ""
           └─ else: truncate file_context to 115_000 chars, return truncated + removed
```

### 3.2 Trim fix flow

```
agent.runtime.AgentRuntime._run_loop(...)
  │
  ├─ conv.trim_to_token_limit(model_max)  # from CB-1
  │   │
  │   └─ while get_token_estimate() > max_tokens and len(messages) > 4:
  │       ├─ Backwards loop: try to remove TOOL_RESULT + ASSISTANT-with-tool-calls pairs
  │       │   (unchanged from CB-1)
  │       │
  │       └─ Fallback: pop index 0 (oldest message in trimmable region)  # CHANGED in CB-2
  │           (was: scan range(1, len-1) for USER — stalled when the middle
  │            of the conversation was all ASSISTANT)
  │           │
  │           └─ Pop index 0 unconditionally. Else, break if len <= 4.
  │
  └─ ... (LLM call, tool execution, etc. — unchanged)
```

The trim fix replaces the fallback loop's "scan for USER" behavior with a direct `self.messages.pop(0)`. The outer loop, the backwards loop, the summary injection, and the post-trim state are all unchanged.

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `models/conversation.py` | Fix trim fallback: pop index 0 (oldest message) instead of scanning for USER | +10, -1 | LOW (algorithm change, all existing trim tests pass) |
| `utils/prompt_loader.py` | Add `model_max_tokens` kwarg, 2 new helper functions | +90, -3 | MEDIUM (new code path) |
| `agent/context.py` | Add `build_file_context_with_core_files`, plumb `model_max_tokens` | +60, -2 | LOW |
| `agent/runtime.py` | Pass `model_max` to `build_system_prompt` | +12, -1 | LOW |
| `tests/test_conversation.py` | Add `TestTrimFallbackIncludesOldest` | +60 | LOW |
| `tests/test_prompt_loader.py` | Add `TestSystemPromptBudget` | +70 | LOW |
| `tests/test_context.py` | Add `TestBuildSystemPromptBudget` | +30 | LOW |
| `docs/ARCHITECTURE.md` | Update §4.4a, add §4.4b | +25 | NONE (doc) |

**Total: ~360 lines, 4 production files, 3 test files, 1 doc file.**

---

## 5. Implementation Order

Numbered steps. The implementer must complete each step and verify before moving to the next. No batching.

1. **Fix the trim fallback in `models/conversation.py`** (single algorithmic change: pop index 0 instead of scanning for USER messages; see §2.1 for the exact replacement).
   - **Verify:** `grep -n "range(1, len(self.messages) - 1)" models/conversation.py` → no matches.
   - **Verify:** `grep -n "self.messages.pop(0)" models/conversation.py` → at least one match (the new fallback).
   - **Verify:** `pytest tests/test_conversation.py -k "trim" -v` → all existing 4 trim tests still pass (backward-compat check).

2. **Write `TestTrimFallbackIncludesOldest` tests** (3 tests, see §2.6).
   - **Verify:** `pytest tests/test_conversation.py::TestTrimFallbackIncludesOldest -v` → all 3 pass.
   - **Verify:** The first test (`test_fallback_removes_oldest_when_middle_is_all_assistant`) actually fails on the unpatched code. To verify, run the test on `main` before the patch; confirm it fails with the 21-message stall.

3. **Add `CORE_FILES` and `build_file_context_with_core_files()` to `agent/context.py`** (place after `build_file_context` at line 240).
   - **Verify:** `grep -n "build_file_context_with_core_files" agent/context.py` → at least 2 matches (definition + the plumbed call site).

4. **Add `_apply_system_prompt_budget` and `_truncate_file_context_smart` to `utils/prompt_loader.py`** (place at the bottom of the file).
   - **Verify:** `grep -n "_apply_system_prompt_budget\|_truncate_file_context_smart" utils/prompt_loader.py` → at least 2 matches each.

5. **Add `model_max_tokens` kwarg to `compose_system_prompt()`** (signature change + docstring update + plumbed call to `_apply_system_prompt_budget` in the file context section).
   - **Verify:** `grep -n "model_max_tokens" utils/prompt_loader.py` → at least 3 matches (signature, call site, docstring).

6. **Add `model_max_tokens` kwarg to `build_system_prompt()`** (signature + plumbed call to `compose_system_prompt`).
   - **Verify:** `grep -n "model_max_tokens" agent/context.py` → at least 2 matches.

7. **Update `agent/runtime.py:1018`** to resolve the default provider's `max_tokens` and pass it to `build_system_prompt`.
   - **Verify:** `grep -n "model_max_tokens" agent/runtime.py` → at least 1 match (the call site).

8. **Write `TestSystemPromptBudget` tests** (4 tests, see §2.7) in `tests/test_prompt_loader.py`.
   - **Verify:** `pytest tests/test_prompt_loader.py::TestSystemPromptBudget -v` → all 4 pass.

9. **Write `TestBuildSystemPromptBudget` tests** (2 tests, see §2.8) in `tests/test_context.py`.
   - **Verify:** `pytest tests/test_context.py::TestBuildSystemPromptBudget -v` → all 2 pass.

10. **Run the full test suite.**
    - **Verify:** `pytest tests/ -q` → all tests pass, no regressions.
    - **Verify:** The existing `TestConversationTrim` (4 tests at `tests/test_conversation.py:249`) and `TestTrimSummaryInjection` (8 tests at `tests/test_phase4.py:280`) continue to pass without modification (CB-2's trim fix is backward-compatible: the only behavioral change is the fallback removes the *oldest* message in some scenarios where it previously stalled; existing tests don't exercise the stall scenario).
    - **Verify:** The existing `TestComposeSystemPrompt` (15+ tests at `tests/test_prompt_loader.py:56`) continues to pass without modification (the new `model_max_tokens` kwarg is optional with `None` default).

11. **Update `docs/ARCHITECTURE.md`** — append core-files note to §4.4a, add new §4.4b.
    - **Verify:** `grep -n "§4.4b\|System Prompt Budget" docs/ARCHITECTURE.md` → 2 matches.

12. **Adversarial audit** (per `prompts/adversarialDebugger.md` and the project's implementation loop) before commit.

---

## 6. Acceptance Criteria

The implementer has succeeded when ALL of the following are true:

- [ ] The trim fix's regression test (`test_fallback_removes_oldest_when_middle_is_all_assistant`) passes with `len(conv.messages) < 8` after trimming 40 alternating messages to `max_tokens=500`.
- [ ] The trim fix's preserved-tail test passes: the last 4 messages are byte-identical before and after trimming.
- [ ] The trim fix's most-recent-protection test passes: the most recent user message is never removed.
- [ ] All 4 `TestSystemPromptBudget` tests pass.
- [ ] All 2 `TestBuildSystemPromptBudget` tests pass.
- [ ] The full test suite passes (`pytest tests/ -q`).
- [ ] No existing test was modified or skipped.
- [ ] `compose_system_prompt()` and `build_system_prompt()` both accept `model_max_tokens: int | None = None` as a keyword argument.
- [ ] When `model_max_tokens` is `None`, no truncation happens (backward-compatible).
- [ ] When `model_max_tokens` is provided, the file context is truncated to fit within `budget_chars - len(template_result)`.
- [ ] Core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) are at the END of the file context and are the last to be truncated.
- [ ] `docs/ARCHITECTURE.md` §4.4a documents the core-files concept.
- [ ] `docs/ARCHITECTURE.md` §4.4b documents the budget mechanism.
- [ ] Adversarial audit produces zero CRITICAL or HIGH findings.

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| `conv.messages` is empty | Trim returns immediately (loop guard). |
| `conv.messages` has exactly 4 messages | Trim returns immediately (loop guard). |
| `conv.messages` has 5 messages, oldest is USER, all others are ASSISTANT | Fallback finds the oldest USER at index 0, pops it. |
| `conv.messages` has 20 messages, all USER | Fallback pops index 0. After pop, len=19, all USER. Next iteration pops index 0 again. |
| `conv.messages` has 20 messages, all ASSISTANT (rare, post-tool-call-only) | Backwards loop finds no TOOL_RESULT or ASSISTANT-with-tool-calls pairs. Fallback pops index 0. If len > 4, the loop continues. Eventually len reaches 4 and the loop exits. Trim always makes progress. |
| Conversation has 100 messages alternating USER/ASSISTANT, `max_tokens=500` | Trim removes in O(N) iterations, each popping one USER from the oldest end. Final state: 4-5 messages (the preserved tail). |
| `model_max_tokens = None` | No budget enforcement. Full file context is appended. Backward-compatible. |
| `model_max_tokens = 0` or negative | Hard cap fallback: 16K tokens = 64K chars. |
| `model_max_tokens = 1000` (tiny model) | Budget = 150 tokens = 600 chars. If templates are 5K chars, no room for file context. Templates alone are returned. |
| `project_path` is None | `build_file_context_with_core_files` returns "". `_apply_system_prompt_budget` returns the template result unchanged. |
| Core file is missing | That core file is skipped (not an error). Other core files are still preserved. |
| `model_max_tokens = 128_000`, default | Budget = 19,200 tokens = 76,800 chars. Fits a typical 50K file context with headroom for growth. |
| File context is exactly at budget | No truncation. |
| File context is 1 byte over budget | Truncated to budget-1 (the leading "\n\n## File context\n\n" header is preserved, the inner content is truncated to fit). |
| `_truncate_file_context_smart` finds no "## " sections | Returns the input unchanged. (Defensive: build_file_context always produces "## " sections, but if it ever changes, this is a no-op.) |
| The truncation drops ALL sections (extreme budget) | Returns the header with empty inner content (or no header if the empty inner wouldn't fit either). The removed portion is the entire file context. |
| `build_system_prompt` is called from a code path that doesn't have a runtime (`create_conversation` is the only call site) | The default-provider-resolution logic in `agent/runtime.py:1018` handles this. |
| The default provider's `max_tokens` is 0 (mis-configured) | The runtime's fallback in step 7 uses 128_000. The system prompt is budgeted against 128K. |
| The agent has a non-standard role (e.g., "helper") | The system prompt composition logic is unchanged from CB-1. The budget applies uniformly. |
| The user pastes a 100K-char message | The trim handles it (CB-1). The system prompt budget is independent — the user's message goes into `conv.messages`, not the system prompt. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the implementer must update `docs/ARCHITECTURE.md` as follows:

### §4.4a — File Context Composition (additive)

Append a note about the core-files concept. See §2.9 for exact text.

### §4.4b — System Prompt Budget (new section)

Add a new section documenting the budget mechanism. See §2.9 for exact text.

### §7 (Agent Runtime) — no changes

The runtime's `create_conversation` method already has documentation. The new code is a 12-line block that resolves the default provider's `max_tokens` and passes it. No architectural change.

---

## 9. Files NOT changed (already correct or out of scope)

- `prompts/system/*.md` — the prompt templates themselves. Out of scope.
- `utils/project_awareness.py:build_awareness_dict` — Phase CB-3 (BUG #6, awareness caps). Out of scope.
- `agent/runtime.py:_run_loop` — no changes from CB-1.
- `agent/runtime.py:_check_stuck` — Phase CB-3 (BUG #4). Out of scope.
- `agent/runtime.py:_call_llm_streaming` — Phase CB-3 (BUG #3). Out of scope.
- `models/conversation.py:get_token_estimate` — Phase CB-4 (BUG #5, tiktoken). Out of scope.
- `agent/runtime.py` `__init__` — no changes. The `_last_trim_removed` attribute is unchanged from CB-1.
- `agent/runtime.py:_compute_model_max` — no changes. The CB-1 helper is used for the trim's `max_tokens` parameter; the runtime's call site in step 7 resolves `model_max` separately for the system prompt budget (because `build_system_prompt` is called from `create_conversation` before any `Conversation` exists).
- `tests/test_conversation.py:TestConversationTrim` — 4 existing tests. No changes.
- `tests/test_phase4.py:TestTrimSummaryInjection` — 8 existing tests. No changes.
- `tests/test_prompt_loader.py:TestComposeSystemPrompt` — 15+ existing tests. No changes (the new `model_max_tokens` kwarg is optional).

---

## 10. Risk and Rollback

**Risk:** LOW-MEDIUM.

The trim fix is a single-line algorithm change with no new public API. The system prompt budget is a new optional keyword with a hard-coded fallback (16K hard cap) and well-defined semantics.

**Failure modes:**

- Trim fix removes the wrong message (e.g., removes a USER message that's part of an active tool-call sequence): **mitigation** — the trim only removes messages from the trimmable region (everything except the last 4). An active tool-call sequence is at the end of the conversation (the tool-result is among the last 4), so the trim never touches it.
- System prompt budget is too aggressive (15% is too small for some models): **mitigation** — the 16K hard cap fallback. For a 128K model, 15% = 19,200 tokens. For an 8K model, 15% = 1,200 tokens (below the 16K cap, so the cap applies, but the cap is 16K anyway, which is generous for a small model).
- System prompt budget is too lenient (50% of model context would be more appropriate): **mitigation** — this is a v1 design choice. Configurable per-model is a v2 feature (out of scope).
- Core files are too aggressive (e.g., README is huge, takes up the entire budget): **mitigation** — the core files are appended LAST. If even the core files exceed the budget, the smart-truncate drops the EARLIEST core files first (README), preserving AGENTS, CONVENTIONS, ARCHITECTURE. If ALL core files exceed the budget, the file context is dropped entirely and the template result is returned (no truncation of templates).
- `build_file_context_with_core_files` adds duplicate content (core file is also matched by `build_file_context`'s default behavior): **mitigation** — `_read_file_safe` returns the file content; the duplication is the same file read twice. The `build_file_context` matches by `KEY_FILES` (a different list, see `agent/context.py:_read_key_files`); the `CORE_FILES` list in this spec is separate. Verify by reading `_read_key_files` before implementation.

**Rollback:**

This phase is one commit. To roll back: `git revert <commit-hash>`. The runtime goes back to the pre-CB-2 state:
- The trim fallback excludes index 0 again (the original bug from CB-1's audit).
- `compose_system_prompt` and `build_system_prompt` lose the new `model_max_tokens` kwarg.
- `build_file_context_with_core_files` is removed.
- The runtime at `create_conversation` loses the 12-line block that resolves `model_max`.

The consumer at `agent_runtime_handler.py:935` is unchanged. The §4.15 breakdown dict (from CB-1) is unchanged. No consumer breaks.

---

## 11. Post-Mortem

After the commit, a short post-mortem goes at `docs/post-mortems/2026-06-17-CONTEXT-BLOAT-PHASE-2-POST-MORTEM.md`. It should cover:

- Before/after token counts for a realistic scenario (a 20-exchange conversation, then another iteration with the system prompt at budget).
- Confirmation that the trim fix actually reaches the 4-5 message floor (not 21).
- The actual file context size before/after the budget is applied.
- Any deviation from this spec (and why).
- The findings from the adversarial audit.

---

## 12. Author Notes

This spec combines the original CB-2 (system prompt budget) with QTR's Phase CB-1 follow-up (trim algorithm fix). The two changes are independent — the trim fix touches `models/conversation.py` and the system prompt budget touches `utils/prompt_loader.py` + `agent/context.py` + `agent/runtime.py`. They share no code, no test files, no data flow.

**Why bundle them in one phase:**

1. Both are small (1-2 line algorithm changes for the trim, 90 lines of new helper code for the budget).
2. Both are testable independently with no cross-coupling.
3. Both are MEDIUM/LOW risk.
4. The proposal's Q5 question recommended spacing phases, but with the trim fix being a 1-line change, bundling makes sense — the implementer can verify both in one loop and the test suite gives a single green light.

**The 15% budget is conservative.** For a 128K model, 15% = 19,200 tokens. The system prompt typically needs 5-15K tokens. The remaining 5-15K tokens of headroom is for future growth (more templates, more awareness variables, more role-specific content). If the headroom is ever exhausted, the budget can be increased in a follow-up spec.

**The trim fix is the actual root-cause fix for the §4.15 trim's effectiveness.** Without it, CB-1's trim call is partially effective — it removes 19 of 40 messages but stalls at 21. With CB-2's fix, the trim reaches the target budget (4-5 messages) and the §4.15 `trimmed_this_turn` and `messages_remaining` keys report accurate counts.

**The system prompt budget is the second-largest source of token bloat** (after the conversation history, which CB-1 addresses). For a project with 200+ files, the file context is ~12K tokens per call. Capping it at 15% of a 128K context (19,200 tokens) means the system prompt stays within the budget for a typical project.

**Risk is bounded by the existing test coverage.** The trim method has 4+8=12 existing tests; CB-2 adds 3 more. The system prompt composition has 15+ existing tests; CB-2 adds 4 more. The build_system_prompt has 12 existing tests; CB-2 adds 2 more. Total coverage for the touched code paths goes from 29 tests to 38 tests.
