# Implementation Loop

> **Status:** Authoritative loop architecture. All implementation work in this project that goes through a supervisor + builder + auditor trio MUST follow this loop. Deviations must be explicitly justified in the post-mortem.
>
> **Scope:** This prompt defines the **loop architecture** — the diagram, role boundaries, the four-prompt composition, the spec/architecture authority hierarchy, entry/exit conditions, and the **mandatory post-mortem format**. It does **not** repeat the supervisor's day-to-day tactics (channel trust, `/ask` payload mechanics, COMPLETENESS checklist, verification grep patterns, post-mortem trigger conditions). Those live in [`implementationSupervisor.md`](./implementationSupervisor.md) and are referenced, not duplicated, here.
>
> **Genericity:** This prompt is written for the crabcakes project but is **agent-trio-agnostic**. The roles `{{SUPERVISOR_AGENT}}`, `{{BUILDER_AGENT}}`, and `{{AUDITOR_AGENT}}` are placeholders. For the canonical crabcakes instance, the supervisor is who ever has the role SUPERVISOR, the builder is who ever has the role CODER, and the auditor is who ever has the role DEBUGGER. To port this loop to another project, copy this file and substitute the prompt paths, the architecture document, and the spec convention.

---

## 1. Purpose

Multi-agent implementation work is hard to supervise. The supervisor and the builder do not share context, do not run in the same session, and do not see the same things. A loop that works across many implementations has four properties:

1. **ARCHITECTURE.md is the floor. The spec narrows it. The code conforms to both.** ARCHITECTURE.md is the authoritative source of truth for both structure and behavior. The spec is a feature-level document that specializes ARCHITECTURE.md for one feature — it may narrow, but never override. The code is the artifact that conforms to both. Anything in the code that contradicts ARCHITECTURE.md is a bug, period. Anything in the spec that contradicts ARCHITECTURE.md is a spec bug, not an architecture bug.
2. **One phase at a time.** Multi-file changes fail more often than single-file changes. Sub-phase integration. Run independent verification between phases. A bug caught at phase N is a 5-minute fix; the same bug caught at phase N+3 is a half-day of cleanup.
3. **Audit every code-bearing turn (mandatory adversarial).** The builder's "done" claim is not evidence. The supervisor delegates the adversarial audit to the **auditor agent** on **every code-bearing turn** (pre-flight, between-phase, post-fix). The auditor loads [`adversarialDebugger.md`](./adversarialDebugger.md) and works through its 11 sections. This is mandatory — pattern-based audits without loading the prompt will miss non-obvious bugs. If bugs are found, the builder fixes them; the supervisor re-routes to the auditor for re-audit. The loop is "auditor adversarial audit → bug → builder fix → auditor re-audit → next phase" until clean. See §3.1a for the full rule.
4. **Post-mortem is the institutional memory.** The final deliverable is not just the code — it is the post-mortem. The post-mortem is the only artifact that survives across loops and across agent pairs. Use the mandatory format in §6 below. No post-mortem, no "done."

---

## 2. Loop Architecture

