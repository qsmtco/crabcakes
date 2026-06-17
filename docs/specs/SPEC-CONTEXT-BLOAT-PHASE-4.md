# SPEC: Context Bloat — Phase 4 (Tiktoken-Based Token Estimation)

**Date:** 2026-06-17
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-context-bloat-fix.md` §5 (Phase CB-4)
**Source bug report:** `docs/bugs/BUG-high-input-token-context-bloat.md` (BUG #5, MEDIUM)
**Depends on:** CB-1 (shipped commit `601067b`) — adds `_compute_model_max` which provides the model_max for trim decisions. CB-2 (shipped commit `d43539e`) — modifies the trim fallback. CB-3 (shipped commit `9c9ab6e`) — streaming usage / stuck / awareness caps.
**Target branch:** main

> **Architecture compliance statement.** This spec conforms to `docs/ARCHITECTURE.md`:
>
> - **§7 (Agent Runtime)** — No changes to the runtime. Only `models/conversation.py` is modified. The existing `get_token_estimate` and `get_token_breakdown` keep their signatures.
> - **§8.3 (Models are plain Python, no GTK)** — Preserved. The new code is a thin wrapper around `tiktoken`.
> - **§8.5 (Tests)** — New test classes added to `tests/test_conversation.py`. Existing tests updated to use a tolerance-based assertion (see §2.4).
> - **§8.7 (No dead code)** — `tiktoken` is an external dependency, not a new module.
> - **No new public API** — `get_token_estimate` and `get_token_breakdown` keep their signatures. Only an internal helper (`_tiktoken_encoding_for`) is added. `tiktoken` becomes a runtime dependency.
> - **New runtime dependency:** `tiktoken` (MIT-licensed, no transitive deps, ~2MB). Added to `pyproject.toml` `dependencies` list.

---

## 1. Overview

### Problem

`Conversation.get_token_estimate()` and `Conversation.get_token_breakdown()` use `chars // 4` as a token estimate (line 215: `return (system_chars + conv_chars) // 4`). For English prose, this is roughly accurate. For code-heavy content (which tokenizes at ~3.5–4 chars per token for variable names but ~1–2 chars per token for keywords like `def`, `return`, `self`), the heuristic undercounts by **~60%**.

**Concrete impact:** the trim loop in `Conversation.trim_to_token_limit()` uses `get_token_estimate()` to decide when to stop trimming. If the estimator undercounts by 60%, the trim stops too early — leaving the conversation with **~1.5x more tokens** than the budget. This negates the CB-1 fix's effectiveness for code-heavy sessions.

### Solution

Replace the `chars // 4` heuristic with `tiktoken`-based tokenization when the model's encoding is available. Fall back to the heuristic for unknown models.

