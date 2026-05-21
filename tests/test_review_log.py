# tests/test_review_log.py
# Unit tests for utils/review_log.py — review history persistence.
#
# Spec reference: SPEC-3 §7.2

import json
import os
import pytest

from utils.review_log import (
    append_review_entry,
    read_review_log,
    get_review_log_path,
    get_dream_log_path,
    get_last_dream_timestamp,
    REVIEW_LOG_FILENAME,
    DREAM_LOG_FILENAME,
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

    def test_dream_log_returns_most_recent_completed(self, tmp_path):
        crab = tmp_path / ".crabcakes"
        crab.mkdir()
        dream_log = crab / "dream-log.jsonl"
        dream_log.write_text(
            '{"timestamp": "2026-05-17T02:00:00Z", "status": "started"}\n'
            '{"timestamp": "2026-05-18T02:00:00Z", "status": "completed"}\n'
            '{"timestamp": "2026-05-19T02:00:00Z", "status": "failed"}\n'
            '{"timestamp": "2026-05-20T02:00:00Z", "status": "completed"}\n'
        )
        ts = get_last_dream_timestamp(str(tmp_path))
        assert ts == "2026-05-20T02:00:00Z"

    def test_review_log_filename_constant(self):
        assert REVIEW_LOG_FILENAME == "review-log.jsonl"

    def test_dream_log_filename_constant(self):
        assert DREAM_LOG_FILENAME == "dream-log.jsonl"