# Proposal: Just-in-Time Context Discovery (P10) — Replace Upfront File Preloading with On-Demand Retrieval

**Author:** Qaster (supervisor)
**Date:** 2026-06-27
**Status:** Awaiting captain review
**Severity:** MEDIUM — Crabcakes injects up to 50,000 chars (~12,500 tokens) of project file context into the system prompt on every turn, even when the user's question is unrelated to most of those files. This wastes 10–15% of the context window on every single LLM call and accelerates context pressure on long sessions.

**Source research:**
- `docs/research/crabcakes-future-context-strategies.md` §T1.4 (Just-in-time retrieval over preloading)
- `docs/research/context-management-survey-2026.md` (LangChain Write/Select/Compress/Isolate framework)
- `docs/research/context-management-comparison.md` (Cursor, Copilot, Windsurf all use on-demand retrieval)

**Related proposals:**
- `docs/proposals/PROPOSAL-pluggable-context-strategy.md` (2026-06-26 — pluggable architecture, SHIPPED)
- `docs/proposals/PROPOSAL-context-management-roadmap.md` (2026-06-25 — P1–P7 compaction, SHIPPED)
- `docs/2026-06-27-CM-INDUSTRY-COMPARISON.md` (industry comparison — Dynamic Context Discovery row)

**Architecture alignment:** This proposal modifies components documented in ARCHITECTURE.md §3.21p (`agent/context.py`), §3.21n (`agent/tools.py`), and §4.4b (System Prompt Budget). All changes respect the layering rules in §2: `agent/` has no UI dependencies, `models/` has no UI dependencies, no `subprocess` in any changed file.

---

## 1. Executive Summary

Crabcakes currently loads project file context **upfront** into the system prompt via `build_file_context_with_core_files()` in `agent/context.py`. This function dumps up to 50,000 characters (~12,500 tokens) of directory tree, key files, and core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) into every single LLM call — regardless of whether the user's question has anything to do with those files.

This is the **opposite** of what every leading competitor does:

- **Cursor** builds a codebase index and lets the agent call tools to look up specific symbols on demand
- **GitHub Copilot** is repo-aware and fetches only relevant snippets
- **Windsurf** uses M-Query similarity retrieval over a full codebase index
- **Claude Code** uses JIT file reading (the pattern Anthropic explicitly recommends in their context engineering guide)

The production consensus from Anthropic, LangChain, and Letta in 2026 is clear: **just-in-time retrieval** beats upfront preloading. LangChain's benchmarks show ~30% token reduction with negligible quality loss when using Select (on-demand retrieval) for stable, large contexts.

**This proposal recommends** replacing the upfront 50K preload with a compact **file index** (~2K chars) plus two new built-in tools (`file_search` and `file_read_path`) that let the agent pull in file contents on demand. The mode is configurable: preload (current behavior, default for short sessions), JIT (new, default for long sessions), or hybrid (preload core files + JIT everything else).

The change touches three files (`agent/context.py`, `agent/tools.py`, `utils/prompt_loader.py`), adds no new dependencies, and is fully backward-compatible.

---

## 2. Problem Statement

### 2.1 The Upfront Preload Problem

**Current behavior** (`agent/context.py:357–400`):

```python
def build_file_context_with_core_files(
    project_path: str,
    query: str | None = None,
    max_chars: int = 50_000,
) -> str:
    base_context = build_file_context(project_path, query=query, max_chars=max_chars)
    # ... appends README.md, AGENTS.md, CONVENTIONS.md, ARCHITECTURE.md
```

This function is called from `utils/prompt_loader.py:331–335` inside `compose_system_prompt()`:

```python
file_context_with_core = build_file_context_with_core_files(project_path)
if file_context_with_core:
    result, _unused_file_context = _apply_system_prompt_budget(
        result, file_context_with_core, model_max_tokens
    )
```

The resulting file context is injected into the **system prompt** — meaning it's sent on every single LLM call for the entire conversation. The system prompt budget (§4.4b) caps this at 15–25% of the model's context window, but within that budget, file context competes with templates (bug journals, rules, awareness) for space.

**Concrete numbers for a typical session:**

