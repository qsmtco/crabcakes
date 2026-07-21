# SPEC: Runtime Modular Extraction — Phase 5 (AuditLog)

**Date:** 2026-07-20
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-runtime-modular-extraction.md` §3.5
**Depends on:** None (standalone extraction)
**Target branch:** main

> **Architecture compliance:** New module `agent/audit.py` lives in the `agent/` layer. Imports only stdlib (`hashlib`, `json`, `os`, `threading`, `time`) and `utils/config.py`. No UI deps, no gateway deps, no circular imports. The `AuditLog` class is currently module-internal in runtime.py (not in `__all__`); extraction promotes it to public in its own module.

---

## 1. Overview

### Problem statement

`AuditEntry` (dataclass-like, lines 86-99) and `AuditLog` (class, lines 101-164) live inside `agent/runtime.py` (~79 lines total). They are self-contained: they record tool executions with args hash, approval status, user identity, and result hash. They have zero dependency on `AgentRuntime` — they only use stdlib (`hashlib`, `json`, `os`, `threading`, `time`) and `utils.config.get_config_dir`. They are instantiated by `AgentRuntime.__init__` (line 745) and called from 3 sites in `_run_loop` (lines 1543, 1563, 1633).

Extracting them to `agent/audit.py` follows the proven ContextStrategy pattern and reduces runtime.py by ~79 lines.

### Solution summary

1. Create `agent/audit.py` with `AuditEntry` and `AuditLog` (verbatim move, no logic changes).
2. Update `agent/runtime.py` to import from `agent.audit` instead of defining inline.
3. Update `AgentRuntime.__init__` to use the imported `AuditLog`.
4. Verify tests that reference `runtime.AuditLog` / `runtime.AuditEntry` still work (via re-export or test update).

### Scope (in/out table)

| In scope | Out of scope |
|----------|-------------|
| `agent/audit.py` — NEW file with AuditEntry + AuditLog | `agent/runtime.py` `_run_loop` logic — no changes to how audit is used |
| `agent/runtime.py` — remove inline classes, add import | `agent/enforcement.py` — no changes |
| `tests/test_agent_audit.py` — NEW test file (if beneficial) | `utils/config.py` — no changes |

### Architecture principles that apply

- §2 layering: `agent/audit.py` imports only stdlib + `utils/`. ✓
- ContextStrategy pattern: Protocol/Default split not needed here (AuditLog is a concrete class, no pluggability required). Verbatim move. ✓

---

## 2. Discovery (Steel-Framed Rule 1)

```
DISCOVERY:
- Read agent/runtime.py lines 86-164: AuditEntry (14 lines, __slots__ class with
  7 fields: tool_name, args_hash, approved, user, timestamp, result_hash, exit_code)
  + AuditLog (64 lines: __init__ with _entries list + _lock, record() method that
  hashes args+result with sha256, flush_audit_log() that writes JSON lines to
  ~/.config/crabcakes/audit-log.jsonl, entries property).
- Read agent/runtime.py line 745: self._audit_log = AuditLog() in AgentRuntime.__init__.
- Read agent/runtime.py lines 1543, 1563, 1633: three self._audit_log.record(...)
  call sites in _run_loop. Signature: record(tool_name, args, approved, user, result, exit_code).
- Read agent/runtime.py line 1606: self._audit_log is also passed as audit_log=self._audit_log
  to ToolContext (the tool middleware context object). This is a 4th reference — not a method
  call but a parameter pass. After extraction, the imported AuditLog type is the same class,
  so this continues to work. No change needed at this site.
- Grep tests: tests/test_agent_runtime.py references AuditLog/AuditEntry? Verify with grep.
  No dedicated test file for audit currently exists.
- Imports needed in agent/audit.py: hashlib, json, os, threading, time (all stdlib),
  plus from utils.config import get_config_dir (lazy, inside flush_audit_log).
- Architecture owner: new module agent/audit.py owns the tool-audit trail.
```

---

## 3. Changes by File

### 3.1 `agent/audit.py` (NEW FILE)

Create this file with the verbatim content of `AuditEntry` + `AuditLog` from runtime.py lines 86-164. Add a module docstring and the necessary imports at the top.

```python
"""Tool execution audit trail.

Extracted from agent/runtime.py (Phase 5). Records tool name, args hash
(not raw args), approval decision, user identity, timestamp, and result
hash. In-memory by default; flushes to disk as JSON lines.

Pure Python — no GTK, no network, no agent.runtime imports.
"""

import hashlib
import json
import os
import threading
import time


class AuditEntry:
    """Single audit log entry for a tool execution."""
    __slots__ = ("tool_name", "args_hash", "approved", "user", "timestamp", "result_hash", "exit_code")

    def __init__(self, tool_name: str, args_hash: str, approved: bool | None,
                 user: str, timestamp: float, result_hash: str = "", exit_code: int | None = None):
        self.tool_name = tool_name
        self.args_hash = args_hash
        self.approved = approved
        self.user = user
        self.timestamp = timestamp
        self.result_hash = result_hash
        self.exit_code = exit_code


