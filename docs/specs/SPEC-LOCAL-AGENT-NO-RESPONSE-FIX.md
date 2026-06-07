# SPEC: Fix Local Special Agent Routing & Silent Failure Modes

**Date:** 2026-06-07
**Author:** Qaster (adversarial-debugger audit + supervisor)
**Status:** Active — implementation in progress
**Implements:** `docs/bugs/BUG-forward-to-special-agent-routing.md` (partial; slash-command path already fixed) + extensions from adversarial audit
**Depends on:** None
**Target branch:** main

**Discovered from:** Adversarial audit on "test message to local agent Coder → no response" (2026-06-07). User reported Coder produces no response when messaged. Root cause: two distinct bug classes.

---

## 0. Summary

| # | Class | Severity | Symptom |
|---|-------|----------|---------|
| 1 | Silent LLM failure | CRITICAL | Body-level MiniMax auth error (HTTP 200) treated as success → empty content → no bubble rendered |
| 2 | Inline @mention routing gap | HIGH | Inline `@Coder` in project tab sends to gateway, not AgentRuntimeHandler → message silently dropped |

Class 2 is the **structural gap** the original `BUG-forward-to-special-agent-routing.md` fix missed (fixed slash-command path, missed inline mention path).
Class 1 is the **deeper root cause** of the user's "no response" symptom.

---

## 1. Architecture Compliance

Per `docs/ARCHITECTURE.md`: each message goes through exactly one routing path (gateway OR AgentRuntime). Special agents (session_key starting with `special:`) have no gateway session. Composition root is `window.py`; handlers are injected via setters.

The `is_special` check is required in EVERY message dispatch path:
1. Special-agent tab (`session_key` directly in `get_special_agents()`) — chat_handler.py:232
2. Slash command `forward_to` and `broadcast_targets` — chat_handler.py:304-340 (already fixed)
3. **Inline `@Agent` and `@all` mentions in project tabs** — chat_handler.py:389, 417 (THE BUG, Phase 1)
4. Project-tab solo DM (right-click) — chat_handler.py:454-468 (already correct)
5. Project-tab group fan-out — chat_handler.py:481-499 (already correct)

A new path added without this check will silently drop messages to local agents.

---

## 2. Changes by File

### 2.1 `ui/handlers/chat_handler.py` — inline @mention routing fix (Class B)

**What:** Add `is_special` checks to inline `@Agent` (line 389) and inline `@all` (line 417) paths.

**Function affected (line 372):** `_show_and_route_solo` — handles a resolved solo mention (e.g., `@Coder hello`).

**Function affected (line 399):** `_show_and_route_broadcast` — handles a resolved broadcast (e.g., `@all hello`).

**Code change at line 389 (replace):**

Before:
```python
if self._gw is not None and self._gw.is_connected():
    self._gw.send_message(resolution.target_session_key, forward_text)
```

After:
```python
# Special agents route through AgentRuntimeHandler, not gateway
# (they have no gateway session; gateway would silently drop the message)
is_special = (self._agent_runtime_handler is not None
              and resolution.target_session_key in self._agent_runtime_handler.get_special_agents())
if is_special:
    self._agent_runtime_handler.send_to_special_agent(resolution.target_session_key, forward_text)
elif self._gw is not None and self._gw.is_connected():
    self._gw.send_message(resolution.target_session_key, forward_text)
```

**Code change at line 417 (replace, inside the `for target in resolution.broadcast_targets:` loop):**

Before:
```python
for target in resolution.broadcast_targets:
    self._gw.send_message(target, forward_text)
```

After:
```python
for target in resolution.broadcast_targets:
    # Special agents route through AgentRuntimeHandler, not gateway
    is_special = (self._agent_runtime_handler is not None
                  and target in self._agent_runtime_handler.get_special_agents())
    if is_special:
        self._agent_runtime_handler.send_to_special_agent(target, forward_text)
        continue
    # Gateway agent — skip silently when offline
    if self._gw is None or not self._gw.is_connected():
        continue
    self._gw.send_message(target, forward_text)
```

