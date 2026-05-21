# utils/audit_parser.py
# Structured audit report extraction from agent messages.
#
# Parses ## Audit Report sections with **Field: Value** lines into
# typed AuditReport dataclass instances.
#
# Architecture: pure utility — no GTK, no network, no agent runtime.

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class AuditReport:
    """Parsed structured audit report from an agent message."""

    task: str
    file_path: str
    severity: str  # "bug" | "issue" | "suggestion"
    bug_description: str
    expected: str
    actual: str
    root_cause: str | None = None
    fix: str | None = None
    pattern: str | None = None
    tests: str | None = None
    raw_text: str = ""

    @property
    def file_name(self) -> str:
        """File path without line number."""
        if self.line_number is None:
            return self.file_path
        return self.file_path.rsplit(":", 1)[0]

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

    def to_review_log_entry(
        self, reviewer: str, project_path: str, target_role: str = "unknown"
    ) -> dict:
        """Convert to JSONL-compatible dict for review-log."""
        import datetime

        return {
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
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


# Key pattern: **Key:** value — colon is inside bold, before closing **
# Fix: change spec's broken r"^\*\*(.+?)\*\*:\s*(.+)$" to capture key before :
_FIELD_RE = re.compile(r"^\*\*(.+?):\*\*(.+)$")


def _parse_report_section(lines: list[str]) -> AuditReport | None:
    """Parse a single audit report section from collected lines.

    Returns None if required fields are missing or severity is invalid.
    """
    fields: dict[str, str] = {}

    for line in lines:
        match = _FIELD_RE.match(line.strip())
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            fields[key] = value

    # Required fields — all six spec-required fields
    required = ["Task", "File", "Severity", "Bug", "Expected", "Actual"]
    for req in required:
        if req not in fields:
            return None

    # Validate severity
    if fields["Severity"] not in ("bug", "issue", "suggestion"):
        return None

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
        raw_text="\n".join(lines),
    )


def extract_audit_reports(text: str) -> list[AuditReport]:
    """Extract all structured audit reports from message text.

    Scans for '## Audit Report' sections and parses **Field: Value** lines.

    NOTE: This function does NOT strip fenced code blocks. If audit reports
    appear inside ```...``` blocks they WILL be detected. Callers must strip
    fenced blocks first using a separate function if fenced-block content
    should be excluded.
    """
    reports: list[AuditReport] = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if line == "## Audit Report":
            # Collect lines until next heading or end
            report_lines: list[str] = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                stripped = next_line.strip()

                # Stop at next ## heading (any ## header)
                if stripped.startswith("## ") and stripped != "## Audit Report":
                    break

                # Stop at blank line followed by non-field content
                if not stripped:
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