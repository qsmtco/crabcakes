# Phase 6 Adversarial Audit

**Date:** 2026-06-19
**Auditor:** Qaster (self-audit, adversarial-debugger posture)
**Scope:** 6 Phase 6 commits on `main` (HEAD `e92b7e0`)
**Method:** Each commit's claims verified against actual code; gaps hunted.

---

## TL;DR

Phase 6 shipped real work — 6 commits, ~1,200 lines added, 60 new tests, 368/368 pass. **But the doc claim that all 7 previously-partial findings are now ✅ is not entirely accurate.** I found 8 real issues across the 6 commits, ranging from "test-only coverage gap" to "real shipping bug":

| # | Severity | Commit | Issue |
|---|---|---|---|
| 1 | n/a | `a6edb30` (MED-3) | Double env-var check (cosmetic) |
| 2 | **Med** | `a6edb30` (MED-3) | **TCP connection to private host is made before re-check** |
| 3 | Low | `4555686` (MED-12) | Pattern list misses Chinese directives, XML system tags, ChatML `[INST]` |
| 4 | n/a | `4555686` (MED-12) | Doc understates the sanitization gap (defense-in-depth framing OK) |
| 5 | n/a | `593391e` (HIGH-6) | Allowlist duplication (markdown vs gtk_safe_link); not single-source |
| 6 | **Med** | `593391e` (HIGH-6) | **HIGH-6 missed the blockquote path** (`_build_quote_segment` at `chat_bubble.py:700`) |
| 7 | Low | `d96780b` (HIGH-5) | Symlink paths not resolved; `/foo` symlinked to `/bar` creates two trust records |
| 8 | Low | `d96780b` (HIGH-5) | Trust is per-project, not per-(project, file); new agent-role file after trust isn't re-prompted |

**Test status:** 368/368 pass. **No regressions** — but the tests don't cover the gap in finding 6 (blockquote).

**Recommendation:** Either fix finding 2 and 6 in a Phase 6.1 (small), or update the doc to acknowledge them as known gaps. Don't ship a new doc claim that HIGH-6 is "fully shipped" without addressing finding 6.

---

## Audit details

### Finding 1: MED-3 — double env-var check (cosmetic)

**Commit:** `a6edb30`
**File:** `agent/tools.py:648-660`

```python
def _validate_response(resp: httpx.Response) -> ToolResult | None:
    if not _is_web_fetch_restricted():
        return None
    for hop_url in [str(resp.url)] + [str(h.url) for h in resp.history]:
        blocked = _reject_restricted_url(hop_url)
        ...
```

`_reject_restricted_url` already calls `_is_web_fetch_restricted()` internally — so we check the env var twice. Not a bug, just wasted work.

**Severity:** n/a (cosmetic)
**Fix:** Inline the body of `_reject_restricted_url` into `_validate_response` after the outer check, OR remove the inner check from `_reject_restricted_url` and require callers to gate it.

---

### Finding 2: MED-3 — TCP connection to private host before re-check

**Commit:** `a6edb30`
**File:** `agent/tools.py:663`

```python
resp = httpx.get(url, timeout=10.0, follow_redirects=True)
resp.raise_for_status()
redirected_blocked = _validate_response(resp)
```

The re-check happens **after** `httpx.get` returns. By then, `httpx` has already followed the redirect(s) and made TCP connections to every hop in the chain — including any private/loopback hosts.

The test passes because the test patches `httpx.get` to return a fake response that doesn't actually make network calls. In production, **a malicious public URL can still trigger TCP connections to internal hosts** (port-scan side channel, internal-only service that has side effects on connect, etc.).

**Severity:** Med — the data isn't exfiltrated (response is dropped), but the connection itself is a network-level exposure.
**Fix:** Set `follow_redirects=False`, then handle redirects manually:
1. Issue `httpx.get(url, follow_redirects=False)`.
2. If `3xx` and `Location` header present, validate `Location` URL via `_reject_restricted_url` *before* following.
3. Loop until final response or max redirects.
4. Run the final response through `_validate_response` (defense-in-depth in case the chain changes).

This requires ~30-40 lines of code change + a new test that verifies the connection is *not* made to the blocked host (using a mock that asserts `httpx.get` is called with the expected URL).

---

