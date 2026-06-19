# Deferred Items

Items considered and consciously parked for future consideration. Each entry records the rationale for deferring and the trigger that would make it worth revisiting. Do **not** re-litigate these without that trigger being met.

---

## A-11 — runtime.py god-object refactor (2026-06-19)

**Status:** Parked. Will not be addressed in current sprint.

**What:** `agent/runtime.py` is 1501 lines mixing message routing, KB integration, tool execution, prompt assembly, state management, and error handling. Refactor would split it into focused sub-modules along natural seams.

**Why defer:**
- Pure refactor, no user-visible win.
- Seams are non-obvious — splitting wrong creates new coupling.
- Current urgent work (Phase 3 security remediation) takes priority.
- For a single-contributor project, the cost (regression risk, test maintenance, review effort) currently exceeds the benefit.

**Why it's fine for now:** File has a clear top-down structure. Functions are reasonably named. 1501 LOC is large but not catastrophic. Bug-hunt turnaround is acceptable.

**Revisit when ANY of these is true:**
- About to add a large feature that touches `runtime.py` extensively.
- Bug-hunt turnaround time on runtime issues is hurting productivity.
- A second contributor is joining and needs shorter files to ramp up.
- The file grows past ~2000 LOC.

**See also:** `docs/audits/ARCHITECTURE-AUDIT-2026-06-11.md` (the audit that flagged A-11 originally).
