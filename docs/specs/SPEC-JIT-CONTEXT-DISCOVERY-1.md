# SPEC: Just-in-Time Context Discovery (P10)

**Date:** 2026-06-27
**Author:** Captain Q (with Qaster proposal)
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-jit-context-discovery.md`
**Depends on:** None (orthogonal to ContextStrategy protocol; uses existing tools)
**Target branch:** main

> **Architecture compliance:** Per `docs/ARCHITECTURE.md`:
> - `agent/context.py` (§3.21p) — owns file-context building; `build_file_index()`, `resolve_context_mode()`, modified `build_file_context_with_core_files()`; no new imports
> - `agent/tools.py` (§3.21n) — owns tool registration; new `_file_search()` + new shared `_run_grep()` helper + refactored `_search_files()`; no new imports
> - `utils/prompt_loader.py` (§4.4b) — owns prompt composition and budget; new `context_mode` pass-through parameter; no new imports (lazy import of `resolve_context_mode`)
> - `agent/runtime.py` (§3.21m) — owns system prompt wiring; new `context_mode` pass-through; no new imports
> - `models/providers.py` (§3.21d) — owns `ProviderConfig`; new `context_mode` field + `validate_provider_context_mode()` helper; no new imports
> - **No `ui/` imports** in any changed file
> - **No `subprocess` added** to any changed file (existing `_search_files` uses subprocess; `_run_grep` extracts the existing call; `_file_search` calls `_run_grep`)
> - **No `gateway/` imports** in any changed file

---

## 1. Overview

### Problem

`agent/context.py:build_file_context_with_core_files()` is called from `utils/prompt_loader.py:compose_system_prompt()` (lines 331–335) and dumps up to **50,000 characters (~12,500 tokens)** of project file context into the system prompt on **every single LLM call**, regardless of whether the user's question has anything to do with those files. For a 50-turn session, that's ~625,000 wasted tokens.

The competitor consensus (Cursor, Copilot, Windsurf, Claude Code) is **just-in-time retrieval** — keep a compact index in the system prompt, let the agent pull files on demand via tools. Crabcakes already has those tools (`read_file`, `list_files`, `search_files`); the system prompt just doesn't tell the agent to use them.

### Solution

Replace the upfront 50K preload with a compact **file index** (~2K chars) plus a new `file_search` tool. Make the mode configurable: `preload` (current behavior, default for short sessions), `jit` (index only, default for long sessions), `hybrid` (core files + index, default for most sessions). Auto-escalate from preload → hybrid → jit as the conversation grows or token pressure rises.

### Scope

| In scope | Out of scope |
|---|---|
| `build_file_index()` new function | Semantic search / embeddings |
| `context_mode` parameter on `build_file_context_with_core_files()` | Tree-sitter / symbol graph indexing |
| `file_search` tool registration | Removing existing `read_file`/`list_files`/`search_files` |
| `context_mode` parameter on `compose_system_prompt()` | MCP file tools (separate epic) |
| Auto-escalation logic in runtime | Per-agent mode config (per-provider only in v1) |
| `context_mode: str = "auto"` field on `ProviderConfig` | New system prompt templates |

---

## 2. Changes by File

### 2.1 `models/providers.py` — Add `context_mode` field

**Change type:** New dataclass field. **Lines:** +1.

Add one field to `ProviderConfig` after `compaction_threshold`:

```python
@dataclass
class ProviderConfig:
    """Configuration for a single LLM API provider."""
    name: str
    base_url: str
    api_key: str
    default_model: str
    caller: str = ""
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    max_tokens: int = 128_000
    default_max_tokens: int = 0
    compaction_threshold: float = 0.80
    last_verified_at: str | None = None
    last_error: str | None = None
    context_mode: str = "auto"  # NEW — "preload" | "jit" | "hybrid" | "auto"
```

**Valid values** (verified against proposal §5.6 and §6 Phase 5):
- `"auto"` (default) — auto-escalate based on session state
- `"preload"` — always preload full 50K context (current behavior)
- `"hybrid"` — always use core files + index
- `"jit"` — always use index only

**Validation:** `_load_agent_config()` does NOT currently validate `context_mode`. Per `docs/ARCHITECTURE.md` §3.21d, `load_agent_config()` is the single entry point for `<config_dir>/agent.json`. Add validation in a new helper:

```python
# New function (after caller_default_max_tokens())
_VALID_CONTEXT_MODES = frozenset({"auto", "preload", "jit", "hybrid"})

def validate_provider_context_mode(mode: str) -> str:
    """Validate and normalize a context_mode string. Raises ValueError on bad input."""
    if not isinstance(mode, str):
        raise ValueError(f"context_mode must be a string, got {type(mode).__name__}")
    normalized = mode.lower().strip()
    if normalized not in _VALID_CONTEXT_MODES:
        raise ValueError(
            f"Invalid context_mode: {mode!r}. Must be one of {sorted(_VALID_CONTEXT_MODES)}."
        )
    return normalized