```
                 ┌────────────────────────────────────────────┐
                 │   Captain / User (human or upstream agent)  │
                 │   provides feature request or spec         │
                 └──────────────────────┬─────────────────────┘
                                        │
                                        ▼
                 ┌────────────────────────────────────────────┐
                 │   {{SUPERVISOR_AGENT}} — implementation    │
                 │   supervisor                  │
                 │                                            │
                 │  1. Read spec + ARCHITECTURE.md            │
                 │  2. Phase the work (1-3 files per phase)   │
                 │  3. Write phase-instructions file to disk  │
                 │  4. Delegate build via /ask @{{BUILDER_AGENT}}
                 │  5. Receive code from builder              │
                 │  6. Delegate audit via /ask @{{AUDITOR_AGENT}} │
                 │     (hand off the code-bearing turn to the │
                 │      auditor for the 11-section probe)     │
                 │  7. Auditor returns bug report?            │
                 │     ├─ Yes → route bug report to builder   │
                 │     │         (loop to step 5)              │
                 │     └─ No  → independent verification      │
                 │              (supervisor runs tests,       │
                 │               reads diffs, greps — own eyes)│
                 │  8. All phases done?                       │
                 │     ├─ No  → next phase (loop to step 3)   │
                 │     └─ Yes → post-mortem (mandatory        │
                 │              §6 format) + commit + report  │
                 └──┬───────────────┬───────────────┬─────────┘
                    │ /ask (build)  │ /ask (audit)  ▲
                    ▼               ▼               │ audit report
                 ┌───────────────────────┐ ┌────────┴──────────────┐
                 │  {{BUILDER_AGENT}}    │ │  {{AUDITOR_AGENT}}    │
                 │  — code writer        │ │  — adversarial auditor│
                 │                       │ │                       │
                 │ - Reads phase-        │ │ - Loads               │
                 │   instructions file   │ │   adversarialDebugger │
                 │ - Writes code per     │ │   .md fresh each turn │
                 │   steelFramedCodeWriter│ │ - Works through all   │
                 │ - Reports back with   │ │   11 sections against │
                 │   COMPLETENESS +      │ │   the code in scope   │
                 │   verification        │ │ - Reports bugs in BUG │
                 │   evidence            │ │   #[N] format to the  │
                 │ - Fixes bugs routed   │ │   supervisor          │
                 │   back by supervisor  │ │ - Does NOT fix code,  │
                 │                       │ │   does NOT commit,    │
                 │                       │ │   does NOT decide     │
                 │                       │ │   phase completion    │
                 └───────────────────────┘ └───────────────────────┘

   External prompts referenced (NOT duplicated in this file):
   ┌──────────────────────────────────────────────────────────┐
   │  steelFramedCodeWriter.md  → builder invokes when       │
   │                              writing code               │
   │  adversarialDebugger.md    → auditor MUST load on every │
   │                              code-bearing turn          │
   │                              (see §3.1a — mandatory,    │
   │                              not optional)              │
   │  implementationSupervisor.md → supervisor's standing    │
   │                              orders (tactics, not loop) │
   │  steelFramedSpecWriter.md  → writing the spec that      │
   │                              anchors the loop           │
   └──────────────────────────────────────────────────────────┘
```

---

## 3. Roles and Boundaries

### 3.1 {{SUPERVISOR_AGENT}} (Implementation Supervisor)

**Owns:**
- Reading the spec and ARCHITECTURE.md before any delegation
- Phasing the work into 1-3 file chunks
- Writing phase-instructions files to disk before the first `/ask`
- Sending the `/ask` to the builder
- **Adversarial audit on every turn** — loading [`adversarialDebugger.md`](./adversarialDebugger.md) and working through its 11 sections (challenge assumptions, trace failures, find hidden assumptions, test weakest links, exploit type system, break external contract, simulate weirdest user, verify scope coverage, audit docs, verify tests) **on every code-bearing turn**, including pre-flight checks, between-phase audits, and post-fix verifications. This is mandatory, not optional. See §3.1a below.
- Independent verification (running tests, reading diffs, greps) — **never trusting the builder's "done" claim**
- Writing the post-mortem at the end (mandatory §6 format)
- Committing and pushing the final work

**Does NOT own:**
- Writing code (delegates to the builder)
- Modifying the spec mid-loop (escalates to the captain if the spec is wrong)
- Running the project manually (the loop is push-based — the builder reports, the supervisor audits, repeat)

**Standing orders:** See [`implementationSupervisor.md`](./implementationSupervisor.md) for the complete tactical playbook (channel trust, `/ask` mechanics, COMPLETENESS enforcement, verification checklist, anti-patterns).

### 3.1a Mandatory Adversarial Audit on Every Turn

**The supervisor MUST load and apply [`adversarialDebugger.md`](./adversarialDebugger.md) on every code-bearing turn.** This is not optional and not skippable. The supervisor who audits "by pattern" without loading the prompt will miss non-obvious bugs (validated by the 2026-06-16 Auxilium Tier 2 audit, which found 2 MEDIUM bugs that pattern-based audits had missed across 5 phases).

**When "every turn" applies:**

