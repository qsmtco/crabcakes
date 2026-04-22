"""
converge — Conversation convergence detection for multi-agent AI systems.

Determines when a multi-agent conversation has naturally ended, without
relying on a hard turn limit. A Random Forest classifies stop/continue
based on 10 conversational signals extracted from the conversation history.

====================================================================
ARCHITECTURE OVERVIEW
====================================================================

converge sits between your orchestrator and your agent loop.
Every time an agent responds, you call should_stop(responses, turn).
It returns True (stop) or False (continue).

The decision is made by three stacked rules:

  Layer 1 — Hard wall
    Turn ≥ 15: always stop. This is the last resort. If a conversation
    runs 15 rounds without converging, it is not going to — stop it.
    This protects against runaway loops.

  Layer 2 — Model decision
    Turns 3–14: use the Random Forest. If P(stop) >= 0.50, stop.
    The model reads 10 signals from the conversation and returns a
    probability. 0.50 is the decision boundary — balanced between
    stopping too early and letting conversations run too long.

  Layer 3 — QAC form
    Turn ≤ 2: always continue. A complete exchange needs at least
    3 turns (question → answer → acknowledge). Stopping at turn 1
    or 2 means cutting off the acknowledgment, which reads as rude
    or broken to the user.

====================================================================
THE 10 SIGNALS (FEATURES)
====================================================================

The Random Forest reads these from the conversation:

  f0  ent_score      — Shannon entropy of last response, normalized to [0,1].
                        High entropy = diverse, substantive vocabulary.
                        Low entropy = repetitive, brief, or mechanical.

  f1  ppl_proxy      — Perplexity proxy: entropy × word diversity.
                        Combines both into one signal. Conversations
                        that are done tend to be shorter and less varied.

  f2  avg_diversity   — Average word diversity (unique/total) across
                        all responses in the conversation. Substantive
                        multi-turn conversations maintain diversity.

  f3  len_trend       — Last response length relative to the conversation
                        average. Stopped conversations truncate — the
                        final response is shorter than average.

  f4  content_ratio  — Fraction of content words (non-stopwords) in the
                        last response. High ratio = substantive.

  f5  polite_frac     — Fraction of polite/confirm words in last response.
                        "Thanks", "confirmed", "done" — polite endings.

  f6  last_sent_norm — Length of the last sentence, normalized to 20 words.
                        Short closing sentences are a strong stop signal.

  f7  last_sent_frac — What fraction of the last response is in the
                        final sentence. One short final sentence = likely done.

  f8  tfidf_prev_sim — TF-IDF cosine similarity between last and previous
                        response. Low = topic shifted, possibly closing.
                        High = still engaged in same thread.

  f9  tfidf_hist_sim — TF-IDF cosine similarity between last response
                        and the average of all prior responses.
                        Low = different from the whole history = closing.

====================================================================
WHY TF-IDF COSINE?
====================================================================

TF-IDF (Term Frequency–Inverse Document Frequency) converts text into
a vector of word weights. Each dimension corresponds to a vocabulary
term. The weight of a term increases with how often it appears and
decreases with how common it is across documents.

Cosine similarity measures the angle between two TF-IDF vectors.
A value of 1.0 means identical word distributions.
A value near 0 means very different word distributions.

Unlike simple word overlap (Jaccard), TF-IDF downweights common words
and upweights distinctive ones. "Confirmed" in a 3-word response gets
a high TF-IDF weight because it's rare and significant.

====================================================================
PUBLIC API
====================================================================

  compute_convergence(responses)
    → {"prob_stop": float, "signal": str}
    Core classification. Returns P(stop) in [0, 1] and a signal tag.

  should_stop(responses, turn)
    → bool
    Policy wrapper. Applies all three layers: QAC → model → hard wall.

  should_stop_legacy(responses)
    → tuple[bool, str]
    Fixed-threshold reference for comparison. Not used by the policy.
    Kept for testing and benchmarking.

====================================================================
USAGE EXAMPLE
====================================================================

  from converge import should_stop

  responses = [
      {"text": "What's the segfault?"},
      {"text": "Use-after-free in session cleanup."},
      {"text": "Got it."},
      {"text": "Applied the fix, tests pass."},
  ]

  turn = len(responses)  # orchestrator tracks this
  if should_stop(responses, turn):
      end_conversation()

====================================================================
DEPENDENCIES
====================================================================

  pip install scikit-learn numpy joblib
No GPU, no cloud API, no external service. Everything runs locally.
The model and TF-IDF vectorizer are pre-trained and shipped as .pkl
files. They are loaded at import time — no training on startup.
"""

