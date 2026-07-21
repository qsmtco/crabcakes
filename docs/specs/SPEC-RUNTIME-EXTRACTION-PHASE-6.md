# SPEC: Runtime Modular Extraction — Phase 6 (Conversation Persistence)

**Date:** 2026-07-20
**Author:** Supervisor
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-runtime-modular-extraction.md` §3.4
**Depends on:** None (standalone extraction)
**Target branch:** main

> **Architecture compliance:** New module `agent/persistence.py` lives in the `agent/` layer. Imports only stdlib (`json`, `os`, `re`) and `utils/config.py`, `utils/providers_store.py`, `models/conversation.py`, `models/team.py`. No UI deps, no gateway deps. The six module-level functions are stateless helpers currently in runtime.py; extraction follows the verbatim-move pattern.

---

## 1. Overview

### Problem statement

Six module-level functions in `agent/runtime.py` handle conversation disk I/O (~270 lines):

| Function | Lines | Purpose |
|----------|-------|---------|
| `_conversations_dir()` | 352-368 | Returns conversations directory (chmod 0700) |
| `_save_conversation_to_disk(conv, session_key)` | 370-425 | Serialize Conversation to JSON (chmod 0600, no api_key) |
| `_resolve_api_key_for_conversation(data)` | 427-460 | Re-resolve api_key from providers.yaml (HIGH-3) |
| `_load_conversation_from_disk(session_key)` | 462-550 | Deserialize Conversation from JSON |
| `_migrate_conversation_files()` | 553-604 | One-time migration (remove api_key from old files) |
| `_resolve_session_workspace(project_path, session_key)` | 606-650 | Per-session secure workspace (LOW-2, path validation) |

These functions have **zero dependency on `AgentRuntime`** — they're stateless module-level helpers. They're called from `AgentRuntime` methods (`save_conversation`, `load_conversation`, `create_conversation`, `_auto_save`, `_run_loop`). Extracting them to `agent/persistence.py` reduces runtime.py by ~270 lines and makes persistence testable without instantiating `AgentRuntime`.

### Solution summary

1. Create `agent/persistence.py` with all 6 functions (verbatim move, drop leading underscore from names since they're now public in their own module).
2. Update `agent/runtime.py` to import from `agent.persistence`.
3. Update all call sites in runtime.py to use the new names.
4. Verify tests that reference these functions (via runtime import or direct).

**Naming decision:** The functions lose their leading underscore when promoted to a public module. `_save_conversation_to_disk` → `save_conversation_to_disk`. This is a deliberate API promotion, consistent with the proposal §3.5 note ("a new top-level module's contents are importable").

### Scope (in/out table)

| In scope | Out of scope |
|----------|-------------|
| `agent/persistence.py` — NEW file with 6 functions | `AgentRuntime.save_conversation()` / `.load_conversation()` methods — stay on the class |
| `agent/runtime.py` — remove 6 functions, add imports, update call sites | `models/conversation.py` — no changes to Conversation/Message dataclasses |
| `tests/test_agent_persistence.py` — NEW test file | `utils/providers_store.py` — no changes |

### Architecture principles that apply

- §2 layering: `agent/persistence.py` imports stdlib + `utils/` + `models/`. No UI, no gateway. ✓
- HIGH-3: api_key never serialized; re-resolved from providers.yaml on load. Preserved. ✓
- LOW-2: session workspace validation (path escape prevention). Preserved. ✓
- ContextStrategy pattern: verbatim move, no behavior change. ✓

---

## 2. Discovery (Steel-Framed Rule 1)

```
DISCOVERY:
- Read agent/runtime.py lines 352-650: Six functions, all stateless module-level.
  _conversations_dir() uses utils.config.get_config_dir (lazy import inside function).
  _save_conversation_to_disk serializes Conversation to dict, writes JSON, chmod 0600.
  _resolve_api_key_for_conversation uses utils.providers_store.load_providers (lazy import).
  _load_conversation_from_disk uses models.conversation (Conversation, Message, MessageRole,
  ToolCall — all lazy imports inside function).
  _migrate_conversation_files has a module-level guard _CONVERSATION_MIGRATION_DONE (bool).
  _resolve_session_workspace uses re.fullmatch for session_key validation.
