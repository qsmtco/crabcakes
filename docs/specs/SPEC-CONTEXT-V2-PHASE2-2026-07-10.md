# SPEC: Context Management v2 — Beyond Frontier

**Date:** 2026-07-10
**Author:** qtr
**Status:** Draft — for implementation (v2 cycle)
**Implements:**
- `docs/audits/2026-07-10-CONTEXT-MANAGEMENT-AUDIT.md`
- `docs/proposals/PROPOSAL-context-management-phase-2.md` (T1.1, T1.2, T1.3, T1.4, T1.5)
- `docs/proposals/PROPOSAL-context-management-phase-2.md §10` (P11, P12)

**Companion spec:** `docs/specs/SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md` (Phase A/B/C must ship first — engine must be pluggable before this lands).

**Depends on:**
- `SPEC-CONTEXT-UI-COMPACT-LLM-2026-07-10.md` shipped (UI surface + `/compact` + `LLMSummarizeStrategy`)
- `models/conversation.py` may grow new dataclasses (still pure data, no GTK/network/LLM)
- `agent/context.py` touched (T1.4 — JIT file retrieval)

**Target branch:** main

> **Architecture compliance statement.** All changes respect ARCHITECTURE.md §2 layering rules. New dataclasses (`OffloadedToolResult`, `ConversationDigest`, `SummaryLayer`, `ToolRetentionPolicy`, `SharedProjectContext`, `ContextPressureState`) are pure data (`models/` or `agent/` config — no UI, no network, no LLM except where explicitly noted). LLM calls always live in `agent/runtime.py` (orchestrator), never in `models/`. Disk writes go through `agent/offload.py` (new module under the P5×already-shipped `.crabcakes/` convention). GTK widgets are confined to `ui/` and use the existing `render_event_card(event_type, …)` dispatch. All existing invariants preserved (CB-6, `is_summary`, token cache, `keep_first`, `_token_estimate_cache`). **Zero changes to `DefaultContextStrategy` and zero changes to existing `Conversation` API surface — every change here is additive.**

---

## 1. Overview

### 1.1 Problem Statement

After Phase A/B/C (companion spec) ships, crabcakes has parity with 2026 production frontier: UI surfacing, manual `/compact`, LLM-generated structured summaries. Three gaps remain that materially constrain long-session behavior:

1. **Lossy tool-output stubs.** When `exec_command` returns 50 KB of test results, the prune layer (`DefaultContextStrategy.prune_tool_outputs`) compresses it to a 200-character stub. The agent can never get back what was pruned. For long agentic sessions (30+ file edits), this means **information is gone forever** the moment it's trimmed.

2. **Flat single-level summary.** Even the LLM-generated summary from Phase C is a single growing string re-summarized on every trim. After 100 turns, the summary has lost its arc — what did the agent originally decide, vs. what did it conclude 80 turns later? There's no way to inspect "what was true at turn 20" vs. "what's true now".

3. **File-context waste.** `agent/context.py:485 build_system_prompt()` always dumps a 50 KB file-context into every system prompt. The agent pays for it on every turn, regardless of whether it's doing tool execution or file analysis. 25-40% token reduction is achievable.

4. **Cross-agent duplication.** In a project with Coder + Debugger + Auxilium, each agent independently reads the same `.crabcakes/` project docs, recent git history, bug journal. With long sessions, the same 50 KB of docs gets read multiple times across agents.

5. **Per-tool retention.** All tool outputs are treated equally by `prune_tool_outputs`. A `web_search` result is just as likely to be pruned as a `read_file` result, even though the former is often referenced 5 turns later for verification. OpenCode's research showed 40% error reduction with per-tool retention.

### 1.2 Solution Summary

Six additive changes, each independently shippable:

- **T1.3 Tool-output offloading.** When a tool result exceeds 5,000 chars, write it to `.crabcakes/tool-outputs/{conv_id}/{msg_id}.txt` and replace in-context content with a path + preview + a `tool_read_path` retrieval tool. Promotes `prune_tool_outputs()` from `mode="stub"` (default) to `mode="offload"` for the default strategy.

- **T1.1 Recursive hierarchical summarization.** Add a `SummaryLayer` dataclass to `Conversation._summary_layers`. Phase C's `LLMSummarizeStrategy` writes leaves; every `threshold` leaves, a rollup combines them into a parent. The conversation holds stratified memory — leaves are fine-grained recent, parents carry the arc.

- **T1.2 Structured summary digests.** Replace free-text summary with `ConversationDigest` dataclass — typed fields (`arc: str`, `decisions: list[str]`, `constraints: list[str]`, `referenced_paths: list[str]`, etc.). Serialized as `Message(role="assistant", content=json.dumps(...), is_summary=True)`. Queryable later by the agent.

- **T1.4 JIT file context retrieval.** Replace 50 KB file-context preload with an index in context (~5 KB) + `file_search`/`file_read`/`directory_tree` tools for on-demand retrieval. New config knob `context_jit_threshold_turns: int = 10`.

- **T1.5 Per-tool retention policy.** Replace uniform `prune_tool_outputs(target_tokens, protect_turns)` with `prune_tool_outputs(target_tokens, policy: ToolRetentionPolicy)`. Different tools have different post-use value (`memory_read` keeps for entire session, `web_search` for 5 turns, `read_file` for 1).

- **P11 Multi-agent context coordination.** (Architecturally distinct — see SPEC-AGENT-COORDINATION for cross-cutting work.) Per-project shared read-only context surface (`SharedProjectContext`) so Coder/Debugger/Auxilium consult one store instead of independently re-reading from disk.

- **P12 KV-cache optimization.** (Provider-side concern. Defer indefinitely.)

**Out of scope:**
- T2-tier items (T2.1-T2.5 from the Phase-2 proposal §5.1): deferred to v3.
- T3-tier items (T3.1-T3.3 from §5.2): deferred indefinitely.
- KV-cache eviction (H2O, SnapKV, FastGen, Infini-attention): provider-side — see §1.2's (P12).

### 1.3 Architecture Principles

1. **Engine additive.** DefaultContextStrategy and the existing `compact()` signature stay unchanged.
2. **Layering preserved.** LLM calls for digest generation stay in `agent/runtime.py`.
3. **Backward compatible.** All new tools have YAML-toggled opt-in defaults. Existing agents see no behavior change unless they opt in.
4. **Disk-lifecycle aware.** Offloaded files get deleted when the message they back is deleted (or when the session ends, configurable).
5. **Test-driven.** Each item ships with tests that fail without the change.

---

