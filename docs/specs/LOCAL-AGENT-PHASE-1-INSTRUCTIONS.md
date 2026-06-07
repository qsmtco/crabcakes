# PHASE 1 — Inline @mention Routing Fix (CRITICAL)

**Spec:** `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` (see §2.1 and §2.5)
**Phase:** 1 of 6
**Risk:** Low (mirrors an existing correct pattern at lines 304-309 and 332-340)
**Files changed:** 2 (1 prod, 1 test)

---

## STEP 0 — Read first (mandatory)

Before writing any code, read:

1. `prompts/steelFramedCodeWriter.md` — follow this prompt EXACTLY, no deviation
2. `docs/specs/SPEC-LOCAL-AGENT-NO-RESPONSE-FIX.md` — sections 2.1, 2.5, 3 (Flow A), 5, 6, 7
3. `docs/ARCHITECTURE.md` — understand the routing architecture
4. `ui/handlers/chat_handler.py` — specifically lines 280-345 (the slash-command pattern QTR will mirror) AND lines 360-430 (where the inline @mention path lives)
5. `ui/handlers/agent_runtime_handler.py` — lines 193 and 339 (verify `get_special_agents()` and `send_to_special_agent()` signatures)
6. `tests/test_chat_handler.py` — lines 480-575 (test patterns to copy), specifically `TestCommandErrorDisplay._make_handler_with_command`
7. `models/command.py` — confirm the `MentionResolution` dataclass fields (target_session_key, broadcast_targets, is_broadcast, error, clean_text)

---

## STEP 1 — Edit 1 of 2: `ui/handlers/chat_handler.py` at line 389

**Location:** Inside the nested function `_show_and_route_solo` (defined at line 372), the offending line is at line 389.

**Current code (BROKEN — line 389):**
```python
if self._gw is not None and self._gw.is_connected():
    self._gw.send_message(resolution.target_session_key, forward_text)
```

**Replace with (FIXED — mirror the pattern at lines 304-309):**
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

**Verification (do this before reporting done):**
- `grep -n "self._agent_runtime_handler" ui/handlers/chat_handler.py` — confirm the attribute name matches.
- The new code must NOT call `self._gw.send_message` when `is_special` is true.

---

## STEP 2 — Edit 2 of 2: `ui/handlers/chat_handler.py` at line 417

**Location:** Inside the nested function `_show_and_route_broadcast` (defined at line 399), the offending line is at line 417, inside a `for target in resolution.broadcast_targets:` loop.

**Current code (BROKEN — line 417):**
```python
for target in resolution.broadcast_targets:
    self._gw.send_message(target, forward_text)
```

**Replace with (FIXED — mirror the pattern at lines 332-340):**
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

**Verification:**
- Confirm the `for` loop body is exactly the lines above (4 branches: is_special, offline, online → gw).
- The original `for` loop body was 1 line. The new body is 7 lines. The diff should show 6 net added lines.

---

## STEP 3 — Edit 3: Add tests in `tests/test_chat_handler.py`

**Location:** Append a new test class at the END of `tests/test_chat_handler.py` (do not modify any existing tests).

**New class name:** `TestInlineMentionRouting`

**Imports to add at the top of the test file** (only if not already present):
```python
from models.command import MentionResolution
```

**Helper to add inside the new class** (use the existing `make_handler` factory from this file):
```python
def _make_chat_handler_with_mention(
    self,
    input_text: str,
    session_key: str,
    mention_resolution,
    special_agents: dict,
):
    """Build a ChatHandler with command handler returning a pre-resolved MentionResolution."""
    gw = FakeGatewayClient(connected=True)
    mc = FakeMainContent(session_key=session_key, input_text=input_text)
    mc.set_tab_sessions({0: session_key})
    handler = make_handler(mc, gw)

    # Mock command handler — return the pre-resolved MentionResolution
    mock_cmd = MagicMock()
    mock_cmd.resolve_inline_mention.return_value = mention_resolution
    handler.set_command_handler(mock_cmd)

    # Mock agent runtime handler
    arh = MagicMock(name="AgentRuntimeHandler")
    arh.get_special_agents.return_value = special_agents
    arh.send_to_special_agent = MagicMock(name="send_to_special_agent")
    handler.set_agent_runtime_handler(arh)

    return handler, gw, arh
```

**Test 1 — `test_inline_mention_to_special_agent_routes_to_runtime`:**
```python
def test_inline_mention_to_special_agent_routes_to_runtime(self):
    """Inline `@Coder hello` from a project tab routes to AgentRuntimeHandler, not gateway."""
    from models.command import MentionResolution
    handler, gw, arh = self._make_chat_handler_with_mention(
        input_text="@Coder hello",
        session_key="project:crabcakes",
        mention_resolution=MentionResolution(
            target_session_key="special:coder",
            clean_text="hello",
        ),
        special_agents={"special:coder": "Coder"},
    )
    handler.on_send()
    arh.send_to_special_agent.assert_called_once_with("special:coder", "hello")
    gw.send_message.assert_not_called()
```