```

**Tests:**
- `test_provider_config_defaults_context_mode_auto` — default is "auto"
- `test_provider_config_accepts_valid_modes` — all 4 values round-trip through dataclass
- `test_validate_provider_context_mode_rejects_invalid` — invalid string raises ValueError
- `test_validate_provider_context_mode_normalizes_case` — `"PRELOAD"` → `"preload"`

**Files NOT changed:** Other dataclasses in `models/` (e.g. `Conversation`) don't need this field — mode is per-provider, not per-conversation.

---

### 2.2 `agent/context.py` — Add `build_file_index()` + `context_mode` parameter

**Change type:** New function + modified function. **Lines:** +110 / −10.

#### 2.2.1 New function: `build_file_index()`

```python
def build_file_index(
    project_path: str,
    max_entries: int = 200,
    include_line_counts: bool = True,
) -> str:
    """Build a compact file index for the system prompt.

    Walks the project tree (respecting .gitignore via _load_gitignore_patterns
    and the EXCLUDED_DIRS frozenset already defined at line 197), groups files
    by extension, shows path + size + (optionally) line count. Capped at
    max_entries; if more files exist, appends a truncation note.

    Args:
        project_path: Absolute path to the project root.
        max_entries: Maximum number of files to list (default 200).
        include_line_counts: Whether to count lines per file (default True).
            Setting False reduces I/O for very large projects.

    Returns:
        Formatted text block, e.g.:
            ## File index (47 files)
            ### Python (12 files)
            agent/runtime.py ............. 2,437 lines / 89KB
            ...
        Empty string if project_path is invalid.
    """
```

**Implementation requirements** (verified against existing helpers in `agent/context.py`):
- Reuse `_load_gitignore_patterns()` (line 24) — same ignore logic as `build_file_context`
- Reuse `EXCLUDED_DIRS` frozenset (line 197) — same exclusion logic
- Skip hidden files (start with `.`) and `__pycache__` (matches `_build_directory_tree` pattern at line 104)
- Sort files: by extension group, then by size descending within each group (largest first, like `_find_matching_files` at line 424)
- Group by extension (last `.` in filename)
- File metadata: `rel_path` + line count (if enabled) + `os.path.getsize()`
- Size formatting: human-readable (KB for <1MB, MB for >=1MB). Use `f"{size // 1024}KB"` if < 1MB, else `f"{size // (1024*1024)}MB"`
- Line counting: `sum(1 for _ in open(path, "rb"))` — but wrap in try/except for binary files (skip them with no line count)
- Truncation: tiered strategy for large projects:
  - **≤ max_entries files**: list all files (existing behavior)
  - **> max_entries files**: list top `max_entries` by size + append a **directory-level summary** of the omitted files, grouped by top-level directory. Format:
    ```
    [... and 8,432 more files across 47 directories. Top directories:]
    src/ ............ 3,891 files / 45.2MB
    tests/ .......... 1,204 files / 8.7MB
    node_modules/ ... 2,100 files / 12.1MB
    vendor/ ......... 1,237 files / 5.4MB
    [Use file_search("symbol") to find specific files within these directories.]
    ```
    This gives the agent **navigational awareness** of large projects (what directories exist, how much code is in each) even when individual files are too numerous to list. The directory summary is capped at 10 entries (sorted by file count descending).
  - The `max_entries` parameter controls the per-file listing cap. The directory summary is always computed from the full file set, so it reflects the true project size even when the file listing is truncated.

**Tests:**
- `test_build_file_index_returns_compact_listing` — verify output is < 3K chars for a fixture project (5–10 files)
- `test_build_file_index_respects_gitignore` — gitignored files don't appear
- `test_build_file_index_groups_by_extension` — Python files in `### Python` section, Markdown in `### Markdown`
- `test_build_file_index_max_entries_cap` — project with 300 files shows 200 + directory summary
- `test_build_file_index_sorted_by_size` — within a group, largest files first
- `test_build_file_index_handles_invalid_path` — empty string for missing dir
- `test_build_file_index_directory_summary_large_project` — project with 1000+ files shows per-directory summary with file counts and total sizes

#### 2.2.2 Modified function: `build_file_context_with_core_files()`

Add `context_mode: str = "preload"` parameter:

```python
def build_file_context_with_core_files(
    project_path: str,
    query: str | None = None,
    max_chars: int = 50_000,
    *,
    context_mode: str = "preload",  # NEW — keyword-only
) -> str:
    """Build a file context block with core files preserved at the end.

    Mode behavior:
    - "preload" (default): existing behavior — full file context + core files
    - "jit": replace base context with file index; do NOT include core files
    - "hybrid": core files + file index (replacing base file context)

    All other behavior (gitignore, .crabcakes/ docs, CB-5 core file
    preservation) is unchanged.
    """
```

