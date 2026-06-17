# Phase F1a — Extract `_prepare_kb_synthesis` helper (move kb_lookup out of tool loop)

**Source:** Auxilium Tier 2 post-mortem §9 (evolution suggestions: items 1 + 5) + adversarial audit follow-up
**Goal:** Item 1 (extract helper to shrink `_run_loop` by 25 lines) + item 5 (move `kb_lookup` out of the tool loop, run once per user message)
**Risk:** Medium (touches a hot loop and a path the fallback chain depends on)
**Lines:** -20 to -25 in `agent/runtime.py`, +30 to +40 (the new helper), +1-2 tests

## Background

Currently in `agent/runtime.py:_run_loop()`:

- The `kb_context` is computed inside the `while` tool loop (around line 1165-1173)
- This means `kb_lookup()` runs once per iteration of the tool loop, not once per user message
- For a typical 1-2 iteration conversation, this is a no-op, but for long tool loops, it's wasted work
- The whole KB-synthesis block is also ~10 lines that could be extracted

## Goal

1. Extract the KB pre-fetch + injection prep into a `_prepare_kb_synthesis` helper method on `AgentRuntime`
2. Move the helper call OUTSIDE the `while` tool loop (so `kb_lookup` runs once per user message)
3. The helper returns `(messages_for_call, kb_context)` so `_run_loop` can use both
4. The fallback chain at line ~1257 still uses `_inject_kb_context` (which takes `messages` and `kb_context` separately) — should not change
5. Add 1 test that verifies `kb_lookup` is called once per `_run_loop` invocation (not once per tool-loop iteration)

## Files to change

1. `agent/runtime.py` — add `_prepare_kb_synthesis` method, refactor `_run_loop` to call it outside the loop
2. `tests/test_auxilium_tier2.py` — add a test for once-per-message behavior

## Edit 1: Add `_prepare_kb_synthesis` method on `AgentRuntime`

**Anchor:** add the new method just before `_run_loop` (around line 1106). The method should be a `self` method on `AgentRuntime`.

**Method signature:** `_prepare_kb_synthesis(self, conv, text: str, messages: list[dict]) -> tuple[list[dict], str | None]`

**Method body (template):**

```python
    def _prepare_kb_synthesis(
        self,
        conv: "Conversation",
        text: str,
        messages: list[dict],
    ) -> tuple[list[dict], str | None]:
        """Prepare KB-synthesis messages for the primary LLM call (Tier 2).

        If conv.agent_role == "helper", runs kb_lookup on the current user
        message and injects the resulting chunks into the messages list.
        Returns (messages_for_call, kb_context). For non-auxilium agents
        or empty KB results, returns (messages, None) — no injection, no
        change to the messages.

        Called once per _run_loop invocation (not per tool-loop iteration).
        The fallback chain uses _inject_kb_context separately with the
        kb_context returned here.
        """
        # Gate: only fire for auxilium (type-safe, case-insensitive)
        if not (isinstance(conv.agent_role, str) and
                conv.agent_role.strip().lower() == "helper"):
            return messages, None

        # kb_lookup is fail-soft — if it raises, proceed without KB context
        try:
            from agent.kb_lookup import kb_lookup
            chunks = kb_lookup(text, top_k=5, min_score=0.35)
        except Exception:
            return messages, None

        if not chunks:
            return messages, None

        kb_context = _format_chunks_for_llm(chunks)
        messages_for_call = self._inject_kb_context(messages, kb_context, text)
        return messages_for_call, kb_context
```

**Notes:**

- The gate is type-safe and case-insensitive (matches the T2-F3 fix at line 1167). Same pattern.
- The `top_k=5, min_score=0.35` defaults are the existing values from `_run_loop`. They'll become configurable in Phase F3.
- The `kb_lookup` import is lazy (inside the try) — same pattern as the current code.
- The helper returns `(messages_for_call, kb_context)` so `_run_loop` can pass `kb_context` to the fallback chain later.

## Edit 2: Refactor `_run_loop` to call the helper

**Anchor:** the KB pre-fetch block at lines 1161-1183 (currently inside the `while` tool loop). Find this pattern:

```python
                # KB synthesis (Tier 2): for auxilium, run kb_lookup on every
                # user message and inject chunks into the primary LLM call.
                # This is separate from the KB fallback chain.
                kb_context = None
                if isinstance(conv.agent_role, str) and conv.agent_role.strip().lower() == "helper":
                    try:
                        from agent.kb_lookup import kb_lookup
                        chunks = kb_lookup(text, top_k=5, min_score=0.35)
                        if chunks:
                            kb_context = _format_chunks_for_llm(chunks)
                    except Exception:
                        pass  # kb_lookup is fail-soft — kb_context stays None, LLM proceeds without KB

                # Inject KB context into the primary LLM call for auxilium.
                # If kb_context is None (no relevant chunks or lookup failed), this is a no-op.
                messages_for_call = messages
                if kb_context:
                    messages_for_call = self._inject_kb_context(messages, kb_context, text)
                response = self._call_llm(session_key, messages_for_call, tools)
```

