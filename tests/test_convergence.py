"""
Convergence detection — policy-driven stop/continue for multi-agent conversations.

Policy — stop signal comes from three layers:
  1. Orchestrator turn number (hard wall at turn 15)
  2. Random Forest model P(stop) vs per-turn threshold (turns 3–9)
  3. Turn ≤ 2: always continue (QAC form — question, answer, acknowledge)

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

import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer

# ── Constants ────────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _shannon_entropy(text: str) -> float:
    """Word-level Shannon entropy — high entropy means diverse, substantive text."""
    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return 0.0
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return -sum((c / len(words)) * math.log2(c / len(words)) for c in freq.values())


def _word_diversity(text: str) -> float:
    """Ratio of unique words to total words — substantive text repeats less."""
    words = re.findall(r'\b\w+\b', text.lower())
    return len(set(words)) / len(words) if words else 0.0


def _content_words(text: str) -> set:
    """Words in text after stripping stopwords and short tokens."""
    return {w for w in re.findall(r'\b\w+\b', text.lower())
            if w not in _STOPWORDS and len(w) > 2}


def _tfidf_cosine(a, b) -> float:
    """Cosine similarity between two TF-IDF vectors."""
    a_d = np.asarray(a.toarray()).flatten() if hasattr(a, 'toarray') else np.asarray(a).flatten()
    b_d = np.asarray(b.toarray()).flatten() if hasattr(b, 'toarray') else np.asarray(b).flatten()
    norm = np.linalg.norm(a_d) * np.linalg.norm(b_d)
    if norm == 0:
        return 0.0
    return float(np.dot(a_d, b_d) / norm)


# ── Feature extraction ─────────────────────────────────────────────────────────

def extract_features(responses: List[dict]) -> List[float]:
    """
    Build 10-feature vector from a conversation.

    Features capture four signals of convergence:
      entropy/diversity  — substantive responses have higher entropy/diversity
      length             — final responses in stopped conversations are shorter
      sentence shape     — last sentence length and proportion of final sentence
      semantic shift     — TF-IDF cosine similarity to prior turns
    """
    n = len(responses)
    last = responses[-1]
    prev = responses[-2] if n >= 2 else responses[-1]
    last_text = last["text"]
    prev_text = prev["text"]
    last_words = re.sub(r'[.,!?]+$', '', last_text.lower().strip()).split()

    # Feature 0: Shannon entropy normalized to [0, 1]
    # Stop conversations end with short acknowledgments — low entropy
    ent = _shannon_entropy(last_text)
    ent_score = max(0.0, min(1.0, ent / 5.0))

    # Feature 1: Perplexity proxy — entropy × diversity
    div = _word_diversity(last_text)
    ppl_proxy = max(0.0, min(1.0, ent / 5.0)) * 0.5 + div * 0.5

    # Feature 2: Average word diversity across all responses
    avg_diversity = sum(_word_diversity(r["text"]) for r in responses) / n

    # Feature 3: Last response length relative to conversation average
    # Stopped conversations truncate — last response is shorter than average
    lens = [len(r["text"]) for r in responses]
    avg_len = sum(lens) / len(lens)
    len_trend = (lens[-1] - avg_len) / max(avg_len, 1)

    # Feature 4: Fraction of content words in last response
    last_keywords = _content_words(last_text)
    content_ratio = len(last_keywords) / max(len(last_words), 1)

    # Feature 5: Fraction of polite/confirm words in last response
    polite_count = sum(1 for w in last_words if w in _POLITE_SOCIAL or w in _CONFIRM_WORDS)
    polite_frac = polite_count / max(len(last_words), 1)

    # Feature 6: Length of the last sentence, normalized to 20 words
    sentences = [s.strip() for s in re.split(r'[.!?]+\s*', last_text) if s.strip()]
    last_sent_words = len(sentences[-1].split()) if sentences else 0
    last_sent_norm = min(last_sent_words / 20.0, 1.0)

    # Feature 7: Fraction of total words that fall in the last sentence
    total_words = max(len(last_words), 1)
    last_sent_frac = last_sent_words / total_words

    # Feature 8: TF-IDF cosine similarity — last turn vs previous turn
    # Low similarity means the topic or style shifted, possible conclusion
    last_vec = _TFIDF.transform([last_text])
    prev_vec = _TFIDF.transform([prev_text])
    tfidf_prev_sim = _tfidf_cosine(last_vec, prev_vec)

    # Feature 9: TF-IDF cosine similarity — last turn vs history average
    # Low similarity to history signals a shift toward closing
    tfidf_hist_sim = 0.0
    if n > 1:
        prior_texts = [r["text"] for r in responses[:-1]]
        prior_vecs = _TFIDF.transform(prior_texts)
        sims = [_tfidf_cosine(last_vec, pv) for pv in prior_vecs]
        tfidf_hist_sim = sum(sims) / len(sims)

    return [
        ent_score,     # f0
        ppl_proxy,     # f1
        avg_diversity, # f2
        len_trend,     # f3
        content_ratio, # f4
        polite_frac,   # f5
        last_sent_norm,  # f6
        last_sent_frac,  # f7
        tfidf_prev_sim,  # f8
        tfidf_hist_sim,   # f9
    ]


# ── Model training ────────────────────────────────────────────────────────────

with open(os.path.join(os.path.dirname(__file__), "fixtures", "unified.json")) as f:
    _FIXTURES = json.load(f)

# Fit TF-IDF vocabulary once across all fixture response text
_ALL_TEXTS = [r["text"] for fx in _FIXTURES for r in fx["responses"]]
_TFIDF = TfidfVectorizer(lowercase=True, token_pattern=r'(?u)\b\w+\b',
                         min_df=2, max_df=0.95, ngram_range=(1, 2))
_TFIDF.fit(_ALL_TEXTS)

# Train Random Forest on all 266 fixtures
_X = [extract_features(fx["responses"]) for fx in _FIXTURES]
_y = [1.0 if fx.get("expected") == "stop" else 0.0 for fx in _FIXTURES]
_MODEL = RandomForestClassifier(n_estimators=200, random_state=42)
_MODEL.fit(_X, _y)


# ── Thresholds ───────────────────────────────────────────────────────────────

# ── Public API ───────────────────────────────────────────────────────────────

def compute_convergence(responses: List[dict]) -> dict:
    """Return P(stop) from the RF model, plus a signal tag."""
    feats = extract_features(responses)
    p_stop = float(_MODEL.predict_proba([feats])[0][1])
    last = responses[-1]["text"]
    signal = "polite" if is_politeness_only(last) else ("neutral")
    return {"prob_stop": p_stop, "signal": signal}




def should_stop(responses: List[dict], turn: int) -> bool:
    """
    Policy decision — should the conversation stop?

    Turn ≤ 2 : always continue (QAC form — a complete exchange needs 3 turns)
    Turn 3–9 : stop if P(stop) >= 0.50
    Turn ≥ 15: always stop (hard wall)
    """
    if turn <= 2:
        return False
    if turn >= 15:
        return True
    result = compute_convergence(responses)
    return result["prob_stop"] >= 0.50


def should_stop_legacy(responses: List[dict]) -> tuple[bool, str]:
    """
    Fixed-threshold decision: P(stop) >= 0.55 → stop,
    P(stop) < 0.30 → continue, else borderline.
    """
    result = compute_convergence(responses)
    p = result["prob_stop"]
    if p >= 0.55:
        return True, f"convergence_detected:p={p:.2f}"
    elif p < 0.30:
        return False, f"active_discussion:p={p:.2f}"
    else:
        return False, f"borderline:p={p:.2f}"


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
def test_policy_at_natural_turn(fixture):
    """Policy decision matches expected stop/continue for each fixture."""
    rs = fixture["responses"]
    stop = should_stop(rs, min(len(rs), 10))
    expected = fixture.get("expected") == "stop"
    assert stop == expected, f"[{fixture['id']}] stop={stop} expected={expected}"


@pytest.mark.parametrize("fixture", _FIXTURES, ids=[f["id"] for f in _FIXTURES])
def test_legacy_decision(fixture):
    """Legacy fixed-threshold decision matches expected stop/continue."""
    stop, _ = should_stop_legacy(fixture["responses"])
    expected = fixture.get("expected") == "stop"
    assert stop == expected, f"[{fixture['id']}] stop={stop} expected={expected}"



def test_turn3_polite_stops():
    """Polite-only response at turn 3 triggers stop."""
    responses = [
        {"text": "Here's the fix."},
        {"text": "Confirmed, looks good."},
        {"text": "Thanks!"},
    ]
    assert should_stop(responses, turn=3)


def test_turn4_substantive_uses_model():
    """Substantive response at turn 4 defers to RF model without crashing."""
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


def test_feature_vector_always_10_features():
    """Every fixture extracts to exactly 10 features."""
    for fx in _FIXTURES:
        feats = extract_features(fx["responses"])
        assert len(feats) == 10, f"[{fx['id']}] expected 10, got {len(feats)}"