class AuditLog:
    """In-memory audit log for tool executions (A-4).

    Defense-in-depth: records tool name, args hash (not raw args),
    approval decision, user identity, timestamp, and result hash.
    In-memory by default; flush to disk via flush_audit_log().
    """

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._lock = threading.Lock()

    def record(self, tool_name: str, args: dict, approved: bool | None,
               user: str, result: str = "", exit_code: int | None = None) -> None:
        """Record a tool execution in the audit log."""
        args_hash = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]
        result_hash = hashlib.sha256(result.encode()).hexdigest()[:16] if result else ""
        entry = AuditEntry(
            tool_name=tool_name,
            args_hash=args_hash,
            approved=approved,
            user=user,
            timestamp=time.time(),
            result_hash=result_hash,
            exit_code=exit_code,
        )
        with self._lock:
            self._entries.append(entry)

    def flush_audit_log(self, path: str | None = None) -> str | None:
        """Flush audit log to disk as JSON lines.

        Args:
            path: Output file path. Defaults to ~/.config/crabcakes/audit-log.jsonl.

        Returns:
            The file path written, or None if no entries.
        """
        from utils.config import get_config_dir
        if path is None:
            path = os.path.join(get_config_dir(), "audit-log.jsonl")
        with self._lock:
            if not self._entries:
                return None
            entries = list(self._entries)
            self._entries.clear()
        with open(path, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps({
                    "tool_name": e.tool_name,
                    "args_hash": e.args_hash,
                    "approved": e.approved,
                    "user": e.user,
                    "timestamp": e.timestamp,
                    "result_hash": e.result_hash,
                    "exit_code": e.exit_code,
                }) + "\n")
        return path

    @property
    def entries(self) -> list[AuditEntry]:
        with self._lock:
            return list(self._entries)
```

### 3.2 `agent/runtime.py`

#### 3.2a: Add import

At the top of `agent/runtime.py`, in the import block (near the other `from agent.` imports), add:

```python
from agent.audit import AuditEntry, AuditLog
```

#### 3.2b: Remove inline class definitions

Delete the `AuditEntry` class (lines 86-99) and the `AuditLog` class (lines 101-164) from `agent/runtime.py`. These are now imported from `agent.audit`.

**The `self._audit_log = AuditLog()` call at line 745 stays unchanged** — it now refers to the imported `AuditLog`, which is the same class.

**The 3 `self._audit_log.record(...)` call sites (lines 1543, 1563, 1633) stay unchanged** — same method, same signature.

### 3.3 `tests/test_agent_audit.py` (NEW FILE — recommended)

Add a focused test file for the extracted module. Tests should cover:
- `AuditLog.record()` creates an entry with hashed args
- `AuditLog.record()` creates an entry with hashed result
- `AuditLog.flush_audit_log()` writes JSON lines and clears entries
- `AuditLog.flush_audit_log()` returns None when empty
- `AuditLog.entries` returns a copy (not the internal list)
- Thread safety (concurrent record calls don't corrupt)

Example test structure:
```python
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
```

### 3.4 `tests/test_agent_runtime.py` (if needed)

**First, check** whether existing tests reference `runtime.AuditLog` or `runtime.AuditEntry`:
```bash
grep -n "AuditLog\|AuditEntry" tests/test_agent_runtime.py
```

If they import from `agent.runtime`, they should still work via the import added in 3.2a (`from agent.audit import AuditEntry, AuditLog` makes both available as `runtime.AuditEntry` / `runtime.AuditLog`). If any test does `from agent.runtime import AuditLog`, it will still work because the import at the top of runtime.py brings the names into the module namespace.

### Files NOT changed

- `agent/enforcement.py` — no changes (doesn't use AuditLog)
- `agent/tools.py` — no changes
- `utils/config.py` — no changes

---

## 4. Data Flow

No data flow change. `AgentRuntime.__init__` still creates `self._audit_log = AuditLog()`. The `_run_loop` still calls `self._audit_log.record(...)` at the same 3 sites. The only change is where `AuditLog` and `AuditEntry` are defined (new file vs inline).

```
AgentRuntime.__init__()
  → from agent.audit import AuditLog  [NEW import path]
  → self._audit_log = AuditLog()      [unchanged]

_run_loop (3 call sites)
  → self._audit_log.record(tool_name, args, approved, user, result, exit_code)  [unchanged]
```

---

## 5. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `agent/audit.py` | NEW (verbatim move of AuditEntry + AuditLog) | +90 | Low |
| `agent/runtime.py` | Edit (remove ~79 lines, add 1 import line) | -78 net | Low |
| `tests/test_agent_audit.py` | NEW (7 tests) | +70 | Low |

---

## 6. Acceptance Criteria

- [ ] `agent/audit.py` exists and contains `AuditEntry` and `AuditLog` classes
- [ ] `grep -c "class AuditEntry\|class AuditLog" agent/runtime.py` returns **0**
- [ ] `grep -c "from agent.audit import" agent/runtime.py` returns **1**
- [ ] `python3 -c "from agent.audit import AuditEntry, AuditLog; print('OK')"` succeeds
- [ ] `python3 -c "from agent.runtime import AgentRuntime; print('OK')"` succeeds (no import error)
- [ ] `python3 -m pytest tests/test_agent_audit.py -q` passes (7 new tests)
- [ ] `python3 -m pytest tests/test_agent_runtime.py -q -k "audit"` passes (if any audit tests exist)

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Test imports `runtime.AuditLog` | Still works (import at top of runtime.py brings name into namespace) |
| `flush_audit_log` called with no entries | Returns None (existing behavior, preserved) |
| Concurrent `record()` calls | Thread-safe via `_lock` (existing behavior, preserved) |
| `audit-log.jsonl` doesn't exist | Created by `open(path, "a")` (existing behavior, preserved) |

---

## 8. ARCHITECTURE.md Updates Required

- Add new entry for `agent/audit.py` in the agent/ module listing
- Update §3.21m (runtime.py): note AuditLog/AuditEntry extracted to `agent/audit.py`