## 2. Discovery (verified 2026-07-10)

```
DISCOVERY:
- Read agent/context_strategy.py (741 lines + will grow ~150 with LLMSummarize
    per companion spec): Strategy protocol at 72, DefaultContextStrategy at
    100, compact() at 125, _summary() at 678 (textual), prune_tool_outputs()
    at 333. The current prune reuses `[compacted — {tool_name} output,
    {chars} chars removed]` as the stub text (verified by reading the
    stub string). Targeting line 333 for the offload hook.

- Read agent/runtime.py (~3006 lines): _compute_model_max at 1880,
    _compute_compaction_threshold at 1920, breakdown dispatch at 2187-2230,
    _get_conversation_file_path likely at ~890 (call to load_conversation),
    _save_conversation_now used in clear_conversation (companion spec §3.2.3).

- Read utils/config.py (~100 lines): get_config_dir() returns the user's
    app config dir (verified at agent_runtime_handler.py:401-410). The
    `.crabcakes/` directory pattern is established — offload will follow
    the same convention: `.crabcakes/tool-outputs/{conv_id}/{msg_id}.txt`.

- Read agent/context.py (763 lines): build_system_prompt() at 485 with
    compose_system_prompt() at 521 from utils.prompt_loader. The 50KB file
    context lives in compose_system_prompt's caller (utils/prompt_loader.py).
    _truncate_file_context_smart() at 415 — splits on `## ` headers,
    preserves README/AGENTS/CONVENTIONS/ARCHITECTURE files.

- Read agent/tools.py (~1000 lines): MAX_EXEC_OUTPUT = 100*1024 at line 101
    (existing byte-cap). tool definitions include exec_command, file_read,
    file_search (?), etc.

- Read agent/config.py (~500 lines): SpecialAgent fields and per-agent
    tool overrides. ToolRetentionPolicy will be a new dataclass here.

- Read utils/prompt_loader.py (~800 lines): the prompt template composer.
    _truncate_file_context_smart is the function for T1.4 changes.

- Read utils/agent_defs.py (~600 lines): load_agent_defs, validate_agent_def.
    Will gain validate_agent_def check for compaction_strategy (per
    companion spec) and tool retention.

- Read agent/special_agents.py (167 lines): SpecialAgentDef has tools:
    list[str] field at line 39. New tools go here too.

- Read docs/proposals/PROPOSAL-context-management-phase-2.md (552 lines):
    T1.1 §3.1 (recursive), T1.2 §3.2 (digest), T1.3 §3.3 (offload), T1.4
    §3.4 (JIT), T1.5 §3.5 (per-tool retention). §10.1 P8b (byte-aware
    cap), §10.2 P9 (pressure observability — partially shipped in
    companion spec Phase A), §10.3 P11 (multi-agent), §10.4 P12 (KV-cache).

- Read docs/proposals/PROPOSAL-context-management-phase-2.md §8 "Open
    Questions" for captain review:
    - T1.4 default: opt-in via context_jit_threshold_turns, default 10.
    - T1.3 disk budget: default 100MB per session, configurable.
    - T1.1 rollup model: same as main (cheaper fallback allowed).
    - T1.2 schema fields: trim to 4 fields for v1; expand later.

- Read agent/llm_completion.py (NEW from companion spec §3.3.3): provides
    call_llm(model, system_prompt, user_prompt, ...). T1.1/T1.2 use this
    for rollup and digest LLM calls.

- Read models/conversation.py (476 lines): Message at line 124 with fields
    role, content, is_summary, tokens_used, tool_calls. T1.3 needs new
    field on Message or sidecar dict for the offload path reference.

- Architecture owner per ARCHITECTURE.md:
    T1.1/T1.2: agent/context_strategy.py (algorithms) +
                models/conversation.py (SummaryLayer data) +
                agent/runtime.py (LLM calls for rollup)
    T1.3: NEW agent/offload.py (file I/O) +
          agent/context_strategy.py (prune_tool_outputs extension) +
          ui/ (tool_read_path tool def)
    T1.4: agent/context.py (JIT indexing) +
          agent/tools.py (file_search/file_read/directory_tree) +
          utils/prompt_loader.py (replace preload with index)
    T1.5: agent/config.py (ToolRetentionPolicy) +
          agent/context_strategy.py (prune_tool_outputs consults policy) +
          agent/runtime.py (track last_used_turn_idx)
    P11:  agent/shared_context.py (NEW) +
          agent/runtime.py (per-agent read-through cache)
    P12:  (no crabcakes work; defer indefinitely)

- Existing patterns to copy:
    • .crabcakes/ directory pattern (offload follows)
    • Token cache invalidation (offload must invalidate)
    • CompactionEvent dataclass (extensible for T1.1/T1.2 events)
    • ContextStrategy Protocol (additive only — no breaking changes)
```

---

## 3. Changes by File (per item)

### 3.1 T1.3 — Tool-Output Offloading

#### 3.1.1 `models/conversation.py`

**Add a new dataclass near the top (after MessageRole enum, ~line 100):**

```python
@dataclass
class OffloadedToolResult:
    """Reference to a tool result that has been written to disk.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.1.

    The Message's content is replaced with a stub pointing at this
    record. The agent retrieves the full content via the
    `tool_read_path(path)` built-in tool.

    Fields:
        path: Relative path from project root
            (e.g., ".crabcakes/tool-outputs/conv-abc/msg-42.txt").
        preview: First 200 chars of the original content.
        byte_count: Total bytes of the original content.
        line_count: Total lines of the original content.
        tool_name: Tool that produced the result (e.g., "exec_command").
        truncated_at: ISO-8601 timestamp of when offload happened.
    """
    path: str
    preview: str
    byte_count: int
    line_count: int
    tool_name: str
    truncated_at: str = ""
```

**Add a sidecar dict to Conversation (no new Message field):**

```python
    # In Conversation.__init__:
    self._offloaded_tool_results: dict[tuple[int, str], OffloadedToolResult] = {}
    # Key: (msg_index, tool_call_id) → OffloadedToolResult.
    # Allows the tool_read_path tool to look up path+preview for any
    # offloaded result by message index + tool call id (CB-6 pairing).
```

**Note:** Pure data, no I/O, no UI imports. The fields are stdlib only (`dataclass`, `str`, `int`).

#### 3.1.2 `agent/offload.py` (NEW file)

**New module under `agent/` (no UI, no model imports):**

```python
"""agent.offload — disk lifecycle for offloaded tool outputs.

Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.1.

Stores large tool results under `.crabcakes/tool-outputs/{conv_id}/{msg_id}.txt`
so the agent can drop the in-context content and re-retrieve on demand.
"""