| Turn type | Adversarial audit required? | Why |
|---|---|---|
| Pre-flight (verifying spec claims before writing phase instructions) | **Yes** | Catches spec-vs-code drift before code is written |
| Between-phase audit (after builder delivers, before next delegation) | **Yes** | This is the primary audit point |
| Post-fix verification (after builder fixes a flagged bug) | **Yes** | Confirms the fix actually addresses the root cause |
| Spec-writing turn (writing or revising a spec) | No | Specs are reviewed by the captain, not adversarially audited |
| Post-mortem turn | No | Post-mortems summarize the audit, they don't replace it |
| Pure-delegation turn (no code in scope) | No | Nothing to audit |

**How to apply:** Load `prompts/adversarialDebugger.md` fresh at the start of each audit turn. Work through its 11 sections against the code in scope. For each section, identify at least one adversarial probe. Run the probe. Report findings using the prompt's BUG format (BUG #[N] / Severity / Assumption violated / Attack vector / Reproduction / Root cause / Fix).

**When bugs are found:** Either (a) send a bug-fix delegation to the builder before continuing the loop, or (b) escalate to the captain if the bug is out of scope. Do NOT silently incorporate fixes into a later phase — that violates the scope-creep rule and breaks the audit trail.

**Tracking:** Count the number of adversarial audits performed per loop in the post-mortem §4 (Bugs Found During Audit). State explicitly which bugs were caught by adversarial audit vs. by pattern-based verification. This data feeds the standing-orders process for future loops.

### 3.2 {{BUILDER_AGENT}} (Code Writer)

**Owns:**
- Reading the phase-instructions file in full before writing any code
- Reading every file the phase touches in full before editing
- Writing code per [`steelFramedCodeWriter.md`](./steelFramedCodeWriter.md) — applies every rule
- Verifying every claim with evidence (test output, `wc -l`, `grep` output, `inspect.signature` results)
- Reporting back with the COMPLETENESS checklist, files-changed list, and all verification command outputs
- Fixing bugs reported by the supervisor (does not silently expand scope — flags related issues)

**Does NOT own:**
- Phasing the work
- Auditing their own code
- Deciding when the implementation is done
- Committing final work (the supervisor owns the commit/push)

**Standing orders:** See [`steelFramedCodeWriter.md`](./steelFramedCodeWriter.md) for the complete builder playbook (read-before-touch, hard-part-first, verify-every-claim, wire-it-or-delete-it, no-fabricated-APIs, etc.).

### 3.3 The Contract Between Them

The supervisor's `/ask` payload is the **delegation contract**. The builder's response is the **delivery**. The contract has four required parts:

1. **Phase scope** — exact files and line numbers (or exact identifiers, when line numbers may have drifted)
2. **Rule reference** — `prompts/steelFramedCodeWriter.md` (the builder must invoke it)
3. **Word marker** — a known phrase (e.g., "please write", "please proceed") so the channel knows the message is canonical
4. **Deliverable expectations** — files-changed list, verification outputs, COMPLETENESS checklist, related issues (flagged, not silently fixed)

A delivery that lacks any of the four is incomplete. The supervisor sends the delivery back. See `implementationSupervisor.md` §3 (Short, Sharp Delegations) for the full template.

---

## 4. The Four-Prompt Composition

The loop is implemented by composing four existing prompts. Each prompt owns one responsibility. No prompt duplicates another's content.

| Prompt | Owner | Invoked when | Responsibility |
|---|---|---|---|
| [`steelFramedSpecWriter.md`](./steelFramedSpecWriter.md) | Supervisor or captain | Before the loop starts | Write the spec that specializes ARCHITECTURE.md for one feature. The spec assumes ARCHITECTURE.md is in force; it must not contradict it. |
| [`steelFramedCodeWriter.md`](./steelFramedCodeWriter.md) | Builder | Every code-writing delegation | How to write code: read-before-touch, hard-part-first, verify-every-claim, wire-it-or-delete-it, no-fabricated-APIs, defensive copies, etc. |
| [`adversarialDebugger.md`](./adversarialDebugger.md) | Supervisor | **On every code-bearing turn (mandatory, see §3.1a)** | How to audit: challenge every assumption, trace failure backwards, find hidden assumptions, test weakest links, break the external contract, simulate the weirdest user, verify scope coverage, audit docs, verify tests match. |
| [`implementationSupervisor.md`](./implementationSupervisor.md) | Supervisor | Continuously, as standing orders | Supervisor tactics: how to phase, how to delegate, how to verify, how to handle the `/ask` channel, how to write a post-mortem trigger. |