**Verified signatures (from source):**
- `AgentRuntimeHandler.get_special_agents(self) -> dict[str, str]` — line 193
- `AgentRuntimeHandler.send_to_special_agent(self, session_key: str, text: str) -> None` — line 339

**No new imports; no new public API.**

### 2.2 `agent/runtime.py` — surface body-level LLM errors (Class A, part 1)

**What:** Detect MiniMax's body-level error format (HTTP 200 with `base_resp.status_code != 0`) and raise `RuntimeError` so `_run_loop`'s exception handler dispatches `_on_error` with a meaningful message.

**Functions affected:** `_call_minimax` (line ~115) and `_stream_minimax_events` (line ~355).

**Verified failure mode (reproduced live):** MiniMax returns `{"base_resp":{"status_code":1004,"status_msg":"login fail..."}}` with HTTP 200 when an invalid key is used. The runtime's existing `urllib.error.HTTPError` handler does NOT fire (HTTP 200 is not an HTTP error). Body must be inspected explicitly.

**`_call_minimax` change:** After successful urlopen, parse the response. If `base_resp.status_code != 0`, raise `RuntimeError` with the status code and message.

**`_stream_minimax_events` change:** Inside the SSE event loop, when a raw event arrives with `base_resp.status_code != 0`, raise the same `RuntimeError` before any deltas are yielded.

### 2.3 `agent/runtime.py` — detect empty-content responses (Class A, part 2)

**What:** In `_run_loop`'s text-only branch (line ~1059), if the response has no `choices` key at all, dispatch `_on_error` instead of `_on_response_complete` with empty text.

**Function affected:** `_run_loop` (line ~1059).

**Code change:** Wrap the existing `if not tool_calls_raw:` branch. Add a check: `if not text_content and not response.get("choices"):` → dispatch `_on_error` with a meaningful message. Otherwise, proceed to the existing text-only path.

**Note:** This is defense-in-depth. The load-bearing fix for the reported symptom is 2.2 (the MiniMax body-level check). This catches other malformed-response scenarios.

### 2.4 `ui/handlers/agent_runtime_handler.py` — defensive empty-response bubble (Class A, part 3)

**What:** In `_do_response_complete` (line 795), if response is empty AND no streaming bubble was active, render a fallback bubble so the user at least sees feedback that the round-trip happened.

**Function affected:** `_do_response_complete` (line 795).

**Code change:** Add a new branch `if not was_streaming and not text:` BEFORE the existing `if not was_streaming and text:` branch. Render a fallback message: "[Agent returned no content. This may indicate a configuration error...]"

**Verified signature:** `self._crh.render_sync(role, text, session_key=None, agent_name=None) -> Gtk.Widget | None` — line 326 of chat_render_handler.py.

### 2.5 Tests (split across phases)

- **Phase 1 tests:** New `TestInlineMentionRouting` class in `tests/test_chat_handler.py` with 4 tests covering the inline @mention routing fix.
- **Phase 2 tests:** New tests in `tests/test_agent_runtime.py` for MiniMax body-level error surfacing.
- **Phase 3 tests:** New test in `tests/test_agent_runtime.py` for empty-choices response handling.
- **Phase 4 tests:** New tests in `tests/test_agent_runtime.py` for the defensive empty-response bubble.

---

## 3. Data Flow

### Flow A: User in project tab types `@Coder hello` (Phase 1 fix)

