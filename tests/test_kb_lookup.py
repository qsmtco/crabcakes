# tests/test_kb_lookup.py
# Unit tests for agent.kb_lookup.
#
# Strategy: tests do NOT load the 130MB embedding model from disk. They
# monkeypatch _load_model() to a no-op, then pre-fill module state with
# synthetic 384-dim vectors (matching the real model's output dim) and a
# fake encoder. This tests the retrieval logic (cosine sim, top-K,
# min_score, sorting, metadata, fail-soft) without the 22s model load.
#
# One integration-style test (test_real_index_retrieval_makes_sense) is
# gated on the real index existing on disk; it loads the real model.

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_index(tmp_path, monkeypatch):
    """Create a tiny index and a fake model; wire them into kb_lookup state.

    Returns (chunks, embeddings, fake_model) for direct inspection.
    The fake model returns whatever vectors the test puts in its lookup dict.
    """
    from agent import kb_lookup

    chunks = [
        {"id": "a.md#0.0", "source": "knowledge/a.md", "section": "Section A",
         "text": "How to install CrabCakes on Linux Ubuntu using apt-get."},
        {"id": "b.md#0.0", "source": "knowledge/b.md", "section": "Section B",
         "text": "Configure the OpenClaw gateway URL in agent.json."},
        {"id": "c.md#0.0", "source": "knowledge/c.md", "section": "Section C",
         "text": "What is the capital of France and its population?"},
    ]
    # 384-dim synthetic vectors (match the real model's dim), L2-normalized.
    # Each vector has a distinct "direction" so cosine sim is well-behaved.
    rng = np.random.default_rng(seed=42)
    vecs = rng.standard_normal((3, 384)).astype("float32")
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    embeddings = vecs

    index_dir = tmp_path / ".index"
    index_dir.mkdir()
    with open(index_dir / "chunks.json", "w") as f:
        json.dump(chunks, f)
    np.save(str(index_dir / "embeddings.npy"), embeddings)

    # Point kb_lookup at the temp index.
    monkeypatch.setattr(kb_lookup, "_INDEX_DIR", index_dir)
    monkeypatch.setattr(kb_lookup, "_CHUNKS_FILE", index_dir / "chunks.json")
    monkeypatch.setattr(kb_lookup, "_EMBEDDINGS_FILE", index_dir / "embeddings.npy")
    # Bypass the real model loader entirely.
    monkeypatch.setattr(kb_lookup, "_load_model", lambda name: None)
    # Reset state so the next call re-loads from the new index files.
    kb_lookup.reset_cache()

    class FakeModel:
        def __init__(self):
            self.lookup: dict[str, np.ndarray] = {}
            self.load_count = 0
        def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False):
            self.load_count += 1
            assert len(texts) == 1
            text = texts[0]
            if text not in self.lookup:
                raise KeyError(f"No fake embedding for question: {text!r}")
            return np.array([self.lookup[text]], dtype="float32")

    fake = FakeModel()
    return chunks, embeddings, fake


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_returns_empty_when_index_missing(tmp_path, monkeypatch):
    """If the index files don't exist, kb_lookup returns []."""
    from agent import kb_lookup
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(kb_lookup, "_INDEX_DIR", empty_dir)
    monkeypatch.setattr(kb_lookup, "_CHUNKS_FILE", empty_dir / "chunks.json")
    monkeypatch.setattr(kb_lookup, "_EMBEDDINGS_FILE", empty_dir / "embeddings.npy")
    monkeypatch.setattr(kb_lookup, "_load_model", lambda name: None)
    kb_lookup.reset_cache()

    assert kb_lookup.kb_lookup("anything") == []


def test_returns_empty_for_empty_or_whitespace_question(synthetic_index):
    """Empty / whitespace questions are no-ops, return []."""
    from agent import kb_lookup
    assert kb_lookup.kb_lookup("") == []
    assert kb_lookup.kb_lookup("   ") == []
    assert kb_lookup.kb_lookup("\n\t") == []


def test_returns_top_k_chunks_sorted_by_score_desc(synthetic_index):
    """Top-K results come back sorted by score, highest first.

    Note: with random 384-dim unit vectors, the "unrelated" chunks have
    small or slightly negative cosine sims with the query. We use
    min_score=-1.0 to include all chunks regardless of their sim sign.
    """
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    # Query: identical to chunk A's vector → score 1.0 for A.
    fake.lookup["install ubuntu"] = embeddings[0].copy()
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    results = kb_lookup.kb_lookup("install ubuntu", top_k=3, min_score=-1.0)
    assert len(results) == 3
    assert results[0].score >= results[1].score >= results[2].score
    assert results[0].source == "knowledge/a.md"
    assert results[0].id == "a.md#0.0"
    assert results[0].section == "Section A"
    assert "install" in results[0].text