**This prompt (`implementationLoop.md`) is the fifth piece.** It does not duplicate any of the above. It defines:
- The loop diagram and role boundaries
- The spec/architecture authority hierarchy (§5)
- The entry/exit conditions (§7)
- The mandatory post-mortem format (§6)

If you find yourself re-explaining how to write a `/ask` payload, how to fill in the COMPLETENESS checklist, or how to challenge an assumption, you are in the wrong prompt. Link, don't duplicate.

---

## 5. Authority Hierarchy

**The single source of truth is `ARCHITECTURE.md`.** The spec and the code both derive from it. The spec may *narrow* or *specialize* ARCHITECTURE.md for a particular feature, but it may never *override* or *contradict* it. If the spec and ARCHITECTURE.md conflict, **ARCHITECTURE.md wins and the spec is wrong** — fix the spec, do not bend the architecture.

When any of these sources disagree, the resolution order is:

```
   1. Captain's standing orders (highest — only the captain can override ARCHITECTURE.md)
      │
      ▼
   2. ARCHITECTURE.md (the floor — authoritative for both structure and behavior;
      │                  the spec and the code must conform to it)
      │
      ▼
   3. The spec (a feature-level document; narrows ARCHITECTURE.md but never
      │          contradicts it; if it does, the spec is wrong, escalate)
      │
      ▼
   4. The code (the artifact; must conform to both ARCHITECTURE.md and the spec)
```

### The two dimensions of authority

ARCHITECTURE.md is authoritative along **both** dimensions the spec touches:

- **Structure** — directory layout, import rules, callback patterns, the "no imports from `ui/`, `gateway/`, `subprocess`" rules, the "no GTK in handlers" rule, the handler/view separation, the polling-bridge pattern. The builder must read ARCHITECTURE.md. The supervisor must enforce it.
- **Behavior** — what a module is allowed to do, what side effects it may have, what state it owns, what guarantees it makes to its callers. If ARCHITECTURE.md says "handlers are pure Python and GTK-free," the spec cannot say "this handler may use Gtk.Dialog" — even if that would be more convenient for the feature.

The spec's job is to **specialize** ARCHITECTURE.md for one feature: which files to add, what the public API looks like, what the user-visible behavior is. The spec assumes ARCHITECTURE.md is already in force. The spec does not re-derive the architecture for the feature.

### Resolution rules

**Rule 1: ARCHITECTURE.md is authoritative. The spec may not override it.**
If the spec says "use Gtk.Dialog in the handler" and ARCHITECTURE.md says "no GTK in handlers," the spec is wrong. The supervisor flags the spec, the captain (or spec author) fixes the spec, and the work proceeds with a GTK-free handler. **Do not write code that violates ARCHITECTURE.md to satisfy the spec.**

**Rule 2: The spec is the feature-level contract.**
Within the constraints of ARCHITECTURE.md, the spec defines what the feature must do: the public API of new functions, the user-visible behavior, the acceptance criteria, the file structure for the feature. If the spec is silent on a question (e.g., "what should the timeout be?"), ARCHITECTURE.md or existing codebase conventions supply the answer — the supervisor picks the most consistent choice and flags it in the post-mortem as a "spec gap."

**Rule 3: The code is the artifact, not the authority.**
If the code does X but the spec says Y, the code is wrong. If the code does X but ARCHITECTURE.md forbids X, the code is wrong (and the spec would be wrong too if it asked for X). The supervisor's audit (via `adversarialDebugger.md`) is the mechanism for catching both kinds of mismatch.

**Rule 4: When the spec is wrong, fix the spec — not the code, not the architecture.**
A spec bug discovered mid-loop is escalated to the captain. The supervisor pauses the affected phase, the captain (or spec author) updates the spec, and the loop resumes. The post-mortem logs the spec fix as a process event. The architecture is never bent to fit a bad spec; the spec is corrected to fit the architecture.

