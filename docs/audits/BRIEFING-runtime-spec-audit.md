# Debugger Briefing — Audit the Updated Runtime Extraction Spec

## Context
Coder just refreshed `docs/specs/SPEC-RUNTIME-MODULAR-EXTRACTION-PHASE-1.md` to match the current state of `agent/runtime.py` (3,297 lines, up from the 2,495 the spec was originally written against). This is a SPEC audit, not a code audit — you're verifying that the spec is accurate against the actual source, so that a future implementer (Coder) can follow it without hitting wrong line numbers or stale signatures.

## Your job
Use the adversarial methodology from `prompts/adversarialDebugger.md`, but adapted for spec verification (not code-bug-hunting). The steel-framed spec writer prompt (`prompts/steelFramedSpecWriter.md`) has Rules 1-10. Your job is to verify the spec author (Coder) actually followed them. Specifically:

### Verification targets

1. **Every line number citation is current.** The spec cites dozens of line numbers (in the discovery table, in §A.1, §B.1-B.4, §C, §D). Coder claims 37/37 anchors verified. Independently spot-check at least 15 of them by grepping the actual source. The drift was ~430-560 lines; any citation still referencing the old offsets is a bug.

2. **Code samples match the actual current code.** The spec contains code samples for the tool-middleware chain (§A.2) and the LLM provider adapter (§B.2-B.4). These were written against the June-28 source. The runtime has changed since (e.g., the `success: bool` param on `_on_tool_call_result` dispatch, the turn-start `_on_text_delta` dispatch at line 2118, the `_pending_tool_args`/`_ended_sessions` state from the activity-drawer work). Do the spec's code samples reflect these changes, or do they show the old signatures/patterns?

3. **The `_run_loop` region (the extraction target for Track A).** The spec claims the tool-exec block is at lines 2455-2583. Read the actual `_run_loop` (starts at line 2101) and verify: (a) the approval gating is where the spec says, (b) the enforcement check is where the spec says, (c) the stuck detection is where the spec says, (d) the `execute_tool` call and its args match the spec's sample.

4. **The discovery table accuracy.** The §0 table claims runtime.py has "15 module-level LLM functions, 3 cost functions, AuditLog/AuditEntry classes" at specific line ranges. Verify these counts and ranges against the actual file. If the file now has 16 provider functions or the AuditLog class moved, that's a staleness bug.

5. **Lines-freed projections.** The spec projects runtime.py shrinks from 3,297 → ~2,327 after both tracks. Verify the arithmetic: does Track A's claimed ~250 lines freed + Track B's claimed ~970 lines freed actually sum correctly against the starting count?

6. **Backward-compat re-exports.** The spec lists symbols that runtime.py will re-export after extraction (§A.7, §B.5). Do all those symbols actually exist in the current runtime.py at the cited lines? Any symbol that was renamed or removed since June 28 would break the re-export plan.

7. **Test line citations.** The spec cites test classes (TestStreamingSignature, TestApproval, TestStuckDetection, TestStreamingUsageCapture) at specific lines in tests/test_agent_runtime.py. Verify these — the test file has grown significantly with the activity-drawer work (20 new tests in TestLocalAgentDrawerEmissions).

### What NOT to audit
- The extraction *design* (whether tool_middleware.py is the right architecture) — that's a separate review. Only audit whether the spec accurately describes the *current* code.
- The proposal (PROPOSAL-runtime-modular-extraction.md) — only audit the SPEC.

## Output
Use the BUG #[N] / issue format. For each finding, cite the spec section, the spec's claim, the actual source value, and the fix needed. If the spec is clean, say so explicitly with a summary of what you verified.