def test_filters_chunks_below_min_score(synthetic_index):
    """Chunks below min_score are filtered out."""
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    # Query: zero vector → score 0.0 for all chunks (cosine sim with 0 vec is undefined,
    # but the model.encode() returns zeros, so dot product is 0 for all).
    fake.lookup["unrelated"] = np.zeros((384,), dtype="float32")
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    # With min_score=0.5, expect 0 results (all scores are ~0).
    results = kb_lookup.kb_lookup("unrelated", top_k=3, min_score=0.5)
    assert results == []


def test_caches_model_across_calls(synthetic_index, monkeypatch):
    """The model is not re-loaded between calls."""
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    load_count = {"n": 0}

    def counting_load(name):
        load_count["n"] += 1

    monkeypatch.setattr(kb_lookup, "_load_model", counting_load)

    # Pre-fill state as "already loaded with the default model name".
    fake.lookup["q1"] = embeddings[0].copy()
    fake.lookup["q2"] = embeddings[1].copy()
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    kb_lookup.kb_lookup("q1", min_score=0.0)
    kb_lookup.kb_lookup("q2", min_score=0.0)
    assert load_count["n"] == 0


def test_chunk_metadata_is_correct(synthetic_index):
    """Returned KBChunk has id, source, section, text, score fields populated."""
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    fake.lookup["q"] = embeddings[0].copy()
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    results = kb_lookup.kb_lookup("q", top_k=1, min_score=0.0)
    assert len(results) == 1
    c = results[0]
    assert c.id == "a.md#0.0"
    assert c.source == "knowledge/a.md"
    assert c.section == "Section A"
    assert c.text.startswith("How to install")
    assert isinstance(c.score, float)
    assert 0.0 <= c.score <= 1.0


def test_unrelated_question_returns_empty(synthetic_index):
    """A question with no embedding in the fake model → empty list (fail-soft)."""
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    # Empty lookup dict → encode() raises KeyError.
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    results = kb_lookup.kb_lookup("totally unknown question", top_k=3, min_score=0.3)
    assert results == []


def test_question_and_chunk_use_same_model(synthetic_index):
    """Sanity: query vector == chunk a's vector → score should be 1.0."""
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    fake.lookup["q"] = embeddings[0].copy()
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    results = kb_lookup.kb_lookup("q", top_k=1, min_score=0.0)
    assert len(results) == 1
    assert results[0].source == "knowledge/a.md"
    assert results[0].score == pytest.approx(1.0, abs=1e-5)


def test_top_k_limits_results(synthetic_index):
    """top_k=1 returns only the single best match."""
    from agent import kb_lookup
    from agent.kb_lookup import _DEFAULT_MODEL
    chunks, embeddings, fake = synthetic_index

    fake.lookup["q"] = embeddings[0].copy()
    kb_lookup._state["chunks"] = chunks
    kb_lookup._state["embeddings"] = embeddings
    kb_lookup._state["model"] = fake
    kb_lookup._state["model_name"] = _DEFAULT_MODEL
    kb_lookup._state["loaded"] = True

    results = kb_lookup.kb_lookup("q", top_k=1, min_score=0.0)
    assert len(results) == 1
    assert results[0].source == "knowledge/a.md"


# ── Integration test (gated on real index existing) ───────────────────────────

REAL_INDEX = Path("/home/q/projects/crabcakes/knowledge/.index")
REAL_INDEX_AVAILABLE = (
    (REAL_INDEX / "chunks.json").is_file()
    and (REAL_INDEX / "embeddings.npy").is_file()
)


@pytest.mark.skipif(
    not REAL_INDEX_AVAILABLE,
    reason="Real index not built (run scripts/rebuild_kb_index.py first)",
)
def test_real_index_retrieval_makes_sense():
    """Smoke test against the real index. Loads the real model (~22s first time)."""
    from agent import kb_lookup

    # Reset state so the real model loads fresh (prior tests may have
    # injected a fake model into the module state).
    kb_lookup.reset_cache()

    results = kb_lookup.kb_lookup("How do I install CrabCakes?", top_k=2, min_score=0.2)
    assert len(results) >= 1, "Expected at least 1 result for install question"
    top_sources = {r.source for r in results}
    assert any("setup.md" in s or "install.md" in s for s in top_sources), \
        f"Top results should include setup.md or install.md, got: {top_sources}"