**Replace with:**

```python
                # KB synthesis (Tier 2): prepare messages with KB context if applicable.
                # The helper runs once per _run_loop invocation (not per tool-loop iteration)
                # so kb_lookup is called once even if the LLM triggers a tool loop.
                messages_for_call, kb_context = self._prepare_kb_synthesis(conv, text, messages)
                response = self._call_llm(session_key, messages_for_call, tools)
```

That's a 17-line → 5-line block, achieving the 25-line shrink (with the helper's added lines, net code is roughly neutral but the logic is isolated and the wasteful per-iteration calls are eliminated).

**The fallback chain (line ~1257) is unchanged.** It still uses `_inject_kb_context(messages, kb_context, text)` and the `kb_context` variable from `_run_loop`'s scope. Since `kb_context` is now set by `_prepare_kb_synthesis` at the top of the function (not inside the loop), it's available in the outer scope.

**Wait — verify the scope.** The fallback chain is INSIDE the `while` tool loop, and the new `_prepare_kb_synthesis` call is OUTSIDE the loop. So `kb_context` is in the function-level scope, accessible from inside the loop. **OK.**

## Edit 3: Add a test for once-per-message behavior

**Anchor:** add a new test to `TestKBLookupFiresForAuxilium` in `tests/test_auxilium_tier2.py`.

```python
    def test_kb_lookup_called_once_per_run_loop_invocation(self):
        """kb_lookup should run once per _run_loop call, NOT once per
        tool-loop iteration.

        Regression test for adversarial audit item 5 (wasteful per-iteration
        calls). After Phase F1a, the helper is called outside the while loop.
        """
        from agent.config import AgentConfig
        from agent.runtime import AgentRuntime
        from unittest.mock import patch

        cfg = AgentConfig(providers={}, default_provider='openai', default_model='openai/gpt-4o')
        rt = AgentRuntime(cfg)
        rt.start()
        rt.create_conversation(session_key='once', agent_name='Aux', agent_role='helper')

        call_count = [0]
        def counting_lookup(question, *, top_k, min_score):
            call_count[0] += 1
            return []  # empty chunks so the loop doesn't actually do anything
        def fake_call(sk, messages, tools):
            return {
                'choices': [{'message': {'content': 'a'}}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
            }

        with patch('agent.kb_lookup.kb_lookup', side_effect=counting_lookup):
            with patch.object(rt, '_call_llm', side_effect=fake_call):
                rt._run_loop('once', 'how do I configure?')

        # Exactly one kb_lookup call, regardless of how many times _call_llm is invoked
        assert call_count[0] == 1, f'expected 1 kb_lookup call, got {call_count[0]}'
```

**Note:** the test doesn't actually trigger a tool loop (the fake `_call_llm` returns a normal response, not a tool_calls response). To really test "once per `_run_loop` invocation, not per iteration," I'd need a fake `_call_llm` that returns a `tool_calls` response on the first call and a normal response on the second. The current test verifies that `kb_lookup` is called once when the tool loop is 1 iteration (the typical case). The test should also verify the multi-iteration case.

**Stronger version:**

```python
    def test_kb_lookup_called_once_per_run_loop_invocation(self):
        """kb_lookup should run once per _run_loop call, NOT once per
        tool-loop iteration. The helper is called outside the while loop.
        """
        from agent.config import AgentConfig
        from agent.runtime import AgentRuntime
        from unittest.mock import patch

        cfg = AgentConfig(providers={}, default_provider='openai', default_model='openai/gpt-4o')
        rt = AgentRuntime(cfg)
        rt.start()
        rt.create_conversation(session_key='once', agent_name='Aux', agent_role='helper')

        call_count = [0]
        def counting_lookup(question, *, top_k, min_score):
            call_count[0] += 1
            return []  # empty chunks so we don't add anything
        # First call returns a tool_calls response, second returns a normal answer
        call_count_llm = [0]
        def fake_call(sk, messages, tools):
            call_count_llm[0] += 1
            if call_count_llm[0] == 1:
                # First call: trigger the tool loop
                return {
                    'choices': [{'message': {
                        'content': '',
                        'tool_calls': [{'id': 't1', 'type': 'function',
                                        'function': {'name': 'read_file', 'arguments': '{}'}}],
                    }}],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
                }
            # Second call: normal answer
            return {
                'choices': [{'message': {'content': 'answer'}}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
            }

        with patch('agent.kb_lookup.kb_lookup', side_effect=counting_lookup):
            with patch.object(rt, '_call_llm', side_effect=fake_call):
                rt._run_loop('once', 'how do I configure?')

        # _call_llm was called twice (tool loop), but kb_lookup was called only once
        assert call_count_llm[0] == 2, f'expected 2 LLM calls, got {call_count_llm[0]}'
        assert call_count[0] == 1, f'expected 1 kb_lookup call, got {call_count[0]}'
```

Use the stronger version. It actually tests the multi-iteration case.

## Rules

