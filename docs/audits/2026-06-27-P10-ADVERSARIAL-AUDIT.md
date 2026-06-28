# 2026-06-27 — P10 (JIT Context Discovery) Adversarial Audit

**Author:** Captain Q (adversarial audit)
**Subject:** Implementation of `docs/specs/SPEC-JIT-CONTEXT-DISCOVERY-1.md` v1.1
**Implementation commit:** `262af32 feat(jit-context-discovery): implement P10`
**Tests:** 50 new tests in `tests/test_jit_context_discovery.py` — all pass
**Methodology:** Per `prompts/adversarialDebugger.md` — find every way the code's mental model is WRONG

---

## Summary

| # | Severity | Area | Bug |
|---|---|---|---|
| 1 | MEDIUM | `_file_search` dead code | Unreachable code block at `tools.py:640-650` (leftover from `_search_files` copy) |
| 2 | **HIGH** | Case-sensitivity in `resolve_context_mode` / `compose_system_prompt` | "AUTO", "PRELOAD", " jit " (whitespace), etc. raise `ValueError`; runtime does not normalize |
| 3 | MEDIUM | `resolve_context_mode` negative-input | `model_max_tokens=-1` returns `"jit"` (treated as tiny window) |
| 4 | MEDIUM | `_file_search` duplicate-file bug | Filename match (`subdir/foo.py`) and content match (`./subdir/foo.py`) are NOT deduplicated by `set()` — same file appears twice |
| 5 | LOW | `build_file_index` I/O | Line counting reads entire file via `sum(1 for _ in f)` — high memory for very large files |
| 6 | MEDIUM | Documentation drift | `docs/ARCHITECTURE.md` §3.21p, §3.21n, §3.21m, §3.21d, §4.4b NOT updated despite spec requiring it |
| 7 | MEDIUM | Spec ↔ tests contract | 7 spec-listed tests missing (`test_runtime_passes_context_mode_from_provider`, `test_runtime_defaults_context_mode_auto`, `test_*_backward_compat`, `test_runtime_per_session_context_mode_isolation`, `test_runtime_context_mode_fixed_for_session`, `test_build_file_index_handles_binary_files`, etc.) |
| 8 | LOW | `_run_grep` input validation | Does not validate `search_root` (None/empty would default to cwd); reachable only via misuse |
| 9 | LOW | Hybrid mode UX | Oversized core files (>50KB) are silently dropped without placeholder/warning |
| 10 | LOW | `build_file_index` perf | Default `include_line_counts=True` adds ~250ms latency for 787-file project |

**Total: 1 HIGH, 4 MEDIUM, 5 LOW** — none are CRITICAL, all should be fixed before declaring done.

---

## BUG #1 — Dead code in `_file_search` (MEDIUM)

**Severity:** MEDIUM (code smell / signals incomplete refactor)
**Location:** `agent/tools.py:640-650`
**Assumption violated:** "After `return` is reached, function exits — no code below should matter"

**Reproduction:**
```python
import inspect
from agent.tools import _file_search
src = inspect.getsource(_file_search)
# After line 638: "return ToolResult(success=True, output=output)"
# Lines 640-650 contain:
#     if returncode == 1: ...
#     elif returncode != 0: ...
#     output = stdout
#     if len(output) > MAX_EXEC_OUTPUT: ...
#     return ToolResult(success=True, output=output)
# All UNREACHABLE — copy-paste leftover from _search_files
```

**Attack vector:** None functional (unreachable). Signals that `_file_search` was created by copy-paste from `_search_files` without cleanup — high risk for future drift between the two tools.

**Root cause:** `_file_search` was modeled on `_search_files` but the implementer did not strip the tail of `_search_files` (which handled returncode 0/1). The current `_file_search` handles `returncode == 1` silently (no exception) and treats empty stdout as no-match — but the duplicated code at the end never runs.

**Fix:** Delete `tools.py:640-650`.

---

## BUG #2 — Case-sensitive `context_mode` validation (HIGH)

**Severity:** HIGH (user-facing failure on edge-case input)
**Locations:** `agent/context.py:resolve_context_mode` line 374, `utils/prompt_loader.py:compose_system_prompt` line 334
**Assumption violated:** "`context_mode` from `ProviderConfig` is always one of the canonical lowercase strings"

**Reproduction:**
```python
from utils.prompt_loader import compose_system_prompt
compose_system_prompt(agent_name="X", project_path="/tmp", context_mode="AUTO")
# ValueError: Invalid context_mode: 'AUTO'

compose_system_prompt(agent_name="X", project_path="/tmp", context_mode=" jit ")
# ValueError: Invalid context_mode: ' jit '

from agent.context import resolve_context_mode
resolve_context_mode("Preload", 128_000)
# ValueError: Invalid context_mode: 'Preload'
```