| Metric | Value |
|---|---|
| `max_chars` for file context | 50,000 |
| Approximate tokens consumed | ~12,500 |
| Typical 128K context window | 12,500 / 128,000 = **9.8%** |
| Typical conversation (20 turns × 2K tokens/turn) | 40,000 tokens |
| File context as % of total context at turn 20 | 12,500 / 52,500 = **23.8%** |
| File context as % of total context at turn 50 | 12,500 / 112,500 = **11.1%** |

That's 12,500 tokens spent on every LLM call to include file contents the agent may never need. For a 50-turn session, that's **625,000 wasted tokens** (12,500 × 50 turns) — most of which are identical across turns because files don't change between calls.

**Where this hurts most:**
- **Short questions on long sessions** — "what does function X do?" doesn't need 50K of file context; it needs one file
- **Non-code questions** — "summarize what we've done" doesn't need any file context at all
- **Context pressure** — the 12,500 tokens of file context eat into the space available for conversation history, accelerating compaction
- **Cost** — on metered APIs, every token costs money. 625K wasted tokens at GPT-4o rates (~$2.50/M input) = ~$1.56 wasted per long session

### 2.2 What the Industry Does Instead

| Platform | Approach | When File Content Enters Context |
|---|---|---|
| **Cursor** | Codebase index + tool lookup | Only when the agent calls a search/read tool |
| **GitHub Copilot** | Repo-aware snippet fetch | Only relevant snippets, fetched per-query |
| **Windsurf** | M-Query similarity retrieval | Only matching chunks from indexed codebase |
| **Claude Code** | JIT file reading | Agent reads files via tool calls as needed |
| **Crabcakes (today)** | Upfront 50K preload | **Every turn, regardless of need** |

### 2.3 What Already Exists in Crabcakes

Crabcakes already has the tools that JIT needs — they're just not used for context discovery:

- `read_file` (`agent/tools.py:220`) — reads file content by path, supports offset/limit
- `list_files` (`agent/tools.py:463`) — lists directory contents, supports recursive
- `search_files` (`agent/tools.py:890`) — grep across project files, supports regex + file type filter
- `_find_matching_files` (`agent/context.py:424`) — internal function that finds files by name match
- `_build_directory_tree` (`agent/context.py:104`) — builds a tree listing (max 200 lines)

These tools already exist and already work. The problem is that the system prompt **also** dumps 50K of file content on top of having these tools. The agent has both the full buffet and the à la carte menu — it's paying for both but only using one.

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. **Replace the 50K upfront preload with a compact file index** (~2K chars) that lists file paths, sizes, and one-line summaries, so the agent knows what exists without reading it all.
2. **Add a `file_search` tool** that lets the agent find files by name or symbol match, returning a preview (first ~500 chars per file) rather than full contents.
3. **Keep core files in the system prompt** (README, AGENTS, CONVENTIONS, ARCHITECTURE) — these are small, critical, and always relevant. They stay in preload mode.
4. **Make the mode configurable**: `preload` (current behavior), `jit` (file index only), `hybrid` (core files + JIT everything else — the default).
5. **Auto-escalate from preload to JIT** when the conversation is long (e.g., turn > 10 or token estimate > 50% of window), so short sessions get the convenience of preloaded context and long sessions get the token savings.
6. **Preserve all existing invariants**: system prompt budget (§4.4b), core file preservation (CB-5), CB-6 tool-call pairing, token cache invalidation, backward compatibility with all existing call sites.

### 3.2 Non-Goals

- **Semantic search / embeddings / codebase indexing** — Windsurf and Cursor use vector indexes for symbol-level similarity search. That's a separate epic requiring tree-sitter or embedding infrastructure. This proposal is about filename + grep-based retrieval, which gets 80% of the benefit at 10% of the complexity.
- **Changing the compaction strategy** — JIT context discovery is orthogonal to context compaction. Compaction manages what's in the conversation; JIT manages what's in the system prompt. They work together but are independently configurable.
- **Changing the system prompt template system** — Templates (from `prompts/system/`) are unchanged. Only the file-context section at the end of the system prompt is affected.
- **MCP integration** — MCP servers may provide their own file-like tools. This proposal doesn't touch MCP; the new `file_search` tool is a built-in crabcakes tool, not an MCP tool.
- **Removing existing tools** — `read_file`, `list_files`, and `search_files` remain unchanged. `file_search` is a new addition, not a replacement.