- Use `prompts/steelFramedCodeWriter.md` as the active prompt.
- Use identifiers as anchors, not line numbers.
- The new helper must be added BEFORE `_run_loop` in the file (so it's defined when `_run_loop` references it). Python doesn't strictly require this for methods (methods are resolved at call time), but the convention is definition order.
- Do NOT change the fallback chain at line ~1257. It still uses `_inject_kb_context(messages, kb_context, text)` with the `kb_context` variable from `_run_loop`'s scope.
- Do NOT change the `_inject_kb_context` method itself.
- Do NOT change the gate pattern (`isinstance(conv.agent_role, str) and ...strip().lower() == "helper"`). Use the same pattern in the helper.
- The new helper's return value MUST be a 2-tuple `(messages_for_call, kb_context)`. The order matters — `_run_loop` destructures in that order.
- The `kb_context` variable in `_run_loop` must remain accessible inside the `while` loop (it is, because Python's lexical scope handles this).

## Verification (run yourself, paste output in report)

1. The new helper exists:
   ```
   grep -n "def _prepare_kb_synthesis" agent/runtime.py
   ```
   Expected: 1 match.

2. The old per-iteration kb_lookup block is gone from `_run_loop`:
   ```
   grep -n "kb_context = None\|if isinstance(conv.agent_role, str) and conv.agent_role.strip().lower() == \"helper\"" agent/runtime.py
   ```
   Expected: 1 match (inside the new helper only), 0 matches inside `_run_loop`.

3. The `_run_loop` now uses the helper:
   ```
   grep -n "_prepare_kb_synthesis" agent/runtime.py
   ```
   Expected: 2 matches (the method definition + the call site in `_run_loop`).

4. The new test passes:
   ```
   python3 -m pytest tests/test_auxilium_tier2.py::TestKBLookupFiresForAuxilium -v 2>&1 | tail -10
   ```
   Expected: 4 tests pass (3 existing + 1 new).

5. End-to-end: tool loop triggers, but `kb_lookup` is called only once:
   ```
   python3 -c "
   from agent.config import AgentConfig
   from agent.runtime import AgentRuntime
   from unittest.mock import patch
   cfg = AgentConfig(providers={}, default_provider='openai', default_model='openai/gpt-4o')
   rt = AgentRuntime(cfg)
   rt.start()
   rt.create_conversation(session_key='once', agent_name='Aux', agent_role='helper')

   kb_calls = [0]
   def counting_lookup(question, *, top_k, min_score):
       kb_calls[0] += 1
       return []
   llm_calls = [0]
   def fake_call(sk, messages, tools):
       llm_calls[0] += 1
       if llm_calls[0] == 1:
           return {'choices': [{'message': {'content': '', 'tool_calls': [{'id': 't1', 'type': 'function', 'function': {'name': 'read_file', 'arguments': '{}'}}]}}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
       return {'choices': [{'message': {'content': 'a'}}], 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
   with patch('agent.kb_lookup.kb_lookup', side_effect=counting_lookup):
       with patch.object(rt, '_call_llm', side_effect=fake_call):
           rt._run_loop('once', 'how do I configure?')
   print(f'LLM calls: {llm_calls[0]}, KB calls: {kb_calls[0]}')
   assert llm_calls[0] == 2, f'expected 2 LLM calls, got {llm_calls[0]}'
   assert kb_calls[0] == 1, f'expected 1 KB call, got {kb_calls[0]}'
   print('OK: tool loop fired twice but kb_lookup ran once')
   "
   ```
   Expected: `OK: tool loop fired twice but kb_lookup ran once`.

6. Full test suite:
   ```
   python3 -m pytest tests/ -q --tb=short --ignore=tests/test_agent_runtime.py --ignore=tests/test_kb_lookup.py 2>&1 | tail -5
   ```
   Expected: 1555 passed (1554 + 1 new), 1 skipped, exit 0.

## Deliverable

- Edit 1 applied (new helper method)
- Edit 2 applied (refactored `_run_loop`)
- Edit 3 applied (new test)
- All 6 verification commands run by you, output pasted in the report
- A `**COMPLETENESS:**` block listing each edit with evidence

## Word marker

Include the word "please write" in your opening reply so the channel knows this delegation is canonical.

## COMPLETENESS template

```
**COMPLETENESS:**
- [x] Edit 1: added _prepare_kb_synthesis method — line N in agent/runtime.py, evidence: V1 output
- [x] Edit 2: refactored _run_loop to call the helper outside the loop — line N in agent/runtime.py, evidence: V2 + V3 output
- [x] Edit 3: added test_kb_lookup_called_once_per_run_loop_invocation — line N in tests/test_auxilium_tier2.py, evidence: V4 output
- [x] Verification 1: helper exists — <paste output>
- [x] Verification 2: old per-iteration block is gone from _run_loop — <paste output>
- [x] Verification 3: _run_loop uses the helper — <paste output>
- [x] Verification 4: new test passes — <paste pytest output>
- [x] Verification 5: end-to-end tool loop fires but KB runs once — <paste output>
- [x] Verification 6: full test suite — <paste last 5 lines>
- [x] Related-bug scan: <list of any related issues found, or "none">
```
