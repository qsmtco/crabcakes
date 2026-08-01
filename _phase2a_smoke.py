"""Phase 2a scaffold smoke verification (one-shot, deleted after run)."""
from agent.runtime import AgentRuntime, TurnStatus, TurnResult
from agent.config import AgentConfig

cfg = AgentConfig(providers={}, default_provider='openai', default_model='openai/gpt-4o')
rt = AgentRuntime(cfg, GLib=None)

# T1: non-terminal status rejected
r = TurnResult(status=TurnStatus.RUNNING, session_key='sk', turn_token=object())
assert rt._terminate_turn(r) is None
print('T1 OK: RUNNING rejected')

# T2: COMPLETED accepted
tk = object()
r = TurnResult(status=TurnStatus.COMPLETED, session_key='sk2', turn_token=tk, text='hi')
result = rt._terminate_turn(r)
assert result is not None and result.text == 'hi'
print('T2 OK: COMPLETED accepted, result.text=hi')

# T3: duplicate terminal rejected
r2 = TurnResult(status=TurnStatus.FAILED, session_key='sk2', turn_token=tk, error='oops')
assert rt._terminate_turn(r2) is None
print('T3 OK: duplicate terminal rejected')

# T4: get_turn_state returns the recorded status
assert rt.get_turn_state('sk2') == TurnStatus.COMPLETED
print('T4 OK: get_turn_state returns COMPLETED')

# T5: get_last_turn_result returns the result
got = rt.get_last_turn_result('sk2')
assert got is not None and got.text == 'hi'
print('T5 OK: get_last_turn_result returns the result')

# T6: stale-token rejection
rt._turn_tokens['sk3'] = object()  # active token differs
r3 = TurnResult(status=TurnStatus.COMPLETED, session_key='sk3', turn_token=object(), text='stale')
assert rt._terminate_turn(r3) is None
print('T6 OK: stale token rejected')

# T7: get_turn_state on unknown session returns None
assert rt.get_turn_state('unknown') is None
assert rt.get_last_turn_result('unknown') is None
print('T7 OK: unknown session returns None')

# T8: STREAMING also rejected as non-terminal
r4 = TurnResult(status=TurnStatus.STREAMING, session_key='sk4', turn_token=object())
assert rt._terminate_turn(r4) is None
print('T8 OK: STREAMING rejected')

# T9: CANCELLED accepted, dispatches on_error
captured = []
rt._on_error = lambda sk, msg, **kw: captured.append((sk, str(msg)))
tk5 = object()
r5 = TurnResult(status=TurnStatus.CANCELLED, session_key='sk5', turn_token=tk5, error='cancelled by user')
assert rt._terminate_turn(r5) is not None
assert len(captured) == 1
assert captured[0][0] == 'sk5'
print('T9 OK: CANCELLED accepted, on_error dispatched with message')

# T10: COMPLETED dispatches on_response_complete
captured2 = []
rt._on_response_complete = lambda sk, text, **kw: captured2.append((sk, text))
tk6 = object()
r6 = TurnResult(status=TurnStatus.COMPLETED, session_key='sk6', turn_token=tk6, text='done')
assert rt._terminate_turn(r6) is not None
assert len(captured2) == 1
assert captured2[0] == ('sk6', 'done')
print('T10 OK: COMPLETED dispatches on_response_complete with text')

print()
print('ALL 10 PHASE 2A SCAFFOLD SMOKE TESTS PASS')
