# tests/test_audit_parser.py
# Unit tests for utils/audit_parser.py — structured audit report extraction.
#
# Spec reference: SPEC-3 §7.1

import pytest
from utils.audit_parser import (
    extract_audit_reports,
    AuditReport,
    _parse_report_section,
)


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
**Expected:** correct behavior
**Actual:** broken behavior

## Audit Report
**Task:** Task 7
**File:** install.sh:80
**Severity:** issue
**Bug:** missing mkdir
**Expected:** dir exists
**Actual:** dir missing

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
        """Report with only required fields.

        Note: Expected and Actual are spec-required — must be present.
        """
        text = """## Audit Report
**Task:** Task 7
**File:** install.sh
**Severity:** suggestion
**Bug:** could be improved
**Expected:** correct behavior
**Actual:** current behavior"""
        reports = extract_audit_reports(text)
        assert len(reports) == 1
        r = reports[0]
        assert r.root_cause is None
        assert r.fix is None
        assert r.pattern is None
        assert r.expected == "correct behavior"
        assert r.actual == "current behavior"

    def test_missing_expected_or_actual_skipped(self):
        """Missing Expected or Actual (now spec-required) → report is skipped."""
        for missing in ("Expected", "Actual"):
            fields = {
                "Task": "T",
                "File": "f.py",
                "Severity": "bug",
                "Bug": "x",
                "Expected": "foo",
                "Actual": "bar",
            }
            del fields[missing]
            text = "## Audit Report\n" + "\n".join(
                f"**{k}:** {v}" for k, v in fields.items()
            )
            reports = extract_audit_reports(text)
            assert len(reports) == 0, f"Should skip when {missing} missing"

    def test_report_with_special_characters(self):
        """Report with quotes, backslashes, etc. in field values."""
        lb = chr(10)
        # Use character codes to avoid quoting issues with backslashes and backticks
        text = (
            "## Audit Report" + lb +
            '**Task:** Task with "quotes"' + lb +
            "**File:** path/to/file.py:42" + lb +
            "**Severity:** bug" + lb +
            "**Bug:** regex `" + r"r" + '"\\n"` matched incorrectly' + lb +
            "**Expected:** match newline" + lb +
            "**Actual:** matches everything" + lb +
            "**Root cause:** wrong pattern"
        )
        reports = extract_audit_reports(text)
        assert len(reports) == 1
        assert '"quotes"' in reports[0].task

    def test_report_in_code_block_detected(self):
        """Audit report inside a fenced code block IS detected.

        NOTE: extract_audit_reports() is naive — it does NOT strip fenced
        blocks. The caller (on_agent_response) must strip fenced blocks first.
        This test documents the actual (not spec'd) behavior.
        """
        lb = chr(10)
        text = (chr(96) * 3 + lb +
                "## Audit Report" + lb +
                "**Task:** fake" + lb +
                "**File:** fake.py" + lb +
                "**Severity:** bug" + lb +
                "**Bug:** not real" + lb +
                "**Expected:** exp" + lb +
                "**Actual:** act" + lb +
                chr(96) * 3 + lb
        )
        reports = extract_audit_reports(text)
        assert len(reports) == 1  # Naive detection — caller must strip

    def test_report_in_code_block_not_detected_when_stripped(self):
        """When fenced blocks are stripped first, no report is found."""
        import re

        def _strip_fenced_blocks(text: str) -> str:
            # Use explicit character codes to avoid quoting issues with backticks
            tb = chr(96) * 3  # triple backtick
            pattern = tb + r"[\s\S]*?" + tb
            return re.sub(pattern, "", text)

        lb = chr(10)  # newline — defined outside so it can be reused below
        text = (chr(96) * 3 + lb +
                "## Audit Report" + lb +
                "**Task:** fake" + lb +
                "**File:** fake.py" + lb +
                "**Severity:** bug" + lb +
                "**Bug:** not real" + lb +
                chr(96) * 3 + lb
        )
        clean = _strip_fenced_blocks(text)
        reports = extract_audit_reports(clean)
        assert len(reports) == 0

    def test_missing_required_field_skipped(self):
        """Missing any required field (Task/File/Severity/Bug/Expected/Actual) → skipped."""
        base = {
            "Task": "T",
            "File": "f.py",
            "Severity": "bug",
            "Bug": "x",
            "Expected": "foo",
            "Actual": "bar",
        }
        for missing in ("Task", "File", "Severity", "Bug", "Expected", "Actual"):
            fields = dict(base)
            del fields[missing]
            text = "## Audit Report\n" + "\n".join(
                f"**{k}:** {v}" for k, v in fields.items()
            )
            reports = extract_audit_reports(text)
            assert len(reports) == 0, f"Should skip when {missing} missing"


class TestAuditReportProperties:
    def test_file_name_without_line(self):
        r = AuditReport(
            task="", file_path="foo.py", severity="bug",
            bug_description="", expected="", actual=""
        )
        assert r.file_name == "foo.py"
        assert r.line_number is None

    def test_file_name_with_line(self):
        r = AuditReport(
            task="", file_path="foo.py:42", severity="bug",
            bug_description="", expected="", actual=""
        )
        assert r.file_name == "foo.py"
        assert r.line_number == 42

    def test_file_name_with_colon_in_path(self):
        """Windows-style path or unusual filename with colon before line number."""
        r = AuditReport(
            task="", file_path="path/to/foo:bar.py", severity="bug",
            bug_description="", expected="", actual=""
        )
        # "foo:bar.py" → rsplit(":", 1) → ["path/to/foo", "bar.py"]
        # "bar.py" is not a digit → line_number is None
        assert r.file_name == "path/to/foo:bar.py"
        assert r.line_number is None

    def test_is_bug_true_for_bug_severity(self):
        r = AuditReport(
            task="", file_path="", severity="bug",
            bug_description="", expected="", actual=""
        )
        assert r.is_bug is True

    def test_is_bug_false_for_issue_and_suggestion(self):
        for sev in ("issue", "suggestion"):
            r = AuditReport(
                task="", file_path="", severity=sev,
                bug_description="", expected="", actual=""
            )
            assert r.is_bug is False


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