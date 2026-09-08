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


class TestAuditLogCap:
    """Bug 3 (SPEC-AUDIT-CLEANUP-1): AuditLog._entries must be FIFO-capped at
    MAX_ENTRIES so a long session cannot grow memory unbounded. Oldest entries
    are dropped when the cap is exceeded."""

    def _record_n(self, log, n):
        for i in range(n):
            log.record("tool", {"i": i}, approved=True, user=f"u{i}")

    def test_cap_drops_oldest_beyond_max(self):
        from agent import audit as audit_mod
        from agent.audit import AuditLog
        log = AuditLog()
        self._record_n(log, audit_mod.MAX_ENTRIES + 500)
        entries = log.entries
        assert len(entries) == audit_mod.MAX_ENTRIES, (
            f"expected cap at MAX_ENTRIES={audit_mod.MAX_ENTRIES}, got {len(entries)}"
        )
        # Oldest 500 dropped — first surviving entry is the 501st recorded.
        assert entries[0].user == "u500"
        # Newest intact, timestamp order preserved oldest→newest.
        assert entries[-1].user == f"u{audit_mod.MAX_ENTRIES + 499}"
        timestamps = [e.timestamp for e in entries]
        assert timestamps == sorted(timestamps), "entries must stay in timestamp order"

    def test_cap_exact_no_drop(self):
        """Boundary: len == MAX_ENTRIES exactly → nothing dropped."""
        from agent import audit as audit_mod
        from agent.audit import AuditLog
        log = AuditLog()
        self._record_n(log, audit_mod.MAX_ENTRIES)
        assert len(log.entries) == audit_mod.MAX_ENTRIES
        assert log.entries[0].user == "u0"  # oldest kept at the exact boundary

    def test_cap_over_by_one_drops_exactly_one(self):
        """Boundary: MAX_ENTRIES + 1 → exactly one (the oldest) dropped."""
        from agent import audit as audit_mod
        from agent.audit import AuditLog
        log = AuditLog()
        self._record_n(log, audit_mod.MAX_ENTRIES + 1)
        assert len(log.entries) == audit_mod.MAX_ENTRIES
        assert log.entries[0].user == "u1"
        assert log.entries[-1].user == f"u{audit_mod.MAX_ENTRIES}"