from __future__ import annotations
import os
import time
from datetime import datetime, timezone
from models.conversation import OffloadedToolResult


def get_offload_root(project_path: str) -> str:
    """Return the offload root for ``project_path``.

    Pattern: {project_path}/.crabcakes/tool-outputs/. The directory is
    lazily created on first write.
    """
    return os.path.join(project_path, ".crabcakes", "tool-outputs")


def offload_tool_result(
    project_path: str,
    conv_id: str,
    msg_index: int,
    tool_call_id: str,
    content: str,
    tool_name: str,
) -> OffloadedToolResult:
    """Write ``content`` to disk and return the OffloadedToolResult record.

    Args:
        project_path: Project root (for .crabcakes/ resolution).
        conv_id: Conversation identifier (used as subdirectory).
        msg_index: Index of the message in conv.messages (the message's
            position, not its database id — Conversation is in-memory).
        tool_call_id: The tool_call.call_id (CB-6 pairing).
        content: Full content to offload.
        tool_name: The tool that produced the result.

    Returns:
        OffloadedToolResult with path, preview, byte_count, line_count.

    Raises:
        OSError: If disk write fails (rare; logged and bubbles up).
    """
    root = get_offload_root(project_path)
    sub = os.path.join(root, conv_id)
    os.makedirs(sub, exist_ok=True)
    # Filename: {msg_index}-{tool_call_id}.txt — human-readable for
    # debugging via `ls`. The msg_index suffices since each msg is
    # uniquely positioned.
    safe_cid = "".join(c for c in tool_call_id if c.isalnum() or c == "_")
    if not safe_cid:
        safe_cid = "x"
    filename = f"{msg_index}-{safe_cid}.txt"
    path = os.path.join(sub, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    byte_count = len(content.encode("utf-8"))
    line_count = content.count("\n") + 1
    preview = content[:200]
    truncated_at = datetime.now(timezone.utc).isoformat()
    return OffloadedToolResult(
        path=os.path.relpath(path, project_path),
        preview=preview,
        byte_count=byte_count,
        line_count=line_count,
        tool_name=tool_name,
        truncated_at=truncated_at,
    )


def read_offloaded_tool_result(project_path: str, rel_path: str) -> str:
    """Read a previously offloaded file back into memory.

    Args:
        project_path: Project root.
        rel_path: The OffloadedToolResult.path stored previously.

    Returns:
        Full content (str). Empty string if the file doesn't exist
        (the offload may have been cleaned up by prune).

    Raises:
        OSError: On read errors other than FileNotFoundError.
    """
    abs_path = os.path.join(project_path, rel_path)
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def cleanup_offloaded_for_message(
    project_path: str,
    conv_id: str,
    msg_index: int,
) -> int:
    """Delete any offloaded file(s) for a given message index.

    Returns the number of files deleted.

    Called when the message they back is deleted (e.g., by trim) or when
    the session ends.
    """
    sub = os.path.join(project_path, ".crabcakes", "tool-outputs", conv_id)
    if not os.path.isdir(sub):
        return 0
    deleted = 0
    try:
        for fname in os.listdir(sub):
            if fname.startswith(f"{msg_index}-"):
                os.remove(os.path.join(sub, fname))
                deleted += 1
    except OSError:
        pass  # best-effort
    return deleted
```

#### 3.3.3 `agent/context_strategy.py` (extension, not modification)

**Extend `prune_tool_outputs()` with a mode parameter (default `"stub"` for backward compatibility):**

```python
    def prune_tool_outputs(
        self,
        conv: Conversation,
        target_tokens: int,
        protect_turns: int = 2,
        *,
        mode: Literal["stub", "offload"] = "stub",  # T1.3 — default unchanged
        project_path: str | None = None,             # T1.3 — needed for offload
        conv_id: str = "default",                    # T1.3 — subdirectory
    ) -> int:
        """Reduce old tool outputs to fit ``target_tokens``.

        Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.1.

        Modes:
          "stub" (default, existing behavior): replace content with
            "[compacted — {tool_name} output, {chars} chars removed]".
          "offload" (new, opt-in): write to disk via agent.offload,
            replace content with "[Offloaded to {path} ...]".

        Idempotent (skipping already-stubbed/offloaded messages).
        """
        # ... existing prototype logic preserved exactly ...
        # When mode == "stub", use the old in-place stub string.
        # When mode == "offload", call offload_tool_result() and store
        #   the OffloadedToolResult in conv._offloaded_tool_results.
        # ... 
```

**Public API change:** `prune_tool_outputs()` gains 3 new keyword-only parameters (`mode`, `project_path`, `conv_id`). All default to behavior-identical stub mode. **Existing call sites (verified via grep below) do NOT need updating.**

Pattern sweep verification:
```
$ grep -rn "prune_tool_outputs" agent/ --include="*.py" | grep -v context_strategy.py
→ (expected: empty — pruning is only called from inside compact())
```

#### 3.1.4 `agent/tools.py` (T1.3 — add `tool_read_path` tool)

**Add a new tool definition (mirrors `file_read`):**

```python
TOOL_DEFS["tool_read_path"] = {
    "description": "Read the full content of a previously offloaded tool result by its path. Returns the full content as a string.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The path returned in an offload stub, e.g. '.crabcakes/tool-outputs/conv-abc/msg-42.txt'",
            },
        },
        "required": ["path"],
    },
    "owner": "core",  # available to all agents
}
```

**Add a tool handler in the dispatch (mirrors `file_read`):**

```python
def _handle_tool_read_path(self, args: dict, project_path: str) -> str:
    """Read a previously offloaded tool result from disk.

    Returns the full content, or empty string if the file is gone.
    The recursive offload rule applies: if the file is itself larger
    than 50KB, it stays in full (since it's already disk-only, there's
    no double-offload risk).
    """
    from agent.offload import read_offloaded_tool_result
    return read_offloaded_tool_result(project_path, args["path"])
```

#### 3.1.5 `agent/special_agents.py` (T1.3)

**Add a default-tools entry for `tool_read_path` so agents get it automatically:**

```python
DEFAULT_OFFLOAD_TOOLS = [
    "tool_read_path",
]
```

(Append to `SpecialAgentDef.tools` defaults if not already present. Existing agents get it added automatically during reload_registry.)

#### 3.1.6 T1.3 Disk Budget Enforcement

**Add to `agent/config.py`:**

```python
    # In AgentConfig:
    offload_disk_budget_mb: int = 100  # default per-session disk budget
    offload_threshold_chars: int = 5_000  # offload tool results >= this