- Call sites in AgentRuntime:
  - _migrate_conversation_files() called at line 717 (in __init__ or startup)
  - _save_conversation_to_disk(conv, sk) at lines 812, 2070, 2082
  - _load_conversation_from_disk(session_key) at line 2087
  - _resolve_session_workspace(conv.project_path, session_key) at line 1586
  - _conversations_dir() at line 2185
- Grep tests: tests/test_conversation.py, tests/test_low2_file_sandbox.py reference these.
  MUST verify import paths.
- _CONVERSATION_MIGRATION_DONE is a module-level global in runtime.py — must move to
  persistence.py or become an attribute on a sentinel object.
- Architecture owner: new module agent/persistence.py owns conversation disk I/O.
```

---

## 3. Changes by File

### 3.1 `agent/persistence.py` (NEW FILE)

Create this file with the 6 functions moved verbatim from runtime.py. Drop the leading underscore from function names (they're public in their own module now). Move the `_CONVERSATION_MIGRATION_DONE` flag too.

```python
"""Conversation persistence — disk I/O for conversation state.

Extracted from agent/runtime.py (Phase 6). Stateless module-level helpers
for saving/loading conversations to ~/.config/crabcakes/conversations/.

Security:
  - HIGH-3: api_key is NEVER serialized. Re-resolved from providers.yaml on load.
  - LOW-2: session workspace validation prevents path escapes.
  - Conversation files are chmod 0600 after write.

Pure Python — no GTK, no network, no agent.runtime imports.
"""

import json
import os
import re

# ── Conversation persistence ──────────────────────────────────────────────────

def conversations_dir() -> str:
    # ... verbatim from runtime.py _conversations_dir, renamed ...


def save_conversation_to_disk(conv, session_key: str) -> str:
    # ... verbatim from runtime.py _save_conversation_to_disk, renamed ...


def resolve_api_key_for_conversation(data: dict) -> str | None:
    # ... verbatim from runtime.py _resolve_api_key_for_conversation, renamed ...


def load_conversation_from_disk(session_key: str):
    # ... verbatim from runtime.py _load_conversation_from_disk, renamed ...


# ── HIGH-3: One-time migration ──────────────────────────────────────────────────

_CONVERSATION_MIGRATION_DONE: bool = False


def migrate_conversation_files() -> int:
    # ... verbatim from runtime.py _migrate_conversation_files, renamed ...
    # NOTE: uses the module-level _CONVERSATION_MIGRATION_DONE flag above


# ── LOW-2: Per-session secure workspace ─────────────────────────────────────


def resolve_session_workspace(project_path: str | None, session_key: str) -> str:
    # ... verbatim from runtime.py _resolve_session_workspace, renamed ...
