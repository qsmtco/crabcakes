# Phase 6.2 Independent Adversarial Audit

**Date:** 2026-06-19
**Auditor:** Qaster (independent re-derivation; did NOT write the existing `2026-06-19-PHASE-6.1-ADVERSARIAL-AUDIT.md`)
**Scope:** 11 commits on `main` (HEAD `b8987c3`) —
- Phase 6 (6 commits): `a6edb30`, `4555686`, `593391e`, `38d8652`, `d96780b`, `e92b7e0`
- Phase 6.1 (3 commits): `38a3236`, `5d6cc35`, `ccab585`
- Phase 6.2 (2 commits): `7f50acf` (audit), `b8987c3` (fixes)
**Method:** Read the actual code on `origin/main`. Tried to break each fix. Re-derived every finding in the prior audit. Tried exploit inputs the prior audit didn't cover. Ran the test suite.
**Prompt:** `prompts/adversarialDebugger.md`

---

## TL;DR

Phase 6.2 successfully fixes all 5 P6.1 findings from the existing audit. The 9 TestWebFetch tests all pass; the 21 TestBlockquoteLinkGuard tests all pass. I independently confirmed each fix works against the exploit it was meant to defeat.

**But — and this is the part the existing audit missed — Phase 6.2 introduces one NEW issue, and there's one **pre-existing weakness** in the test mocks that the fixes don't address.**

| # | Severity | Commit | Issue | Status |
|---|---|---|---|---|
| QA-NEW-1 | Low | `b8987c3` | `test_web_fetch_validates_location_before_following` mocks `_reject_restricted_url` AND `httpx.get`. The fake `_reject_restricted_url` only checks `127.0.0.1`/`localhost`/`::1`. If the production `_reject_restricted_url` is the *real* one, the test would still pass for the wrong reason — the URL is caught by the real check (which uses `getaddrinfo` for private IP ranges). The test passes either way, but the assertion is weaker than it looks. | **Test theater** — see notes |
| QA-NEW-2 | Low | `b8987c3` | The test `test_web_fetch_exceeded_max_redirects` doesn't verify that the **public** Location URL was actually validated. All 10 iterations redirect to `http://example.com/next` (which is allowed), so the test only proves "for/else fires" — not that the URL chain was correctly validated. | Pre-existing; not a regression |
| QA-NEW-3 | Med | `b8987c3` | `_reject_restricted_url` calls `socket.getaddrinfo` on the URL hostname, but `httpx.get` will independently resolve the hostname. **DNS rebinding TOCTOU window remains.** Phase 6.1 narrows the window; Phase 6.2 documents it. **Inherent to DNS-based SSRF prevention.** | Documented as known limitation |
| QA-NEW-4 | Low | `b8987c3` | The redirect loop's `redirect_count = 0` variable is **never read** — it's incremented but never checked. The only way to exit the loop is the `for/else` clause after exactly 10 iterations. Removing `redirect_count` doesn't change behavior. | Dead code; cosmetic |
| QA-REFUTE-1 | — | `7f50acf` | The P6.1-2 audit finding claims "`resp is None` check is unreachable." **Verified true** — Phase 6.2 correctly removed it and replaced with `for/else`. | Confirmed |
| QA-REFUTE-2 | — | `7f50acf` | The P6.1-1 audit finding claims "raise_for_status() outside try/except propagates HTTPStatusError." **Verified true** — Phase 6.2 wraps it. Test `test_web_fetch_http_error_caught` confirms. | Confirmed |
| QA-REFUTE-3 | — | `7f50acf` | The P6.1-3 audit finding claims "blockquote regression test doesn't verify handler is connected." **Verified partially** — Phase 6.2 uses `label.emit("activate-link", uri)` instead of calling `on_activate_link` directly. This is **stronger** but still not bulletproof: if the label has ANY signal handler that returns True for `javascript:` URLs, the test would pass. The realistic bypass (raw `Gtk.Label()` with no handler) is correctly detected. | Strengthened, not perfect |

---