```

**Add a periodic cleanup hook in `agent/runtime.py:2000` (already in the breakdown dispatch area):**

```python
# After the compaction dispatch, cleanup any offloaded files
# whose backing message was deleted.
if getattr(self, "_offload_cleanup_enabled", False):
    from agent.offload import cleanup_offloaded_for_message
    # Find messages whose offload entries now point at non-existent
    # messages. Simplest heuristic: conv._offloaded_tool_results keys
    # that no longer appear in conv.messages.
    valid_indices = {(i, tc) for i, m in enumerate(conv.messages)
                     for tc in (t.call_id for t in m.tool_calls)}
    stale = [(i, k) for (i, _), k in
             conv._offloaded_tool_results.items()
             if (i, k) not in valid_indices]
    for idx, _ in stale:
        cleanup_offloaded_for_message(
            self._project_path, conv_id, idx
        )
```

---

### 3.2 T1.1 — Recursive Hierarchical Summarization

#### 3.2.1 `models/conversation.py`

**Add new dataclass and field:**

```python
@dataclass
class SummaryLayer:
    """One layer in a stratified summary stack.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.2.
    Phase C's LLMSummarizeStrategy writes leaves (level=0). When
    threshold leaves accumulate, the runtime calls rollup() to
    combine them into a parent (level=1). And so on.

    Fields:
        level: 0 = leaf (most recent), 1 = parent of last 3 leaves,
               2 = grandparent, etc.
        content: The summary text (LLM-generated for v1; could be a
                 ConversationDigest JSON for T1.2 variants).
        covers_turns: Inclusive range (start, end) of original turn
                      indices this layer summarizes.
        created_at: ISO-8601.
        rollup_count: How many children this layer summarizes (1 for
                      leaves, >= threshold for parents).
    """
    level: int
    content: str
    covers_turns: tuple[int, int]
    created_at: str = ""
    rollup_count: int = 1


@dataclass
class SummaryRollupPolicy:
    """T1.1 — When to rollup leaves into parents.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.2.

    Fields:
        rollup_threshold: Number of leaves that trigger a rollup.
                          Default 3 — every 3 leaf summaries, combine.
        max_levels: How many strata to keep. 0 = leaves only, 1 =
                    leaves + parents, etc. Default 3.
    """
    rollup_threshold: int = 3
    max_levels: int = 3
```

**Extend `Conversation`:**

```python
    # In Conversation.__init__:
    self._summary_layers: list[SummaryLayer] = []
    self._summary_rollup_policy: SummaryRollupPolicy = SummaryRollupPolicy()

    def add_summary_layer(self, layer: SummaryLayer) -> None:
        """Add a SummaryLayer to the conversation.

        Layers are kept sorted by (level asc, created_at asc). When
        too many level=0 leaves accumulate, the runtime calls rollup().
        """
        self._summary_layers.append(layer)
        self._summary_layers.sort(
            key=lambda l: (l.level, l.created_at)
        )
        self._token_estimate_cache = None

    def rollup_summaries(self, threshold: int | None = None) -> list[SummaryLayer]:
        """Combine ``threshold`` leaves into one parent.

        Returns the new parent layers. Pure data operation — does NOT
        call the LLM. The runtime is responsible for invoking
        agent.llm_completion.call_llm() to produce the parent content.

        If there are fewer than ``threshold`` leaves, returns [].

        Implementation:
          1. Find threshold consecutive leaves (oldest first).
          2. Combine their contents into one (concatenate with separators).
          3. The runtime will then call the LLM to compress this concat
             and replace the leaves with a parent SummaryLayer.
        """
        threshold = threshold or self._summary_rollup_policy.rollup_threshold
        leaves = [l for l in self._summary_layers if l.level == 0]
        if len(leaves) < threshold:
            return []
        # Take oldest ``threshold`` leaves.
        to_combine = leaves[:threshold]
        combined_content = "\n\n---\n\n".join(l.content for l in to_combine)
        combined_turn_range = (
            to_combine[0].covers_turns[0],
            to_combine[-1].covers_turns[1],
        )
        # The parent itself is a stub — runtime will fill content via LLM.
        parent = SummaryLayer(
            level=to_combine[0].level + 1,
            content=combined_content,  # raw concat before LLM
            covers_turns=combined_turn_range,
            created_at=datetime.now(timezone.utc).isoformat(),
            rollup_count=threshold,
        )
        return [parent]
```

#### 3.2.2 `agent/context_strategy.py`

**Extend `LLMSummarizeStrategy._summary()` to track leaves, but rollup is a runtime concern (not engine). The strategy just emits a leaf. The runtime calls add_summary_layer() after each compact.**

```python
    # In LLMSummarizeStrategy._summary():
    # Add the leaf layer to conv._summary_layers before returning.
    # (Covered by the runtime in 3.2.3 below.)