```

**Implementation note:** Each function body is copied VERBATIM from runtime.py. The only changes are:
1. Function name: drop leading underscore
2. Internal calls to sibling functions use the new names (e.g., `conversations_dir()` instead of `_conversations_dir()`)
3. The `global _CONVERSATION_MIGRATION_DONE` in `migrate_conversation_files` refers to the module-level flag in `persistence.py`

### 3.2 `agent/runtime.py`

#### 3.2a: Add imports

At the top of `agent/runtime.py`, in the import block, add:

```python
from agent.persistence import (
    conversations_dir,
    load_conversation_from_disk,
    migrate_conversation_files,
    resolve_api_key_for_conversation,
    resolve_session_workspace,
    save_conversation_to_disk,
)
```

#### 3.2b: Remove the 6 inline functions

Delete lines 352-650 from `agent/runtime.py` (the 6 functions + the `_CONVERSATION_MIGRATION_DONE` flag + section comments). These are now in `agent/persistence.py`.

#### 3.2c: Update call sites

Update all call sites in `agent/runtime.py` to use the new (non-underscored) names:

| Line | Old | New |
|------|-----|-----|
| 717 | `_migrate_conversation_files()` | `migrate_conversation_files()` |
| 812 | `_save_conversation_to_disk(conv, sk)` | `save_conversation_to_disk(conv, sk)` |
| 1586 | `_resolve_session_workspace(conv.project_path, session_key)` | `resolve_session_workspace(conv.project_path, session_key)` |
| 2070 | `_save_conversation_to_disk(conv, session_key)` | `save_conversation_to_disk(conv, session_key)` |
| 2082 | `_save_conversation_to_disk(conv, session_key)` | `save_conversation_to_disk(conv, session_key)` |
| 2087 | `_load_conversation_from_disk(session_key)` | `load_conversation_from_disk(session_key)` |
| 2185 | `_conversations_dir()` | `conversations_dir()` |

**Use grep to find ALL call sites before editing** — line numbers may have drifted:
```bash
grep -n "_save_conversation_to_disk\|_load_conversation_from_disk\|_conversations_dir\|_resolve_api_key_for_conversation\|_migrate_conversation_files\|_resolve_session_workspace" agent/runtime.py
```

Every match must be updated to the non-underscored name.

### 3.3 `tests/test_agent_persistence.py` (NEW FILE — recommended)

Add tests that exercise persistence without instantiating `AgentRuntime`:

```python
import json
import os
from agent.persistence import (
    conversations_dir,
    save_conversation_to_disk,
    load_conversation_from_disk,
    resolve_session_workspace,
    migrate_conversation_files,
)
from models.conversation import Conversation, Message, MessageRole


class TestConversationsDir:
    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        d = conversations_dir()
        assert os.path.isdir(d)