from __future__ import annotations

import math
import re
from typing import List

import joblib
import numpy as np


# ── Constants ────────────────────────────────────────────────────────────────

# Short phrases that carry no substantive information.
# Used to detect "politeness-only" responses — a closing signal.
_POLITE_SOCIAL = {
    "thanks", "thank you", "you're welcome", "anytime", "happy to help",
    "of course", "certainly", "no problem", "my pleasure", "you got it",
    "no worries", "no problem at all", "sure thing", "exactly", "indeed", "yes",
}

# Words that affirm, confirm, or close a thread.
# Appear frequently in closing responses alongside polite phrases.
_CONFIRM_WORDS = {
    "yes", "no", "right", "ok", "okay", "correct", "exact", "agreed",
    "done", "confirmed", "indeed", "do",
}

# Common English stopwords. Stripped before computing content words so
# that "the" and "a" don't pollute content similarity scores.
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


# ── Pre-trained model artifacts ────────────────────────────────────────────

_MODEL  = joblib.load(__file__.rsplit("/", 1)[0] + "/model.pkl")
_TFIDF  = joblib.load(__file__.rsplit("/", 1)[0] + "/vectorizer.pkl")


# ── Politeness detection ────────────────────────────────────────────────────

def is_politeness_only(text: str) -> bool:
    """
    Detect a response that is pure social politeness with no task content.

    Examples that return True:
      "Thanks!"
      "You're welcome."
      "Happy to help!"

    Examples that return False:
      "Thanks, I applied the fix."  (has content after polite opener)
      "No problem, let me know if it happens again."

    Logic:
      - Strip trailing punctuation, lowercase
      - If the whole thing is a known polite phrase → True
      - If 4 or fewer words and all are in the polite set → True
      - Otherwise → False
    """
    # Normalise: remove trailing punctuation, collapse internal punctuation to space
    t = re.sub(r'[.,!?]+$', '', text.lower().strip())
    t = re.sub(r'[.,]+', ' ', t).strip()
    words = t.split()
    if not words:
        return False
    # Full phrase match
    if t in _POLITE_SOCIAL:
        return True
    # Single-word polite
    if len(words) == 1 and words[0] in _POLITE_SOCIAL:
        return True
    # Short all-polite
    if len(words) <= 4 and all(w in _POLITE_SOCIAL for w in words):
        return True
    return False


# ── Text statistics helpers ────────────────────────────────────────────────

def _shannon_entropy(text: str) -> float:
    """
    Compute Shannon entropy of the word distribution in text.

    Entropy is high when words are evenly distributed (many different
    words, each appearing roughly equally often). Entropy is low when
    one word dominates (e.g., repetitive responses).

    Formula: H = -sum(p_i * log2(p_i)) for each word frequency p_i.

    Returns 0.0 for empty text.
    """
    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return 0.0
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    n = len(words)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _word_diversity(text: str) -> float:
    """
    Ratio of unique words to total words.

    A response with 10 words, 8 of which are unique → diversity = 0.80.
    A response that repeats the same word 10 times → diversity = 0.10.

    High diversity correlates with substantive, varied language.
    Low diversity correlates with brief, mechanical, or closing responses.
    """
    words = re.findall(r'\b\w+\b', text.lower())
    if not words:
        return 0.0
    return len(set(words)) / len(words)


def _content_words(text: str) -> set:
    """
    Return words in text after stripping stopwords and short tokens.

    Content words are the semantically meaningful vocabulary.
    Used for computing content_ratio and content-based similarity.
    """
    return {w for w in re.findall(r'\b\w+\b', text.lower())
            if w not in _STOPWORDS and len(w) > 2}