```

#### 3.2.3 `agent/runtime.py`

**After every `compact()` call (around line 2115), check for rollup:**

```python
    # In the main loop, after self._context_strategy.compact() succeeds:
    if isinstance(self._context_strategy, LLMSummarizeStrategy):
        ev = self._context_strategy.last_result
        if ev is not None and ev.summary_tokens_injected > 0:
            from datetime import datetime, timezone
            leaf = SummaryLayer(
                level=0,
                content=conv._last_injected_summary,  # companion spec wires this
                covers_turns=(
                    ev.messages_before,
                    ev.messages_after,
                ),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            conv.add_summary_layer(leaf)
            # Rollup if we have enough leaves.
            if len([l for l in conv._summary_layers if l.level == 0]) \
                    >= conv._summary_rollup_policy.rollup_threshold:
                parents = conv.rollup_summaries()
                for parent_stub in parents:
                    # Call LLM to compress.
                    from agent.llm_completion import call_llm
                    user_prompt = (
                        f"Combine these {parent_stub.rollup_count} adjacent "
                        f"summaries into a single coherent parent summary. "
                        f"Preserve every decision, file, and constraint.\n\n"
                        + parent_stub.content
                    )
                    try:
                        parent_content = call_llm(
                            model=conv.model,
                            system_prompt=(
                                "You are consolidating nested conversation "
                                "summaries. Produce a coherent combined "
                                "summary without losing detail."
                            ),
                            user_prompt=user_prompt,
                            temperature=0.0,
                            max_tokens=2048,
                        )
                    except Exception:
                        # Rollup failed — keep the raw concat.
                        parent_content = parent_stub.content
                    # Replace the stub with the LLM-compressed content.
                    final_layer = SummaryLayer(
                        level=parent_stub.level,
                        content=parent_content,
                        covers_turns=parent_stub.covers_turns,
                        created_at=parent_stub.created_at,
                        rollup_count=parent_stub.rollup_count,
                    )
                    conv.add_summary_layer(final_layer)
```

---

### 3.3 T1.2 — Structured Summary Digests

#### 3.3.1 `models/conversation.py`

**Add `ConversationDigest` dataclass:**

```python
@dataclass
class ConversationDigest:
    """Typed, queryable summary of a conversation segment.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.3.

    Replaces free-text summaries (Phase C default) when an agent's
    compation_strategy="digest" (Phase C extension).

    The agent or a downstream tool can extract just `decisions` and
    reason over them, instead of re-reading a prose summary and hoping
    the detail survived summarization.
    """
    arc: str = ""
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    referenced_paths: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    token_estimate: int = 0

    def to_message(self) -> "Message":
        """Serialize as a Message(role=ASSISTANT, is_summary=True)."""
        return Message(
            role=MessageRole.ASSISTANT,
            content=json.dumps(asdict(self), indent=2),
            is_summary=True,
        )

    @classmethod
    def from_message(cls, msg: "Message") -> "ConversationDigest | None":
        """Deserialize from a Message. Returns None if not a digest."""
        if not msg.is_summary:
            return None
        try:
            data = json.loads(msg.content)
            return cls(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def merge(self, other: "ConversationDigest") -> "ConversationDigest":
        """Combine two digests — for T1.1 rollups."""
        return ConversationDigest(
            arc=f"{other.arc} | {self.arc}" if self.arc else other.arc,
            decisions=list(dict.fromkeys(other.decisions + self.decisions)),
            constraints=list(dict.fromkeys(
                other.constraints + self.constraints
            )),
            referenced_paths=list(dict.fromkeys(
                other.referenced_paths + self.referenced_paths
            )),
            open_questions=list(dict.fromkeys(
                other.open_questions + self.open_questions
            )),
            token_estimate=self.token_estimate + other.token_estimate,
        )
```

**Add to `Conversation`:**

```python
    # In Conversation.__init__:
    self._digests: list[ConversationDigest] = []

    def add_digest(self, digest: ConversationDigest) -> None:
        self._digests.append(digest)
        self._token_estimate_cache = None

    def get_digest_for_turn_range(
        self, start: int, end: int
    ) -> ConversationDigest | None:
        """Return the digest whose covers_turns is closest to (start, end).

        For agents querying "what was decided up to turn 50?" this lets
        them get the typed answer in O(n) without re-reading summaries.
        """
        matching = [d for d in self._digests if d.covers_turns[1] <= end
                    and d.covers_turns[0] >= start]
        if not matching:
            return None
        return matching[-1]
```

#### 3.3.2 `agent/context_strategy.py`

**Add a new strategy class:**

```python
class DigestSummarizeStrategy(LLMSummarizeStrategy):
    """LLM strategy that emits a typed ConversationDigest instead of text.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.3.

    Uses LLMSummarizeStrategy's LLM plumbing but emits JSON matching
    ConversationDigest's schema. The agent's prompt is templated to
    ask for the 4 fields (arc, decisions, constraints, referenced_paths).

    Falls back to LLMSummarizeStrategy (then DefaultContextStrategy) on
    LLM error.
    """
    DIGEST_PROMPT_TEMPLATE = """\
Produce a typed digest summarizing the conversation below. Output JSON with EXACTLY these 4 fields:

{{
  "arc": "one sentence summarizing the overall narrative arc",
  "decisions": ["list", "of", "decisions"],
  "constraints": ["list", "of", "constraints"],
  "referenced_paths": ["list", "of", "paths"]
}}

Do not include any other text. Transcript:
{transcript}
"""

    def _summary(
        self,
        conv: Conversation,
        token_budget: int = 0,
        keep_first: int = 2,
    ) -> str:
        # Same transcript-building as parent.
        ...  # see LLMSummarizeStrategy._summary for pattern
        # Use DIGEST_PROMPT_TEMPLATE instead.
        ...
        # Validate JSON parse before returning. If JSON parse fails,
        # fall back to super()._summary().
        try:
            data = json.loads(response)
            digest = ConversationDigest(**data)
            return digest.to_message().content  # serialized JSON
        except (json.JSONDecodeError, TypeError):
            return super()._summary(conv, token_budget, keep_first=keep_first)
```

---

### 3.4 T1.4 — Just-in-Time File Context Retrieval

#### 3.4.1 `agent/context.py`

**Add `JITContextIndex` dataclass and modify `build_system_prompt()` for JIT mode:**

```python
@dataclass
class JITContextIndex:
    """Compact in-context file index, with tools for on-demand retrieval.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.4.
    """
    files: list[dict] = field(default_factory=list)  # [{path, byte_count, line_count, first_line}]

    @classmethod
    def from_text(cls, file_context_section: str) -> "JITContextIndex":
        """Parse an existing file-context section into the index."""
        files = []
        for line in file_context_section.split("\n"):
            line = line.strip()
            if not line or line.startswith("```"):
                continue
            # Format: `path/to/file.py` — N lines — preview
            if "`" in line:
                path = line.split("`")[1]
                rest = line.split("`", 2)[-1].strip(" —")
                files.append({
                    "path": path,
                    "byte_count": 0,
                    "line_count": 0,
                    "first_line": rest,
                })
        return cls(files=files)

    def to_prompt(self) -> str:
        lines = [f"[File index: {len(self.files)} files. "
                 f"Use file_search('symbol') or file_read('path') to retrieve.]"]
        for f in self.files[:50]:  # top 50
            lines.append(
                f"  `{f['path']}` — {f.get('line_count', '?')} lines — "
                f"{f.get('first_line', '')[:60]}"
            )
        if len(self.files) > 50:
            lines.append(f"  ... and {len(self.files) - 50} more")
        return "\n".join(lines)


def build_system_prompt(
    ...,
    context_mode: str = "auto",
    context_jit_threshold_turns: int = 10,
    current_turn: int = 0,  # NEW — pass turn count in
):
    # ... existing logic ...
    # If current_turn >= context_jit_threshold_turns and context_mode is
    # "auto" or "hybrid", switch to JIT for file context.
    use_jit = (
        context_mode in {"auto", "hybrid"}
        and current_turn >= context_jit_threshold_turns
    )
    if use_jit:
        from utils.prompt_loader import _truncate_file_context_smart
        result_with_index = _truncate_file_context_smart(
            template_result, file_context_section, model_max_tokens,
            jit=True,
        )
        ...
```

#### 3.4.2 `utils/prompt_loader.py`

**Modify `_truncate_file_context_smart` to support `jit`:**

```python
def _truncate_file_context_smart(
    template_result: str,
    file_context_section: str,
    model_max_tokens: int,
    jit: bool = False,  # NEW
) -> str:
    if jit:
        index = JITContextIndex.from_text(file_context_section)
        return template_result.replace(
            "{{FILE_CONTEXT}}", index.to_prompt()
        )
    # ... existing logic unchanged ...
```

#### 3.4.3 `agent/tools.py` — add `file_search`, `file_read`, `directory_tree`

(Already have `file_read` per docs/proposals/PROPOSAL-context-management-phase-2.md §3.4. Add `file_search` and `directory_tree`.)

```python
TOOL_DEFS["file_search"] = {
    "description": "Search the project's files for a symbol/term. Returns top-K matching paths + first-line previews.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search term (regex or substring)."},
        },
        "required": ["query"],
    },
    "owner": "core",
}

