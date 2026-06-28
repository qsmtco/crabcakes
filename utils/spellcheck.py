"""Subprocess wrapper for enchant-2 spell checking.

Security Manifest:
- Reads text strings from caller (user-provided message text).
- Executes the ``enchant-2`` binary via subprocess; no other I/O.
- Optionally reads a personal word list from a caller-supplied path
  (``--dictionary-path``) — read-only, no writes.
- No files are written. No network calls. No secrets accessed.
- All subprocess calls have a 5-second timeout to prevent hangs.
"""

from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_ENCHANT_BIN = "enchant-2"
_TIMEOUT = 5  # seconds


def _personal_wordlist_args(dictionary_path: str | None) -> list[str]:
    """Return ``["-p", path]`` if *dictionary_path* is set and readable.

    Silently returns ``[]`` when the path is unset, missing, or not a
    regular file — call sites then fall back to enchant's default
    dictionaries (current behavior preserved).
    """
    if not dictionary_path:
        return []
    try:
        if os.path.isfile(dictionary_path):
            return ["-p", dictionary_path]
    except OSError:
        # Defensive: exotic path (e.g. ENOENT races, EACCES) → fall back.
        pass
    return []


def check_words(text: str, dictionary_path: str | None = None) -> list[str]:
    """Return list of misspelled words found in *text*.

    Uses ``enchant-2 -l`` (batch mode — one subprocess call for entire text).
    Deduplicates results while preserving order.

    Args:
        text: The text to spell-check.
        dictionary_path: Optional path to a personal word list (one word per
            line, ``#`` comments allowed). If the file does not exist or is
            unreadable, falls back to enchant's default dictionaries.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    cmd = [_ENCHANT_BIN, "-l", *_personal_wordlist_args(dictionary_path)]
    try:
        result = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError:
        logger.warning("enchant-2 binary not found on $PATH")
        return []
    except subprocess.TimeoutExpired:
        logger.error("enchant-2 -l timed out after %ds", _TIMEOUT)
        return []
    except Exception:
        logger.exception("Unexpected error running enchant-2 -l")
        return []

    seen: set[str] = set()
    misspelled: list[str] = []
    for line in result.stdout.splitlines():
        word = line.strip()
        if word and word not in seen:
            seen.add(word)
            misspelled.append(word)
    return misspelled


def get_suggestions(word: str, dictionary_path: str | None = None) -> list[str]:
    """Return up to 8 spelling suggestions for a misspelled *word*.

    Uses ``enchant-2 -a`` (ispell pipe mode).
    Returns empty list if *word* is correctly spelled.

    Args:
        word: The word to look up suggestions for.
        dictionary_path: Optional path to a personal word list. Same
            fallback rules as :func:`check_words`.
    """
    if not isinstance(word, str) or not word.strip():
        return []

    cmd = [_ENCHANT_BIN, "-a", *_personal_wordlist_args(dictionary_path)]
    try:
        result = subprocess.run(
            cmd,
            input=word,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except FileNotFoundError:
        logger.warning("enchant-2 binary not found on $PATH")
        return []
    except subprocess.TimeoutExpired:
        logger.error("enchant-2 -a timed out after %ds", _TIMEOUT)
        return []
    except Exception:
        logger.exception("Unexpected error running enchant-2 -a")
        return []

    # ispell pipe mode output:
    #   Line 1: "@(#) International Ispell ..."  (version header)
    #   For misspelled:  "& word count offset: sug1, sug2, ..."
    #   For correct:     "*"
    suggestions: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("&"):
            # Format: & <word> <count> <offset>: <comma-separated suggestions>
            colon_idx = line.find(":")
            if colon_idx != -1:
                sug_text = line[colon_idx + 1:]
                for sug in sug_text.split(","):
                    sug = sug.strip()
                    if sug:
                        suggestions.append(sug)
    return suggestions[:8]
