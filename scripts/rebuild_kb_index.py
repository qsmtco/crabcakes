#!/usr/bin/env python3
"""Rebuild the KB index from knowledge/*.md files.

Reads all .md files in the project's knowledge/ directory, splits each
into chunks (one per `##` level-2 heading), embeds each chunk with the
configured Sentence-Transformers model, and writes:

  knowledge/.index/chunks.json     — list of {id, source, section, text}
  knowledge/.index/embeddings.npy  — float32 array, shape (N, 384), L2-normalized

Usage:
    python3 scripts/rebuild_kb_index.py
    python3 scripts/rebuild_kb_index.py --model sentence-transformers/all-MiniLM-L6-v2
    python3 scripts/rebuild_kb_index.py --out /tmp/kb_index/

This is a build-time script, not a runtime module. It is not imported
by any runtime code. Run it offline when KB content changes.

Idempotency: re-running on unchanged KB produces byte-identical output
(deterministic model + same inputs → same embeddings).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# Project root: scripts/rebuild_kb_index.py is one level deep.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_KB_DIR = _PROJECT_ROOT / "knowledge"
_DEFAULT_OUT_DIR = _DEFAULT_KB_DIR / ".index"
_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# Max chunk size in characters. Larger sections are split further.
_MAX_CHUNK_CHARS = 2000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("rebuild_kb_index")


# ── Chunking ──────────────────────────────────────────────────────────────────

def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown text into (section_title, section_body) pairs.

    A section starts at a `##` heading and runs until the next `##` (or
    end of file). Pre-amble (text before the first `##`) becomes a
    section with title "Introduction" (or empty string if absent).
    """
    lines = text.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_body: list[str] = []

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            # Flush previous section.
            if current_body or current_title:
                sections.append((current_title, current_body))
            current_title = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)

    # Flush final section.
    if current_body or current_title:
        sections.append((current_title, current_body))

    # Title-less preamble becomes "Introduction".
    out: list[tuple[str, str]] = []
    for i, (title, body) in enumerate(sections):
        if i == 0 and not title:
            title = "Introduction"
        out.append((title, "\n".join(body).strip()))
    return out


def _split_long_section(text: str) -> list[str]:
    """Split a section that exceeds _MAX_CHUNK_CHARS into smaller pieces.

    Tries to split on `###` (level-3) headings first. If that's not
    enough, splits on paragraph boundaries (double newlines). Last
    resort: hard-splits on character count.
    """
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]

    # Try ### boundaries.
    parts = re.split(r"(?m)^### ", text)
    if len(parts) > 1:
        # Re-prepend "### " to the split parts (except the first).
        parts = [parts[0]] + ["### " + p for p in parts[1:]]
        out: list[str] = []
        for p in parts:
            if len(p) > _MAX_CHUNK_CHARS:
                # Still too long after ### split — go to paragraph/hard split (no recursion)
                out.extend(_paragraph_split(p))
            else:
                out.append(p)
        return out

    # Try paragraph boundaries.
    return _paragraph_split(text)


def _paragraph_split(text: str) -> list[str]:
    """Split text on paragraph boundaries, then hard-split if still too long."""
    paragraphs = text.split("\n\n")
    out = []
    buffer = ""
    for p in paragraphs:
        if len(buffer) + len(p) + 2 > _MAX_CHUNK_CHARS and buffer:
            out.append(buffer)
            buffer = p
        else:
            buffer = buffer + "\n\n" + p if buffer else p
    if buffer:
        out.append(buffer)
    if out and any(len(x) > _MAX_CHUNK_CHARS for x in out):
        # Still too long — hard split.
        return _hard_split(text)
    return out


def _hard_split(text: str) -> list[str]:
    """Last-resort split: cut at _MAX_CHUNK_CHARS boundaries."""
    return [text[i : i + _MAX_CHUNK_CHARS] for i in range(0, len(text), _MAX_CHUNK_CHARS)]


def chunk_file(path: Path, source_label: str) -> list[dict]:
    """Read one .md file and return a list of chunk dicts."""
    text = path.read_text(encoding="utf-8")
    sections = _split_into_sections(text)
    chunks: list[dict] = []
    for section_idx, (title, body) in enumerate(sections):
        if not body:
            continue
        for piece_idx, piece in enumerate(_split_long_section(body)):
            chunk_id = f"{source_label}#{section_idx}.{piece_idx}"
            chunks.append({
                "id": chunk_id,
                "source": source_label,
                "section": title,
                "text": piece.strip(),
            })
    return chunks


def chunk_kb_dir(kb_dir: Path) -> list[dict]:
    """Glob kb_dir for *.md and chunk all of them."""
    all_chunks: list[dict] = []
    md_files = sorted(kb_dir.glob("*.md"))
    for path in md_files:
        source = f"knowledge/{path.name}"
        chunks = chunk_file(path, source)
        log.info("  %s: %d chunks", path.name, len(chunks))
        all_chunks.extend(chunks)
    return all_chunks


# ── Embedding ─────────────────────────────────────────────────────────────────

def embed_chunks(chunks: list[dict], model_name: str) -> "np.ndarray":
    """Embed all chunk texts with the configured model. Returns (N, D) array."""
    try:
        import numpy as np
    except ImportError:
        log.error("numpy is required: pip install numpy")
        sys.exit(1)

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        log.error("sentence-transformers is required: pip install sentence-transformers")
        sys.exit(1)

    log.info("Loading model: %s", model_name)
    model = SentenceTransformer(model_name)
    log.info("Model loaded. Embedding %d chunks…", len(chunks))

    texts = [c["text"] for c in chunks]
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=32,
    ).astype("float32")

    log.info("Embeddings shape: %s, dtype: %s", embeddings.shape, embeddings.dtype)
    return embeddings


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the KB index.")
    parser.add_argument("--model", default=_DEFAULT_MODEL, help="Sentence-Transformers model name")
    parser.add_argument("--kb-dir", default=str(_DEFAULT_KB_DIR), help="KB directory (default: knowledge/)")
    parser.add_argument("--out", default=str(_DEFAULT_OUT_DIR), help="Output directory (default: knowledge/.index/)")
    args = parser.parse_args()

    kb_dir = Path(args.kb_dir)
    out_dir = Path(args.out)

    if not kb_dir.is_dir():
        log.error("KB directory not found: %s", kb_dir)
        return 1

    log.info("Chunking KB files in: %s", kb_dir)
    chunks = chunk_kb_dir(kb_dir)
    if not chunks:
        log.error("No chunks produced. Are there .md files in %s?", kb_dir)
        return 1
    log.info("Total chunks: %d from %d file(s)", len(chunks), len(list(kb_dir.glob("*.md"))))

    embeddings = embed_chunks(chunks, args.model)

    out_dir.mkdir(parents=True, exist_ok=True)
    chunks_file = out_dir / "chunks.json"
    embeddings_file = out_dir / "embeddings.npy"

    with open(chunks_file, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    log.info("Wrote: %s", chunks_file)

    import numpy as np
    np.save(str(embeddings_file), embeddings)
    log.info("Wrote: %s", embeddings_file)

    log.info("Done. Indexed %d chunks. Use `agent.kb_lookup.kb_lookup()` to query.", len(chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