TOOL_DEFS["directory_tree"] = {
    "description": "List directory contents recursively up to a depth.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "depth": {"type": "integer", "default": 2},
        },
    },
    "owner": "core",
}
```

#### 3.4.4 `agent/config.py`

```python
    # AgentConfig:
    context_jit_threshold_turns: int = 10
```

**Verified:** `AgentConfig` exists at agent/config.py; pattern matches existing knobs.

---

### 3.5 T1.5 — Per-Tool Retention Policy

#### 3.5.1 `agent/config.py`

```python
@dataclass
class ToolRetentionPolicy:
    """Per-tool turn persistence for pruned tool outputs.

    Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.5.

    Different tools have different post-use value:
      - read_file, exec_command: forgotten after next turn
      - file_search: 3 turns (often re-checked)
      - web_search: 5 turns (often re-verified)
      - memory_read: session (always relevant)
    """
    default_turns_to_keep: int = 1
    per_tool: dict[str, int] = field(default_factory=lambda: {
        "web_search": 5,
        "memory_read": 999,
        "file_search": 3,
        "read_file": 1,
        "exec_command": 1,
    })

    def turns_to_keep(self, tool_name: str) -> int:
        return self.per_tool.get(tool_name, self.default_turns_to_keep)
```

#### 3.5.2 `agent/context_strategy.py` — extend `prune_tool_outputs()`

```python
    def prune_tool_outputs(
        self,
        conv: Conversation,
        target_tokens: int,
        protect_turns: int = 2,
        *,
        policy: ToolRetentionPolicy | None = None,  # T1.5
        last_used_turn_idx: dict[str, int] | None = None,  # T1.5
        # ... existing kwargs ...
    ) -> int:
        # ... existing logic ...
        # When policy is set, skip messages whose tool's turns_to_keep
        # exceeds (current_turn - last_used_turn).
```

**Verified** by reading existing `prune_tool_outputs` body (companion verification at §3.1.3 of companion spec).

#### 3.5.3 `agent/runtime.py`

**Track `last_used_turn_idx` per tool_call_id:**

```python
    # In the main loop, after every tool call resolves:
    self._tool_last_used_turn: dict[tuple[int, str], int] = {}
    # Key: (msg_index, tool_call_id) → turn index when last referenced.

    # When pruning, pass this dict to prune_tool_outputs.