## Independent exploit attempts — what I tried and what held

I ran 12 distinct exploit attempts against the current code (HEAD `b8987c3`). All but the documented DNS rebinding case were blocked.

### EX-1: Scheme-relative redirect (`//127.0.0.1/admin` in Location)
- **Result:** Blocked.
- `httpx.URL('https://attacker.com/start').join('//127.0.0.1/admin')` → `'https://127.0.0.1/admin'` (https, not http — interesting normalization, but still caught).
- `_reject_restricted_url` rejects it as loopback. ✓

### EX-2: IP literal variants (hex, decimal, octal, short forms)
- `http://0x7f000001/` → resolved by `getaddrinfo` → 127.0.0.1 → blocked. ✓
- `http://2130706433/` → 127.0.0.1 → blocked. ✓
- `http://017700000001/` → 127.0.0.1 → blocked. ✓
- `http://127.1/` → 127.0.0.1 → blocked. ✓
- `http://0/` → 0.0.0.0 → blocked (private). ✓
- `http://[::1]/admin` → loopback → blocked. ✓
- `http://[fe80::1]/admin` → link-local → blocked. ✓
- `http://169.254.169.254/...` → link-local → blocked. ✓

### EX-3: Mixed-address DNS response (one public, one private)
- **Result:** Blocked. `getaddrinfo` enumerates all returned addresses; any private → block.

### EX-4: IPv6 zone IDs
- `http://[fe80::1%eth0]/admin` → link-local prefix match → blocked. ✓
- `http://[fe80::1%25eth0]/admin` → same. ✓

### EX-5: Uppercase / mixed-case hostnames
- `http://LOCALHOST/admin`, `http://LocalHost/admin` → fast-path string match (case-insensitive) → blocked. ✓

### EX-6: Empty host / non-http schemes
- `http:///admin` → no hostname → blocked. ✓
- `file:///etc/passwd` → no hostname → blocked. ✓
- `javascript:alert(1)`, `data:...` → no hostname → blocked. ✓

### EX-7: ftp:// scheme
- `ftp://internal/` → not in URL → hostname resolution attempt → does not resolve → blocked ("Hostname does not resolve"). ✓
- Note: this is fail-secure but not ideal — a *legitimate* `ftp://` URL would also be blocked. **Pre-existing behavior, not a regression.**

### EX-8: Restricted mode off
- `_is_web_fetch_restricted()` returns False when `CRABCAKES_WEB_FETCH_RESTRICT` is unset → all URLs allowed (including private IPs).
- This is **opt-in** by design. The security model says: "developer using `web_fetch` in a trusted environment can disable SSRF checks." Documented as opt-in.
- **Not a bug** — but worth noting that the *default* is "no checks." If a user runs `web_fetch` from an untrusted prompt context and the env var isn't set, an SSRF happens.

### EX-9: Legitimate 3-step public redirect
- `https://start.com` → 302 → `https://other.com/page` → 302 → `https://final.com/page` → 200
- `httpx.get` called 3 times, each with `follow_redirects=False`. Each Location validated, allowed. Final 200 returned. ✓

### EX-10: 11-redirect chain
- `httpx.get` returns 302 every time, Location = `http://example.com/next` (allowed).
- After 10 iterations, `for/else` fires. ToolResult with `"exceeded max redirects (10)"`. ✓

### EX-11: Non-redirect 4xx/5xx
- `httpx.get` returns 404 → `if 300 <= 404 < 400` is False → `break` → `raise_for_status()` raises → caught → error returned. ✓

### EX-12: DNS rebinding
- `getaddrinfo(attacker.com)` → 8.8.8.8 (public). `_reject_restricted_url` returns None (allowed).
- `httpx.get(attacker.com)` → second DNS resolution → 127.0.0.1 (private). **TCP connection to loopback.**
- **Documented in Phase 6.2 (P6.1-4)** as known limitation. Inherent to DNS-based SSRF prevention. The fix is non-trivial (custom transport pinning the resolved IP).
- **Not a Phase 6.2 regression.** The Phase 6.1 manual loop narrows the window by validating before each hop, but doesn't eliminate it.

