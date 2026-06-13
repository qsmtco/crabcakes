# PHASE 10.5b — Spec freshness pass: line numbers + §12 reference

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md`
**Adversarial finding:** Post-mortem item #3 — spec references stale line numbers and a §12 that didn't exist in the current `docs/ARCHITECTURE.md`. Future phases that use this spec as input will land in the wrong place.

---

## Files to change

1. `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` — update stale line numbers and §12 reference

## What to do

**Edit 1 — Add a "Post-implementation line number corrections" note to the top of the spec:**

Find the spec header (around line 1-10, just after the title and before the "Architecture compliance" blockquote).

Insert this note at line 3 (right after the `# PHASE 10 — Provider Caller Field` heading, before the blockquote):

```markdown
> **Note (PHASE 10.5b):** The line numbers in this spec were written against an earlier version of the codebase. Verified current line numbers as of PHASE-10.5b:
>
> - `_call_llm_streaming` streamer lookup: line **573** (spec said 1303) — this is the module-level function, not the method
> - `_call_llm` caller lookup: line **1374** (spec said 1352)
> - `_resolve_caller_key` definition: line **1284** (spec said ~1281)
> - `_call_llm` definition: line **1302** (spec said 1281)
> - `settings_dialog.py` placeholder: line **38** (spec said 37-38) ✓
> - `settings_dialog.py` caller label widget: line **95** (spec said ~91)
> - `settings_dialog.py` `_populate_from_provider` caller set: line **146** (spec said ~138)
> - `settings_dialog.py` `_collect_from_form` caller preserve: line **181** (spec said ~170)
> - `agent_runtime_handler.py` double-prefix guard: line **291** (spec said 286-289)
> - `provider_test.py` `test_connection` signature: line **59** (spec said 47-88)
>
> The §2.4 "streamer lookup" change in this spec was **deferred to PHASE 10.5a** (now in commit `[pending]`). The `caller_key` is now resolved at the caller of `_call_llm_streaming` and passed as a parameter, rather than being resolved inside the function (see PHASE-10.5a for rationale).
>
> ARCHITECTURE.md §12 reference: the new section "Provider Resolution & API Caller" was inserted as **§12** (renumbering old §12→§13, §13→§14). This spec's "§12 Provider Resolution & API Caller" references now correctly point to that section.
```

**Edit 2 — Fix the comment in `verify_caller_resolution.py` about the streamer (optional, cosmetic):**

This is NOT required. The spec's §2.4 will be re-implemented in PHASE 10.5a, so the stale "line 1303" references will become accurate again after that phase lands.

**Edit 3 — DO NOT change the spec's code samples or verification commands.** The spec is the source of truth for what was built. Even if a line number drifted, the *intent* of each section is still correct. Future readers can use the actual code to find the right line.

## Why this matters

The spec is a contract. When the next phase (e.g. PHASE-11) is written, the implementer will grep the spec for line numbers. If those numbers are 70 lines off, they'll either:
1. Trust the spec and edit the wrong lines (bug)
2. Distrust the spec and spend time verifying (slow)
3. Notice the discrepancy and pause to ask (correct, but wasteful)

Adding the corrections note at the top makes option (1) impossible without rewriting history, makes option (3) unnecessary, and makes option (2) faster (grep the actual line in the note's table).

## Rules

- Use the implementationSupervisor prompt at `/home/q/projects/crabcakes/prompts/implementationSupervisor.md`
- Read `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` lines 1-15 before editing
- Make ONLY the 1 edit described above (insert the corrections note at line 3)
- Do NOT rewrite the rest of the spec
- Do NOT change code samples or verification commands
- Do NOT commit the spec as part of PHASE-10 (it's untracked scaffolding). But for this phase, DO commit the spec update so the spec stays in sync with the code.

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
# Verify the corrections note is in place
head -25 docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md
```

Expect: the corrections note appears at the top, before the "Architecture compliance" blockquote.

```bash
cd /home/q/projects/crabcakes
# Verify the actual line numbers in the spec match reality
echo "=== agent/runtime.py ==="
grep -n "def _call_llm_streaming\|def _call_llm(\|def _resolve_caller_key\|streamer = _PROVIDER_STREAMERS\|caller = _PROVIDER_CALLERS" agent/runtime.py
echo "=== ui/views/settings_dialog.py ==="
grep -n "caller=\"\")\|self._caller_label\|caller=existing.caller" ui/views/settings_dialog.py
echo "=== ui/handlers/agent_runtime_handler.py ==="
grep -n "if \"/\" in prov_cfg.default_model\|return f\"{provider}/{prov_cfg.default_model}\"" ui/handlers/agent_runtime_handler.py
```

Expect: the actual line numbers match (or are within 2 lines of) the numbers in the corrections note.

```bash
cd /home/q/projects/crabcakes
# Verify ARCHITECTURE.md §12 reference
grep -n "^## 12\." docs/ARCHITECTURE.md
```

Expect: line 3037 (the new "Provider Resolution & API Caller" section from P9).

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.