**Rule 5: Spec drift is a real failure mode.**
Specs that hardcode line numbers drift as files grow. The builder must anchor edits to identifiers (function names, class names, dataclass field names), not line numbers. Spec drift >10 lines from the documented location must be flagged in the COMPLETENESS checklist as "Spec drift" and the supervisor decides whether to update the spec. **Note:** spec drift is a documentation problem, not a code problem. The code is correct; the spec's pointer is stale. Update the spec; do not "fix" the code to match the stale line number.

---

## 6. Mandatory Post-Mortem Format

Every implementation loop that completes MUST produce a post-mortem in the following format. This format was validated on the D7 Auxilium first-run wizard implementation (Tier 1) and is now the standard for all post-mortems going forward. **A post-mortem that omits any of the 11 sections below is incomplete and the work is not done.**

The post-mortem file lives at `docs/post-mortems/YYYY-MM-DD-<FEATURE>-POST-MORTEM.md` (use the date the loop started, not the date the post-mortem was written).

### 6.1 Required Sections (11 total)

```markdown
# <Feature> Post-Mortem

**Date:** YYYY-MM-DD
**Supervisor:** <name>
**Builder:** <name>
**Commits:** <count> (<short SHA list>)
**Phases:** <count> (e.g., handler → view → wiring → tests → docs → commit)
**Total bugs found:** <count> (<severity breakdown>)
**Process:** <one-line description of how the loop ran>

---

## 1. Code Quality Grade: <LETTER> (<NN>/100)

### Justification

<One paragraph explaining the grade. State what went well, what didn't, what was caught
in-phase vs. after-the-fact.>

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | NN/20 | <one-line> |
| Architecture compliance | NN/10 | <one-line> |
| Test coverage         | NN/10 | <one-line> |
| Documentation         | NN/10 | <one-line> |
| Maintainability       | NN/10 | <one-line> |
| DX (Developer Exp.)   | NN/10 | <one-line> |
| **Total**             | **NN/100** | <grade letter and short label> |

Deducted points:
- <N> <category>: <one-line reason>
- <N> <category>: <one-line reason>

---

## 2. What's Good About the Code

<Numbered list of architectural wins, design decisions, defensive patterns, or process
discipline that paid off. Each item: name the pattern, cite the file/line where it
landed, and explain why it matters. Minimum 3 items.>

1. **<Pattern name>:** <description>. <File:line> — <why it matters>.
2. **<Pattern name>:** <description>. <File:line> — <why it matters>.
3. **<Pattern name>:** <description>. <File:line> — <why it matters>.

---

## 3. What's Bad About the Code

<Numbered list of code quality issues, missed requirements, scope creep, or design
choices that should evolve in a future tier. Each item: name the issue, quantify it
(where possible), and propose an evolution path.>

1. **<Issue>:** <description>. <Quantification: line counts, time, complexity>.
   - Evolution suggestion: <what to do in Tier 2+>
2. **<Issue>:** <description>. <Quantification>.
   - Evolution suggestion: <what to do in Tier 2+>

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| 1 | <N>   | <sev>    | <one-sentence description> | <name> (probe <ref>) | <name> (1 commit) |
| 2 | <N>   | <sev>    | <one-sentence description> | <name> (probe <ref>) | <name> (1 commit) |

<One paragraph summarizing: how many bugs, what kinds, whether they compounded. State
whether any bug reached downstream phases before being caught.>

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `<kebab-case-tag>` | N | <one-line description> |
| `<kebab-case-tag>` | N | <one-line description> |

---

## 5. Process: What Worked

<Numbered list of process decisions that made the loop efficient or caught issues
early. Cite specific actions taken (e.g., "sub-phasing within integration", "running
probes before delegations", "file-based delegation for complex instructions").>

1. **<Process decision>:** <description>. <Why it worked: time saved, bugs caught, or
   clarity gained.>
2. **<Process decision>:** <description>. <Why it worked.>
3. **<Process decision>:** <description>. <Why it worked.>

---

## 6. Process: What Didn't Work

<Numbered list of process failures, miscommunications, or tooling issues that wasted
time or caused bugs. For each, state the lesson and the proposed fix.>

1. **<Failure>:** <description>. <Impact: time lost or bug caused.>
   - Lesson: <what to do differently next time>
2. **<Failure>:** <description>. <Impact.>
   - Lesson: <what to do differently next time>

---

## 7. What the Code Actually Does (End-User Impact)

<One paragraph per user-facing behavior. Describe what a real user sees, clicks, and
gets back. Anchor every paragraph to a code path (file:line). This is the section
that answers "did this feature actually work for a human?" not "did the tests pass?".>

1. **<Behavior>:** <user-visible description>. Code path: <file:line> → <file:line>.
2. **<Behavior>:** <user-visible description>. Code path: <file:line> → <file:line>.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

<Numbered list of issues found in the codebase during the loop that pre-existed and
were NOT fixed (per scope-creep rule). For each: state the issue, cite the source
verification (e.g., "pre-existing on HEAD before this work"), and note that it was
intentionally left for a future loop.>

1. **<Issue>:** <description>. Verified pre-existing on <commit SHA>. Not in scope.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| <one-line description> | <hours or days> | <what improves: test time, code size, DX, etc.> |
| <one-line description> | <hours or days> | <what improves> |

---

## 10. Lessons Learned / Process Rules to Carry Forward

<Numbered list of durable rules that should be added to the standing-order prompts
(`implementationSupervisor.md`, `steelFramedCodeWriter.md`, `adversarialDebugger.md`,
or this file) based on what was learned in this loop. Each rule: name it, state the
trigger, state the action.>

1. **<Rule name>:** <one-line statement of the rule>.
   - Trigger: <when to apply>
   - Action: <what to do>

---

## 11. Sign-off

- [ ] Code committed and pushed to <branch>
- [ ] All post-loop verification commands run and pasted
- [ ] Captain notified with summary
- [ ] Tier 2+ backlog updated (if any items deferred)
```

