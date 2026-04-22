# Adversarial Audit: Convergence Detection (converge/)
**Auditor:** Qaster (Synthetic Tensor Intelligence)
**Date:** 2026-04-21
**Target:** `converge/converge.py`, `converge/__init__.py`, `converge/model.pkl`, `converge/vectorizer.pkl`
**Methodology:** Adversarial debugging — challenge every assumption, trace every failure path, prove it doesn't work

---

## Summary Scorecard

| Category | Count |
|----------|-------|
| 🔴 Critical (fundamentally broken) | 1 |
| 🟠 High (broken in real usage) | 4 |
| 🟡 Medium (broken in edge cases) | 4 |
| 🟢 Low (code quality) | 4 |
| **Total bugs found** | **13** |
| **Existing test failures** | **5/266 fixtures** |

---

## BUG #1 — TEST FILE IS A COMPLETE CODE DUPLICATION (Tests Different Code Than Ships)
**Severity:** 🔴 CRITICAL
**File:** `tests/test_convergence.py`

The test file does **not import from the `converge` package**. Its imports:
```python
import math, re, json, os
import numpy as np, pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
```

It then **reimplements every function** — `is_politeness_only`, `_shannon_entropy`, `_word_diversity`, `_content_words`, `_tfidf_cosine`, `extract_features`, `compute_convergence`, `should_stop`, `should_stop_legacy` — as module-level definitions. It trains its **own Random Forest** from fixture data at import time.

The production module loads a **pre-trained model from `.pkl` files**.

**Mitigating factor:** I verified the two models produce *identical* predictions on all 266 fixtures (max probability difference: 0.000000). Same hyperparameters (200 estimators, random_state=42), same vocabulary. So the pkl was generated from this exact training code. The models match today.

**The risk:** If anyone changes `converge/converge.py` — fixes a bug in `extract_features`, updates a word list, changes a formula — the tests **will not catch it**. They're running their own copy of the old code. A refactoring or bugfix to the production module is invisible to the test suite. The tests provide false confidence.

---

## BUG #2 — `len_trend` (f3) IS UNBOUNDED, NOT NORMALIZED
**Severity:** 🟠 HIGH
**File:** `converge/converge.py`, `extract_features()`, line ~200

```python
len_trend = (lens[-1] - avg_len) / max(avg_len, 1)
```

Every other feature is bounded:
- f0, f1: clamped via `min(..., 1.0)`
- f2: ratio → [0, 1] by construction
- f4, f5: fractions → [0, 1]
- f6, f7: fractions → [0, 1]
- f8, f9: cosine similarity → [0, 1]

f3 can produce values well outside [0, 1]. Verified:
- 1-char avg response followed by 500-word response → `f3 = 1.998`
- 1000-char avg response followed by "ok" → `f3 = -0.996`

A Random Forest can handle unbounded inputs, but this feature has disproportionate range compared to all others. The model trained on it works by accident — the training data happened to have bounded length distributions. A deployment with different conversation length patterns could produce extreme f3 values the model never saw during training.

---

## BUG #3 — QAC FORM PREVENTS 2-TURN CONVERSATIONS FROM STOPPING (5 Fixtures Fail)
**Severity:** 🟠 HIGH
**File:** `converge/converge.py`, `should_stop()`

```python
if turn <= 2:
    return False  # QAC: don't stop before the acknowledgment
```

5 out of 266 fixtures fail:
- `quick-close-1` — "What's causing the segfault?" → "Use-after-free. Fix: defer cleanup." → should stop at turn 2, doesn't
- `quick-close-2`, `quick-close-3` — same pattern
- `edge-case-reallly-short-1` — "Is line 82 OK?" → "Yes." → should stop, doesn't
- `edge-case-long-answer-first-1` — same pattern

Simple Q&A conversations that naturally end in 2 turns can never stop. The model correctly predicts stop for these (prob_stop > 0.50), but the policy layer overrides it with "always continue."

