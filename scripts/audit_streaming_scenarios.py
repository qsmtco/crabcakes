"""PHASE-11 adversarial audit: streaming-path attack scenarios."""
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")

from unittest.mock import MagicMock, patch
from agent.config import AgentConfig
from agent.runtime import AgentRuntime, SSEEvent
from agent.llm.openai_provider import OpenAIProvider

def banner(title):
    print("\n" + "="*60)
    print(title)
    print("="*60)

def make_rt():
    """Create a minimal AgentRuntime for testing."""
    from agent.config import AgentConfig, LLMProviderConfig
    cfg = AgentConfig(
        providers={
            "openai": LLMProviderConfig(
                name="openai",
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                default_model="gpt-4o",
            )
        },
        default_provider="openai",
        default_model="openai/gpt-4o",
        max_tool_iterations=5,
        tool_timeout_seconds=30,
    )
    return AgentRuntime(cfg)

# ── Scenario 1: streamer raises mid-iteration ──
banner("Scenario 1: streamer raises exception mid-iteration")
rt = make_rt()
def bad_streamer(*a, **kw):
    yield SSEEvent(type="text_delta", data={"content": "Hello"})
    raise RuntimeError("connection reset")

deltas = []
rt._on_text_delta = lambda sk, d: deltas.append(d)

with patch.object(OpenAIProvider, "stream", bad_streamer):
    try:
        result = rt._call_llm_streaming(
            session_key="test",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="openai/gpt-4o",
            caller_key="openai",
            messages=[],
            tools=None,
            timeout=30.0,
        )
        print(f"  Result: {result}")
        print(f"  Deltas fired: {deltas}")
        print(f"  VERDICT: FAIL — exception was swallowed")
    except RuntimeError as e:
        print(f"  Caught: {type(e).__name__}: {e}")
        print(f"  Deltas fired before crash: {deltas}")
        print(f"  VERDICT: PASS — exception propagates (caller will see it)")

# ── Scenario 2: streamer yields no events at all (empty) ──
banner("Scenario 2: streamer yields zero events")
rt = make_rt()
def empty_streamer(*a, **kw):
    return
    yield  # unreachable, makes this a generator

with patch.object(OpenAIProvider, "stream", empty_streamer):
    result = rt._call_llm_streaming(
        session_key="test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="openai/gpt-4o",
        caller_key="openai",
        messages=[],
        tools=None,
        timeout=30.0,
    )
    print(f"  Result: {result}")
    print(f"  content: {result['choices'][0]['message']['content']!r}")
    print(f"  tool_calls: {result['choices'][0]['message']['tool_calls']}")
    print(f"  VERDICT: {'PASS — returns empty response' if result['choices'][0]['message']['content'] == '' else 'FAIL'}")

# ── Scenario 3: tool_call_delta with missing 'index' key ──
banner("Scenario 3: tool_call_delta with missing 'index' key")
rt = make_rt()
def broken_tool_streamer(*a, **kw):
    yield SSEEvent(type="tool_call_delta", data={"name": "list_files", "arguments": "{}"})  # no index

with patch.object(OpenAIProvider, "stream", broken_tool_streamer):
    try:
        result = rt._call_llm_streaming(
            session_key="test",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="openai/gpt-4o",
            caller_key="openai",
            messages=[],
            tools=None,
            timeout=30.0,
        )
        print(f"  Result: {result}")
        print(f"  VERDICT: {'PASS — defaults to index 0' if result['choices'][0]['message']['tool_calls'] else 'NOTE — empty tool_calls'}")
    except KeyError as e:
        print(f"  Caught KeyError: {e}")
        print(f"  VERDICT: FAIL — KeyError on missing 'index' (should default to 0)")

# ── Scenario 4: text_delta with None content ──
banner("Scenario 4: text_delta with content=None")
rt = make_rt()
deltas = []
rt._on_text_delta = lambda sk, d: deltas.append(d)
def none_text_streamer(*a, **kw):
    yield SSEEvent(type="text_delta", data={"content": None})

with patch.object(OpenAIProvider, "stream", none_text_streamer):
    result = rt._call_llm_streaming(
        session_key="test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="openai/gpt-4o",
        caller_key="openai",
        messages=[],
        tools=None,
        timeout=30.0,
    )
    print(f"  Result content: {result['choices'][0]['message']['content']!r}")
    print(f"  Deltas: {deltas}")
    print(f"  VERDICT: {'PASS — None coerced to empty string' if result['choices'][0]['message']['content'] == '' else 'FAIL'}")

# ── Scenario 5: on_text_delta callback raises ──
banner("Scenario 5: on_text_delta callback raises exception")
rt = make_rt()
def bad_callback(sk, d):
    raise ValueError("callback exploded")
rt._on_text_delta = bad_callback

def normal_streamer(*a, **kw):
    yield SSEEvent(type="text_delta", data={"content": "hello"})