---

## 4. Architecture Alignment

All changes respect ARCHITECTURE.md layering and module rules:

| Component | File | ARCHITECTURE.md Section | Change Type |
|---|---|---|---|
| File index builder | `agent/context.py` | §3.21p | New function `build_file_index()` |
| Mode flag on context builder | `agent/context.py` | §3.21p | New `context_mode` parameter on `build_file_context_with_core_files()` |
| New `file_search` tool | `agent/tools.py` | §3.21n | New tool registration in `_register_all()` |
| Mode selection in prompt composition | `utils/prompt_loader.py` | §4.4b | New `context_mode` parameter on `compose_system_prompt()` |
| Mode propagation from runtime | `agent/runtime.py` | §3.21m | Pass `context_mode` through to `build_system_prompt()` |
| Provider-level config | `models/providers.py` | §3.21d | New `context_mode: str = "hybrid"` field on `ProviderConfig` |

**Layering compliance:**
- `agent/context.py`: New pure function. No new imports. ✓
- `agent/tools.py`: New tool registration. No new imports. ✓
- `utils/prompt_loader.py`: New parameter. No new imports. ✓
- `agent/runtime.py`: Pass-through parameter. No new imports. ✓
- `models/providers.py`: New dataclass field. No new imports. ✓
- No `ui/` imports in any changed file. ✓
- No `gateway/` imports in any changed file. ✓
- No `subprocess` in any changed file. ✓

**Existing invariants preserved:**
- System prompt budget (§4.4b): `_apply_system_prompt_budget()` still caps the total. In JIT mode, the file index is ~2K chars — well within budget. In hybrid mode, core files + index is ~5–8K chars — still within budget. ✓
- Core file preservation (CB-5): In hybrid mode, core files are still preloaded. In JIT mode, the index explicitly lists core files and the agent is instructed to read them first. ✓
- CB-6 tool-call pairing: Unaffected — this proposal doesn't touch conversation messages or compaction. ✓
- Token cache invalidation: The system prompt is cached per `(len(messages), hash(system_prompt))`. When the mode changes, the prompt hash changes, invalidating the cache naturally. ✓

---

## 5. Design

### 5.1 Three Modes

| Mode | What's in the system prompt | When to use | Token cost |
|---|---|---|---|
| **`preload`** (current default) | Full 50K file context + core files | Short sessions, small projects, first-time exploration | ~12,500 tokens |
| **`jit`** | File index only (~2K) | Long sessions, large projects, context pressure | ~500 tokens |
| **`hybrid`** (new default) | Core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) + file index (~2K) | Most sessions — best balance | ~3,000–5,000 tokens |

### 5.2 The File Index Format

Instead of file contents, the system prompt gets a compact index:

```
## File index (142 files, ~7.6M total)

### Python (47 files)
agent/runtime.py ............. 2,847 lines / 89KB
agent/context.py ............. 485 lines / 15KB
agent/tools.py ............... 950 lines / 28KB
agent/context_strategy.py .... 340 lines / 11KB
models/conversation.py ....... 280 lines / 9KB
models/providers.py .......... 80 lines / 3KB
...

### Markdown (23 files)
docs/ARCHITECTURE.md ......... 1,700 lines / 68KB
README.md .................... 120 lines / 4KB
AGENTS.md .................... 45 lines / 2KB
...

### Config (8 files)
pyproject.toml ............... 60 lines / 2KB
...

[Use file_search("symbol") to find files by name or content.]
[Use read_file("path") to read a specific file's contents.]
```

This gives the agent:
- **Awareness** of what files exist (so it knows what to look for)
- **Size context** (so it knows which files are big and should be read with offset/limit)
- **Tool guidance** (explicit instructions to use `file_search` and `read_file`)

Total cost: ~500–2,000 tokens depending on project size. That's a **6–25× reduction** from the current 12,500-token preload.

### 5.3 The `file_search` Tool

A new tool that combines filename matching with content grep — purpose-built for context discovery:

