# PHASE 2 — Surface Body-Level MiniMax Errors (CRITICAL)

**Spec:** `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` (see §2.2 and Phase 2 of §5)
**Phase:** 2 of 6
**Risk:** Medium (touches core LLM call path)
**Files changed:** 2 (1 prod, 1 test)

---

## STEP 0 — Read first (mandatory)

1. `prompts/steelFramedCodeWriter.md` — follow EXACTLY, no deviation
2. `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` — sections 2.2, 3 (Flow A, the failure mode)
3. `docs/ARCHITECTURE.md`
4. `agent/runtime.py` — specifically:
   - `_call_minimax` (line ~115) — the blocking caller
   - `_stream_minimax_events` (line ~355) — the streaming caller
   - `_call_llm` (line ~1212) — the dispatcher that calls both
   - `_run_loop` (line ~960) — the consumer that catches exceptions
5. `tests/test_agent_runtime.py` — existing test patterns (read the whole file)
6. **Live failure mode (reproduced by Qaster):** MiniMax returns `{"base_resp":{"status_code":1004,"status_msg":"login fail..."}}` with **HTTP 200** when an invalid key is used. The runtime's existing `urllib.error.HTTPError` handler does NOT fire because HTTP 200 is not an HTTP error. The body must be inspected explicitly.

---

## STEP 1 — Edit 1 of 2: `agent/runtime.py:_call_minimax` (line ~115)

**Current code (around line 115-145):**
```python
def _call_minimax(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
    """Call MiniMax ChatCompletion v2 API."""
    import urllib.request

    endpoint = f"{base_url.rstrip('/')}/text/chatcompletion_v2"
    payload = {
        "model": _model_id(model),
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"MiniMax API error {e.code} {e.reason}: {body}"
        ) from e
```

**Replace the `try/with` block with (new version handles both body-level errors and JSON parse errors):**

```python
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            # MiniMax returns body-level errors with HTTP 200:
            # {"base_resp":{"status_code":1004,"status_msg":"login fail..."}}
            base_resp = result.get("base_resp", {})
            status_code = base_resp.get("status_code", 0)
            if status_code != 0:
                status_msg = base_resp.get("status_msg", "unknown error")
                raise RuntimeError(
                    f"MiniMax API error (status_code={status_code}): {status_msg}"
                )
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"MiniMax API error {e.code} {e.reason}: {body}"
        ) from e
```

**Verification:** After the change, `_call_minimax` should:
- Still raise `RuntimeError` on `urllib.error.HTTPError` (existing behavior preserved)
- Raise `RuntimeError` if `base_resp.status_code != 0` (the load-bearing fix)
- Return the parsed response only when both checks pass

---

## STEP 2 — Edit 2 of 2: `agent/runtime.py:_stream_minimax_events` (line ~355)

The streaming variant catches body-level errors that arrive as a single JSON object (not SSE) before the normal SSE event loop. The implementation can either peek the first line or check inside the SSE event loop — both are acceptable as long as body-level errors raise `RuntimeError` before any deltas are yielded.

**Suggested approach (peek first non-empty line):**
```python
with urllib.request.urlopen(req, timeout=timeout) as resp:
    # MiniMax may return a body-level error with HTTP 200 (not SSE).
    # Check the first non-empty line before entering SSE parsing.
    first_line = None
    for line in _sse_lines(resp):
        if line.strip():
            first_line = line
            break
    if first_line is not None:
        # Check if this is a non-SSE JSON error response
        try:
            parsed = json.loads(first_line.decode("utf-8"))
            base_resp = parsed.get("base_resp", {})
            status_code = base_resp.get("status_code", 0)
            if status_code != 0:
                status_msg = base_resp.get("status_msg", "unknown error")
                raise RuntimeError(
                    f"MiniMax API error (status_code={status_code}): {status_msg}"
                )
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # Not JSON — likely SSE data, fall through

        # First line wasn't an error — process it as SSE
        ev = _parse_sse_line(first_line)
        if ev is not None:
            # ... existing SSE event handling ...

    for line in _sse_lines(resp):
        ev = _parse_sse_line(line)
        # ... existing SSE event handling ...
```

**Verification:** The new check raises `RuntimeError` before any text deltas are yielded when MiniMax returns a body-level error.

---

## STEP 3 — Edit 3: Add tests in `tests/test_agent_runtime.py`

**Location:** Append a new test class at the END of `tests/test_agent_runtime.py`. Do not modify any existing test.

**New class name:** `TestMinimaxBodyLevelError`

**Test 1 — `test_minimax_body_level_error_raises`:**
- Mock `urllib.request.urlopen` to return a context manager whose `read()` returns `b'{"base_resp":{"status_code":1004,"status_msg":"login fail"}}'` and status is HTTP 200.
- Call `_call_minimax(base_url, api_key, model, messages, None, timeout=10)`.
- Assert: raises `RuntimeError` with "1004" in the message.

**Test 2 — `test_streaming_minimax_body_error_raises`:**
- Mock the SSE line iterator to yield exactly one line: `b'data: {"base_resp":{"status_code":1004,"status_msg":"quota exceeded"}}'`.
- Call `_stream_minimax_events(...)` and consume the generator.
- Assert: raises `RuntimeError` with "1004" in the message.

---

## STEP 4 — Run tests, paste output, grep sweep

**Step 4a — Run the new test class:**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py::TestMinimaxBodyLevelError -v 2>&1
```

Expected: 2 passed, 0 failed.

**Step 4b — Run the full agent_runtime test file (regression check):**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_agent_runtime.py -v -k "not test_exec_with_approval" 2>&1
```

**Step 4c — Pattern sweep:**
```bash
cd /home/q/projects/crabcakes && grep -n "base_resp" agent/runtime.py
```
Expected: at least 4 matches (one or more in `_call_minimax`, one or more in `_stream_minimax_events`).

```bash
cd /home/q/projects/crabcakes && grep -n "status_code" agent/runtime.py
```
Expected: at least 4 matches.

---

## STEP 5 — Report back with COMPLETENESS checklist

```
COMPLETENESS:
- [ ] Edit 1: _call_minimax base_resp check — evidence: <paste the new line range>
- [ ] Edit 2: _stream_minimax_events base_resp check — evidence: <paste the new line range>
- [ ] Edit 3: TestMinimaxBodyLevelError class with 2 tests — evidence: <paste grep -n output>
- [ ] Step 4a: 2 new tests pass — evidence: <paste pytest output>
- [ ] Step 4b: 0 regressions in test_agent_runtime.py — evidence: <paste pytest summary line>
- [ ] Step 4c-1: at least 4 base_resp matches — evidence: <paste grep -c output>
- [ ] Step 4c-2: at least 4 status_code matches — evidence: <paste grep -c output>
```

---

## RULES — NO DEVIATION

1. Use `prompts/steelFramedCodeWriter.md` — follow EXACTLY.
2. Do NOT modify any file other than `agent/runtime.py` and `tests/test_agent_runtime.py`.
3. Do NOT modify any existing test in `tests/test_agent_runtime.py`. Append the new class at the END.
4. Do NOT change the existing `urllib.error.HTTPError` handling in `_call_minimax` — preserve the existing branch.
5. The new `base_resp` check must RAISE `RuntimeError`, not return an empty dict. Returning an empty dict would silently swallow the error and is exactly the bug we're fixing.
6. Do NOT add the `base_resp` check to `_call_openai` or `_call_anthropic` — only MiniMax exhibits the HTTP-200-with-body-error pattern.

---

**End of Phase 2 instructions. Begin work.**