def _tfidf_cosine(a, b) -> float:
    """
    Cosine similarity between two TF-IDF vectors.

    Cosine similarity = (A · B) / (||A|| × ||B||)
    Ranges from 0 (completely different) to 1 (identical).

    Handles both sparse matrices (sklearn TF-IDF output) and dense
    arrays. If either vector is zero, returns 0.0.
    """
    # Sparse matrices have .toarray(); dense arrays are already arrays
    a_d = np.asarray(a.toarray()).flatten() if hasattr(a, 'toarray') else np.asarray(a).flatten()
    b_d = np.asarray(b.toarray()).flatten() if hasattr(b, 'toarray') else np.asarray(b).flatten()
    norm = np.linalg.norm(a_d) * np.linalg.norm(b_d)
    if norm == 0.0:
        return 0.0
    return float(np.dot(a_d, b_d) / norm)


# ── Feature extraction ─────────────────────────────────────────────────────

def extract_features(responses: List[dict]) -> List[float]:
    """
    Convert a conversation into a 10-dimensional feature vector.

    The vector is the input to the Random Forest. Each dimension
    captures a different signal of conversation convergence.

    Feature order (must match training):
      [f0]  ent_score      — entropy, normalized to [0, 1]
      [f1]  ppl_proxy      — entropy × diversity combined signal
      [f2]  avg_diversity  — diversity across all turns
      [f3]  len_trend      — last length vs conversation average
      [f4]  content_ratio — content words / total words in last response
      [f5]  polite_frac    — polite/confirm words / total words
      [f6]  last_sent_norm — last sentence length / 20
      [f7]  last_sent_frac  — last sentence words / total words
      [f8]  tfidf_prev_sim — TF-IDF cosine, last vs previous
      [f9]  tfidf_hist_sim — TF-IDF cosine, last vs history average

    Arguments:
      responses — list of dicts, each with a "text" key.
                   At least 1 response required.

    Returns:
      List[float]: 10 floats in [0, 1] (mostly), representing the
      conversational signals.
    """
    n = len(responses)
    last = responses[-1]
    prev = responses[-2] if n >= 2 else responses[-1]
    last_text = last["text"]
    prev_text = prev["text"]
    last_words = re.sub(r'[.,!?]+$', '', last_text.lower().strip()).split()

    # ── f0: entropy score ────────────────────────────────────────────────
    # Entropy of last response, capped at 5.0 and normalized to [0, 1].
    # A value of 5.0 represents a maximally diverse 5-word response.
    ent = _shannon_entropy(last_text)
    ent_score = max(0.0, min(1.0, ent / 5.0))

    # ── f1: perplexity proxy ─────────────────────────────────────────────
    # Combines entropy and diversity into one signal. Weights them
    # equally (0.5 each). Substantive responses score high on both.
    div = _word_diversity(last_text)
    ppl_proxy = max(0.0, min(1.0, ent / 5.0)) * 0.5 + div * 0.5

    # ── f2: average word diversity across all responses ─────────────────
    # Measures whether the conversation as a whole is substantive.
    # Long investigations maintain word diversity throughout.
    avg_diversity = sum(_word_diversity(r["text"]) for r in responses) / n

    # ── f3: length trend ────────────────────────────────────────────────
    # How does the last response length compare to the conversation average?
    # Positive → last response is longer than average (still going strong)
    # Negative → last response is shorter than average (wrapping up)
    lens = [len(r["text"]) for r in responses]
    avg_len = sum(lens) / len(lens)
    len_trend = (lens[-1] - avg_len) / max(avg_len, 1)

    # ── f4: content word ratio ──────────────────────────────────────────
    # Fraction of words in the last response that are content words
    # (not stopwords). High ratio = substantive, task-focused response.
    last_keywords = _content_words(last_text)
    content_ratio = len(last_keywords) / max(len(last_words), 1)

    # ── f5: polite/confirm word fraction ──────────────────────────────
    # Fraction of polite or confirm words in the last response.
    # Closing responses tend to have more of these.
    polite_count = sum(
        1 for w in last_words
        if w in _POLITE_SOCIAL or w in _CONFIRM_WORDS
    )
    polite_frac = polite_count / max(len(last_words), 1)

    # ── f6–f7: last sentence shape ───────────────────────────────────────
    # Split the last response into sentences. Look at the final one.
    # Short final sentences are a strong closing signal.
    sentences = [
        s.strip() for s in re.split(r'[.!?]+\s*', last_text)
        if s.strip()
    ]
    last_sent_words = len(sentences[-1].split()) if sentences else 0
    total_words = max(len(last_words), 1)

    # f6: last sentence length, normalized to a 20-word baseline
    last_sent_norm = min(last_sent_words / 20.0, 1.0)
    # f7: what fraction of the total response is in the last sentence
    last_sent_frac = last_sent_words / total_words

    # ── f8: TF-IDF cosine, last vs previous ────────────────────────────
    # If the last response uses the same vocabulary as the previous one,
    # the cosine similarity is high → still on the same topic → continue.
    # Low cosine similarity → topic shifted or winding down → stop.
    last_vec = _TFIDF.transform([last_text])
    prev_vec = _TFIDF.transform([prev_text])
    tfidf_prev_sim = _tfidf_cosine(last_vec, prev_vec)

    # ── f9: TF-IDF cosine, last vs history average ───────────────────────
    # Compare the last response to the average vocabulary of all prior
    # responses. Low similarity to history = a concluding shift = stop.
    tfidf_hist_sim = 0.0
    if n > 1:
        prior_texts = [r["text"] for r in responses[:-1]]
        prior_vecs = _TFIDF.transform(prior_texts)
        sims = [_tfidf_cosine(last_vec, pv) for pv in prior_vecs]
        tfidf_hist_sim = sum(sims) / len(sims)

    return [
        ent_score,        # f0
        ppl_proxy,        # f1
        avg_diversity,    # f2
        len_trend,        # f3
        content_ratio,    # f4
        polite_frac,      # f5
        last_sent_norm,   # f6
        last_sent_frac,   # f7
        tfidf_prev_sim,  # f8
        tfidf_hist_sim,   # f9
    ]


