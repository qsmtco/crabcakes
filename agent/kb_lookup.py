# agent/kb_lookup.py
# Knowledge-base lookup — cosine-similarity retrieval over indexed KB chunks.
#
# Architecture:
#   - Pure Python — no GTK, no network at import time.
#   - Lazy-loads the Sentence-Transformers model and the index on first call.
#   - Module-level singleton state (model, index, chunks) cached across calls.
#   - Graceful degradation: if sentence_transformers is unavailable or the
#     index is missing, returns [] and logs a warning. The agent still works;
#     it just doesn't get KB grounding.
#
# Index format (produced by scripts/rebuild_kb_index.py):
#   knowledge/.index/chunks.json     — list of {id, source, section, text}
#   knowledge/.index/embeddings.npy  — float32 array, shape (N, 384)
#
# Public API:
#   KBChunk            — dataclass for a single retrieval result
#   kb_lookup()        — embed a question, return top-K chunks above min_score
#   is_index_available — bool, True if the index files exist on disk
#   get_index_path()   — Path to the index directory
#
# Usage:
#   from agent.kb_lookup import kb_lookup
#   chunks = kb_lookup("how do I install on Ubuntu?", top_k=3)
#   for c in chunks:
#       print(f"{c.score:.2f} {c.source} :: {c.section}")

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

# Project root: agent/kb_lookup.py is two levels deep from project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_INDEX_DIR = _PROJECT_ROOT / "knowledge" / ".index"
_CHUNKS_FILE = _INDEX_DIR / "chunks.json"
_EMBEDDINGS_FILE = _INDEX_DIR / "embeddings.npy"

# Model name. Local, MIT-licensed, ~130MB, 384-dim, runs on CPU.
_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Default threshold for "confident match" — chunks below this score are filtered.
_DEFAULT_MIN_SCORE = 0.3

# Module-level cache. Filled on first call to _get_state().
_state_lock = threading.Lock()
_state: dict = {
    "model": None,           # SentenceTransformer instance
    "chunks": None,          # list[dict] from chunks.json
    "embeddings": None,      # np.ndarray, shape (N, 384), L2-normalized
    "model_name": None,      # str — model used to build the index
    "loaded": False,         # bool — _get_state() has succeeded at least once
}


# ── Public dataclass ───────────────────────────────────────────────────────────

@dataclass
class KBChunk:
    """A single KB retrieval result."""
    id: str
    source: str       # e.g. "knowledge/install.md"
    section: str      # e.g. "Verifying GTK4 on Linux"
    text: str
    score: float      # cosine similarity, 0..1

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ")
        return f"KBChunk(score={self.score:.3f}, source={self.source!r}, section={self.section!r}, text={preview!r}…)"


# ── Path helpers ───────────────────────────────────────────────────────────────

def get_index_path() -> Path:
    """Path to the index directory (knowledge/.index/)."""
    return _INDEX_DIR


def is_index_available() -> bool:
    """True if both chunks.json and embeddings.npy exist on disk."""
    return _CHUNKS_FILE.is_file() and _EMBEDDINGS_FILE.is_file()


# ── Lazy load ──────────────────────────────────────────────────────────────────

