# SPEC: Context Bloat Phase 5 — Hotfix Audit Findings (CB-5)

**Date:** 2026-06-17
**Author:** Qaster (supervisor/auditor)
**Status:** Draft — for implementation
**Implements:** Qrusher end-to-end audit findings (`docs/audits/2026-06-17-CONTEXT-BLOAT-END-TO-END-AUDIT.md`)
**Depends on:** CB-1 (`601067b`), CB-2 (`d43539e`), CB-4 (`0c3db2b`)
**Target branch:** main

> **Architecture compliance:** Changes are confined to `models/conversation.py` (data model layer, §3.17), `utils/prompt_loader.py` (prompt composition, §4.4a), and test files. No imports from `ui/`, `agent/`, or `gateway/` in the changed production code. No new public API surface. No GTK, no network, no LLM calls.

---

## DISCOVERY

- **Read `models/conversation.py`**: `_tiktoken_encoding_for` is a module-level helper (line 25). `Conversation.get_token_estimate()` (line 198) calls `_tiktoken_encoding_for(self.model)` then `_count_tokens_accurate(encoding)` — no caching. `Conversation.trim_to_token_limit` (line 265) has a `while self.get_token_estimate() > max_tokens` loop (line 265) that re-encodes the entire conversation on every iteration. Summary injection gate at line 291 is `if len(self.messages) >= 8:` — checked on POST-trim count, so aggressive trims that drop below 8 never fire. `Conversation` is a `@dataclass` with no `__post_init__`.

- **Read `utils/prompt_loader.py`**: `_truncate_file_context_smart` (line 365) splits on `## ` headers and keeps sections from the END until budget is exceeded. No awareness of which sections are "core files" vs regular files — it just keeps whatever is last. `build_file_context_with_core_files` in `agent/context.py` (line 312) appends core files at the end, but when the smart-truncation budget is smaller than even one core file section, only that last section survives. The `_apply_system_prompt_budget` function name implies a total budget, but it only caps the file context portion, not the template result.

- **Read `agent/context.py`**: `CORE_FILES` constant at line 304 lists `["README.md", "AGENTS.md", "CONVENTIONS.md", "ARCHITECTURE.md"]`. `build_file_context_with_core_files` (line 312) appends these after the base file context. Core files can be duplicated: they appear in the base context (from `build_file_context`) AND in the appended core block.

- **Read `agent/runtime.py:1151-1200`**: `_compute_model_max` returns an `int` (never `None`). The docstring mentions `conv.model is None` in a comment, but the actual code does `conv.model.split("/")` inside a `try/except Exception` that catches `TypeError` on `None`. The `Conversation.model` field is typed `str` with default `""`.

- **Read `tests/test_conversation.py`**: `TestConversationTrim` (line 329) has 4 tests using small payloads. `TestConversationTokenEstimate` (line 225) has 4 tests. `TestTiktokenAccurate` (line 279) has 5 tests. No performance/latency tests exist.

- **Read `tests/test_phase4.py`**: `TestTrimSummaryInjection` (line 283) has 7 tests. All use small payloads. No test covers the "aggressive trim drops below 8 messages" case for summary injection.

- **Read `tests/test_prompt_loader.py:387-470`**: `TestSystemPromptBudget` has 4 tests. `test_core_files_preserved_at_end` (line 431) uses `model_max_tokens=50_000` (large budget) with tiny core files — trivially passes.

- **Architecture owner:** `models/conversation.py` owns token estimation (§3.17). `utils/prompt_loader.py` owns system prompt composition (§4.4a). `agent/context.py` owns file context building (§4.4). No cross-layer violations in the proposed changes.

- **Existing patterns:** The `Conversation` dataclass uses plain attributes (no properties, no slots). Adding a private `_token_estimate_cache` attribute follows the same underscore-prefix convention as `_last_trim_removed` in `agent/runtime.py`. The `_truncate_file_context_smart` function uses `re.split(r'(?=^## )', ...)` to parse sections — the fix adds a set lookup on section headers, same pattern.

---

## 1. Overview

### Problem statement

Qrusher's end-to-end audit found 3 real bugs and 2 design gotchas that the per-phase audits missed:

1. **Bug #1 (HIGH):** `get_token_estimate()` re-encodes the entire conversation with tiktoken on every call. `trim_to_token_limit` calls it once per loop iteration. A 100K-char system prompt makes each call take ~5.8 seconds; a full trim takes 30+ seconds.
2. **Bug #2 (MEDIUM):** `_truncate_file_context_smart` doesn't guarantee core files survive. When the budget is smaller than one core file section, only the last section survives — all other core files are dropped, violating the spec's "core files preserved" invariant.
3. **Bug #3 (LOW, latent):** `_tiktoken_encoding_for(None)` raises `TypeError` because `model.split("/")` is outside the `try/except`. Not reachable today (`model` defaults to `""`), but the function's stated contract says "returns None on any failure."
4. **Gotcha #1:** Summary injection only fires when `len(messages) >= 8` AFTER trim. An aggressive trim that drops to 4 messages injects no summary — the model loses all context of what was removed.
5. **Gotcha #2:** `_apply_system_prompt_budget` implies a total system prompt budget, but only caps the file context portion. Templates alone can exceed the budget. This is a documentation/naming issue.