### 6.2 Section Content Requirements

| Section | Min. length | Required content |
|---|---|---|
| 1. Code Quality Grade | 1 paragraph + table + deduction list | Score, justification, table with 6 categories, deducted-points list |
| 2. What's Good | 3 numbered items | Each cites file:line and explains why it matters |
| 3. What's Bad | 2 numbered items | Each has quantification + evolution suggestion |
| 4. Bugs Found | Table + paragraph + pattern sub-table | All bugs from the audit cycle, even if severity is LOW |
| 5. Process Worked | 3 numbered items | Each names a process decision and explains the payoff |
| 6. Process Didn't Work | 2 numbered items | Each names a failure, quantifies impact, and states a lesson |
| 7. End-User Impact | 2 numbered items | Each is a user-visible behavior with anchored code path |
| 8. Pre-Existing Issues | 1 numbered item or "None" | If any, cite the pre-existing commit SHA |
| 9. Evolution Suggestions | Table with 2+ rows | Each row has effort + impact |
| 10. Lessons Learned | 2 numbered items | Each names a rule, trigger, and action |
| 11. Sign-off | All checkboxes ticked | No unchecked boxes |

### 6.3 What the Post-Mortem Is NOT

- It is **not** a changelog or commit message. Commits already exist; the post-mortem summarizes the arc.
- It is **not** a tutorial. Future readers need the conclusions, not the step-by-step.
- It is **not** an apology or a victory lap. State what worked, what didn't, and what's next. No hedging.
- It is **not** a place to fix bugs. Bugs are fixed in the code. The post-mortem reports on them.

### 6.4 When to Write It

- After the last phase's audit returns clean.
- After independent verification (full test suite, clean launch smoke, `G_DEBUG=fatal-criticals` if GUI).
- Before the final commit/push.
- The supervisor owns the post-mortem file. The builder reviews it (in case of attribution errors) but does not write it.

---

## 7. Entry and Exit Conditions

### 7.1 Entry (when to start the loop)

The supervisor starts the implementation loop when **all** of the following are true:

- [ ] A spec or feature request exists on disk (either a captain-provided request, a `docs/specs/SPEC-*.md` file, or an extracted user story)
- [ ] ARCHITECTURE.md is read in full by the supervisor
- [ ] The supervisor can identify the entry points affected by the change
- [ ] The captain (or upstream) has authorized the work (implicit for small changes, explicit for tier-level work)
- [ ] The builder agent is reachable via `/ask` on an authorized channel (per `implementationSupervisor.md` §9.5)

If any of these is false, the supervisor escalates to the captain before proceeding.

### 7.2 Exit (when "done" is real)