```python
file_search(query="ContextStrategy", file_type="py")
→ Returns: agent/context_strategy.py (340 lines, 11KB)
   Line 72: class ContextStrategy(Protocol):
   Line 97: class DefaultContextStrategy:
   Line 121:     def compact(self, conv: Conversation, token_budget: int) -> None:
   Line 286:     def prune_tool_outputs(self, ...
   [Use read_file("agent/context_strategy.py") for full content]
```

**Why a new tool instead of reusing `search_files`?** `search_files` returns raw grep output (every matching line, no file-level grouping, no preview). `file_search` is designed for discovery: it groups by file, shows file metadata (size, line count), returns a short preview per file, and explicitly tells the agent to use `read_file` for full content. It bridges the gap between "I know something exists" and "give me the whole file."

**Parameters:**
- `query` (required) — text pattern or filename fragment
- `file_type` (optional) — filter by extension (`.py`, `.md`, etc.)
- `max_results` (optional, default 20) — cap number of files returned
- `preview_lines` (optional, default 5) — lines of context per match

### 5.4 Auto-Escalation

In `hybrid` mode (the default), the context builder automatically escalates based on conversation state:

```python
def resolve_context_mode(
    explicit_mode: str | None,      # from provider config
    turn_count: int,                 # current turn number
    token_estimate: int,             # current token usage
    model_max_tokens: int,           # model context window
) -> str:
    """Resolve the effective context mode based on session state."""
    if explicit_mode and explicit_mode != "auto":
        return explicit_mode

    # Auto-escalate: start with hybrid, switch to jit when pressure rises
    pressure = token_estimate / model_max_tokens
    if turn_count <= 5 and pressure < 0.30:
        return "preload"   # short session, low pressure — convenience wins
    elif pressure > 0.50 or turn_count > 15:
        return "jit"       # long session or high pressure — token savings win
    else:
        return "hybrid"    # middle ground
```

This means:
- **Turns 1–5** of a fresh session: full preload (the agent can answer immediately without tool calls)
- **Turns 6–15** or moderate pressure: hybrid mode (core files + index)
- **Turn 16+** or high pressure: JIT mode (index only, agent reads files on demand)

Auto-escalation is the default (`context_mode = "auto"` in config). Users can pin to any specific mode if they prefer.

### 5.5 What Core Files Stay Preloaded

In `hybrid` and `preload` modes, these files are always in the system prompt (unchanged from CB-5):

- `README.md` — project overview
- `AGENTS.md` — project-specific agent instructions
- `CONVENTIONS.md` — coding conventions
- `ARCHITECTURE.md` — architecture documentation

In `jit` mode, core files are listed in the index with a `[CORE — read first]` marker and the system prompt instructs the agent to read them via `read_file` at the start of a task. This is a trade-off: one extra tool call per core file, but 12K+ tokens saved.

### 5.6 Configuration

New field on `ProviderConfig` (`models/providers.py`):

```python
@dataclass
class ProviderConfig:
    # ... existing fields ...
    context_mode: str = "auto"  # "preload" | "jit" | "hybrid" | "auto"
```

- `auto` (default) — auto-escalate based on session state (§5.4)
- `preload` — always preload full 50K context (current behavior, backward-compatible)
- `hybrid` — always use core files + index
- `jit` — always use index only

Per-provider because users with 1M-context models (MiniMax-M3) may prefer `preload` (plenty of room), while users on 128K models may prefer `jit` (every token counts).

---

## 6. Implementation Plan

### Phase 1: File Index Builder (`agent/context.py`)

**New functions:**

```python
def build_file_index(
    project_path: str,
    max_entries: int = 200,
    include_line_counts: bool = True,
) -> str:
    """Build a compact file index for the system prompt.

    Groups files by extension, shows path + size + line count.
    Respects .gitignore.
    """
```

**Modify:** `build_file_context_with_core_files()` to accept `context_mode: str = "preload"` parameter. When mode is `"jit"`, return the file index instead of full contents. When mode is `"hybrid"`, return core files + file index.