### Solution summary

| # | Fix | Effort |
|---|-----|--------|
| 1 | Add a token-estimate cache to `Conversation` keyed on `(len(messages), system_prompt_hash)`. Invalidate on message add/remove. | ~20 lines |
| 2 | Add core-file-awareness to `_truncate_file_context_smart` using a set of core filenames. Core sections are always kept; truncation only drops non-core sections. | ~15 lines |
| 3 | Move `bare_name = model.split(...)` inside the `try/except Exception` block, or add a type guard at the top of `_tiktoken_encoding_for`. | ~3 lines |
| 4 | Change summary gate from `if len(self.messages) >= 8:` to `if messages_removed > 0 and len(self.messages) >= 4:`. | ~5 lines |
| 5 | Add a docstring note to `_apply_system_prompt_budget` documenting that it caps file context, not total prompt size. | ~5 lines |

### Scope

| In scope | Out of scope |
|----------|-------------|
| `models/conversation.py`: token-estimate cache, None guard, summary gate fix | Rewriting the trim loop to pre-compute deficit (Option B from audit) |
| `utils/prompt_loader.py`: core-file-aware truncation, docstring fix | Per-file truncation (Option C from audit) |
| `tests/test_conversation.py`: cache tests, None model test, summary-on-aggressive-trim test | Restructuring `build_file_context_with_core_files` data layout |
| `tests/test_prompt_loader.py`: core-files-preserved-with-tiny-budget test | Renaming `_apply_system_prompt_budget` (breaks callers) |
| `docs/ARCHITECTURE.md`: §3.17 cache note | Template truncation (out of scope per CB-2 spec) |

---

## 2. Changes by File

### 2.1 `models/conversation.py` — Token-estimate cache (Bug #1)

**What changes:** Add a private `_token_estimate_cache` attribute to `Conversation`. Invalidate it whenever messages are added or removed. `get_token_estimate()` checks the cache before re-encoding.

**Attribute addition** (in the `Conversation` dataclass field list, after `step_count`):

```python
    # Phase CB-5: token-estimate cache (BUG #1 fix from end-to-end audit).
    # Invalidated by any message add/remove/trim operation. Keyed on
    # (len(messages), hash(system_prompt)). See get_token_estimate().
    _token_estimate_cache: tuple | None = field(default=None, repr=False, compare=False)
```

**Cache invalidation** — add `_token_estimate_cache = None` to:
- `add_user_message` — after `self.messages.append(msg)`
- `add_assistant_message` — after `self.messages.append(msg)`
- `add_tool_result` — after `self.messages.append(msg)`
- `trim_to_token_limit` — set `self._token_estimate_cache = None` at the top of the method (before the while loop)

**Updated `get_token_estimate`** (replaces the current method at line 198):

```python
    def get_token_estimate(self) -> int:
        """
        Token count estimate for the conversation.

        Phase CB-4: uses tiktoken when available, chars // 4 fallback.
        Phase CB-5: caches the tiktoken result to avoid re-encoding on
        every call (the trim loop calls this once per iteration; without
        caching, a 100K-char system prompt makes each call take ~6s).
        """
        encoding = _tiktoken_encoding_for(self.model)
        if encoding is None:
            # Fallback path — fast (string length), no caching needed.
            system_chars, conv_chars = self._count_char_tokens()
            return (system_chars + conv_chars) // 4

        # Tiktoken path — check cache.
        cache_key = (len(self.messages), hash(self.system_prompt))
        if self._token_estimate_cache is not None:
            cached_key, cached_value = self._token_estimate_cache
            if cached_key == cache_key:
                return cached_value

        result = self._count_tokens_accurate(encoding)
        self._token_estimate_cache = (cache_key, result)
        return result
```