The loop is complete when **all** of the following are true:

- [ ] Every phase has been completed and audited clean (no outstanding bugs)
- [ ] Every file in the phase scope was changed as specified (verified by diff inspection)
- [ ] All verification commands were run independently by the supervisor (tests, greps, launches)
- [ ] All pre-existing failures in the test suite are attributed correctly (not caused by this work)
- [ ] ARCHITECTURE.md is still consistent with the new code (no undocumented conventions introduced)
- [ ] A post-mortem file exists at `docs/post-mortems/YYYY-MM-DD-<FEATURE>-POST-MORTEM.md` matching the §6 format
- [ ] The post-mortem is committed and pushed
- [ ] The captain has been notified with a one-paragraph summary

If any of these is false, the loop is not done. The supervisor either continues the bug-fix loop, updates ARCHITECTURE.md, or escalates to the captain.

### 7.3 Stop Conditions (when to abort the loop)

The supervisor aborts the loop and escalates to the captain when:

- The spec is fundamentally broken (contradicts itself, references nonexistent systems, or conflicts with the captain's intent)
- The builder fails the same phase three times after full delegation cycles
- The loop uncovers a pre-existing critical bug that blocks the work
- The captain revokes authorization mid-loop

In all cases, the supervisor writes a short abort note in the post-mortem file (or a dedicated `docs/post-mortems/ABORT-YYYY-MM-DD-<FEATURE>.md` if the post-mortem can't be completed) explaining why and what's needed to resume.

---

## 8. Worked Example (Reference)

The D7 Auxilium first-run wizard (Tier 1) implementation is the canonical reference for this loop. The post-mortem is at `docs/post-mortems/2026-06-13-D7-AUXILIUM-WIZARD-POST-MORTEM.md` and is a complete example of the §6 format in production.

**What the loop looked like for D7:**

- **Spec:** `docs/specs/SPEC-auxilium-tier-1.md` (417 lines, 10 acceptance criteria)
- **Phases:** 6 (handler → view → wiring → tests → docs → commit)
- **Sub-phasing:** Phase 3 (wiring) was sub-phased into 3a (helper), 3b (wizard creation), 3c (dismissal) — three sub-phases in one instructions file
- **Bugs caught in-phase:** 3 HIGH (all caught between phases, none compounded)
- **Bug patterns:** `reference-leak`, `view-sync`, `parameter-ignored`
- **Code quality grade:** A- (90/100)
- **Process rules added to standing orders:** 4 (defensive copy on state return, view re-reads after callback, `config_dir` over globals, `tempfile.TemporaryDirectory()` for handler tests)

When a new implementation loop starts, the supervisor reads the most recent post-mortem of the same feature area first to understand the prior context, recurring bug patterns, and the standing rules already in place.

---

## 9. Cross-References

- **Tactics for the supervisor** (channel trust, `/ask` mechanics, COMPLETENESS enforcement, anti-patterns): [`implementationSupervisor.md`](./implementationSupervisor.md)
- **How the builder writes code** (read-before-touch, hard-part-first, verify-every-claim, wire-it-or-delete-it): [`steelFramedCodeWriter.md`](./steelFramedCodeWriter.md)
- **How the supervisor audits** (challenge assumptions, trace backwards, test weakest links, break the contract): [`adversarialDebugger.md`](./adversarialDebugger.md)
- **How the spec is written** (acceptance criteria, phased deliverables, completion markers): [`steelFramedSpecWriter.md`](./steelFramedSpecWriter.md)

---

## 10. Versioning and Updates

This file is the **fifth canonical prompt** in the project's prompt set. It is referenced from every post-mortem and from the standing orders in `implementationSupervisor.md`. Updates to this file must:

1. Preserve the 11-section post-mortem format in §6 (or explicitly version-bump and migrate old post-mortems)
2. Preserve the four-prompt composition in §4 (or explicitly deprecate a prompt and migrate its content)
3. Preserve the mandatory adversarial-audit rule in §3.1a (or explicitly deprecate the rule with a documented rationale and migration plan)
4. Be reviewed by the captain before merge (this is a meta-prompt; mistakes here propagate to every future loop)
5. Be committed in a single commit with a `meta:` prefix in the message