**Tests:**
- `test_build_file_index_returns_compact_listing` — verify output is under 3K chars for a typical project
- `test_build_file_index_respects_gitignore` — verify excluded dirs don't appear
- `test_build_file_index_groups_by_extension` — verify grouping
- `test_build_file_context_hybrid_mode` — verify core files + index
- `test_build_file_context_jit_mode` — verify index only, no file contents
- `test_build_file_context_preload_mode_backward_compat` — verify existing behavior unchanged when mode="preload"

### Phase 2: `file_search` Tool (`agent/tools.py`)

**New tool registration:**

```python
_TOOLS["file_search"] = (
    ToolDefinition(
        name="file_search",
        description=(
            "Find files by name or content pattern. Returns grouped results\n"
            "with file metadata and preview lines.\n\n"
            "WHEN TO USE: Discovering which files contain a function, class,\n"
            "or concept before reading them. Replaces browsing the file index.\n\n"
            "BEHAVIOR: Groups matches by file. Shows line count + size per file.\n"
            "Returns up to 5 preview lines per match.\n"
            "Use read_file() to get full contents after finding the right file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Filename fragment or text/regex pattern"},
                "file_type": {"type": "string", "description": "Filter by extension (e.g. 'py', 'md')"},
                "max_results": {"type": "integer", "description": "Max files to return (default 20)"},
            },
            "required": ["query"],
        },
        requires_approval=False,
    ),
    lambda query, project_path, file_type=None, max_results=None, **kwargs:
        _file_search(query, project_path, file_type, max_results),
)
```

**New function:** `_file_search()` — combines `_find_matching_files()` (filename match) with `grep` (content match), groups results by file, returns preview lines.

**Tests:**
- `test_file_search_finds_by_filename` — query matching a filename returns that file
- `test_file_search_finds_by_content` — query matching content returns the file with preview lines
- `test_file_search_groups_by_file` — multiple matches in same file are grouped
- `test_file_search_respects_max_results` — cap on number of files returned
- `test_file_search_file_type_filter` — filter by extension works

### Phase 3: Prompt Loader Integration (`utils/prompt_loader.py`)

**Modify:** `compose_system_prompt()` to accept `context_mode: str = "preload"` parameter. Pass it through to `build_file_context_with_core_files()`.

**Modify:** `_apply_system_prompt_budget()` to handle the case where file context is a small index (~2K) rather than full content (~50K). The budget logic is simpler: the index almost always fits, so truncation is rare.

**Tests:**
- `test_compose_prompt_jit_mode_produces_smaller_prompt` — JIT prompt < preload prompt
- `test_compose_prompt_hybrid_mode_includes_core_files` — core files present in hybrid mode
- `test_compose_prompt_budget_not_exceeded_in_jit` — total prompt within 15–25% budget

### Phase 4: Runtime Wiring + Auto-Escalation (`agent/runtime.py`)

**Modify:** `create_conversation()` to read `context_mode` from the provider config and pass it to `build_system_prompt()`.

**New function:** `_resolve_context_mode()` on `AgentRuntime` — implements the auto-escalation logic from §5.4. Called at the start of each tool-loop iteration to potentially switch modes mid-session.

**Modify:** The tool loop to check if the mode should escalate before each LLM call. When escalating from `preload` → `hybrid` or `jit`, the system prompt is rebuilt (this is the one cost of escalation — one extra prompt rebuild per mode change).

**Tests:**
- `test_resolve_context_mode_short_session_preload` — turn ≤5, low pressure → preload
- `test_resolve_context_mode_long_session_jit` — turn >15 or high pressure → jit
- `test_resolve_context_mode_explicit_override` — explicit mode not overridden by auto
- `test_runtime_passes_context_mode_to_prompt` — verify wiring

### Phase 5: Provider Config (`models/providers.py`)

**Add field:** `context_mode: str = "auto"` to `ProviderConfig`.

**Tests:**
- `test_provider_config_defaults` — verify default is "auto"
- `test_provider_config_accepts_valid_modes` — all four modes
- `test_provider_config_rejects_invalid_mode` — validation

---

## 7. Risks and Mitigations

### 7.1 Latency Increase (Medium Risk)

**Risk:** JIT mode adds tool-call round-trips. If the agent needs to read 3 files to answer a question, that's 3 extra LLM calls (tool-call → response → tool-call → response → tool-call → response → final answer) vs 0 in preload mode.