```
User types "@Coder hello" in project:crabcakes tab
  ↓
chat_handler.py:on_send() line 232 → NOT a special agent tab
  → command handler returns handled=False (no slash prefix)
  → Inline @mention branch (line 360) — project tab
  → command_handler.resolve_inline_mention(...) returns MentionResolution(target_session_key="special:coder", clean_text="hello")
  ↓
chat_handler.py:372 _show_and_route_solo (PHASE 1 FIX)
  → is_special = True (NEW check at line 389)
  → self._agent_runtime_handler.send_to_special_agent("special:coder", "hello")
  ↓
agent_runtime_handler.py:send_to_special_agent (line 339)
  → Looks up agent_def, _active_project, _get_runtime(...)
  → rt.send_message("special:coder", "hello")
  ↓
agent/runtime.py:send_message → spawns thread → _run_loop
  → _call_llm → MiniMax API (or wherever configured)
  → If 200 with base_resp.status_code != 0: PHASE 2 raises RuntimeError
  → If empty content with empty choices: PHASE 3 dispatches _on_error
  → Otherwise: dispatches _on_response_complete with text
  ↓
agent_runtime_handler.py:_do_response_complete
  → If empty + not streaming: PHASE 4 renders fallback "no content" bubble
  → Else: existing rendering path
```

### Flow B: User in Coder tab types "hello" (already works)

```
User in special:coder tab types "hello"
  ↓
chat_handler.py:on_send() line 232 → True (special agent tab)
  → self._agent_runtime_handler.send_to_special_agent("special:coder", "hello")
  ↓  [same as Flow A from here]
```

### Flow C: Project tab group fan-out (already works)

```
User in project:crabcakes tab types "status check" (no @mention)
  ↓
chat_handler.py:on_send() line 232 → false
  → command handler returns handled=False
  → resolve_inline_mention returns clean_text only
  → falls through to project fan-out (line 481)
  → for each member: is_special_member check, route accordingly
```

---

## 4. File Change Summary

| File | Change type | Lines | Risk |
|---|---|---|---|
| `ui/handlers/chat_handler.py` | Bug fix — 2 `is_special` checks | +9 net | Low (mirrors existing correct pattern) |
| `agent/runtime.py` | Bug fix — body-level errors + empty responses | +35 net | Medium (touches core tool loop) |
| `ui/handlers/agent_runtime_handler.py` | Defensive render — fallback bubble | +18 net | Low (additive branch) |
| `tests/test_chat_handler.py` | New test class `TestInlineMentionRouting` | +120 | Low (test-only) |
| `tests/test_agent_runtime.py` | New tests for LLM error surfacing | +150 | Low (test-only) |
| `docs/post-mortems/2026-06-07-LOCAL-AGENT-NO-RESPONSE-FIX.md` | Post-mortem (separate task) | +200 | n/a |

---

## 5. Implementation Order (Phases)

**Phase 1 — Inline @mention routing fix (Class B)**
- Edit `ui/handlers/chat_handler.py:389` and `:417`.
- Add `TestInlineMentionRouting` class with 4 tests.
- Run: `python3 -m pytest tests/test_chat_handler.py -v`
- Acceptance: 4 new tests pass, 0 regressions, 3 grep sweeps clean.

**Phase 2 — Surface body-level MiniMax errors (Class A, part 1)**
- Edit `agent/runtime.py:_call_minimax` and `_stream_minimax_events`.
- Add 2 tests for body-level error raising.
- Run: `python3 -m pytest tests/test_agent_runtime.py -v -k "minimax"`
- Acceptance: 2 new tests pass, 0 regressions.

**Phase 3 — Detect empty-content responses (Class A, part 2)**
- Edit `agent/runtime.py:_run_loop` at line ~1059.
- Add 1 test for empty-choices response dispatching `_on_error`.
- Run: `python3 -m pytest tests/test_agent_runtime.py -v -k "empty"`
- Acceptance: 1 new test passes, 0 regressions.

**Phase 4 — Defensive empty-content bubble (Class A, part 3)**
- Edit `ui/handlers/agent_runtime_handler.py:_do_response_complete`.
- Add 2 tests for the fallback bubble.
- Run: `python3 -m pytest tests/test_agent_runtime.py -v -k "fallback"`
- Acceptance: 2 new tests pass, 0 regressions.

