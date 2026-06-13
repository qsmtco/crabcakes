---
status: DONE
---
# SPEC: Line-Number Drift Prevention in Specs

## The Problem

Every time code changes, line numbers shift. Specs that say "insert at line 1401" are wrong the moment the first edit lands.

This has burned three consecutive phases:
- **PHASE-10.5:** spec said "line 1401" but actual was different
- **PHASE-11 P1:** spec said "insert after line 1400" but actual was ~1369
- **PHASE-11 P2:** spec said "4 patches at lines 631, 661, 689, 724" — there are 5 patches, positions shifted
- **PHASE-11 P3:** spec said "around line 690-745" — drifted

Line numbers in specs become **historical lies**. Every future reader and agent trusting them is misled.

## The Rule

**Never use line numbers for navigation in specs.** Navigation means: finding where to insert code, find a function to modify, locate an anchor point. Use symbols instead.

### Approved Symbol-Based Patterns

| Instead of | Use |
|---|---|
| "at line 1401" | "find `def _call_llm(` in agent/runtime.py" |
| "after line 600" | "find `class TestStreaming:` and insert the helper after `_resp()`" |
| "around line 690" | "find the last `rt.stop()` in `TestStreaming` before `class TestSSEParsing:`" |
| "line 631, 661..." | "find all occurrences of `rt_module._call_llm_streaming(` in `tests/test_agent_runtime.py`" |

### When Line Numbers ARE Acceptable

Line numbers may appear in:
1. **Verification commands** — e.g. `sed -n '50,60p' file.py` — these are for the agent to run, not for navigation
2. **Marked as approximate** — e.g. "around line 50" not "at line 50" — still prefer symbols
3. **Exact line numbers with a re-check step** — the spec includes a "verify line numbers before running" step that re-checks the numbers

### Symbol-Based Pattern Library

**Insert a function inside a class:**
```
Find the end of `class AgentRuntime:` in agent/runtime.py.
Insert the new method just before `def _check_stuck(`.
```

**Insert a helper after another function:**
```
In tests/test_agent_runtime.py, find `_resp()`.
Insert the new helper function after it, before the first `class `.
```

**Find and replace a call pattern:**
```
In tests/test_agent_runtime.py, find all occurrences of:
    rt_module._call_llm_streaming(
Replace each with:
    rt._call_llm_streaming(
```

**Insert before a class:**
```
In tests/test_agent_runtime.py, find `class TestStreamingSignature:`.
Insert the new test class before it.
```

**Find a specific line in context:**
```
grep -n "self._call_llm_streaming(" agent/runtime.py
```
Then use the output to understand context, not as a hard anchor.

## Retroactive Fix Protocol

When editing an existing spec to fix line-number drift:

1. Find every line-number reference (grep for `line [0-9]`)
2. For each reference, determine if it's for navigation or verification
3. Replace navigation references with symbol-based equivalents
4. Keep verification references but add a "verify before running" preamble

## Anti-Patterns

**❌ DO NOT:**
- "Insert at line 1401" — wrong the moment the spec ships
- "lines 553-650" — drifts on every edit
- "around line 631" — vague AND wrong
- "The patch at line 661" — fragile, disappears when other patches move

**✅ DO:**
- "Find `def _call_llm_streaming(` and remove it entirely"
- "In `TestStreaming`, find the `with unittest.mock.patch.object(rt, \"_call_llm\", ...)` block and update it"
- "Count all occurrences of `rt._call_llm_streaming(` in the test file"
