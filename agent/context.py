# agent/context.py
# System prompt + file context builder for the agent runtime.
#
# Manifest:
#   - Reads: project files, .gitignore, .crabcakes/agent-system-prompt.md, AGENTS.md
#   - No network, no GTK, no config files outside the project
#   - No stateful mutations — pure functions
#
# Architecture: this module is intentionally dependency-free (stdlib only).
# Any runtime that needs context should call helpers from here.

from __future__ import annotations

import os
import re
from fnmatch import fnmatch
from typing import Callable

# ── Default prompt templates ──────────────────────────────────────────────────

# These are the default templates used when no custom prompt is found.
# Custom prompts (from .crabcakes/agent-system-prompt.md or AGENTS.md)
# completely replace these.

_CODER_SYSTEM_PROMPT = """You are {agent_name}, a software engineering agent.

Project: {project_path}
Review mode: {review_mode}

You have access to the following tools:
{tool_list}

Guidelines:
- Work in small, verified steps — never write large untested blocks
- Prefer patterns: early returns, explicit logging, narrow asserts
- Never rely solely on memory — verify against actual code, docs, and specs
- Output format: plain text explanations, with code in markdown backtick blocks
- When in doubt, ask before acting externally

{file_context_block}"""

_DEBUGGER_SYSTEM_PROMPT = """You are {agent_name}, a diagnostic and debugging agent.

Project: {project_path}
Review mode: {review_mode}

You have access to the following tools:
{tool_list}

Guidelines:
- Start from verifiable facts: reproduce the error, read the actual code
- Trace execution path step by step — don't guess
- Prefer patterns: early returns, explicit logging, narrow asserts
- Never rely solely on memory — verify against actual code, docs, and specs
- Output format: plain text explanations, with code in markdown backtick blocks
- When in doubt, ask before acting externally

{file_context_block}"""

# ── Gitignore ─────────────────────────────────────────────────────────────────


