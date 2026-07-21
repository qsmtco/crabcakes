"""Tests for agent/audit.py — AuditEntry and AuditLog."""

import json
import os
import threading

from agent.audit import AuditEntry, AuditLog


class TestAuditLog:
    def test_record_creates_entry_with_hashed_args(self):
        log = AuditLog()
        log.record("exec_command", {"cmd": "ls"}, approved=True, user="test")
        assert len(log.entries) == 1
        entry = log.entries[0]
        assert entry.tool_name == "exec_command"
        assert entry.approved is True
        assert entry.user == "test"
        assert len(entry.args_hash) == 16  # sha256 truncated to 16 chars

    def test_record_hashes_result(self):
        log = AuditLog()
        log.record("read_file", {"path": "x"}, approved=None, user="u", result="file content")
        assert log.entries[0].result_hash  # non-empty

    def test_record_empty_result_has_empty_hash(self):
        log = AuditLog()
        log.record("read_file", {"path": "x"}, approved=None, user="u", result="")
        assert log.entries[0].result_hash == ""

    def test_flush_writes_jsonl_and_clears(self, tmp_path):
        log = AuditLog()
        log.record("exec_command", {"cmd": "ls"}, approved=True, user="test", result="output")
        path = str(tmp_path / "audit.jsonl")
        written = log.flush_audit_log(path)
        assert written == path
        assert os.path.isfile(path)
        with open(path) as f:
            line = json.loads(f.readline())
            assert line["tool_name"] == "exec_command"
        # Entries cleared after flush
        assert len(log.entries) == 0

    def test_flush_empty_returns_none(self, tmp_path):
        log = AuditLog()
        path = str(tmp_path / "audit.jsonl")
        assert log.flush_audit_log(path) is None

    def test_entries_returns_copy(self):
        log = AuditLog()
        log.record("x", {}, approved=True, user="u")
        e1 = log.entries
        e2 = log.entries
        assert e1 is not e2  # different list objects
        assert e1 == e2      # same contents

    def test_concurrent_record_is_thread_safe(self):
        log = AuditLog()

        def worker():
            for i in range(100):
                log.record("tool", {"i": i}, approved=True, user="t")

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(log.entries) == 500  # no lost entries