**Mitigation:**
- Auto-escalation means short sessions (turns 1–5) stay in preload mode — zero latency impact for the most common case
- The file index gives the agent enough information to read files in parallel (multiple `read_file` calls in one assistant message), minimizing round-trips
- The token savings from JIT reduce per-call cost and latency (smaller prompt = faster inference)

**Measurement:** Add a `context_mode` field to `CompactionEvent` telemetry so we can correlate mode with turn latency and token usage in production.

### 7.2 Agent Quality Degradation (Low Risk)

**Risk:** If the agent doesn't know to use `file_search`/`read_file`, it may hallucinate or fail to find relevant files.

**Mitigation:**
- The file index includes explicit tool-use instructions: `[Use file_search("symbol") to find files. Use read_file("path") to read contents.]`
- The system prompt template can include a "Context Mode" awareness section explaining the current mode and available tools
- Core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) stay in preload in hybrid mode — the agent always has project-level context
- The `default.md` system prompt template already instructs the agent to use `read_file` before modifying files — this is reinforced, not changed

**Measurement:** Add a test suite that runs canonical agent tasks (implement a function, fix a bug, explain a module) in all three modes and compares success rate.

### 7.3 Backward Compatibility (Low Risk)

**Risk:** Existing call sites that don't pass `context_mode` get unexpected behavior changes.

