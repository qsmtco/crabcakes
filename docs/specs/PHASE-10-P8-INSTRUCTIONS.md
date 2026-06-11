# PHASE 10 — P8: New test file `test_runtime_caller_resolution.py`

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Step 8 of the master spec's Implementation Order (new test file)

---

## Files to change

1. `tests/test_runtime_caller_resolution.py` — NEW file, ~80 lines

## What to do

**Create a new file `tests/test_runtime_caller_resolution.py`:**

```python
# tests/test_runtime_caller_resolution.py
# Unit tests for AgentRuntime._resolve_caller_key (PHASE-10).
# Verifies caller resolution priority:
#   1. Explicit provider_cfg.caller (highest priority)
#   2. Derivation from provider_cfg.default_model prefix
#   3. Fallback to model argument's prefix
#   4. Edge: empty model + empty caller + None provider_cfg

import pytest

from agent.config import LLMProviderConfig
from agent.runtime import AgentRuntime


def _pcfg(name="Owl-Alpha", base_url="https://openrouter.ai/api/v1",
          default_model="openrouter/owl-alpha", caller=""):
    """Build a minimal LLMProviderConfig with a dummy key."""
    return LLMProviderConfig(
        name=name, base_url=base_url, api_key=*** default_model=default_model, caller=caller,
    )


class TestResolveCallerKey:
    """Tests for AgentRuntime._resolve_caller_key static method."""

    def test_explicit_caller_wins(self):
        """provider_cfg.caller is the highest-priority source."""
        pcfg = _pcfg(caller="openrouter")
        # Even though default_model prefix is also "openrouter", the explicit
        # caller should be used as-is.
        key = AgentRuntime._resolve_caller_key(pcfg, "Owl-Alpha/openrouter/owl-alpha")
        assert key == "openrouter"

    def test_derivation_from_default_model(self):
        """When caller is empty, derive from default_model prefix."""
        pcfg = _pcfg(caller="", default_model="minimax/MiniMax-M2.7")
        key = AgentRuntime._resolve_caller_key(pcfg, "minimax/MiniMax-M2.7")
        assert key == "minimax"

    def test_fallback_to_model_argument(self):
        """When provider_cfg has no default_model and no caller, use model arg."""
        pcfg = _pcfg(caller="", default_model="")
        key = AgentRuntime._resolve_caller_key(pcfg, "openrouter/owl-alpha")
        assert key == "openrouter"

    def test_none_provider_cfg_falls_through_to_model(self):
        """When provider_cfg is None, use the model argument's prefix."""
        key = AgentRuntime._resolve_caller_key(None, "openrouter/owl-alpha")
        assert key == "openrouter"

    def test_empty_inputs_return_model_as_is(self):
        """When nothing is resolvable, return the model as-is (caller lookup will fail)."""
        pcfg = _pcfg(caller="", default_model="MiniMax-M2.7")
        key = AgentRuntime._resolve_caller_key(pcfg, "MiniMax-M2.7")
        assert key == "MiniMax-M2.7"

    def test_caller_not_lowered_when_mixed_case(self):
        """Caller is lowercased before return to match _PROVIDER_CALLERS keys."""
        pcfg = _pcfg(caller="OpenRouter")
        key = AgentRuntime._resolve_caller_key(pcfg, "Owl-Alpha/openrouter/owl-alpha")
        assert key == "openrouter"  # lowered

    def test_all_known_caller_keys_resolvable(self):
        """All 5 known caller keys (openai, minimax, anthropic, openrouter, zai)
        can be produced by _resolve_caller_key for a suitable provider_cfg."""
        for caller_name, model in [
            ("openai", "gpt-4o"),
            ("minimax", "minimax/MiniMax-M2.7"),
            ("anthropic", "claude-3-5-sonnet"),
            ("openrouter", "openrouter/owl-alpha"),
            ("zai", "zai/glm-5"),
        ]:
            pcfg = _pcfg(caller=caller_name, default_model=model)
            key = AgentRuntime._resolve_caller_key(pcfg, model)
            assert key == caller_name, f"{caller_name}: got {key!r}"


class TestResolveAgentModelNoDoublePrefix:
    """Tests for the P4 fix: _resolve_agent_model must not double-prefix
    model names that already contain a slash."""

    def test_slashed_default_model_returned_as_is(self, monkeypatch):
        """If default_model contains a slash, return it as-is (no double prefix)."""
        from agent.config import config as agent_config
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        import types

        # Set up a config with a slashed default_model
        # We use the real config; the user's "Owl-Alpha" provider has default_model "openrouter/owl-alpha"
        handler = AgentRuntimeHandler.__new__(AgentRuntimeHandler)
        fn = types.MethodType(AgentRuntimeHandler._resolve_agent_model, handler)

        class MockAgentDef:
            llm_name = "Owl-Alpha"
            model = None
            provider = None

        result = fn(MockAgentDef())
        assert result == "openrouter/owl-alpha", f"got {result!r}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Test only the **public surface** of `_resolve_caller_key` (it's a static method, so direct calls are fine)
- Do NOT test private internals like `_PROVIDER_CALLERS` dict contents
- Do NOT add GTK dependencies
- Keep the test file under 100 lines
- Use the same test style as `tests/test_agent_runtime.py` (plain functions, `pytest`, no class fixtures)

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
test -f tests/test_runtime_caller_resolution.py && echo "EXISTS" || echo "MISSING"
wc -l tests/test_runtime_caller_resolution.py
```

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_runtime_caller_resolution.py -v 2>&1 | tail -20
```

Expect: all 8 tests pass.

## Report

- Files created with line count
- Full verification output
- Pytest output (verbose)
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.