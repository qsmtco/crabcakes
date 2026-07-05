# Investigation Report — Cohere 400 Empty-Assistant Bug (READ-ONLY)

**Date:** 2026-07-05 09:55 PDT
**Author:** Implementation Supervisor (this session)
**Severity:** CRITICAL (blocks all supervisor agent calls — every API call fails)
**Status:** DIAGNOSTIC ONLY — no code changes made per user instruction
**Reporter error:** `Provider returned error … must have non-empty content or tool calls at index 262`

---

## TL;DR

The current `"HTTP Error 400: Bad Request"` error you see from the supervisor agent is **not** the bug covered by either of the two recent specs:

- `SPEC-COMPACTION-MULTI-TOOL-RESULT-ORPHAN.md` (which I just implemented) — multi-TC orphans, FIXED.
- `SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY.md` — stale `to_api_messages()` and lost HTTPError body, **ALREADY FIXED IN BOTH BUGS before today's session**, audit verified.

The current error is a **third, distinct bug**: empty-content ASSISTANT messages in the on-disk conversation file. Cohere (and Anthropic with strict enforcement, and MiniMax) reject empty `{"role":"assistant","content":""}` API entries. **The supervisor is now broken until the empty message is removed — it cannot recover on its own.** A stopgap script is needed (analogous to `BUG-compaction-multi-tool-result-orphan.md`'s approach).

This bug is **independent of our Phase 1–5 work**. It pre-dates our changes; the corrupt message was created yesterday (2026-07-04 17:47 PDT) by an earlier session.

---

## 1. Verification of "did the prior work fix anything?"

I audited `agent/runtime.py` against `SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY.md` and the fix was already in place before my session started:

### Bug #1 of that spec: `messages = conv.to_api_messages()` after compact
- Spec target lines: `agent/runtime.py` line 2043 (was BEFORE compact)
- Current code, line 2134: `messages = conv.to_api_messages()` — comes AFTER `self._context_strategy.compact(conv, soft_ceiling)`
- Inline comment at line 2131 confirms: `"Build API messages AFTER compact so the wire payload reflects the trimmed conversation. Bug fix: was captured before compact()"`
- **VERIFIED: Bug #1 already fixed**

### Bug #2 of that spec: HTTPError body logging in streamers
- Spec target: `_stream_openai_events` (line ~877) and `_stream_minimax_events` (line ~928)
- Current code, `_stream_openai_events` (lines ~875-888):
  ```python
  try:
      resp = _urlopen_with_ssl_retry(req, timeout=timeout)
  except urllib.error.HTTPError as e:
      try:
          body = e.read().decode("utf-8", errors="replace")
      except Exception:
          body = "(could not read body)"
      logger.error(
          "Provider HTTP %d from %s (model=%s): %s",
          e.code, req.full_url, model, body[:500],
      )
      raise
  ```
- Identical pattern in `_stream_minimax_events` at lines 942–955.
- **VERIFIED: Bug #2 already fixed**. This is why your current error trace includes `"metadata":{"raw":"…must have non-empty content or tool calls…"}"` — without the fix, you'd only see `"HTTP Error 400: Bad Request"`.

So **both spec items in `SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY.md` are already in production**. The supervisor's HTTP 400 today is a different root cause.

---

## 2. Actual root cause — empty ASSISTANT message in conversation file

### 2.1 Direct evidence from on-disk conversation file

`~/.config/crabcakes/conversations/special:supervisor.json` contains exactly **one** malformed message:

```
conv[262]: {'role': 'assistant', 'content': '', 'tool_calls': [],
            'tool_call_id': None, 'tokens_used': 0,
            'timestamp': '2026-07-04T17:47:09.875555'}
```

That's a 0-byte assistant message with no tool calls. When `Conversation.to_api_messages()` serializes it, the API entry is literally:
```python
{"role": "assistant", "content": ""}
```

Cohere's API rejects it with `must have non-empty content or tool calls` (HTTP 400, code 400 via OpenRouter error wrapping).

The empty message sits at `api[263]` in the serialized message list (1 system + 262 user/assistant/tool entries before it) — matches your error trace of "index 262" within a 265-message payload (Cohere/OpenRouter counts may differ by ±1; the proximate cause is identical).

### 2.2 When it was created

The empty assistant's `timestamp` is **2026-07-04 17:47 PDT** (yesterday, ~15 hours before this session started). The compaction-fix work happened today (2026-07-05 06:53–07:49 PDT). So this message pre-dates our work and was **not caused by** any change in this session.

### 2.3 How it likely got there

There is exactly **one** code path in `agent/runtime.py` that creates an empty-content assistant message:

**`agent/runtime.py:2214`**
```python
if not tool_calls_raw:
    # Text-only response — but check for empty/missing content
    # which may indicate a provider error that wasn't raised (e.g. body-level
    # error that slipped through, or malformed response with no choices)
    if not text_content and not response.get("choices"):
        logger.warning("[tool-loop] sk=%s LLM returned no choices and no content — treating as error",
                       session_key)
        conv.add_assistant_message("", [])     # ← empty assistant
        self._dispatch(self._on_error, session_key, ...)
        self._auto_save(session_key, conv)
        return
```

When the LLM returns a malformed response (e.g. body-level error with HTTP 200, or a partially-parsed SSE stream that ended with no `choices[0].message.content`), this path **adds the empty message to the conversation and returns**. That's structurally correct (we don't want to lose the failure trace), but two things conspire to make the conversation unusable afterward:

1. **Auto-save persists the bad message** — `_auto_save` writes the now-corrupted conversation to disk.
2. **`to_api_messages` faithfully serializes the bad message** — there is no filter at serialization time to either drop empty-assistant entries or replace them with placeholder content.

Next time the supervisor agent tries to send any user message, the same corrupted conversation is loaded → `to_api_messages` serializes → provider returns 400 → cycle repeats. The supervisor is now stuck.

Other `add_assistant_message` call sites all pass meaningful content:
- Line 2279: `text_content` (the LLM's actual reply, or fallback to empty if extraction failed → still empty, but rare path)
- Line 2296: same
- Line 2431: `"[max tool iterations reached]"` (descriptive error)
- Line 2792: `f"[stopped: {reason}]"` (descriptive)

**Most likely origin: line 2214**, triggered by yesterday's session when the supervisor model returned a response with no choices and no content (could have been a body-level error from an earlier HTTPError, or a malformed SSE that the parser didn't catch).

---

## 3. Related code observation — `to_api_messages` doesn't filter

```python
# models/conversation.py:243-251
elif msg.role == MessageRole.ASSISTANT:
    entry: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        entry["tool_calls"] = [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in msg.tool_calls
        ]
    result.append(entry)
```

If `msg.content == ""` and `msg.tool_calls == []`, the entry is `{"role": "assistant", "content": ""}` — invalid for strict providers.

The symmetric issue could also occur with `TOOL_RESULT` (empty `content=""` with a `tool_call_id` set is technically valid by spec but suspicious), and with `USER` (empty user messages are usually allowed but unhelpful).

---

## 4. Recommended actions (NOT applied — read-only per request)

### 4.1 Stopgap: repair the corrupt supervisor conversation file (USER ACTION, NOT CODE)

Analogous to the stopgap script proposed in `BUG-compaction-multi-tool-result-orphan.md`:

```bash
python3 -c "
import json
from pathlib import Path

p = Path.home() / '.config/crabcakes/conversations/special:supervisor.json'
data = json.loads(p.read_text())
msgs = data['messages']
fixed = 0
for m in msgs:
    if m.get('role') == 'assistant' and not m.get('content', '') and not m.get('tool_calls', []):
        m['content'] = '[supervisor agent returned no content — placeholder]'
        m.setdefault('tokens_used', 0)
        fixed += 1
if fixed:
    p.write_text(json.dumps(data, indent=2, default=str))
    print(f'Repaired {fixed} empty assistant message(s) in {p}')
else:
    print('No empty assistant messages found.')
"
```

This can be run once now to unblock the supervisor. It does NOT fix the underlying bug; it only repairs the corrupted file.

### 4.2 Proper fix: add validation in `to_api_messages` (RECOMMENDED)

Add a filter inside the ASSISTANT branch of `models/conversation.py::to_api_messages`:

```python
elif msg.role == MessageRole.ASSISTANT:
    # Defense in depth: providers (Cohere, strict-mode Anthropic) reject empty
    # content with no tool calls. If we encounter one, log and substitute a
    # descriptive placeholder so the API call succeeds.
    if not msg.content and not msg.tool_calls:
        import logging
        logging.getLogger(__name__).warning(
            "to_api_messages: replacing empty assistant message at idx %d "
            "(no content, no tool_calls) with placeholder",
            len(result),  # before append
        )
        entry = {"role": "assistant", "content": "[assistant returned no content]"}
    else:
        entry = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]
    result.append(entry)
```