# ── Core classification ─────────────────────────────────────────────────

def compute_convergence(responses: List[dict]) -> dict:
    """
    Run the Random Forest on a conversation and return a result.

    This is the core classification function. It extracts the
    10 features from the conversation and runs them through the
    pre-trained Random Forest to get P(stop).

    Arguments:
      responses — list of dicts, each with a "text" key.

    Returns:
      {
        "prob_stop": float,   # P(stop) in [0, 1]
        "signal": str,        # "polite" if last response is polite-only
                              # "neutral" otherwise
      }
    """
    feats = extract_features(responses)
    # [:, 1] is the probability of class 1 = "stop"
    p_stop = float(_MODEL.predict_proba([feats])[0][1])
    last = responses[-1]["text"]
    signal = "polite" if is_politeness_only(last) else "neutral"
    return {"prob_stop": p_stop, "signal": signal}


# ── Policy decisions ─────────────────────────────────────────────────────

def should_stop(responses: List[dict], turn: int) -> bool:
    """
    Should the conversation stop?

    Layer 3 — QAC form:
      Turn ≤ 2: always continue. A complete exchange needs at least
      3 turns: question → answer → acknowledge. Stopping at turn 1
      or 2 cuts off the acknowledgment and reads as broken.

    Layer 2 — Model decision:
      Turns 3–14: stop if P(stop) >= 0.50. The Random Forest is the
      primary decision-maker here. 0.50 is a balanced threshold —
      it divides the decision boundary evenly.

    Layer 1 — Hard wall:
      Turn ≥ 15: always stop. This is the last resort. If a conversation
      runs 15 rounds without converging naturally, it is not going to.
      Stopping it prevents runaway loops.

    Arguments:
      responses — list of dicts, each with a "text" key
      turn      — current orchestrator turn (1-indexed). Typically
                  len(responses) when called after each agent response.

    Returns:
      bool: True = stop, False = continue
    """
    if turn <= 2:
        return False  # QAC: don't stop before the acknowledgment
    if turn >= 15:
        return True   # Hard wall: last resort
    result = compute_convergence(responses)
    return result["prob_stop"] >= 0.50


def should_stop_legacy(responses: List[dict]) -> tuple[bool, str]:
    """
    Fixed-threshold reference implementation.

    Used for comparison and benchmarking. Not used by the policy.

    Three zones:
      P(stop) >= 0.55  → "convergence_detected" — stop
      P(stop) <  0.30  → "active_discussion"  — continue
      otherwise         → "borderline"           — continue (but flagged)

    Returns:
      (stop: bool, signal: str)
    """
    result = compute_convergence(responses)
    p = result["prob_stop"]
    if p >= 0.55:
        return True, f"convergence_detected:p={p:.2f}"
    elif p < 0.30:
        return False, f"active_discussion:p={p:.2f}"
    else:
        return False, f"borderline:p={p:.2f}"