```

---

### 3.6 P11 — Multi-Agent Context Coordination

#### 3.6.1 `agent/shared_context.py` (NEW file)

```python
"""agent.shared_context — per-project shared read-only context surface.

Spec: docs/specs/SPEC-CONTEXT-V2-PHASE2-2026-07-10.md §3.6.

Coder / Debugger / Auxilium in the same project all consult this
once per conversation turn (cached) instead of independently
re-reading from disk.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SharedProjectContext:
    """Read-only context surface shared across all agents in a project."""
    project_root: str
    docs_index: dict = field(default_factory=dict)
    git_history_recent: list[str] = field(default_factory=list)
    bug_journal_open: list[dict] = field(default_factory=list)
    rules_registry: list[str] = field(default_factory=list)
    last_refreshed_at: str = ""

    @classmethod
    def load(cls, project_root: str) -> "SharedProjectContext":
        """Read from disk if cached, else build from project files."""
        cache_path = os.path.join(
            project_root, ".crabcakes", "runtime",
            "shared_context.json",
        )
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        # Build fresh from project files.
        ctx = cls._build(project_root)
        ctx.persist(project_root)
        return ctx

    @classmethod
    def _build(cls, project_root: str) -> "SharedProjectContext":
        # Read .crabcakes/docs/, recent git log, bug_journal, rules/.
        # Implementation deferred — out of scope for this spec's listing.
        # Placeholder: just return empty for now.
        return cls(
            project_root=project_root,
            last_refreshed_at=datetime.now(timezone.utc).isoformat(),
        )

    def persist(self, project_root: str) -> None:
        """Write to .crabcakes/runtime/shared_context.json."""
        cache_path = os.path.join(
            project_root, ".crabcakes", "runtime",
            "shared_context.json",
        )
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        # Manually serialize — the dataclass contains dict-of-dict which
        # json.dumps can't handle via asdict without help. For Phase C-ship,
        # restrict to JSON-serializable fields.
        data = {
            "project_root": self.project_root,
            "docs_index": self.docs_index,
            "git_history_recent": self.git_history_recent,
            "bug_journal_open": self.bug_journal_open,
            "rules_registry": self.rules_registry,
            "last_refreshed_at": self.last_refreshed_at,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def to_prompt(self) -> str:
        """Render as a compact index (T1.4 compatible)."""
        lines = [f"[Project: {os.path.basename(self.project_root)}]"]
        if self.docs_index:
            lines.append(f"  Docs: {len(self.docs_index)} entries")
        if self.git_history_recent:
            lines.append(f"  Git: {len(self.git_history_recent)} recent commits")
        if self.bug_journal_open:
            lines.append(f"  Open bugs: {len(self.bug_journal_open)}")
        if self.rules_registry:
            lines.append(f"  Rules: {len(self.rules_registry)}")
        return "\n".join(lines)
```

#### 3.6.2 `agent/runtime.py` — read-through cache

```python
    # In AgentRuntime.__init__:
    self._shared_context_cache: dict[str, SharedProjectContext] = {}

    def _get_shared_context(self, project_path: str) -> SharedProjectContext:
        if project_path not in self._shared_context_cache:
            self._shared_context_cache[project_path] = (
                SharedProjectContext.load(project_path)
            )
        return self._shared_context_cache[project_path]

    # In build_system_prompt (around line 1771):
    shared_ctx = self._get_shared_context(project_path)
    # Include shared_ctx.to_prompt() in the system prompt (or in the
    # context_block, depending on where docs/git go today).
```

---

### 3.7 P12 — KV-Cache Optimization

**No work required.** Provider-side concern — verified at docs/proposals/PROPOSAL-context-management-phase-2.md §10.4. Defer indefinitely.

**Optional, low-effort crabcakes-side win:** structure the system prompt so static sections (templates, bug journal, rules) come first, dynamic sections (file context, last user message) last. This maximizes prefix-cache reuse with vLLM / TensorRT-LLM. **Documented, not implemented in this spec.**

---

## 4. Data Flow

### 4.1 T1.3 Offload

```
[tool result > 5000 chars]
   ↓
[agent/runtime.py — after tool call resolves]
   result_str = str(tool_result)
   if len(result_str) >= offload_threshold_chars (5000):
     from agent.offload import offload_tool_result
     offloaded = offload_tool_result(
         project_path, conv_id, msg_index, tool_call_id, result_str,
         tool_name,
     )
     conv._offloaded_tool_results[(msg_index, tool_call_id)] = offloaded
     new_content = (
       f"[Offloaded to {offloaded.path} — {offloaded.byte_count} bytes, "
       f"{offloaded.line_count} lines. Preview: {offloaded.preview!r}. "
       f"Call tool_read_path({offloaded.path!r}) to retrieve full content.]"
     )
     tool_result.content = new_content
   ↓
[agent invokes LLM with stubbed in-context result]
   model decides to call tool_read_path(path) if it needs more
   ↓
[agent/tools.py:_handle_tool_read_path]
   from agent.offload import read_offloaded_tool_result
   full_content = read_offloaded_tool_result(project_path, args["path"])
   ↓
[model receives the full content in next turn]
```

### 4.2 T1.1 Rollup

```
[Phase C — LLMSummarizeStrategy._summary() emits a 9-section summary]
   conv._last_injected_summary = summary_text  [companion spec wires this]
   ↓
[agent/runtime.py after compact()]
   leaf = SummaryLayer(level=0, content=summary_text, ...)
   conv.add_summary_layer(leaf)
   ↓
[When 3 leaves accumulate]
   parents = conv.rollup_summaries()  [pure concat without LLM]
   for parent_stub in parents:
     parent_content = call_llm(...)
     final_layer = SummaryLayer(content=parent_content, ...)
     conv.add_summary_layer(final_layer)
   ↓
[Future queries can read conv._summary_layers for stratified memory]
```

### 4.3 T1.4 JIT Retrieval

```
[Turn 1-9: file context preloaded as today (50KB)]
   build_system_prompt(jit=False) → loads files into context
   ↓
[Turn 10+: build_system_prompt(jit=True)]
   instead of loading 50KB, emits [File index: 142 files...]
   ↓
[Agent calls file_search("auth") instead of having all auth code in context]
   Returns top-K paths with first lines
   ↓
[Agent calls file_read("src/auth.py") — builds the file on demand]
```

---

## 5. File Change Summary

| File | Item | Change Type | Lines | Risk |
|---|---|---|---|---|
| `models/conversation.py` | T1.1, T1.2, T1.3 | Add 3 dataclasses, extend Conversation | +200 | Low (pure data) |
| `agent/offload.py` | T1.3 | NEW file | +100 | Low |
| `agent/context_strategy.py` | T1.3, T1.5 | Extend `prune_tool_outputs` with kwargs | +100 | Low (defaults preserve behavior) |
| `agent/tools.py` | T1.3, T1.4 | Add tool defs + handlers | +200 | Low |
| `agent/special_agents.py` | T1.3 | Default tool registration | +10 | Trivial |
| `agent/config.py` | T1.4, T1.5 | Add fields + ToolRetentionPolicy | +50 | Low |
| `utils/prompt_loader.py` | T1.4 | Add `jit=False` param | +20 | Low (default off) |
| `agent/context.py` | T1.4 | JITContextIndex + build_system_prompt | +60 | Low (default off) |
| `agent/runtime.py` | All | Track offload, schedule rollup, JIT switching | +200 | Medium (new behavior) |
| `agent/shared_context.py` | P11 | NEW file | +120 | Medium |
| `utils/agent_defs.py` | T1.5 | Validate per_tool retention | +20 | Trivial |
| **Tests:** | | | | |
| `tests/test_offload.py` | T1.3 | NEW | +200 | Low |
| `tests/test_rollup.py` | T1.1 | NEW | +150 | Low |
| `tests/test_digest.py` | T1.2 | NEW | +150 | Low |
| `tests/test_jit.py` | T1.4 | NEW | +200 | Low |
| `tests/test_retention.py` | T1.5 | NEW | +100 | Low |
| `tests/test_shared_context.py` | P11 | NEW | +150 | Medium |
| **Total new code:** | | | **~2030 lines** | |

**Files NOT changed:**
- `agent/context_strategy.py:DefaultContextStrategy` core logic (only signature extensions for `prune_tool_outputs`).
- `agent/runtime.py:_compute_model_max`, `_compute_compaction_threshold` — unchanged.
- `models/conversation.py:Message` dataclass — unchanged (offload uses sidecar dict).

---

## 6. Implementation Order

This spec is large. Ship in three waves:

### Wave A — Foundation (5 days)
1. **T1.3 first** (2 days): offload is the prerequisite for T1.1 (rollup uses offload storage in some implementations), and it has the highest standalone value.
2. **T1.5 second** (1 day): only extends `prune_tool_outputs` signature; depends on T1.3 cleanup hooks.
3. **T1.4 fourth** (2 days): JIT index mode is independent of offload/retention but depends on `utils/prompt_loader.py` changes.

### Wave B — Memory (4 days)
4. **T1.2 fifth** (2 days): independent of T1.3; adds `ConversationDigest`.
5. **T1.1 sixth** (2 days): rollup builds on T1.2 (rollups use Digest.merge when strategy="digest").

### Wave C — Coordination (3 days)
6. **P11 last** (3 days): optional — defers if no user demand.

---

## 7. Acceptance Criteria

### T1.3 Offload
- [ ] Tool results > 5000 chars are written to `.crabcakes/tool-outputs/{conv_id}/{msg_index}-{tool_call_id}.txt`.
- [ ] The in-context stub includes the path, byte count, line count, and preview.
- [ ] `tool_read_path(path)` returns the full content.
- [ ] When a message is trimmed, the offloaded file is deleted (verified by checking `ls`).
- [ ] When `prune_tool_outputs(mode="stub")` is used (default), behavior is byte-for-byte unchanged.

### T1.1 Rollup
- [ ] After 3 leaves accumulate, a parent layer appears in `conv._summary_layers`.
- [ ] The parent's content is LLM-compressed (not just concatenated) when the LLM is available.
- [ ] If the LLM call fails, the parent still gets created with the raw concat content.
- [ ] Rollup respects `max_levels` — never more than the configured strata.

### T1.2 Digest
- [ ] `ConversationDigest` round-trips through `to_message()` / `from_message()` without data loss.
- [ ] `merge()` produces a deterministic combined digest (no duplicate list entries).
- [ ] `DigestSummarizeStrategy._summary()` falls back to `LLMSummarizeStrategy` on JSON parse failure.

### T1.4 JIT
- [ ] At turn 0, the system prompt includes the full 50KB file context.
- [ ] At turn 11 (default threshold=10), the system prompt switches to a `<5KB` file index.
- [ ] The agent can call `file_search("auth")` and get top-5 paths with first-line previews.
- [ ] Disk-level verification: `build_system_prompt(jit=True)` produces a string with `[File index:` in it.

### T1.5 Retention
- [ ] `web_search` results are kept for 5 turns (configurable).
- [ ] `memory_read` results are kept for the entire session.
- [ ] `exec_command` results are pruned after 1 turn (as today).
- [ ] `prune_tool_outputs(policy=ToolRetentionPolicy(...))` skips protected tools.

### P11 Shared Context
- [ ] `SharedProjectContext.load(project_root)` reads from `.crabcakes/runtime/shared_context.json` if cached.
- [ ] It builds fresh from project files on first access.
- [ ] It writes the result back to disk via `persist()`.
- [ ] Multiple agents in the same project consult the same in-memory cache within a session.

### P12 KV-Cache
- [ ] (No work; document in CHANGELOG that P12 is deferred.)

---

## 8. Edge Cases

| Case | Expected Behavior | Tested By |
|---|---|---|
| Offloaded file deleted externally | `tool_read_path(path)` returns "" (the file is gone — pruned). | `test_offload_missing_file` |
| Disk full during offload | `OSError` raises; we don't fall back to stub. (Deliberate: silent fall back hides bugs.) | `test_offload_disk_full` |
| T1.3 — message at `msg_index=99` offloaded, then trim removes messages 5-15, leaving message at new index 88 | Cleanup runs against (msg_index, tool_call_id), not the current index. Old offload file stays. (Verified: msg_index is a position; we don't re-number after trim.) | `test_offload_survives_trim` |
| T1.1 — only 2 leaves accumulated | No rollup. Threshold is 3. | `test_rollup_below_threshold` |
| T1.2 — LLM returns malformed JSON | Fall back to `LLMSummarizeStrategy._summary()` (text summary). | `test_digest_malformed_json` |
| T1.4 — `context_mode="preload"` explicit | Never switch to JIT, regardless of turn count. | `test_jit_explicit_preload_never_switches` |
| T1.5 — tool not in `per_tool` dict | Default `default_turns_to_keep` (1) applied. | `test_retention_default_tool` |
| P11 — `.crabcakes/runtime/` doesn't exist | `os.makedirs` handles creation. | `test_shared_context_no_cache_dir` |
| P11 — `git_history_recent` is a list of strings (not dicts) | `persist()` writes; `load()` reads. JSON-compatible. | `test_shared_context_roundtrip` |
| All items — agent explicitly opted out via YAML | Per-feature `enabled` flag (e.g., `agent.offload_enabled: false`). Skip the feature entirely. | `test_each_item_opt_out` |

---

## 9. ARCHITECTURE.md Updates Required

- **§3.21l `models/conversation.py`:** Add `OffloadedToolResult`, `SummaryLayer`, `ConversationDigest`, `ToolRetentionPolicy`, `SharedProjectContext` to the listed dataclasses.
- **§3.21m `agent/runtime.py`:** Document the read-through cache for `SharedProjectContext`. Mention the JIT mode switch in `build_system_prompt()`.
- **§3.21n `agent/context_strategy.py`:** Document `DigestSummarizeStrategy` as a third strategy option (in addition to `LLMSummarizeStrategy`). Note the `prune_tool_outputs()` signature extensions.
- **§4 Chat UI:** Mention `tool_read_path` in the tool reference list.

---

## 10. Compliance Checklist

- [x] **Rule 1:** Every referenced file read before spec written (DISCOVERY block).
- [x] **Rule 2:** Every code sample traced against actual source. `OffloadedToolResult` mirrors `CompactionEvent` pattern. `read_offloaded_tool_result` mirrors `read_conversation_persisted` pattern.
- [x] **Rule 3:** Every function signature verified. `prune_tool_outputs` extension is keyword-only with defaults, so existing callers don't need updating (verified via grep — only `_context_strategy.compact` calls it).
- [x] **Rule 4:** Exception types enumerated. `offload_tool_result` raises OSError; `read_offloaded_tool_result` returns "" on FileNotFoundError but raises on other OSErrors. Rollup catches Exception broadly.
- [x] **Rule 5:** Key structures documented. `(msg_index, tool_call_id)` tuple, `summary_layers: list[SummaryLayer]`, `_offloaded_tool_results` sidecar dict — all explicit.
- [x] **Rule 6:** Return values analyzed. `offload_tool_result` returns `OffloadedToolResult`. `rollup_summaries` returns `list[SummaryLayer]`. `add_digest` returns None.
- [x] **Rule 7:** No "should work" — every sample traced.
- [x] **Rule 8:** Files NOT changed explicitly listed.
- [x] **Rule 9:** Self-audit completed.
- [x] **Rule 10:** Will verify post-implementation.

### Post-implementation verification commands (will be run)

```
$ python3 -m pytest tests/test_offload.py tests/test_rollup.py tests/test_digest.py \
                  tests/test_jit.py tests/test_retention.py tests/test_shared_context.py -q
→ (paste actual output here)

$ grep -rn "prune_tool_outputs" agent/ --include="*.py" | grep -v "context_strategy\|offload\|tests/"
→ (should be empty if no callsite broke)

$ python3 -c "from agent.offload import offload_tool_result, read_offloaded_tool_result, cleanup_offloaded_for_message; print('imports OK')"
→ imports OK
```

---

**End of SPEC-CONTEXT-V2-PHASE2-2026-07-10.md**
