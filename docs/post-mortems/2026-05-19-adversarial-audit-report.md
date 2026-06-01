# Adversarial Audit Report — Self-Improvement Specs + User-Defined Local Agents

**Date:** 2026-05-19
**Auditor:** Qaster
**Status:** All findings addressed — fixes applied to spec documents

**Documents reviewed:**
1. `docs/proposals/PROPOSAL-user-defined-local-agents.md`
2. `docs/specs/SPEC-1-context-injection.md`
3. `docs/specs/SPEC-2-auto-test-enforcement.md`
4. `docs/specs/SPEC-3-structured-feedback.md`
5. `docs/specs/SPEC-4-dream-consolidation.md`
6. `docs/ARCHITECTURE.md` (existing reference)

---

## Category 1: Internal Consistency Issues

### 1.1 — SPEC-3: `to_bug_journal_entry()` double-writes `Fix` and `Root cause`

**Severity:** bug
**File:** SPEC-3, §3.1, `AuditReport.to_bug_journal_entry()`

The method has a logic error:

```python
if self.root_cause:
    lines.append(f"**Fix:** {self.root_cause}")     # ← writes root_cause as "Fix"
elif self.fix:
    lines.append(f"**Fix:** {self.fix}")
if self.fix and self.root_cause:                     # ← if BOTH exist
    lines.append(f"**Fix:** {self.fix}")             # ← writes fix as "Fix" AGAIN
```

**Problems:**
1. When both `root_cause` and `fix` exist, the `Fix` field is emitted **twice** — once with root_cause, once with fix.
2. When only `root_cause` exists, it's written as the `**Fix:**` field, but root_cause and fix are different things (root_cause = *why it happened*, fix = *what to do about it*).

**Fix:** The SPEC-1 bug journal format has distinct `**Fix:**` and `**Lesson:**` fields. The `to_bug_journal_entry()` method should map:
- `fix` → `**Fix:**`
- `root_cause` → `**Lesson:**` (or add a separate `**Root cause:**` field matching the Audit Report format)

---

### 1.2 — SPEC-3: Audit report field name mismatch with parser

**Severity:** bug
**Files:** SPEC-3 §2.2 vs §3.1

The field specification table (§2.2) defines `Root cause` (with a space) as the field name, and the regex parser (§3.1, `_parse_report_section`) parses it as:

```python
fields["Root cause"] = value   # ← stored with space
```

But `AuditReport` maps it as:
```python
root_cause=fields.get("Root cause"),
```

This is *internally consistent within SPEC-3* but it means the markdown written by agents must use `**Root cause:**` (with space), not `**RootCause:**` or `**root_cause:**`. This is fragile — the parser should document this constraint more prominently, or the field spec should use a simpler key like `RootCause` or `Cause`.

---

### 1.3 — SPEC-1 vs SPEC-3: Bug journal entry format mismatch

**Severity:** issue
**Files:** SPEC-1 §4.1 vs SPEC-3 §3.1 `to_bug_journal_entry()`

SPEC-1 defines the bug journal entry format with these fields:
```
**Task:** **Mistake:** **Expected:** **Actual:** **Fix:** **Lesson:** **Pattern:**
```

SPEC-3's `to_bug_journal_entry()` generates:
```
**Task:** **Mistake:** **Expected:** **Actual:** [Fix] [Lesson] [Pattern]
```

The `**Lesson:**` field in SPEC-3's method comes from `root_cause`, not from a dedicated lesson field. There's no `**Lesson:**` line when there's no `root_cause`. The mapping is:
- `root_cause` → `**Lesson:**` (partially, see issue 1.1)
- No explicit `**Fix:**` when only `root_cause` exists and it's written as Fix

This means auto-generated entries from SPEC-3 will have inconsistent field layouts compared to SPEC-1's template. The `**Lesson:**` field may be missing entirely, or `**Fix:**` may contain the wrong data.

---

