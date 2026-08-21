# Pango Attribute Validation Post-Mortem

**Date:** 2026-08-21
**Supervisor:** Supervisor
**Builder:** Coder
**Auditor:** Debugger
**Commits:** `6fda382` (Phase 1), `3e2cebc` (Phase 2)
**Phases:** 2 (Phase 1: escaper validation + feed_card guards, 1 send-back; Phase 2: remaining guard sites)
**Total bugs found:** 4 (2 audit-found blockers in Phase 1 + 2 non-blocking notes in Phase 2; plus the 5 original production warnings as the initiating defect)
**Process:** investigation (read-only) → spec → Phase 1 delegation → Debugger audit (1 CRITICAL + 1 HIGH) → Supervisor independent reproduction → send-back → Coder fix → re-audit ACCEPT → commit → Phase 2 delegation → Debugger audit ACCEPT (2 non-blocking notes) → commit

**Investigation report:** docs/investigations/2026-08-21-PANGO-WARNINGS-AND-SSL-RETRY.md
**Spec:** docs/specs/SPEC-PANGO-ATTR-VALIDATION.md
**Prior art:** docs/post-mortems/2026-07-31-PANGO-MARKUP-GUARD-POST-MORTEM.md (commit `898062a`) — this fix extends that guard to the sites it missed and closes the root cause it deferred.

---

## 1. Code Quality Grade: A− (91/100)

### Justification

The fix lands on the correct architecture: validate at the source (escaper) and defend at the sink (guard). The attribute allowlist is empirically derived — every entry probed against real Pango — and the adversarial audit earned its keep by catching an over-permissive entry (`bg`) that would have silently reintroduced the bug for that attribute, and a test that enshrined a cascade failure as correct behavior. The per-line diff fallback converts a whole-diff degradation into a single-line one. Deductions: the value-validation gap remains open (documented rather than solved — the right call for scope, but still a gap), and three of the eighteen new tests are decorative re-implementations that provide no regression coverage.

| Category              | Score | Notes |
|-----------------------|-------|-------|
| Correctness           | 18/20 | Root cause fixed and probe-verified; value-validation gap documented but open |
| Architecture compliance | 10/10 | utils/ stays GTK-free; guard pattern matches 898062a prior art |
| Test coverage         | 8/10 | 26 new tests, mutation-verified source-inspection tests; 3 decorative branch tests |
| Documentation         | 9/10 | Honest test docstrings; stale href comment fixed; allowlist rationale inline |
| Maintainability       | 10/10 | Allowlist is data, not logic; per-line fallback isolates blast radius |
| DX (Developer Exp.)   | 9/10 | Terminal warnings eliminated; content-loss symptom gone; fallbacks preserve raw text |
| **Total**             | **91/100** | **A−** |

Deducted points:
- 2 Correctness: value-validation gap (name-valid/value-invalid attrs still reach the guard)
- 2 Test coverage: `TestGuardBranchLogic`'s 3 tests re-implement the pattern instead of exercising production code

---

## 2. What's Good About the Code

1. **Source-level validation, not just another guard.** The allowlist fixes every current and future call site at once — any code path that escapes markup now cannot emit an unknown span attribute. The guards remain as defense-in-depth. Two layers, each with a clear contract documented in the test docstring. `utils/escaping.py:_SPAN_ALLOWED_ATTRS`.

2. **Empirically-derived allowlist with audit enforcement.** All 33 entries were probed against real Pango, and the adversarial audit re-probed all of them independently — which is how `bg` was caught (Pango rejects it; only `background` is valid). The deprecated `color` alias is included *with its rationale inline* ("used by ui/views/diff_card.py templates"), so the next person doesn't remove it as dead weight. `utils/escaping.py:48-61`.

3. **Per-line diff validation.** The naive guard degrades the entire joined diff markup to plain text when any line fails. Validating per line means one malformed line costs only its own color. Verified end-to-end: joined markup of [good+, bad-with-classname, good−] parses clean with the bad line rendered as text. `ui/views/feed_card.py:330-347`.

4. **Fallbacks show raw content, not escaped entities.** The chat_bubble code label falls back to `set_text(raw_content)` — real source code — rather than `set_text(code_markup)` which would display `&lt;` litter. Same discipline at file_tree (plain names). Users see degraded formatting, never garbage.