def _load_gitignore_patterns(project_path: str) -> list[str]:
    """
    Load .gitignore patterns from project root.
    Returns a list of pattern strings (not fnmatch-based - actual gitignore syntax).
    """
    gitignore_path = os.path.join(project_path, ".gitignore")
    if not os.path.isfile(gitignore_path):
        return []

    try:
        with open(gitignore_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []

    patterns: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue
        # Negation — store as-is, fnmatch doesn't support this directly
        # but we handle it separately
        patterns.append(stripped)
    return patterns


def _match_gitignore(name: str, patterns: list[str], anchored: bool = False) -> bool:
    """
    Return True if name matches any non-negated .gitignore pattern.
    fnmatch is used as a close approximation to gitignore semantics.

    Args:
        name: Path segment or path to match.
        patterns: List of .gitignore patterns.
        anchored: If True, patterns with / are anchored to the start (depth-1).
                  If False, all patterns match anywhere (simpler behavior).
    """
    for pattern in patterns:
        negated = pattern.startswith("!")
        active = pattern[1:] if negated else pattern

        # Directory-only pattern: ends with /
        dir_only = active.endswith("/")
        if dir_only:
            active = active[:-1]
            # Anchored directory pattern: only matches at depth 1
            if "/" not in active and fnmatch(name, active):
                return not negated
            continue

        if fnmatch(name, active):
            return not negated
    return False


def _is_ignored(rel_path: str, project_path: str, patterns: list[str]) -> bool:
    """
    Check if a relative path should be ignored based on .gitignore patterns.
    For a project-root .gitignore, patterns with / are anchored to depth 1.
    Patterns without / match any path segment at any depth.
    """
    parts = rel_path.replace("\\", "/").split("/")
    depth = len(parts)

    for i, part in enumerate(parts):
        # Check segment at its depth level (for anchored patterns like src/)
        if i == 0 and "/" not in rel_path:
            # Single segment — check against patterns with /
            if _match_gitignore(part + "/", patterns):
                return True
        # Check without anchor (unanchored patterns match anywhere)
        if _match_gitignore(part, patterns):
            return True
    return False


# ── Custom prompt loading ─────────────────────────────────────────────────────


def load_custom_system_prompt(project_path: str) -> str | None:
    """
    Load custom agent system prompt from project.

    Searches in order:
    1. .crabcakes/agent-system-prompt.md
    2. AGENTS.md (project root)

    Returns the content if found, or None if neither exists.
    Raises OSError if the file exists but can't be read.
    """
    if not project_path or not os.path.isdir(project_path):
        return None

    candidates = [
        os.path.join(project_path, ".crabcakes", "agent-system-prompt.md"),
        os.path.join(project_path, "AGENTS.md"),
    ]

    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    content = fh.read().strip()
                if content:
                    return content
            except OSError:
                # Try next candidate
                pass
    return None


# ── File context builder ──────────────────────────────────────────────────────


def _build_directory_tree(project_path: str, max_lines: int = 200) -> str:
    """
    Build a directory tree string for the project.
    Skips ignored files/directories. Respects .gitignore.
    Returns a multi-line string like tree(1) output.
    """
    patterns = _load_gitignore_patterns(project_path)
    lines: list[str] = []
    prefix_skip = {"__pycache__", ".git", "node_modules", ".pytest_cache", ".mypy_cache", ".tox"}

    def add_dir(rel_dir: str, indent: str) -> None:
        """Add entries for one directory level and recurse into subdirs."""
        if len(lines) >= max_lines:
            return
        try:
            entries = sorted(
                os.listdir(os.path.join(project_path, rel_dir) if rel_dir else project_path)
            )
        except OSError:
            return

        for name in entries:
            full = os.path.join(rel_dir, name) if rel_dir else name
            if _is_ignored(full, project_path, patterns):
                continue
            if name in prefix_skip or name.startswith("."):
                continue
            full_path = os.path.join(project_path, full)
            if os.path.isdir(full_path):
                lines.append(f"{indent}{name}/")
                add_dir(full, indent + "  ")
            else:
                lines.append(f"{indent}{name}")

    add_dir("", "")
    return "\n".join(lines)


def _read_key_files(project_path: str) -> str:
    """
    Read key project files for context: README, ARCHITECTURE, package.json, etc.
    Skips files > 50KB. Respects .gitignore.
    """
    patterns = _load_gitignore_patterns(project_path)
    key_names = {
        "README.md", "README.txt", "README",
        "ARCHITECTURE.md", "ARCHITECTURE.txt",
        "package.json", "pyproject.toml", "Cargo.toml",
        "Makefile", "Dockerfile", ".env.example",
        "AGENTS.md",
    }
    MAX_FILE_SIZE = 50 * 1024  # 50 KB per file
    sections: list[str] = []

    try:
        entries = os.listdir(project_path)
    except OSError:
        return ""

    for name in entries:
        if name not in key_names:
            continue
        rel_path = name
        if _is_ignored(rel_path, project_path, patterns):
            continue
        file_path = os.path.join(project_path, name)
        if not os.path.isfile(file_path):
            continue
        try:
            size = os.path.getsize(file_path)
            if size > MAX_FILE_SIZE:
                content = f"[File too large to display — {size // 1024}KB]"
            else:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
        except OSError:
            continue

        sections.append(f"## {name}\n\n{content}\n")

    return "\n".join(sections)


def build_file_context(
    project_path: str,
    query: str | None = None,
    max_chars: int = 50_000,
) -> str:
    """
    Build a file context block for an LLM prompt.

    Strategy:
    - With query: include files matching the query (by name)
    - Without query: directory tree + key files (README, ARCHITECTURE, etc.)
    - Respects .gitignore
    - Total context capped at ~max_chars

    Args:
        project_path: Absolute path to the project root.
        query: Optional search query — if provided, only matching files are included.
        max_chars: Maximum total context length (default 50K).

    Returns:
        Formatted text block, truncated to max_chars if needed.
    """
    if not project_path or not os.path.isdir(project_path):
        return ""

    patterns = _load_gitignore_patterns(project_path)
    parts: list[str] = []

    if query:
        # Query mode: find files matching the query string
        matches = _find_matching_files(project_path, query, patterns)
        if not matches:
            return f"(No files match query: {query})"
        parts.append("## Matching files\n")
        for rel_path in matches:
            content = _read_file_safe(os.path.join(project_path, rel_path))
            if content is None:
                continue
            parts.append(f"## {rel_path}\n\n{content}\n")
    else:
        # No query: directory tree + key files
        tree = _build_directory_tree(project_path)
        parts.append(f"## Project tree\n\n{tree}\n\n")
        key_files = _read_key_files(project_path)
        if key_files:
            parts.append(f"## Key files\n\n{key_files}\n")

    full = "".join(parts)

    # Truncate if needed — preserve header if possible
    if len(full) <= max_chars:
        return full

    # Truncate, keeping as much as possible from the end (most recent context)
    return full[:max_chars] + f"\n\n[... file context truncated to {max_chars} chars ...]"


def _find_matching_files(
    project_path: str,
    query: str,
    patterns: list[str],
    max_files: int = 20,
    max_total_chars: int = 40_000,
) -> list[str]:
    """Find files matching query (by name) within project."""
    query_lower = query.lower()
    matches: list[tuple[str, int]] = []  # (rel_path, size)
    total = 0

    for root, dirs, files in os.walk(project_path):
        # Prune ignored dirs in-place
        rel_root = os.path.relpath(root, project_path)
        if _is_ignored(rel_root, project_path, patterns):
            dirs[:] = []
            continue

        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {
            "__pycache__", "node_modules", ".pytest_cache", ".mypy_cache", ".tox"
        }]

        for name in files:
            if name.startswith("."):
                continue
            rel_path = os.path.join(rel_root, name) if rel_root != "." else name
            if _is_ignored(rel_path, project_path, patterns):
                continue
            if query_lower in name.lower():
                try:
                    size = os.path.getsize(os.path.join(root, name))
                except OSError:
                    size = 0
                if total + size > max_total_chars and len(matches) >= 3:
                    continue
                matches.append((rel_path, size))
                total += size
                if len(matches) >= max_files:
                    return [m[0] for m in matches]

    # Sort by size descending (larger/more important files first)
    matches.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matches]