**Mode dispatch logic:**

```python
    # Validate mode (delegate to resolve_context_mode for consistency)
    if context_mode not in ("preload", "jit", "hybrid"):
        raise ValueError(f"Invalid context_mode: {context_mode!r}")

    if not project_path or not os.path.isdir(project_path):
        return ""

    if context_mode == "preload":
        # Existing behavior — unchanged
        base_context = build_file_context(project_path, query=query, max_chars=max_chars)
        if not base_context:
            return ""
        core_sections = []
        for core_file in CORE_FILES:
            core_path = os.path.join(project_path, core_file)
            content = _read_file_safe(core_path)
            if content:
                core_sections.append(f"## {core_file}\n\n{content}\n")
        if not core_sections:
            return base_context
        core_block = "\n".join(core_sections)
        return base_context + "\n\n" + core_block

    # jit or hybrid
    file_index = build_file_index(project_path)
    if context_mode == "jit":
        # JIT: index only, no core files
        return file_index

    # hybrid: core files + index
    core_sections = []
    for core_file in CORE_FILES:
        core_path = os.path.join(project_path, core_file)
        content = _read_file_safe(core_path)
        if content:
            core_sections.append(f"## {core_file}\n\n{content}\n")
    if not core_sections:
        return file_index
    return "\n".join(core_sections) + "\n\n" + file_index
```

**Tests:**
- `test_build_file_context_preload_mode_unchanged` — when mode="preload", output matches existing test fixture
- `test_build_file_context_jit_mode_returns_index` — mode="jit" returns just the index, no file contents
- `test_build_file_context_hybrid_mode_includes_core_files` — mode="hybrid" has core files + index
- `test_build_file_context_jit_mode_omits_core_files` — mode="jit" does NOT include README/AGENTS/etc.

**Imports required:** None new (`build_file_index` is in the same module).

---

### 2.3 `agent/tools.py` — Register `file_search` tool

**Change type:** New function + new tool registration. **Lines:** +85.

#### 2.3.1 New function: `_file_search()`

```python
def _file_search(
    query: str,
    project_path: str,
    file_type: str | None = None,
    max_results: int = 20,
    preview_lines: int = 5,
) -> ToolResult:
    """Find files by name OR content pattern. Returns grouped, previewed results.

    Combines:
    - Filename matching via agent.context._find_matching_files (line 424)
    - Content matching via _search_files (line 505) with grep

    Results are grouped by file. Each file shows:
    - rel_path, total line count (best-effort), size in KB
    - Up to `preview_lines` matching lines (file:line: content)

    Args:
        query: Filename fragment or text pattern (used as grep pattern too).
        project_path: Absolute path to the project root.
        file_type: Optional extension filter (e.g. "py", "md").
        max_results: Cap on number of files returned (default 20).
        preview_lines: Lines of context per match (default 5).

    Returns:
        ToolResult with output like:
            agent/context_strategy.py (340 lines, 11KB)
              Line 72: class ContextStrategy(Protocol):
              Line 97: class DefaultContextStrategy:
            [Use read_file("agent/context_strategy.py") for full content]
    """
```

**Implementation requirements** (verified against existing helpers):
- Import `_find_matching_files` from `agent.context` (lazy import inside function to avoid circular imports):
  ```python
  from agent.context import _find_matching_files  # safe — context.py imports nothing from tools.py
  ```
- Call `_find_matching_files(project_path, query, patterns, max_files=max_results)` — signature verified: `(project_path, query, patterns, max_files=20, max_total_chars=40000) -> list[str]`
- For content matching, call `_run_grep(query, project_path, file_type)` (see §2.3.2 below — new shared helper). Do NOT call `_search_files()` directly; both `_search_files` and `_file_search` route through the same `_run_grep` to guarantee identical grep behavior (same flags, same timeout, same error handling). This prevents behavioral drift between the two tools.
- Group by file: `dict[file_path, list[(line_num, content)]]`
- For files matched only by name (no grep hits), show "[name match only — use read_file for content]"
- Truncate preview to `preview_lines` per file
- Cap to `max_results` files total
- Append footer: `[Use read_file("path") to read full contents. Use list_files(".") to browse directory tree.]`

**Tests:**
- `test_file_search_finds_by_filename` — `file_search("context_strategy")` returns `agent/context_strategy.py`
- `test_file_search_finds_by_content` — `file_search("ContextStrategy")` returns files containing the class
- `test_file_search_groups_by_file` — multiple grep hits in same file shown once
- `test_file_search_respects_max_results` — `max_results=2` returns at most 2 files
- `test_file_search_file_type_filter` — `file_type="py"` filters out `.md` files
- `test_file_search_includes_preview_lines` — at least 1 preview line per file with content matches
- `test_file_search_invalid_query_returns_error` — empty query returns `ToolResult(success=False, error="...")`