The QAC rule was designed for multi-agent conversations where 3 turns is the minimum for a complete exchange. But the fixture data includes legitimate 2-turn conversations. Either the QAC rule is too aggressive or the fixtures are wrong — one of them needs to change.

---

## BUG #4 — MODEL LOADS AT IMPORT TIME (Brittle Startup)
**Severity:** 🟠 HIGH
**File:** `converge/converge.py`, module-level lines

```python
_MODEL = joblib.load(__file__.rsplit("/", 1)[0] + "/model.pkl")
_TFIDF = joblib.load(__file__.rsplit("/", 1)[0] + "/vectorizer.pkl")
```

Two problems:

**a) Any import triggers loading.** `from converge import should_stop` loads 1.4MB of pickled objects. If the module is imported but never used (e.g., imported for type hints or re-exported by a package), the startup cost is paid anyway.

**b) Import failure crashes the application.** If the `.pkl` files are missing, corrupted, or incompatible with the installed scikit-learn version (sklearn is notorious for breaking pickle compatibility between versions), `import converge` raises an exception. The entire CrabCakes app fails to start, even if convergence detection is never used.

---

## BUG #5 — `__file__` PATH RESOLUTION IS FRAGILE
**Severity:** 🟡 MEDIUM
**File:** `converge/converge.py`

```python
__file__.rsplit("/", 1)[0] + "/model.pkl"
```