**Attack vector:** A user edits `~/.crabcakes/providers.yaml` and writes `context_mode: AUTO` or `context_mode: Preload` (common in YAML configs). The runtime `agent/runtime.py:1400` does:
```python
context_mode=getattr(default_provider_cfg, "context_mode", "auto") or "auto"
```
This bypasses `validate_provider_context_mode` (which DOES normalize) and passes raw value to `build_system_prompt → compose_system_prompt → resolve_context_mode`, which raises. **Result: every LLM call crashes** when user has any non-canonical mode string in config.

**Root cause:** `validate_provider_context_mode` exists in `models/providers.py` and DOES handle normalization (`.lower().strip()`), but the runtime never calls it. Two validation paths diverge:
- `validate_provider_context_mode` (case-insensitive, normalizes whitespace) — UNUSED
- inline `if context_mode not in ("preload", "jit", "hybrid")` (case-sensitive, no normalization) — used in `build_file_context_with_core_files` and `resolve_context_mode`

**Fix (smallest):** Have `resolve_context_mode` call `validate_provider_context_mode` first to normalize before the comparison:
```python
def resolve_context_mode(explicit_mode: str, model_max_tokens: int | None) -> str:
    normalized = validate_provider_context_mode(explicit_mode)
    if normalized in ("preload", "jit", "hybrid"):
        return normalized
    # auto: resolve by window size
    ...
```

This makes both code paths consistent and matches the helper's behavior.

**Test gap:** No test for `"AUTO"`, `"Preload"`, `" jit "`, etc. — these inputs are not covered.

---

## BUG #3 — `resolve_context_mode` accepts negative `model_max_tokens` (MEDIUM)

**Severity:** MEDIUM (silent wrong answer for invalid input)
**Location:** `agent/context.py:357-385` (specifically line 380: `window = model_max_tokens or 128_000`)
**Assumption violated:** "`model_max_tokens` is non-negative"

**Reproduction:**
```python
from agent.context import resolve_context_mode
resolve_context_mode("auto", -1)        # → "jit" (WRONG; should reject)
resolve_context_mode("auto", -1_000_000) # → "jit"
resolve_context_mode("auto", float("inf")) # → "preload" (acceptable, but unchecked)
```

**Attack vector:** If `ProviderConfig.max_tokens` is corrupted/migrated from older version (e.g., `-1` sentinel for "unknown"), `resolve_context_mode` returns `"jit"` silently. The LLM gets a different file-context strategy than the operator intended, with no error visible.

**Root cause:** `window = model_max_tokens or 128_000` treats any truthy value (including negative) as valid. No `> 0` check.

**Fix:**
```python
if explicit_mode in ("preload", "jit", "hybrid"):
    return explicit_mode
if explicit_mode != "auto":
    raise ValueError(f"Invalid context_mode: {explicit_mode!r}")
if model_max_tokens is None or model_max_tokens <= 0:
    return "hybrid"  # default to balanced mode, not silent fallback
window = model_max_tokens
...
```

**Note:** v1.1 spec says "treat None or 0 as 128_000" — both are falsy, so `or` covers them. The spec did NOT consider negatives. Decision: reject negatives, OR normalize to 128K. **Recommend reject** (silent normalization hides bugs).

---

## BUG #4 — `_file_search` shows same file twice (MEDIUM)

**Severity:** MEDIUM (corrupts tool output; LLM confused)
**Location:** `agent/tools.py:557-637` (`_file_search`)
**Assumption violated:** "Filename match and content match use the same relative-path format"

**Reproduction:**
```python
import os, tempfile
from agent.tools import _file_search

with tempfile.TemporaryDirectory() as d:
    sub = os.path.join(d, "subdir")
    os.makedirs(sub)
    with open(os.path.join(sub, "hello.py"), "w") as f:
        f.write("hello world")
    r = _file_search("hello", d)
    # Output contains BOTH:
    #   ./subdir/hello.py (1 lines, 0KB)        ← from grep (cwd-relative: "./")
    #     Line 1: hello world
    #   subdir/hello.py (1 lines, 0KB)          ← from _find_matching_files (rel_path)
    #     [name match only — use read_file for content]
```

**Attack vector:** Any query that matches both a filename and content in a subdirectory. The file appears twice with different paths. The LLM wastes tokens on the duplicate entry AND gets confused about which path to use with `read_file`.