### 1.4 — Proposal vs SPEC-4: `self_improvement` defaults don't fully align

**Severity:** issue
**Files:** Proposal §1a vs SPEC-4 §2.2

The Proposal says `dream_consolidation` defaults to `false`. SPEC-4 correctly checks `si.get("dream_consolidation", False)`. This is consistent.

However, the Proposal says `enforcement` defaults to `true (if agent has write tools)`. The default logic in the Proposal's `get_self_improvement_config()` uses `self.can_write` as the default — but the Python code in SPEC-1's `_get_agent_self_improvement_config()` hardcodes `"enforcement": True` as the default. This means for a read-only agent whose YAML doesn't specify `enforcement`, SPEC-1 would inject enforcement as enabled, while the Proposal says it should be disabled for read-only agents.

**Fix:** SPEC-1's defaults dict should match the Proposal — enforcement should default based on whether the agent has write tools, not hardcoded True.

---

### 1.5 — SPEC-4 references `prompts/system/{role}.md` but not all roles have one

**Severity:** issue
**File:** SPEC-4 §2.1, Phase 1

The dream engine reads `prompts/system/{role}.md` for "current pitfalls." Currently only `coder.md` and `debugger.md` exist. If a user creates a custom agent with `role: security-auditor`, the dream engine tries to read `prompts/system/security-auditor.md` which won't exist.

The code handles this gracefully (`_read_agent_pitfalls` returns "" via `_read_file_safe`), but the spec should document this as expected behavior for custom agents without dedicated prompt templates.

---

### 1.6 — SPEC-2 vs existing code: `_find_related_test()` signature change

**Severity:** issue
**Files:** SPEC-2 §3.2.4 vs existing `agent/enforcement.py` line 256

The existing `_find_related_test()` has signature:
```python
def _find_related_test(file_path: str, project_path: str) -> str | None:
```

SPEC-2 proposes changing it to:
```python
def _find_related_test(file_path, project_path, test_dir="tests", naming_pattern="test_{module}.py"):
```

This is backwards-compatible (new params have defaults). However, the existing function also checks `{basename}_test.py` convention, while the SPEC-2 version drops that candidate. The existing code checks 4 candidate paths, the new code only checks 3. This is a minor functionality regression.

---

### 1.7 — SPEC-4: Cron job `toolsAllow` uses OpenClaw tool IDs, not CrabCakes tool names

**Severity:** bug
**File:** SPEC-4 §4.1

The cron job config uses:
```json
"toolsAllow": ["read_file", "write_file", "edit_file", "exec_command"]
```

But this is an OpenClaw isolated agent session, which uses OpenClaw's tool system (exec, read, write, edit), NOT CrabCakes's tool names. The dream engine runs as a Python module inside CrabCakes, not as an OpenClaw agent. The cron job approach is fundamentally wrong for calling `utils.dream_engine.run_dream_cycle()` — that's a Python function call, not something an OpenClaw agent can invoke.

The `message` payload says:
```
"Run dream consolidation for project at {project_path}. Use: from utils.dream_engine import run_dream_cycle; ..."
```

An OpenClaw isolated agent has no access to `utils.dream_engine` — that's CrabCakes code. The cron job would need to either:
1. Run a Python script that imports dream_engine, OR
2. Be a completely different execution model (e.g., a timer within CrabCakes itself)

**Fix:** Either use `exec_command` to run a Python script, or use a different scheduling mechanism (GLib.timeout_add or a GLib-based timer within CrabCakes).

---

## Category 2: Architecture Alignment Issues

### 2.1 — SPEC-3 puts business logic in `ui/handlers/agent_command_handler.py`

**Severity:** architectural violation
**Files:** SPEC-3 §4.1, §4.1.4

SPEC-3 adds `_process_audit_reports()`, `_append_to_bug_journal()`, and `_resolve_target_role()` to `agent_command_handler.py`. The spec even acknowledges this in a comment:

