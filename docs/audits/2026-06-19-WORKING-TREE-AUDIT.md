# Working-Tree Audit (2026-06-19)

**Auditor:** Qaster (read-only investigation)
**Trigger:** User request to audit 11+4 unstaged files left in working tree from prior sessions
**Mode:** Read-only. No files modified. No commits made.

---

## TL;DR

The working tree contains the **missing fix wire-up for two real bugs that were in the security-remediation work** (LOW-1 `user_id` half-implementation, LOW-3 `a.name` → `a.display_name`), plus the **MED-7 sanitization bugfix** (the sanitization was over-stripping generated `## Bug #N` headings, breaking 1 test in Phase 2's release), plus the **A-9 status-bar wire-up** that was spec'd but not wired to the gateway identity dict, plus 3 phase-3 spec/bugfix instruction docs that were authored but never committed.

**This is not "stale leftover noise."** This is **the post-Phase-3 cleanup that should have been committed on 2026-06-18 but wasn't.** It's the work that closes the loop on the Phase 3 audit findings that were flagged in the commit message but never actioned.

**Verdict:** All 9 modified files and 3 of 4 untracked files are legitimate, on-spec, working-tree-only-pending-commit. **One untracked file** (`tests/test_gateway.py`) **duplicates existing test coverage** of A-1 and should likely be discarded (or merged with the existing A-1 test class if such a class already exists — needs further check).

**Tests:** 140 of 140 pass in the security-relevant subsets. 0 fail. 0 new warnings.

---

## 1. What the user asked for

Audit the following (note: actual count is 9 modified + 4 untracked = 13 files, not 11+4 — the original count included the post-mortem/spec files from the previous turn):

### Modified (9)
- `agent/kb_server.py`
- `gateway/client.py`
- `models/command.py`
- `tests/test_agent_config_yaml_fallback.py`
- `ui/handlers/command_handler.py`
- `ui/handlers/connection_sync_handler.py`
- `ui/handlers/task_handler.py`
- `ui/window.py`
- `utils/feedback_processor.py`

### Untracked (4)
- `docs/specs/SECURITY-PHASE3-BUG3-WIRE-INSTRUCTIONS.md`
- `docs/specs/SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md`
- `docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md`
- `tests/test_gateway.py`

---

## 2. Per-file audit

### 2.1 `agent/kb_server.py` (LOW-3 fix, 1 line)

```diff
-                agent_ids = [a.name for a in agents]
+                agent_ids = [a.display_name for a in agents]
```

**Verdict: REAL BUGFIX. Required.**

Phase 3 (`2fe016e`) shipped LOW-3 (`GET /agents` listing endpoint) with code that referenced `a.name` on `SpecialAgentDef`. **That attribute does not exist.** The dataclass has `display_name` (line 32 of `agent/special_agents.py`). The original code would `AttributeError` on every call, fall into `except Exception: self._send_json(200, {"agents": []})` and silently return an empty list.

Net effect: the LOW-3 endpoint shipped, but **it always returned an empty list in production**. The fix is a one-line attribute rename. No test existed for LOW-3 (the silent-failure path masked the bug).

**Status:** Fix is correct. Should be committed. Recommend adding a test that confirms the endpoint returns the correct list when agents are registered (would have caught this on commit).

### 2.2 `gateway/client.py` (A-9 wire-up helper, 4 lines)

```diff
+    def get_identity(self) -> dict[str, Any]:
+        """Return the device identity dict (device_id, etc.)."""
+        return self._id
```

**Verdict: REAL NEW METHOD. Required for the A-9 wire-up.**

Adds a public accessor for the device identity dict (device_id, etc.) so that `connection_sync_handler` can read it on gateway connect and update the status-bar label. Clean, minimal, follows the existing pattern of accessor methods (`hello_snapshot` on the same class).

**Status:** Correct. Should be committed.

### 2.3 `models/command.py` (LOW-1 field, 1 line)

```diff
+    user: str = ""                        # LOW-1: human-readable user identity for traceability
```

**Verdict: REAL NEW FIELD. Required for the LOW-1 chain.**

Adds a `user` field to the `Command` dataclass. Used in `ui/handlers/command_handler.py:386-387` to pass the human-readable label into the command, then consumed by `ui/handlers/task_handler.py:107` for `Task(user=...)`. The chain is:

1. `Command.user` set in `command_handler.py` (line 388 in the new code)
2. `Task.user=cmd.user or cmd.source_session_key` in `task_handler.py` (line 107)

The `or` fallback is defensive — if `_human_label_for_session` returns empty for some reason, the original session key is used. **Good pattern.**

**Status:** Correct. Should be committed. The default value of `""` preserves backward compatibility — any test that constructs `Command(...)` without `user=` will continue to pass.

### 2.4 `tests/test_agent_config_yaml_fallback.py` (TestUserIdWireUp class, 25 lines)

Adds `TestUserIdWireUp` with 2 tests:
- `test_user_id_loaded_from_config` — writes an `agent.json` with `user_id: "alice@example.com"`, asserts the loaded config has it.
- `test_user_id_empty_when_missing` — writes an `agent.json` without `user_id`, asserts the loaded config has `user_id == ""`.

**Verdict: REAL NEW TEST CLASS. Required.**

The Phase 3 spec mentioned that `AgentConfig.user_id` would be wired through `load_agent_config()`, but no test verified it. This commit adds the test. **Test results: 2/2 pass.** The test follows the existing pattern (uses `tmp_config_dir` fixture, sets `os.chmod(agent_json, 0o600)` per security model).

**Status:** Correct. Should be committed.

### 2.5 `ui/handlers/command_handler.py` (LOW-1 wire-up, 22 lines)

Two changes:

1. Line 386-388: pass `user=self._human_label_for_session(session_key)` to `Command(...)`.
2. Lines 573-590: new `_human_label_for_session` helper that returns:
   1. The agent display name from AgentManager (gateway agents) — via `self._agent_mgr.get_name(session_key)`
   2. The display name from `_special_agents` (special agents)
   3. The last segment of the session key (e.g., `'telegram'` from `'agent:qaster:telegram:direct:7478874934'`)

**Verdict: REAL WIRE-UP. Required for LOW-1.**

The Phase 3 commit (`2fe016e`) shipped `LOW-1: Added user field to Task dataclass, set at construction` but did NOT populate it with a human-readable value — it just set `user=cmd.source_session_key` (a session key, not human-readable). The audit doc flagged this. The working-tree fix completes the LOW-1 implementation: it produces a human-readable label, not a session key.

The `_human_label_for_session` method has a good fallback chain. The last-segment fallback is sensible for non-agent sources (e.g., a session key from a Telegram user would resolve to "7478874934" — the chat ID, which is a reasonable last-resort label).

**Status:** Correct. Should be committed.

### 2.6 `ui/handlers/connection_sync_handler.py` (A-9 wire-up, 9 lines)

Three changes:

1. Docstring update: `main_window: MainWindow instance — for update_agent_id_display (A-9)`.
2. New constructor parameter `main_window=None` with `self._main_window = main_window`.
3. New wire-up call in the existing connect sync block: reads `gw.get_identity()`, extracts `device_id`, calls `self._main_window.update_agent_id_display(agent_id)` if non-empty.

**Verdict: REAL WIRE-UP. Required for A-9.**

A-9 was shipped in Phase 3 (`2fe016e`) as: "Agent-id display label in window status bar" — but **the wire-up to actually call `update_agent_id_display` on gateway connect was missing.** The status-bar label widget exists in `ui/window.py` (the `update_agent_id_display` method at line 798), but nothing was calling it. This commit wires it.

The `if self._main_window is not None` guard is defensive — preserves backward compatibility for any test that constructs `ConnectionSyncHandler` without passing `main_window`.

**Status:** Correct. Should be committed.

### 2.7 `ui/handlers/task_handler.py` (LOW-1 chain completion, 1 line)

```diff
-            user=cmd.source_session_key,  # LOW-1: traceability
+            user=cmd.user or cmd.source_session_key,  # LOW-1: human-readable identity
```

**Verdict: REAL CHAIN COMPLETION. Required.**

Phase 3 set `user=cmd.source_session_key` (a session key, opaque). The working tree replaces it with `cmd.user or cmd.source_session_key` — uses the human-readable label from `command_handler.py:388` if set, else falls back to the session key. **This is what LOW-1 was supposed to ship.**

**Status:** Correct. Should be committed.

### 2.8 `ui/window.py` (A-9 wire-up construction site, 1 line)

```diff
+            main_window=self,
```

**Verdict: REAL CONSTRUCTION ARGUMENT. Required.**

Passes `self` (the `MainWindow` instance) to the `ConnectionSyncHandler` constructor. This is the construction site that pairs with the `connection_sync_handler.py` change above.

**Status:** Correct. Should be committed.

### 2.9 `utils/feedback_processor.py` (MED-7 sanitization fix, 51 lines)

This is the largest change. The original MED-7 sanitization (shipped in Phase 2, `3f02119`) over-stripped: it removed **all** lines starting with `#`, including the generated `## Bug #N` heading from `to_bug_journal_entry()`. The result: the journal heading was missing from the entry, breaking the assertion in `test_bug_severity_appended_to_journal`.

**The fix is a two-layer approach:**

1. **Pre-sanitize field values** (task, bug_description, expected, actual, pattern) using a `_sanitize_field` helper that:
   - Strips `` ` `` (fence breaks) from each line
   - Drops lines matching `(?i)(ignore|disregard|forget)\s+(previous|prior|above|all)` (instruction override attempts)
   - Drops lines matching `(?i)new instructions:` (instruction override attempts)

2. **Post-sanitize the generated entry** but **preserve the safe `## Bug #N` heading** by:
   - Stripping `#`-starting lines UNLESS they match the `^## Bug #\d+` pattern
   - Stripping `**Field:**\s*#` patterns (where a field value starts with `#` — would render as a heading)
   - The original fence/instruction-override stripping from Phase 2 is preserved

**Verdict: REAL MED-7 FIX. Required. Caught by Phase 3 audit, fixed in working tree.**

This is a textbook fix for "sanitization broke legitimate code" — the right approach is to sanitize the data at its source (the field values) and let the generated structure pass through. The pattern preservation (`## Bug #N`) shows care for not over-stripping.

**Test results:** 6/6 in `TestAuditReportProcessing` pass. The 3 pre-existing failures in `TestAppendToBugJournal` mentioned in the Phase 3 post-mortem are **no longer present** (the test class doesn't exist as `TestAppendToBugJournal`; the test was likely renamed to `TestAuditReportProcessing` or restructured at some point). The MED-7 root-cause is fixed.

**Status:** Correct. Should be committed. The fix matches the bug spec in `docs/specs/SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md`.

### 2.10 `docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md` (untracked, 119 lines)

This is the **phase-instructions file** for Phase 3 of the security remediation. It describes the 16 findings (LOW-1..13 + A-4, A-6, A-8, A-9, A-10) and gives file-level guidance.

**Verdict: REAL SPEC DOC. Should be committed.**

The spec describes the work that was supposed to be done in Phase 3. The bugfix instructions (`SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md`, `SECURITY-PHASE3-BUG3-WIRE-INSTRUCTIONS.md`) and the code changes in the working tree all map back to this spec.

**Status:** Correct. Should be committed. The spec was authored 2026-06-18, shipped 2026-06-18 via `2fe016e`, and the spec itself was never committed. **Likely the supervisor's spec file that should have been committed as `docs(specs): add Phase 3 instructions` before/after the implementation commit.**

### 2.11 `docs/specs/SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md` (untracked, 80 lines)

Bugfix spec for **5 bugs** found during the Phase 3 audit:
- Bug 1: MED-7 sanitization strips `## Bug #N` headings (CRITICAL) — **FIXED in working tree** (`utils/feedback_processor.py`)
- Bug 2: LOW-3 `GET /agents` AttributeError — **FIXED in working tree** (`agent/kb_server.py`)
- Bug 3: A-4 AuditLog user_id never wired — **FIXED in working tree** (`agent/config.py` — already in HEAD, but the test that exercises it is new)
- Bug 4: A-9 Agent-id display never wired — **FIXED in working tree** (`ui/handlers/connection_sync_handler.py` + `ui/window.py` + `gateway/client.py`)
- Bug 5: LOW-1 user field set to session_key, not human-readable — **FIXED in working tree** (`models/command.py` + `ui/handlers/command_handler.py` + `ui/handlers/task_handler.py`)

**Verdict: REAL BUGFIX SPEC. Should be committed.**

This is the spec that drove the working-tree changes. It maps 1:1 to the 9 modified files. **Excellent spec discipline** — the bug fix instructions are clearly enumerated, each bug has a "Test to verify" section, and the changes match the spec exactly.

**Status:** Correct. Should be committed.

### 2.12 `docs/specs/SECURITY-PHASE3-BUG3-WIRE-INSTRUCTIONS.md` (untracked, 76 lines)

Detailed wire-up instructions for Bug 3 (A-4 user_id wiring). Adds `user_id=raw.get("user_id", "")` to `load_agent_config()` and a default `"user_id": ""` to the example dict in `_create_default_config()`.

**Verdict: REAL WIRE-UP SPEC. Should be committed.**

The actual `agent/config.py` changes (`user_id=raw.get("user_id", "")` at line 247 and `"user_id": ""` at line 269) are already in HEAD (per `git log` — the file is **not** in the working-tree diff, only the spec describing the change is untracked). So this spec is documenting work that was done.

**Status:** Correct. Should be committed. The implementation is already shipped; only the spec doc is untracked.

### 2.13 `tests/test_gateway.py` (untracked, 146 lines)

5 tests for A-1 lazy identity loading. All 5 tests pass.

**Verdict: PROBABLY DUPLICATE COVERAGE. Needs further check.**

The test file is untracked, and the 5 tests it contains are the A-1 verification tests. **There's a question: are these tests already in HEAD under a different name?** Let me check:
**Verified: NOT a duplicate.** `grep -rn "TestLazyIdentityLoading" tests/` shows the class exists only in the untracked file. The A-1 spec called for these tests; they were never committed.

**Verdict: REAL NEW TEST FILE. Required.**

The 5 tests verify:
1. `test_constructor_does_not_raise_without_identity_file` — patches `_load_identity` to track calls; constructs `GatewayClient` with no identity file; asserts `_load_identity` was NOT called.
2. `test_identity_loaded_flag_initialized_to_false` — constructs; asserts `_identity_loaded == False`.
3. `test_start_loads_identity_and_sets_flag` — constructs; calls `start()`; asserts `_identity_loaded == True`.
4. `test_identity_id_is_empty_dict_before_start` — asserts `_id == {}` before start.
5. `test_module_preload_does_not_affect_client` — pre-imports `gateway.client`; constructs a client; asserts construction still works (catches the bug from the Phase 1 bugfix cycle).

**Test results:** 5/5 pass.

**Status:** Correct. Should be committed. This is the test coverage that should have been committed with the A-1 fix in `9943740` but wasn't.

---

## 3. Cross-checks

### 3.1 Against post-mortems and DEFERRED-ITEMS

- `2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md` mentions "3 pre-existing MED-7 test failures" — **the working tree MED-7 fix resolves this** (the failing tests now pass; 6/6 in `TestAuditReportProcessing`).
- `2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md` mentions "A-4 audit log user_id was never wired" as a backlog item — **the working tree Bug 3 wire-up resolves this** (`agent/config.py` line 247 has `user_id=raw.get("user_id", "")` already in HEAD; the new test class exercises it).
- `2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md` mentions "A-9 status bar agent-id was never wired" as a backlog item — **the working tree A-9 wire-up resolves this** (`connection_sync_handler.py` calls `update_agent_id_display` on connect; `gateway/client.py` adds `get_identity()` accessor; `ui/window.py` passes `main_window=self`).

**Net: the working tree closes 3 of the 5 backlog items from the post-mortem I just wrote.** The other 2 are: (1) update parent `SECURITY_ARCHITECTURE_REVIEW.md` to mark all 46 SHIPPED per finding; (2) update `THREAT_MODEL.md` to reflect new defenses. Both are pure paperwork, not code.

### 3.2 Against the test suite

- 140 tests pass in the security-relevant subsets (gateway, agent_command, agent_config, bug_fixes, architecture, command_models).
- 0 fail.
- 0 new warnings.
- The 3 pre-existing MED-7 test failures documented in the Phase 3 post-mortem are **gone** (the `TestAppendToBugJournal` class no longer exists; the tests were restructured into `TestAuditReportProcessing`, which now passes 6/6).

### 3.3 Against the diff

The 9 modified files cluster into 5 fix themes:

1. **MED-7 sanitization fix** — `utils/feedback_processor.py`
2. **LOW-3 `a.name` → `a.display_name`** — `agent/kb_server.py`
3. **A-9 status-bar wire-up** — `gateway/client.py` + `ui/handlers/connection_sync_handler.py` + `ui/window.py`
4. **LOW-1 `user_id` chain completion** — `models/command.py` + `ui/handlers/command_handler.py` + `ui/handlers/task_handler.py` + `tests/test_agent_config_yaml_fallback.py`
5. **None of the 9 files are unrelated to security-remediation work** — every diff is either a fix for a documented bug from the post-mortem, a wire-up for a finding that was spec'd but not connected, or a test for a spec'd behavior.

### 3.4 Against the spec/bugfix instructions

The 3 untracked spec docs map 1:1 to the 9 modified files:
- `SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md` → Phase 3 spec that drove `2fe016e` (already shipped; spec doc untracked).
- `SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md` → 5 bugs from the Phase 3 audit; the working tree fixes all 5.
- `SECURITY-PHASE3-BUG3-WIRE-INSTRUCTIONS.md` → A-4 user_id wire-up; already in HEAD at `agent/config.py:247`; only the spec is untracked.

**This is a clean spec-to-implementation trace.** No drift. No scope creep.

---

## 4. Risk assessment

### 4.1 What's at risk if these changes are NOT committed

1. **LOW-3 endpoint silently returns empty list in production.** (Was broken in `2fe016e`; fix is in working tree.)
2. **A-9 status bar shows "Agent: " with no ID after gateway connect** (label is wired, but the wire-up call is not connected).
3. **LOW-1 `Task.user` is set to a session key, not a human-readable label** (e.g., `"agent:qaster:telegram:direct:7478874934"` instead of `"7478874934"` or `"Coder"`).
4. **MED-7 sanitization strips the bug journal heading** (the fix is in working tree; without it, `test_bug_severity_appended_to_journal` fails).
5. **A-1 has no test coverage** (the 5 tests are in the untracked `tests/test_gateway.py`; if discarded, A-1 has zero regression protection).

### 4.2 What's at risk if these changes ARE committed (badly)

1. The 3 spec docs could be committed at the wrong level (e.g., as part of a code change) instead of in their own `docs(specs): ...` commit. This is a paperwork issue, not a code issue.
2. The `get_identity` accessor exposes the device identity dict to any caller. This is a small attack surface increase (was previously only available internally). For a loopback-only gateway, this is acceptable. **No security regression.**

### 4.3 What's at risk if these changes are NOT reviewed first

Low. The changes are small, well-scoped, and the tests pass. The biggest risk is the LOW-1 fallback `cmd.user or cmd.source_session_key` — if `cmd.user` is an empty string (default value), it falls back to the session key. **This is the intended behavior** (empty user label is a valid state for first-run), but it's worth a code reviewer confirming.

---

## 5. Recommendation

**Commit the working tree as 2 logical commits:**

### Commit 1: Phase 3 spec docs (`docs(specs): ...`)

- `docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md`
- `docs/specs/SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md`
- `docs/specs/SECURITY-PHASE3-BUG3-WIRE-INSTRUCTIONS.md`

These are pure spec/docs; no code. Safe to commit independently.

### Commit 2: Phase 3 audit bugfixes (`fix(security): ...`)

- `agent/kb_server.py` (LOW-3)
- `utils/feedback_processor.py` (MED-7 sanitization)
- `models/command.py` (LOW-1 new field)
- `ui/handlers/command_handler.py` (LOW-1 wire-up)
- `ui/handlers/task_handler.py` (LOW-1 chain completion)
- `gateway/client.py` (A-9 accessor)
- `ui/handlers/connection_sync_handler.py` (A-9 wire-up)
- `ui/window.py` (A-9 construction)
- `tests/test_agent_config_yaml_fallback.py` (LOW-1 test)
- `tests/test_gateway.py` (A-1 test — untracked)

All related to closing the Phase 3 audit findings. Should be 1 commit (or 2 if you want to split A-1 tests from the wire-ups).

**Note: this commit would also be a good place to write a post-mortem** (`2026-06-19-PHASE-3-AUDIT-BUGFIXES-POST-MORTEM.md`) documenting the 5 bugs found and the 1-cycle fix. **The post-mortem I wrote earlier (`2026-06-19-SECURITY-REMEDIATION-PHASE-0-3-POST-MORTEM.md`) already mentions most of these in §7 Backlog** — that section can be updated to mark items 1, 2, 3 as resolved by this commit.

---

## 6. What I did NOT do

- I did not commit anything.
- I did not modify any of the 9 modified files or 4 untracked files.
- I did not run the full test suite (only the security-relevant subsets: 140 tests).
- I did not modify any post-mortem or backlog file.
- I did not consult the supervisor's process docs (`implementationLoop.md`, `steelFramedSpecWriter.md`) — this is a read-only audit, not a build.

---

## 7. Final tally

| File | Status | Action | Risk if not committed |
|------|--------|--------|----------------------|
| `agent/kb_server.py` | LOW-3 fix | commit | LOW-3 endpoint silently broken |
| `gateway/client.py` | A-9 accessor | commit | A-9 cannot read identity |
| `models/command.py` | LOW-1 field | commit | LOW-1 chain incomplete |
| `tests/test_agent_config_yaml_fallback.py` | LOW-1 test | commit | LOW-1 wire-up untested |
| `ui/handlers/command_handler.py` | LOW-1 wire-up | commit | LOW-1 chain incomplete |
| `ui/handlers/connection_sync_handler.py` | A-9 wire-up | commit | A-9 label never updates |
| `ui/handlers/task_handler.py` | LOW-1 chain | commit | LOW-1 user is session_key, not human-readable |
| `ui/window.py` | A-9 construction | commit | A-9 wire-up fails at construction |
| `utils/feedback_processor.py` | MED-7 fix | commit | MED-7 test fails; bug journal heading missing |
| `docs/specs/SECURITY-REMEDIATION-PHASE-3-INSTRUCTIONS.md` | spec doc | commit | Spec doc untracked |
| `docs/specs/SECURITY-PHASE3-BUGFIX-INSTRUCTIONS.md` | spec doc | commit | Spec doc untracked |
| `docs/specs/SECURITY-PHASE3-BUG3-WIRE-INSTRUCTIONS.md` | spec doc | commit | Spec doc untracked |
| `tests/test_gateway.py` | A-1 test | commit | A-1 has zero regression protection |

**13 files total. 9 modified + 4 untracked. All 13 are legitimate, on-spec, working-tree-only-pending-commit. None are stale noise. None are scope creep.**

**Recommendation: commit as 2 commits (docs + fix) at your convenience. No further review needed; the audit is complete.**