5. **Mutation-verified tests.** The auditor removed each guard and confirmed the source-inspection tests fail. This is the difference between regression coverage and test theater, and it was checked rather than assumed.

---

## 3. What's Bad About the Code

1. **Value-validation gap is open.** `<span foreground=noquotes>` passes the escaper (name is allowlisted) and only the downstream guard catches it — degrading a single block to plain text, or (in the narrow diff case where the raw fallback still contains the bad tag) collapsing to the outer guard. Solving it requires per-attribute value grammars in the escaper.
   - Evolution suggestion: add lightweight value-shape checks for the numeric/boolean attrs (size, rise, letter_spacing, weight, show, insert_hyphens, allow_breaks). ~half a day. The color/font attrs need real parsers — probably never worth it.

2. **Three decorative tests.** `TestGuardBranchLogic` re-implements the try/except pattern inside the test body and asserts on its own re-implementation. If all three production guards were deleted, those 3 tests would still pass. The 8 source-inspection tests carry the real coverage.
   - Evolution suggestion: extract a shared `pango_set_markup_safe(label, markup, fallback_text)` helper into `utils/gtk_safe_link.py`, use it at all five guarded sites, and point the branch tests at the helper. ~1 hour, also deduplicates the pattern six times over.

3. **`fgcolor`/`bgcolor` aliases not in the allowlist.** Pango accepts them; agents emitting legacy GTK-era markup would get fully escaped (safe, but formatting lost).
   - Evolution suggestion: two-line addition if ever observed in real agent output. Not speculative-add now.

---

## 4. Bugs Found During Audit

| # | Phase | Severity | Bug | Found by | Fixed by |
|---|-------|----------|-----|----------|----------|
| S1 | root cause | CRITICAL (prod) | `escape_for_pango` preserves unknown attributes on whitelisted tags → JSX in agent output reaches `set_markup` → Pango rejects → empty labels (silent content loss, 5 terminal warnings) | Supervisor (investigation, character-for-character reproduction) | Coder (attribute-name allowlist, Phase 1) |
| S2 | root cause | HIGH (prod) | Diff card joined all lines before one `set_markup` — one bad line degraded the whole diff to plain text | Supervisor (investigation) | Coder (per-line validation, Phase 1 send-back) |
| A1 | audit R1 | HIGH | `bg` in `_SPAN_ALLOWED_ATTRS` — Pango rejects it; over-permissive allowlist would have silently kept the bug alive for that attribute | Debugger (probe of all 33 entries) | Coder (removed + regression test) |
| A2 | audit R1 | CRITICAL (test) | `test_malformed_value_still_preserved` enshrined the cascade failure as correct behavior — asserted "we preserve bad markup" without acknowledging the guard then destroys all valid markup in the string | Debugger (probe vs. brief instruction to match reality) | Coder (test rewritten to assert the honest two-layer invariant) |
| N1 | audit R2 | MEDIUM (test) | `TestGuardBranchLogic`'s 3 tests are tautological — they re-implement the pattern and never touch production functions | Debugger (mutation experiment design) | Deferred (source-inspection tests carry coverage; helper extraction is §3.2) |
| N2 | audit R2 | LOW | Missing `gi.require_version('Pango', '1.0')` in file_tree.py — consistent with majority pattern, inconsistent with strict pattern; zero practical impact (no warning fires) | Debugger | Deferred (project-wide inconsistency, pre-existing) |

**6 items total: 2 production defects (S1, S2) + 2 audit-found blockers (A1, A2) fixed; 2 audit-found notes (N1, N2) deferred with rationale.** No bug compounded across phases. The Phase 1 send-back prevented both A1 and A2 from shipping.

### Bug patterns

| Pattern | Count | Description |
|---------|-------|-------------|
| `unvalidated-passthrough` | 1 | Escaper validated tag names but passed attributes through unchecked |
| `over-permissive-allowlist` | 1 | `bg` allowlisted without probing Pango acceptance |
| `test-enshrines-bug` | 1 | Test asserted the wrong invariant, converting a latent bug into a "verified" one |
| `whole-container-blast-radius` | 1 | Joined-string validation made one bad line destroy valid siblings |
| `tautological-test` | 1 | Branch tests exercised their own re-implementation, not production code |

---

## 5. Process: What Worked