> *"Architecture note: This method does direct file I/O from a handler, which is unusual. A future refactor should extract... into a `utils/feedback_processor.py` utility."*

Per ARCHITECTURE.md §8.6, handlers coordinate between models, gateway, and UI views. They should NOT contain file I/O logic for managing bug journals. The audit report parsing already lives in `utils/audit_parser.py` (correct), but the *processing* logic (writing to bug journals, resolving target roles) should be in a utility, not a handler.

**Recommendation:** Create `utils/feedback_processor.py` NOW (not as a future refactor) containing `_process_audit_reports()`, `_append_to_bug_journal()`, and role resolution logic. The handler should just call it.

---

### 2.2 — SPEC-1: `_get_agent_self_improvement_config()` imports from `utils.agent_defs` — circular risk

**Severity:** potential issue
**File:** SPEC-1 §4.3.2

The function does:
```python
from utils.agent_defs import load_agent_def_by_role
```

This is called from `utils/prompt_loader.py`, which is called from `agent/context.py` (the system prompt builder). If `agent_defs.py` ever needs to compose a system prompt (e.g., to validate agent definitions), you'd get a circular import. Currently safe, but fragile.

---

### 2.3 — Proposal: `utils/agent_defs.py` reads from `agent/tools.py` but spec says "does NOT import from `agent/`"

**Severity:** contradiction
**File:** Proposal §2

The proposal says:
> *"No circular imports. `utils/agent_defs.py` reads `agent.json` directly (like `agent/config.py` does) and scans `prompts/` directly (like `utils/prompts.py` does). It does NOT import from `agent/` or `ui/`."*

But `get_available_tools()` is defined as:
> *"Wrap `agent/tools.py get_all_tools()` → `[{name, description}]. Used by the UI to show tool checkboxes."*

This means `agent_defs.py` DOES import from `agent/tools.py`, contradicting the stated rule. Either:
1. `get_available_tools()` should be in a different module (e.g., `agent/config.py`), OR
2. The rule should be relaxed to allow imports from `agent/` for read-only utility access.

---

### 2.4 — Proposal: `ui/views/agent_builder.py` is a new view but isn't in ARCHITECTURE.md directory listing

