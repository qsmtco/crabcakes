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

---

## HIGH-2 — Remote A2A provenance / per-source trust list (2026-06-19)

**Status:** Parked. Will not be addressed in current sprint.

**What:** When agent A asks agent B to run a tool/command, B currently treats the request as if A is fully trusted (same trust level as the local user). If A is a remote third-party gateway, that's a trust-boundary violation. The fix is provenance tagging (`source_id` on every inbound request, set by the transport layer) plus a per-source trust list (`~/.config/crabcakes/remote_sources.yaml`) consulted before any tool/command execution.

**Trigger (revisit when ANY of these is true):**
- Connecting crabcakes to a remote gateway operated by a third party (not just "you from your phone").
- Adding cross-device sync via a remote intermediary.
- A second user is added to the deployment with different trust posture.

**Why defer:**
- Current deployment is single-user, loopback-only. The only "remote" source is the user's own phone relaying the user's own commands.
- Trust boundary is the user, not the network. No third-party gateway in the picture.
- Requires gateway protocol change (add `source_id` field, propagate through every transport).
- Adds latency: per-source trust lookup + possibly confirm dialog per inbound command.
- New config file to maintain.

**Why it's fine as-is:** Threat model doesn't apply. Local agent, local user, loopback. The "remote A2A" path doesn't exist.

**Estimated effort when triggered:** ~1 day implementation + review (design already spec'd).

**See also:** `docs/proposals/PROPOSAL-security-remediation-roadmap.md` §HIGH-2 design (lines ~320–340, 469) — full design specified, not implemented.