1. **Character-for-character reproduction before any delegation.** Every error class from the terminal log was reproduced through the actual pipeline functions (`escape_for_pango` → `format_markdown` → `Pango.parse_markup`) before phase instructions were written. The Coder received exact failing inputs, not descriptions. Both phases landed correctly on the first attempt.
2. **Supervisor independent reproduction of audit findings.** When Debugger reported `bg` and the enshrining test, the Supervisor re-ran both probes personally before sending back. Both confirmed. This took two minutes and prevented a potential false-positive send-back — and given this project's incident history with unverified claims, the trust asymmetry favors verify-always.
3. **The audit caught what the brief caused.** The Phase 1 brief told Coder to "verify actual Pango behavior and match the test to reality" for the unquoted-value case. Coder wrote a passing test that asserted preservation. Debugger probed deeper and found the test enshrined a cascade failure. The adversarial layer caught a defect the delegation instructions themselves invited.
4. **Pre-existing-failure attribution via git stash.** When `test_file_tree_sort_filter.py` segfaulted, the Supervisor stashed the changes and re-ran — it segfaults on unmodified code too. Documented as environmental rather than burned as a send-back round.

---

## 6. Process: What Didn't Work

1. **Both `/clear` attempts failed ("tool loop is currently running").** Neither builder context was cleared before their first delegations. No correctness impact occurred (both Coders produced clean Discovery blocks proving they read current state), but the loop's own guidance says stale context risks outdated references on larger phases.
   - Lesson: `/clear` immediately after receiving a builder's final report, not bundled with the next delegation — the loop-running window is right after a response arrives.
2. **The brief invited the enshrining test.** FIX instruction said "match the test expectation to reality (do not assert what you did not run)" — Coder ran the probe, saw preservation, and asserted preservation, missing that *preservation itself* was the hazard. The instruction tested whether the probe was run, not whether the conclusion was sound.
   - Lesson: when delegating a "verify reality" instruction, also name the decision the verification should feed (here: "if Pango rejects it downstream, the test must document the guard contract, not assert preservation").
3. **Sandbox GTK segfaults continue to tax every loop.** Real widget construction segfaults at process exit; one file_tree suite segfaults entirely. Tests get designed around the limitation (source inspection, pure-Pango logic), which works but produces patterns like the decorative branch tests.
   - Lesson: unchanged from the 2026-07-31 post-mortem — extract pure-Python helpers so the logic is testable without widgets. Now there are two concrete candidates (`_validate_pango_markup`, `pango_set_markup_safe`).

---

## 7. What the Code Actually Does (End-User Impact)

1. **Feed cards containing JSX/TSX render their content instead of going blank.** Before: an agent message quoting `<span classname="field-error">…</span>` produced a card body that silently rendered empty (plus a terminal warning). After: the unknown attribute causes the whole tag to be escaped at the source, so the code renders as visible text. Code path: agent output → `feed_card._render_text_body` → `escape_for_pango` (tag escaped) → `Pango.parse_markup` OK → `set_markup`.

2. **One malformed diff line no longer erases the colors of valid lines.** A diff card where line 7 contains JSX now renders lines 1–6 and 8+ with their green/red coloring and line 7 as plain text. Before, all lines went plain. Code path: `feed_card.build_context_panel` → per-line `Pango.parse_markup` → failed line falls back to its own escaped text.

3. **Code blocks in chat survive highlighter regressions.** If `syntax_highlight.highlight()` ever emits malformed markup, the code block shows raw source instead of vanishing. Code path: `chat_bubble._build_code_from_markup` → parse fails → `set_text(raw_content)`.

4. **Terminal log volume drops.** The five `Gtk-WARNING: Failed to set text` errors collected over four days stop recurring; the failure mode they represented (empty labels) is replaced by graceful degradation.

---

## 8. Pre-Existing Issues Flagged (Not Caused by This Implementation)