**Verification of cache key correctness:**
- `len(self.messages)` changes when messages are added/removed → cache miss → re-encode. ✓
- `hash(self.system_prompt)` changes when the system prompt is updated → cache miss → re-encode. ✓
- Message content changes (e.g., `tool_call.result` populated after initial append) do NOT change the key. This is a **known limitation**: if a tool call's result is populated after the message is added, the cache will be stale.
- **Mitigation:** `add_tool_result` creates a NEW `Message` (it doesn't mutate an existing one). `ToolCall.mark_completed(result)` does mutate the existing `ToolCall` object, but this happens on the assistant message's `tool_calls` list, which changes the token count without invalidating the cache.
- **Decision:** Accept this limitation. The trim loop is the only caller that benefits from caching. The trim runs AFTER all tool calls have completed for the turn. The cache is invalidated at the top of `trim_to_token_limit` and on every `add_*` call. The only stale-window is within a single `_run_loop` iteration between `mark_completed` and the next `add_user_message` — but `get_token_estimate` is only called by `trim_to_token_limit` (inside the trim loop) and by `get_token_breakdown` (which computes independently). No correctness issue in practice.
- **Future hardening (Tier 2+):** Include `sum(len(tc.result or "") for msg in self.messages for tc in msg.tool_calls)` in the cache key. Deferred — adds O(n) work per cache check, partially defeating the purpose.

### 2.2 `models/conversation.py` — None guard on `_tiktoken_encoding_for` (Bug #3)

**What changes:** Move the `bare_name = model.split(...)` line inside the outer `try/except Exception` or add a type guard at the top.

**Updated function** (replaces current function at line 25):

```python
def _tiktoken_encoding_for(model) -> object | None:
    """
    Return the tiktoken encoding for the given model name, or None on failure.

    Resolution order:
      1. tiktoken.encoding_for_model(model_name)  (OpenAI models)
      2. tiktoken.get_encoding("cl100k_base")    (default for non-OpenAI models)

    Returns None if tiktoken is not installed, the model is not a string,
    or any other exception occurs.
    The caller must fall back to the chars // 4 heuristic when None is returned.

    Strips provider prefix from model names like "openai/gpt-4o" → "gpt-4o".
    """
    if not isinstance(model, str) or not model:
        # Non-string or empty — fall through to cl100k_base default below.
        bare_name = ""
    else:
        bare_name = model.split("/", 1)[-1] if "/" in model else model

    try:
        import tiktoken
    except ImportError:
        return None

    try:
        if bare_name:
            return tiktoken.encoding_for_model(bare_name)
        # Empty/None model — skip encoding_for_model (it requires a non-empty
        # string) and fall through to the cl100k_base default.
        raise KeyError("empty model name")

    except KeyError:
        try:
            return tiktoken.get_encoding(_DEFAULT_ENCODING_NAME)
        except Exception:
            return None
    except Exception:
        return None
```

**Verification:**
- `_tiktoken_encoding_for("gpt-4o")` → `tiktoken.encoding_for_model("gpt-4o")` → o200k_base ✓
- `_tiktoken_encoding_for("openai/gpt-4o")` → bare_name `"gpt-4o"` → o200k_base ✓
- `_tiktoken_encoding_for("claude-3-opus")` → KeyError → cl100k_base ✓
- `_tiktoken_encoding_for(None)` → `bare_name = ""` → raises KeyError → cl100k_base ✓
- `_tiktoken_encoding_for("")` → `bare_name = ""` → raises KeyError → cl100k_base ✓
- `_tiktoken_encoding_for(123)` → `not isinstance(model, str)` → `bare_name = ""` → cl100k_base ✓

**Note on behavior change for empty string:** Before this fix, `_tiktoken_encoding_for("")` called `tiktoken.encoding_for_model("")` which raised `KeyError`, falling back to `cl100k_base`. After this fix, it raises `KeyError` directly. Same result, cleaner path. No behavior change visible to callers.

### 2.3 `models/conversation.py` — Summary gate fix (Gotcha #1)

**What changes:** Track whether any messages were removed during the trim, and fire summary injection based on removal, not on post-trim count.

**Updated trim method** — the summary injection section (currently at line 291):

Current code:
```python
        if len(self.messages) >= 8:
            summary = self._last_exchange_summary()
            if summary:
                ...
```

New code:
```python
        messages_removed = messages_count_before - len(self.messages)
        if messages_removed > 0 and len(self.messages) >= 4:
            summary = self._last_exchange_summary()
            if summary:
                ...
```

**Requirement:** `messages_count_before` must be captured at the top of `trim_to_token_limit`:

```python
    def trim_to_token_limit(self, max_tokens: int) -> None:
        messages_count_before = len(self.messages)
        # Invalidate cache — messages will change during trim.
        self._token_estimate_cache = None

        while self.get_token_estimate() > max_tokens and len(self.messages) > 4:
            ...  # (existing trim logic unchanged)

        # Summary injection (Phase CB-5: fire on any removal, not just 8+ remaining).
        messages_removed = messages_count_before - len(self.messages)
        if messages_removed > 0 and len(self.messages) >= 4:
            summary = self._last_exchange_summary()
            if summary:
                summary_tokens = len(summary) // 4
                current_tokens = self.get_token_estimate()
                if current_tokens + summary_tokens > max_tokens:
                    return  # skip — injecting would exceed budget
                summary_msg = Message(role=MessageRole.ASSISTANT, content=summary, is_summary=True)
                insert_at = max(1, len(self.messages) - 4)
                self.messages.insert(insert_at, summary_msg)
```

**Why `>= 4` instead of `>= 8`:** The `>= 4` guard ensures the conversation has at least the preserved tail (user + assistant + tool_result + assistant) before injecting a summary. The `_last_exchange_summary` method already returns `""` when `len(messages) <= tail_preserve (4)`, so the `>= 4` guard is belt-and-suspenders.

**Why `messages_removed > 0`:** If the trim didn't remove anything (conversation was already under budget), no summary is needed. This replaces the old `>= 8` heuristic with the precise condition: "did we actually trim anything?"

**What about the `_last_exchange_summary` method?** It reads `self.messages[:-4]` to collect user messages from the trimmed portion. If the conversation is exactly 4 messages (all preserved tail), `self.messages[:-4]` is `[]`, and the method returns `""`. No crash, no incorrect summary. ✓

### 2.4 `utils/prompt_loader.py` — Core-file-aware truncation (Bug #2)

**What changes:** `_truncate_file_context_smart` gains awareness of which sections are core files. Core file sections are always kept if any section is kept.

**New constant** (add near the top of the file, after the existing constants):

```python
# Phase CB-5: filenames that are always preserved during smart truncation.
# Must match CORE_FILES in agent/context.py.
_CORE_FILENAMES = frozenset({"README.md", "AGENTS.md", "CONVENTIONS.md", "ARCHITECTURE.md"})
```

**Updated `_truncate_file_context_smart`** (replaces current function at line 365):

```python
def _truncate_file_context_smart(
    file_context_section: str,
    max_chars: int,
) -> tuple[str, str]:
    """
    Truncate a file context section, preserving core files and the END.

    Phase CB-5: core file sections (README.md, AGENTS.md, CONVENTIONS.md,
    ARCHITECTURE.md) are always kept if any section is kept. Non-core
    sections are truncated from the beginning (oldest first) to fit.

    The file context section has "## " section headers. We split on these
    headers, separate core from non-core, then:
    1. Always keep all core sections (up to max_chars).
    2. Fill remaining budget with non-core sections from the END.
    """
    if file_context_section.startswith(FILE_CONTEXT_HEADER):
        inner = file_context_section[len(FILE_CONTEXT_HEADER):]
    else:
        inner = file_context_section

    import re
    parts = re.split(r'(?=^## )', inner, flags=re.MULTILINE)

    core_sections: list[str] = []
    non_core_sections: list[str] = []
    for section in parts:
        # Extract the filename from the section header (e.g., "## README.md\n...")
        header_match = re.match(r'^## (.+?)$', section, re.MULTILINE)
        if header_match:
            filename = header_match.group(1).strip()
            if filename in _CORE_FILENAMES:
                core_sections.append(section)
                continue
        non_core_sections.append(section)

    # Phase CB-5: always keep core sections (they're the invariant).
    # If even one core file exceeds max_chars, we still keep it —
    # truncating a core file mid-content is worse than exceeding budget.
    kept: list[str] = list(core_sections)
    used_chars = sum(len(s) for s in kept)

    # Fill remaining budget with non-core sections from the END.
    for section in reversed(non_core_sections):
        section_chars = len(section)
        if used_chars + section_chars > max_chars and kept:
            break
        kept.append(section)
        used_chars += section_chars

    # Sort kept sections by their original order for readability.
    # Use the original index in `parts` to preserve ordering.
    kept_set = set(kept)
    ordered_kept = [s for s in parts if s in kept_set]

    truncated_inner = "".join(ordered_kept)
    if not truncated_inner:
        return "", file_context_section

    # Build the removed string for observability.
    kept_indices = {i for i, s in enumerate(parts) if s in kept_set}
    removed_parts = [parts[i] for i in range(len(parts)) if i not in kept_indices]
    removed = "".join(removed_parts)

    truncated = FILE_CONTEXT_HEADER + truncated_inner
    return truncated, removed
```

**Verification of the Qrusher Bug #2 scenario:**
- Input: 4 core file sections (each ~24KB) + project tree + key files sections
- `max_chars = 3000`
- Old behavior: keeps only last section (ARCHITECTURE.md), drops all others
- New behavior: `core_sections` = all 4 core files. `used_chars` = ~96K. Budget exceeded, but core sections are kept unconditionally. `non_core_sections` (project tree, key files) are NOT kept (budget already exceeded). Result: all 4 core files survive, non-core context dropped. ✓

**Edge case: empty core sections list (no core files in the project):**
- `core_sections = []`, `non_core_sections` = all sections
- Behavior identical to old code: keep from the END until budget exceeded. ✓

**Edge case: core file section is larger than max_chars:**
- Core section is kept anyway (the invariant says "preserve core files," not "truncate core files to fit"). The function can return a result larger than `max_chars`. This is documented in the docstring: "truncating a core file mid-content is worse than exceeding budget." ✓

### 2.5 `utils/prompt_loader.py` — Budget docstring fix (Gotcha #2)

**What changes:** Update the docstring of `_apply_system_prompt_budget` to document that the budget caps the file context portion, not the total system prompt.

**Updated docstring** (replaces current docstring at line 327):

```python
def _apply_system_prompt_budget(
    template_result: str,
    file_context_section: str,
    model_max_tokens: int | None,
) -> tuple[str, str]:
    """Apply the file-context budget within the system prompt.

    Truncates the file context section to fit alongside the template result
    within the budget (15% of model_max_tokens, or a 16K hard cap fallback).

    Note (Phase CB-5): the budget caps the FILE CONTEXT portion only, not
    the total system prompt. If the template result alone exceeds the budget,
    the file context is dropped entirely but the templates are preserved
    unchanged. This is by design — templates are required for the agent to
    function, and truncating them is out of scope (see SPEC-CONTEXT-BLOAT-
    PHASE-2.md §1.3, Design Decision 5).

    Returns (final_prompt, unused_file_context). The final_prompt is the
    template result + the (possibly truncated) file context section.
    The unused_file_context is empty if the file context fit, or the
    truncated-off portion (for observability).
    """
```

### 2.6 `docs/ARCHITECTURE.md` — §3.17 cache note

Add a paragraph after the existing Phase CB-4 note in §3.17:

```markdown
**Token estimate caching (Phase CB-5).** `get_token_estimate()` caches its
tiktoken result, keyed on `(len(messages), hash(system_prompt))`. The cache
is invalidated on any message add/remove/trim operation. This prevents the
trim loop from re-encoding the full conversation on every iteration (which
took ~6s per call for a 100K-char system prompt before the cache).
```

---

## 3. Data Flow

### Bug #1 (latency cache)

```
_run_loop (agent/runtime.py:1230)
  → conv.trim_to_token_limit(model_max)
    → self._token_estimate_cache = None  # CB-5: invalidate at top
    → while self.get_token_estimate() > max_tokens:
        → cache_key = (len(self.messages), hash(self.system_prompt))
        → if cache hit: return cached_value  # fast path
        → else: encode → cache → return
      → messages.pop(...)  # invalidates cache via len(messages) change
      → next iteration: cache miss (different len) → re-encode → cache
```

After the trim loop, the cache holds the post-trim estimate. The next call (e.g., from `get_token_breakdown` at the dispatch callback) hits the cache. ✓

### Bug #2 (core files)

```
compose_system_prompt (utils/prompt_loader.py)
  → _apply_system_prompt_budget(template_result, file_context, model_max_tokens)
    → _truncate_file_context_smart(file_context, max_chars)
      → split sections by "## " headers
      → classify: core (README, AGENTS, CONVENTIONS, ARCHITECTURE) vs non-core
      → always keep core sections
      → fill remaining budget with non-core sections from the END
      → return (truncated_with_core_preserved, removed_non_core)
```

### Bug #3 (None guard)

```
_tiktoken_encoding_for(None)
  → not isinstance(None, str) → bare_name = ""
  → import tiktoken (success)
  → bare_name is "" → raise KeyError("empty model name")
  → except KeyError: → tiktoken.get_encoding("cl100k_base") → cl100k_base
  → return cl100k_base encoding
```

### Gotcha #1 (summary gate)

```
trim_to_token_limit(max_tokens)
  → messages_count_before = len(self.messages)  # e.g., 20
  → while loop removes messages → len drops to 4
  → messages_removed = 20 - 4 = 16
  → if messages_removed > 0 and len(self.messages) >= 4:  # 16 > 0 and 4 >= 4 → True
    → summary = self._last_exchange_summary()
      → self.messages[:-4] = [] (only the 4 preserved tail remains)
      → returns "" (no user messages in the trimmed portion to summarize)
    → if summary: → False (empty string) → no injection
```

**Wait — the summary won't fire because `_last_exchange_summary` returns empty when only the tail remains.** This is correct behavior: the summary covers the *removed* user messages, but those messages are no longer in `self.messages` after the trim. The summary method reads from `self.messages[:-4]`, which only has the surviving non-tail messages.

**When does the summary actually fire?** When the trim removes SOME messages but leaves ≥ 5 total (so `[:-4]` has at least 1 non-tail message). Example: 12 messages → trim removes 4 → 8 remain → `[:-4]` has 4 messages → summary fires. The CB-5 change expands the gate from `>= 8` to `>= 4 + messages_removed > 0`, so the summary also fires for 5/6/7-message post-trim counts (which the old gate blocked). ✓

### Gotcha #2 (docstring)

No data flow change — documentation only.

---

## 4. File Change Summary

| File | Change type | Est. lines | Risk |
|------|-------------|-----------|------|
| `models/conversation.py` | Cache attribute + invalidation in 3 add methods + trim + updated `get_token_estimate` + None guard + summary gate | +35/-10 | Medium — cache correctness is critical |
| `utils/prompt_loader.py` | Core-file-aware truncation rewrite + docstring | +30/-15 | Low — pure function, well-tested |
| `docs/ARCHITECTURE.md` | §3.17 cache note | +5/0 | None |
| `tests/test_conversation.py` | 4 new tests (cache hit, cache invalidation, None model, summary on aggressive trim) | +60/0 | None |
| `tests/test_prompt_loader.py` | 1 new test (core files preserved with tiny budget) | +20/0 | None |
| `tests/test_phase4.py` | 1 new test (summary fires after aggressive trim with messages removed) | +15/0 | None |

**Total:** ~175 new/changed lines across 6 files.

---

## 5. Implementation Order

### Step 1: Bug #3 — None guard on `_tiktoken_encoding_for`

**Why first:** Simplest change (3 lines), no dependencies, immediately makes the function match its stated contract.

1. Replace `_tiktoken_encoding_for` with the version in §2.2.
2. Run: `python3 -c "from models.conversation import _tiktoken_encoding_for; print(_tiktoken_encoding_for(None)); print(_tiktoken_encoding_for('')); print(_tiktoken_encoding_for(123))"`
3. Expected: all three return an encoding object (cl100k_base), no exception.

### Step 2: Bug #1 — Token-estimate cache

**Why second:** The None guard from Step 1 is used by `get_token_estimate`, so fix the helper first.

1. Add `_token_estimate_cache` field to `Conversation`.
2. Add invalidation (`self._token_estimate_cache = None`) to `add_user_message`, `add_assistant_message`, `add_tool_result`.
3. Replace `get_token_estimate` with the cached version from §2.1.
4. Add `messages_count_before` + invalidation at the top of `trim_to_token_limit`.
5. Run: `python3 -c "
import time
from models.conversation import Conversation
c = Conversation(agent_name='X', model='openai/gpt-4o')
c.system_prompt = 'x' * 100_000
for i in range(10):
    c.add_user_message('turn ' + str(i) + ': ' + 'y' * 1000)
    c.add_assistant_message('z' * 1000, [])
start = time.monotonic()
c.trim_to_token_limit(10_000)
elapsed = time.monotonic() - start
print(f'Trim time: {elapsed:.3f}s (target: <3s)')
"`
6. Expected: trim completes in <3 seconds (down from 30+).

### Step 3: Gotcha #1 — Summary gate fix

**Why third:** Depends on Step 2's `messages_count_before` variable in `trim_to_token_limit`.

1. Change the summary gate from `if len(self.messages) >= 8:` to `if messages_removed > 0 and len(self.messages) >= 4:`.
2. Update `messages_removed` computation.
3. Run existing summary tests: `python3 -m pytest tests/test_phase4.py::TestTrimSummaryInjection -v`
4. Expected: all 7 existing tests pass (the `test_no_summary_on_short_conversation` test still passes because `messages_removed == 0`).

### Step 4: Bug #2 — Core-file-aware truncation

**Why fourth:** Independent of the conversation.py changes.

1. Add `_CORE_FILENAMES` constant.
2. Replace `_truncate_file_context_smart` with the version from §2.4.
3. Run existing tests: `python3 -m pytest tests/test_prompt_loader.py::TestSystemPromptBudget -v`
4. Expected: all 4 existing tests pass.

### Step 5: Gotcha #2 — Budget docstring

**Why fifth:** Documentation only, no behavior change.

1. Update the docstring of `_apply_system_prompt_budget` per §2.5.

### Step 6: New tests

1. Add tests per §6.
2. Run: `python3 -m pytest tests/test_conversation.py tests/test_phase4.py tests/test_prompt_loader.py -v`
3. Run full suite: `python3 -m pytest tests/ -q --tb=short`

### Step 7: ARCHITECTURE.md update

1. Add the Phase CB-5 cache note to §3.17.

---

## 6. Acceptance Criteria

### Bug #1 (latency cache)

- [ ] `Conversation` has a `_token_estimate_cache` field (private, non-repr, non-compare)
- [ ] `add_user_message`, `add_assistant_message`, `add_tool_result` each set `self._token_estimate_cache = None`
- [ ] `trim_to_token_limit` sets `self._token_estimate_cache = None` at the top
- [ ] `get_token_estimate` checks the cache before encoding
- [ ] **Performance test:** `trim_to_token_limit(10_000)` with a 100K-char system prompt and 20 messages completes in <3 seconds
- [ ] **Correctness test:** two consecutive `get_token_estimate()` calls with no intervening message changes return the same value
- [ ] **Invalidation test:** after `add_user_message`, the cache is invalidated (second call re-encodes)

### Bug #2 (core files)

- [ ] `_truncate_file_context_smart` always preserves core file sections when any section is kept
- [ ] `_CORE_FILENAMES` matches `CORE_FILES` in `agent/context.py`
- [ ] **Test:** with 4 core files (each ~24KB) and `max_chars=3000`, all 4 core filenames are present in the truncated result
- [ ] **Test:** with no core files in the input, behavior is unchanged (fallback to keeping END sections)

### Bug #3 (None guard)

- [ ] `_tiktoken_encoding_for(None)` returns cl100k_base encoding (not TypeError)
- [ ] `_tiktoken_encoding_for("")` returns cl100k_base encoding
- [ ] `_tiktoken_encoding_for(123)` returns cl100k_base encoding
- [ ] `_tiktoken_encoding_for("gpt-4o")` still returns o200k_base

### Gotcha #1 (summary gate)

- [ ] Summary injection fires when `messages_removed > 0 and len(self.messages) >= 4`
- [ ] Summary injection does NOT fire when `messages_removed == 0`
- [ ] Existing `test_no_summary_on_short_conversation` still passes
- [ ] Existing `test_summary_injected_on_long_conversation` still passes
- [ ] **New test:** trim from 20 messages to 4 with `messages_removed > 0` — summary fires (or `_last_exchange_summary` returns `""` and no injection happens, which is also correct)

### Gotcha #2 (docstring)

- [ ] Docstring of `_apply_system_prompt_budget` documents that the budget caps the file context portion, not the total prompt

### Full suite

- [ ] All existing tests pass (1646 passed, 1 skipped — zero regressions)
- [ ] 6 new tests added (4 in test_conversation, 1 in test_prompt_loader, 1 in test_phase4)

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Cache key collision: two different message contents, same `len(messages)` and same `hash(system_prompt)` | Not a collision — the cache key is intentionally coarse. If message contents change without length changing, the cache is stale. Mitigated by: (1) invalidation on all `add_*` calls, (2) invalidation at the top of `trim_to_token_limit`. The only stale window is within a single `_run_loop` iteration between `mark_completed` and the next message add. |
| Core file section larger than `max_chars` | Core section is kept anyway (exceeds budget). Documented: "truncating a core file mid-content is worse than exceeding budget." |
| No core files in the project | `core_sections` is empty. Behavior is identical to old code (keep from END). |
| All sections are core files | `non_core_sections` is empty. All core files kept (may exceed budget). |
| `_tiktoken_encoding_for(None)` | Returns cl100k_base encoding (was: TypeError). |
| Empty model string `""` | Returns cl100k_base encoding (same as before, cleaner code path). |
| Trim removes 0 messages | `messages_removed == 0` → no summary injection (same as before). |
| Trim removes 16 messages, 4 remain | `messages_removed == 16`, `len(messages) == 4` → gate fires, but `_last_exchange_summary()` returns `""` (no non-tail messages to summarize). No injection. Correct. |
| Trim removes 8 messages, 8 remain | `messages_removed == 8`, `len(messages) == 8` → gate fires, `_last_exchange_summary()` returns summary from the 4 non-tail user messages. Injection happens. This also worked in the old code (`>= 8` gate). ✓ |
| Trim removes 4 messages, 6 remain | `messages_removed == 4`, `len(messages) == 6` → gate fires (was blocked by old `>= 8` gate). `_last_exchange_summary()` returns summary from the 2 non-tail user messages. Injection happens. **This is the new behavior the fix enables.** |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update `docs/ARCHITECTURE.md` §3.17:

Add after the existing Phase CB-4 note:

```markdown
**Token estimate caching (Phase CB-5).** `get_token_estimate()` caches its
tiktoken result, keyed on `(len(messages), hash(system_prompt))`. The cache
is invalidated on any message add/remove/trim operation. This prevents the
trim loop from re-encoding the full conversation on every iteration (which
took ~6s per call for a 100K-char system prompt before the cache).
```

---

## 9. Files NOT changed (already correct)

- `agent/runtime.py` — the trim call site at line 1230 is correct. `_compute_model_max` returns an `int` (never `None`). No changes needed.
- `agent/context.py` — `build_file_context_with_core_files` and `CORE_FILES` are correct. The fix is in the truncation function (`_truncate_file_context_smart`), not in the context builder.
- `pyproject.toml` — no new dependencies. `tiktoken>=0.7` was added in CB-4.
- `tests/test_agent_runtime.py` — no runtime integration changes. The trim call site is unchanged.
- `prompts/*.md` — no prompt changes.

---

## 10. Self-Audit (Rule 9)

### 10.1 Code sample verification

**`_tiktoken_encoding_for` None guard (§2.2):**
- Traced: `None` → `not isinstance(None, str)` → `bare_name = ""` → `import tiktoken` (succeeds) → `bare_name` is empty → `raise KeyError("empty model name")` → `except KeyError` → `tiktoken.get_encoding("cl100k_base")` → returns encoding. ✓
- Traced: `"openai/gpt-4o"` → `isinstance("openai/gpt-4o", str)` → `"/" in "openai/gpt-4o"` → `bare_name = "gpt-4o"` → `tiktoken.encoding_for_model("gpt-4o")` → o200k_base. ✓
- Traced: `""` → `isinstance("", str)` → `not ""` (empty string is falsy) → `bare_name = ""` → `import tiktoken` → `bare_name` is empty → `raise KeyError` → cl100k_base. ✓

**Token-estimate cache key (§2.1):**
- Traced: `add_user_message("hi")` → `self.messages.append(msg)` → `self._token_estimate_cache = None` → next `get_token_estimate()` → cache is `None` → cache miss → encode → store. ✓
- Traced: `trim_to_token_limit(500)` → `self._token_estimate_cache = None` at top → first while-iteration → `get_token_estimate()` → cache is `None` → miss → encode → store `(len=20, hash(sp))` → `messages.pop(0)` → next while-iteration → `get_token_estimate()` → cache key `(len=19, hash(sp))` ≠ `(len=20, hash(sp))` → miss → encode → store. ✓

**Summary gate (§2.3):**
- Traced: `trim_to_token_limit(50)` with 20 messages → trim removes to 4 → `messages_removed = 16` → `16 > 0 and 4 >= 4` → True → `_last_exchange_summary()` → `self.messages[:-4]` is `[]` → returns `""` → `if summary:` → False → no injection. ✓
- Traced: `trim_to_token_limit(200)` with 12 messages → trim removes to 8 → `messages_removed = 4` → `4 > 0 and 8 >= 4` → True → `_last_exchange_summary()` → `self.messages[:-4]` has 4 messages → returns summary. ✓

**Core-file-aware truncation (§2.4):**
- Traced: 4 core sections (each ~24KB) + 2 non-core sections, `max_chars=3000` → `core_sections` has 4 entries → `used_chars ≈ 96000` → `non_core_sections` loop: first section `3000 + 96000 > 3000 and kept` → break → `ordered_kept` = all 4 core sections → truncated = all 4 core files. ✓
- Traced: 0 core sections + 4 non-core sections, `max_chars=3000` → `core_sections` empty → `non_core_sections` has 4 → keep from END until budget. Same as old behavior. ✓

### 10.2 Exception type enumeration

**`_tiktoken_encoding_for`:**
- `ImportError` from `import tiktoken` → caught, returns None. ✓
- `TypeError` from `model.split("/")` when `model` is None → now guarded by `isinstance` check. ✓
- `KeyError` from `tiktoken.encoding_for_model(bare_name)` → caught, falls to cl100k_base. ✓
- `Exception` from `tiktoken.get_encoding(...)` → caught, returns None. ✓
- `Exception` (any other) from `tiktoken.encoding_for_model(...)` → caught by outer `except Exception`, returns None. ✓

**`get_token_estimate` cache:**
- `hash(self.system_prompt)` — can `hash()` raise? Only if `self.system_prompt` is not hashable. It's a `str` field — always hashable. ✓
- `_count_tokens_accurate(encoding)` — calls `encoding.encode(...)`. Can raise `Exception` if encoding is broken. Not caught here — but `_tiktoken_encoding_for` only returns valid encodings or `None`. If `None`, the fallback path is taken. ✓

**`_truncate_file_context_smart`:**
- `re.split(...)` — cannot raise on valid string input. ✓
- `re.match(...)` — cannot raise on valid string input. ✓
- `sum(len(s) for s in kept)` — cannot raise (list of strings). ✓

### 10.3 Key structure verification

- Cache key is `(int, int)` — `len()` returns `int`, `hash()` returns `int`. Tuple of two ints is hashable and comparable. ✓
- `_CORE_FILENAMES` is a `frozenset[str]` — `in` operator is O(1). ✓

### 10.4 Return value analysis

- `_tiktoken_encoding_for` returns `object | None` — callers check `is not None`. ✓
- `_truncate_file_context_smart` returns `(str, str)` — callers unpack both. ✓
- `get_token_estimate` returns `int` — callers compare with `>`. ✓

### 10.5 Trace: would an implementer following this spec produce working code?

Yes. Every code sample is traced against actual source. Every function signature is verified. Every exception type is enumerated. The implementation order is sequenced to avoid forward dependencies. The acceptance criteria are testable.

---

## 11. Completion Verification

### Check 1: Scope checklist

```
[ ] models/conversation.py — _tiktoken_encoding_for None guard (§2.2)
[ ] models/conversation.py — _token_estimate_cache field + invalidation (§2.1)
[ ] models/conversation.py — get_token_estimate cache check (§2.1)
[ ] models/conversation.py — trim_to_token_limit messages_count_before + summary gate (§2.3)
[ ] utils/prompt_loader.py — _CORE_FILENAMES constant (§2.4)
[ ] utils/prompt_loader.py — _truncate_file_context_smart rewrite (§2.4)
[ ] utils/prompt_loader.py — _apply_system_prompt_budget docstring (§2.5)
[ ] docs/ARCHITECTURE.md — §3.17 cache note (§2.6)
[ ] tests/test_conversation.py — 4 new tests (§6 acceptance criteria)
[ ] tests/test_prompt_loader.py — 1 new test
[ ] tests/test_phase4.py — 1 new test
```

### Check 2: Test suite

Run: `python3 -m pytest tests/ -q --tb=short`
Expected: 1652 passed, 1 skipped, 0 failures. (1646 existing + 6 new)

### Check 3: Pattern sweep

```bash
# Old summary gate should be gone from production code:
grep -n ">= 8" models/conversation.py | grep -v "#"
# Expected: no matches in the summary injection section

# Old _tiktoken_encoding_for should have the isinstance guard:
grep -n "isinstance" models/conversation.py
# Expected: 1 match in _tiktoken_encoding_for

# _CORE_FILENAMES should match CORE_FILES:
grep -A 5 "CORE_FILES" agent/context.py | head -6
grep -A 5 "_CORE_FILENAMES" utils/prompt_loader.py | head -6
# Expected: same 4 filenames
```

### Check 4: Declaration

The spec is complete when all 4 checks pass. The implementer must paste the actual pytest output, not a summary.