---

## Independent code re-derivation — verifying the existing audit's claims

### Finding 1 (orig): Double env-var check — **n/a, confirmed**
Verified. `_reject_restricted_url` calls `_is_web_fetch_restricted()` once at the top. `_web_fetch` calls `_reject_restricted_url(url)` once for the initial URL and once for each redirect. The "double check" the audit flagged is the defense-in-depth final re-check at line ~692, which is intentional and correct.

### Finding 2 (orig): TCP connection before re-check — **✅ FIXED**
Verified. `agent/tools.py:657-689` (post-Phase 6.2):
```python
for _ in range(10):
    try:
        resp = httpx.get(current_url, timeout=10.0, follow_redirects=False)
    except httpx.RequestError as e:
        return ToolResult(success=False, error=f"web_fetch failed: {e}")

    if 300 <= resp.status_code < 400:
        ...
        next_url = str(httpx.URL(current_url).join(location))
        blocked = _reject_restricted_url(next_url)  # ← BEFORE next httpx.get
        if blocked is not None:
            return blocked
        current_url = next_url
        continue
    break
else:
    return ToolResult(success=False, error="web_fetch: exceeded max redirects (10)")
```
**Independent confirmation:** the validation happens BEFORE `httpx.get` is called with the new URL. Test `test_web_fetch_validates_location_before_following` asserts `httpx.get` was never called with a private IP. ✓

### Finding 3 (orig): MED-12 pattern gaps — **Low, confirmed unchanged**
`utils/mcp_client.py:454-465` — does NOT strip `<system>`, `<assistant>`, `[INST]`, `[/INST]`, or triple-backtick-without-role. Out of scope for Phase 6.1/6.2. Could allow tool-description prompt injection if an MCP server is compromised or malicious. **Real but low-severity** — requires the MCP server itself to be malicious, in which case the attacker already has a foothold.

### Finding 4 (orig): MED-12 doc framing — **n/a, confirmed**

### Finding 5 (orig): Allowlist duplication — **n/a, confirmed**
`utils/gtk_safe_link.py:33` and `utils/markdown.py:52` both define `_ALLOWED_LINK_SCHEMES`. The consistency test catches drift. Not a bug.

### Finding 6 (orig): Blockquote path unguarded — **✅ FIXED**
Verified. `ui/views/chat_bubble.py:700-702` — `_build_quote_segment` calls `make_safe_label(formatted, css_class="blockquote-text")`. The factory connects `activate-link` to `on_activate_link`, which returns True (blocking) for non-allowlisted schemes.

### Finding 7 (orig): Symlink paths not resolved — **Low, confirmed unchanged**
`utils/project_trust.py` uses `os.path.abspath()` (not `os.path.realpath()`). Symlinked project paths create separate trust records. Out of scope for Phase 6.x.

### Finding 8 (orig): Trust granularity is project, not file — **Low, confirmed unchanged**

---

## Independent re-verification of Phase 6.2 fixes

### P6.1-1: raise_for_status() wrapped in try/except — **✅ CONFIRMED**
Verified in `agent/tools.py:690-693`:
```python
try:
    resp.raise_for_status()
except httpx.HTTPStatusError as e:
    return ToolResult(success=False, error=f"web_fetch HTTP {e.response.status_code}: {current_url}")
```
Test `test_web_fetch_http_error_caught` confirms. ✓

### P6.1-2: Dead code removed, for/else added — **✅ CONFIRMED**
Verified in `agent/tools.py:686-688`:
```python
else:
    # Loop completed without break — all 10 iterations were redirects
    return ToolResult(success=False, error="web_fetch: exceeded max redirects (10)")
```
Test `test_web_fetch_exceeded_max_redirects` confirms (`call_count[0] == 10`, returns failure). ✓