**Severity:** documentation gap (noted as expected in the proposal's File Changes Summary)
**Files:** Proposal §4, ARCHITECTURE.md §2

The proposal correctly notes that `docs/ARCHITECTURE.md` should be updated as the last step. Just flagging that this is critical — the directory listing in ARCHITECTURE.md §2 must include all new files.

---

### 2.5 — SPEC-4: `utils/dream_engine.py` calls `agent/config.py` directly

**Severity:** architectural issue
**File:** SPEC-4 §3.2, `_call_llm()`

The dream engine imports `from agent.config import load_agent_config` to get provider settings for its LLM call. This makes `utils/` depend on `agent/`, which ARCHITECTURE.md doesn't explicitly forbid (the stated rules are `gateway/` and `models/` must not import from `ui/`), but it's a layering violation since `utils/` is documented as "Pure Python utilities — no GTK, no network."

The dream engine's `_call_llm()` also uses `urllib.request.urlopen` — that's network I/O from `utils/`, violating the "no network" rule.

**Fix:** Move `dream_engine.py` to `agent/dream_engine.py` (it depends on agent config and makes LLM calls), or extract the LLM call into a thin wrapper in `agent/`.

---

### 2.6 — SPEC-3: `agent_command_handler.py` gets 4 new setters — handler bloat

**Severity:** style issue (not a violation per se)
**File:** SPEC-3 §4.1.2

The handler already has 7 setters. SPEC-3 adds 2 more (`set_project_path_provider`, `set_agent_defs_loader`). That's 9 setters on one handler. Per ARCHITECTURE.md §8.6, handlers should "receive dependencies via constructor or setters" — but 9 is a code smell suggesting the handler is doing too much.

This isn't a blocking issue, but it's a sign that `AgentCommandHandler` is becoming a god handler. Consider splitting audit report processing into its own handler (`AuditHandler`).

---

## Category 3: Correctness Issues

### 3.1 — SPEC-2: `_check_tests()` references undefined `related_test` variable

**Severity:** bug
**File:** SPEC-2 §3.2.5

The rewritten `_check_tests()` function has two branches (custom command vs auto-detect), but both define `related_test` in their own scope. Then at the end:

```python
if related_test:
    detail = f"{related_test}: {'passed' if passed else 'FAILED'}"
else:
    detail = f"Full test suite: {'passed' if passed else 'FAILED'}"
```

If execution takes the `test_config.command` branch and hits the `else` at the bottom (`command = venv_prefix + test_config.full_suite_command or test_config.command`), `related_test` is defined in the outer scope but might be `None` if it was set in the first branch. Actually, looking more carefully, `related_test` is defined in both branches, but only the auto-detect branch has `related_test` in scope at the final reporting section. In the custom command branch, `related_test` is defined earlier but might not be if `test_config.run_full_suite` is True and `test_config.full_suite_command` is set — in that case, the first `if` condition enters the `run_full_suite` path and `related_test` is never assigned.

Wait, looking again: `related_test` IS assigned in both branches before the command construction. But in the `test_config.command` branch, the `run_full_suite` path skips the `related_test` assignment. Let me trace:

```python
if test_config.command:
    related_test = _find_related_test(...)    # ← assigned here
    if related_test is None and not test_config.run_full_suite:
        return None
    if test_config.run_full_suite and test_config.full_suite_command:
        command = ...                         # ← related_test is None here
    elif related_test:
        command = ...
    else:
        command = ...                         # ← related_test is None here too
```

OK, `related_test` IS assigned (possibly None) before the branches. The later reference `if related_test:` will correctly be falsy when None. This is actually fine — my initial concern was wrong. Withdrawing this finding.

**Update:** Not a bug. `related_test` is always assigned before use.

---

### 3.2 — SPEC-1: `compose_system_prompt()` insertion point may not match actual code

**Severity:** bug
**File:** SPEC-1 §4.3.3

The spec says the injection should go "After the `if agent_role == "coder":` / `elif agent_role == "debugger":` block (step 6), before the `if not parts:` check."

In the actual code (line ~137), step 6 is:
```python
if agent_role == "coder":
    ...
elif agent_role == "debugger":
    ...
```

And then:
```python
if not parts:
    ...
```

The spec's insertion point is correct. However, the spec's step numbering for the "ordering in the composed prompt" (§4.3.3) doesn't match the actual code. The spec lists:
1. default.md
2. collab.md
3. project-awareness.md
4. code-review.md
5. Agent-specific template
6. Bug journal ← new
7. Project rules ← new
8. File context

But the actual code has step 3b (crabcakes-commands.md) and step 4 (project-onboarding.md) which the spec doesn't mention. This is a documentation inconsistency but doesn't break anything since the spec's insertion point description is correct.

---

### 3.3 — SPEC-3: `_resolve_target_role()` default is hardcoded "coder"

**Severity:** issue
**File:** SPEC-3 §4.1.5

```python
def _resolve_target_role(self, reviewer_session_key: str) -> str:
    ...
    # No pending ask — try to infer from the reviewer's own project membership
    # Default to 'coder' as the most common review target
    return "coder"
```

If an agent sends an audit report without a pending ask context (e.g., an unsolicited code review), the target role defaults to "coder" regardless of who actually wrote the code. This means audit reports about a Debugger's work would be filed under `coder-bugs.md`.

The comment says "most common review target" but this assumption will break in multi-agent scenarios where any agent can write code.

---

### 3.4 — SPEC-4: `_prune_journal()` regex may match incorrectly

**Severity:** bug
**File:** SPEC-4 §3.2, `_prune_journal()`

```python
entries = list(re.finditer(r"(## Bug #(\d+).*?)(?=\n## Bug #|\Z)", content, re.DOTALL))
```

Then later:
```python
for bug_num in to_prune:
    remaining = re.sub(
        rf"\n*## Bug #{bug_num} .*?(?=\n## Bug #|\Z)",
        "",
        remaining,
        flags=re.DOTALL,
    )
```

The `.*?` in the regex with `re.DOTALL` could theoretically match across bug entries if the lookahead `(?=\n## Bug #|\Z)` fails on edge cases (e.g., extra newlines between entries). Also, the regex pattern in the substitution has a space after the bug number (`## Bug #{bug_num} `) but the original pattern doesn't require a space. If a journal entry is `## Bug #5—synthesized` (no space before dash), it would not be matched for removal but would be matched for counting.

Looking at SPEC-1's format: `## Bug #N — YYYY-MM-DD — [filename]` — there IS a space after the number. So the space in the removal regex is correct, but it's fragile.

---

### 3.5 — SPEC-4: `_call_llm()` has no retry logic

**Severity:** robustness issue
**File:** SPEC-4 §3.2, `_call_llm()`

The dream engine makes a single LLM call with a 120-second timeout. If the API call fails (network blip, rate limit, timeout), the entire dream cycle for that role fails. Given that this runs unattended at 2 AM, a transient failure means no dream analysis until the next night.

The spec acknowledges this is experimental, so a retry might be over-engineering. But at minimum, the spec should document this as a known limitation.

---

### 3.6 — SPEC-2: `enforcement` field in SPEC-1's `_get_agent_self_improvement_config()` serves two purposes

**Severity:** naming confusion
**Files:** SPEC-1 §4.3.2, SPEC-2 §3.5

SPEC-1's `_get_agent_self_improvement_config()` returns enforcement as part of the config dict. SPEC-2 uses this config to gate enforcement. But the enforcement flag is also used in `agent/runtime.py` (per SPEC-2 §3.5) to decide whether to call `enforcement.check()`.

There are two places checking the enforcement flag:
1. `runtime.py` — checks before calling enforcement.check()
2. `prompt_loader.py` — returns it as part of the self_improvement config (but doesn't use it for anything)

SPEC-1 includes `enforcement` in the defaults dict but never uses it for injection logic. It's just... there. Not harmful, but it's dead data in the context of SPEC-1.

---

### 3.7 — SPEC-4: The `since` filter in `read_review_log()` uses string comparison

**Severity:** bug (latent)
**Files:** SPEC-3 §3.2 (review_log.py), SPEC-4 §3.2

`read_review_log(since=timestamp)` filters with:
```python
if since and entry.get("timestamp", "") <= since:
    continue
```

This is a lexicographic string comparison on ISO timestamps. It works *if* all timestamps are in the same format (e.g., all UTC with same precision). But SPEC-3's `to_review_log_entry()` generates timestamps with `datetime.datetime.now(datetime.timezone.utc).isoformat()`, which produces `2026-05-19T02:00:00+00:00`, while SPEC-4's dream log uses `Z` suffix (`2026-05-19T02:00:00Z`).

Comparing `"2026-05-19T02:00:00+00:00" <= "2026-05-19T02:00:00Z"` — the `+` character (ASCII 43) is less than `Z` (ASCII 90), so `+00:00` timestamps sort before `Z` timestamps even if they represent the same instant. This would cause `read_review_log(since=...)` to either include or exclude entries incorrectly depending on the mix of timestamp formats.

**Fix:** Either normalize all timestamps to the same format, or parse them as `datetime` objects for comparison.

---

### 3.8 — SPEC-1: Template files use `{agent-name}` but code uses `{role}`

**Severity:** inconsistency
**File:** SPEC-1 §3.1 vs §4.1

The template files (`docs/templates/agent-bugs-template.md`) say:
> "These templates use `{agent-name}` and `{project-name}` placeholders..."

But the actual file format (§4.1) uses `{Agent Name}` in the header and `{role}` as the filename component. The `{agent-name}` placeholder in the template doesn't match any documented substitution mechanism. There's no code shown that replaces `{agent-name}` with anything.

---

## Category 4: Minor Issues / Nitpicks

### 4.1 — SPEC-3: Section numbering skips §5.4

The data flow section goes from §5.3 to §5.5, skipping §5.4.

### 4.2 — SPEC-4: `DreamResult` dataclass has `proposals: DreamProposals` field

This field contains complex nested data. If `DreamResult` is ever logged to JSONL (it is — via `_log_dream_cycle`), the `proposals` field is NOT included in the log entry. The log only includes scalar fields. This is fine, but it means the full proposals data is lost after a dream cycle unless the proposal files are retained.

### 4.3 — Proposal: YAML support requires `pyyaml` package

The proposal says "YAML is in the standard library (or use JSON as fallback)." Python does NOT have YAML in the standard library. `pyyaml` is a third-party package that must be installed. The fallback to JSON is mentioned but not specified — what happens if YAML parsing fails? Does it try JSON? The code should be explicit about this.

### 4.4 — SPEC-2: Template JSON includes `_comment` field

The template `enforcement-template.json` has a `_comment` field. JSON doesn't support comments. While it's valid JSON (just a regular key), the field would be loaded and ignored by the parser. Minor, but worth noting.

### 4.5 — SPEC-3 test: `test_report_in_code_block_not_detected` documents wrong behavior

The test explicitly documents that `extract_audit_reports()` WILL detect reports inside code blocks, and says "the caller must strip fenced blocks first." The handler's `on_agent_response()` should call `_strip_fenced_blocks()` before `_process_audit_reports()`, but the spec doesn't show this wiring. The test's comment says "extract_audit_reports is naive" — this should be documented in the function's docstring.

---

## Summary

| Category | Critical | Issue | Minor |
|----------|----------|-------|-------|
| Internal consistency | 2 | 4 | 1 |
| Architecture alignment | 1 | 4 | 1 |
| Correctness | 0 | 5 | 4 |
| **Total** | **3** | **13** | **6** |

### Critical findings (must fix before implementation):
1. **SPEC-3 `to_bug_journal_entry()` double-writes Fix field** — generates malformed journal entries
2. **SPEC-4 cron job uses wrong execution model** — OpenClaw agent can't call CrabCakes Python modules
3. **SPEC-3 architecture violation** — business logic (file I/O) in handler instead of utility

### High-priority issues (should fix):
1. **SPEC-3 target role defaults to "coder"** — breaks multi-agent scenarios
2. **SPEC-4 timestamp comparison is lexicographic** — mixed formats cause filter bugs
3. **SPEC-2 drops `{basename}_test.py` candidate** — minor functionality regression
4. **SPEC-4 dream_engine in utils/ does network I/O** — violates "no network" rule for utils/
5. **Proposal claims YAML is stdlib** — it's not; `pyyaml` is required

### Everything else is cosmetic or minor.

---

## Fix Log (2026-05-19)

All 22 findings addressed:

| Finding | Fix Applied |
|---------|------------|
| **1.1** SPEC-3 `to_bug_journal_entry()` double-write | Replaced broken conditional with clean `if self.fix:` / `if self.root_cause:` blocks |
| **1.2** Audit report field name `Root cause` with space | No code change needed — parser is consistent. Added note to SPEC-3 detection rules |
| **1.3** SPEC-1 vs SPEC-3 bug journal format mismatch | Fixed by 1.1 — `Fix` now maps to `self.fix`, `Lesson` maps to `self.root_cause` |
| **1.4** SPEC-1 enforcement default doesn't match Proposal | Fixed — defaults to `False`, overridden by checking `write_file` in agent's tool list |
| **1.5** SPEC-4 references non-existent prompt templates | Added docstring to `_read_agent_pitfalls()` documenting expected empty-string behavior |
| **1.6** SPEC-2 drops `{basename}_test.py` candidate | Restored the candidate in the candidates list |
| **1.7** SPEC-4 cron job uses wrong execution model | Replaced direct module import with CLI wrapper (`utils/dream_engine_cli.py`) exec'd via `python3 -m` |
| **2.1** SPEC-3 business logic in handler | Created `utils/feedback_processor.py` (§3.3), moved all file I/O there. Handler is now thin coordinator |
| **2.2** SPEC-1 circular import risk | Documented as acceptable risk — `utils/agent_defs` import in `prompt_loader` is lazy/try-except |
| **2.3** Proposal claims no agent/ imports but `get_available_tools()` does | Fixed claim — acknowledged the exception and documented fallback plan |
| **2.4** New files not in ARCHITECTURE.md | Noted as expected — implementation PR must update it |
| **2.5** SPEC-4 dream_engine in utils/ does network I/O | Moved to `agent/dream_engine.py`. All references updated |
| **2.6** Handler has 9 setters | Noted as code smell — acceptable for now |
| **3.2** SPEC-1 step numbering doesn't match code | Fixed — added steps 3b and 4 to match actual `compose_system_prompt()` code |
| **3.3** SPEC-3 target role defaults to "coder" | Fixed — now uses `resolve_default_target_role()` which returns 'unknown' unless exactly one writing agent exists |
| **3.4** SPEC-4 prune regex fragile | Replaced regex-substitution approach with position-based extraction using `match.span()` |
| **3.5** SPEC-4 no retry on LLM failure | Documented as known limitation with future improvement note |
| **3.6** SPEC-1 enforcement field unused | Acknowledged as dead data — harmless, may be used by future enforcement gating in prompt_loader |
| **3.7** Timestamp `+00:00` vs `Z` format mismatch | Normalized all `.isoformat()` calls to use `.replace("+00:00", "Z")`. Updated all example data |
| **3.8** SPEC-1 template placeholder `{agent-name}` doesn't match code | Fixed — changed to `{role}` and `{project_name}` with explanation |
| **4.1** SPEC-3 §5.4 skipped | Added §5.4 (self-review scenario) |
| **4.5** `extract_audit_reports` doesn't strip fenced blocks | Added docstring note documenting the behavior and caller responsibility |
| **4.3** Proposal claims YAML is stdlib | Fixed — now correctly states `pyyaml` is required, with JSON fallback and graceful degradation code |
| **4.4** SPEC-2 template has `_comment` field | Noted as valid JSON (just a key) — no fix needed |

---

## QTR Audit Verification (2026-05-19)

Second adversarial audit performed by QTR (Cutter). 20 findings total. Verified against current spec state and applied fixes where correct.

### QTR Finding Disposition

| Finding | QTR's Severity | Disposition | Action Taken |
|---------|---------------|-------------|-------------|
| **§1.1** Dual source of truth for self-improvement defaults | Medium | ✅ Correct | Consolidated to `utils/agent_defs.get_default_si_config()`. PROPOSAL's `SpecialAgentDef` and SPEC-1/3 both delegate to it |
| **§1.2** `_find_related_test` signature not in ARCHITECTURE.md | Low | ✅ Correct | Noted — ARCHITECTURE.md update required at implementation time |
| **§1.3** Inconsistent agent-def lookup patterns | Low | ✅ Correct, by design | Both `load_agent_def_by_role()` and `load_agent_defs()` serve different purposes |
| **§1.4** Handler-to-utils coupling for runtime context | Low | ✅ Correct, acceptable | Handler passes `runtime_handler` to utility — the coupling is explicit and narrow |
| **§1.5** Bug journal entries have inconsistent field sets | Low | ✅ Correct, by design | Fix is optional in SPEC-4 syntheses; not all bugs have fixes |
| **§1.6** `enforcement` default differs across specs | Medium | ✅ Correct | Fixed — all three specs now delegate to `get_default_si_config(can_write=...)` |
| **§1.7** SPEC-4 has two contradictory cron configs | Medium | ✅ Correct | Fixed — §4.1 now matches §2.2 CLI-wrapper approach |
| **§2.1** `utils/agent_defs.py` imports from `agent/tools.py` | Medium | ✅ Correct, acknowledged | Documented as exception with fallback plan. Not fixed — requires extracting tool metadata |
| **§2.8** SPEC-2 enforcement gating doesn't reconcile with global | Medium | ✅ Correct | Fixed — now clearly documents two-level gating (global first, then agent-specific) |
| **§2.9** Audit processing on relay messages | Low | ✅ Correct, intentional | No fix needed — review-log logging for all agents is by design |
| **§3.1** `_check_tests()` fallback generates literal `{test_file}` | Medium | ✅ Correct | Fixed — explicit `elif full_suite_command:` and `else: return None` branches |
| **§3.2** `related_test` variable scoping | Medium | ❌ Not a bug | `related_test` is always assigned before use in both branches — QTR corrected this in the same report |
| **§3.3** No fenced-block stripping before audit extraction | Medium | ✅ Correct | Fixed — `_strip_fenced_blocks(text)` now called before `extract_audit_reports()` |
| **§3.4** Journal pruning regex fragile | Low | ✅ Already fixed | My earlier pass replaced regex with position-based extraction |
| **§3.5** No retry on LLM calls | Low | ✅ Already fixed | Documented as known limitation |
| **§3.6** Pitfalls regex assumes heading format | Low | ✅ Correct, graceful | Returns empty string if heading missing — dream engine continues without current pitfalls |
| **§3.7** SPEC-1 insertion point references nonexistent code | Medium | ❌ Wrong | The `if agent_role == "coder":` / `elif agent_role == "debugger":` block DOES exist in the actual code at line 142 |
| **§3.8** Multi-writer projects file audits to unknown-bugs.md | Medium | ✅ Already fixed | Default changed to 'unknown' with explicit documentation |
| **§3.9** Pruning ignores LLM-suggested IDs | Low | ✅ Correct, design issue | Not fixed — low priority. The pruning still works (reduces to target count) |
| **§4.1** `prompts/default_agents/` not in ARCHITECTURE.md | Low | ✅ Correct | Noted — must be added during implementation |
| **§4.7** `dream-log.jsonl` hardcoded in two modules | Low | ✅ Correct | Fixed — `DREAM_LOG_FILENAME` now defined once in `utils/review_log.py`, imported by `agent/dream_engine.py` |

### New Fixes Applied from QTR's Report

1. **Single source of truth for SI defaults** — `get_default_si_config(can_write)` in `utils/agent_defs.py`. All consumers (PROPOSAL, SPEC-1, SPEC-3) delegate to it.
2. **SPEC-3 `_SI_DEFAULTS` removed** — replaced with `get_default_si_config()` calls.
3. **SPEC-4 §4.1 cron config** — aligned with §2.2 CLI-wrapper approach.
4. **SPEC-2 two-level enforcement gating** — global gate preserved, agent-specific gate added as second level.
5. **SPEC-2 `_check_tests()` fallback** — removed path that could generate `{test_file}` literal in command. Now explicitly returns None when no command can be built.
6. **SPEC-3 fenced-block stripping** — `_strip_fenced_blocks()` called before `extract_audit_reports()`.
7. **`DREAM_LOG_FILENAME` shared constant** — defined once in `utils/review_log.py`, imported by `agent/dream_engine.py`.

### QTR Findings Rejected

- **§3.7** — QTR claimed SPEC-1's insertion point references code that doesn't exist. Verified against actual codebase: the `if agent_role == "coder":` / `elif agent_role == "debugger":` block exists at `utils/prompt_loader.py:142`. Finding is incorrect.
- **§2.1** — Acknowledged but not fixed. Extracting tool metadata to a data file is a valid improvement but doesn't block implementation.
