---
status: DONE
---
# SPEC-3: Structured Feedback Protocol

**Implements:** Self-Improvement Layer 4
**Estimated effort:** ~3 hours
**Depends on:** User-Defined Local Agents (agent YAML with `self_improvement.structured_feedback` flag), SPEC-1 (bug journal format and auto-population)
**Enables:** SPEC-4 (dream consolidation consumes structured feedback data)

---

## 1. Overview

This specification adds a machine-parseable format for adversarial audit reports. When one agent (e.g., Qaster) reviews another agent's (e.g., Coder's) work, the feedback follows a structured format that can be:

1. **Automatically added to the bug journal** (SPEC-1) — no manual entry needed
2. **Logged to a review history file** — queryable record of all code review feedback
3. **Consumed by the dream consolidation layer** (SPEC-4) — raw data for pattern analysis

The structured format is embedded in regular agent messages. It's detected and parsed by the agent command handler without changing the message flow — the report still reaches the target agent as normal text, but it's simultaneously processed and logged.

**Agent gating:** Structured feedback processing (auto-populating bug journals) only applies when the *target* agent (the one being reviewed) has `self_improvement.structured_feedback: true` in its YAML definition. This defaults to `false` — only agents that opt in get automatic audit report processing. The review-log.jsonl logging happens for ALL agents regardless of this flag (it's just data recording).

---

## 2. Audit Report Format

### 2.1 Text Format

Audit reports are embedded in agent messages using a specific markdown section format:

```markdown
## Audit Report
**Task:** Task 7 — Install script
**File:** install.sh:57
**Severity:** bug
**Bug:** sed replaces all "python3" including inside venv path
**Expected:** .venv/bin/python3 stays intact
**Actual:** .venv/bin/.venv/bin/python3 (double-nested)
**Root cause:** sed expression matches all occurrences of "python3" substring
**Fix:** Remove the sed python3 replacement line entirely
**Pattern:** sed-overmatch
**Tests:** bash -n install.sh (syntax), manual verification of generated paths
```

### 2.2 Field Specification

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `Task` | Yes | string | Which task or work item triggered this |
| `File` | Yes | string | File path with optional `:line` suffix |
| `Severity` | Yes | enum | `bug` (must fix), `issue` (should fix), `suggestion` (nice to have) |
| `Bug` | Yes | string | One-sentence description of the problem |
| `Expected` | Yes | string | What the correct behavior should be |
| `Actual` | Yes | string | What actually happens |
| `Root cause` | No | string | Why it happened (valuable for learning) |
| `Fix` | No | string | What to do about it |
| `Pattern` | No | string | kebab-case tag matching SPEC-1 pattern taxonomy |
| `Tests` | No | string | How to verify the fix |

### 2.3 Detection Rules

A message contains an audit report if it has a line matching `## Audit Report` followed by a block of `**Field:** Value` lines. Detection is:

1. **Start marker:** Line equals exactly `## Audit Report` (case-sensitive, no extra text)
2. **End marker:** Next `##` heading, blank line, or end of message
3. **Validation:** Must have at minimum `Task`, `File`, `Severity`, and `Bug` fields

Multiple audit reports can appear in a single message (one per `## Audit Report` section).

### 2.4 Severity Levels

| Level | Meaning | Action Required |
|-------|---------|-----------------|
| `bug` | Must fix — code is broken or will break | Fix before proceeding |
| `issue` | Should fix — suboptimal but functional | Fix in current pass |
| `suggestion` | Nice to have — improvement opportunity | Optional |

### 2.5 Known Pattern Tags

These tags are used for clustering in SPEC-1 and SPEC-4:

| Pattern | Description |
|---------|-------------|
| `mock-truthiness` | Checking truthiness instead of type on mock objects |
| `partial-test-run` | Running only the failing test instead of full suite |
| `type-confusion` | Comparing integer enum to string, or similar type mismatches |
| `sed-overmatch` | sed/regex matching too broadly, replacing inside existing paths |
| `over-fixing` | Fix that's too aggressive, breaking adjacent functionality |
| `wrong-entry-point` | Using wrong command/module name for execution |
| `missing-mkdir` | Writing to directory that doesn't exist without creating it |

New patterns can be invented as needed — the system just stores whatever string is provided.

---

## 3. Files to Create

### 3.1 `utils/audit_parser.py` — Structured report extraction

New utility module. Pure Python, no GTK, no network.

**Public API:**

```python
@dataclass
class AuditReport:
    """Parsed structured audit report."""
    task: str                           # Task description
    file_path: str                      # File path (may include :line)
    severity: str                       # "bug" | "issue" | "suggestion"
    bug_description: str                # One-line bug description
    expected: str                       # Expected behavior
    actual: str                         # Actual behavior
    root_cause: str | None = None       # Why it happened
    fix: str | None = None              # How to fix it
    pattern: str | None = None          # Taxonomy tag
    tests: str | None = None            # How to verify
    raw_text: str = ""                  # Original markdown text

    @property
    def file_name(self) -> str:
        """File path without line number."""
        return self.file_path.split(":")[0]

    @property
    def line_number(self) -> int | None:
        """Line number if present, else None."""
        parts = self.file_path.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return int(parts[1])
        return None

    @property
    def is_bug(self) -> bool:
        return self.severity == "bug"

    def to_bug_journal_entry(self, bug_number: int, date: str) -> str:
        """Convert to SPEC-1 bug journal entry format."""
        lines = [
            f"## Bug #{bug_number} — {date} — {self.file_name}",
            "",
            f"**Task:** {self.task}",
            f"**Mistake:** {self.bug_description}",
            f"**Expected:** {self.expected}",
            f"**Actual:** {self.actual}",
        ]
        if self.fix:
            lines.append(f"**Fix:** {self.fix}")
        if self.root_cause:
            lines.append(f"**Lesson:** {self.root_cause}")
        if self.pattern:
            lines.append(f"**Pattern:** {self.pattern}")
        lines.append("")
        lines.append("---")
        return "\n".join(lines)

    def to_review_log_entry(self, reviewer: str, project_path: str, target_role: str = "unknown") -> dict:
        """Convert to JSONL-compatible dict for review-log.

        Args:
            reviewer: Display name of the reviewing agent.
            project_path: Absolute path to the project.
            target_role: Role identifier of the agent being reviewed (e.g. "coder").
                Used by SPEC-4 dream consolidation to filter reviews per agent role.
        """
        import datetime
        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "reviewer": reviewer,
            "target_role": target_role,
            "project_path": project_path,
            "task": self.task,
            "file": self.file_path,
            "severity": self.severity,
            "bug": self.bug_description,
            "expected": self.expected,
            "actual": self.actual,
            "root_cause": self.root_cause,
            "fix": self.fix,
            "pattern": self.pattern,
            "tests": self.tests,
        }


def extract_audit_reports(text: str) -> list[AuditReport]:
    """Extract all structured audit reports from message text.

    Scans for '## Audit Report' sections and parses the **Field: Value** lines.

    **Note:** This function does NOT strip fenced code blocks (```...```).
    If audit reports appear inside code blocks, they WILL be detected.
    Callers must strip fenced blocks first using `_strip_fenced_blocks()`
    if fenced-block content should be excluded.

    Args:
        text: Full message text from an agent response.

    Returns:
        List of parsed AuditReport objects. Empty list if none found.
    """
    reports = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if line == "## Audit Report":
            # Collect lines until next heading or end
            report_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                # Stop at next ## heading
                if next_line.strip().startswith("## ") and next_line.strip() != "## Audit Report":
                    break
                # Stop at completely blank line followed by non-field content
                if not next_line.strip():
                    # Peek ahead — if next line is not a **field**, stop
                    if i + 1 < len(lines) and not lines[i + 1].strip().startswith("**"):
                        break
                report_lines.append(next_line)
                i += 1

            report = _parse_report_section(report_lines)
            if report is not None:
                reports.append(report)
        else:
            i += 1

    return reports


def _parse_report_section(lines: list[str]) -> AuditReport | None:
    """Parse a single audit report section from collected lines.

    Returns None if required fields are missing.
    """
    fields: dict[str, str] = {}
    field_re = re.compile(r"^\*\*(.+?)\*\*:\s*(.+)$")

    for line in lines:
        match = field_re.match(line.strip())
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            fields[key] = value

    # Required fields
    required = ["Task", "File", "Severity", "Bug"]
    for req in required:
        if req not in fields:
            return None

    # Validate severity
    if fields["Severity"] not in ("bug", "issue", "suggestion"):
        return None

    raw_text = "\n".join(lines)

    return AuditReport(
        task=fields["Task"],
        file_path=fields["File"],
        severity=fields["Severity"],
        bug_description=fields["Bug"],
        expected=fields.get("Expected", ""),
        actual=fields.get("Actual", ""),
        root_cause=fields.get("Root cause"),
        fix=fields.get("Fix"),
        pattern=fields.get("Pattern"),
        tests=fields.get("Tests"),
        raw_text=raw_text,
    )
```

**Import required:** `import re`, `from dataclasses import dataclass`

### 3.2 `utils/review_log.py` — Review history persistence

New utility module. Manages the append-only review log.

**Public API:**

```python
REVIEW_LOG_FILENAME = "review-log.jsonl"
DREAM_LOG_FILENAME = "dream-log.jsonl"  # Shared with agent/dream_engine.py — single definition

def get_review_log_path(project_path: str) -> str:
    """Get the path to the review log file for a project."""
    return os.path.join(project_path, ".crabcakes", REVIEW_LOG_FILENAME)

def append_review_entry(project_path: str, entry: dict) -> None:
    """Append a single entry to the review log.

    Creates the file and .crabcakes/ directory if they don't exist.

    Args:
        project_path: Absolute path to the project root.
        entry: Dict to serialize as JSON line. Must be JSON-serializable.
    """
    log_path = get_review_log_path(project_path)

    # Ensure .crabcakes/ directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    line = json.dumps(entry, ensure_ascii=False)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def read_review_log(project_path: str, since: str | None = None) -> list[dict]:
    """Read entries from the review log.

    Args:
        project_path: Absolute path to the project root.
        since: Optional ISO timestamp — only return entries after this time.

    Returns:
        List of parsed JSON dicts, oldest first.
    """
    log_path = get_review_log_path(project_path)
    if not os.path.isfile(log_path):
        return []

    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if since and entry.get("timestamp", "") <= since:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue  # Skip malformed lines

    return entries

def get_last_dream_timestamp(project_path: str) -> str | None:
    """Get the timestamp of the last dream cycle for this project.

    Reads .crabcakes/dream-log.jsonl to find the last completed dream cycle.
    Returns ISO timestamp string or None if no dream has run.
    """
    dream_log = os.path.join(project_path, ".crabcakes", DREAM_LOG_FILENAME)
    if not os.path.isfile(dream_log):
        return None

    last_ts = None
    with open(dream_log, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("status") == "completed":
                    last_ts = entry.get("timestamp")
            except json.JSONDecodeError:
                continue

    return last_ts
```

**Imports required:** `import os`, `import json`

### 3.3 `utils/feedback_processor.py` — Audit report processing (file I/O + role resolution)

New utility module containing all file I/O for audit report processing. Pure Python — no GTK, no network.
This is the rightful home for bug-journal appends and role resolution. The handler calls these functions;
it never does file I/O itself.

**Public API:**

```python
from utils.audit_parser import AuditReport
from typing import Any

# ── Defaults — delegate to centralized source ──────────────────────────────
# Use get_default_si_config() from utils/agent_defs.py as the single source of truth.
# Do NOT duplicate defaults here — that's how bugs happen.

def get_target_si_config(target_role: str) -> dict:
    """Get the self_improvement config for the target agent role.

    Loads agent definitions and finds the one matching the target role,
    then returns its self_improvement config dict.

    Returns defaults if agent defs can't be loaded or role not found.
    """
    from utils.agent_defs import get_default_si_config
    try:
        from utils.agent_defs import load_agent_defs
        defs = load_agent_defs()
        for d in defs:
            role = d.get("role", d.get("name", "").lower().replace(" ", "-"))
            if role == target_role:
                can_write = "write_file" in d.get("tools", [])
                defaults = get_default_si_config(can_write=can_write)
                si = d.get("self_improvement", {})
                return {**defaults, **si}
    except Exception:
        pass
    return get_default_si_config(can_write=False)

def resolve_role_from_session(session_key: str, runtime_handler: Any = None) -> str:
    """Resolve an agent role from a session key.

    For special agents (session_key starts with "special:"), extract the
    role from SpecialAgentDef via the runtime handler. For gateway agents,
    return 'unknown'.

    Args:
        session_key: Agent session key.
        runtime_handler: AgentRuntimeHandler instance (optional, used for
            special agent lookups).
    """
    if session_key.startswith("special:"):
        if runtime_handler:
            sad = runtime_handler.get_special_agent_def(session_key)
            if sad and hasattr(sad, 'role'):
                return sad.role
    return "unknown"

def resolve_default_target_role() -> str:
    """Resolve the default target role when no pending ask context exists.

    Looks up all agent definitions with write tools. If exactly one
    writing agent exists, returns its role. Otherwise returns 'unknown'
    to avoid mis-filing audit reports.
    """
    try:
        from utils.agent_defs import load_agent_defs
        all_defs = load_agent_defs()
        writers = [d for d in all_defs if 'write_file' in d.get('tools', [])]
        if len(writers) == 1:
            return writers[0].get('role', 'unknown')
    except Exception:
        pass
    return "unknown"

def append_to_bug_journal(project_path: str, report: AuditReport, target_role: str) -> None:
    """Append an audit report as a new entry in the target agent's bug journal.

    Reads the current bug journal for the given agent role, determines
    the next bug number, and appends the new entry.

    Args:
        project_path: Absolute path to the project root.
        report: Parsed AuditReport to append.
        target_role: Role identifier of the agent being reviewed (e.g. "coder").
            Determines which {role}-bugs.md file to write to.
    """
    import datetime
    import re
    journal_path = os.path.join(project_path, ".crabcakes", f"{target_role}-bugs.md")

    # Determine next bug number
    next_num = 1
    if os.path.isfile(journal_path):
        with open(journal_path, "r", encoding="utf-8") as f:
            content = f.read()
        nums = re.findall(r"## Bug #(\d+)", content)
        if nums:
            next_num = max(int(n) for n in nums) + 1

    # Generate entry
    today = datetime.date.today().isoformat()
    entry_text = report.to_bug_journal_entry(next_num, today)

    # Append to file (create if doesn't exist)
    os.makedirs(os.path.dirname(journal_path), exist_ok=True)
    with open(journal_path, "a", encoding="utf-8") as f:
        if os.path.isfile(journal_path) and os.path.getsize(journal_path) > 0:
            f.write("\n")
        f.write(entry_text + "\n")

    logger.info("[feedback] Appended Bug #%d to %s", next_num, journal_path)

def process_audit_reports(
    project_path: str,
    reports: list[AuditReport],
    reviewer: str,
    target_role: str,
) -> None:
    """Process a list of parsed audit reports: log and optionally append to bug journal.

    For each audit report found:
    1. Log to .crabcakes/review-log.jsonl (always, with target_role)
    2. Auto-append to .crabcakes/{role}-bugs.md if:
       - severity is 'bug'
       - target agent has self_improvement.structured_feedback: true

    Args:
        project_path: Absolute path to the project root.
        reports: List of parsed AuditReport objects.
        reviewer: Display name of the reviewing agent.
        target_role: Role identifier of the agent being reviewed.
    """
    from utils.review_log import append_review_entry

    # Check target agent's structured_feedback flag
    si_config = get_target_si_config(target_role)
    structured_feedback_enabled = si_config.get("structured_feedback", False)

    for report in reports:
        # 1. Log to review-log.jsonl (always, regardless of flag)
        try:
            entry = report.to_review_log_entry(reviewer, project_path, target_role=target_role)
            append_review_entry(project_path, entry)
            logger.info(
                "[feedback] Logged audit report: %s %s (%s) target=%s",
                report.severity, report.file_path, report.pattern or "no-pattern",
                target_role
            )
        except Exception as e:
            logger.warning("[feedback] Failed to log audit report: %s", e)

        # 2. Auto-append to bug journal if severity is 'bug' AND structured_feedback enabled
        if report.is_bug and structured_feedback_enabled:
            try:
                append_to_bug_journal(project_path, report, target_role)
            except Exception as e:
                logger.warning("[feedback] Failed to append to bug journal: %s", e)
```

**Imports required:** `import os`, `import json`, `import logging`, `from utils.audit_parser import AuditReport`

**Design rationale:** All file I/O (bug journal writes, review log writes) lives in `utils/` where it belongs.
The handler only provides runtime context (session keys, display names, pending ask state) that utilities
can't access. This follows ARCHITECTURE.md §8.6 handler pattern — handlers coordinate, utilities execute.

### 4.1 `ui/handlers/agent_command_handler.py` — Detect and process structured reports

#### 4.1.1 Add import

At the top of the file, add:

```python
from utils.audit_parser import extract_audit_reports
from utils.review_log import append_review_entry
```

#### 4.1.2 Add project_path setter and role resolution helpers

The handler needs access to the project path and the ability to resolve which agent is being reviewed. Add setters:

```python
def set_project_path_provider(self, provider) -> None:
    """Callable that returns the active project path, or None."""
    self._project_path_provider = provider

def set_agent_defs_loader(self, loader) -> None:
    """Callable that loads agent definitions for self_improvement config lookup.

    Typically wired as: lambda: utils.agent_defs.load_agent_defs()
    """
    self._agent_defs_loader = loader

# In __init__, add:
#     self._project_path_provider: Callable | None = None
#     self._agent_defs_loader: Callable | None = None
```

Wire in `window.py` as:

```python
agent_cmd_handler.set_project_path_provider(
    lambda: project_handler.get_active_project_path() if project_handler else None
)
agent_cmd_handler.set_agent_defs_loader(
    lambda: utils.agent_defs.load_agent_defs()
)
```

#### 4.1.3 Add processing method (delegates to `utils/feedback_processor.py`)

The handler's processing method is a thin coordinator that resolves runtime context
(session key, display name) then delegates all file I/O to the utility.

```python
def _process_audit_reports(self, session_key: str, text: str) -> None:
    """Detect and process structured audit reports in an agent message.

    Delegates to utils.feedback_processor for all file I/O.
    """
    from utils.feedback_processor import process_audit_reports

    # Strip fenced code blocks BEFORE extraction to prevent false positives
    # from audit-report examples or explanations inside ```...``` blocks.
    clean_text = _strip_fenced_blocks(text)
    reports = extract_audit_reports(clean_text)
    if not reports:
        return

    project_path = None
    if self._project_path_provider:
        project_path = self._project_path_provider()

    if not project_path:
        logger.debug("[agent-cmd] Audit reports found but no active project — skipping")
        return

    reviewer = self._resolve_display_name(session_key)
    target_role = self._resolve_target_role(session_key)

    process_audit_reports(
        project_path=project_path,
        reports=reports,
        reviewer=reviewer,
        target_role=target_role,
    )
```

#### 4.1.4 Delegate to `utils/feedback_processor.py` (see §3.3)

The handler's `_process_audit_reports()` method delegates all file I/O and role resolution to `utils/feedback_processor.py` (new module, see §3.3 below). The handler only provides runtime context (session keys, display names) that the utility can't access.

```python
def _resolve_target_role(self, reviewer_session_key: str) -> str:
    """Determine the target agent role from the review context.

    Delegates to feedback_processor for agent-def lookups. The handler
    only resolves the pending-ask context (which requires _pending_asks
    state that belongs to the handler).

    Strategy (in order of priority):
    1. If there's a pending ask for this reviewer, the target is the asker
    2. Look up single writing agent in project context
    3. Fallback to 'unknown'

    Args:
        reviewer_session_key: Session key of the agent that sent the audit.

    Returns:
        Role string (e.g. "coder", "debugger", "security-auditor").
    """
    # Check if there's a pending ask — the reviewer was asked by someone
    if reviewer_session_key in self._pending_asks:
        asker_sk = self._pending_asks[reviewer_session_key]
        # Resolve the asker's role from their agent definition
        return resolve_role_from_session(asker_sk, self._agent_runtime_handler)

    # No pending ask — delegate to utility for agent-def lookup
    return resolve_default_target_role()
```

#### 4.1.6 Wire into `on_agent_response()`

Add the audit report processing call at the beginning of `on_agent_response()`, after the empty-text check:

```python
def on_agent_response(self, session_key: str, text: str,
                      project_name: str | None) -> None:
    if not text:
        return

    # ── Step 0: Process structured audit reports ───────────────────────
    self._process_audit_reports(session_key, text)

    # ── Step 1: Relay answer back to asking agent ──────────────────────
    # ... (existing code continues unchanged)
```

**Why at the beginning:** The audit report processing is a side effect that should happen regardless of whether the message contains A2A commands or relay responses. It's non-blocking — failures are logged but don't prevent message delivery.

### 4.2 `ui/window.py` — Wire the project path provider

In the section where `AgentCommandHandler` is wired up, add:

```python
# After existing agent_cmd_handler.set_*() calls:
agent_cmd_handler.set_project_path_provider(
    lambda: project_handler.get_active_project_path() if project_handler else None
)
```

---

## 5. Data Flow

### 5.1 Happy Path: Reviewer sends audit to any agent

```
1. Reviewer agent responds with a message containing "## Audit Report" + structured fields
2. agent_command_handler.on_agent_response("session:reviewer:...", text, project_name) called
3. _process_audit_reports() delegates to utils/feedback_processor.process_audit_reports():
   a. extract_audit_reports(text) → [AuditReport(severity="bug", ...)]
   b. Get project_path from provider
   c. Resolve target agent role (e.g. "coder") from the pending ask
   d. Check target agent's self_improvement.structured_feedback → true
   e. For each report:
      - append_review_entry() → writes to .crabcakes/review-log.jsonl (with target_role field)
      - report.is_bug → True → append_to_bug_journal(path, report, "coder")
        - Read coder-bugs.md, find next number (e.g. #4)
        - Generate entry text from report
        - Append to .crabcakes/coder-bugs.md
4. Message continues normal flow (relay or command scan)
5. Target agent receives the message text unchanged — it sees the audit report as regular text
6. The bug journal now has a new entry that will be injected into the target agent's context next time
```

### 5.2 Multiple reports in one message

```
1. Reviewer sends a message with 2 audit reports (2 "## Audit Report" sections)
2. extract_audit_reports() returns [AuditReport, AuditReport]
3. Both are logged to review-log.jsonl (2 lines appended, each with target_role)
4. Both are appended to the target agent's bug journal ({role}-bugs.md) as Bug #4 and Bug #5
5. Message delivered to target agent unchanged
```

### 5.3 Report in a non-project context

```
1. Agent sends a message with an audit report but no project is active
2. _process_audit_reports() → project_path is None
3. Reports are detected but logged with debug message: "no active project — skipping"
4. No files written, no error raised
```

### 5.4 Agent sends report about itself (self-review)

An agent reviewing its own previous work sends an audit report. The target role resolves to itself. The review is logged normally. If structured_feedback is enabled, it goes into its own bug journal.

### 5.5 Agent with structured_feedback disabled

```
1. Reviewer sends audit about a Debugger agent's work
2. Debugger has self_improvement.structured_feedback: false in its YAML
3. _process_audit_reports() checks si_config.structured_feedback → false
4. Report is logged to review-log.jsonl (logging always happens)
5. Report is NOT appended to debugger-bugs.md (gated by flag)
```

```
1. Agent sends "## Audit Report" but missing required fields
2. _parse_report_section() returns None (validation failed)
3. Report is silently skipped — not logged, not added to journal
4. No error raised
```

---

## 6. Review Log Format

**File:** `.crabcakes/review-log.jsonl`

Each line is a JSON object:

```json
{"timestamp": "2026-05-18T21:30:00Z", "reviewer": "Qaster", "project_path": "/home/q/projects/crabwatch", "task": "Task 7 — Install script", "file": "install.sh:57", "severity": "bug", "bug": "sed replaces all python3 including inside venv path", "expected": ".venv/bin/python3 stays intact", "actual": ".venv/bin/.venv/bin/python3 (double-nested)", "root_cause": "sed expression matches all occurrences of python3 substring", "fix": "Remove the sed python3 replacement line entirely", "pattern": "sed-overmatch", "tests": "bash -n install.sh (syntax), manual verification of generated paths"}
```

**Fields:**
- `timestamp` — ISO 8601 UTC timestamp
- `reviewer` — Display name of the reviewing agent
- `project_path` — Absolute path to the project
- All other fields from the AuditReport

**Size management:** The review log is append-only and unbounded. SPEC-4 (dream consolidation) will be the consumer that prunes old entries. For now, just let it grow. A 1000-entry log would be ~200KB — negligible.

---

## 7. Testing Plan

### 7.1 Unit Tests — `tests/test_audit_parser.py` (new file)

```python
import pytest
from utils.audit_parser import extract_audit_reports, AuditReport, _parse_report_section


class TestExtractAuditReports:
    def test_single_report(self):
        text = """Some preamble text here.

## Audit Report
**Task:** Task 7 — Install script
**File:** install.sh:57
**Severity:** bug
**Bug:** sed replaces all "python3" including inside venv path
**Expected:** .venv/bin/python3 stays intact
**Actual:** .venv/bin/.venv/bin/python3 (double-nested)
**Root cause:** sed expression matches all occurrences of "python3" substring
**Fix:** Remove the sed python3 replacement line entirely
**Pattern:** sed-overmatch
**Tests:** bash -n install.sh (syntax), manual verification

Some trailing text."""

        reports = extract_audit_reports(text)
        assert len(reports) == 1
        r = reports[0]
        assert r.task == "Task 7 — Install script"
        assert r.file_path == "install.sh:57"
        assert r.file_name == "install.sh"
        assert r.line_number == 57
        assert r.severity == "bug"
        assert r.is_bug is True
        assert r.pattern == "sed-overmatch"
        assert r.root_cause == 'sed expression matches all occurrences of "python3" substring'

    def test_multiple_reports(self):
        text = """## Audit Report
**Task:** Task 7
**File:** install.sh:57
**Severity:** bug
**Bug:** sed overmatch

## Audit Report
**Task:** Task 7
**File:** install.sh:80
**Severity:** issue
**Bug:** missing mkdir

Some text between."""

        reports = extract_audit_reports(text)
        assert len(reports) == 2
        assert reports[0].severity == "bug"
        assert reports[1].severity == "issue"
        assert reports[1].is_bug is False

    def test_no_reports(self):
        text = "Just a regular message with no audit reports."
        assert extract_audit_reports(text) == []

    def test_incomplete_report_skipped(self):
        """Missing required fields → report is skipped."""
        text = """## Audit Report
**Task:** Task 7
**File:** install.sh
**Severity:** invalid_severity
**Bug:** something wrong"""
        # Invalid severity → report is skipped
        reports = extract_audit_reports(text)
        assert len(reports) == 0

    def test_minimal_valid_report(self):
        """Report with only required fields."""
        text = """## Audit Report
**Task:** Task 7
**File:** install.sh
**Severity:** suggestion
**Bug:** could be improved"""
        reports = extract_audit_reports(text)
        assert len(reports) == 1
        r = reports[0]
        assert r.root_cause is None
        assert r.fix is None
        assert r.pattern is None

    def test_report_with_special_characters(self):
        """Report with quotes, backslashes, etc. in field values."""
        text = '''## Audit Report
**Task:** Task with "quotes"
**File:** path/to/file.py:42
**Severity:** bug
**Bug:** regex `r"\\n"` matched incorrectly'''
        reports = extract_audit_reports(text)
        assert len(reports) == 1
        assert '"quotes"' in reports[0].task

    def test_report_in_code_block_not_detected(self):
        """Audit report inside a fenced code block should NOT be detected.
        Note: _strip_fenced_blocks() is called BEFORE audit extraction in
        on_agent_response(), but extract_audit_reports() itself is naive."""
        text = """```
## Audit Report
**Task:** fake
**File:** fake.py
**Severity:** bug
**Bug:** not real
```"""
        # extract_audit_reports is naive — it WILL detect this.
        # The caller (on_agent_response) should strip fenced blocks first.
        # This test documents the behavior.
        reports = extract_audit_reports(text)
        assert len(reports) == 1  # Naive detection — caller must strip


class TestAuditReportProperties:
    def test_file_name_without_line(self):
        r = AuditReport(task="", file_path="foo.py", severity="bug",
                        bug_description="", expected="", actual="")
        assert r.file_name == "foo.py"
        assert r.line_number is None

    def test_file_name_with_line(self):
        r = AuditReport(task="", file_path="foo.py:42", severity="bug",
                        bug_description="", expected="", actual="")
        assert r.file_name == "foo.py"
        assert r.line_number == 42

    def test_file_name_with_colon_in_path(self):
        """Windows-style path or unusual filename."""
        r = AuditReport(task="", file_path="path/to/foo:bar.py", severity="bug",
                        bug_description="", expected="", actual="")
        # "foo:bar.py" → rsplit(":", 1) → ["path/to/foo", "bar.py"]
        # "bar.py" is not a digit → line_number is None
        assert r.file_name == "path/to/foo:bar.py"
        assert r.line_number is None


class TestBugJournalEntry:
    def test_full_entry(self):
        r = AuditReport(
            task="Fix watcher",
            file_path="watcher.py:15",
            severity="bug",
            bug_description="Used is not None on MagicMock",
            expected="Only real events detected",
            actual="All events treated as moved",
            root_cause="MagicMock is always truthy",
            fix="Use isinstance check",
            pattern="mock-truthiness",
        )
        entry = r.to_bug_journal_entry(4, "2026-05-18")
        assert "## Bug #4 — 2026-05-18 — watcher.py" in entry
        assert "**Task:** Fix watcher" in entry
        assert "**Pattern:** mock-truthiness" in entry
        assert "---" in entry

    def test_minimal_entry(self):
        r = AuditReport(
            task="Some task",
            file_path="file.py",
            severity="issue",
            bug_description="something wrong",
            expected="correct",
            actual="incorrect",
        )
        entry = r.to_bug_journal_entry(1, "2026-05-18")
        assert "## Bug #1" in entry
        assert "**Pattern:**" not in entry


class TestReviewLogEntry:
    def test_to_dict(self):
        r = AuditReport(
            task="Task 7",
            file_path="install.sh:57",
            severity="bug",
            bug_description="sed overmatch",
            expected="correct path",
            actual="double-nested path",
            pattern="sed-overmatch",
        )
        entry = r.to_review_log_entry("Qaster", "/home/q/projects/crabwatch")
        assert entry["reviewer"] == "Qaster"
        assert entry["project_path"] == "/home/q/projects/crabwatch"
        assert entry["severity"] == "bug"
        assert entry["pattern"] == "sed-overmatch"
        assert "timestamp" in entry
```

### 7.2 Unit Tests — `tests/test_review_log.py` (new file)

```python
import json
import os
import pytest
from utils.review_log import (
    append_review_entry, read_review_log, get_review_log_path,
    get_last_dream_timestamp,
)


class TestReviewLog:
    def test_append_and_read(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        entry = {"severity": "bug", "file": "test.py", "message": "broken"}

        append_review_entry(str(project), entry)

        log_path = get_review_log_path(str(project))
        assert os.path.isfile(log_path)

        entries = read_review_log(str(project))
        assert len(entries) == 1
        assert entries[0]["severity"] == "bug"

    def test_append_creates_crabcakes_dir(self, tmp_path):
        project = tmp_path / "newproject"
        project.mkdir()
        # .crabcakes/ doesn't exist yet
        append_review_entry(str(project), {"test": True})
        assert os.path.isdir(os.path.join(str(project), ".crabcakes"))

    def test_multiple_entries(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        for i in range(5):
            append_review_entry(str(project), {"index": i})

        entries = read_review_log(str(project))
        assert len(entries) == 5
        assert entries[0]["index"] == 0
        assert entries[4]["index"] == 4

    def test_read_nonexistent(self, tmp_path):
        entries = read_review_log(str(tmp_path))
        assert entries == []

    def test_read_with_since_filter(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        append_review_entry(str(project), {
            "timestamp": "2026-05-18T20:00:00Z", "id": 1
        })
        append_review_entry(str(project), {
            "timestamp": "2026-05-18T21:00:00Z", "id": 2
        })
        append_review_entry(str(project), {
            "timestamp": "2026-05-18T22:00:00Z", "id": 3
        })

        entries = read_review_log(str(project), since="2026-05-18T21:00:00Z")
        assert len(entries) == 1
        assert entries[0]["id"] == 3

    def test_malformed_line_skipped(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        log_path = get_review_log_path(str(project))
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            f.write('{"valid": true}\n')
            f.write('not json\n')
            f.write('{"also_valid": true}\n')

        entries = read_review_log(str(project))
        assert len(entries) == 2

    def test_get_last_dream_timestamp_none(self, tmp_path):
        assert get_last_dream_timestamp(str(tmp_path)) is None

    def test_get_last_dream_timestamp(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        dream_log = crab / "dream-log.jsonl"
        dream_log.write_text(
            '{"timestamp": "2026-05-18T02:00:00Z", "status": "completed"}\n'
            '{"timestamp": "2026-05-19T02:00:00Z", "status": "completed"}\n'
        )
        ts = get_last_dream_timestamp(str(tmp_path))
        assert ts == "2026-05-19T02:00:00Z"
```

### 7.3 Integration Tests — `tests/test_agent_command_handler.py` (extend existing)

Add tests for the audit report processing in the context of the full command flow:

```python
class TestAuditReportProcessing:
    def test_audit_report_logged_to_review_log(self, tmp_path):
        """Structured audit report in agent message is logged to review-log.jsonl."""
        handler = AgentCommandHandler()
        handler.set_project_path_provider(lambda: str(tmp_path))

        text = """## Audit Report
**Task:** Test task
**File:** test.py:10
**Severity:** bug
**Bug:** off by one error
**Expected:** correct index
**Actual:** wrong index
**Pattern:** off-by-one"""

        handler.on_agent_response("session:qaster:123", text, "test-project")

        # Check review log was created
        from utils.review_log import read_review_log
        entries = read_review_log(str(tmp_path))
        assert len(entries) == 1
        assert entries[0]["bug"] == "off by one error"

    def test_bug_severity_appended_to_journal(self, tmp_path):
        """Bug-severity report is auto-appended to {role}-bugs.md for the target agent."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()
        (crab_dir / "coder-bugs.md").write_text(
            "# Coder Bug Journal\n\n---\n\n## Bug #1 — 2026-05-17 — old.py\n\n**Task:** old\n"
        )

        handler = AgentCommandHandler()
        handler.set_project_path_provider(lambda: str(tmp_path))
        # Set up agent defs loader that returns a coder with structured_feedback: true
        handler.set_agent_defs_loader(lambda: [
            {"name": "Coder", "role": "coder",
             "self_improvement": {"structured_feedback": True}}
        ])

        text = """## Audit Report
**Task:** New task
**File:** new.py:20
**Severity:** bug
**Bug:** new mistake
**Expected:** correct
**Actual:** wrong
**Pattern:** test-pattern"""

        handler.on_agent_response("session:qaster:123", text, "test-project")

        # Bug journal should now have Bug #2
        journal = (crab_dir / "coder-bugs.md").read_text()
        assert "## Bug #2" in journal
        assert "new.py" in journal

    def test_suggestion_severity_not_appended_to_journal(self, tmp_path):
        """Suggestion-severity report is logged but NOT added to bug journal."""
        crab_dir = tmp_path / ".crabcakes"
        crab_dir.mkdir()

        handler = AgentCommandHandler()
        handler.set_project_path_provider(lambda: str(tmp_path))
        handler.set_agent_defs_loader(lambda: [
            {"name": "Coder", "role": "coder",
             "self_improvement": {"structured_feedback": True}}
        ])

        text = """## Audit Report
**Task:** Task
**File:** file.py
**Severity:** suggestion
**Bug:** could be improved"""

        handler.on_agent_response("session:qaster:123", text, "test-project")

        # Review log should have entry
        from utils.review_log import read_review_log
        entries = read_review_log(str(tmp_path))
        assert len(entries) == 1

        # Bug journal should NOT exist (no bug-severity reports)
        assert not (crab_dir / "coder-bugs.md").exists()

    def test_no_project_path_skips_logging(self):
        """No project path provider → reports detected but not logged."""
        handler = AgentCommandHandler()
        # No project path provider set

        text = """## Audit Report
**Task:** Task
**File:** file.py
**Severity:** bug
**Bug:** something wrong"""

        # Should not crash
        handler.on_agent_response("session:qaster:123", text, None)
```

---

## 8. Acceptance Criteria

- [ ] `utils/audit_parser.py` created with `extract_audit_reports()` and `AuditReport` dataclass
- [ ] `utils/review_log.py` created with `append_review_entry()`, `read_review_log()`, `get_last_dream_timestamp()`
- [ ] `utils/feedback_processor.py` created with `process_audit_reports()`, `append_to_bug_journal()`, `resolve_role_from_session()`, `resolve_default_target_role()`, `get_target_si_config()`
- [ ] `agent_command_handler.py` imports audit_parser and feedback_processor
- [ ] `agent_command_handler.py` has `set_project_path_provider()` and `set_agent_defs_loader()` setters
- [ ] `_resolve_target_role()` in handler delegates to `feedback_processor.resolve_role_from_session()` and `feedback_processor.resolve_default_target_role()`
- [ ] `_process_audit_reports()` in handler delegates to `feedback_processor.process_audit_reports()`
- [ ] Handler contains NO direct file I/O — all journal/log writes go through `utils/feedback_processor.py`
- [ ] Audit reports are logged to `.crabcakes/review-log.jsonl`
- [ ] Bug-severity reports are auto-appended to `.crabcakes/{role}-bugs.md` for the target agent
- [ ] Non-bug-severity reports are logged but NOT added to bug journal
- [ ] Malformed reports are silently skipped (no crash)
- [ ] Missing project path is handled gracefully (logged, not crashed)
- [ ] `window.py` wires the project path provider
- [ ] All tests in `test_audit_parser.py` pass
- [ ] All tests in `test_review_log.py` pass
- [ ] Existing tests in `test_agent_command_handler.py` pass
- [ ] End-to-end: Qaster sends structured audit → review log updated → bug journal updated → Coder receives message