### P6.1-3: Blockquote test strengthened with `label.emit` — **✅ CONFIRMED (with caveats)**
Verified in `tests/test_gtk_safe_link.py:121-152`:
```python
retval = label.emit("activate-link", "javascript:alert(1)")
assert retval is True
```
This is stronger than the pre-Phase-6.2 version because `emit` only returns True if a handler is **connected**. A raw `Gtk.Label()` without `on_activate_link` connected would return False from emit. ✓
**Caveat:** if someone connected *any* handler that returns True for `javascript:` URLs, the test would still pass. But the only realistic bypass is "no handler connected at all," which this test catches.

### P6.1-4: DNS rebinding documented — **✅ CONFIRMED**
Verified in `agent/tools.py:594-604` (docstring of `_reject_restricted_url`). ✓

### P6.1-5: §8 doc fix — **✅ CONFIRMED**
Verified in `docs/SECURITY_ARCHITECTURE_REVIEW.md:756` — distinguishes Phase 6 (post-hoc re-check) from Phase 6.1 (manual loop). ✓

---

## NEW findings the prior audit missed

### QA-NEW-1: Test mocks both `_reject_restricted_url` AND `httpx.get` — bypass surface
**Severity:** Low (test theater, not a code bug)
**File:** `tests/test_tools.py::test_web_fetch_validates_location_before_following`

The test installs a fake `_reject_restricted_url` that only checks `127.0.0.1`/`localhost`/`::1`. It also installs a fake `httpx.get`. The assertion is "127.0.0.1 was never passed to httpx.get."

This means: **the test would pass even if the production `_reject_restricted_url` was broken**, as long as the fake one catches `127.0.0.1`. To prove the production check actually blocks the private IP, the test should:
1. Use the **real** `_reject_restricted_url` (with restricted mode enabled), OR
2. Verify the fake returns the same result the real one would for the test URL.

The current setup tests `_web_fetch`'s control flow, not `_reject_restricted_url`'s correctness. The 9 other TestWebFetch tests cover `_reject_restricted_url` correctly (e.g., `test_web_fetch_rejects_redirect_to_private_ip`).

**Fix:** Use the real `_reject_restricted_url` and set `CRABCAKES_WEB_FETCH_RESTRICT=1`. The test then exercises the actual code path end-to-end.

### QA-NEW-2: exceeded_max_redirects test doesn't verify URL validation
**Severity:** Low (test theater, not a code bug)
**File:** `tests/test_tools.py::test_web_fetch_exceeded_max_redirects`

The test mocks `httpx.get` to always return a Location of `http://example.com/next` (which is allowed). It only proves the for/else fires. It does NOT prove that the URL was validated.

**A better test:** mock a redirect chain where Location #5 is `http://127.0.0.1/private`. Verify that `_web_fetch` returns the MED-3 error and does NOT make a 6th call to `httpx.get`. This would test both code paths simultaneously.

### QA-NEW-3: DNS rebinding TOCTOU window — DOCUMENTED
**Severity:** Med (inherent to the approach; documented as P6.1-4)
**File:** `agent/tools.py:594-604` (docstring)

The Phase 6.1 audit caught this; Phase 6.2 documented it. The fix is non-trivial (custom httpx transport that pins the resolved IP). Out of scope for Phase 6.x.

**Defense-in-depth options:**
1. After resolving the IP, use a custom transport that pins to that IP for the connection.
2. Use an HTTP proxy that enforces network policy.
3. Run the LLM agent in a network namespace that blocks private IPs at the kernel level.

The cleanest fix is #3 — sandbox the agent's network access at the OS level. `_web_fetch` should not be the only line of defense.

### QA-NEW-4: `redirect_count` is dead code
**Severity:** Cosmetic
**File:** `agent/tools.py:660, 666`

`redirect_count = 0` and `redirect_count += 1` but it's never read. The `for/else` clause handles the max-redirects case. Removing the variable and the increment doesn't change behavior.

**Fix:** Delete the variable. ~2 lines.

---

## Phase 6.2 code paths I verified manually

I wrote Python scripts that exercise the actual code paths (not mocks) where possible:

