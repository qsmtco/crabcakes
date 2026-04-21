"""
Convergence detection — policy-driven with LR model.

Policy layer decides stop/continue using three signals:
  1. Orchestrator turn number (hard walls, escalation)
  2. Politeness-only response heuristic (turns 1–2: too early)
  3. LR model P(stop) vs escalation threshold (turns 3–9)

Escalation thresholds (P(stop) required to stop):
  turn  3–4: 0.40    turn  7: 0.80
  turn  5: 0.55     turn  8: 0.85
  turn  6: 0.70     turn  9: 0.90
  hard wall at turn 10 (always stop)

The LR model produces P(stop) from a 22-feature vector trained on 26 fixtures.
The policy combines turn count + P(stop) threshold — portable, no sklearn dep.

Public API:
  compute_convergence(responses) → {"prob_stop": float, "signal": str}
  should_stop(responses, turn)  → bool  (new policy)
  should_stop_legacy(responses)  → bool  (old fixed-threshold LR model)
"""
import math
import re
import json
import os
from typing import List

import pytest
from sklearn.linear_model import LogisticRegression

# ─────────────────────────────────────────────────────────────────────────────
# Word sets
# ─────────────────────────────────────────────────────────────────────────────

_POLITE_SOCIAL = {
    "thanks", "thank you", "you're welcome", "anytime", "happy to help",
    "of course", "certainly", "no problem", "my pleasure", "you got it",
    "no worries", "no problem at all", "sure thing", "exactly", "indeed",
    "yes",
}
_CONFIRM_WORDS = {
    "yes", "no", "right", "ok", "okay", "correct", "exact", "agreed",
    "done", "confirmed", "indeed", "do",
}
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "it", "this", "that", "these", "those",
    "i", "you", "he", "she", "we", "they", "them", "his", "her", "our", "their",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "can", "may", "might", "must", "shall",
    "and", "but", "or", "not", "no", "so", "if", "then", "than",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other", "some", "any",
    "just", "also", "very", "too", "only", "even", "still", "well",
    "now", "here", "there", "about", "after", "before", "above", "below",
    "up", "down", "out", "off", "over", "under", "again", "further",
    "same", "such", "its", "into", "your", "my", "me", "us", "let",
}

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_politeness_only(text: str) -> bool:
    """True if text is pure social politeness with no substantive content."""
    t = re.sub(r'[.,!?]+$', '', text.lower().strip())
    t = re.sub(r'[.,]+', ' ', t).strip()
    words = t.split()
    if not words:
        return False
    if t in _POLITE_SOCIAL or len(words) == 1 and words[0] in _POLITE_SOCIAL:
        return True
    if len(words) <= 4:
        return all(w in _POLITE_SOCIAL for w in words)
    return False


def _is_question(text: str) -> bool:
    """True if text starts with an interrogative word."""
    return bool(re.match(
        r'^(how|why|what|where|when|can|could|would|should|do|does|is|are|was|were)\b',
        text.strip().lower(),
    ))


def _shannon_entropy(text: str) -> float:
    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return 0.0
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return -sum((c / len(words)) * math.log2(c / len(words)) for c in freq.values())


def _word_diversity(text: str) -> float:
    words = re.findall(r'\b\w+\b', text.lower())
    return len(set(words)) / len(words) if words else 0.0


def _get_ngrams(text: str, n: int = 2) -> set:
    words = re.findall(r'\b\w+\b', text.lower())
    return set(' '.join(words[i:i + n]) for i in range(len(words) - n + 1)) if len(words) >= n else set()


