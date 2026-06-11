# PHASE 11.2 — Update 4 `TestStreaming` test patches to use `self._call_llm_streaming`

**Master spec:** `docs/specs/PHASE-11-STREAMING-CLASS-METHOD.md`
**Depends on:** P11.1 (the function is now a method on `AgentRuntime`)

---

## Files to change

1. `tests/test_agent_runtime.py` — FOUR edits: update the 4 `TestStreaming` test patches at lines 631, 661, 689, 724

## What to do

**Edit pattern (applies to all 4 patches):**

Find each occurrence of:
```python
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt_module._call_llm_streaming(
                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",
                api_key=*** model="openai/gpt-4o",
                caller_key="openai",  # PHASE-10.5a: required positional arg
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
```

Replace with:
```python
            with unittest.mock.patch.object(rt, "_call_llm", lambda *a, **kw: rt._call_llm_streaming(
                session_key=a[0], base_url="https://api.openai.com/v1",
                api_key=*** model="openai/gpt-4o",
                caller_key="openai",  # PHASE-11: method on AgentRuntime
                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0
            )):
```

The changes are:
1. `rt_module._call_llm_streaming(` → `rt._call_llm_streaming(`
2. Remove the `runtime=rt,` line entirely
3. Update the comment from `PHASE-10.5a: required positional arg` to `PHASE-11: method on AgentRuntime`

**All 4 patches use the same pattern.** They all use `model="openai/gpt-4o"` and `caller_key="openai"`. The only difference between them is which mock streamer they patch in (`_mock_stream_openai_3_chunks`, `_mock_stream_openai_full_text`, `_mock_stream_with_tool_call`, etc.) and which assertion they make after.

**Use a script to do the substitution across all 4 occurrences** (since they're identical patterns, a `sed` or `python3` script is more reliable than 4 separate edits). The pattern to match and replace:

```python
# Match (with the `api_key=***` line as-is — that's the actual file content):
'rt_module._call_llm_streaming(\n                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",\n                api_key="test", model="openai/gpt-4o",\n                caller_key="openai",  # PHASE-10.5a: required positional arg\n                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0\n            )'

# Replace with:
'rt._call_llm_streaming(\n                session_key=a[0], base_url="https://api.openai.com/v1",\n                api_key="test", model="openai/gpt-4o",\n                caller_key="openai",  # PHASE-11: method on AgentRuntime\n                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0\n            )'
```

Or use a simpler approach with `python3 -c`:
```python
import re
with open('tests/test_agent_runtime.py') as f:
    content = f.read()
new_content = content.replace(
    'rt_module._call_llm_streaming(\n                runtime=rt, session_key=a[0], base_url="https://api.openai.com/v1",\n                api_key="test", model="openai/gpt-4o",\n                caller_key="openai",  # PHASE-10.5a: required positional arg\n                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0\n            )',
    'rt._call_llm_streaming(\n                session_key=a[0], base_url="https://api.openai.com/v1",\n                api_key="test", model="openai/gpt-4o",\n                caller_key="openai",  # PHASE-11: method on AgentRuntime\n                messages=a[1], tools=a[2] if len(a) > 2 else None, timeout=30.0\n            )'
)
assert new_content != content, 'No replacements made'
# Count replacements
n = content.count('rt_module._call_llm_streaming(') - new_content.count('rt_module._call_llm_streaming(')
assert n == 4, f'Expected 4 replacements, got {n}'
with open('tests/test_agent_runtime.py', 'w') as f:
    f.write(new_content)
```

## Rules

- Use the implementationSupervisor prompt at `/home/q/projects/crabcakes/prompts/implementationSupervisor.md`
- Read `tests/test_agent_runtime.py` lines 625-740 COMPLETELY before editing
- The 4 patches are at lines 631, 661, 689, 724 (verify with `grep -n "rt_module._call_llm_streaming" tests/test_agent_runtime.py`)
- Do NOT change any other part of the test file
- Do NOT change the assertions in the test methods
- Do NOT change the mock streamers (the `_PROVIDER_STREAMERS` patching above the `with` block)
- The 4 patches should be replaced in one pass (use a script, not 4 separate edits)

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
# Verify rt_module._call_llm_streaming is gone from the test file
grep -n "rt_module._call_llm_streaming\|rt\._call_llm_streaming" tests/test_agent_runtime.py
```

Expect: 4 matches, all using `rt._call_llm_streaming(`. Zero matches for `rt_module._call_llm_streaming`.

```bash
cd /home/q/projects/crabcakes
# Verify runtime= is gone from the test patches
grep -n "runtime=rt, session_key" tests/test_agent_runtime.py
```

Expect: 0 matches.

```bash
cd /home/q/projects/crabcakes
# Verify the 4 streaming tests now pass
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreaming -v 2>&1 | tail -10
```

Expect: 4 passed.

```bash
cd /home/q/projects/crabcakes
# Verify the full test_agent_runtime suite passes
timeout 60 python3 -m pytest tests/test_agent_runtime.py -q 2>&1 | tail -5
```

Expect: 57 passed (53 from before + 4 TestStreaming).

```bash
cd /home/q/projects/crabcakes
# Verify the P8 caller resolution tests still pass
timeout 30 python3 -m pytest tests/test_runtime_caller_resolution.py -v 2>&1 | tail -12
```

Expect: 8 passed.

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- Pytest output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.
