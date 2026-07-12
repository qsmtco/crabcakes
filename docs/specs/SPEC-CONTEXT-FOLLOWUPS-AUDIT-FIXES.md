# PHASE 1 Audit Fixes — 3 bugs + tests

**File:** `ui/handlers/agent_runtime_handler.py`, `ui/views/agent_builder.py`

---

## BUG #1 — Un-locked call site bypasses force_compact

**File:** `ui/handlers/agent_runtime_handler.py`

At line 518, the textual compaction path calls:
```python
        rt._context_strategy.compact(conv, target_budget)
```

This bypasses the new lock on `force_compact`. Change to:
```python
        rt.force_compact(conv, target_budget)
```

One-line change. This ensures the textual path also acquires `_compaction_lock`.

---

## BUG #4 — Position-coupled restore in agent_builder.py

**File:** `ui/views/agent_builder.py`

Line 740-744 uses hardcoded `if cs == "llm"` logic. Replace with constant-based lookup:

```python
        cs = agent_def.get("compaction_strategy", VALID_COMPACTION_STRATEGIES[0])
        if cs in VALID_COMPACTION_STRATEGIES:
            self._compaction_strategy_combo.set_selected(VALID_COMPACTION_STRATEGIES.index(cs))
        else:
            self._compaction_strategy_combo.set_selected(0)
```

---

## BUG #2 — Zero tests for new code paths

**File:** `tests/test_compact_command.py` — add tests at end of file

```python
class TestTargetSessionKey:
    """Tests for @Agent targeting via target_session_key."""

    def test_cmd_compact_uses_target_session_key(self):
        """When target_session_key is set, cmd_compact uses it over source."""
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        captured = {}
        def capture_cb(sk, focus):
            captured["sk"] = sk
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}
        handler._compact_callback = capture_cb
        handler._compact_chat_callback = None
        from models.command import Command
        cmd = Command(
            name="compact", args=[], flags={}, raw_text="/compact @Coder",
            body="", source_session_key="project:foo",
            target_session_key="special:coder"
        )
        result = handler.cmd_compact(cmd)
        assert captured["sk"] == "special:coder"
        assert result.handled is True

    def test_cmd_clear_uses_target_session_key(self):
        """When target_session_key is set, cmd_clear uses it over source."""
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        captured = {}
        handler._clear_callback = lambda sk: captured.__setitem__("sk", sk) or True
        handler._clear_chat_callback = None
        from models.command import Command
        cmd = Command(
            name="clear", args=[], flags={}, raw_text="/clear @Coder",
            body="", source_session_key="project:foo",
            target_session_key="special:coder"
        )
        result = handler.cmd_clear(cmd)
        assert captured["sk"] == "special:coder"
        assert result.handled is True

    def test_cmd_compact_falls_back_to_source(self):
        """When target_session_key is None, uses source_session_key."""
        from ui.handlers.project_handler import ProjectHandler
        handler = ProjectHandler.__new__(ProjectHandler)
        captured = {}
        def capture_cb(sk, focus):
            captured["sk"] = sk
            return {"messages_removed": 0, "tokens_freed": 0, "summary_chars": 0, "layer": 0}
        handler._compact_callback = capture_cb
        handler._compact_chat_callback = None
        from models.command import Command
        cmd = Command(
            name="compact", args=[], flags={}, raw_text="/compact",
            body="", source_session_key="special:coder",
            target_session_key=None
        )
        result = handler.cmd_compact(cmd)
        assert captured["sk"] == "special:coder"
```

**File:** `tests/test_llm_summarize_strategy.py` — add tests at end of file

```python
class TestLlmNameResolution:
    """Tests for agent_def.llm_name precedence in force_llm_compact."""

    def test_llm_name_overrides_conv_model(self):
        """When agent_def has llm_name, it takes precedence over conv.model."""
        from agent.runtime import AgentRuntime, DefaultContextStrategy
        rt = AgentRuntime.__new__(AgentRuntime)
        rt._context_strategy = DefaultContextStrategy()
        rt._compaction_lock = __import__("threading").Lock()

        conv = MagicMock()
        conv.messages = []
        conv.system_prompt = "test"
        conv.model = "openai/gpt-4o"
        conv.get_token_estimate.return_value = 100

        agent_def = MagicMock()
        agent_def.llm_name = "anthropic"

        # Mock config with anthropic provider
        prov_cfg = MagicMock()
        prov_cfg.default_model = "claude-3-5-sonnet"
        rt._config = MagicMock()
        rt._config.providers = {"anthropic": prov_cfg}

        captured_model = {}
        def mock_call_summary(system_prompt, user_prompt, model_id=None, conv=None):
            captured_model["model_id"] = model_id
            raise RuntimeError("stop here")  # prevent actual compact

        with patch.object(rt, "_call_for_summary", side_effect=mock_call_summary):
            try:
                rt.force_llm_compact(conv, 5000, "", agent_def=agent_def)
            except RuntimeError:
                pass

        assert captured_model.get("model_id", "").startswith("anthropic/")

    def test_no_llm_name_falls_back_to_conv_model(self):
        """When agent_def has no llm_name, falls back to conv.model."""
        from agent.runtime import AgentRuntime, DefaultContextStrategy
        rt = AgentRuntime.__new__(AgentRuntime)
        rt._context_strategy = DefaultContextStrategy()
        rt._compaction_lock = __import__("threading").Lock()

        conv = MagicMock()
        conv.messages = []
        conv.system_prompt = "test"
        conv.model = "openai/gpt-4o"
        conv.get_token_estimate.return_value = 100

        agent_def = MagicMock()
        agent_def.llm_name = None

        rt._config = MagicMock()
        rt._config.providers = {}

        captured_model = {}
        def mock_call_summary(system_prompt, user_prompt, model_id=None, conv=None):
            captured_model["model_id"] = model_id
            raise RuntimeError("stop here")

        with patch.object(rt, "_call_for_summary", side_effect=mock_call_summary):
            try:
                rt.force_llm_compact(conv, 5000, "", agent_def=agent_def)
            except RuntimeError:
                pass

        assert captured_model.get("model_id") == "openai/gpt-4o"
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read each file before editing.
- 2 code fixes + 5 new tests.

## Verification

```bash
cd /home/q/projects/crabcakes

# 1. Syntax
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['ui/handlers/agent_runtime_handler.py', 'ui/views/agent_builder.py', 'tests/test_compact_command.py', 'tests/test_llm_summarize_strategy.py']]; print('SYNTAX OK')"

# 2. force_compact called (not direct _context_strategy.compact)
grep -n "force_compact\|_context_strategy.compact" ui/handlers/agent_runtime_handler.py | grep -v "def \|#"

# 3. agent_builder uses constant for restore
grep -n "VALID_COMPACTION_STRATEGIES" ui/views/agent_builder.py | grep -i "index\|set_selected"

# 4. New tests exist
grep -c "test_cmd_compact_uses_target\|test_cmd_clear_uses_target\|test_llm_name_overrides\|test_no_llm_name_falls" tests/test_compact_command.py tests/test_llm_summarize_strategy.py

# 5. All tests pass
python3 -m pytest tests/test_compact_command.py tests/test_llm_summarize_strategy.py tests/test_project_handler.py -q
```
