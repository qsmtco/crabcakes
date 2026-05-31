"""Subprocess wrapper for enchant-2 spell checking.

Security Manifest:
- Reads text strings from caller (user-provided message text).
- Executes the ``enchant-2`` binary via subprocess; no other I/O.
- No files are written. No network calls. No secrets accessed.
- All subprocess calls have a 5-second timeout to prevent hangs.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

_ENCHANT_BIN = "enchant-2"
_TIMEOUT = 5  # seconds


def check_words(text: str) -> list[str]:
    """Return list of misspelled words found in *text*.

    Uses ``enchant-2 -l`` (batch mode — one subprocess call for entire text).
    Deduplicates results while preserving order.
    """
    if not text or not text.strip():
        return []

    try:
        result = subprocess.run(
            [_ENCHANT_BIN, "-l"],
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


def get_suggestions(word: str) -> list[str]:
    """Return up to 8 spelling suggestions for a misspelled *word*.

    Uses ``enchant-2 -a`` (ispell pipe mode).
    Returns empty list if *word* is correctly spelled.
    """
    if not word or not word.strip():
        return []

    try:
        result = subprocess.run(
            [_ENCHANT_BIN, "-a"],
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