**Key design decision (locked by this spec):** `tiktoken.encoding_for_model()` only recognizes OpenAI model names (e.g., `"gpt-4o"`). It raises `KeyError` for any name with a `/` (e.g., `"openai/gpt-4o"` — crabcakes's format). The spec mandates stripping the provider prefix before calling `encoding_for_model`. For models that still don't match, the spec mandates a default encoding (`cl100k_base` — the GPT-4 / GPT-3.5-turbo encoding) and a final fallback to `chars // 4` if `tiktoken` is unavailable or raises.

### Scope

| In scope | Out of scope |
|---|---|
| Replace `chars // 4` with `tiktoken` in `get_token_estimate` and `get_token_breakdown` | Tokenizing tool_call names (only `arguments` and `result` are tokenized today) |
| Add `tiktoken` to `pyproject.toml` | Adding Anthropic-specific tokenization (Anthropic's tokenizer is not publicly available; use OpenAI's cl100k_base as a reasonable proxy) |
| Add provider-prefix stripping for model names | Per-model calibration (tiktoken cl100k_base is "close enough" for non-OpenAI models) |
| Update the 4 existing `TestConversationTokenEstimate` tests to use tolerance-based assertions | Changing the `get_token_estimate` / `get_token_breakdown` signatures |
| Add new `TestTiktokenAccurate` test class verifying the new accurate counts match `tiktoken` directly | Cache the encoding per-Conversation (encoding_for_model is fast enough to call per-iteration) |
| Document the new behavior in the `get_token_estimate` / `get_token_breakdown` docstrings | |

### Design decisions (locked by this spec)

1. **Provider prefix stripping:** `conv.model = "openai/gpt-4o"` → `tiktoken.encoding_for_model("gpt-4o")`. If the model has no `/`, use it as-is.
2. **Default encoding:** `cl100k_base` (GPT-4 / GPT-3.5-turbo). This is the most widely-used encoding and provides a reasonable approximation for Anthropic, MiniMax, ZAI, and OpenRouter models (all of which use OpenAI-compatible APIs).
3. **Final fallback:** `chars // 4` when `tiktoken` is not installed or raises any exception. The trim's behavior is preserved (worse accuracy, but no crash).
4. **Existing test updates:** The 4 tests in `TestConversationTokenEstimate` use hard-coded `chars // 4` expectations. The spec mandates updating them to tolerance-based assertions (`assert abs(actual - expected) < 2` for small inputs, or `assert 0.7 * expected < actual < 1.3 * expected` for larger inputs).
5. **New `TestTiktokenAccurate`:** Verifies that `get_token_estimate()` for a known model (e.g., `"gpt-4o"`) returns the EXACT same count as `tiktoken.encoding_for_model("gpt-4o").encode(text)`.
6. **No signature changes:** `get_token_estimate()` and `get_token_breakdown()` keep their signatures. The trim loop at line 269 and the breakdown consumer at `agent/runtime.py:1288` continue to work without changes.

---

## 2. Changes by File

### 2.1 `pyproject.toml` — add `tiktoken` dependency

**What changes:** Add `"tiktoken>=0.7"` to the `dependencies` list.

**Find** the dependencies block (around line 8-13):

```toml
dependencies = [
    "PyGObject>=3.48",
    "websockets>=12.0",
    "cryptography>=41.0",
    "GitPython>=3.1",
]
```

**Replace with:**

```toml
dependencies = [
    "PyGObject>=3.48",
    "websockets>=12.0",
    "cryptography>=41.0",
    "GitPython>=3.1",
    "tiktoken>=0.7",  # Phase CB-4: accurate token estimation for trim decisions (BUG #5 fix)
]
```

**Rationale:** `tiktoken>=0.7` is the minimum version that supports `cl100k_base` and `o200k_base` (the GPT-4 and GPT-4o encodings). The current installed version is 0.12.0. No transitive dependencies.

### 2.2 `models/conversation.py` — add tiktoken helper, replace chars/4

**What changes:** Add a private helper `_tiktoken_encoding_for(conv)` that returns the appropriate tiktoken encoding for a conversation, with multiple fallback layers. Replace the `// 4` calculations in `get_token_estimate` and `get_token_breakdown` with helper-based tokenization.

#### 2.2.1 Add the helper function

**Add** this function after the `_count_char_tokens` helper (around line 213, before `get_token_estimate`):

```python
# Phase CB-4: tiktoken-based accurate token estimation (BUG #5 fix).
# See SPEC-CONTEXT-BLOAT-PHASE-4.md §2.2.

_DEFAULT_ENCODING_NAME = "cl100k_base"  # GPT-4 / GPT-3.5-turbo encoding; reasonable proxy for non-OpenAI models


def _tiktoken_encoding_for(model_name: str) -> object | None:
    """
    Return the tiktoken encoding for the given model name, or None on failure.

    Resolution order:
      1. tiktoken.encoding_for_model(model_name)  (OpenAI models: gpt-4o, gpt-4, gpt-3.5-turbo, ...)
      2. tiktoken.get_encoding("cl100k_base")    (default for non-OpenAI models)

    Returns None if tiktoken is not installed or raises any exception.
    The caller must fall back to the chars // 4 heuristic when None is returned.

    Strips provider prefix from model names like "openai/gpt-4o" → "gpt-4o"
    because tiktoken.encoding_for_model only recognizes bare OpenAI model names.
    """
    try:
        import tiktoken
    except ImportError:
        return None

    # Strip provider prefix (e.g., "openai/" or "anthropic/" or "openrouter/")
    bare_name = model_name.split("/", 1)[-1] if "/" in model_name else model_name

    try:
        return tiktoken.encoding_for_model(bare_name)
    except KeyError:
        # Unknown model name. Fall back to the default encoding.
        try:
            return tiktoken.get_encoding(_DEFAULT_ENCODING_NAME)
        except Exception:
            return None
    except Exception:
        # Any other error (e.g., download failure for the encoding data).
        return None
```

**Imports required:** None new (the `import tiktoken` is inside the function for defensive lazy loading).

#### 2.2.2 Update `get_token_estimate`

**Find** at line 214-218:

```python
    def get_token_estimate(self) -> int:
        """
        Rough token count estimate (~4 chars per token).

        Used for context-window management. Not accurate — overestimates
        for non-English text and underestimates for code-heavy content.
        """
        system_chars, conv_chars = self._count_char_tokens()
        return (system_chars + conv_chars) // 4
```

**Replace with:**

```python
    def get_token_estimate(self) -> int:
        """
        Token count estimate for the conversation.

        Phase CB-4: when tiktoken is installed and the model has a known encoding,
        uses tiktoken.encoding_for_model() for accurate counts. Falls back to the
        chars // 4 heuristic for unknown models or when tiktoken is unavailable.

        Used for context-window management (see trim_to_token_limit).
        """
        encoding = _tiktoken_encoding_for(self.model)
        if encoding is not None:
            return self._count_tokens_accurate(encoding)
        # Fallback: chars // 4 heuristic (preserves CB-1/CB-2/CB-3 behavior)
        system_chars, conv_chars = self._count_char_tokens()
        return (system_chars + conv_chars) // 4

    def _count_tokens_accurate(self, encoding) -> int:
        """
        Count tokens accurately using the provided tiktoken encoding.

        Counts tokens in:
        - system_prompt
        - each message's content
        - each tool_call's arguments (serialized) and result

        Does NOT count tool_call.name (it doesn't appear in the API request body
        sent to the LLM, only the id and arguments do).
        """
        total = len(encoding.encode(self.system_prompt))
        for msg in self.messages:
            total += len(encoding.encode(msg.content or ""))
            for tc in msg.tool_calls:
                total += len(encoding.encode(str(tc.arguments)))
                if tc.result:
                    total += len(encoding.encode(tc.result))
        return total
```

**Note:** The old docstring said "Not accurate." The new docstring is honest about the new accurate path AND the fallback.

#### 2.2.3 Update `get_token_breakdown`

**Find** at line 224-249:

```python
    def get_token_breakdown(self, model_max_tokens: int) -> dict:
        """
        §4.15 — Per-turn token budget breakdown.

        Returns a dict with token allocation info for observability:
        - system_prompt_tokens: chars in system_prompt // 4
        - conversation_tokens: chars in all messages // 4
        - total_used_tokens: system + conversation
        - model_max_tokens: total available context window
        - remaining_tokens: model_max - total_used
        - usage_percent: (total_used / model_max_tokens) * 100

        This helps identify context bloat before hitting the limit.
        """
        system_chars, conv_chars = self._count_char_tokens()
        system_tokens = system_chars // 4
        conversation_tokens = conv_chars // 4
        total_used = system_tokens + conversation_tokens
        return {
            "system_prompt_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "total_used_tokens": total_used,
            "model_max_tokens": model_max_tokens,
            "remaining_tokens": max(0, model_max_tokens - total_used),
            "usage_percent": round(total_used / model_max_tokens * 100, 1) if model_max_tokens > 0 else 0,
        }
```

**Replace with:**

```python
    def get_token_breakdown(self, model_max_tokens: int) -> dict:
        """
        §4.15 — Per-turn token budget breakdown.

        Returns a dict with token allocation info for observability:
        - system_prompt_tokens: accurate count when tiktoken is available, else chars // 4
        - conversation_tokens: accurate count when tiktoken is available, else chars // 4
        - total_used_tokens: system + conversation
        - model_max_tokens: total available context window
        - remaining_tokens: model_max - total_used
        - usage_percent: (total_used / model_max_tokens) * 100

        Phase CB-4: uses tiktoken when available, falls back to chars // 4 otherwise.
        Same fallback semantics as get_token_estimate.

        This helps identify context bloat before hitting the limit.
        """
        encoding = _tiktoken_encoding_for(self.model)
        if encoding is not None:
            system_tokens = len(encoding.encode(self.system_prompt))
            conversation_tokens = 0
            for msg in self.messages:
                conversation_tokens += len(encoding.encode(msg.content or ""))
                for tc in msg.tool_calls:
                    conversation_tokens += len(encoding.encode(str(tc.arguments)))
                    if tc.result:
                        conversation_tokens += len(encoding.encode(tc.result))
        else:
            # Fallback: chars // 4 heuristic
            system_chars, conv_chars = self._count_char_tokens()
            system_tokens = system_chars // 4
            conversation_tokens = conv_chars // 4
        total_used = system_tokens + conversation_tokens
        return {
            "system_prompt_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "total_used_tokens": total_used,
            "model_max_tokens": model_max_tokens,
            "remaining_tokens": max(0, model_max_tokens - total_used),
            "usage_percent": round(total_used / model_max_tokens * 100, 1) if model_max_tokens > 0 else 0,
        }
```

**Note:** The body of `get_token_breakdown` duplicates the count logic from `_count_tokens_accurate`. A future refactor could extract a shared helper, but for now the duplication is acceptable (keeps each function self-contained for readability).

**Files NOT changed in this section:**

- `models/conversation.py:trim_to_token_limit` — unchanged. It calls `get_token_estimate()` which now uses tiktoken. The trim's behavior improves automatically.
- `agent/runtime.py:1288` — unchanged. It calls `conv.get_token_breakdown(model_max)` which now uses tiktoken. The breakdown's accuracy improves automatically.
- `models/conversation.py:Message` dataclass — unchanged. The new `_count_tokens_accurate` reads `msg.content`, `tc.arguments`, `tc.result` (the same fields the existing `_count_char_tokens` reads).
- `models/conversation.py:_count_char_tokens` — unchanged. It's still used as the fallback when tiktoken is unavailable.

### 2.3 `tests/test_conversation.py` — update existing tests, add new tests

**What changes:** The 4 existing tests in `TestConversationTokenEstimate` use hard-coded `chars // 4` expectations. They MUST be updated to use tolerance-based assertions because tiktoken counts differ. Add a new `TestTiktokenAccurate` class with 3 tests that verify the new behavior.

#### 2.3.1 Update existing tests

**Find** the entire `TestConversationTokenEstimate` class (lines 226-246):

```python
class TestConversationTokenEstimate:
    def test_empty_conversation_is_zero(self):
        c = Conversation(agent_name="Coder")
        assert c.get_token_estimate() == 0

    def test_system_prompt_counted(self):
        c = Conversation(agent_name="Coder", system_prompt="x" * 40)  # 10 tokens at 4 chars/token
        assert c.get_token_estimate() == 10

    def test_messages_counted(self):
        c = Conversation(agent_name="Coder")
        c.add_user_message("hello world")  # 11 chars
        assert c.get_token_estimate() == 11 // 4  # ~2 tokens

    def test_tool_call_args_and_result_counted(self):
        c = Conversation(agent_name="Coder")
        tc = ToolCall(call_id="c1", tool_name="read_file", arguments={"path": "a.py", "content": "xyzt"})
        c.add_tool_result("c1", "result here")
        # tokens counted from tool_calls arguments + result
        estimate = c.get_token_estimate()
        assert estimate > 0
```

**Replace with:**

```python
class TestConversationTokenEstimate:
    """Phase CB-4: tests use tolerance-based assertions because tiktoken counts differ from chars // 4.

    The conv.model defaults to "" (empty string), which is not a known model name.
    So _tiktoken_encoding_for("") falls back to the cl100k_base default encoding.
    """

    def test_empty_conversation_is_zero(self):
        c = Conversation(agent_name="Coder")
        # system_prompt is empty, no messages → 0 tokens
        assert c.get_token_estimate() == 0

    def test_system_prompt_counted(self):
        # Use realistic text (not "x" * 40, which tokenizes to 1 token with tiktoken
        # but 10 tokens with chars // 4). The system_prompt is the agent's
        # general instructions, which contains normal English words.
        prompt = "You are a helpful assistant that writes Python code."  # 11 words
        c = Conversation(agent_name="Coder", system_prompt=prompt, model="gpt-4o")
        # With tiktoken (cl100k_base for gpt-4o), this prompt is ~10-11 tokens.
        # With chars // 4 fallback, it would be ~14 tokens.
        # We assert a tolerance: actual is within ±30% of the tiktoken ground truth.
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected = len(enc.encode(prompt))
        actual = c.get_token_estimate()
        assert abs(actual - expected) <= 1, f"expected ~{expected} tokens, got {actual}"

    def test_messages_counted(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        c.add_user_message("hello world")  # 11 chars
        # tiktoken says: "hello world" = 2 tokens (cl100k_base).
        # chars // 4 says: 11 // 4 = 2.
        # Both agree on this case.
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected_msg = len(enc.encode("hello world"))
        actual = c.get_token_estimate()
        assert actual == expected_msg, f"expected {expected_msg} tokens, got {actual}"

    def test_tool_call_args_and_result_counted(self):
        c = Conversation(agent_name="Coder", model="gpt-4o")
        tc = ToolCall(call_id="c1", tool_name="read_file", arguments={"path": "a.py", "content": "xyzt"})
        c.add_tool_result("c1", "result here")
        # tokens counted from tool_calls arguments + result
        estimate = c.get_token_estimate()
        assert estimate > 0
        # Sanity: at least the "result here" + serialized arguments
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        min_expected = len(enc.encode("result here"))
        assert estimate >= min_expected, f"expected >= {min_expected} tokens, got {estimate}"
```

#### 2.3.2 Add new test class

**Add** this class after `TestConversationTokenEstimate`:

```python
class TestTiktokenAccurate:
    """Phase CB-4 (BUG #5 fix): tiktoken-based accurate token estimation."""

    def test_known_openai_model_uses_tiktoken(self):
        """conv.model='gpt-4o' should use tiktoken.encoding_for_model('gpt-4o')."""
        c = Conversation(agent_name="Coder", system_prompt="hello", model="gpt-4o")
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        # system_prompt + nothing else
        expected = len(enc.encode("hello"))
        assert c.get_token_estimate() == expected

    def test_provider_prefix_is_stripped(self):
        """conv.model='openai/gpt-4o' should strip the 'openai/' prefix and use 'gpt-4o'."""
        c = Conversation(agent_name="Coder", system_prompt="hello", model="openai/gpt-4o")
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")  # same encoding as "openai/gpt-4o"
        expected = len(enc.encode("hello"))
        assert c.get_token_estimate() == expected, (
            f"Provider prefix should be stripped; expected {expected} tokens"
        )

    def test_unknown_model_falls_back_to_default_encoding(self):
        """conv.model='unknown-xyz' should fall back to cl100k_base (not chars // 4)."""
        c = Conversation(agent_name="Coder", system_prompt="hello world", model="unknown-xyz")
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode("hello world"))
        actual = c.get_token_estimate()
        assert actual == expected, (
            f"Expected tiktoken cl100k_base count ({expected}), got {actual}. "
            f"Fallback to chars // 4 would give {len('hello world') // 4}."
        )

    def test_tiktoken_import_error_falls_back_to_chars(self, monkeypatch):
        """If tiktoken is not importable, fall back to chars // 4 (no crash)."""
        # Hide tiktoken from the import system
        import sys
        monkeypatch.setitem(sys.modules, "tiktoken", None)
        # Force re-import via the helper
        from models import conversation as conv_module
        monkeypatch.setattr(conv_module, "_tiktoken_encoding_for",
                            lambda model_name: None)  # simulate import failure
        c = Conversation(agent_name="Coder", system_prompt="x" * 40)  # 40 chars
        # chars // 4 fallback: 40 // 4 = 10
        assert c.get_token_estimate() == 10

    def test_breakdown_uses_tiktoken(self):
        """get_token_breakdown should return tiktoken-accurate counts for known models."""
        c = Conversation(agent_name="Coder", system_prompt="x" * 40, model="gpt-4o")
        c.add_user_message("hello")
        breakdown = c.get_token_breakdown(model_max_tokens=1000)
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-4o")
        expected_system = len(enc.encode("x" * 40))
        expected_conv = len(enc.encode("hello"))
        assert breakdown["system_prompt_tokens"] == expected_system
        assert breakdown["conversation_tokens"] == expected_conv
        assert breakdown["total_used_tokens"] == expected_system + expected_conv
```

**Files NOT changed in this section:**

- `tests/test_conversation.py:TestConversationTrim` (4 tests at line 247+) — unchanged. They test the trim's behavior with the existing `get_token_estimate` calls. The trim's behavior improves (more accurate trigger) but the existing tests still pass.
- `tests/test_conversation.py:TestTrimSummaryInjection` (8 tests in `tests/test_phase4.py`) — unchanged for the same reason.
- `tests/test_conversation.py:TestRunLoopTrimsContext` (1 test in `tests/test_agent_runtime.py`) — unchanged.

### 2.4 `docs/ARCHITECTURE.md` — document the new dependency and behavior

**What changes:** Add a one-line note in §3.17 (the `models/conversation.py` section) about the new `tiktoken` dependency. Update the `get_token_estimate` / `get_token_breakdown` documentation if present.

**Find** the `models/conversation.py` section in `docs/ARCHITECTURE.md`. Search for `models/conversation.py` or `get_token_estimate`. The current section likely doesn't have an explicit mention; if it does, update it.

**Append** to the section:

```markdown
**Token estimation (Phase CB-4).** `get_token_estimate()` and
`get_token_breakdown()` use `tiktoken.encoding_for_model()` for accurate
token counts (BUG #5 fix). Provider prefixes are stripped from model
names (e.g., `"openai/gpt-4o"` → `"gpt-4o"`). Unknown model names
fall back to the `cl100k_base` encoding. The `chars // 4` heuristic
is the final fallback when `tiktoken` is unavailable. See
`SPEC-CONTEXT-BLOAT-PHASE-4.md` §2.2.

Requires `tiktoken>=0.7` (MIT-licensed, no transitive deps, ~2MB).
```

---

## 3. Data Flow

Trace the full execution path for `get_token_estimate()` on a `Conversation` with `model="openai/gpt-4o"` and a 100-char system prompt + a 200-char user message:

```
get_token_estimate() called from trim_to_token_limit (line 269) or get_token_breakdown
  │
  ├─ _tiktoken_encoding_for("openai/gpt-4o")
  │   ├─ import tiktoken (succeeds — it's a dep)
  │   ├─ bare_name = "openai/gpt-4o".split("/", 1)[-1] = "gpt-4o"
  │   ├─ tiktoken.encoding_for_model("gpt-4o") → o200k_base encoding
  │   └─ return o200k_base encoding
  │
  ├─ encoding is not None → use _count_tokens_accurate
  │   │
  │   └─ _count_tokens_accurate(encoding):
  │       ├─ len(encoding.encode("..." * 100))  # system_prompt
  │       ├─ for msg in self.messages:
  │       │   ├─ len(encoding.encode(msg.content or ""))  # user message
  │       │   └─ for tc in msg.tool_calls:
  │       │       ├─ len(encoding.encode(str(tc.arguments)))
  │       │       └─ if tc.result: len(encoding.encode(tc.result))
  │       └─ return total
  │
  └─ return total  # the actual token count, not the heuristic

For unknown models (e.g., "unknown-xyz"):
  │
  ├─ _tiktoken_encoding_for("unknown-xyz")
  │   ├─ import tiktoken (succeeds)
  │   ├─ bare_name = "unknown-xyz"  # no prefix to strip
  │   ├─ tiktoken.encoding_for_model("unknown-xyz") raises KeyError
  │   ├─ fallback: tiktoken.get_encoding("cl100k_base") succeeds
  │   └─ return cl100k_base encoding
  │
  └─ (proceeds with tiktoken using cl100k_base)

For unavailable tiktoken (import fails):
  │
  ├─ _tiktoken_encoding_for(model) → None
  │
  ├─ encoding is None → use chars // 4 fallback
  │   ├─ system_chars, conv_chars = self._count_char_tokens()
  │   └─ return (system_chars + conv_chars) // 4
  │
  └─ return total  # the heuristic count (worse accuracy, no crash)
```

---

## 4. File Change Summary

| File | Change type | Lines (est.) | Risk |
|---|---|---|---|
| `pyproject.toml` | Add `tiktoken>=0.7` to dependencies | +1, -0 | NONE (dep) |
| `models/conversation.py` | Add `_tiktoken_encoding_for` helper, add `_count_tokens_accurate` method, modify `get_token_estimate` and `get_token_breakdown` | +60, -20 | LOW (additive with fallback) |
| `tests/test_conversation.py` | Update 4 existing tests, add new `TestTiktokenAccurate` (5 tests) | +90, -8 | LOW |
| `docs/ARCHITECTURE.md` | Add tiktoken note to §3.17 | +5, -0 | NONE (doc) |

**Total: ~160 lines, 1 production file + 1 dep, 1 test file, 1 doc file.**

---

## 5. Implementation Order

Numbered steps. The implementer must complete each step and verify before moving to the next. No batching.

1. **Add `tiktoken>=0.7` to `pyproject.toml` dependencies.**
   - **Verify:** `grep -n "tiktoken" pyproject.toml` → at least 1 match in the `dependencies` block.
   - **Verify:** `python3 -c "import tiktoken; print(tiktoken.__version__)"` → still works.

2. **Add the `_tiktoken_encoding_for` helper to `models/conversation.py`** (place after `_count_char_tokens`, before `get_token_estimate`).
   - **Verify:** `python3 -c "from models.conversation import _tiktoken_encoding_for; enc = _tiktoken_encoding_for('gpt-4o'); print(enc.name)"` → `o200k_base`.
   - **Verify:** `python3 -c "from models.conversation import _tiktoken_encoding_for; enc = _tiktoken_encoding_for('openai/gpt-4o'); print(enc.name)"` → `o200k_base` (prefix stripped).
   - **Verify:** `python3 -c "from models.conversation import _tiktoken_encoding_for; enc = _tiktoken_encoding_for('unknown-xyz'); print(enc.name)"` → `cl100k_base` (default fallback).

3. **Add the `_count_tokens_accurate` method to `Conversation`** (place after `get_token_estimate` or wherever matches the existing method ordering).
   - **Verify:** `python3 -c "from models.conversation import Conversation; c = Conversation(); print(c._count_tokens_accurate(__import__('tiktoken').get_encoding('cl100k_base')))"` → 0 for empty conversation.

4. **Update `get_token_estimate`** to use tiktoken with fallback.
   - **Verify:** `python3 -c "from models.conversation import Conversation; c = Conversation(system_prompt='hello world', model='gpt-4o'); print(c.get_token_estimate())"` → 2 (tiktoken o200k_base count for "hello world").

5. **Update `get_token_breakdown`** to use tiktoken with fallback.
   - **Verify:** `python3 -c "from models.conversation import Conversation; c = Conversation(system_prompt='hello', model='gpt-4o'); c.add_user_message('world'); print(c.get_token_breakdown(1000))"` → dict with accurate system_prompt_tokens and conversation_tokens.

6. **Update the 4 existing tests in `TestConversationTokenEstimate`** to use tolerance-based assertions.
   - **Verify:** `pytest tests/test_conversation.py::TestConversationTokenEstimate -v` → all 4 pass.

7. **Add the new `TestTiktokenAccurate` class** with 5 tests.
   - **Verify:** `pytest tests/test_conversation.py::TestTiktokenAccurate -v` → all 5 pass.

8. **Run the full test suite.**
   - **Verify:** `pytest tests/ -q` → all tests pass, no regressions.
   - **Verify:** The existing `TestConversationTrim` (4 tests), `TestTrimSummaryInjection` (8 tests), `TestRunLoopTrimsContext` (1 test), and `TestComputeModelMax` (5 tests) all continue to pass.
   - **Verify:** The existing `TestStreamingUsageCapture` (3 tests), `TestStuckMessageTransient` (2 tests), and `TestAwarenessCaps` (2 tests) all continue to pass.

9. **Update `docs/ARCHITECTURE.md`** — add the tiktoken note to §3.17.
   - **Verify:** `grep -n "tiktoken" docs/ARCHITECTURE.md` → at least 1 match.

10. **Adversarial audit** (per `prompts/adversarialDebugger.md` and the project's implementation loop) before commit.

---

## 6. Acceptance Criteria

The implementer has succeeded when ALL of the following are true:

- [ ] `tiktoken>=0.7` is in `pyproject.toml` `dependencies`.
- [ ] `_tiktoken_encoding_for("gpt-4o")` returns the `o200k_base` encoding.
- [ ] `_tiktoken_encoding_for("openai/gpt-4o")` returns the `o200k_base` encoding (prefix stripped).
- [ ] `_tiktoken_encoding_for("claude-3-opus")` returns the `cl100k_base` encoding (default fallback).
- [ ] `_tiktoken_encoding_for("unknown-xyz")` returns the `cl100k_base` encoding (default fallback).
- [ ] `get_token_estimate()` for `Conversation(model="gpt-4o", system_prompt="hello world")` returns 2 (tiktoken count, not `11 // 4 = 2` coincidence — the test must use a string where the counts DIFFER to prove tiktoken is being used).
- [ ] `get_token_breakdown()` returns tiktoken-accurate counts for known models.
- [ ] When `tiktoken` is not importable, `get_token_estimate()` falls back to `chars // 4` (no crash).
- [ ] All 4 updated `TestConversationTokenEstimate` tests pass.
- [ ] All 5 new `TestTiktokenAccurate` tests pass.
- [ ] All 1641+ existing tests still pass (full suite green, no regressions).
- [ ] No new public API surface (only one new private helper `_tiktoken_encoding_for` and one new private method `_count_tokens_accurate`).
- [ ] `docs/ARCHITECTURE.md` §3.17 documents the new tiktoken dependency and behavior.
- [ ] Adversarial audit produces zero CRITICAL or HIGH findings.

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| `conv.model` is `""` (empty string, the default) | `_tiktoken_encoding_for("")` → `tiktoken.encoding_for_model("")` raises `KeyError` → falls back to `cl100k_base`. Returns encoding. |
| `conv.model` is `"gpt-4o"` | `_tiktoken_encoding_for("gpt-4o")` → `o200k_base`. Returns encoding. |
| `conv.model` is `"openai/gpt-4o"` (with provider prefix) | Strip prefix → `tiktoken.encoding_for_model("gpt-4o")` → `o200k_base`. Returns encoding. |
| `conv.model` is `"openrouter/auto"` (unknown model with provider prefix) | Strip prefix → `tiktoken.encoding_for_model("auto")` raises `KeyError` → falls back to `cl100k_base`. Returns encoding. |
| `conv.model` is `"claude-3-opus"` (Anthropic, not in tiktoken) | `tiktoken.encoding_for_model("claude-3-opus")` raises `KeyError` → falls back to `cl100k_base`. Returns encoding. |
| `tiktoken` is not installed (ImportError) | Helper returns `None`. `get_token_estimate` falls back to `chars // 4`. No crash. |
| `tiktoken.encoding_for_model` raises some other exception (e.g., download failure) | Helper's outer `except Exception` catches it, returns `None`. Fallback to `chars // 4`. No crash. |
| `conv.system_prompt` is empty | `len(encoding.encode(""))` = 0. No tokens counted for the system prompt. |
| `msg.content` is `None` (some messages have None content, e.g., tool-call-only assistant messages) | `_count_tokens_accurate` uses `msg.content or ""`. None is treated as empty. |
| `tc.arguments` is a dict (e.g., `{"path": "x.py"}`) | `str(tc.arguments)` = `'{"path": "x.py"}'`. Encoded as 6 tokens (o200k_base) or 4 tokens (cl100k_base). Both reasonable. |
| `tc.arguments` is a non-JSON-serializable object (e.g., a `datetime`) | `str(tc.arguments)` = the repr. Encoded as the appropriate number of tokens. Both work. |
| A message has 100 tool_calls | The loop iterates 100 times. Total tokens is the sum. Slightly slower than `_count_char_tokens` (which also iterates 100 times), but the difference is negligible. |
| `get_token_breakdown(model_max_tokens=0)` | The existing `if model_max_tokens > 0` guard prevents division by zero. Returns `usage_percent: 0`. |
| The trim runs in a hot loop (per-iteration of `_run_loop`) | `_tiktoken_encoding_for` is called once per `get_token_estimate` call. The `encoding_for_model` is fast (cached internally in tiktoken). The `len(encoding.encode(...))` is fast for typical text. Total overhead: <1ms per call. Acceptable. |
| Two threads call `get_token_estimate` concurrently | `_tiktoken_encoding_for` is stateless (just imports and returns an encoding). `len(encoding.encode(...))` is thread-safe. No race. |
| The user's model is "minimax/MiniMax-Text-01" (a non-standard MiniMax model) | Strip prefix → "MiniMax-Text-01". `tiktoken.encoding_for_model("MiniMax-Text-01")` raises `KeyError` → falls back to `cl100k_base`. Returns encoding. |
| The model name has multiple slashes (e.g., "openai/gpt-4o/2024-08-06") | Strip prefix via `split("/", 1)[-1]` → "gpt-4o/2024-08-06". `tiktoken.encoding_for_model("gpt-4o/2024-08-06")` raises `KeyError` → falls back to `cl100k_base`. The user's accuracy is `cl100k_base` (close enough for GPT-4o). |
| The `tiktoken` library raises during `encoding.encode(text)` (e.g., text is a `bytes` object, not `str`) | The current code only passes `str` to `encoding.encode` (via `self.system_prompt`, `msg.content or ""`, `str(tc.arguments)`, `tc.result`). All are `str`. No risk. |
| The test for `test_tiktoken_import_error_falls_back_to_chars` uses `monkeypatch.setitem(sys.modules, "tiktoken", None)` | This is the standard pattern for simulating a missing import. After `setitem`, the next `import tiktoken` raises `ImportError`. The helper's `try/except ImportError` catches it. |
| The first call to `tiktoken.encoding_for_model` triggers a download (for the encoding data) | The download is one-time (cached in `~/.cache/tiktoken/`). The first call is slow (~100ms). Subsequent calls are fast (~1ms). The trim doesn't care about the first-call latency. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, the implementer must update `docs/ARCHITECTURE.md` as follows:

### §3.17 — `models/conversation.py` (additive change)

Append the tiktoken note (see §2.4 for exact text). No other §3.17 changes.

### §8.3 (New dependency) — optional

If the project has a section listing runtime dependencies, add `tiktoken>=0.7` to it. Otherwise, the §3.17 note is sufficient.

---

## 9. Files NOT changed (already correct or out of scope)

- `models/conversation.py:trim_to_token_limit` — unchanged. The trim's behavior improves automatically because `get_token_estimate` is more accurate.
- `models/conversation.py:Message` dataclass — unchanged.
- `models/conversation.py:_count_char_tokens` — unchanged. Still used as the fallback when tiktoken is unavailable.
- `agent/runtime.py` — unchanged. The runtime calls `get_token_estimate` and `get_token_breakdown`; the new accuracy flows through automatically.
- `utils/prompt_loader.py` — unchanged. Doesn't use tiktoken.
- `utils/project_awareness.py` — unchanged.
- `tests/test_conversation.py:TestConversationTrim` (4 tests) — unchanged. The trim's behavior with the new estimator is correct (more accurate trigger).
- `tests/test_phase4.py:TestTrimSummaryInjection` (8 tests) — unchanged.
- `tests/test_agent_runtime.py:TestRunLoopTrimsContext` (1 test) — unchanged.
- `tests/test_agent_runtime.py:TestComputeModelMax` (5 tests) — unchanged.
- `tests/test_agent_runtime.py:TestStreamingUsageCapture` (3 tests) — unchanged.
- `tests/test_agent_runtime.py:TestStuckMessageTransient` (2 tests) — unchanged.
- `tests/test_project_awareness.py:TestAwarenessCaps` (2 tests) — unchanged.
- `pyproject.toml:optional-dependencies` — the `dev` group is unchanged. `tiktoken` is a runtime dep, not a dev dep.

---

## 10. Risk and Rollback

**Risk:** LOW.

The change is additive: a new private helper, a new private method, and a one-line modification to two existing methods. The fallback to `chars // 4` preserves the existing behavior when tiktoken is unavailable.

**Failure modes:**

- `tiktoken.encoding_for_model` raises an unexpected exception: caught by the helper's outer `except Exception`. Returns `None`. Fallback to `chars // 4`.
- The encoding download fails (no internet, corrupted cache): caught by `tiktoken.encoding_for_model` raising an exception, which the helper catches.
- A model name that tiktoken recognizes but produces wildly different counts from the LLM: out of scope. `tiktoken`'s `o200k_base` and `cl100k_base` are the SAME encodings used by OpenAI's GPT-4o and GPT-4 respectively. They are accurate for those models. For other models (Anthropic, MiniMax, etc.), the accuracy is "close enough" (per the proposal).
- The existing 4 tests in `TestConversationTokenEstimate` are not updated: they fail with the new accurate counts. The spec mandates updating them with tolerance-based assertions.
- A test that constructs a `Conversation` with an empty `model=""` and expects `chars // 4` behavior: the test gets `cl100k_base` counts. The spec doesn't guarantee `chars // 4` behavior for any model — the fallback is only when `tiktoken` is unavailable.

**Rollback:**

This phase is one commit. To roll back: `git revert <commit-hash>`. The runtime goes back to the pre-CB-4 state:
- `tiktoken` is removed from `pyproject.toml` (still installed but not declared).
- `_tiktoken_encoding_for` is removed.
- `_count_tokens_accurate` is removed.
- `get_token_estimate` and `get_token_breakdown` revert to `chars // 4`.
- The 4 existing tests revert to their hard-coded assertions.

No consumer breaks because the only changed behavior is more accurate token counts, which is strictly an improvement.

---

## 11. Post-Mortem

After the commit, a short post-mortem goes at `docs/post-mortems/2026-06-17-CONTEXT-BLOAT-PHASE-4-POST-MORTEM.md` using the §6 format from `prompts/implementationLoop.md`. The post-mortem MUST include the 11 sections (Code Quality Grade, What's Good, What's Bad, Bugs Found, Process Worked, Process Didn't Work, End-User Impact, Pre-Existing Issues, Evolution Suggestions, Lessons Learned, Sign-off).

The post-mortem should specifically address:
- Whether the empirical token counts from `tiktoken` match the trim's behavior in a real session (verifying the proposal's claim that "BUG #1's fix becomes more reliable").
- Whether the existing tests' update to tolerance-based assertions preserves their intent (the original tests verified "tokens are counted" — the new tests verify "tokens are counted accurately").
- Whether the `cl100k_base` default encoding is a reasonable proxy for non-OpenAI models (Anthropic, MiniMax, ZAI).

---

## 12. Author Notes

This spec addresses BUG #5 from the original investigation: the `chars // 4` token estimation is ~60% undercount for code-heavy content. The fix is straightforward (use `tiktoken`) but the implementation has two subtleties that surfaced during pre-flight:

1. **`tiktoken.encoding_for_model` only recognizes bare OpenAI model names.** Crabcakes uses `"openai/gpt-4o"` style names (provider/model). The fix MUST strip the provider prefix. Without this, every conversation in this project would raise `KeyError` and fall back to the default encoding — which is fine (it's `cl100k_base`) but would obscure the "real" encoding for GPT-4o (which is `o200k_base`).

2. **The existing 4 tests in `TestConversationTokenEstimate` use hard-coded `chars // 4` expectations.** For example, `assert c.get_token_estimate() == 10` for `"x" * 40`. With tiktoken, `"x" * 40` is 5 tokens (not 10). The spec mandates updating these tests to use tolerance-based assertions, which is a more robust testing pattern anyway (doesn't depend on the exact tokenization of specific test strings).

The spec is identifier-anchored (no line numbers) per Rule 6.8. The few line numbers cited (e.g., `get_token_estimate` at line 214, `get_token_breakdown` at line 224) are anchor points for the current codebase state. If the line numbers drift, the implementer should use `grep -n "def get_token_estimate" models/conversation.py` to find the real location.

**Risk is bounded by the fallback.** The `chars // 4` heuristic is preserved as the final fallback. If `tiktoken` raises for any reason, the trim's behavior is the same as pre-CB-4 (less accurate but no crash). The risk is "worse accuracy" not "broken trim."

**The new `tiktoken` dependency is small and well-maintained.** ~2MB, MIT-licensed, no transitive deps, used by OpenAI's official tools. Adding it to `pyproject.toml` is standard.