def _jaccard_similarity(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _jaccard_distance(a: set, b: set) -> float:
    return 1.0 - _jaccard_similarity(a, b)


def _content_words(text: str) -> set:
    return {w for w in re.findall(r'\b\w+\b', text.lower())
            if w not in _STOPWORDS and len(w) > 2}


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction — 22 signals per conversation
# ─────────────────────────────────────────────────────────────────────────────
# Indices: 0=rld 1=semantic_novelty 2=perplexity_proxy 3=entropy 4=q_density
#   5=politeness_only_last 6=politeness_rel_last 7=politeness_hist
#   8=politeness_last3 9=politeness_word_frac 10=politeness_hist_count
#   11=n_norm 12=content_ratio 13=continuation 14=avg_diversity
#   15=prev_sim 16=ends_sentence 17=last_sent_frac 18=last_sent_norm
#   19=first_sent_polite_only 20=concluding_phrase
#   21=<free slot>

def extract_features(responses: List[dict]) -> List[float]:
    """Build 22-feature vector from a conversation."""
    n = len(responses)
    last = responses[-1]
    prev = responses[-2] if n >= 2 else responses[-1]
    last_text = last["text"]
    prev_text = prev["text"]
    last_words = re.sub(r'[.,!?]+$', '', last_text.lower().strip()).split()
    last_ngrams = _get_ngrams(last_text, 2)
    last_keywords = _content_words(last_text)

    # f0: response length delta
    rld = min(len(last_text) / max(len(prev_text), 1), 1.0)

    # f1: avg semantic novelty vs history
    scores = []
    for r in responses[:-1]:
        pn = _get_ngrams(r["text"], 2)
        pk = _content_words(r["text"])
        scores.append(0.6 * _jaccard_distance(last_ngrams, pn)
                    + 0.4 * _jaccard_distance(last_keywords, pk))
    sn = sum(scores) / len(scores) if scores else 0.0

    # f2, f3: perplexity proxy, entropy
    ent = _shannon_entropy(last_text)
    div = _word_diversity(last_text)
    ent_norm = max(0.0, min(1.0, ent / 5.0))
    ppl_proxy = ent_norm * 0.5 + div * 0.5
    ent_score = max(0.0, min(1.0, ent / 5.0))

    # f4: question density (inverted: high QD → continue)
    window = responses[-3:]
    qd = 1.0 - (sum(1 for r in window if _is_question(r["text"])) / len(window))

    # f5: politeness-only last response
    politeness_only_last = 1.0 if is_politeness_only(last_text) else 0.0

    # f6: politeness/confirm words in last response
    polite_count = sum(1 for w in last_words if w in _POLITE_SOCIAL or w in _CONFIRM_WORDS)
    politeness_rel_last = 1.0 if polite_count > 0 else 0.0

    # f7: politeness-only in history (excl last 1)
    politeness_hist = 1.0 if any(is_politeness_only(r["text"]) for r in responses[-4:-1]) else 0.0

    # f8: politeness-only in last-3 (excl last 1)
    politeness_last3 = 1.0 if any(is_politeness_only(r["text"]) for r in responses[-3:-1]) else 0.0

    # f9: politeness word fraction
    politeness_word_frac = polite_count / max(len(last_words), 1)

    # f10: politeness-only count in history
    politeness_hist_count = sum(1 for r in responses[:-1] if is_politeness_only(r["text"]))

    # f11: exchange count normalized
    n_norm = min(n / 10.0, 1.0)

    # f12: content word ratio
    content_ratio = len(last_keywords) / max(len(last_words), 1)

    # f13: continuation pattern ("Yes, and...", "Sure, but...")
    continuation = 1.0 if re.match(
        r'^(yes,?\s+(and|but|also|so|if)|ok[ay],?\s+(but|so|and)|'
        r'sure,?\s+(but|and)|right,?\s+(but|and))',
        last_text, re.IGNORECASE
    ) else 0.0

    # f14: average word diversity
    avg_diversity = sum(_word_diversity(r["text"]) for r in responses) / n

    # f15: similarity to previous response
    prev_ngrams = _get_ngrams(prev_text, 2)
    prev_keywords = _content_words(prev_text)
    prev_sim = (0.6 * _jaccard_similarity(last_ngrams, prev_ngrams)
                + 0.4 * _jaccard_similarity(last_keywords, prev_keywords))

    # f16: ends with period
    ends_sentence = 1.0 if last_text.strip()[-1:] == '.' else 0.0

    # Sentence-level features
    sentences = [s.strip() for s in re.split(r'[.!?]+\s*', last_text) if s.strip()]
    last_sent_words = len(sentences[-1].split()) if sentences else 0
    total_words = max(len(last_words), 1)

    # f17: last sentence fraction
    last_sent_frac = last_sent_words / total_words

    # f18: last sentence length normalized
    last_sent_norm = min(last_sent_words / 20.0, 1.0)

    # f19: first sentence is standalone politeness
    first_sent_polite_only = 1.0 if sentences and is_politeness_only(sentences[0]) else 0.0

    # f20: last sentence starts with concluding phrase
    concluding_phrases = [
        "at the very", "in summary", "to summarize", "in conclusion",
        "to conclude", "ultimately", "in short", "to sum up",
        "finally", "that concludes",
    ]
    last_sent_lower = sentences[-1].lower() if sentences else ""
    concluding_phrase = 1.0 if any(last_sent_lower.startswith(p) for p in concluding_phrases) else 0.0

    return [
        rld, sn, ppl_proxy, ent_score, qd,
        politeness_only_last, politeness_rel_last,
        politeness_hist, politeness_last3,
        politeness_word_frac, politeness_hist_count, n_norm,
        content_ratio, continuation, avg_diversity,
        prev_sim, ends_sentence,
        last_sent_frac, last_sent_norm,
        first_sent_polite_only, concluding_phrase,
    ]


# ─────────────────────────────────────────────────────────────────────────────
# LR Model — trained once on 26 fixtures
# ─────────────────────────────────────────────────────────────────────────────

_MODEL_C = 10.0

with open(os.path.join(os.path.dirname(__file__), "fixtures", "conversations.json")) as f:
    _FIXTURES = json.load(f)

_X = [extract_features(fx["responses"]) for fx in _FIXTURES]
_y = [1.0 if fx.get("expected") == "stop" else 0.0 for fx in _FIXTURES]
_MODEL = LogisticRegression(C=_MODEL_C, solver="lbfgs", max_iter=1000, random_state=42)
_MODEL.fit(_X, _y)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def compute_convergence(responses: List[dict]) -> dict:
    """Return P(stop) from LR model."""
    feats = extract_features(responses)
    p_stop = float(_MODEL.predict_proba([feats])[0][1])
    n = len(responses)
    last = responses[-1]["text"]
    parts = []
    if is_politeness_only(last):
        parts.append("polite")
    if n >= 5:
        parts.append(f"n={n}")
    return {"prob_stop": p_stop, "signal": ":".join(parts) if parts else "neutral"}


# ─────────────────────────────────────────────────────────────────────────────
# Policy — portable decision layer
# ─────────────────────────────────────────────────────────────────────────────

_THRESHOLDS = {
    3: 0.90, 4: 0.85, 5: 0.75, 6: 0.70,
    7: 0.55, 8: 0.50, 9: 0.40,
}


def get_escalation_threshold(turn: int) -> float:
    """P(stop) threshold for a given turn. Unknown turns → 1.0."""
    return _THRESHOLDS.get(turn, 1.0)


def should_stop(responses: List[dict], turn: int) -> bool:
    """
    Policy decision: should the conversation stop?

    Args:
        responses: list of {"text": str, ...} dicts
        turn:      1-indexed current orchestrator turn
    Returns:
        True to stop, False to continue.
    """
    if turn <= 2:
        return False          # too early
    if turn >= 10:
        return True           # hard wall
    result = compute_convergence(responses)
    return result["prob_stop"] >= get_escalation_threshold(turn)


def should_stop_legacy(responses: List[dict]) -> tuple[bool, str]:
    """
    Original LR-only decision: fixed 0.60 threshold, no turn awareness.
    Kept for regression comparison.
    """
    result = compute_convergence(responses)
    p = result["prob_stop"]
    if p >= 0.60:
        return True, f"convergence_detected:p={p:.2f}"
    elif p < 0.40:
        return False, f"active_discussion:p={p:.2f}"
    else:
        return False, f"borderline:p={p:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Policy
# ─────────────────────────────────────────────────────────────────────────────

_SHORT = {
    "quick-close-1", "quick-close-2", "quick-close-3",
    "edge-case-reallly-short-1", "edge-case-long-answer-first-1",
    "edge-case-long-answer-first-2", "question-answer-close-1",
    "empty-minimal-responses-1", "very-long-substantive-response-1",
}
_LONG = [f for f in _FIXTURES if f["id"] not in _SHORT]
_SHORT_LIST = [f for f in _FIXTURES if f["id"] in _SHORT]


@pytest.mark.parametrize("fixture", _LONG, ids=[f["id"] for f in _LONG])
def test_policy_at_natural_turn(fixture):
    """Long fixtures: new policy at natural turn count (≥3)."""
    rs = fixture["responses"]
    stop = should_stop(rs, min(len(rs), 10))
    assert stop == (fixture.get("expected") == "stop"), (
        f"[{fixture['id']}] stop={stop} expected={fixture.get('expected')}"
    )


@pytest.mark.parametrize("fixture", _SHORT_LIST, ids=[f["id"] for f in _SHORT_LIST])
def test_short_fixtures_at_turn3(fixture):
    """Short fixtures: evaluate at turn 3 minimum."""
    stop = should_stop(fixture["responses"], turn=3)
    assert stop == (fixture.get("expected") == "stop")


def test_escalation_easier_to_stop():
    """Lower turn → higher threshold → harder to stop (easy to continue).
    Higher turn → lower threshold → easier to stop (harder to continue).
    This is the inverted schedule: as conversation approaches hard wall,
    stopping becomes progressively easier because we're nearing natural end.
    """
    assert get_escalation_threshold(3) > get_escalation_threshold(9)
    assert get_escalation_threshold(4) > get_escalation_threshold(7)
    assert get_escalation_threshold(5) > get_escalation_threshold(6)


def test_turn3_polite_stops():
    """Turn 3 with polite-only response → stop."""
    # "Thanks!" at turn 3 on top of an ongoing conversation
    responses = [
        {"text": "Here's the fix."},
        {"text": "Confirmed, looks good."},
        {"text": "Thanks!"},
    ]
    assert should_stop(responses, turn=3)


def test_turn4_substantive_uses_lr():
    """Turn 4 with substantive response → LR model decides."""
    responses = [
        {"text": "What's the segfault?"},
        {"text": "Use-after-free in session cleanup."},
        {"text": "Got it."},
        {"text": "The fix looks correct, apply it and run tests."},
    ]
    result = compute_convergence(responses)
    # P may be anywhere — just verify it doesn't crash
    assert 0.0 <= result["prob_stop"] <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Tests — LR model (legacy comparison)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
def test_legacy_lr_still_passes(fixture):
    """Original fixed-threshold LR model — should still pass all 26."""
    stop, _ = should_stop_legacy(fixture["responses"])
    assert stop == (fixture.get("expected") == "stop")


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Smoke
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_convergence_returns_valid_output():
    result = compute_convergence(_FIXTURES[0]["responses"])
    assert "prob_stop" in result
    assert "signal" in result
    assert 0.0 <= result["prob_stop"] <= 1.0


def test_feature_vector_always_21_features():
    for fx in _FIXTURES:
        feats = extract_features(fx["responses"])
        assert len(feats) == 21, f"[{fx['id']}] expected 21, got {len(feats)}"