with patch.object(OpenAIProvider, "stream", normal_streamer):
    try:
        result = rt._call_llm_streaming(
            session_key="test",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="openai/gpt-4o",
            caller_key="openai",
            messages=[],
            tools=None,
            timeout=30.0,
        )
        print(f"  VERDICT: FAIL — callback exception was swallowed silently")
    except ValueError as e:
        print(f"  Caught: {type(e).__name__}: {e}")
        print(f"  VERDICT: PASS — exception propagates")

# ── Scenario 6: _dispatch swallows callback errors? ──
banner("Scenario 6: does _dispatch swallow callback errors?")
rt = make_rt()
# Read the _dispatch method
import inspect
src = inspect.getsource(rt._dispatch)
print(f"  _dispatch source:\n{src}")
if "except" in src:
    print(f"  VERDICT: NOTE — _dispatch catches exceptions (may swallow callback errors)")
else:
    print(f"  VERDICT: PASS — _dispatch does not catch (exceptions propagate)")

# ── Scenario 7: two concurrent calls to _call_llm_streaming ──
banner("Scenario 7: two concurrent _call_llm_streaming calls (same runtime)")
rt = make_rt()
import threading

deltas_1 = []
deltas_2 = []
rt._on_text_delta = None  # will set per-thread

def thread_target(thread_id):
    if thread_id == 1:
        rt._on_text_delta = lambda sk, d: deltas_1.append(d)
    else:
        rt._on_text_delta = lambda sk, d: deltas_2.append(d)
    
    def streamer(*a, **kw):
        for i in range(3):
            yield SSEEvent(type="text_delta", data={"content": f"t{thread_id}-{i} "})
    
    with patch.object(OpenAIProvider, "stream", streamer):
        rt._call_llm_streaming(
            session_key=f"thread-{thread_id}",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="openai/gpt-4o",
            caller_key="openai",
            messages=[],
            tools=None,
            timeout=30.0,
        )

t1 = threading.Thread(target=thread_target, args=(1,))
t2 = threading.Thread(target=thread_target, args=(2,))
t1.start()
t2.start()
t1.join()
t2.join()
print(f"  Thread 1 deltas: {deltas_1}")
print(f"  Thread 2 deltas: {deltas_2}")
print(f"  VERDICT: NOTE — shared _on_text_delta is a race condition. Last writer wins.")
print(f"  NOTE: in practice, _call_llm_streaming is called from a single thread per session.")

# ── Scenario 8: unknown event type from streamer ──
banner("Scenario 8: streamer yields unknown event type")
rt = make_rt()
def weird_streamer(*a, **kw):
    yield SSEEvent(type="text_delta", data={"content": "hello"})
    yield SSEEvent(type="unknown_event", data={"foo": "bar"})
    yield SSEEvent(type="text_delta", data={"content": " world"})

with patch.object(OpenAIProvider, "stream", weird_streamer):
    result = rt._call_llm_streaming(
        session_key="test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="openai/gpt-4o",
        caller_key="openai",
        messages=[],
        tools=None,
        timeout=30.0,
    )
    print(f"  Result content: {result['choices'][0]['message']['content']!r}")
    print(f"  VERDICT: {'PASS — unknown event silently skipped' if 'hello world' in result['choices'][0]['message']['content'] else 'FAIL'}")

# ── Scenario 9: done event with no prior events ──
banner("Scenario 9: done event with no prior text/tool events")
rt = make_rt()
def immediate_done(*a, **kw):
    yield SSEEvent(type="done", data={})

with patch.object(OpenAIProvider, "stream", immediate_done):
    result = rt._call_llm_streaming(
        session_key="test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="openai/gpt-4o",
        caller_key="openai",
        messages=[],
        tools=None,
        timeout=30.0,
    )
    print(f"  Result: {result['choices'][0]['message']}")
    print(f"  VERDICT: {'PASS — empty content, no tool_calls' if result['choices'][0]['message']['content'] == '' and not result['choices'][0]['message']['tool_calls'] else 'FAIL'}")

# ── Scenario 10: tool_call_delta with invalid arguments JSON ──
banner("Scenario 10: tool_call_delta accumulates invalid JSON in arguments")
rt = make_rt()
def bad_args_streamer(*a, **kw):
    yield SSEEvent(type="tool_call_delta", data={"index": 0, "name": "list_files", "arguments": "{not valid json"})

with patch.object(OpenAIProvider, "stream", bad_args_streamer):
    try:
        result = rt._call_llm_streaming(
            session_key="test",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model="openai/gpt-4o",
            caller_key="openai",
            messages=[],
            tools=None,
            timeout=30.0,
        )
        tc = result['choices'][0]['message']['tool_calls']
        print(f"  Result tool_calls: {tc}")
        if tc and tc[0]['function']['arguments'] == "{not valid json":
            print(f"  VERDICT: NOTE — invalid JSON stored verbatim (validation deferred to tool execution)")
        else:
            print(f"  VERDICT: FAIL — arguments not preserved")
    except Exception as e:
        print(f"  Caught: {type(e).__name__}: {e}")
        print(f"  VERDICT: FAIL — exception during accumulation")

print("\n" + "="*60)
print("Streaming audit complete.")
print("="*60)
