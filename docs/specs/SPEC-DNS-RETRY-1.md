# SPEC: DNS-RETRY-1 — Cover transient DNS failures in the LLM retry layer

**Date:** 2026-09-12
**Author:** Supervisor (per PM go; investigation at docs/investigations/2026-09-12-debugger-turn-dns-resolution-failure.md)
**Status:** Draft — for implementation
**Depends on:** none
**Target branch:** main

> Architecture compliance: `agent/llm/streaming.py` is the existing SSL/network retry infrastructure (see its module docstring + SPEC-SSL-RETRY-FIX.md Layer 1). No new modules, no provider changes, no handler changes.

## 1. Problem

`urlopen_with_ssl_retry` (agent/llm/streaming.py:278) retries SSL errors and
TCP-level errors (`ConnectionResetError`, `BrokenPipeError`, `TimeoutError`) but
NOT DNS failures. On 2026-09-12 a transient `socket.gaierror [Errno -3]`
(EAI_AGAIN — "Temporary failure in name resolution") killed a live Debugger
turn mid-audit. urllib wraps the gaierror in `URLError`; the existing
exponential backoff (MAX_SSL_RETRIES=3, 500ms × 2^attempt) never fired.
The whole turn was lost to a ~2-second resolver hiccup.

## 2. Changes by File

### 2.1 `agent/llm/streaming.py`

**Edit A — retryable types:** add `socket.gaierror` to the exception handling
of `urlopen_with_ssl_retry` (both the direct-catch and the URLError-unwrap
path via `is_retryable_ssl_error` — read both functions first and extend the
mechanism that actually classifies; do not duplicate logic).

**Edit B — classification:** a `gaierror` is retryable when raised during
name resolution (transient resolver failure). Simplest correct rule: ALL
`gaierror`s are retryable within the existing budget (max 3 attempts,
existing backoff). Rationale: permanent resolution failures (NXDOMAIN,
errno -2) also burn only 3 × ~1.5s worst-case before propagating unchanged —
acceptable cost vs. losing a whole agent turn; keeps the classifier simple.
Document this trade-off in the function docstring.

**Edit C — docstrings:** update `urlopen_with_ssl_retry` and
`is_retryable_ssl_error` docstrings + module docstring list to name DNS
gaierror as retryable. Update the docstring's numbered exception list
(currently 3 numbered types).

### 2.2 `tests/test_llm_streaming.py` (or the suite covering streaming.py — locate it)

**Edit D — new tests (RED FIRST):**
1. `test_urlopen_retries_transient_dns_gaierror` — mock `urllib.request.urlopen`
   to raise `URLError(socket.gaierror(-3, "Temporary failure in name resolution"))`
   twice then succeed → assert success returned and urlopen called 3 times
   (2 retries + initial). Patch `time.sleep` to keep the test fast.
2. `test_urlopen_dns_retry_budget_exhausts` — urlopen always raises the same
   → assert the URLError propagates unchanged after MAX_SSL_RETRIES+1 calls.
3. `test_direct_gaierror_retried` — raw `socket.gaierror(-3, ...)` (not
   URLError-wrapped) → retried.

## 3. Acceptance Criteria

- [ ] 3 new tests RED on current code, GREEN after Edit A/B (paste both outputs)
- [ ] Existing streaming/SSL-retry suite green (locate: grep -rl "urlopen_with_ssl_retry" tests/)
- [ ] pyflakes: 0 undefined names on agent/llm/streaming.py
- [ ] Full-suite failure set unchanged (41 baseline)

## 4. Out of scope

- Provider fallback on connection errors (agent/runtime.py:1621 fires on
  KB_OUT_OF_SCOPE only) — separate unit
- The 4 pre-existing test_runtime_fallback failures
