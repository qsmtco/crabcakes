with open('tests/test_agent_runtime.py', 'rb') as f:
    content = f.read()

old_start = content.find(b'def _mock_stream_with_tool_call():')
old_end = content.find(b'# Done\n    yield SSEEvent(type="done"', old_start)
old_end = content.find(b'\n', old_end) + 1

old = content[old_start:old_end]
print("Old found:", old)
print()
print("Old repr:", repr(old))