class TestSaveLoadRoundtrip:
    def test_save_and_load_preserves_messages(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        conv = Conversation(
            agent_name="Coder",
            model="openai/gpt-4o",
            system_prompt="You are Coder",
            messages=[Message(role=MessageRole.USER, content="hello")],
        )
        path = save_conversation_to_disk(conv, "special:coder")
        assert os.path.isfile(path)
        result = load_conversation_from_disk("special:coder")
        assert result is not None
        loaded_conv, _data = result
        assert loaded_conv.agent_name == "Coder"
        assert len(loaded_conv.messages) == 1
        assert loaded_conv.messages[0].content == "hello"

    def test_saved_file_does_not_contain_api_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        conv = Conversation(
            agent_name="Coder",
            model="openai/gpt-4o",
            system_prompt="",
            messages=[],
            api_key="sk-secret-12345",
        )
        path = save_conversation_to_disk(conv, "special:coder")
        with open(path) as f:
            data = json.load(f)
        assert "api_key" not in json.dumps(data)  # HIGH-3


class TestResolveSessionWorkspace:
    def test_valid_session_key(self, tmp_path):
        ws = resolve_session_workspace(str(tmp_path), "special:coder")
        assert os.path.isdir(ws)

    def test_empty_project_path_raises(self):
        import pytest
        with pytest.raises(ValueError, match="LOW-2"):
            resolve_session_workspace("", "special:coder")

    def test_path_escape_rejected(self, tmp_path):
        import pytest
        with pytest.raises(ValueError, match="LOW-2"):
            resolve_session_workspace(str(tmp_path), "../escape")

    def test_colon_sanitized(self, tmp_path):
        ws = resolve_session_workspace(str(tmp_path), "special:coder")
        assert "special-coder" in ws  # colon → hyphen


class TestMigrateConversationFiles:
    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr("utils.config.get_config_dir", lambda: str(tmp_path))
        # First call may migrate; second must be no-op
        migrate_conversation_files()
        assert migrate_conversation_files() == 0
```

### 3.4 Existing test files (REQUIRED — 2 files need updates)

Grep confirmed TWO test files reference the moved functions:

**File 1: `tests/test_low2_file_sandbox.py`** — 24 references to `_resolve_session_workspace`:
```bash
grep -c "_resolve_session_workspace" tests/test_low2_file_sandbox.py  # 24
```
Update the import to `from agent.persistence import resolve_session_workspace` (non-underscored) and update all 24 call sites.

**File 2: `tests/test_conversation.py`** — references to `_save_conversation_to_disk`, `_load_conversation_from_disk`, `_resolve_api_key_for_conversation`, `_conversations_dir`:
```bash
grep -n "_save_conversation_to_disk\|_load_conversation_from_disk\|_conversations_dir\|_resolve_api_key_for_conversation" tests/test_conversation.py
```
Update all imports to use `agent.persistence` with non-underscored names.

**IMPORTANT:** The grep regex in the verification section must include `_resolve_api_key_for_conversation` (5 references in test_conversation.py).

### Files NOT changed

- `models/conversation.py` — no changes
- `utils/config.py` — no changes
- `utils/providers_store.py` — no changes
- `agent/enforcement.py` — no changes

---

## 4. Data Flow

No data flow change. The same functions are called at the same sites with the same arguments. The only change is the import path and the function names (underscore dropped).

```
AgentRuntime.__init__()
  → migrate_conversation_files()  [was _migrate_conversation_files]

AgentRuntime.save_conversation(session_key)
  → save_conversation_to_disk(conv, session_key)  [was _save_conversation_to_disk]

AgentRuntime.load_conversation(session_key)
  → load_conversation_from_disk(session_key)  [was _load_conversation_from_disk]

AgentRuntime._run_loop (workspace setup)
  → resolve_session_workspace(conv.project_path, session_key)  [was _resolve_session_workspace]
```

---

## 5. File Change Summary

| File | Change type | Lines | Risk |
|------|-------------|-------|------|
| `agent/persistence.py` | NEW (verbatim move of 6 functions + migration flag) | +280 | Low-Medium |
| `agent/runtime.py` | Edit (remove ~280 lines, add import block, update 7 call sites) | -270 net | Medium |
| `tests/test_agent_persistence.py` | NEW (10 tests) | +100 | Low |

---

## 6. Acceptance Criteria

- [ ] `agent/persistence.py` exists and contains 6 public functions
- [ ] `grep -c "def _save_conversation_to_disk\|def _load_conversation_from_disk\|def _conversations_dir\|def _resolve_api_key_for_conversation\|def _migrate_conversation_files\|def _resolve_session_workspace" agent/runtime.py` returns **0**
- [ ] `grep -c "from agent.persistence import" agent/runtime.py` returns **1**
- [ ] `python3 -c "from agent.persistence import save_conversation_to_disk, load_conversation_from_disk, conversations_dir, resolve_session_workspace, migrate_conversation_files; print('OK')"` succeeds
- [ ] `python3 -c "from agent.runtime import AgentRuntime; print('OK')"` succeeds
- [ ] `python3 -m pytest tests/test_agent_persistence.py -q` passes
- [ ] `grep -rn "_save_conversation_to_disk\|_load_conversation_from_disk\|_conversations_dir\|_resolve_session_workspace\|_migrate_conversation_files" agent/runtime.py` returns **0** (all call sites updated)
- [ ] HIGH-3 preserved: saved conversation files do not contain api_key
- [ ] LOW-2 preserved: session workspace validates session_key

---

## 7. Edge Cases

| Case | Expected behavior |
|------|-------------------|
| Migration flag already set | `migrate_conversation_files()` returns 0 (idempotent) |
| Conversation file missing | `load_conversation_from_disk()` returns None |
| Corrupt JSON file | `load_conversation_from_disk()` returns None (catches JSONDecodeError) |
| Session key with path escape | `resolve_session_workspace()` raises ValueError |
| api_key in old conversation file | Migration removes it; load re-resolves from providers.yaml |
| providers.yaml has no matching provider | `resolve_api_key_for_conversation()` returns None |

---

## 8. ARCHITECTURE.md Updates Required

- Add new entry for `agent/persistence.py` in the agent/ module listing
- Update §3.21m (runtime.py): note persistence functions extracted to `agent/persistence.py`
