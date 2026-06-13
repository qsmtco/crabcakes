---
status: PARTIAL
---
# SPEC-4: Dream Consolidation Layer

**Implements:** Self-Improvement Layer 5
**Estimated effort:** ~1 day (prototype), ongoing refinement
**Depends on:** User-Defined Local Agents (agent YAML with `self_improvement.dream_consolidation` flag), SPEC-1, SPEC-2, SPEC-3 (all layers must be operational with accumulated data)
**Enables:** Autonomous prompt evolution — the system improves itself

---

## 1. Overview

The Dream Consolidation layer is an autonomous process that runs during idle time (typically nightly), analyzes accumulated review feedback from SPEC-3, and evolves each agent's bug journal, project rules, and system prompt. It's the capstone of the self-improvement stack:

- **SPEC-1** provides the bug journal (what went wrong, per agent role)
- **SPEC-2** provides enforcement data (what tests caught)
- **SPEC-3** provides structured feedback (what reviewers found, per target agent role)
- **SPEC-4** synthesizes all of it into actionable improvements for each agent

This is the most experimental layer. It should not be implemented until SPECs 1-3 have been running for at least a week and have accumulated meaningful data.

**Agent gating:** Dream consolidation runs per agent role. Only agents with `self_improvement.dream_consolidation: true` in their YAML definition are included in the dream cycle. Each agent role gets its own bug journal (`{role}-bugs.md`), rules file (`{role}-rules.md`), and proposal directory. The dream engine can process multiple agent roles in a single cycle.

---

## 2. Architecture

### 2.1 Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Dream Engine                              │
│                                                             │
│  Phase 1: Gather (per role) ─────────────────────────────  │
│  ├── Discover agent roles with dream_consolidation: true    │
│  ├── For each enabled role:                                 │
│  │   ├── Read review-log.jsonl (entries for this role)      │
│  │   ├── Read {role}-bugs.md (current bug journal)          │
│  │   ├── Read {role}-rules.md (current project rules)       │
│  │   └── Read prompts/system/{role}.md (current pitfalls)   │
│                                                             │
│  Phase 2: Analyze (per role) ────────────────────────────   │
│  ├── LLM call with dream-analysis.md prompt                 │
│  ├── Input: gathered data for this role                     │
│  └── Output: structured JSON with patterns + proposals      │
│                                                             │
│  Phase 3: Synthesize (per role) ─────────────────────────   │
│  ├── Cluster related bugs by Pattern tag                    │
│  ├── Generate meta-lessons for recurring patterns           │
│  ├── Propose new Common Pitfalls for prompts/system/{role}.md│
│  ├── Propose new gotchas for {role}-rules.md                │
│  └── Identify resolved patterns (not seen recently)         │
│                                                             │
│  Phase 4: Write (per role) ──────────────────────────────   │
│  ├── For each role:                                         │
│  │   ├── Update {role}-bugs.md (add syntheses)              │
│  │   ├── Update {role}-rules.md (add gotchas)               │
│  │   ├── Store {role}.md proposals in dream-proposals/      │
│  │   └── Archive old entries if journal > 50                │
│  └── Log cycle results per role                             │
│                                                             │
│  Phase 5: Verify ─────────────────────────────────────────  │
│  ├── Validate updated files are parseable                   │
│  ├── Log dream cycle results to dream-log.jsonl             │
│  └── Announce results to main session                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Execution Model

The dream runs as an **OpenClaw cron job** that triggers a Python script:

```json
{
  "schedule": {"kind": "cron", "expr": "0 2 * * *", "tz": "America/Los_Angeles"},
  "payload": {
    "kind": "agentTurn",
    "message": "Run the dream consolidation script for the CrabCakes project. Execute: cd /home/q/projects/crabcakes && python3 -m utils.dream_engine_cli",
    "toolsAllow": ["exec"]
  },
  "sessionTarget": "isolated",
  "delivery": {"mode": "announce"}
}
```

The cron job uses the isolated agent's `exec` tool to run a Python CLI wrapper (`utils/dream_engine_cli.py`). This wrapper imports `agent.dream_engine.run_dream_cycle()` and runs it for each configured project. This avoids the problem of an OpenClaw agent trying to import CrabCakes modules directly.

**The CLI wrapper** (`utils/dream_engine_cli.py`):
```python
#!/usr/bin/env python3
"""CLI entry point for dream consolidation cron job.

Run via: python3 -m utils.dream_engine_cli [--project /path/to/project]
If no --project is given, runs for all projects in CRABCAKES_PROJECTS_DIR.
"""
import argparse
from agent.dream_engine import run_dream_cycle

def main():
    parser = argparse.ArgumentParser(description="CrabCakes Dream Consolidation")
    parser.add_argument("--project", help="Project path", default=None)
    args = parser.parse_args()

    if args.project:
        results = run_dream_cycle(args.project)
        for role, result in results.items():
            print(f"{role}: {'OK' if result.success else 'FAILED'} — {result.summary}")
    else:
        # Discover all projects and run for each
        from utils.projects import load_projects
        for name, path in load_projects():
            results = run_dream_cycle(path)
            for role, result in results.items():
                print(f"{name}/{role}: {'OK' if result.success else 'FAILED'} — {result.summary}")

if __name__ == "__main__":
    main()
```

**Why not direct module import:** An OpenClaw isolated agent cannot import CrabCakes modules like `agent.dream_engine`. It can, however, execute shell commands. The CLI wrapper bridges this gap.

**Alternative execution modes:**
- **On-demand:** Triggered by a command like `` `dream @Agent ` `` or manual invocation
- **Idle-triggered:** After 4+ hours of agent inactivity (requires heartbeat integration)
- **GLib timer:** For in-process scheduling, use `GLib.timeout_add_seconds()` with a 24h interval. This is an alternative to the cron approach for when CrabCakes is running continuously.

### 2.3 Safety Model

Dream consolidation modifies each agent's operating instructions. Three tiers of safety:

| File Modified | Risk Level | Approval Required | Revertible |
|---------------|-----------|-------------------|------------|
| `{role}-bugs.md` | Low | No (auto-applied) | Yes (git revert) |
| `{role}-rules.md` | Low | No (auto-applied) | Yes (git revert) |
| `prompts/system/{role}.md` | **High** | **Yes (human review)** | Yes (git revert) |