def _load_index() -> None:
    """Load chunks.json + embeddings.npy into module state. Thread-safe.

    Raises:
        FileNotFoundError: if index files are missing.
    """
    import numpy as np

    if not is_index_available():
        raise FileNotFoundError(
            f"KB index not found at {_INDEX_DIR}. "
            f"Run `python3 scripts/rebuild_kb_index.py` to build it."
        )

    with open(_CHUNKS_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    embeddings = np.load(str(_EMBEDDINGS_FILE))
    if embeddings.dtype != "float32":
        embeddings = embeddings.astype("float32")

    _state["chunks"] = chunks
    _state["embeddings"] = embeddings
    logger.debug("Loaded KB index: %d chunks, shape %s", len(chunks), embeddings.shape)


def _load_model(model_name: str) -> None:
    """Load the Sentence-Transformers model into module state. Thread-safe.

    Raises:
        ImportError: if sentence_transformers is not installed.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Run `pip install sentence-transformers` to enable KB lookup."
        ) from e

    model = SentenceTransformer(model_name)
    _state["model"] = model
    _state["model_name"] = model_name
    logger.info("Loaded embedding model: %s", model_name)


def _get_state(model_name: str) -> None:
    """Ensure model + index are loaded. Idempotent. Thread-safe via lock.

    On first call: loads model and index. On subsequent calls: no-op if
    already loaded with the same model name. If the model name changed
    (e.g. test fixture using a different model), reloads the model.
    """
    if (
        _state["loaded"]
        and _state["model"] is not None
        and _state["model_name"] == model_name
        and _state["chunks"] is not None
        and _state["embeddings"] is not None
    ):
        return

    with _state_lock:
        # Double-check inside the lock.
        if (
            _state["loaded"]
            and _state["model"] is not None
            and _state["model_name"] == model_name
            and _state["chunks"] is not None
            and _state["embeddings"] is not None
        ):
            return

        _load_index()
        if _state["model"] is None or _state["model_name"] != model_name:
            _load_model(model_name)
        _state["loaded"] = True


# ── Public API ─────────────────────────────────────────────────────────────────

def kb_lookup(
    question: str,
    top_k: int = 3,
    min_score: float = _DEFAULT_MIN_SCORE,
    model_name: str = _DEFAULT_MODEL,
) -> list[KBChunk]:
    """Return top-K KB chunks most relevant to `question`.

    Args:
        question: The user's natural-language question.
        top_k: Maximum number of chunks to return.
        min_score: Minimum cosine-similarity score for a chunk to be included.
            Chunks below this threshold are filtered out. If no chunk meets
            the threshold, returns an empty list.
        model_name: Sentence-Transformers model to use. Must match the model
            used to build the index (default: BAAI/bge-small-en-v1.5).

    Returns:
        List of KBChunk, sorted by score descending. Empty list if the
        index is missing, the model is unavailable, or no chunk meets
        `min_score`.

    Note:
        This function is designed to fail soft. Missing index → []. Missing
        sentence-transformers → []. No confident match → []. Callers should
        treat empty list as "I don't have info on that" and respond
        accordingly, never as a hard error.
    """
    if not question or not question.strip():
        return []

    if not is_index_available():
        logger.debug("KB index not available; returning empty list")
        return []

    try:
        start = time.perf_counter()
        _get_state(model_name)

        import numpy as np

        # Embed the question. Sentence-Transformers handles tokenization.
        model = _state["model"]
        query_vec = model.encode(
            [question],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype("float32")  # shape (1, 384)

        # Cosine similarity on L2-normalized vectors = dot product.
        embeddings = _state["embeddings"]  # shape (N, 384), already normalized
        scores = (embeddings @ query_vec.T).flatten()  # shape (N,)

        # Top-K by score, descending.
        top_k_actual = min(top_k, len(scores))
        top_indices = np.argpartition(-scores, top_k_actual - 1)[:top_k_actual]
        top_indices = top_indices[np.argsort(-scores[top_indices])]

        chunks = _state["chunks"]
        results: list[KBChunk] = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < min_score:
                break  # sorted desc; all subsequent are below threshold
            c = chunks[int(idx)]
            results.append(KBChunk(
                id=c["id"],
                source=c["source"],
                section=c.get("section", ""),
                text=c["text"],
                score=score,
            ))

        elapsed_ms = (time.perf_counter() - start) * 1000
        if results:
            logger.debug(
                "kb_lookup: %d results in %.1fms (top: %s @ %.3f)",
                len(results), elapsed_ms, results[0].id, results[0].score,
            )
        else:
            logger.debug("kb_lookup: no results above min_score=%.2f in %.1fms", min_score, elapsed_ms)
        return results

    except ImportError:
        logger.warning("sentence-transformers not available; kb_lookup returning []")
        return []
    except FileNotFoundError:
        logger.debug("KB index missing; kb_lookup returning []")
        return []
    except Exception as e:  # noqa: BLE001 — fail soft by design
        logger.warning("kb_lookup failed: %s; returning []", e)
        return []


def reset_cache() -> None:
    """Clear module-level state. Used by tests."""
    with _state_lock:
        _state["model"] = None
        _state["chunks"] = None
        _state["embeddings"] = None
        _state["model_name"] = None
        _state["loaded"] = False
