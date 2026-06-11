# PHASE 11.1 — Move `_call_llm_streaming` into `AgentRuntime` class

**Master spec:** `docs/specs/PHASE-11-STREAMING-CLASS-METHOD.md`

---

## Files to change

1. `agent/runtime.py` — TWO edits: (1) delete the module-level `_call_llm_streaming` function, (2) add a new method `def _call_llm_streaming(self, session_key, base_url, api_key, model, caller_key, messages, tools, timeout, x_title="")` inside the `AgentRuntime` class, positioned after `def _call_llm(` ends and before `def _check_stuck(`, (3) update the call site to call as `self._call_llm_streaming(...)` without the `runtime=` kwarg.

## What to do

**Edit 1 — Delete the module-level function definition:**

Find the module-level function `def _call_llm_streaming(`:
```python
def _call_llm_streaming(
    runtime,  # AgentRuntime instance — for GLib dispatch
    session_key: str,
    base_url: str,
    api_key: str,
    model: str,
    caller_key: str,  # PHASE-10.5a: resolved via AgentRuntime._resolve_caller_key
    messages: list[dict],
    tools: list[dict] | None,
    timeout: float,
    x_title: str = "",
) -> dict:
    """
    Call the LLM with streaming. ...
    """
    # PHASE-10.5a: ...
    streamer = _PROVIDER_STREAMERS.get(caller_key)
    if streamer is None:
        raise ValueError(...)
    ...
    return {"choices": [{"message": {"content": full_content, "tool_calls": ...}}], ...}
```

The function ends where the next top-level definition begins (look for a blank line followed by `def ` at column 0, or a class definition `class `). The exact end line varies — read the file to find it.

**Remove the entire function (definition + body + docstring + the blank lines before/after that separate it from neighbors).**

**Edit 2 — Add a new method inside `AgentRuntime` class:**

Find the end of `def _call_llm(` in the `AgentRuntime` class. The new method should be inserted after `_call_llm` ends, before `def _check_stuck(`. Read the area around the end of `_call_llm` to see what comes after it. The new method should be:

```python
    def _call_llm_streaming(
        self,
        session_key: str,
        base_url: str,
        api_key: str,
        model: str,
        caller_key: str,
        messages: list[dict],
        tools: list[dict] | None,
        timeout: float,
        x_title: str = "",
    ) -> dict:
        """
        Call the LLM with streaming. Fires on_text_delta as chunks arrive,
        on_tool_call_start when a tool call is complete, and returns the
        assembled response dict when done.

        Returns:
            Assembled response dict compatible with _extract_tool_calls / _extract_text_content.
        """
        # PHASE-11: caller_key is resolved by _call_llm before calling this method
        # (explicit caller > default_model prefix > model prefix). Symmetric with
        # the non-streaming path.
        streamer = _PROVIDER_STREAMERS.get(caller_key)
        if streamer is None:
            raise ValueError(
                f"No streaming caller for caller_key={caller_key!r} "
                f"(model={model!r}). Check provider's 'caller' field in Settings → Providers."
            )

        full_content = ""
        # tool_call_index → {name, arguments, done}
        tool_calls_partial: dict[int, dict] = {}

        for ev in streamer(base_url, api_key, model, messages, tools, timeout, x_title=x_title):
            if ev.type == "text_delta":
                text = ev.data.get("content") or ""
                full_content += text
                if self._on_text_delta:
                    self._dispatch(self._on_text_delta, session_key, text)

            elif ev.type == "tool_call_delta":
                idx = ev.data.get("index", 0)
                ... # rest of body unchanged, but replace `runtime.` with `self.`
```

**Critical changes in the body:**
- Replace `runtime._on_text_delta` with `self._on_text_delta`
- Replace `runtime._dispatch` with `self._dispatch`
- The rest of the body is unchanged — just copy it verbatim, change indentation from 4 spaces to 8 spaces (since it's now a method), and change `runtime.` to `self.`

**Read the file carefully** — the function body is long (~50 lines). Copy it accurately. Use the read tool to get the exact text.

**Edit 3 — Update the call site to `_call_llm_streaming`:**

Find:
```python
            return _call_llm_streaming(
                runtime=self,
                session_key=session_key,
                base_url=provider_cfg.base_url,
                api_key=effect…key,
                model=model,
                caller_key=caller_key,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
                x_title=x_title,
            )
```

Replace with:
```python
            return self._call_llm_streaming(
                session_key=session_key,
                base_url=provider_cfg.base_url,
                api_key=effect…key,
                model=model,
                caller_key=caller_key,
                messages=messages,
                tools=tools if tools else None,
                timeout=float(self._config.tool_timeout_seconds),
                x_title=x_title,
            )
```

The only change is `self._call_llm_streaming(` instead of `_call_llm_streaming(` and removal of the `runtime=self,` line.

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `agent/runtime.py` — find `def _call_llm_streaming(` at module level (the function to delete) and `def _call_llm(` in `AgentRuntime` class (the call site location) COMPLETELY before editing
- Symbol-based insertion point: after `def _call_llm(` ends and before `def _check_stuck(`
- Do NOT change the body logic of `_call_llm_streaming` — only the indentation, the `runtime.` → `self.` substitutions, and the signature (drop `runtime`, add `self`)
- Do NOT rename the method (keep `_call_llm_streaming`)
- Do NOT move `_call_llm` or any other method
- Do NOT change the call site to resolve `caller_key` inside the method — `_call_llm` still does the resolution and passes the key as a primitive (same pattern as `model`, `base_url`, `api_key`)
- Do NOT add a `provider_cfg` parameter — the caller passes the resolved primitives

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
# Verify the function is gone from module level
grep -n "^def _call_llm_streaming\|    def _call_llm_streaming" agent/runtime.py
```

Expect: exactly 1 match, indented (the new method, inside the class). NOT at column 0.

```bash
cd /home/q/projects/crabcakes
# Verify the call site uses self.
grep -n "_call_llm_streaming(" agent/runtime.py
```

Expect: 2 matches — one for the method definition, one for the call site. The call site should start with `self._call_llm_streaming(`.

```bash
cd /home/q/projects/crabcakes
# Verify runtime= is gone from the call site
grep -n "runtime=self" agent/runtime.py
```

Expect: 0 matches inside the call to `_call_llm_streaming`. There may be other `runtime=` usages elsewhere in the file (e.g. in `__init__` or other methods) — those are fine.

```bash
cd /home/q/projects/crabcakes
# Verify the body uses self. for runtime accesses
grep -n "runtime\._on_text_delta\|runtime\._dispatch" agent/runtime.py
```

Expect: 0 matches. All such accesses should now be `self._on_text_delta` and `self._dispatch`.

```bash
cd /home/q/projects/crabcakes
# Verify the runtime can still be imported
python3 -c "from agent.runtime import AgentRuntime; rt = AgentRuntime.__init__; print('imports ok')"
```

Expect: `imports ok`.

**NOTE: The 4 `TestStreaming` tests will BREAK after this edit.** This is expected — they still call `rt_module._call_llm_streaming(runtime=rt, ...)` which no longer exists. The next phase (P11.2) will fix them. Do NOT fix them in this phase.

To verify the 4 tests break predictably:
```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_agent_runtime.py::TestStreaming -q 2>&1 | tail -10
```

Expect: 4 failed, all with `AttributeError: module 'agent.runtime' has no attribute '_call_llm_streaming'` (or similar). This is the expected failure that P11.2 will resolve.

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- Pytest output (showing 4 expected failures)
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.