**Rules:**
1. Bug journal and project rules changes are auto-applied. They're project-scoped, git-tracked, and easily revertable.
2. System prompt (`prompts/system/{role}.md`) changes require human approval. Proposals are stored in `.crabcakes/dream-proposals/` with timestamps. A human reviews and either accepts or rejects.
3. No deletion without approval. The dream can mark entries as "possibly stale" but cannot delete from the bug journal.
4. Idempotency. Running the dream twice with the same data should produce the same output. Only new review-log entries (since last dream) are processed.

---

## 3. Files to Create

### 3.1 `prompts/system/dream-analysis.md` — The analysis prompt

This is the core LLM prompt that drives the dream. It receives gathered data and produces structured analysis.

```markdown
# Dream Analysis — Agent Self-Improvement

You are analyzing code review feedback to identify patterns and propose improvements to an AI agent's instructions.

## Input Data

You will receive:
1. **Current Common Pitfalls** — the agent's existing list of known failure patterns
2. **Current Bug Journal** — accumulated project-specific bugs for this agent role
3. **New Review Entries** — structured audit reports from recent code reviews targeting this agent
4. **Current Project Rules** — project-specific conventions and gotchas for this agent role

## Your Task

### 1. Pattern Identification
Analyze the new review entries. For each entry:
- Is it a new pattern or a recurrence of an existing one?
- How severe is it? (how many times has it occurred?)
- Is it project-specific or likely universal?
- Has the agent already learned from this pattern? (check if it appears in Common Pitfalls)

### 2. Frequency Analysis
Count occurrences of each pattern across all review entries:
- Patterns appearing 3+ times → candidate for promotion to Common Pitfalls
- Patterns appearing in 2+ projects → likely universal, not project-specific
- Patterns appearing only once → note but don't promote yet

### 3. Resolution Detection
Check if any previously-identified patterns are no longer appearing:
- If a pattern was common but hasn't appeared in the last 10+ reviews → likely resolved
- Mark resolved patterns — they can be archived from the active bug journal

### 4. Generate Proposals

Based on your analysis, generate:

**For the agent prompt (Common Pitfalls):** New pitfall entries for patterns with 3+ occurrences. Format:
```
| Pattern Name | What Happened | Prevention |
```

**For project rules (Gotchas):** New gotcha entries for project-specific patterns. Format:
```
- [gotcha description]
```

**For bug journal (Synthesis):** Meta-lessons that consolidate multiple related bug entries. Format:
```
## Bug #N — DATE — synthesized
**Task:** Pattern synthesis
**Mistake:** [consolidated description of the recurring pattern]
**Lesson:** [meta-lesson]
**Pattern:** [tag]
**Synthesized from:** Bug #X, Bug #Y, Bug #Z
```

**For bug journal (Pruning):** IDs of entries that can be archived because they're covered by a synthesis entry.

## Output Format

Respond with ONLY a JSON object (no markdown fences, no explanation):

{
  "patterns": [
    {
      "pattern": "mock-truthiness",
      "frequency": 3,
      "first_seen": "2026-05-18",
      "last_seen": "2026-05-25",
      "projects": ["crabwatch", "crabcakes"],
      "status": "active",
      "is_universal": true,
      "suggested_action": "add_to_agent_prompt",
      "proposed_pitfall": {
        "name": "Mock Object Truthiness",
        "what": "Checking `if value is not None` or `if value:` on MagicMock objects always returns True",
        "prevention": "Use `isinstance(value, str)` or `isinstance(value, ExpectedType)` to verify actual type before checking truthiness"
      }
    }
  ],
  "proposals": {
    "agent_prompt_additions": [
      "| Mock Object Truthiness | `if value is not None` always True with MagicMock | Use `isinstance(value, ExpectedType)` to verify type |"
    ],
    "agent_rules_additions": {
      "crabwatch": ["- Tests use MagicMock extensively — never check truthiness on mock objects, always check type"]
    },
    "bug_journal_syntheses": [
      {
        "pattern": "mock-truthiness",
        "lesson": "Mock objects from unittest.mock.MagicMock are always truthy for any attribute access. Always verify type with isinstance() before checking truthiness when working with test code.",
        "source_bugs": [1, 2, 3]
      }
    ],
    "bug_journal_prune": [1, 2, 3]
  },
  "resolved_patterns": [],
  "summary": "Found 2 active patterns, 1 new proposal for agent prompt, 3 bugs suitable for synthesis."
}

## Important Rules

1. **Minimum frequency.** Do not propose additions to agent prompts for patterns seen fewer than 3 times. One-off mistakes are noise, not signal.
2. **No duplicates.** Check if a pattern already exists in the current Common Pitfalls table before proposing a new entry.
3. **Be specific.** Proposals should describe concrete behavior, not vague principles. "Check types when working with mocks" is vague. "Use `isinstance(value, str)` instead of `if value is not None:` when the value might be a MagicMock" is specific.
4. **Preserve context.** When synthesizing multiple bugs into one meta-lesson, preserve enough detail that the agent understands the pattern, not just the label.
5. **JSON only.** Your entire response must be valid JSON. No markdown, no explanation, no commentary.
```

### 3.2 `agent/dream_engine.py` — Orchestration logic

This is the main module that orchestrates the dream cycle. It processes each enabled agent role independently.

**Note:** This module lives in `agent/` (not `utils/`) because it makes LLM API calls (network I/O via `_call_llm()`) and depends on `agent/config.py`. The `utils/` package is reserved for pure Python with no network and no GTK.