**Phase 5 — Full test suite**
- Run: `python3 -m pytest tests/ -v`
- Acceptance: full suite passes, no regressions.

**Phase 6 — Post-mortem**
- Write `docs/post-mortems/2026-06-07-LOCAL-AGENT-NO-RESPONSE-FIX.md`.

---

## 6. Acceptance Criteria

| # | Criterion | Test |
|---|---|---|
| 1 | Inline `@Coder hello` from project tab reaches Coder via AgentRuntimeHandler | `test_inline_mention_to_special_agent_routes_to_runtime` |
| 2 | Inline `@QTR status` from project tab reaches QTR via GatewayClient | `test_inline_mention_to_gateway_agent_routes_to_gw` |
| 3 | Inline `@all hello` routes special agents to runtime and gateway agents to gateway | `test_inline_mention_broadcast_with_special_member_routes_to_runtime` |
| 4 | Inline `@Coder hello` does NOT call `gw.send_message` (regression guard) | `test_inline_mention_to_special_agent_does_not_call_gw` |
| 5 | MiniMax HTTP-200 with `base_resp.status_code != 0` raises `RuntimeError` | `test_minimax_body_level_error_raises` |
| 6 | MiniMax streaming body-level error raises `RuntimeError` | `test_streaming_minimax_body_error_raises` |
| 7 | LLM response with no `choices` key dispatches `_on_error` | `test_empty_choices_response_dispatches_on_error` |
| 8 | `_do_response_complete("", ...)` with no streaming bubble renders fallback bubble | `test_empty_response_renders_fallback_bubble` |
| 9 | `_do_response_complete("", ...)` with active streaming does NOT render extra bubble | `test_empty_response_with_streaming_does_not_render_extra_bubble` |
| 10 | Full test suite passes with no regressions | `python3 -m pytest tests/ -v` |

---

## 7. Edge Cases

| Case | Expected | Test |
|---|---|---|
| `_agent_runtime_handler is None` (handler not yet wired) | Fall through to `gw.send_message` | Existing |
| `get_special_agents()` returns `{}` | Fall through to `gw.send_message` | Existing |
| `resolution.target_session_key` is None | Skip the solo branch entirely | Existing |
| `resolution.broadcast_targets` is `[]` | Skip the broadcast branch entirely | Existing |
| MiniMax `base_resp.status_code == 0` but empty `choices` | Pass body check, fail empty check (Phase 3) | Combined |
| MiniMax response is not valid JSON | `RuntimeError` from `json.JSONDecodeError` handler | Test 5 |
| Tool-only follow-up: empty content but tool_calls present | `tool_calls_raw` truthy → enters tool exec, NOT empty check | Trace verified |
| `_do_error` fails to render (chat_box is None) | Pre-existing limitation, not in scope | Out of scope |

---

## 8. Notes for Implementers

- **Phase 1 is the easiest** — small surgical changes, mirrors existing correct pattern.
- **Phases 2/3/4 are the deeper fix** for the user's reported "no response" symptom. The order matters: Phase 2 raises the error, Phase 3 catches edge cases, Phase 4 adds defense-in-depth.
- **Test patterns to copy:** `tests/test_chat_handler.py:480-575` (TestCommandErrorDisplay) for command-handler mocking. `tests/test_forward_handler.py:140-330` (TestForwardToAgent) for is_special routing assertions.
- **The user's live config (Coder with OpenRouter key on MiniMax provider) is a USER CONFIG BUG, not a runtime bug.** The spec does NOT silently rewrite the URL or auto-detect key/provider mismatch. The runtime correctly uses `provider_cfg.base_url` and the per-agent `api_key`; the configuration is the user's responsibility. Phase 2 surfaces the resulting auth failure clearly so the user can fix it.

---

**End of spec.**
