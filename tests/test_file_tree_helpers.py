"""Tests for pure helper functions in ui/views/file_tree.py.

These are pure functions (no GTK imports needed): format_size, format_mtime,
git_status_to_display. They can be tested without a GTK display/sandbox
environment, making them ideal for unit testing.
"""

import time
from datetime import datetime, timedelta

from ui.views.file_tree import format_size, format_mtime, git_status_to_display


# ── format_size ─────────────────────────────────────────────────────────


class TestFormatSize:
    def test_zero_bytes(self):
        assert format_size(0) == "—"

    def test_negative_bytes(self):
        assert format_size(-1) == "—"

    def test_single_byte(self):
        assert format_size(1) == "1 B"

    def test_bytes_no_fraction(self):
        assert format_size(512) == "512 B"

    def test_kilobyte_boundary(self):
        assert format_size(1024) == "1 KB"

    def test_kilobyte_fractional(self):
        assert format_size(1500) == "1.5 KB"

    def test_megabyte_exact(self):
        assert format_size(1048576) == "1 MB"

    def test_megabyte_fractional(self):
        assert format_size(1572864) == "1.5 MB"

    def test_gigabyte(self):
        # 2 GB
        val = 2 * 1024 * 1024 * 1024
        assert format_size(val) == "2 GB"

    def test_large_values_no_exception(self):
        """Large values should not crash."""
        val = 10 * 1024 ** 4  # 10 TB
        result = format_size(val)
        assert "TB" in result or "PB" in result
        assert result != ""


# ── format_mtime ────────────────────────────────────────────────────────


class TestFormatMtime:
    def test_zero_mtime(self):
        """Zero mtime returns em-dash."""
        assert format_mtime(0) == "—"

    def test_negative_mtime(self):
        """Negative mtime returns em-dash."""
        assert format_mtime(-1) == "—"

    def test_just_now(self):
        """Less than 60 seconds ago shows 'just now'."""
        now_ns = int(time.time() * 1_000_000_000)
        assert format_mtime(now_ns) == "just now"

    def test_minutes_ago(self):
        """Between 1 and 59 minutes ago shows 'Xm ago'."""
        past = int((time.time() - 5 * 60) * 1_000_000_000)
        assert format_mtime(past) == "5m ago"

    def test_hours_ago(self):
        """Between 1 and 23 hours ago shows 'Xh ago'."""
        past = int((time.time() - 3 * 3600) * 1_000_000_000)
        assert format_mtime(past) == "3h ago"

    def test_yesterday(self):
        """24-47 hours ago shows 'yesterday'."""
        past = int((time.time() - 25 * 3600) * 1_000_000_000)
        assert format_mtime(past) == "yesterday"

    def test_days_ago(self):
        """2-6 days ago shows 'Xd ago'."""
        past = int((time.time() - 3 * 86400) * 1_000_000_000)
        assert format_mtime(past) == "3d ago"

    def test_weeks_ago(self):
        """7-29 days ago shows 'Xw ago'."""
        past = int((time.time() - 14 * 86400) * 1_000_000_000)
        assert format_mtime(past) == "2w ago"

    def test_older_than_month(self):
        """30+ days ago returns a formatted date (month + day)."""
        past = int((time.time() - 60 * 86400) * 1_000_000_000)
        result = format_mtime(past)
        # Should NOT contain "ago", should contain a month abbreviation
        assert "ago" not in result

    def test_future_timestamp_shows_date(self):
        """Future timestamp (positive diff) returns a formatted date, not negative string."""
        tomorrow = int((time.time() + 86400) * 1_000_000_000)
        result = format_mtime(tomorrow)
        assert "ago" not in result, f"future still shows 'ago': {result}"
        # Should look like "Jul 25" or similar — contains a month abbreviation
        import calendar
        assert any(month in result for month in calendar.month_abbr if month)

    def test_far_future_shows_date(self):
        """A far-future timestamp shows an absolute date, not a relative string."""
        future = int(4102444800 * 10 ** 9)  # Jan 1, 2100
        result = format_mtime(future)
        assert "ago" not in result
        # Should contain a month abbreviation
        import calendar
        assert any(month in result for month in calendar.month_abbr if month)


# ── git_status_to_display ───────────────────────────────────────────────


class TestGitStatusToDisplay:
    def test_modified_index(self):
        """Index modified 'M ' returns 'M'."""
        assert git_status_to_display("M ") == "M"

    def test_modified_worktree(self):
        """Worktree modified ' M' returns 'M'."""
        assert git_status_to_display(" M") == "M"

    def test_untracked(self):
        """Untracked '??' returns '?'."""
        assert git_status_to_display("??") == "?"

    def test_deleted_worktree(self):
        """Worktree deleted ' D' returns 'D'."""
        assert git_status_to_display(" D") == "D"

    def test_empty_string(self):
        """Empty string returns ''."""
        assert git_status_to_display("") == ""

    def test_ignored(self):
        """Ignored '!!' returns '!'."""
        assert git_status_to_display("!!") == "!"

    def test_added(self):
        """Added 'A ' returns 'A'."""
        assert git_status_to_display("A ") == "A"

    def test_rename(self):
        """Renamed 'R ' returns 'R'."""
        assert git_status_to_display("R ") == "R"

    def test_copy(self):
        """Copied 'C ' returns 'C'."""
        assert git_status_to_display("C ") == "C"

    def test_rename_worktree(self):
        """Worktree rename ' R' returns 'R'."""
        assert git_status_to_display(" R") == "R"

    def test_malformed_short_string(self):
        """A single-char string returns empty string."""
        assert git_status_to_display("M") == ""