**Root cause:** `_find_matching_files` returns paths like `subdir/hello.py` (no leading `./`), but grep output (run with `cwd=search_root, -- pattern .`) returns paths like `./subdir/hello.py` (with leading `./`). The merge:
```python
all_files = set(name_matches)
all_files.update(grep_hits.keys())
all_files = sorted(all_files)[:max_results]
```
treats the two as distinct strings. The `set()` deduplication is a no-op.

**Fix:** Normalize grep output paths before merging:
```python
for line in stdout.splitlines():
    parts = line.split(":", 2)
    if len(parts) >= 3:
        fpath = parts[0]
        if fpath.startswith("./"):
            fpath = fpath[2:]
        lineno, content = int(parts[1]), parts[2]
        ...
```

**Test gap:** No test asserts that a file matching both name and content appears ONCE. Adding a test would have caught this.

---

## BUG #5 — `build_file_index` line counting reads entire file (LOW)

**Severity:** LOW (perf concern; no data loss)
**Location:** `agent/context.py:485-489` (inside `build_file_index`)
**Assumption violated:** "File line counting is bounded I/O"

**Reproduction:**
```python
import time, tempfile, os
from agent.context import build_file_index

# 200 files × 5MB each
with tempfile.TemporaryDirectory() as d:
    for i in range(200):
        with open(os.path.join(d, f"f{i:03d}.py"), "w") as f:
            f.write("x = 1\n" * 500_000)  # 5MB per file

    t0 = time.time()
    r = build_file_index(d)
    print(f"{time.time()-t0:.2f}s")  # ~5-10s
```

**Attack vector:** Project with many large files (logs, generated code, vendored deps). Each `sum(1 for _ in f)` reads the whole file through the iterator, holding the file descriptor open and allocating the iterator state. For 200 files × 50MB = 10GB of I/O.

**Root cause:** Line counting reads every byte of every file, even when only the line count is needed.

**Fix (perf, not correctness):** For very large files, count lines in chunks without holding them all, OR skip line counting for files > some size threshold (e.g., 1MB). The spec already provides `include_line_counts=False` opt-out — but it's not auto-enabled.

**Recommended compromise:** If `os.path.getsize() > 1_000_000` and `include_line_counts=True`, log a warning and skip line count for that file (show `"size only"`).

---

## BUG #6 — ARCHITECTURE.md sections not updated (MEDIUM)

**Severity:** MEDIUM (documentation drift — violates spec §7 "Documentation")
**Location:** `docs/ARCHITECTURE.md`
**Assumption violated:** "Spec's §7 Documentation requirements were met"

**Spec requirement:** Update §3.21p (agent/context.py), §3.21n (agent/tools.py), §3.21m (agent/runtime.py), §3.21d (models/providers.py), §4.4b (utils/prompt_loader.py) to reflect new behavior.

**Reproduction:**
```bash
git show --stat 262af32 -- docs/ARCHITECTURE.md
# (empty — no changes to ARCHITECTURE.md in P10 implementation commit)
git grep -n "context_mode\|file_search\|build_file_index" docs/ARCHITECTURE.md
# (no matches — sections completely silent on P10)
```

**Attack vector:** A future developer reading ARCHITECTURE.md (the canonical project reference) sees zero mention of `context_mode`, `file_search`, or `build_file_index`. They will be confused about which file owns what. The spec is the only place this is documented.

**Root cause:** Implementation commit `262af32` modified 6 source/test files but did NOT touch `docs/ARCHITECTURE.md`. The spec's documentation step was skipped.

**Fix:** Add to `ARCHITECTURE.md`:
- §3.21p: "Added `build_file_index()`, `resolve_context_mode()`. `build_file_context_with_core_files()` and `build_system_prompt()` gain `context_mode` parameter."
- §3.21n: "Added `file_search` tool. Added shared `_run_grep()` helper used by both `search_files` and `file_search`."
- §3.21m: "`create_conversation()` reads `context_mode` from `ProviderConfig` and passes to `build_system_prompt`. `# TODO: P10.8 — mid-session re-escalation` marker."
- §3.21d: "Added `context_mode: str = 'auto'` field + `validate_provider_context_mode()` helper."
- §4.4b: "Added `context_mode` keyword-only parameter. Lazy-imports `resolve_context_mode` from `agent.context`."

---

## BUG #7 — Spec ↔ tests contract violated (MEDIUM)

