# Phase 3 Instructions — Fix test_special_agents.py

## Context
3 tests fail because the agent registry loads user config from `~/.config/crabcakes/agents/coder.yaml` which overrides the defaults the tests expect. The fix is to mock `load_agent_defs` so tests get controlled definitions.

## Root Cause
- `test_coder_has_write_tools`: expects `"write_file" in coder.tools` but user config has only `["list_files", "read_file", "search_files"]`
- `test_coder_has_provider_model`: expects `coder.model == "MiniMax-M2.7"` but user config sets `model: minimax/MiniMax-M2.7` (with provider prefix)
- `test_coder_si_full_stack`: expects `si["enforcement"] is True` but user config sets `enforcement: false`

## Strategy
Mock `agent.special_agents.load_agent_defs` to return a controlled `SpecialAgentDef` for each test. The mock must be active during `reload_registry()` (called by the autouse `fresh_registry` fixture).

## Implementation

### Import needed (add at top of test methods or at file level):
```python
from unittest.mock import patch
```

### Test 1: `test_coder_has_write_tools` (line ~115)

Replace the current test body with:
```python
def test_coder_has_write_tools(self):
    from unittest.mock import patch
    from agent.special_agents import SpecialAgentDef
    coder_def = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file", "edit_file", "exec_command",
               "list_files", "search_files", "web_search", "web_fetch"],
        provider="minimax",
        model="MiniMax-M2.7",
        can_write=True,
    )
    with patch("agent.special_agents.load_agent_defs", return_value=[coder_def]):
        reload_registry()
        coder = get_special_agent("special:coder")
        assert coder is not None
        assert "write_file" in coder.tools
        assert coder.can_write is True
```

### Test 2: `test_coder_has_provider_model` (line ~130)

Replace the current test body with:
```python
def test_coder_has_provider_model(self):
    from unittest.mock import patch
    from agent.special_agents import SpecialAgentDef
    coder_def = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file"],
        provider="minimax",
        model="MiniMax-M2.7",
        can_write=True,
    )
    with patch("agent.special_agents.load_agent_defs", return_value=[coder_def]):
        reload_registry()
        coder = get_special_agent("special:coder")
        assert coder.provider == "minimax"
        assert coder.model == "MiniMax-M2.7"
```

### Test 3: `test_coder_si_full_stack` (line ~136)

Replace the current test body with:
```python
def test_coder_si_full_stack(self):
    from unittest.mock import patch
    from agent.special_agents import SpecialAgentDef
    coder_def = SpecialAgentDef(
        conv_id_prefix="special:coder",
        display_name="Coder",
        role="coder",
        emoji="🛠️",
        tools=["read_file", "write_file"],
        provider="minimax",
        model="MiniMax-M2.7",
        can_write=True,
        self_improvement={
            "bug_journal": True,
            "project_rules": True,
            "enforcement": True,
            "structured_feedback": True,
            "dream_consolidation": True,
        },
    )
    with patch("agent.special_agents.load_agent_defs", return_value=[coder_def]):
        reload_registry()
        coder = get_special_agent("special:coder")
        si = coder.get_self_improvement_config()
        assert si["bug_journal"] is True
        assert si["enforcement"] is True
        assert si["structured_feedback"] is True
        assert si["dream_consolidation"] is True
```

## Critical Notes
- The `fresh_registry` autouse fixture calls `reload_registry()` at the START of each test. But the mock needs to be active DURING that reload. Since we call `reload_registry()` again inside the `with patch(...)` block, the mock will be active for our reload. The fixture's initial reload will load user config, but our second reload inside the mock will override with our controlled def. This is fine.
- Do NOT modify any other tests in the file — only the 3 failing ones.
- The `SpecialAgentDef` constructor signature must be verified. Check that all required fields are present: `conv_id_prefix`, `display_name`, `role`, `emoji`, `tools`, `provider`, `model`, `can_write`.
- `self_improvement` is an optional field.

## Verification
```bash
python3 -m pytest tests/test_special_agents.py -q --tb=short
grep -n 'load_agent_defs' tests/test_special_agents.py
```
Expected: all tests pass, 3 occurrences of `load_agent_defs` (one per patched test).