This is a **read-side filter**: never lets a malformed conversation break an API call. **Trades off**: a real conversational sequence may now have a "fake" assistant message in the wire payload that the LLM has to interpret. For Cohere this is harmless (it'll see the placeholder and continue). For OpenAI's tool loop, a placeholder with no tool_calls is structurally equivalent to an empty text response — which the model itself can emit.

Trade-off scorecard:
- ✅ Unblocks the supervisor immediately
- ✅ No data loss (the placeholder is descriptive; the original empty entry is still in `conv.messages`)
- ⚠️ Adds one warning log per empty message (useful for tracking how often this happens)
- ⚠️ Does NOT prevent the empty message from being created at line 2214 (separate fix below)

### 4.3 Companion fix: add content validation in the add path (RECOMMENDED)

At `agent/runtime.py:2214`, before calling `conv.add_assistant_message("", [])`, instead use a descriptive placeholder:

```python
# OLD:
conv.add_assistant_message("", [])

# NEW:
conv.add_assistant_message(
    "[LLM returned no choices and no content — provider error or malformed response]",
    [],
)
```

This prevents future corruption. Combined with §4.2, the system becomes resilient at both the create-time (no empty messages go in) and serialize-time (if one slips in, it gets a placeholder).

### 4.4 Should we revisit the recent compaction fix? **NO.**

Audit confirmed:
- 4 changes applied verbatim from spec §4 of `SPEC-COMPACTION-MULTI-TOOL-RESULT-ORPHAN.md`
- 4 regression tests passing (`TestMultiToolCallOrphanRegression`)
- 700+ unit tests pass
- `compact()` does not create empty ASSISTANT messages (only the summary injection path creates one, and it always passes `fitted` content — non-empty by guard)
- The corrupt supervisor message pre-dates our work by ~15 hours

The compaction fix is correct, complete, audited, and unrelated to this new bug.

---

## 5. Concise implementation order (if/when you authorize)

If you decide to ship the §4.2 + §4.3 fixes, I'd suggest **one phase each**, audited adversarially:

1. **Phase A: Stopgap script** (user-runs-now) — repair `~/.config/crabcakes/conversations/special:supervisor.json`. No code change.
2. **Phase B: Read-side filter** — `models/conversation.py::to_api_messages` ASSISTANT branch. +10 lines.
3. **Phase C: Write-side guard** — `agent/runtime.py:2214` substitute empty-content with a descriptive placeholder. 1 line changed.
4. **Phase D: Regression test** — add a test that builds a conv with an empty-content ASSISTANT message and verifies `to_api_messages` produces a valid entry.

New spec should be authored before implementation. Recommend `docs/specs/SPEC-CODER-EMPTY-ASSISTANT-MESSAGE.md` (mirrors the format of `SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY.md`).

---

## 6. Files for reference

- `/home/q/projects/crabcakes/agent/runtime.py` — runtime loop; line 2214 is the empty-message append path; lines 875–888 and 942–955 have the HTTPError body logger (already in place)
- `/home/q/projects/crabcakes/models/conversation.py` — `to_api_messages` at lines 221–273; `add_assistant_message` at lines 193–207; `add_tool_result` at lines 210–218
- `/home/q/projects/crabcakes/agent/context_strategy.py` — `compact()` does NOT create empty ASSISTANT messages (verified); only the summary injection path creates new ASSISTANT messages and it guards with `if fitted is not None`
- `/home/q/projects/crabcakes/docs/specs/SPEC-CODER-400-STALE-MESSAGES-AND-HTTPERROR-BODY.md` — both spec'd bugs are already fixed
- `/home/q/projects/crabcakes/docs/specs/SPEC-COMPACTION-MULTI-TOOL-RESULT-ORPHAN.md` — all 4 changes applied; not relevant to this new bug
- `~/.config/crabcakes/conversations/special:supervisor.json` — contains the corrupt message at conv[262]; timestamp 2026-07-04 17:47 PDT

## 7. Self-audit answers to your frustration

You said "you didn't fix anything witht the last bug fix" and "im am very frustrated with this".

Audit response:
1. **The compaction fix DID fix the multi-TC orphan bug.** 700+ tests pass; the post-mortem at `docs/post-mortems/2026-07-05-COMPACTION-MULTI-TOOL-RESULT-ORPHAN-POST-MORTEM.md` documents the change. That bug is closed.
2. **The "HTTP Error 400: Bad Request" symptom appeared twice.** The first instance (Coder bug) was already fixed by someone before my session — see §1 above. The current instance (supervisor bug) is a *different* 400 error with a different cause.
3. **The current 400 error has a different root cause than the previous one.** Both look identical in the UI ("HTTP Error 400: Bad Request") because they hit the same `_friendly_error_message(e) → str(exc)` path, but the provider body (which is now logged thanks to Bug #2's fix) tells us this one is about empty content, not stale messages.
4. **No silent "the fix didn't work" situation.** The new error is being correctly diagnosed via the error body that Bug #2's fix made visible. We have full visibility into the failure.
5. **Two of the three bugs in this chain are fixed (compaction orphans + stale-messages); the third (empty-assistant-message) is identified and ready for spec authorship and phased implementation when you authorize.**

I understand the frustration with repeated 400 errors. The systemic fix proposed in §4.2 + §4.3 would prevent this entire class of bug from recurring.

---

**Recommendation:** ship the stopgap immediately (Phase A, your one-line command). Author a new spec for the read-side and write-side fixes (Phase B/C) and revisit with a fresh plan. **Do not rush; the current code is correctly auditing its own behavior.**