```python
# agent/dream_engine.py
# Dream Consolidation Engine — autonomous prompt evolution.
#
# Runs as a cron job or on-demand. Analyzes accumulated review feedback
# and proposes improvements to each agent's bug journal, project rules,
# and system prompt.
#
# Public API:
#   run_dream_cycle(project_path, agent_roles=None) -> dict[str, DreamResult]
#   get_dream_status(project_path) -> dict
#
# No GTK. No network (except LLM API call). Pure logic.

from __future__ import annotations

import datetime
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

MAX_JOURNAL_ENTRIES = 50          # Prune above this
MIN_PATTERN_FREQUENCY = 3         # Minimum occurrences to propose prompt addition
DREAM_PROPOSALS_DIR = "dream-proposals"

# Shared constants — single source of truth is utils/review_log.py
from utils.review_log import REVIEW_LOG_FILENAME, DREAM_LOG_FILENAME

# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class DreamPattern:
    """Identified pattern from dream analysis."""
    pattern: str
    frequency: int
    first_seen: str
    last_seen: str
    projects: list[str]
    status: str           # "active" | "resolved" | "evolving"
    is_universal: bool
    suggested_action: str  # "add_to_agent_prompt" | "add_to_agent_rules" | "synthesize" | "none"
    proposed_pitfall: dict | None = None


@dataclass
class DreamProposals:
    """Proposed changes from dream analysis."""
    agent_prompt_additions: list[str] = field(default_factory=list)
    agent_rules_additions: dict[str, list[str]] = field(default_factory=dict)
    bug_journal_syntheses: list[dict] = field(default_factory=list)
    bug_journal_prune: list[int] = field(default_factory=list)


@dataclass
class DreamResult:
    """Result of a dream cycle for one agent role."""
    agent_role: str
    success: bool
    patterns_found: int = 0
    proposals: DreamProposals = field(default_factory=DreamProposals)
    resolved_patterns: list[str] = field(default_factory=list)
    journal_entries_added: int = 0
    journal_entries_pruned: int = 0
    rules_updated: bool = False
    agent_prompt_proposed: bool = False
    error: str = ""
    summary: str = ""
    duration_seconds: float = 0.0


# ── Role Discovery ────────────────────────────────────────────────────────────


def _discover_dream_enabled_roles() -> list[str]:
    """Find all agent roles with dream_consolidation: true in their YAML definitions.

    Returns list of role strings (e.g. ["coder", "security-auditor"]).
    """
    try:
        from utils.agent_defs import load_agent_defs
        defs = load_agent_defs()
        roles = []
        for d in defs:
            si = d.get("self_improvement", {})
            if si.get("dream_consolidation", False):
                role = d.get("role", d.get("name", "").lower().replace(" ", "-"))
                roles.append(role)
        return roles
    except Exception as e:
        logger.debug("[dream] Could not discover dream-enabled roles: %s", e)
        return []


# ── Phase 1: Gather ──────────────────────────────────────────────────────────


def _gather_data(project_path: str, agent_role: str) -> dict[str, Any]:
    """Gather all data needed for dream analysis for a specific agent role.

    Returns dict with keys:
        agent_role: str — the role being analyzed
        common_pitfalls: str — current Common Pitfalls section from agent prompt
        bug_journal: str — full {role}-bugs.md content
        new_reviews: list[dict] — review-log entries for this role since last dream
        project_rules: str — full {role}-rules.md content
    """
    data: dict[str, Any] = {}
    data["agent_role"] = agent_role

    # Current Common Pitfalls from agent prompt
    data["common_pitfalls"] = _read_agent_pitfalls(agent_role)

    # Current bug journal
    data["bug_journal"] = _read_file_safe(
        os.path.join(project_path, ".crabcakes", f"{agent_role}-bugs.md")
    )

    # New review-log entries since last dream (filtered by target_role)
    from utils.review_log import read_review_log, get_last_dream_timestamp
    last_dream_ts = get_last_dream_timestamp(project_path)
    all_reviews = read_review_log(project_path, since=last_dream_ts)
    # Filter to reviews targeting this agent role
    data["new_reviews"] = [
        r for r in all_reviews
        if r.get("target_role", "unknown") == agent_role
    ]

    # Current project rules
    data["project_rules"] = _read_file_safe(
        os.path.join(project_path, ".crabcakes", f"{agent_role}-rules.md")
    )

    return data


def _read_agent_pitfalls(agent_role: str) -> str:
    """Read the Common Pitfalls section from an agent's system prompt.

    Note: For custom agents without a dedicated prompt template
    (no `prompts/system/{role}.md` file), this returns an empty string.
    This is expected behavior — the dream cycle simply won't propose
    additions to a non-existent prompt template.
    """
    from utils.prompt_loader import load_prompt_template
    agent_md = load_prompt_template(agent_role)
    if not agent_md:
        return ""

    # Extract Common Pitfalls section
    match = re.search(
        r"## Common Pitfalls\s*\n(.+?)(?=\n## |\Z)",
        agent_md, re.DOTALL
    )
    return match.group(1).strip() if match else ""


def _read_file_safe(path: str) -> str:
    """Read a file safely, returning empty string on error."""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


# ── Phase 2: Analyze ────────────────────────────────────────────────────────


def _analyze_with_llm(data: dict[str, Any], project_path: str) -> dict | None:
    """Call LLM with dream-analysis prompt and gathered data.

    Returns parsed JSON response or None on failure.
    """
    from utils.prompt_loader import load_prompt_template

    # Load dream analysis prompt
    analysis_prompt = load_prompt_template("dream-analysis")
    if not analysis_prompt:
        logger.error("[dream] dream-analysis.md prompt not found")
        return None

    # Build the input data block
    input_block = _build_analysis_input(data, project_path)

    # Combine prompt + input
    role = data.get("agent_role", "unknown")
    full_prompt = f"{analysis_prompt}\n\n## Input (agent role: {role})\n\n{input_block}"

    # Call LLM
    try:
        response = _call_llm(full_prompt)
        if not response:
            return None

        # Parse JSON from response (strip markdown fences if present)
        response = response.strip()
        if response.startswith("```"):
            response = re.sub(r"^```(?:json)?\s*\n?", "", response)
            response = re.sub(r"\n?```\s*$", "", response)

        return json.loads(response)

    except json.JSONDecodeError as e:
        logger.error("[dream] LLM response was not valid JSON: %s", e)
        return None
    except Exception as e:
        logger.error("[dream] LLM call failed: %s: %s", type(e).__name__, e)
        return None


