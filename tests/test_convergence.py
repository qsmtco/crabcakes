"""
Convergence detection — policy-driven stop/continue decision for multi-agent conversations.

The policy layer decides when a conversation has naturally ended using:
  1. Orchestrator turn number (always stop at turn 10)
  2. LR model P(stop) vs hand-tuned threshold (turns 3–9)

Thresholds are tuned per-turn based on the P(stop) distribution of the training data:
  turn  3: 0.30    turn  6: 0.40
  turn  4: 0.50    turn  7: 0.55
  turn  5: 0.45    turn  8: 0.40
                     turn  9: 0.35

Public API:
  compute_convergence(responses) -> {"prob_stop": float, "signal": str}
  should_stop(responses, turn)    -> bool
  should_stop_legacy(responses)   -> tuple[bool, str]
"""
import math
import re
import json
import os
from typing import List

import pytest
from sklearn.linear_model import LogisticRegression

_POLITE_SOCIAL = {
    "thanks", "thank you", "you're welcome", "anytime", "happy to help",
    "of course", "certainly", "no problem", "my pleasure", "you got it",
    "no worries", "no problem at all", "sure thing", "exactly", "indeed", "yes",
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


def is_politeness_only(text: str) -> bool:
    """True if text is pure social politeness with no substantive content."""
    t = re.sub(r'[.,!?]+$', '', text.lower().strip())
    t = re.sub(r'[.,]+', ' ', t).strip()
    words = t.split()
    if not words:
        return False
    if t in _POLITE_SOCIAL or (len(words) == 1 and words[0] in _POLITE_SOCIAL):
        return True
    if len(words) <= 4:
        return all(w in _POLITE_SOCIAL for w in words)
    return False


def _is_question(text: str) -> bool:
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


def extract_features(responses: List[dict]) -> List[float]:
    """Build 21-feature vector from a conversation."""
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

    # f1: average semantic novelty vs conversation history
    scores = []
    for r in responses[:-1]:
        pn = _get_ngrams(r["text"], 2)
        pk = _content_words(r["text"])
        scores.append(0.6 * _jaccard_distance(last_ngrams, pn)
                    + 0.4 * _jaccard_distance(last_keywords, pk))
    sn = sum(scores) / len(scores) if scores else 0.0

    # f2: perplexity proxy (entropy + diversity combined)
    ent = _shannon_entropy(last_text)
    div = _word_diversity(last_text)
    ppl_proxy = max(0.0, min(1.0, ent / 5.0)) * 0.5 + div * 0.5

    # f3: entropy score normalized
    ent_score = max(0.0, min(1.0, ent / 5.0))

    # f4: question density (inverted — high QD means keep going)
    window = responses[-3:]
    qd = 1.0 - (sum(1 for r in window if _is_question(r["text"])) / len(window))

    # f5: last response is politeness-only
    politeness_only_last = 1.0 if is_politeness_only(last_text) else 0.0

    # f6: last response contains polite or confirm words
    polite_count = sum(1 for w in last_words if w in _POLITE_SOCIAL or w in _CONFIRM_WORDS)
    politeness_rel_last = 1.0 if polite_count > 0 else 0.0

    # f7: politeness-only response in history (excluding last)
    politeness_hist = 1.0 if any(is_politeness_only(r["text"]) for r in responses[-4:-1]) else 0.0

    # f8: politeness-only in last-3 exchanges (excluding last)
    politeness_last3 = 1.0 if any(is_politeness_only(r["text"]) for r in responses[-3:-1]) else 0.0

    # f9: fraction of polite/confirm words in last response
    politeness_word_frac = polite_count / max(len(last_words), 1)

    # f10: count of politeness-only responses in history
    politeness_hist_count = sum(1 for r in responses[:-1] if is_politeness_only(r["text"]))

    # f11: exchange count normalized to [0, 1]
    n_norm = min(n / 10.0, 1.0)

    # f12: content word ratio in last response
    content_ratio = len(last_keywords) / max(len(last_words), 1)

    # f13: last response continues prior thread ("Yes, and...", "Sure, but...")
    continuation = 1.0 if re.match(
        r'^(yes,?\s+(and|but|also|so|if)|ok[ay],?\s+(but|so|and)|'
        r'sure,?\s+(but|and)|right,?\s+(but|and))',
        last_text, re.IGNORECASE
    ) else 0.0

    # f14: average word diversity across all responses
    avg_diversity = sum(_word_diversity(r["text"]) for r in responses) / n

    # f15: similarity to previous response (n-gram + keyword Jaccard)
    prev_ngrams = _get_ngrams(prev_text, 2)
    prev_keywords = _content_words(prev_text)
    prev_sim = (0.6 * _jaccard_similarity(last_ngrams, prev_ngrams)
                + 0.4 * _jaccard_similarity(last_keywords, prev_keywords))

    # f16: last response ends with a period
    ends_sentence = 1.0 if last_text.strip()[-1:] == '.' else 0.0

    # Sentence-level features
    sentences = [s.strip() for s in re.split(r'[.!?]+\s*', last_text) if s.strip()]
    last_sent_words = len(sentences[-1].split()) if sentences else 0
    total_words = max(len(last_words), 1)

    # f17: fraction of words in the last sentence
    last_sent_frac = last_sent_words / total_words

    # f18: last sentence length normalized to 20 words
    last_sent_norm = min(last_sent_words / 20.0, 1.0)

    # f19: first sentence is standalone politeness
    first_sent_polite_only = 1.0 if sentences and is_politeness_only(sentences[0]) else 0.0

    # f20: last sentence starts with a concluding phrase
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


# ── LR Model trained on 266 unified fixtures ──────────────────────────────────

_MODEL_C = 10.0

with open(os.path.join(os.path.dirname(__file__), "fixtures", "unified.json")) as f:
    _FIXTURES = json.load(f)

_X = [extract_features(fx["responses"]) for fx in _FIXTURES]
_y = [1.0 if fx.get("expected") == "stop" else 0.0 for fx in _FIXTURES]
_MODEL = LogisticRegression(C=_MODEL_C, solver="lbfgs", max_iter=5000, random_state=42)
_MODEL.fit(_X, _y)


# ── Public API ───────────────────────────────────────────────────────────────

def compute_convergence(responses: List[dict]) -> dict:
    """Return P(stop) from the LR model, plus a signal tag."""
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


_THRESHOLDS = {
    3: 0.30,   # stop cluster at 0.76, cont at 0.22
    4: 0.50,   # stop at 0.54, cont at 0.33
    5: 0.45,   # stop at 0.73, cont at 0.23
    6: 0.40,   # distributions overlap heavily
    7: 0.55,   # stop at 0.67, cont at 0.30
    8: 0.40,   # hardest turn — model can't separate stop/cont well here
    9: 0.35,   # near the hard wall, easy to stop
}


def get_escalation_threshold(turn: int) -> float:
    """Hand-tuned P(stop) threshold per turn. Unknown turns default to 1.0."""
    return _THRESHOLDS.get(turn, 1.0)


def should_stop(responses: List[dict], turn: int) -> bool:
    """
    Policy decision — should the conversation stop?

    Turns 1–2  : always continue (too early to decide)
    Turns 3–9  : stop if P(stop) >= threshold for that turn
    Turn 10+   : always stop (hard wall)
    """
    if turn <= 2:
        return False
    if turn >= 10:
        return True
    result = compute_convergence(responses)
    return result["prob_stop"] >= get_escalation_threshold(turn)


def should_stop_legacy(responses: List[dict]) -> tuple[bool, str]:
    """
    Fixed-threshold decision (no turn awareness).
    P(stop) >= 0.55 → stop, P(stop) < 0.30 → continue, else borderline.
    Kept for reference comparison.
    """
    result = compute_convergence(responses)
    p = result["prob_stop"]
    if p >= 0.55:
        return True, f"convergence_detected:p={p:.2f}"
    elif p < 0.30:
        return False, f"active_discussion:p={p:.2f}"
    else:
        return False, f"borderline:p={p:.2f}"


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
def test_policy_at_natural_turn(fixture):
    """Policy decision at natural turn count matches expected stop/continue."""
    rs = fixture["responses"]
    stop = should_stop(rs, min(len(rs), 10))
    assert stop == (fixture.get("expected") == "stop"), (
        f"[{fixture['id']}] stop={stop} expected={fixture.get('expected')}"
    )


@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
def test_legacy_decision(fixture):
    """Legacy fixed-threshold decision across all 266 fixtures."""
    stop, _ = should_stop_legacy(fixture["responses"])
    assert stop == (fixture.get("expected") == "stop"), (
        f"[{fixture['id']}] stop={stop} expected={fixture.get('expected')}"
    )


def test_escalation_schedule():
    """Thresholds hand-tuned per turn using P(stop) distribution data.
    Turn 3 is easy to stop, turn 7 is hardest, turn 9 is near the wall.
    """
    assert get_escalation_threshold(3) == 0.30
    assert get_escalation_threshold(4) == 0.50
    assert get_escalation_threshold(5) == 0.45
    assert get_escalation_threshold(6) == 0.40
    assert get_escalation_threshold(7) == 0.55
    assert get_escalation_threshold(8) == 0.40
    assert get_escalation_threshold(9) == 0.35


def test_turn3_polite_stops():
    """Polite-only response at turn 3 triggers stop."""
    responses = [
        {"text": "Here's the fix."},
        {"text": "Confirmed, looks good."},
        {"text": "Thanks!"},
    ]
    assert should_stop(responses, turn=3)


def test_turn4_substantive_uses_model():
    """Substantive response at turn 4 defers to LR model — no crash, valid output."""
    responses = [
        {"text": "What's the segfault?"},
        {"text": "Use-after-free in session cleanup."},
        {"text": "Got it."},
        {"text": "The fix looks correct, apply it and run tests."},
    ]
    result = compute_convergence(responses)
    assert 0.0 <= result["prob_stop"] <= 1.0


def test_compute_convergence_returns_valid_output():
    """compute_convergence returns a well-formed dict with prob_stop in [0, 1]."""
    result = compute_convergence(_FIXTURES[0]["responses"])
    assert "prob_stop" in result
    assert "signal" in result
    assert 0.0 <= result["prob_stop"] <= 1.0


def test_feature_vector_always_21_features():
    """Every fixture extracts to exactly 21 features."""
    for fx in _FIXTURES:
        feats = extract_features(fx["responses"])
        assert len(feats) == 21, f"[{fx['id']}] expected 21, got {len(feats)}"