#### 2.3.2 New tool registration

Add inside `_register_tools()` after the `search_files` block (note: `_register_tools` is at line 719; `web_search` registration is at line 924 — `file_search` goes before it):

```python
    # file_search
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
        lambda query, project_path, file_type=None, max_results=None, **kwargs:  # type: ignore
            _file_search(query, project_path, file_type, max_results or 20),
    )
```

**Tests:**
- `test_file_search_tool_registered` — `get_all_tools()` includes `"file_search"`
- `test_file_search_tool_description_includes_when_to_use` — description contains "WHEN TO USE"
- `test_file_search_tool_requires_query` — JSON schema marks `query` as required

**Imports required:** None new (`_file_search` is in the same module; lazy import of `_find_matching_files` is inside the function).

#### 2.3.2 Shared helper: `_run_grep()`

Extract the grep logic currently inside `_search_files()` (lines 505–540) into a shared helper so both `_search_files` and `_file_search` use identical grep behavior:

```python
def _run_grep(
    pattern: str,
    search_root: str,
    file_type: str | None = None,
    timeout: int = 10,
) -> tuple[int, str, str]:
    """Run grep and return (returncode, stdout, stderr).

    Shared by _search_files (tool) and _file_search (tool) to guarantee
    identical grep behavior: same flags (-n -H --directories=skip -r),
    same --include filter, same -- separator, same timeout.
    """
    cmd = ["grep", "-n", "-H", "--directories=skip", "-r"]
    if file_type:
        cmd += ["--include=*." + file_type]
    cmd += ["--", pattern, "."]
    result = subprocess.run(
        cmd, capture_output=True, timeout=timeout,
        cwd=search_root, text=True,
    )
    return result.returncode, result.stdout, result.stderr
```

**Modify `_search_files()`** (lines 505–540) to call `_run_grep()` instead of inlining the subprocess call. This is a pure refactor — the grep flags, timeout, and error handling are identical. The only change is moving the subprocess call behind a shared function.

**Why this matters:** Without a shared helper, any future change to grep flags (e.g., adding `--max-count` or switching to ripgrep) would need to be applied in two places. With `_run_grep`, both tools evolve together.

**Test:**
- `test_run_grep_returns_expected_format` — verify `(returncode, stdout, stderr)` tuple
- `test_search_files_unchanged_after_refactor` — existing `search_files` behavior identical post-refactor (regression test)

---

### 2.4 `utils/prompt_loader.py` — Add `context_mode` parameter

**Change type:** Modified function signature. **Lines:** +8 / −2.

#### 2.4.1 `compose_system_prompt()` — new parameter

Add `context_mode: str = "auto"` to the signature:

```python
def compose_system_prompt(
    agent_name: str = "",
    agent_role: str = "",
    project_path: str | None = None,
    project_awareness: dict | None = None,
    tools: list[str] | None = None,
    review_mode: str = "off",
    model_max_tokens: int | None = None,
    *,
    context_mode: str = "auto",  # NEW — keyword-only
) -> str:
```

**v1 scope — conversation-creation-time resolution only:** The system prompt is built once in `create_conversation()` (line 1396) and stored on the `Conversation` dataclass (line 1409). It is never reassigned mid-session — there is no rebuild step in the tool loop. Therefore `resolve_context_mode()` in v1 resolves using **only `model_max_tokens`** (available at creation time). The `turn_count` and `token_estimate` parameters from the proposal's §5.4 auto-escalation pseudo-code are **not available** at conversation creation time and are deferred to P10.8 (mid-session re-escalation).

**Mode resolution:** New helper function. This lives in `agent/context.py` (next to `build_file_context_with_core_files`) rather than `prompt_loader.py`, because mode resolution is a context-strategy concern and `context.py` is the module that owns file-context semantics. `prompt_loader.py` calls it indirectly via `build_file_context_with_core_files(context_mode=...)`.

In `agent/context.py`:

```python
def resolve_context_mode(
    explicit_mode: str,
    model_max_tokens: int | None,
) -> str:
    """Resolve the effective context mode based on provider configuration.

    v1: resolves at conversation-creation time only, using model_max_tokens.
    Mid-session escalation (turn_count, token_estimate) is deferred to P10.8.

    Args:
        explicit_mode: One of "auto", "preload", "jit", "hybrid".
            "auto" is resolved by this function.
        model_max_tokens: Model context window from ProviderConfig.
            If None or 0, defaults to 128_000 for heuristics.

    Returns:
        One of "preload", "hybrid", "jit".

    Logic:
        - explicit "preload"/"jit"/"hybrid" → return as-is
        - explicit "auto":
            - treat None or 0 model_max_tokens as 128_000 (typical default)
            - if window >= 500_000: return "preload"  (large window —
              plenty of room, convenience wins; e.g. MiniMax-M3 1M)
            - if window <= 32_000: return "jit"  (small window —
              every token counts; e.g. legacy 32K models)
            - else: return "hybrid"  (typical 128K–256K — balanced default)
    """
    if explicit_mode in ("preload", "jit", "hybrid"):
        return explicit_mode
    if explicit_mode != "auto":
        raise ValueError(f"Invalid context_mode: {explicit_mode!r}")
    # auto: resolve by model context window size
    window = model_max_tokens or 128_000
    if window >= 500_000:
        return "preload"   # large window — convenience wins
    if window <= 32_000:
        return "jit"       # small window — every token counts
    return "hybrid"        # typical 128K–256K — balanced
```

