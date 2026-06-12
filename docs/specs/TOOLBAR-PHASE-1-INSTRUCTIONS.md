# PHASE 1 of 7 — Verify + Test `utils/spellcheck.py`

**Spec:** `/home/q/projects/crabcakes/docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md` Section 2.1
**Target file:** `utils/spellcheck.py` (already exists — 100 lines)
**Test file to create:** `tests/test_spellcheck.py`

## Context

The file `utils/spellcheck.py` already exists and implements `check_words()` and `get_suggestions()`. Your job is to:

1. **Read the existing file** and verify it matches the spec in Section 2.1
2. **Read the spec** Section 2.1 to understand the contract
3. **Write comprehensive tests** covering happy path, sad path, and edge cases
4. **Fix any bugs** you find in the existing implementation

## What the spec requires

### `check_words(text: str) -> list[str]`
- Uses `enchant-2 -l` (batch mode, one subprocess call)
- Returns list of unique misspelled words (order preserved, deduplicated)
- Returns empty list on: empty input, `FileNotFoundError`, `TimeoutExpired`, any exception
- All exceptions logged, not silenced

### `get_suggestions(word: str) -> list[str]`
- Uses `enchant-2 -a` (ispell pipe mode)
- Returns up to 8 suggestions
- Parses ispell format: `& word count offset: sug1, sug2, ...`
- Returns empty list on: empty input, correct word (`*` response), any exception

## Architecture Rules (from ARCHITECTURE.md)
- `utils/` is pure Python — no GTK, no network
- This file must have no GTK imports and no network calls
- Security manifest in module docstring

## Test Requirements (steelFramedCodeWriter Rules 3 & 4)

Write `tests/test_spellcheck.py` with:

### Happy path tests:
1. `test_check_words_finds_misspelled` — known misspelled word ("wrld") is detected
2. `test_check_words_clean_text` — correct text returns empty list
3. `test_check_words_deduplicates` — same misspelled word appearing twice returns once
4. `test_check_words_preserves_order` — multiple misspellings returned in order of first occurrence
5. `test_get_suggestions_returns_list` — suggestions for "wrld" include common corrections
6. `test_get_suggestions_max_8` — verify truncation to 8 items

### Sad path tests:
7. `test_check_words_empty_string` — returns []
8. `test_check_words_whitespace_only` — returns []
9. `test_get_suggestions_empty_string` — returns []
10. `test_check_words_enchant_not_found` — mock subprocess to raise FileNotFoundError, returns []
11. `test_check_words_timeout` — mock subprocess to raise TimeoutExpired, returns []
12. `test_get_suggestions_enchant_not_found` — mock to raise FileNotFoundError, returns []
13. `test_get_suggestions_timeout` — mock to raise TimeoutExpired, returns []
14. `test_check_words_unexpected_exception` — mock to raise RuntimeError, returns []

### Edge case tests:
15. `test_check_words_single_word_correct` — single correct word returns []
16. `test_get_suggestions_correct_word` — word spelled correctly returns [] (enchant returns `*`)
17. `test_check_words_unicode_text` — text with unicode characters doesn't crash
18. `test_get_suggestions_empty_response` — enchant returns empty stdout, returns []

### Mocking rules:
- Mock `subprocess.run` at `utils.spellcheck.subprocess.run` — this is the external boundary (Rule 4)
- Do NOT mock `check_words` or `get_suggestions` themselves
- For happy-path tests: use REAL `enchant-2` if available (check `which enchant-2`), skip if not installed
- For sad-path tests: always use mocks (we need to simulate errors)

### For happy-path tests that need real enchant-2:
```python
import shutil
import pytest

ENCHANT_AVAILABLE = shutil.which("enchant-2") is not None

@pytest.mark.skipif(not ENCHANT_AVAILABLE, reason="enchant-2 not installed")
def test_check_words_finds_misspelled():
    ...
```

## Verification Commands

After writing tests and any fixes:

```bash
# Run the new tests
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_spellcheck.py -v --tb=short

# Run the full suite to check for regressions
cd /home/q/projects/crabcakes && python3 -m pytest tests/ -q --tb=short

# Verify the file has no GTK or network imports
grep -n "import gi\|from gi\|import gtk\|urllib\|requests\|socket" utils/spellcheck.py

# Verify line count
wc -l utils/spellcheck.py
```

## COMPLETENESS Checklist

At the end of your response, you MUST include:

```
COMPLETENESS:
- [x/not done] Read existing utils/spellcheck.py — verified against spec Section 2.1
- [x/not done] Read spec Section 2.1 — understood the contract
- [x/not done] Created tests/test_spellcheck.py — evidence: (test count, passing count)
- [x/not done] Happy path tests (6 tests) — evidence: test names + results
- [x/not done] Sad path tests (8 tests) — evidence: test names + results  
- [x/not done] Edge case tests (4 tests) — evidence: test names + results
- [x/not done] All new tests pass — evidence: pytest output
- [x/not done] Full test suite passes — evidence: pytest output (1397+ passed)
- [x/not done] No GTK/network imports in spellcheck.py — evidence: grep output
- [x/not done] Bugs found in existing code (if any) — description + fix
```

## Important Reminders

- Use the **steelFramedCodeWriter** prompt at `prompts/steelFramedCodeWriter.md`
- Start with discovery: read the file, read the spec section, then write
- Maximum 15 lines before verifying
- Every test must be able to fail (Rule 4)
- Report any bugs found in existing code — do not silently fix without reporting
- The word marker for this delegation is: **"please write"**