**Mitigation:**
- Default is `context_mode = "preload"` on all existing functions — zero behavior change for code that doesn't opt in
- Default is `context_mode = "auto"` only on `ProviderConfig` — but auto starts in preload for short sessions, so the first few turns are identical to current behavior
- All existing tests pass unchanged (they don't set `context_mode`, so they get the default)

### 7.4 Cache Invalidation (Low Risk)

**Risk:** Switching modes mid-session changes the system prompt, invalidating the token estimate cache (`_token_estimate_cache` on `Conversation`).

**Mitigation:**
- The cache is keyed on `(len(messages), hash(system_prompt))` — when the prompt changes, the hash changes, and the cache is naturally invalidated. This is already how the system works when any prompt template changes.
- Mode escalation happens at most 2 times per session (preload → hybrid → jit), not per-turn, so the cache miss cost is negligible.

### 7.5 Large Project Index Size (Low Risk)

**Risk:** A very large project (10,000+ files) could produce a file index larger than the current 50K preload.

**Mitigation:**
- `max_entries = 200` cap on the index. Projects with more files get a truncated index with `[... and 8,000 more files. Use file_search to find specific files.]`
- The index groups by extension and sorts by size (largest first), so the most important files are always listed
- `_apply_system_prompt_budget()` still caps the total system prompt at 15–25% of the context window — if the index is too big, it's truncated like any other file context

---

## 8. Trade-off Analysis

| Dimension | Preload (current) | JIT | Hybrid (proposed default) |
|---|---|---|---|
| **Tokens per turn** | ~12,500 | ~500 | ~3,000–5,000 |
| **Tool-call latency** | None (0 extra calls) | 1–3 extra calls per question | 0–2 extra calls |
| **Agent "knows" project** | Everything upfront | Must discover via tools | Core knowledge upfront, rest on demand |
| **Best for** | Short sessions, small projects | Long sessions, large projects | Most real-world usage |
| **Complexity** | Lowest (current) | Medium (new tool + index) | Medium (same as JIT) |

**The hybrid default is the sweet spot:** core files give the agent project-level awareness (what is this project, how does it work, what are the rules), while the file index gives it awareness of what exists (what files are there, how big are they) without paying for their full content until needed.

---

## 9. Token Savings Estimate

For a typical 30-turn coding session on a 128K-context model:

| Mode | System prompt tokens | × 30 turns | Total prompt tokens | vs. Preload |
|---|---|---|---|---|
| **Preload** | ~12,500 | × 30 | 375,000 | baseline |
| **Hybrid** (turns 1–5 preload, 6–15 hybrid, 16–30 jit) | ~12,500 → ~4,000 → ~500 | mixed | ~133,000 | **−64.5%** |
| **JIT** (all turns) | ~500 | × 30 | 15,000 | **−96.0%** |

At GPT-4o input rates (~$2.50/M tokens):
- Preload: ~$0.94 in system-prompt tokens
- Hybrid: ~$0.33 — **$0.61 saved per session**
- JIT: ~$0.04 — **$0.90 saved per session**

For a team running 100 agent sessions/day, hybrid mode saves ~$61/day or ~$1,830/month in input token costs alone. Output tokens are also smaller (smaller prompt = less to process).

---

## 10. Evidence from Research

| Source | Finding | Relevance |
|---|---|---|
| **LangChain** (Write/Select/Compress/Isolate framework, 2026) | ~30% token reduction with negligible quality loss using Select for stable, large contexts | Directly supports JIT |
| **Anthropic** (Context Engineering guide, 2026) | Recommends just-in-time retrieval over upfront loading; Claude Code uses JIT pattern to handle entire codebases | Industry consensus |
| **Cursor** (Composer 2, 2026) | Builds codebase index; agent calls tools to look up symbols on demand | Production proof of JIT at scale |
| **Windsurf** (Cascade, 2026) | M-Query similarity retrieval over indexed codebase | Production proof of on-demand retrieval |
| **Letta** (MemFS, 2026) | File-system-based memory with selective retrieval | Academic proof of JIT in agentic memory |
| **LlamaIndex** (MemoryBlocks, 2026) | `FactExtractionMemoryBlock` extracts and retrieves structured facts on demand | Production proof of selective context injection |

Full citations in `docs/research/context-management-survey-2026.md`.

---

## 11. Relationship to the Pluggable Context Strategy Architecture

This proposal is **orthogonal** to the `ContextStrategy` protocol (`docs/proposals/PROPOSAL-pluggable-context-strategy.md`). They address different problems:

| Concern | Layer | What it controls |
|---|---|---|
| **Context Compaction** (`ContextStrategy`) | Conversation `messages[]` | How to shrink the conversation when it exceeds the token budget (stub → trim → summarize) |
| **Context Discovery** (this proposal) | System prompt `file_context` | What project information to inject into the system prompt (all files → index → on-demand) |

A future implementation could combine both: a `JITAwareCompactionStrategy` that adjusts compaction thresholds based on whether the system prompt is in JIT mode (lower threshold acceptable because the prompt is smaller). But that's a future enhancement, not part of this proposal.

The key insight: **the pluggable architecture makes this combination possible**. Because `ContextStrategy` is decoupled from the runtime, a future strategy can be aware of the context mode without runtime changes. This is exactly the future-proofing benefit described in the pluggable architecture proposal.

---

## 12. Acceptance Criteria

This proposal is complete when:

1. **`build_file_index()` exists** in `agent/context.py` and returns a compact file listing under 3K chars for a typical project
2. **`file_search` tool is registered** in `agent/tools.py` and returns grouped, previewed results
3. **`context_mode` parameter** is accepted by `build_file_context_with_core_files()`, `compose_system_prompt()`, `build_system_prompt()`, and `create_conversation()`
4. **`context_mode` field** exists on `ProviderConfig` with default `"auto"`
5. **Auto-escalation logic** switches mode based on turn count and token pressure
6. **All existing tests pass** without modification (backward compatibility)
7. **New test suite covers** file index building, file_search tool, mode selection, hybrid mode, JIT mode, auto-escalation, and budget compliance
8. **System prompt in JIT mode** is demonstrably smaller than preload mode for the same project (measured, not assumed)
9. **Documentation updated**: ARCHITECTURE.md §3.21p and §4.4b reflect the new `context_mode` parameter
10. **Comparison doc updated**: `docs/2026-06-27-CM-INDUSTRY-COMPARISON.md` Dynamic Context Discovery row changes from ❌ to ✅

---

## 13. Open Questions

These are design decisions for the implementation phase, not blockers for the proposal:

1. **Should the file index include import graphs?** Showing `agent/runtime.py imports: agent.context, agent.tools, models.conversation` would help the agent navigate faster. Adds ~50 tokens to the index. Decision: nice-to-have, not required for v1.

2. **Should `file_search` support fuzzy matching?** E.g., searching "context strategy" finds `context_strategy.py` even without exact match. Decision: v1 uses exact substring + regex (consistent with `search_files`). Fuzzy is a future enhancement.

3. **Should the mode be per-agent or per-provider?** Currently proposed as per-provider (on `ProviderConfig`). A debugger agent might want JIT while a coder agent wants preload, even on the same provider. Decision: add to `AgentConfig` too in a future iteration. For v1, per-provider is sufficient.

4. **Should mode changes be logged as telemetry events?** Logging mode escalation as a new event type would help analyze usage patterns. Decision: add to `CompactionEvent` telemetry as a `context_mode` field. Or create a new `ContextModeChangeEvent`. Decision for implementation phase.

---

## 14. Delivery Phases

This proposal is delivered through the standard implementation loop (spec → phase instructions → builder → adversarial audit → commit):

| Phase | Scope | Estimated Effort |
|---|---|---|
| **P10.1** | File index builder + tests (`agent/context.py`) | 2–3 hours |
| **P10.2** | `file_search` tool + tests (`agent/tools.py`) | 2–3 hours |
| **P10.3** | Prompt loader integration + budget compliance tests (`utils/prompt_loader.py`) | 1–2 hours |
| **P10.4** | Runtime wiring + auto-escalation logic + tests (`agent/runtime.py`) | 2–3 hours |
| **P10.5** | Provider config field + tests (`models/providers.py`) | 30 minutes |
| **P10.6** | Documentation updates (ARCHITECTURE.md, comparison doc) | 1 hour |
| **P10.7** | Adversarial audit: test all three modes on canonical tasks, verify token savings | 2–3 hours |
| **Total** | | **10–16 hours** |

---

## 15. Alternatives Considered

### 15.1 Embeddings-Based Semantic Search (Rejected for Now)

**What:** Build a vector index of the codebase using embeddings (e.g., `sentence-transformers` + FAISS). The agent queries with natural language and gets the most semantically similar code chunks.

**Why rejected:**
- Requires new infrastructure (embedding model, vector store, indexing pipeline)
- Adds a heavy dependency (~500MB for `sentence-transformers`)
- Index must be rebuilt when files change (complex invalidation logic)
- Marginal benefit over grep + filename matching for most agent tasks
- This is what Cursor and Windsurf do — but they have dedicated indexing infrastructure and teams

**When to revisit:** When crabcakes adds tree-sitter or MCP symbol-graph support. At that point, semantic search becomes a natural extension of the symbol graph rather than a standalone system.

### 15.2 Always-Hybrid (No Mode Switching)

**What:** Always use hybrid mode (core files + index). No preload, no JIT, no auto-escalation.

**Why rejected:**
- Removes user choice — some projects are small enough that full preload is fine
- Removes auto-escalation benefit — short sessions lose the convenience of full context
- Simpler, but less flexible. The mode system isn't complex enough to justify removing it.

### 15.3 Remove File Context Entirely (Agent Must Always Discover)

**What:** No file context in the system prompt at all. The agent starts with zero project knowledge and must discover everything via tools.

**Why rejected:**
- Too aggressive — the agent doesn't even know what project it's in without reading files first
- First-turn latency would be terrible (4–5 tool calls just to orient)
- No competitor does this — even Cursor preloads some project metadata
- Core files (README, AGENTS, ARCHITECTURE) are designed to be read once and kept in context

---

## Related Documents

- `docs/research/crabcakes-future-context-strategies.md` §T1.4 — original research for this proposal
- `docs/research/context-management-survey-2026.md` — LangChain Write/Select/Compress/Isolate framework
- `docs/research/context-management-comparison.md` — competitor analysis (Cursor, Copilot, Windsurf)
- `docs/2026-06-27-CM-INDUSTRY-COMPARISON.md` — industry comparison (Dynamic Context Discovery row)
- `docs/proposals/PROPOSAL-pluggable-context-strategy.md` — pluggable architecture (SHIPPED)
- `docs/proposals/PROPOSAL-context-management-roadmap.md` — P1–P7 compaction (SHIPPED)
- `docs/ARCHITECTURE.md` §3.21p, §3.21n, §4.4b — architecture reference