def _build_analysis_input(data: dict[str, Any], project_path: str) -> str:
    """Build the input data block for the LLM."""
    parts = []

    parts.append("### Current Common Pitfalls (from agent prompt)\n")
    parts.append(data.get("common_pitfalls") or "(empty)")
    parts.append("")

    parts.append("### Current Bug Journal\n")
    parts.append(data.get("bug_journal") or "(empty)")
    parts.append("")

    parts.append("### New Review Entries (since last dream)\n")
    reviews = data.get("new_reviews", [])
    if reviews:
        for r in reviews:
            parts.append(json.dumps(r, ensure_ascii=False))
    else:
        parts.append("(no new reviews since last dream cycle)")
    parts.append("")

    parts.append("### Current Project Rules\n")
    parts.append(data.get("project_rules") or "(empty)")

    return "\n".join(parts)


def _call_llm(prompt: str) -> str | None:
    """Make an LLM API call. Uses the global default provider from agent config.

    Design note: The dream engine uses the global default provider rather than
    any agent-specific provider. This is intentional — the dream is a utility
    process, not an agent. It runs in an isolated context (cron job) and doesn't
    need agent-specific routing. If provider-specific behavior is needed in the
    future, pass a provider_name parameter to this function.

    **Known limitation:** No retry logic — a single failed API call (network blip,
    rate limit, timeout) will fail the entire dream cycle for that role. Since this
    runs unattended at 2 AM, a transient failure means no analysis until the next
    cycle. This is acceptable for the initial implementation but may need retry
    logic (1-2 retries with exponential backoff) once the system is running reliably.

    Returns the response text or None on failure.
    """
    try:
        from agent.config import load_agent_config
        import urllib.request

        config = load_agent_config()
        provider_name = config.default_provider
        provider = config.providers.get(provider_name)
        if not provider:
            logger.error("[dream] No provider configured: %s", provider_name)
            return None

        # Build request
        model = provider.default_model
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": 0.3,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]

    except Exception as e:
        logger.error("[dream] LLM API call failed: %s: %s", type(e).__name__, e)
        return None


# ── Phase 3: Synthesize ──────────────────────────────────────────────────────


def _synthesize(analysis: dict) -> DreamProposals:
    """Convert LLM analysis into concrete proposals.

    Validates the analysis output and creates DreamProposals.
    """
    proposals = DreamProposals()

    if not analysis or "proposals" not in analysis:
        return proposals

    raw_proposals = analysis.get("proposals", {})

    # Agent prompt additions
    proposals.agent_prompt_additions = raw_proposals.get("agent_prompt_additions", [])

    # Agent rules additions (keyed by project name)
    proposals.agent_rules_additions = raw_proposals.get("agent_rules_additions", {})

    # Bug journal syntheses
    proposals.bug_journal_syntheses = raw_proposals.get("bug_journal_syntheses", [])

    # Bug journal pruning (IDs to archive)
    proposals.bug_journal_prune = raw_proposals.get("bug_journal_prune", [])

    return proposals


# ── Phase 4: Write ───────────────────────────────────────────────────────────


def _apply_changes(
    project_path: str,
    proposals: DreamProposals,
    analysis: dict,
    agent_role: str,
) -> tuple[int, int, bool]:
    """Apply proposals to project files for a specific agent role.

    Returns (entries_added, entries_pruned, rules_updated).
    """
    entries_added = 0
    entries_pruned = 0
    rules_updated = False

    # 4a. Update bug journal with syntheses
    if proposals.bug_journal_syntheses:
        entries_added = _add_syntheses_to_journal(
            project_path, proposals.bug_journal_syntheses, agent_role
        )

    # 4b. Prune old entries if journal is too large
    journal_path = os.path.join(project_path, ".crabcakes", f"{agent_role}-bugs.md")
    if os.path.isfile(journal_path):
        entry_count = _count_journal_entries(journal_path)
        if entry_count > MAX_JOURNAL_ENTRIES:
            entries_pruned = _prune_journal(
                journal_path,
                proposals.bug_journal_prune,
                target=MAX_JOURNAL_ENTRIES - 10,  # Prune to 40 to give room
            )

    # 4c. Update project rules
    if proposals.agent_rules_additions:
        project_name = os.path.basename(project_path)
        additions = proposals.agent_rules_additions.get(project_name, [])
        if additions:
            rules_updated = _add_to_project_rules(project_path, additions, agent_role)

    # 4d. Store agent prompt proposals for human review (DO NOT auto-apply)
    if proposals.agent_prompt_additions:
        _store_agent_prompt_proposal(
            project_path, proposals.agent_prompt_additions, analysis, agent_role
        )

    return entries_added, entries_pruned, rules_updated


def _add_syntheses_to_journal(project_path: str, syntheses: list[dict],
                               agent_role: str) -> int:
    """Add synthesized meta-lessons to the agent's bug journal."""
    journal_path = os.path.join(project_path, ".crabcakes", f"{agent_role}-bugs.md")
    next_num = _get_next_bug_number(journal_path)
    today = datetime.date.today().isoformat()
    added = 0

    os.makedirs(os.path.dirname(journal_path), exist_ok=True)

    with open(journal_path, "a", encoding="utf-8") as f:
        for synth in syntheses:
            pattern = synth.get("pattern", "unknown")
            lesson = synth.get("lesson", "")
            sources = synth.get("source_bugs", [])
            source_str = ", ".join(f"Bug #{b}" for b in sources) if sources else "multiple"

            entry = (
                f"\n## Bug #{next_num} — {today} — synthesized\n\n"
                f"**Task:** Pattern synthesis ({source_str})\n"
                f"**Mistake:** Recurring pattern: {pattern}\n"
                f"**Expected:** Agent avoids this class of mistakes\n"
                f"**Actual:** Pattern repeated {len(sources)} times\n"
                f"**Lesson:** {lesson}\n"
                f"**Pattern:** {pattern}\n\n"
                f"---\n"
            )
            f.write(entry)
            next_num += 1
            added += 1

    return added


def _get_next_bug_number(journal_path: str) -> int:
    """Determine the next bug number from the journal."""
    if not os.path.isfile(journal_path):
        return 1
    with open(journal_path, "r", encoding="utf-8") as f:
        content = f.read()
    nums = re.findall(r"## Bug #(\d+)", content)
    return max(int(n) for n in nums) + 1 if nums else 1