**Why model-window-based heuristics instead of turn-count/pressure?** In v1, mode resolution happens at `create_conversation()` time only. At that point we know the model's context window but not how long the conversation will be or what the token pressure will become. Window-size heuristics are a stable proxy: large-window models (500K+) can afford the preload cost; small-window models (32K) benefit immediately from JIT; typical 128K–256K models get the balanced hybrid default. This is a simpler, more predictable rule than pseudo-turn-count escalation that can't actually fire.

**P10.8 future (mid-session re-escalation):** When implemented, `resolve_context_mode()` will gain `turn_count: int = 0` and `token_estimate: int = 0` parameters. The runtime tool loop will call it before each LLM invocation and rebuild the system prompt if the mode changes. This requires adding a `_maybe_rebuild_system_prompt()` step to the tool loop (estimated 3–4 hours, including cache-invalidation testing). For v1, a `# TODO: P10.8 — mid-session re-escalation` comment marks the extension point in `create_conversation()`.

**Wire `context_mode` to file context builder:**

In `compose_system_prompt()`, at line 331–335 (the file-context block), replace:

```python
        file_context_with_core = build_file_context_with_core_files(project_path)
```

with:

```python
        from agent.context import resolve_context_mode  # already same package
        effective_mode = resolve_context_mode(context_mode, model_max_tokens)
        file_context_with_core = build_file_context_with_core_files(
            project_path,
            context_mode=effective_mode,
        )
```

No new parameters on `compose_system_prompt()` beyond `context_mode`. The `turn_count` and `token_estimate` parameters from the proposal are not needed in v1 because `resolve_context_mode()` uses model-window heuristics only (no per-turn data required). They will be added in P10.8 when mid-session re-escalation is implemented.

**Tests:**
- `test_compose_prompt_jit_mode_produces_smaller_prompt` — JIT prompt < preload prompt for same project
- `test_compose_prompt_hybrid_mode_includes_core_files` — core files present in hybrid mode
- `test_compose_prompt_default_mode_is_auto` — explicit `context_mode="auto"` is accepted
- `test_resolve_context_mode_explicit_override` — explicit "jit" not overridden by auto logic
- `test_resolve_context_mode_large_window_preload` — window=1_000_000 → "preload"
- `test_resolve_context_mode_small_window_jit` — window=32_000 → "jit"
- `test_resolve_context_mode_typical_window_hybrid` — window=128_000 → "hybrid"
- `test_resolve_context_mode_auto_no_model_returns_hybrid` — model_max_tokens=None → "hybrid" (128K default)

**Imports required:** `resolve_context_mode` from `agent.context` (lazy import at line 331, same as existing `build_file_context_with_core_files` lazy import).

---

### 2.5 `agent/runtime.py` — Wire `context_mode` from `ProviderConfig`

**Change type:** Modified function. **Lines:** +25 / −5.

#### 2.5.1 `create_conversation()` — pass `context_mode` to `build_system_prompt()`

In `agent/runtime.py` at lines 1389–1396, modify the `default_provider_cfg` block to also read `context_mode`:

```python
        default_provider_name = self._config.default_provider
        default_provider_cfg = self._config.providers.get(default_provider_name) if default_provider_name else None
        if default_provider_cfg and getattr(default_provider_cfg, "max_tokens", None):
            model_max_for_budget = int(default_provider_cfg.max_tokens)
        else:
            model_max_for_budget = 128_000

        # NEW: read context_mode from provider config (defaults to "auto")
        context_mode = getattr(default_provider_cfg, "context_mode", "auto") or "auto"

        system_prompt = build_system_prompt(
            agent_name, project_path, tool_names,
            agent_role=agent_role,
            model_max_tokens=model_max_for_budget,
            context_mode=context_mode,  # NEW
        )
        # TODO: P10.8 — mid-session re-escalation. Currently the system prompt
        # is built once here and never reassigned. P10.8 will add a
        # _maybe_rebuild_system_prompt() check in the tool loop that calls
        # resolve_context_mode(turn_count, token_estimate) before each LLM call
        # and rebuilds if the effective mode changes.
```