1. **Value-validation gap** (see §3.1): name-valid/value-invalid attributes pass Layer 1. Verified during this loop (`<span foreground=noquotes>` preserved, Pango rejects). Documented in `test_valid_name_invalid_value_preserved_guard_handles`. Not solved by design.
2. **`gi.require_version('Pango', '1.0')` inconsistency project-wide**: 2 of 6 Pango-importing ui/ files declare it. Zero practical impact (no warning fires in this environment). Predates this work.
3. **Redundant `set_use_markup(True)` after `set_markup`** at `file_tree.py:1109`: cosmetic, dates to April 2026.
4. **Sandbox GTK segfaults** in `test_markdown.py` / `test_escaping.py` / `test_gtk_safe_link.py` / `test_file_tree_sort_filter.py`: documented since 2026-07-28; stash-probe verified pre-existing during this loop.
5. **SSL retry warnings from the same investigation** (`[ssl-retry] EOF occurred in violation of protocol`, `SSLV3_ALERT_BAD_RECORD_MAC` on openrouter.ai): verified working-as-designed — both tokens are in `RETRYABLE_SSL_ERRORS`, retries self-healed at attempt 1/3, mid-stream suppression prevents duplicate text. No action taken; none needed.

---

## 9. Evolution Suggestions (Tier 2+)

| Suggestion | Effort | Impact |
|------------|--------|--------|
| Extract `pango_set_markup_safe(label, markup, fallback_text)` into `utils/gtk_safe_link.py`; use at all 5 guarded sites; repoint branch tests at it | 1 hour | Deduplicates the pattern ×5; makes the 3 decorative tests real; enables direct unit testing of the guard decision |
| Extract `_validate_pango_markup(markup) -> bool` pure helper (carried over from 2026-07-31 post-mortem §9) | 30 min | Guard logic testable without GTK widgets |
| Value-shape checks for numeric/boolean span attrs (size, rise, weight, letter_spacing, show, insert_hyphens, allow_breaks) | Half day | Closes most of the value-validation gap; color/font values need real parsers — likely never worth it |
| Add `fgcolor`/`bgcolor` aliases to the allowlist if observed in real agent output | 10 min | Prevents over-escaping legacy markup |
| Project-wide `gi.require_version('Pango', '1.0')` normalization | 15 min | Consistency; silences PyGIWarning in strict mode |
| Headless-CI-safe GTK test harness (xvfb) so widget-construction tests stop segfaulting | Half day | Unblocks direct testing of make_safe_label-class code permanently |

---

## 10. Lessons Learned / Process Rules to Carry Forward

1. **Whitelisting a tag is not validating it.** Tag-name whitelists must be paired with attribute-name allowlists (and ideally value shapes), because Pango rejects unknown attributes on known tags exactly as hard as unknown tags.
   - Trigger: any escaper/sanitizer that preserves structured elements with attributes.
   - Action: enumerate the allowed attribute set empirically (probe the real parser, don't trust API-reference memory — `bg` came from exactly that confusion); escape the whole element on any unknown attribute.

2. **A passing test can enshrine a bug.** "Match the test to observed reality" is insufficient if the observed reality is itself the hazard. Tests must assert the *contract*, not the *current behavior*.
   - Trigger: writing a test whose assertion encodes behavior the surrounding system treats as a failure mode.
   - Action: for every new test, ask "if this assertion holds forever, is that good?" If no, rewrite the assertion or document why the hazardous behavior is accepted.

3. **Validate at the smallest independent unit.** Joined-string validation gives one bad element veto power over all good ones. Per-element validation localizes degradation.
   - Trigger: aggregating N formatted fragments into one markup blob before a single render call.
   - Action: validate per fragment; fall back per fragment; join after.

4. **Re-run critical probes yourself before routing audit findings.** Two-minute personal reproduction of `bg` and the enshrining test converted an audit claim into a verified fact before the send-back went out.
   - Trigger: auditor reports a blocker that will trigger a builder round-trip.
   - Action: reproduce first; send-back second.

---

## 11. Sign-off

- [x] Code committed: `6fda382` (Phase 1), `3e2cebc` (Phase 2) on main
- [x] Spec written: docs/specs/SPEC-PANGO-ATTR-VALIDATION.md
- [x] Investigation preserved: docs/investigations/2026-08-21-PANGO-WARNINGS-AND-SSL-RETRY.md
- [x] All verification commands run and outputs pasted in-loop (probe scripts, pytest runs, mutation experiments)
- [x] Pre-existing failures attributed (git-stash probe for test_file_tree_sort_filter; documented environmental segfaults)
- [x] Deferred items documented with rationale (N1 decorative tests, N2 require_version, value-validation gap)
- [x] Captain notified with summary (this document serves as the summary)
- [ ] Push to origin (pending Captain approval)