def _count_journal_entries(journal_path: str) -> int:
    """Count entries in the bug journal."""
    if not os.path.isfile(journal_path):
        return 0
    with open(journal_path, "r", encoding="utf-8") as f:
        content = f.read()
    return len(re.findall(r"## Bug #(\d+)", content))


def _prune_journal(journal_path: str, prune_ids: list[int], target: int) -> int:
    """Archive old journal entries, keeping the most recent ones.

    Moves pruned entries to {role}-bugs-archive.md.
    """
    if not os.path.isfile(journal_path):
        return 0

    with open(journal_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find all entries with their positions
    entries = list(re.finditer(r"(## Bug #(\d+).*?)(?=\n## Bug #|\Z)", content, re.DOTALL))
    if len(entries) <= target:
        return 0

    # Determine which entries to prune (oldest first, prefer ones in prune_ids)
    to_prune = set()
    for entry in entries:
        if len(to_prune) >= len(entries) - target:
            break
        bug_num = int(entry.group(2))
        if bug_num in prune_ids or len(to_prune) < len(entries) - target:
            to_prune.add(bug_num)

    if not to_prune:
        return 0

    # Archive pruned entries
    archive_path = journal_path.replace("-bugs.md", "-bugs-archive.md")
    pruned_content = []
    for entry in entries:
        bug_num = int(entry.group(2))
        if bug_num in to_prune:
            pruned_content.append(entry.group(1))

    if pruned_content:
        os.makedirs(os.path.dirname(archive_path), exist_ok=True)
        with open(archive_path, "a", encoding="utf-8") as f:
            f.write("\n\n".join(pruned_content) + "\n")

    # Remove pruned entries from active journal
    # Use entry positions (match.span) instead of regex substitution to avoid
    # overlapping matches and DOTALL fragility across entries
    remaining_parts = []
    prev_end = 0
    for entry in entries:
        bug_num = int(entry.group(2))
        if bug_num not in to_prune:
            remaining_parts.append(content[prev_end:entry.start()])
            remaining_parts.append(entry.group(0))
            prev_end = entry.end()
    remaining_parts.append(content[prev_end:])
    remaining = "".join(remaining_parts)

    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(remaining.strip() + "\n")

    return len(to_prune)


def _add_to_project_rules(project_path: str, additions: list[str],
                           agent_role: str) -> bool:
    """Append new gotchas to the agent's project rules file."""
    rules_path = os.path.join(project_path, ".crabcakes", f"{agent_role}-rules.md")
    if not os.path.isfile(rules_path):
        return False

    # Find or create "## Known Gotchas" section
    with open(rules_path, "r", encoding="utf-8") as f:
        content = f.read()

    gotchas_section = "## Known Gotchas"
    if gotchas_section in content:
        # Append after the section header
        insertion_point = content.index(gotchas_section) + len(gotchas_section)
        # Find next ## heading or end of file
        after = content[insertion_point:]
        next_section = re.search(r"\n## ", after)
        if next_section:
            insert_at = insertion_point + next_section.start()
            new_content = (
                content[:insert_at] +
                "\n" + "\n".join(f"- {a}" for a in additions) +
                content[insert_at:]
            )
        else:
            new_content = content + "\n" + "\n".join(f"- {a}" for a in additions)
    else:
        # Add new section at end
        new_content = content.rstrip() + f"\n\n{gotchas_section}\n" + "\n".join(f"- {a}" for a in additions)

    with open(rules_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def _store_agent_prompt_proposal(project_path: str, additions: list[str],
                                  analysis: dict, agent_role: str) -> None:
    """Store proposed prompt changes for human review.

    Files go to .crabcakes/dream-proposals/{role}-YYYY-MM-DDTHH-MM-SS.json
    """
    proposals_dir = os.path.join(project_path, ".crabcakes", DREAM_PROPOSALS_DIR)
    os.makedirs(proposals_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    proposal_file = os.path.join(proposals_dir, f"{agent_role}-{timestamp}.json")

    proposal = {
        "type": "agent_prompt_additions",
        "agent_role": agent_role,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "pending_review",
        "additions": additions,
        "patterns": [p.get("pattern") for p in analysis.get("patterns", [])],
        "summary": analysis.get("summary", ""),
    }

    with open(proposal_file, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)

    logger.info("[dream] Stored %s prompt proposal at %s", agent_role, proposal_file)


# ── Phase 5: Verify ──────────────────────────────────────────────────────────


def _log_dream_cycle(project_path: str, agent_role: str, result: DreamResult) -> None:
    """Append dream cycle result to dream-log.jsonl."""
    log_path = os.path.join(project_path, ".crabcakes", DREAM_LOG_FILENAME)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "agent_role": agent_role,
        "status": "completed" if result.success else "failed",
        "patterns_found": result.patterns_found,
        "journal_entries_added": result.journal_entries_added,
        "journal_entries_pruned": result.journal_entries_pruned,
        "rules_updated": result.rules_updated,
        "agent_prompt_proposed": result.agent_prompt_proposed,
        "summary": result.summary,
        "duration_seconds": result.duration_seconds,
        "error": result.error if not result.success else None,
    }

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Public API ────────────────────────────────────────────────────────────────


def run_dream_cycle(project_path: str,
                    agent_roles: list[str] | None = None) -> dict[str, DreamResult]:
    """Execute a full dream consolidation cycle.

    Args:
        project_path: Absolute path to the project root.
        agent_roles: List of agent roles to process (e.g. ["coder", "debugger"]).
            If None, auto-discovers all roles with dream_consolidation: true
            in their agent YAML definitions.

    Returns:
        Dict mapping agent_role to DreamResult with details of what was done.
    """
    # Discover roles to process
    if agent_roles is None:
        agent_roles = _discover_dream_enabled_roles()

    if not agent_roles:
        logger.info("[dream] No dream-enabled agent roles found — nothing to do")
        return {}

    logger.info("[dream] Starting dream cycle for %s (roles: %s)", project_path, agent_roles)

    results: dict[str, DreamResult] = {}

    for role in agent_roles:
        results[role] = _run_dream_for_role(project_path, role)

    return results


def _run_dream_for_role(project_path: str, agent_role: str) -> DreamResult:
    """Execute dream cycle for a single agent role."""
    start = datetime.datetime.now()
    logger.info("[dream] Processing role: %s", agent_role)

    try:
        # Phase 1: Gather
        data = _gather_data(project_path, agent_role)
        review_count = len(data.get("new_reviews", []))

        if review_count == 0:
            logger.info("[dream] No new reviews for %s since last cycle — skipping", agent_role)
            result = DreamResult(
                agent_role=agent_role,
                success=True,
                summary="No new reviews to process",
            )
            result.duration_seconds = (datetime.datetime.now() - start).total_seconds()
            _log_dream_cycle(project_path, agent_role, result)
            return result

        logger.info("[dream] Gathered %d new review entries for %s", review_count, agent_role)

        # Phase 2: Analyze
        analysis = _analyze_with_llm(data, project_path)
        if analysis is None:
            result = DreamResult(
                agent_role=agent_role,
                success=False,
                error="LLM analysis failed",
                summary="Dream cycle failed — LLM analysis returned no result",
            )
            result.duration_seconds = (datetime.datetime.now() - start).total_seconds()
            _log_dream_cycle(project_path, agent_role, result)
            return result

        patterns = analysis.get("patterns", [])
        logger.info("[dream] Found %d patterns for %s", len(patterns), agent_role)

        # Phase 3: Synthesize
        proposals = _synthesize(analysis)

        # Phase 4: Write
        entries_added, entries_pruned, rules_updated = _apply_changes(
            project_path, proposals, analysis, agent_role
        )

        # Phase 5: Verify + Log
        result = DreamResult(
            agent_role=agent_role,
            success=True,
            patterns_found=len(patterns),
            proposals=proposals,
            resolved_patterns=[p.get("pattern") for p in patterns if p.get("status") == "resolved"],
            journal_entries_added=entries_added,
            journal_entries_pruned=entries_pruned,
            rules_updated=rules_updated,
            agent_prompt_proposed=bool(proposals.agent_prompt_additions),
            summary=analysis.get("summary", f"Processed {review_count} reviews, found {len(patterns)} patterns"),
        )
        result.duration_seconds = (datetime.datetime.now() - start).total_seconds()

        _log_dream_cycle(project_path, agent_role, result)

        logger.info(
            "[dream] %s complete: %d patterns, %d syntheses, %d pruned, %s",
            agent_role, len(patterns), entries_added, entries_pruned,
            "prompt proposal pending" if result.agent_prompt_proposed else "no prompt changes",
        )

        return result

    except Exception as e:
        logger.error("[dream] Unexpected error for %s: %s: %s", agent_role, type(e).__name__, e)
        result = DreamResult(
            agent_role=agent_role,
            success=False,
            error=f"{type(e).__name__}: {e}",
            summary=f"Dream cycle failed with error: {e}",
        )
        result.duration_seconds = (datetime.datetime.now() - start).total_seconds()
        _log_dream_cycle(project_path, agent_role, result)
        return result


def get_dream_status(project_path: str) -> dict:
    """Get the status of the dream system for a project.

    Returns dict with:
        last_cycle: timestamp or None
        enabled_roles: list[str]
        total_reviews: int
        total_patterns: int (from last analysis)
        pending_proposals: int
        journals: dict[str, int]  (role → entry count)
    """
    status: dict[str, Any] = {
        "last_cycle": None,
        "enabled_roles": _discover_dream_enabled_roles(),
        "total_reviews": 0,
        "total_patterns": 0,
        "pending_proposals": 0,
        "journals": {},
    }

    # Last cycle
    from utils.review_log import get_last_dream_timestamp
    status["last_cycle"] = get_last_dream_timestamp(project_path)

    # Total reviews
    from utils.review_log import read_review_log
    status["total_reviews"] = len(read_review_log(project_path))

    # Journal sizes per role
    for role in status["enabled_roles"]:
        journal_path = os.path.join(project_path, ".crabcakes", f"{role}-bugs.md")
        status["journals"][role] = _count_journal_entries(journal_path)

    # Pending proposals
    proposals_dir = os.path.join(project_path, ".crabcakes", DREAM_PROPOSALS_DIR)
    if os.path.isdir(proposals_dir):
        for f in os.listdir(proposals_dir):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(proposals_dir, f), "r") as fh:
                        data = json.load(fh)
                    if data.get("status") == "pending_review":
                        status["pending_proposals"] += 1
                except Exception:
                    pass

    # Patterns from last dream log
    dream_log = os.path.join(project_path, ".crabcakes", DREAM_LOG_FILENAME)
    if os.path.isfile(dream_log):
        with open(dream_log, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("status") == "completed":
                        status["total_patterns"] = max(
                            status["total_patterns"],
                            entry.get("patterns_found", 0)
                        )
                except Exception:
                    pass

    return status
```

### 3.3 `.crabcakes/dream-log.jsonl` — Dream cycle results log

Auto-created by the dream engine. Format:

```json
{"timestamp": "2026-05-19T02:00:00Z", "agent_role": "coder", "status": "completed", "patterns_found": 2, "journal_entries_added": 1, "journal_entries_pruned": 0, "rules_updated": true, "agent_prompt_proposed": false, "summary": "Processed 8 reviews, found 2 patterns", "duration_seconds": 12.5, "error": null}
```

### 3.4 `.crabcakes/dream-proposals/` — Pending prompt change proposals

Directory containing JSON files with proposed prompt changes. Named `{role}-YYYY-MM-DDTHH-MM-SS.json`. Each file:

```json
{
  "type": "agent_prompt_additions",
  "agent_role": "coder",
  "timestamp": "2026-05-19T02:00:00Z",
  "status": "pending_review",
  "additions": [
    "| Mock Object Truthiness | `if value is not None` always True with MagicMock | Use `isinstance(value, ExpectedType)` to verify type |"
  ],
  "patterns": ["mock-truthiness"],
  "summary": "Found 3 mock-truthiness bugs across 2 projects"
}
```

**Approval workflow:**
1. Dream stores proposal with `"status": "pending_review"`
2. Human reviews the proposal file
3. To accept: apply the additions to `prompts/system/{role}.md` and set `"status": "accepted"`
4. To reject: set `"status": "rejected"` (keep file for history)

---

## 4. Cron Job Setup

### 4.1 OpenClaw Cron Configuration

Uses the CLI-wrapper approach described in §2.2. The cron job triggers a Python script
via the isolated agent's exec tool, rather than trying to import CrabCakes modules directly.

```python
cron.add({
    "name": "crabwatch-dream-consolidation",
    "schedule": {
        "kind": "cron",
        "expr": "0 2 * * *",
        "tz": "America/Los_Angeles"
    },
    "payload": {
        "kind": "agentTurn",
        "message": "Run the dream consolidation script for crabwatch. Execute: cd /home/q/projects/crabcakes && python3 -m utils.dream_engine_cli --project /home/q/projects/crabwatch",
        "toolsAllow": ["exec"],
    },
    "sessionTarget": "isolated",
    "delivery": {"mode": "announce"},
    "enabled": True,
})
```

**Note:** The cron job uses `toolsAllow: ["exec"]` because it runs a Python script via the
isolated agent's exec tool. The actual CrabCakes code runs in the Python process, not in the
OpenClaw agent session.

### 4.2 On-Demand Execution

```python
from agent.dream_engine import run_dream_cycle

# All dream-enabled roles
results = run_dream_cycle("/home/q/projects/crabwatch")

# Specific role only
results = run_dream_cycle("/home/q/projects/crabwatch", agent_roles=["coder"])
```

---

## 5. Data Flow — Full Cycle

```
2 AM Pacific → Cron triggers isolated agent session
    │
    ▼
_discover_dream_enabled_roles()
    → ["coder", "security-auditor"]  (2 agents with dream_consolidation: true)
    │
    ▼ For each role:
    │
    Phase 1: Gather (role="coder")
    ├── Read .crabcakes/review-log.jsonl → filter target_role="coder" → 8 entries
    ├── Read .crabcakes/coder-bugs.md → 3 existing entries
    ├── Read .crabcakes/coder-rules.md → crabwatch rules
    └── Read prompts/system/coder.md → Common Pitfalls table
    │
    ▼
    Phase 2: Analyze
    ├── Build input block (all gathered data)
    ├── Call LLM with dream-analysis.md prompt
    └── Parse JSON response:
        {
          "patterns": [
            {"pattern": "mock-truthiness", "frequency": 3, ...},
            {"pattern": "partial-test-run", "frequency": 2, ...}
          ],
          "proposals": {
            "agent_prompt_additions": ["| Mock Object Truthiness | ..."],
            "bug_journal_syntheses": [{"pattern": "mock-truthiness", ...}],
            "bug_journal_prune": [1, 2, 3]
          }
        }
    │
    ▼
    Phase 3: Synthesize
    ├── mock-truthiness: frequency=3 → candidate for agent prompt
    ├── partial-test-run: frequency=2 → below threshold, note only
    └── Create DreamProposals object
    │
    ▼
    Phase 4: Write
    ├── Add synthesis entry to coder-bugs.md (Bug #4: "synthesized")
    ├── Prune Bugs #1-3 → archive to coder-bugs-archive.md
    ├── Add "Tests use MagicMock extensively" to coder-rules.md
    └── Store prompt proposal in dream-proposals/coder-2026-05-19T02-00-00.json
    │
    ▼
    Phase 5: Verify + Log
    ├── Validate files are parseable
    ├── Log to dream-log.jsonl (with agent_role="coder")
    └── Announce: "coder: 2 patterns, 1 synthesis, prompt proposal pending"
    │
    ▼ Repeat for role="security-auditor" (if it has new reviews)
    │
    ▼ Done → return {"coder": DreamResult, "security-auditor": DreamResult}
```

---

## 6. Testing Plan

### 6.1 Unit Tests — `tests/test_dream_engine.py`

```python
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from agent.dream_engine import (
    run_dream_cycle, _run_dream_for_role, get_dream_status,
    _gather_data, _synthesize, _add_syntheses_to_journal,
    _prune_journal, _add_to_project_rules, _store_agent_prompt_proposal,
    _count_journal_entries, _discover_dream_enabled_roles,
    MAX_JOURNAL_ENTRIES,
)
from utils.review_log import append_review_entry


class TestRoleDiscovery:
    @patch("agent.dream_engine._discover_dream_enabled_roles.__code__", None)
    def test_discover_from_agent_defs(self, tmp_path):
        """Discovers roles with dream_consolidation: true."""
        # This would require mocking utils.agent_defs.load_agent_defs
        pass  # Integration test

    def test_no_enabled_roles(self):
        """Returns empty list when no agents have dream enabled."""
        # Mocked test
        pass


class TestGatherData:
    def test_gather_filters_by_role(self, tmp_path):
        """Gather reads {role}-specific files and filters reviews."""
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        (crab / "coder-bugs.md").write_text("## Bug #1 — test")
        (crab / "debugger-bugs.md").write_text("## Bug #1 — debugger test")
        (crab / "coder-rules.md").write_text("# Coder Rules")
        (crab / "review-log.jsonl").write_text(
            '{"timestamp":"2026-05-18T20:00:00Z","target_role":"coder","severity":"bug"}\n'
            '{"timestamp":"2026-05-18T20:00:00Z","target_role":"debugger","severity":"bug"}\n'
        )

        coder_data = _gather_data(str(tmp_path), "coder")
        assert "## Bug #1 — test" in coder_data["bug_journal"]
        assert "debugger test" not in coder_data["bug_journal"]
        assert len(coder_data["new_reviews"]) == 1
        assert coder_data["new_reviews"][0]["target_role"] == "coder"

        debugger_data = _gather_data(str(tmp_path), "debugger")
        assert "debugger test" in debugger_data["bug_journal"]
        assert len(debugger_data["new_reviews"]) == 1

    def test_gather_empty_project(self, tmp_path):
        """Gather with no .crabcakes dir returns empty data."""
        data = _gather_data(str(tmp_path), "coder")
        assert data["bug_journal"] == ""
        assert data["new_reviews"] == []


class TestSynthesize:
    def test_empty_analysis(self):
        proposals = _synthesize({})
        assert proposals.agent_prompt_additions == []

    def test_with_proposals(self):
        analysis = {
            "proposals": {
                "agent_prompt_additions": ["| Test | Pitfall | Fix |"],
                "agent_rules_additions": {"test-project": ["- new gotcha"]},
                "bug_journal_syntheses": [{"pattern": "test", "lesson": "learn"}],
                "bug_journal_prune": [1, 2],
            }
        }
        proposals = _synthesize(analysis)
        assert len(proposals.agent_prompt_additions) == 1
        assert proposals.agent_rules_additions.get("test-project") == ["- new gotcha"]
        assert len(proposals.bug_journal_prune) == 2


class TestAddSynthesesToJournal:
    def test_creates_journal(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        added = _add_syntheses_to_journal(str(tmp_path), [
            {"pattern": "test", "lesson": "test lesson", "source_bugs": [1, 2]}
        ], "coder")
        assert added == 1
        journal = (crab / "coder-bugs.md").read_text()
        assert "## Bug #1" in journal
        assert "synthesized" in journal

    def test_uses_correct_role_filename(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        _add_syntheses_to_journal(str(tmp_path), [
            {"pattern": "test", "lesson": "test", "source_bugs": []}
        ], "security-auditor")
        assert (crab / "security-auditor-bugs.md").exists()
        assert not (crab / "coder-bugs.md").exists()


class TestPruneJournal:
    def test_prune_over_limit(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        journal = crab / "coder-bugs.md"
        content = ""
        for i in range(1, 55):
            content += f"## Bug #{i} — test\n\nContent for bug {i}\n\n---\n"
        journal.write_text(content)
        pruned = _prune_journal(str(journal), [1, 2, 3, 4, 5], target=40)
        assert pruned > 0
        archive = crab / "coder-bugs-archive.md"
        assert archive.exists()


class TestStoreProposal:
    def test_stores_per_role(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        _store_agent_prompt_proposal(
            str(tmp_path),
            ["| Test | Pitfall | Fix |"],
            {"patterns": [{"pattern": "test"}], "summary": "test"},
            "coder",
        )
        proposals_dir = crab / "dream-proposals"
        files = list(proposals_dir.glob("coder-*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["agent_role"] == "coder"
        assert data["status"] == "pending_review"


class TestDreamCycle:
    @patch("agent.dream_engine._analyze_with_llm")
    @patch("agent.dream_engine._discover_dream_enabled_roles")
    def test_full_cycle_multi_role(self, mock_discover, mock_analyze, tmp_path):
        """End-to-end dream cycle with 2 roles."""
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        (crab / "coder-bugs.md").write_text("# Journal\n\n---\n")
        (crab / "coder-rules.md").write_text("# Rules\n\n## Known Gotchas\n- existing\n")
        (crab / "debugger-bugs.md").write_text("# Journal\n\n---\n")

        # Add reviews targeting both roles
        append_review_entry(str(tmp_path), {
            "timestamp": "2026-05-19T00:00:00Z",
            "target_role": "coder",
            "severity": "bug",
            "pattern": "test-pattern",
            "bug": "test bug",
        })

        mock_discover.return_value = ["coder"]
        mock_analyze.return_value = {
            "patterns": [{"pattern": "test-pattern", "frequency": 3, "status": "active"}],
            "proposals": {
                "agent_prompt_additions": ["| Test | Pattern | Fix |"],
                "agent_rules_additions": {os.path.basename(str(tmp_path)): ["- new rule"]},
                "bug_journal_syntheses": [{"pattern": "test-pattern", "lesson": "test lesson", "source_bugs": [1]}],
                "bug_journal_prune": [],
            },
            "summary": "Found 1 pattern",
        }

        results = run_dream_cycle(str(tmp_path))
        assert "coder" in results
        assert results["coder"].success is True
        assert results["coder"].patterns_found == 1
        assert results["coder"].journal_entries_added == 1

    def test_cycle_no_reviews(self, tmp_path):
        """Cycle with no reviews skips analysis."""
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        results = run_dream_cycle(str(tmp_path), agent_roles=["coder"])
        assert results["coder"].success is True
        assert "No new reviews" in results["coder"].summary


class TestGetDreamStatus:
    def test_status_with_data(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        (crab / "coder-bugs.md").write_text("## Bug #1 — test\n## Bug #2 — test\n")
        (crab / "review-log.jsonl").write_text(
            '{"timestamp":"2026-05-18T00:00:00Z","target_role":"coder"}\n'
        )
        (crab / "dream-log.jsonl").write_text(
            '{"timestamp":"2026-05-19T02:00:00Z","agent_role":"coder","status":"completed","patterns_found":3}\n'
        )

        with patch("agent.dream_engine._discover_dream_enabled_roles", return_value=["coder"]):
            status = get_dream_status(str(tmp_path))
        assert status["total_reviews"] == 1
        assert status["journals"].get("coder") == 2
        assert status["total_patterns"] == 3
```

---

## 7. Acceptance Criteria

- [ ] `prompts/system/dream-analysis.md` created with full analysis prompt
- [ ] `agent/dream_engine.py` created with all 5 phases
- [ ] `_discover_dream_enabled_roles()` reads agent YAML definitions for dream_consolidation flag
- [ ] `run_dream_cycle()` accepts optional `agent_roles` list, auto-discovers if None
- [ ] `run_dream_cycle()` returns `dict[str, DreamResult]` — one result per role
- [ ] `_gather_data()` reads `{role}-bugs.md`, `{role}-rules.md`, and filters review-log by `target_role`
- [ ] Bug journal syntheses are correctly formatted and appended to the right role's file
- [ ] Journal pruning archives old entries when count exceeds 50
- [ ] Project rules are updated with new gotchas for the correct role
- [ ] Agent prompt proposals are stored in `{role}-YYYY-MM-DDTHH-MM-SS.json` but NOT auto-applied
- [ ] Dream log records each role's cycle results with `agent_role` field
- [ ] `get_dream_status()` returns per-role journal sizes and enabled roles
- [ ] LLM call uses configured provider from agent config
- [ ] Idempotency: re-running with no new reviews is a no-op
- [ ] All tests in `test_dream_engine.py` pass
- [ ] Error handling: LLM failure, missing files, malformed data all handled gracefully
- [ ] No hardcoded "coder" references — all file paths and logic parameterized by `agent_role`
