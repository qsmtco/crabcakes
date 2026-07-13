# PHASE 1 Audit Fixes — 3 bugs

**File:** `ui/handlers/agent_command_handler.py`, `tests/test_agent_command_handler.py`

---

## BUG #1 — Pass 6 double-matches /compact @Agent "quoted payload"

Pass 1 matches the full quoted form. Pass 6 also matches the `/compact @Agent` prefix because its span is shorter and doesn't overlap in seen_spans.

**Fix:** Add negative lookahead to Pass 6 regex so it doesn't match when a quote follows the agent token.

**Current Pass 6 (around line 170):**
```python
    for m in re.finditer(r'(?:^|\s)/(compact|clear)\s+(@[^\s"]+)', text):
```

**Replace with:**
```python
    for m in re.finditer(r'(?:^|\s)/(compact|clear)\s+(@[^\s"]+)(?!\s*")', text):
```

---

## BUG #2 — `clear` missing from Pass 1 and Pass 2 allow-lists

**Pass 1 (around line 95):**
```python
# Before:
if cmd not in ('ask', 'tell', 'delegate', 'stop', 'compact'):
# After:
if cmd not in ('ask', 'tell', 'delegate', 'stop', 'compact', 'clear'):
```

**Pass 2 (around line 122):**
```python
# Before:
if cmd not in ('ask', 'tell', 'delegate', 'compact'):
# After:
if cmd not in ('ask', 'tell', 'delegate', 'compact', 'clear'):
```

---

## BUG #4 — Tests don't cover _record_action_result end-to-end

Add these tests to `TestAgentIssuedCompactClear`:

```python
    def test_no_duplicate_match_on_quoted_compact(self):
        """BUG #1: /compact @Coder "x" must produce exactly 1 command, not 2."""
        from ui.handlers.agent_command_handler import _extract_quoted_commands
        cmds = _extract_quoted_commands('/compact @Coder "preserve auth"')
        compact_cmds = [c for c in cmds if c.command == "compact"]
        assert len(compact_cmds) == 1, f"Duplicate match: {compact_cmds}"

    def test_clear_with_quoted_payload(self):
        """BUG #2: /clear @Coder "x" must parse (symmetric with compact)."""
        from ui.handlers.agent_command_handler import _extract_quoted_commands
        cmds = _extract_quoted_commands('/clear @Coder "session"')
        clear_cmds = [c for c in cmds if c.command == "clear"]
        assert len(clear_cmds) == 1, f"No clear command found: {cmds}"

    def test_record_action_result_calls_add_user_message(self):
        """BUG #4: _record_action_result must inject text into conversation."""
        from ui.handlers.agent_command_handler import AgentCommandHandler
        from unittest.mock import MagicMock, patch

        handler = AgentCommandHandler(GLib_module=None)

        # Mock runtime handler chain
        mock_conv = MagicMock()
        mock_rt = MagicMock()
        mock_rt.get_conversation.return_value = mock_conv
        import threading
        mock_rt._lock = threading.Lock()

        mock_agent_def = MagicMock()
        mock_agent_def.display_name = "Supervisor"

        mock_arh = MagicMock()
        mock_arh.get_special_agent_def.return_value = mock_agent_def
        mock_arh._get_runtime.return_value = mock_rt

        handler._agent_runtime_handler = mock_arh

        handler._record_action_result("special:supervisor", "Compacted. Freed 12K tokens.")

        mock_conv.add_user_message.assert_called_once()
        call_arg = mock_conv.add_user_message.call_args[0][0]
        assert "[Action result]" in call_arg
        assert "Compacted" in call_arg

    def test_record_action_result_no_crash_when_agent_def_none(self):
        """When get_special_agent_def returns None, must not crash."""
        from ui.handlers.agent_command_handler import AgentCommandHandler
        from unittest.mock import MagicMock

        handler = AgentCommandHandler(GLib_module=None)
        mock_arh = MagicMock()
        mock_arh.get_special_agent_def.return_value = None
        handler._agent_runtime_handler = mock_arh

        handler._record_action_result("special:unknown", "test")
        # No exception = pass
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read each file before editing.
- 2 regex/filter fixes + 4 new tests.

## Verification

```bash
cd /home/q/projects/crabcakes

# 1. Syntax
python3 -c "import ast; ast.parse(open('ui/handlers/agent_command_handler.py').read()); print('SYNTAX OK')"

# 2. Pass 6 has lookahead
grep -n "compact|clear" ui/handlers/agent_command_handler.py | grep "!"

# 3. clear in both allow-lists
grep -n "'clear'" ui/handlers/agent_command_handler.py | head -5

# 4. All tests
python3 -m pytest tests/test_agent_command_handler.py -v
```