**Test 2 — `test_inline_mention_to_gateway_agent_routes_to_gw`:**
```python
def test_inline_mention_to_gateway_agent_routes_to_gw(self):
    """Inline `@QTR status` (gateway agent) routes to GatewayClient."""
    from models.command import MentionResolution
    handler, gw, arh = self._make_chat_handler_with_mention(
        input_text="@QTR status",
        session_key="project:crabcakes",
        mention_resolution=MentionResolution(
            target_session_key="agent:qaster:1",
            clean_text="status",
        ),
        special_agents={},  # QTR is a gateway agent
    )
    handler.on_send()
    gw.send_message.assert_called_once_with("agent:qaster:1", "status")
    arh.send_to_special_agent.assert_not_called()
```

**Test 3 — `test_inline_mention_broadcast_with_special_member_routes_to_runtime`:**
```python
def test_inline_mention_broadcast_with_special_member_routes_to_runtime(self):
    """Inline `@all hello` splits: special agents → runtime, gateway agents → gateway."""
    from models.command import MentionResolution
    handler, gw, arh = self._make_chat_handler_with_mention(
        input_text="@all hello",
        session_key="project:crabcakes",
        mention_resolution=MentionResolution(
            broadcast_targets=["special:coder", "agent:qaster:1"],
            clean_text="hello",
            is_broadcast=True,
        ),
        special_agents={"special:coder": "Coder"},
    )
    handler.on_send()
    arh.send_to_special_agent.assert_called_once_with("special:coder", "hello")
    gw.send_message.assert_called_once_with("agent:qaster:1", "hello")
```

**Test 4 — `test_inline_mention_to_special_agent_does_not_call_gw` (regression guard):**
```python
def test_inline_mention_to_special_agent_does_not_call_gw(self):
    """Regression: the broken path called gw.send_message for special agents.
    This test fails if someone reverts the fix."""
    from models.command import MentionResolution
    handler, gw, arh = self._make_chat_handler_with_mention(
        input_text="@Coder hello",
        session_key="project:crabcakes",
        mention_resolution=MentionResolution(
            target_session_key="special:coder",
            clean_text="hello",
        ),
        special_agents={"special:coder": "Coder"},
    )
    handler.on_send()
    # Both must be checked — special goes to runtime, NEVER to gateway
    assert gw.send_message.call_count == 0, (
        f"gw.send_message should NOT be called for special agents, "
        f"but was called {gw.send_message.call_count} times: {gw.send_message.call_args_list}"
    )
    arh.send_to_special_agent.assert_called_once_with("special:coder", "hello")
```

---

## STEP 4 — Run tests, paste output, grep sweep

**Step 4a — Run the new test class:**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_chat_handler.py::TestInlineMentionRouting -v 2>&1
```

Expected: 4 passed, 0 failed.

**Step 4b — Run the full chat_handler test file (regression check):**
```bash
cd /home/q/projects/crabcakes && python3 -m pytest tests/test_chat_handler.py -v 2>&1
```

Expected: all tests pass (existing + 4 new).

**Step 4c — Pattern sweep (confirm zero broken-pattern remnants):**
```bash
cd /home/q/projects/crabcakes && grep -n "is_special" ui/handlers/chat_handler.py | wc -l
```
Expected: at least 6 matches (4 in the existing slash + DM + fan-out paths, plus 2 new in the inline @mention paths).

```bash
cd /home/q/projects/crabcakes && grep -n "for target in resolution.broadcast_targets" ui/handlers/chat_handler.py
```
Expected: 1 match (the new fixed line).

---

## STEP 5 — Report back with COMPLETENESS checklist

In your reply to the supervising /ask, include this checklist filled in:

```
COMPLETENESS:
- [x/not done] Edit 1: chat_handler.py line 389 is_special check — evidence: <paste the new line range from grep -n>
- [x/not done] Edit 2: chat_handler.py line 417 broadcast is_special check — evidence: <paste the new for-loop body>
- [x/not done] Edit 3: tests/test_chat_handler.py — new class TestInlineMentionRouting with 4 tests — evidence: <paste grep -n "class TestInlineMentionRouting" output>
- [x/not done] Step 4a: 4 new tests pass — evidence: <paste pytest output>
- [x/not done] Step 4b: 0 regressions in test_chat_handler.py — evidence: <paste pytest summary line>
- [x/not done] Step 4c-1: at least 6 is_special matches in chat_handler.py — evidence: <paste grep -c output>
- [x/not done] Step 4c-2: exactly 1 match for `for target in resolution.broadcast_targets` — evidence: <paste grep output>
```

---

## RULES — NO DEVIATION

1. Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md` — follow it exactly.
2. Do NOT modify any file other than `ui/handlers/chat_handler.py` and `tests/test_chat_handler.py`.
3. Do NOT modify any existing test in `tests/test_chat_handler.py`. Append the new class at the END of the file.
4. Do NOT add imports that aren't already needed. Only add `from models.command import MentionResolution` at the top of the test file IF not already imported.
5. Do NOT change the line numbers of the `for` loop or the `if` checks — the exact line numbers in this spec (389, 417) are what the supervisor will grep for.
6. Do NOT declare done without pasting the COMPLETENESS checklist with evidence.
7. If any of the 3 edits fails a test or grep, fix it and re-run — do not report partial completion.
8. If a test fails and you cannot diagnose it in 2 attempts, STOP and report what you tried, the exact failure output, and the line number. The supervisor will fix it.

---

**End of Phase 1 instructions. Begin work.**