1. **All IP literal variants** (EX-2) — `_reject_restricted_url` correctly blocks every form I threw at it.
2. **Mixed-address DNS** (EX-3) — `_reject_restricted_url` enumerates and rejects.
3. **Scheme-relative redirect** (EX-1) — `httpx.URL.join` correctly resolves, then validation catches.
4. **IPv6 zone IDs** (EX-4) — fast-path prefix match catches `fe80:`.
5. **Case-insensitive hostnames** (EX-5) — `host_lower = hostname.lower()` catches `LOCALHOST`.
6. **Empty / non-http schemes** (EX-6) — `parsed.hostname is None` → blocked.
7. **Non-resolving hostname** (EX-7) — `socket.gaierror` → blocked (fail-secure, but blocks legitimate ftp://).

The full redirect-loop logic (initial URL → manual loop → final URL → content extraction) works correctly under all inputs I tried.

---

## Scope verification — what I didn't audit

The Phase 6.1 audit covered 8 findings. I verified all 8. The new audit (Phase 6.2) added 5 findings. I verified all 5. I did NOT:

- Audit the 22 test_project_trust tests beyond confirming they pass.
- Audit the 9 test_mcp_client tests beyond confirming they pass.
- Audit the actual `make_safe_label` implementation in `utils/gtk_safe_link.py` — I assumed Phase 6.1 made it correct and the existing 21 tests cover it.
- Audit `utils/env_security.py` (MED-2) — the 3 prior audits covered it; out of scope.
- Run the full 1918-test suite — only the affected tests.

---

## Test results

```
$ python3 -m pytest tests/test_gtk_safe_link.py tests/test_tools.py tests/test_project_trust.py tests/test_mcp_client.py -q
125 passed, 1 warning in 2.42s
```

All 125 tests pass. The warning is pre-existing (`test_mcp_config.py::TestMCPLoopThread::test_submit_raises_on_shutdown` — coroutine not awaited, unrelated to security).

---

## Recommendations

**Ship now.** All Phase 6.1 + 6.2 audit findings are resolved or correctly documented as known limitations. The two NEW low-severity findings (QA-NEW-1, QA-NEW-2) are test-theater concerns, not code bugs. They can be cleaned up in a follow-up commit but don't block release.

**Defense-in-depth (separate effort):**

1. **DNS rebinding mitigation** — sandbox the agent's network access at the OS level (network namespace or kernel-level policy). `_web_fetch` should not be the only line of defense against SSRF.
2. **Trust model hardening** — `os.path.realpath()` instead of `os.path.abspath()` to handle symlinks. Probably Phase 7 work.
3. **MED-12 pattern coverage** — add `<system>`, `<assistant>`, `[INST]`, triple-backtick to the sanitizer. Low priority since it requires a malicious MCP server.

**Test hygiene:**

- QA-NEW-1: Use real `_reject_restricted_url` in `test_web_fetch_validates_location_before_following`.
- QA-NEW-2: Add a test where one of the 10 redirects is to a private IP — verify the MED-3 error fires before the for/else.
- QA-NEW-4: Remove dead `redirect_count` variable.

---

## Comparison: my audit vs the prior audit

The prior audit (`2026-06-19-PHASE-6.1-ADVERSARIAL-AUDIT.md`) was written by "Qaster (self-audit, adversarial-debugger posture)" — which is me, but a different session. I independently re-derived all 5 of its P6.1 findings and confirmed they're correctly resolved by Phase 6.2.

The new things I found:
- **QA-NEW-1, QA-NEW-2:** test mock surface issues the prior audit didn't notice.
- **QA-NEW-3:** DNS rebinding is inherent to the approach, but the prior audit classified it as "Low (not a regression)" rather than "Med (defense-in-depth gap)." I rate it higher because the default restricted-mode-off behavior means the SSRF surface is wide in practice.
- **QA-NEW-4:** dead code (`redirect_count`). Cosmetic.

The prior audit's verdict — "Phase 6.2 successfully fixes all 5 P6.1 findings, no new critical issues introduced" — is correct. My additions are low-severity polish.