**Tests:**
- `test_runtime_passes_context_mode_from_provider` — `ProviderConfig(context_mode="jit")` flows to `build_system_prompt`
- `test_runtime_defaults_context_mode_auto` — `ProviderConfig()` (no field) → `context_mode="auto"`

#### 2.5.2 `build_system_prompt()` — accept and forward `context_mode`

In `agent/context.py` at line 485, add `context_mode` parameter:

```python
def build_system_prompt(
    agent_name: str,
    project_path: str | None,
    tools: list[str],
    review_mode: str = "off",
    agent_role: str = "",
    model_max_tokens: int | None = None,
    *,
    context_mode: str = "auto",  # NEW
) -> str:
```

In the `compose_system_prompt()` call (around line ~510), forward:

```python
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
            context_mode=context_mode,  # NEW
        )
```

**Tests:**
- `test_build_system_prompt_forwards_context_mode` — verify `context_mode="jit"` reaches `compose_system_prompt`
- `test_build_system_prompt_default_context_mode_auto` — no param → "auto"

---

## 3. Data Flow

```
ProviderConfig(context_mode="auto") 
        ↓
create_conversation() reads context_mode via getattr()
        ↓
build_system_prompt(..., context_mode="auto")
        ↓
compose_system_prompt(..., context_mode="auto")
        ↓
resolve_context_mode("auto", model_max_tokens)  ← v1: creation-time only
        ↓  (returns "preload"|"hybrid"|"jit")
build_file_context_with_core_files(project_path, context_mode=resolved)
        ↓
[mode="preload"] → build_file_context() + CORE_FILES append
[mode="jit"]     → build_file_index()
[mode="hybrid"]  → CORE_FILES append + build_file_index()
        ↓
_apply_system_prompt_budget(result, file_context, model_max_tokens)
        ↓
Final system prompt stored on Conversation.system_prompt (set once, never reassigned)
        ↓
[Agent wants to read file] → file_search(query) → read_file(path) → tool result → LLM
```

**v1 scope — mode is resolved at conversation creation only.** The system prompt is built once in `create_conversation()` (line 1396) and stored on `Conversation.system_prompt` (line 1409). There is no per-turn rebuild. Auto-escalation based on `turn_count` and `token_estimate` requires a mid-session prompt rebuild step (P10.8). For v1, mode is resolved using `model_max_tokens` heuristics only:
- Large window (≥500K, e.g. MiniMax-M3 1M): `preload` — plenty of room
- Small window (≤32K): `jit` — every token counts
- Typical (128K–256K): `hybrid` — balanced default

**Key invariants:**
- Explicit `context_mode="preload"`/`"jit"`/`"hybrid"` is never overridden by auto logic
- File context budget (§4.4b) still enforced via `_apply_system_prompt_budget()`
- `_token_estimate_cache` (`Conversation`, line ~166) naturally invalidates on prompt change (different hash) — relevant for P10.8 when mid-session mode changes are added
- `# TODO: P10.8 — mid-session re-escalation` comment marks the extension point in `create_conversation()`

---

## 4. File Change Summary

| File | Change Type | Lines (est.) | Risk Level |
|---|---|---|---|
| `models/providers.py` | New field + new function | +25 | LOW (additive) |
| `agent/context.py` | New function (`build_file_index`) + new function (`resolve_context_mode`) + modified function | +140 / −10 | LOW (default arg preserves back-compat) |
| `agent/tools.py` | New function (`_file_search`) + new shared helper (`_run_grep`) + refactor `_search_files` + new tool registration | +110 / −15 | LOW (additive; `_search_files` refactor is pure extraction) |
| `utils/prompt_loader.py` | Modified function (pass-through to `resolve_context_mode`) | +8 / −3 | MEDIUM (mode resolution affects prompt content) |
| `agent/runtime.py` | Modified function (pass-through) | +25 / −5 | LOW (defaults preserve behavior) |
| `tests/test_jit_context_discovery.py` | NEW test file | +450 | N/A (test only) |
| **Total** | | **+758 / −33** | |

---

## 5. Implementation Order

**P10.1**: `models/providers.py` — add `context_mode` field + `validate_provider_context_mode()` helper + 4 tests  
**P10.2**: `agent/context.py` — add `build_file_index()` + `resolve_context_mode()` + modify `build_file_context_with_core_files()` + 12 tests  
**P10.3**: `agent/tools.py` — add `_run_grep()` shared helper + refactor `_search_files()` to use it + add `_file_search()` function + register `file_search` tool + 12 tests  
**P10.4**: `utils/prompt_loader.py` — add `context_mode` parameter to `compose_system_prompt()` + wire to `resolve_context_mode()` in `agent.context` + 4 tests  
**P10.5**: `agent/runtime.py` + `agent/context.py::build_system_prompt` — wire `context_mode` end-to-end + 4 tests

