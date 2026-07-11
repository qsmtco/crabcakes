# PHASE B Audit Fixes — 3 mechanical fixes

**File:** `ui/handlers/project_handler.py`, `ui/handlers/command_handler.py`

---

## BUG #1 — Guard LLM branch with hasattr

**File:** `ui/handlers/agent_runtime_handler.py`

In `compact_conversation`, the `if strat_name == "llm":` branch calls `rt.force_llm_compact` which doesn't exist yet (Phase C). Add a `hasattr` guard so the branch only fires when the method exists:

**Current (around line 506):**
```python
        if strat_name == "llm":
            # Phase C path
            try:
                return rt.force_llm_compact(conv, target_budget, focus_text)
```

**Replace with:**
```python
        if strat_name == "llm" and hasattr(rt, "force_llm_compact"):
            # Phase C path — only fires when force_llm_compact exists.
            # Phase B: this branch is unreachable (no compaction_strategy
            # field on SpecialAgentDef, and force_llm_compact not implemented).
            try:
                return rt.force_llm_compact(conv, target_budget, focus_text)
```

---

## BUG #4 — Mark /compact as payload_free

**File:** `ui/handlers/command_handler.py`

**Current (around line 165):**
```python
                self.register_command("compact", project_handler.cmd_compact,
                    help_text="Compact conversation: /compact [focus-instructions]")
```

**Replace with:**
```python
                self.register_command("compact", project_handler.cmd_compact,
                    help_text="Compact conversation: /compact [focus-instructions]",
                    payload_free=True)
```

---

## BUG #5 — Defensive None handling for cmd.body

**File:** `ui/handlers/project_handler.py`

In `cmd_compact`, find the line:
```python
            focus_text = cmd.body.strip() if cmd.body else ""
```

**Replace with:**
```python
            focus_text = (cmd.body or "").strip()
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read each file before editing.
- 3 one-line fixes.

## Verification

```bash
cd /home/q/projects/crabcakes

# 1. Syntax
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['ui/handlers/agent_runtime_handler.py', 'ui/handlers/command_handler.py', 'ui/handlers/project_handler.py']]; print('SYNTAX OK')"

# 2. hasattr guard
grep -n "hasattr.*force_llm_compact" ui/handlers/agent_runtime_handler.py

# 3. payload_free
grep -n "payload_free" ui/handlers/command_handler.py | grep compact

# 4. defensive None
grep -n "cmd.body or" ui/handlers/project_handler.py

# 5. Existing tests
python3 -m pytest tests/test_project_handler.py tests/test_command_handler.py -q
```