**Severity:** MEDIUM (spec contract broken; tests don't enforce spec)
**Location:** `tests/test_jit_context_discovery.py` (missing tests)
**Assumption violated:** "All spec-listed tests are implemented"

**Spec-listed tests that are MISSING from implementation:**

1. `test_runtime_passes_context_mode_from_provider` — spec §3.21m acceptance test
2. `test_runtime_defaults_context_mode_auto` — spec §3.21m acceptance test
3. `test_build_system_prompt_backward_compat` — spec §4.4b acceptance test (default mode unchanged)
4. `test_compose_system_prompt_backward_compat` — spec §4.4b acceptance test
5. `test_runtime_per_session_context_mode_isolation` — spec §7 edge case
6. `test_runtime_context_mode_fixed_for_session` — spec §7 edge case
7. `test_build_file_index_handles_binary_files` — spec §7 edge case

**Reproduction:**
```bash
grep -E "test_runtime_passes_context_mode_from_provider|test_runtime_defaults_context_mode_auto|test_.*_backward_compat|test_runtime_per_session|test_runtime_context_mode_fixed|test_build_file_index_handles_binary" tests/test_jit_context_discovery.py
# (no matches — tests not implemented)
```

**Attack vector:** Spec is the contract. Missing tests mean the contract isn't enforced — future refactors can break behavior without test failures.

**Root cause:** The implementer wrote 50 tests covering the core paths (model providers, resolve_context_mode, build_file_index, mode selection in build_file_context_with_core_files, file_search, registration, prompt composition). But did not write tests for:
- Runtime integration (mode flowing from ProviderConfig → build_system_prompt)
- Backward compatibility (existing callers work without context_mode)
- Per-session isolation (two sessions with different modes)
- Binary file handling in index

**Fix:** Add the 7 missing tests. Estimated effort: ~2 hours.

---

## BUG #8 — `_run_grep` does not validate `search_root` (LOW)

**Severity:** LOW (reachable only via misuse; current callers all check `None` first)
**Location:** `agent/tools.py:505-528`
**Assumption violated:** "`search_root` is a valid directory path"

**Reproduction:**
```python
from agent.tools import _run_grep
rc, out, err = _run_grep("foo", None)
# Returns (0, "", "") — silently uses CWD as search root
# (no crash, but searches wrong location)

rc, out, err = _run_grep("foo", "")
# FileNotFoundError: [Errno 2] No such file or directory: ''
# (inconsistent — empty string crashes but None doesn't)
```

**Attack vector:** If a future caller forgets to validate `search_root`, `_run_grep` silently searches the wrong directory. Currently `_file_search` and `_search_files` both call `_resolve_project_path(".", project_path)` first which returns `None` for invalid paths, and they handle `None` before calling `_run_grep`. So this is currently unreachable — but the helper itself is unsafe.

**Root cause:** `_run_grep` is a thin subprocess wrapper with no input validation.

**Fix:** Add at the top of `_run_grep`:
```python
if not search_root:
    raise ValueError(f"_run_grep: search_root must be a non-empty path, got {search_root!r}")
if not os.path.isdir(search_root):
    raise FileNotFoundError(f"_run_grep: search_root not a directory: {search_root!r}")
```

---

## BUG #9 — Hybrid mode silently drops oversized core files (LOW)

**Severity:** LOW (UX bug, no crash)
**Location:** `agent/context.py:600-606` (the `core_sections` loop in `build_file_context_with_core_files`)
**Assumption violated:** "Core files always appear in hybrid mode if present"

**Reproduction:**
```python
import tempfile, os
from agent.context import build_file_context_with_core_files

with tempfile.TemporaryDirectory() as d:
    # README.md > 50KB (the _read_file_safe cap)
    with open(os.path.join(d, "README.md"), "w") as f:
        f.write("# Title\n" + "x" * 100_000)
    r = build_file_context_with_core_files(d, context_mode="hybrid")
    # Output: ## File index (1 files) — no README, no placeholder
    print(r)
```

**Attack vector:** A user with a 100KB README expects hybrid mode to include README (the spec says hybrid preserves core files). Instead, README is silently omitted. The user sees only the file index and has no idea the README was meant to be there.

**Root cause:** `build_file_context_with_core_files` calls `_read_file_safe` (line 605) which returns `None` for files > 50KB. The hybrid mode then falls through to `if not core_sections: return file_index` (line 615) and the user gets only the index.

**Fix:** Add a placeholder for oversized core files:
```python
for core_file in CORE_FILES:
    core_path = os.path.join(project_path, core_file)
    content = _read_file_safe(core_path)
    if content:
        core_sections.append(f"## {core_file}\n\n{content}\n")
    elif os.path.isfile(core_path):
        # File exists but is too large to inline
        size = os.path.getsize(core_path)
        core_sections.append(
            f"## {core_file}\n\n[{size // 1024}KB — too large for inline; "
            f'use read_file("{core_file}") to read in full]\n'
        )
```

This matches the existing CB-5 truncation marker pattern.

---

## BUG #10 — `build_file_index` adds ~250ms latency on real project (LOW)

**Severity:** LOW (perf; one-shot at conversation start)
**Location:** `agent/context.py:485-489`
**Assumption violated:** "Default `include_line_counts=True` is fast"

**Reproduction:**
```python
import time
from utils.prompt_loader import compose_system_prompt

t0 = time.time()
p = compose_system_prompt(
    agent_name="X", project_path="/home/q/projects/crabcakes",
    context_mode="jit", model_max_tokens=128_000,
)
print(f"{time.time()-t0:.3f}s, prompt_len={len(p)}")
# → 0.283s for 787-file project

# Compare: PRELOAD mode (no line counting)
t0 = time.time()
p = compose_system_prompt(
    agent_name="X", project_path="/home/q/projects/crabcakes",
    context_mode="preload", model_max_tokens=128_000,
)
print(f"{time.time()-t0:.3f}s, prompt_len={len(p)}")
# → 0.020s for 787-file project
```

**Attack vector:** Conversation creation is noticeably slower for projects with many files. For 5000-file projects, could approach 1-2 seconds. JIT's value prop is "save tokens" — but the line counting erodes some of the latency benefit.

**Root cause:** `include_line_counts=True` is default, and every file is read in full for line count. See BUG #5 for the memory concern.

**Fix:** Either:
- Change default to `include_line_counts=False` (saves perf, loses minor info)
- Auto-disable line counting for files >1MB (keeps accuracy for small files)
- Add progress log so user sees what's happening

**Spec note:** v1.1 spec defaulted `include_line_counts=True`. This is a per-project tradeoff decision.

---

## Mantra Check (per `prompts/adversarialDebugger.md`)

> "You don't verify the code works — you prove it doesn't."

- ✓ Tested case sensitivity, whitespace, negatives — found BUG #2 (HIGH), BUG #3
- ✓ Tested path-prefix mismatch — found BUG #4 (file shown twice)
- ✓ Tested scope coverage — found BUG #6 (ARCHITECTURE.md not updated)
- ✓ Tested spec contract compliance — found BUG #7 (5 missing tests)
- ✓ Tested input validation — found BUG #8 (_run_grep(None))
- ✓ Tested silent failure modes — found BUG #9 (oversized core files dropped)
- ✓ Tested performance edge cases — found BUG #5, BUG #10
- ✓ Verified all 50 new tests pass — they do, but they don't cover the bug scenarios above
- ✓ Ran regression tests on `test_context.py`, `test_context_strategy_audit_fixes.py` — all still pass

## Test suite health

- `tests/test_jit_context_discovery.py`: 50/50 pass
- `tests/test_context.py`: 33/33 pass
- `tests/test_context_strategy_audit_fixes.py`: 20/20 pass
- `tests/test_prompt_loader.py`: not directly re-run in this audit
- `tests/test_agent_runtime.py`: not directly re-run in this audit

**Net:** No existing tests broken. New tests all pass. Bugs found are mostly **missing coverage** (BUG #7), **missing input validation** (BUG #2, BUG #3, BUG #8), and **one real correctness bug** (BUG #4: file shown twice).

---

## Recommended fix order

1. **BUG #2 (HIGH)** — normalize mode input in `resolve_context_mode` (5 min)
2. **BUG #4 (MEDIUM)** — normalize grep output paths in `_file_search` (5 min)
3. **BUG #6 (MEDIUM)** — update ARCHITECTURE.md sections (20 min)
4. **BUG #7 (MEDIUM)** — add 7 missing tests (2 hours)
5. **BUG #1 (LOW)** — delete dead code at `tools.py:640-650` (2 min)
6. **BUG #3 (LOW)** — reject negative `model_max_tokens` (5 min)
7. **BUG #9 (LOW)** — add placeholder for oversized core files (10 min)
8. **BUG #8 (LOW)** — validate `_run_grep` input (5 min)
9. **BUG #5 (LOW)** — auto-skip line counting for large files (15 min)
10. **BUG #10 (LOW)** — consider default `include_line_counts=False` or progress log (10 min)

**Estimated total fix time: 3 hours.**

After fixes, re-run: `pytest tests/test_jit_context_discovery.py tests/test_context.py tests/test_context_strategy_audit_fixes.py tests/test_prompt_loader.py tests/test_agent_runtime.py -v`