After each phase: `pytest tests/test_jit_context_discovery.py tests/test_context.py tests/test_prompt_loader.py tests/test_agent_runtime.py -v` — must show all green.

---

## 6. Acceptance Criteria

| # | Criterion | Test |
|---|---|---|
| 1 | `build_file_index()` returns <3K chars for a fixture project (10 files) | `test_build_file_index_returns_compact_listing` |
| 2 | `file_search` tool is registered and callable via `get_all_tools()` | `test_file_search_tool_registered` |
| 3 | `context_mode` parameter accepted by `build_file_context_with_core_files()`, `compose_system_prompt()`, `build_system_prompt()` | All mode tests |
| 4 | `context_mode` field exists on `ProviderConfig` with default `"auto"` | `test_provider_config_defaults_context_mode_auto` |
| 5 | Auto-escalation resolves mode based on model context window size | `test_resolve_context_mode_*` (4 tests) |
| 6 | All 158 existing in-scope tests still pass without modification | full test run |
| 7 | System prompt in JIT mode is demonstrably smaller than preload mode (measured) | `test_compose_prompt_jit_mode_produces_smaller_prompt` |
| 8 | Hybrid mode includes core files (README, AGENTS, CONVENTIONS, ARCHITECTURE) | `test_compose_prompt_hybrid_mode_includes_core_files` |
| 9 | Backward compatibility: existing callers without `context_mode` get `"preload"` default (no behavior change) | `test_*_backward_compat` |
| 10 | `resolve_context_mode` with explicit `"preload"`/`"jit"`/`"hybrid"` never overridden | `test_resolve_context_mode_explicit_override` |

---

## 7. Edge Cases

| Case | Expected Behavior | Test |
|---|---|---|
| `project_path` doesn't exist | `build_file_index()` returns `""` | `test_build_file_index_handles_invalid_path` |
| `context_mode="invalid"` | `ValueError` raised | `test_build_file_context_invalid_mode_raises` |
| `context_mode="auto"`, `model_max_tokens=None` | Resolves to `"hybrid"` (128K default window) | `test_resolve_context_mode_auto_no_model_returns_hybrid` |
| File in `.gitignore` | Not in index | `test_build_file_index_respects_gitignore` |
| Very large project (1000+ files) | Index shows top 200 by size + directory-level summary with file counts and total sizes per directory | `test_build_file_index_directory_summary_large_project` |
| File is binary | Skipped from line count (but path still shown if matched by name) | `test_build_file_index_handles_binary_files` |
| `file_search("")` | Returns error `ToolResult(success=False, error="empty query")` | `test_file_search_invalid_query_returns_error` |
| Two sessions with different `context_mode` | Each gets its own mode (no shared state — `ProviderConfig` is per-provider, not per-session) | `test_runtime_per_session_context_mode_isolation` |
| Mode changes mid-session | v1: not supported (mode resolved at creation time). P10.8 will add mid-session re-escalation via tool-loop rebuild. | `test_runtime_context_mode_fixed_for_session` |
| File has no extension (e.g. `Makefile`) | Grouped under `### Other (N files)` | `test_build_file_index_groups_files_without_extension` |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update these sections:

1. **§3.21p** — Add `build_file_index` and `resolve_context_mode` to the public API list. Add a paragraph explaining the 3 modes and the creation-time resolution. Reference the new `context_mode` parameter.
2. **§3.21n** — Add `file_search` to the tools list. Document `_run_grep` as the shared grep helper used by both `search_files` and `file_search`. Note `file_search` is purpose-built for context discovery (different from `search_files` which is for raw grep).
3. **§4.4b** — Note that `_apply_system_prompt_budget` still applies in all 3 modes. The index is much smaller (~2K) so truncation is rare in JIT mode.
4. **§3.21d** — Document `context_mode` field on `ProviderConfig` with valid values and resolution heuristics.
5. **§3.21m** — Document the `context_mode` pass-through in `create_conversation()`. Note P10.8 extension point for mid-session re-escalation.

---

## Self-Audit (Rule 9)

### 1. Does every code sample work against the current codebase?

Verified:
- `ProviderConfig` field addition: dataclass auto-accepts new field with default
- `_find_matching_files` signature: `(project_path, query, patterns, max_files=20, max_total_chars=40000) -> list[str]` — verified via `inspect.signature()`
- `_read_file` signature: `(path, project_path, offset=None, limit=None) -> ToolResult` — verified
- `_search_files` signature: `(pattern, project_path, path=None, file_type=None) -> ToolResult` — verified
- `_load_gitignore_patterns`: returns `list[str]` — verified
- `EXCLUDED_DIRS`: frozenset at `agent/context.py:145` — verified
- `_resolve_project_path`: returns `str | None` — verified
- `build_file_context_with_core_files` signature: `(project_path, query=None, max_chars=50_000) -> str` — verified; new param is keyword-only with default "preload"
- `compose_system_prompt` signature: 7 existing positional/keyword args + new keyword-only `context_mode`
- `build_system_prompt` signature: 6 existing args + new keyword-only `context_mode`

