# BUGFIX 5 & 6 — Document gateway event limitations

## Problem

Bugs #5 and #6 are NOT code bugs in Crabcakes — they are gateway-side limitations that produce the same symptom as code bugs (missing rows in the activity drawer). Users and developers need to know about these limitations.

## What to document

### BUG #5 — Patch events only fire for `apply_patch` tool

The gateway (`openclaw 2026.5.18`) only emits `stream: "patch"` events inside an `if (isPatchToolName(toolName))` block where `isPatchToolName` returns `toolName === "apply_patch"`. Agents that use `write`, `edit`, `write_file`, `edit_file`, or `str_replace_editor` tools will NOT produce patch events from the gateway. The Crabcakes code is correct — it handles patch events when they arrive — but they simply never arrive for most tools.

### BUG #6 — Plan events only fire on planning-only-retry

The gateway only emits `stream: "plan"` events inside a planning-only-retry loop (when the model outputs a plan and needs to retry). Normal agent turns where the model responds directly do NOT emit plan events. The Crabcakes code is correct — it handles plan events when they arrive.

## What to implement

### File: `docs/specs/SPEC-activity-drawer.md`

Add a new section at the end of the spec (or after the event catalog section) called "Gateway Event Limitations" with:

```markdown
## Gateway Event Limitations

The following activity drawer event types depend on gateway emission policies that are outside Crabcakes' control. The code handles these events correctly when they arrive, but they may not appear in all sessions.

### Patch Events (`stream: "patch"`)

**Limitation:** The gateway only emits patch events for the `apply_patch` tool. Agents using `write`, `edit`, `write_file`, `edit_file`, or `str_replace_editor` will NOT produce patch events. Patch rows will only appear when an agent uses `apply_patch`.

**Workaround options:**
- (A) Add client-side detection: treat `stream: "item" kind: "tool"` end events with `name` in `{write, edit, write_file, edit_file}` as patch-like events
- (B) Document the limitation and rely on the tool_start/tool_end rows for file-edit visibility

### Plan Events (`stream: "plan"`)

**Limitation:** The gateway only emits plan events during a planning-only-retry loop. Normal agent turns do not emit plan events. Plan rows will only appear when the model enters a retry cycle.

**Impact:** In most sessions, no plan rows will appear. This is expected behavior.

### Approval Events (`stream: "approval"`)

**Limitation:** Approval events only fire when an exec requires interactive approval (status: "approval-pending"). In sessions where all execs are auto-approved, no approval rows appear. This is expected behavior — the activity drawer only shows approval rows when the user needs to act.

### Command Output Events (`stream: "command_output"`)

**No limitation as of BUGFIX-1.** The handler now correctly processes gateway command_output events. Previously these were silently dropped.
```

### No code changes needed for BUGFIX-5 or BUGFIX-6.

## Verification Commands

```bash
cd /home/q/projects/crabcakes
grep -n "Gateway Event Limitations\|Patch Events.*Limitation\|Plan Events.*Limitation" docs/specs/SPEC-activity-drawer.md
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5
```

## Completeness Checklist

```
COMPLETENESS:
- [ ] Edit 1: Added "Gateway Event Limitations" section to SPEC-activity-drawer.md — evidence: grep output
- [ ] Edit 2: Documented patch event limitation (BUG #5) — evidence: grep output
- [ ] Edit 3: Documented plan event limitation (BUG #6) — evidence: grep output
- [ ] Edit 4: Documented approval and command_output notes — evidence: grep output
- [ ] Edit 5: Full test suite passes (no regressions from doc-only change) — evidence: pytest output
```