- Uses `/` separator — breaks on Windows (`\`)
- In frozen executables (PyInstaller, cx_Freeze), `__file__` may be `None`
- In zip imports, `__file__` may not exist
- String concatenation instead of `os.path.join`

Should be:
```python
os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.pkl")
```

---

## BUG #6 — `should_stop()` DOESN'T VALIDATE `turn` vs `len(responses)`
**Severity:** 🟠 HIGH
**File:** `converge/converge.py`, `should_stop()`

The function accepts `turn` and `responses` as independent parameters with no validation:
- `turn=14, responses=[2 items]` — model evaluates 2 responses as if they represent 14 turns
- `turn=3, responses=[100 items]` — model evaluates 100 responses as if they're at turn 3
- `turn=-1` — silently treated as `turn <= 2`, always continues
- `turn=0` — same

The caller is trusted to keep them in sync. A single caller bug creates undetectable misbehavior.

---

## BUG #7 — MISSING `"text"` KEY CRASHES AT TURN ≥ 3
**Severity:** 🟡 MEDIUM
**File:** `converge/converge.py`, `extract_features()`

```python
last_text = last["text"]  # KeyError if "text" is missing
```

At turn ≤ 2, `should_stop` short-circuits before reaching `extract_features`. At turn ≥ 3, a response dict without a `"text"` key causes an uncaught `KeyError`. The function doesn't validate input structure.

---

## BUG #8 — `_CONFIRM_WORDS` CONTAINS "do" AND "no" (False Politeness)
**Severity:** 🟡 MEDIUM
**File:** `converge/converge.py`

```python
_CONFIRM_WORDS = {
    "yes", "no", "right", "ok", "okay", "correct", "exact", "agreed",
    "done", "confirmed", "indeed", "do",
}
```

`"do"` is in the confirm set. "I do think this approach is solid" → `"do"` counted as polite/confirm, inflating `polite_frac` (f5). Verified: the sentence "I do not know what to do about the node module" has 2/11 words flagged as polite/confirm.

`"no"` is also in the set. "There is no evidence of a memory leak" → `"no"` counted as polite/confirm.

These false positives shift `polite_frac` upward in substantive technical sentences, biasing the model toward predicting "stop" for normal discussion.

---

## BUG #9 — `content_words()` FILTERS ALL WORDS ≤ 2 CHARACTERS
**Severity:** 🟡 MEDIUM
**File:** `converge/converge.py`, `_content_words()`

```python
return {w for w in re.findall(r'\b\w+\b', text.lower())
        if w not in _STOPWORDS and len(w) > 2}
```

Filters out all 1-2 character words. In programming discussions, this strips:
- `"Go"` (the language) → filtered
- `"C"` (the language) → filtered
- `"R"` (the language) → filtered
- `"JS"` → filtered
- `"no"` (as in "no errors") → filtered (also a stopword)

Verified: `content_words("Go")` → empty set, `content_words("Rust")` → `{"rust"}`. The `content_ratio` (f4) underestimates substantive content in technical conversations where short tokens carry meaning.

---

## BUG #10 — SENTENCE SPLITTING BREAKS ON ABBREVIATIONS
**Severity:** 🟡 MEDIUM
**File:** `converge/converge.py`, `extract_features()`, f6/f7

```python
sentences = [s.strip() for s in re.split(r'[.!?]+\s*', last_text) if s.strip()]
```

Splits on `.!?` followed by whitespace. Breaks on:
- "Dr. Smith confirmed" → splits at "Dr." → two fragments
- "The fix is in auth.py. Tested." → splits at "auth.py." → "auth" and "py" become fragments
- "E.g. the buffer" → splits at "E.g." → wrong
- "St. Louis" → splits at "St."

Features f6 (`last_sent_norm`) and f7 (`last_sent_frac`) are computed on incorrectly split sentences. In technical conversations where abbreviations, file extensions, and "e.g." are common, these features produce noisy values.

---

## BUG #11 — NOTHING IN THE CODEBASE IMPORTS THE CONVERGE PACKAGE
**Severity:** 🟠 HIGH

```bash
$ grep -rn "from converge\|import converge" --include="*.py" --exclude-dir=__pycache__
converge/converge.py:115:  from converge import should_stop  # docstring example only
```

The only reference is a usage example in the module's own docstring. No source file, no UI handler, no orchestrator imports from `converge`. The entire module is **dead code** — it exists but nothing uses it. It's not wired into the application.

---

## BUG #12 — ORPHANED TEST FILES REFERENCE NONEXISTENT MODULE
**Severity:** 🟢 LOW
**Files:** `converge/test_stoplight.py`, `converge/run_tests.py`

```python
from stoplight import compute_convergence, should_stop, should_stop_legacy
```

The module was renamed from `stoplight` to `converge`. These files were left behind and can never run — `ModuleNotFoundError`. Dead files.

---

## BUG #13 — NO RE-TRAINING SCRIPT
**Severity:** 🟢 LOW

The model ships as `model.pkl` (1.1MB) and `vectorizer.pkl` (268KB). Training code only exists inside `tests/test_convergence.py` (as inline module-level code, not a reusable function). If someone:
- Adds new fixtures
- Changes feature calculations
- Updates scikit-learn (pickle compatibility)
- Retunes hyperparameters

There's no documented way to regenerate the `.pkl` files.

---

## THINGS THAT ACTUALLY WORK WELL

To be fair — this isn't all bad:

- **The Random Forest approach is sound.** 261/266 fixtures classify correctly (98.1% accuracy). The 10-feature design captures meaningful convergence signals.
- **Feature extraction is well-documented.** Each feature has clear comments explaining what it measures and why.
- **The module is dependency-clean.** No GTK, no network, no LLM calls. Pure math + sklearn.
- **Politeness detection works well for common cases.** "Thanks!", "You're welcome!" correctly detected.
- **The two models (pkl vs test-trained) are identical.** Same predictions on all 266 fixtures.
- **Cost is negligible.** ~50ms per evaluation even for 10-response conversations. Sub-millisecond for typical 3-5 turn conversations.

---

## THE VERDICT

The convergence module works as a standalone piece of ML engineering. 98.1% accuracy on its own test fixtures. Clean code. Good documentation.

But it has three structural problems that will bite in production:

1. **It's dead code.** Nothing imports it. It's not wired into CrabCakes. It's a library without a consumer.
2. **The test file tests a copy, not the module.** Any change to `converge.py` is invisible to tests. The test suite provides false confidence.
3. **The QAC rule prevents 2-turn conversations from stopping.** 5 fixtures already prove this is wrong.

The ML works. The engineering around it doesn't.
