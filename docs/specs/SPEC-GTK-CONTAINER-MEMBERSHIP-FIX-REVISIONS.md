# Spec Revision Required — Debugger Audit Findings

Debugger audited docs/specs/SPEC-GTK-CONTAINER-MEMBERSHIP-FIX.md using
prompts/adversarialDebugger.md. Production code changes are SOUND. All issues
are in the spec's test layer. Fix these in the spec:

## CRITICAL

### BUG #1 — mock-the-symptom
Group A tests (3 "bug class" tests) mock the TypeError side-effect rather than
reproducing the real bug. This proves nothing about actual GTK behavior.
**Fix:** Rewrite Group A as a SINGLE pure-Python test using a `FakeGtkBoxNoContains`
class that mimics GTK4's lack of `__contains__`/`__iter__` (raises TypeError on
`widget in fake_box`). This reproduces the real bug class without mocking the
symptom.

### BUG #2 — fake-incompatible-with-new-helper
The spec's chosen helper uses `container.get_first_child()` /
`child.get_next_sibling()`. But `tests/test_chat_render_handler.py::FakeChatBox`
does NOT implement these methods. Result: the production helper will raise
`AttributeError: 'FakeChatBox' object has no attribute 'get_first_child'` in
ALL 12 TestPhase3Streaming + TestPhase4EventCards tests, breaking the suite
the spec claims will pass.
**Fix:** Add a "Test Fakes" subsection under §3.3 mandating that `FakeChatBox`
be updated to implement `get_first_child()` / `get_next_sibling()` walking over
its `_children` list. Without this, the existing tests cannot exercise the new
helper.

## HIGH

### BUG #3 — stale-test-rationale
`test_start_streaming_twice_idempotent` has an assertion + comment whose
rationale is now stale (describes the old broken behavior as the reason for
the test).
**Fix:** Update the assertion and comment to reflect the fixed behavior.

### BUG #4 — loose-anchor-test
Test 4 in Group C (static regression check) uses a regex anchor that is too
loose — it could match unrelated `in` patterns in the file, giving false
confidence.
**Fix:** Narrow the regex to anchor specifically on the `_dispatch` method body
or the exact `sb.container` / `self._card_container` membership patterns, not
a generic `in` occurrence.

## MEDIUM (address if straightforward)

### BUG #5 — c-callback-exception-leak
The `_dispatch` try/except wrapper should document whether KeyboardInterrupt /
SystemExit are intentionally re-raised or just caught. Either add a comment
explaining the choice, or explicitly re-raise BaseException subclasses.
**Fix:** Add `except (KeyboardInterrupt, SystemExit): raise` before the generic
`except Exception`, with a one-line comment.

### BUG #6 — scope-silence
Other handlers besides chat_render_handler have `_dispatch` methods (e.g.
`chat_handler._dispatch`). The spec only fixes one. That's fine for scope, but
the spec should LIST these as deferred scope so the implementer doesn't wonder.
**Fix:** Add a "Deferred scope" subsection listing the other `_dispatch` sites.

### BUG #10 — over-application-of-rule
The spec duplicates the helper across chat_render_handler.py and feed_tab.py
citing §8.6. But §8.6 forbids handler-to-handler imports, NOT imports from
`utils/`. A pure GTK utility could live in `utils/gtk_containers.py` and be
imported by both files.
**Fix:** Either (a) move helper to `utils/gtk_containers.py` and import from
both — simpler, avoids drift; OR (b) keep duplicated but add a comment in BOTH
files explaining the §8.6 rationale. Supervisor leans toward (a) — it's cleaner
and utils/ is the natural home.

## LOW

### BUG #7 — off-by-estimate
Line count deltas in the spec are slightly off. Recount.

### BUG #9 (advisory) — edge-case-completeness
No real bug. Helper is correct. No action.

### BUG #11 — verification-step-impossible
Spec §6 Step 1 says to verify by running tests, but those tests break until
FakeChatBox is updated (BUG #2). Reorder: update FakeChatBox BEFORE the step 1
verification.

### BUG #12 — convention-undocumented
The defensive logging in `_dispatch` is a new convention. Optional: add a
one-line note to ARCHITECTURE.md. Advisory only.

## Summary of required spec changes
1. Rewrite Group A → single FakeGtkBoxNoContains test (BUG #1)
2. Add Test Fakes subsection: FakeChatBox must implement sibling-walk API (BUG #2)
3. Fix stale assertion/comment in test_start_streaming_twice_idempotent (BUG #3)
4. Narrow Test 4 regex anchor (BUG #4)
5. Add BaseException re-raise + comment to _dispatch wrapper (BUG #5)
6. Add Deferred scope subsection listing other _dispatch sites (BUG #6)
7. Decide on utils/gtk_containers.py vs duplication (BUG #10)
8. Reorder §6 steps: FakeChatBox update before verification (BUG #11)