def _read_file_safe(path: str, max_size: int = 50 * 1024) -> str | None:
    """Read a file safely, returning None on error or if too large."""
    try:
        if os.path.getsize(path) > max_size:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# ── System prompt builder ─────────────────────────────────────────────────────


def build_system_prompt(
    agent_name: str,
    project_path: str | None,
    tools: list[str],
    review_mode: str = "off",
) -> str:
    """
    Build the system prompt for an agent.

    Includes: agent identity, project context, tool usage instructions,
    review mode awareness, output format guidelines.

    Custom prompts (from .crabcakes/agent-system-prompt.md or AGENTS.md)
    completely replace this default template.

    Args:
        agent_name: Display name of the agent (e.g. "Coder").
        project_path: Absolute path to the project root. Used in system prompt
            and to load custom prompts and file context.
        tools: List of tool names this agent can use.
        review_mode: "off" | "review" — controls write permission awareness.

    Returns:
        Formatted system prompt string.
    """
    # Check for custom prompt first
    if project_path:
        custom = load_custom_system_prompt(project_path)
        if custom:
            return custom

    # Build tool list string
    tool_list = "\n".join(f"  - {t}" for t in tools) if tools else "  (no tools)"

    # Review mode awareness
    review_note = ""
    if review_mode == "review":
        review_note = (
            "\n[REVIEW MODE ACTIVE] You are in review mode. "
            "All file writes are queued for PM approval. "
            "Do not write directly — propose changes for review.]"
        )

    # File context
    file_context = ""
    if project_path:
        file_context = build_file_context(project_path)
        if file_context:
            file_context = f"\n\n## File context\n\n{file_context}"

    # Select template
    template = (
        _CODER_SYSTEM_PROMPT
        if "coder" in agent_name.lower()
        else _DEBUGGER_SYSTEM_PROMPT
    )

    return template.format(
        agent_name=agent_name,
        project_path=project_path or "(no project open)",
        review_mode=review_mode,
        tool_list=tool_list,
        file_context_block=file_context + review_note,
    )