### Finding 3: MED-12 — sanitization pattern gaps

**Commit:** `4555686`
**File:** `utils/mcp_client.py:451-465` (the `_INJECTION_PATTERNS` tuple)

The patterns catch:
- ✅ Markdown role headers (`system:`, `assistant:`, `user:`)
- ✅ Fence-breaks with role keywords (` ```system `)
- ✅ Anthropic role tokens (`<|...|>`)
- ✅ Control chars / escapes
- ✅ English directive phrases ("ignore all previous", "act as if")

The patterns miss:
- ❌ **Multi-lingual directives** (`忽略之前的所有指令`, `oublie les instructions précédentes`, ...)
- ❌ **XML role tags** (`<system>`, `<assistant>`, `<user>` — Anthropic Messages API accepts these)
- ❌ **ChatML tokens** (`[INST]`, `[/INST]` — Mistral/Llama format)
- ❌ **Llama-3 special tokens** (`<|start_header_id|>`, `<|end_header_id|>`)

**Severity:** Low — this is defense-in-depth; the HIGH-5 `<untrusted-project-data>` fence wraps *tool results* (the actual data), not descriptions. The description is one-shot injected into the system prompt; the model still treats it as untrusted. So even a malicious description that slips through is bounded by the fence's framing.
**Fix:** Add 2-3 more patterns (XML system tags, ChatML tokens) for cheap coverage. Multi-lingual is hard — skip unless we see evidence of bypass.

---

### Finding 4: MED-12 — doc framing

**Severity:** n/a
**Note:** The Phase 6 doc claims `_sanitize_tool_description` "strips prompt-injection patterns" — technically true, but the *coverage* is narrow (English-only directives, no XML/ChatML tags). The doc should add "(defense-in-depth; HIGH-5 fence on tool results is the primary defense; description sanitization is best-effort coverage of obvious patterns)".

---

### Finding 5: HIGH-6 — allowlist duplication

**Commit:** `593391e`
**Files:** `utils/gtk_safe_link.py:33` and `utils/markdown.py:52`

Both files define `_ALLOWED_LINK_SCHEMES = frozenset({"http", "https", "mailto"})`. The Phase 6 commit message claims a "consistency check" test ensures they match, but **the consistency check is in the test file** (`tests/test_gtk_safe_link.py`) — it's a runtime assertion, not a build-time guarantee. If someone updates `utils/markdown.py` first, the tests will fail loudly. If someone updates `utils/gtk_safe_link.py` and the test isn't run, drift is silent.

**Severity:** n/a — the test catches drift at test-time.
**Fix (optional):** Have `utils/gtk_safe_link.py` import the constant from `utils/markdown.py` instead of redefining it. Single source of truth.

---

### Finding 6: HIGH-6 — blockquote path is unguarded (REAL SHIPPING BUG)

**Commit:** `593391e`
**File:** `ui/views/chat_bubble.py:700-704`

```python
def _build_quote_segment(seg: dict) -> Gtk.Widget:
    ...
    escaped = escape_for_pango(content)
    formatted = format_markdown(escaped)    # ← renders <a href="..."> tags
    label = Gtk.Label()                     # ← raw Gtk.Label, no guard
    label.set_markup(formatted)             # ← user can click javascript: links
    ...
```

This is a HIGH-6 regression. The commit wired `make_safe_label` into 3 sites (`_build_text_segment`, the file-read bubble, and the chat-render text path) but missed `_build_quote_segment`. Blockquotes with markdown links will emit clickable `<a>` tags without an activate-link handler — meaning a markdown link with `javascript:` or `file://` scheme would be clickable.

**Severity:** Med — HIGH-6 regression. In a chat bubble containing a blockquote with a markdown link, clicking the link will navigate to the URL (including `javascript:` schemes, since GTK's `<a href="javascript:...">` is executed by the default handler).
**Exploit:** An attacker who controls text that reaches the chat bubble (LLM output, project .crabcakes/ content, MCP server response) can include a blockquote with a `[click me](javascript:...)` link. The user sees the red warning ⚠ but the link is clickable and executes the JS.
**Fix:** Replace `label = Gtk.Label(); label.set_markup(formatted)` with `label = make_safe_label(formatted, css_class="blockquote-text")` at line 700-701. One line change. Add a test that verifies a blockquote with `javascript:` link has its activate-link handler installed and returns True (blocking) for the URL.
**Note:** This is in scope for Phase 6 because the commit's stated intent is to wire activate-link guards into all user-/agent-authored text paths. The blockquote is exactly such a path.

---

### Finding 7: HIGH-5 — symlink paths not resolved

**Commit:** `d96780b`
**File:** `utils/project_trust.py:80-110` (the trust store functions)

`os.path.abspath()` is used to normalize paths, but symlinks are not followed. If a project path is `/foo` and `/foo` is a symlink to `/bar`:
- User opens `/foo` → trust record at key `/foo`
- User opens `/bar` → trust record at key `/bar` (separate)
These are treated as different projects.

**Severity:** Low — rare in practice; users typically use the same path consistently. The trust model is per-project-path, not per-inode.
**Fix (optional):** Use `os.path.realpath()` instead of `os.path.abspath()` for the trust record key. Be aware this changes the user-visible behavior: if a user `mv`s their project, they'd need to re-trust.

---

### Finding 8: HIGH-5 — trust granularity is project, not (project, file)

**Commit:** `d96780b`
**File:** `utils/prompt_loader.py:255-281`

The trust gate (`request_trust_if_needed`) is project-scoped. If a project is trusted, any future `*-bugs.md` or `*-rules.md` file added to `.crabcakes/` (under a different agent role) is auto-trusted.

**Severity:** Low — the trust prompt is shown on first open, and the user is told what they're approving. Adding a new `*-bugs.md` later (e.g. via `git pull` of a cloned repo) bypasses re-prompting.
**Mitigation:** The HIGH-5 fence `<untrusted-project-data>` wraps the content even after trust, so the model treats it as untrusted.
**Fix (optional):** Hash the `.crabcakes/` directory contents at trust-time; re-prompt if the hash changes.

---

## Test results

**Phase 6 added 60 tests across 5 test classes:**

| File | Tests | Status |
|---|---|---|
| `tests/test_project_trust.py` | 22 | ✅ all pass |
| `tests/test_gtk_safe_link.py` | 19 | ✅ all pass |
| `tests/test_mcp_client.py::TestSanitizeToolDescription` | 9 | ✅ all pass |
| `tests/test_tools.py::TestWebFetch::test_web_fetch_rejects_*` | 3 | ✅ all pass |
| `tests/test_tools.py::TestExecCommand::test_exec_command_scrubs_*` | 4 | ✅ all pass |
| `tests/test_prompt_loader.py` | 3 new | ✅ all pass |

**Total project test suite: 368/368 pass.** No regressions.

**Coverage gap:** The tests do not cover Finding 6 (blockquote path). If a regression test were added ("a blockquote with `javascript:` link has its activate-link handler installed and blocks navigation"), it would currently fail.

---

## Recommendations

**Two real shipping bugs (Findings 2 and 6):**

- **Finding 2 (MED-3):** Re-architect the redirect handling to validate each `Location` header before following. ~40 LOC + a test that asserts `httpx.get` is called only for allowed URLs. Time: 30-45 min.

- **Finding 6 (HIGH-6):** Replace `Gtk.Label()` + `set_markup()` at `chat_bubble.py:700` with `make_safe_label(formatted, css_class="blockquote-text")`. Add a regression test for the blockquote path. Time: 5-10 min.

**Three low-severity gaps (Findings 3, 7, 8):** Worth noting in the doc as "known limitations of defense-in-depth" but not blocking.

**One n/a (Findings 1, 4, 5):** Cosmetic / framing / single-source-of-truth. Skip.

**Updated accounting after Phase 6.1:**

If Findings 2 and 6 are fixed:
- HIGH-6 → ✅ **fully shipped** (was 🟡)
- MED-3 → ✅ **fully shipped** (was ✅, but the re-check was after-the-fact; becomes true re-check)

If they aren't fixed but the doc is honest:
- HIGH-6 → 🟡 **mostly shipped** (blockquote path uncovered)
- MED-3 → 🟡 **partial** (TCP connection still made to private hosts before re-check)

**My recommendation:** Ship a small Phase 6.1 commit fixing Findings 2 and 6, then update the doc to reflect the clean state. ~45 min total. This makes the "44 of 46 fully shipped" claim actually true.