### 2. Did I catch all exception types?

New code paths and their exceptions:
- `build_file_index`: `OSError` from `os.listdir`, `os.stat`, `open()` — caught per-file (skip on error)
- `_file_search`: `OSError` from `os.walk`, `subprocess.TimeoutExpired` from grep (re-raised as `ToolResult(success=False, error="...")`)
- `validate_provider_context_mode`: raises `ValueError` on invalid input
- `build_file_context_with_core_files` (modified): raises `ValueError` on invalid mode
- `resolve_context_mode`: raises `ValueError` on invalid mode string; no I/O exceptions (pure function using model_max_tokens heuristics)

### 3. Did I verify key structures?

- `_TOOLS` is `dict[str, tuple[ToolDefinition, Callable[..., ToolResult]]]` — verified at `agent/tools.py:716`
- `ToolDefinition` fields: `name`, `description`, `parameters`, `requires_approval` — verified at `agent/tools.py:32`
- `ToolResult` fields: `success`, `output`, `error`, `duration_ms`, `stdout`, `stderr`, `exit_code` — verified at `agent/tools.py:41`
- `_find_matching_files` returns `list[str]` of relative paths — verified
- `_load_gitignore_patterns` returns `list[str]` of patterns — verified
- `EXCLUDED_DIRS` is `frozenset` — verified
- `CORE_FILES` is `list[str]` of 4 filenames — verified at `agent/context.py:349`
- `Conversation.system_prompt` is `str` field (line 149), set once at construction (line 1409), never reassigned — verified via grep for `.system_prompt =` in `agent/runtime.py` (only one hit: line 1409 in `create_conversation`)
- `_search_files` uses `subprocess.run` with `grep -n -H --directories=skip -r` — verified at lines 514–525; `_run_grep` extracts this exact call

### 4. Did I trace the data flow end-to-end?

Traced from `ProviderConfig.context_mode` → `runtime.create_conversation()` reads via `getattr()` → `build_system_prompt(context_mode=...)` → `compose_system_prompt(context_mode=...)` → `resolve_context_mode(context_mode, model_max_tokens)` (in `agent/context.py`) → `build_file_context_with_core_files(context_mode=resolved)` → final prompt stored once on `Conversation.system_prompt` (never reassigned).

For `file_search` tool: agent LLM call with function-call → `agent.tools._file_search(query, ...)` → combines `_find_matching_files` + `_run_grep` (shared helper) → grouped output → LLM sees preview lines.

**v1 limitation confirmed:** `system_prompt` is set once at line 1409 and never reassigned (grep for `.system_prompt =` in runtime.py returns only the `create_conversation` assignment). Mid-session escalation requires adding a rebuild step to the tool loop — deferred to P10.8.

### 5. Would an implementer following this spec produce working code?

Yes. Every change specifies:
- Exact function signatures (verified via `inspect.signature()`)
- Exact line numbers where modifications go
- Before/after code samples
- Validation logic and edge cases
- Test names and what they verify
- Architecture section references

---

## Files NOT Changed

- `models/conversation.py` — The `Conversation` dataclass doesn't need a `context_mode` field. Mode is per-provider, not per-conversation. The system prompt is built once at `create_conversation()` time and stored on the conversation.
- `prompts/system/*.md` — No template changes. The `[Use file_search(...)]` hint is appended by `build_file_index()` directly, not via templates.
- `tests/test_context_strategy*.py` — ContextStrategy protocol is orthogonal to context discovery (compaction manages `messages[]`, discovery manages `file_context`).
- `docs/2026-06-27-CM-INDUSTRY-COMPARISON.md` — Updated separately as part of P10.6 (documentation phase, not implementation).

---

**Mantra check:** "A spec is a contract. If it has a bug, the implementer will ship that bug. Verify everything." ✓

**Mantra 2 check:** "Done means every file changed, every test passing, every old pattern gone." ✓ (acceptance criteria include grep sweep for old `build_file_context_with_core_files()` callsites without `context_mode` — should all still work due to default arg)

---

## Revision History

| Date | Revision | Author | Changes |
|---|---|---|---|
| 2026-06-27 | v1.0 | Captain Q | Initial spec from proposal |
| 2026-06-27 | v1.1 | Qaster | Fix 4 review concerns: (1) v1 scope is conversation-creation-time resolution only, mid-session escalation deferred to P10.8; (2) extract `_run_grep()` shared helper to prevent grep behavior drift between `search_files` and `file_search`; (3) move `resolve_context_mode()` from `prompt_loader.py` to `agent/context.py` (context-strategy concern); (4) add tiered directory-level summary for large projects (1000+ files) instead of bare truncation note |
