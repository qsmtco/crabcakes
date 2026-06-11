"""PHASE-11 adversarial audit: attack scenarios for _resolve_caller_key + _call_llm_streaming."""
import sys
sys.path.insert(0, "/home/q/projects/crabcakes")

from agent.config import LLMProviderConfig
from agent.runtime import AgentRuntime, _PROVIDER_CALLERS, _PROVIDER_STREAMERS

KNOWN_CALLERS = {"openai", "minimax", "anthropic", "openrouter", "zai"}

def banner(title):
    print("\n" + "="*60)
    print(title)
    print("="*60)

def make_config(name, caller, default_model):
    """Helper to build LLMProviderConfig without shell-quoting nightmares."""
    return LLMProviderConfig(
        name=name,
        base_url="https://api.example.com/v1",
        api_key="sk-test-key",
        caller=caller,
        default_model=default_model,
        enabled=True,
    )

# ── Scenario 1: bogus caller in provider_cfg.caller ──
banner("Scenario 1: provider_cfg.caller = 'gpt-future' (unknown caller)")
p = make_config("rogue", "gpt-future", "openai/gpt-4o")
result = AgentRuntime._resolve_caller_key(p, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  In _PROVIDER_CALLERS: {result in _PROVIDER_CALLERS}")
verdict = "PASS — fails loudly" if result not in _PROVIDER_CALLERS else "FAIL — silently accepts bogus caller"
print(f"  VERDICT: {verdict}")

# ── Scenario 2: empty string caller (should fall through) ──
banner("Scenario 2: provider_cfg.caller = '' (empty, should fall through)")
p = make_config("empty", "", "openai/gpt-4o")
result = AgentRuntime._resolve_caller_key(p, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  Expected: 'openai' (derivation from default_model)")
print(f"  VERDICT: {'PASS' if result == 'openai' else 'FAIL'}")

# ── Scenario 3: None caller (should fall through) ──
banner("Scenario 3: provider_cfg.caller = None (should fall through)")
p = make_config("none", None, "openai/gpt-4o")
result = AgentRuntime._resolve_caller_key(p, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  Expected: 'openai' (derivation from default_model)")
print(f"  VERDICT: {'PASS' if result == 'openai' else 'FAIL'}")

# ── Scenario 4: provider_cfg None, model slashed ──
banner("Scenario 4: provider_cfg = None, model = 'openai/gpt-4o'")
result = AgentRuntime._resolve_caller_key(None, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  Expected: 'openai' (legacy model prefix)")
print(f"  VERDICT: {'PASS' if result == 'openai' else 'FAIL'}")

# ── Scenario 5: provider_cfg None, model no slash ──
banner("Scenario 5: provider_cfg = None, model = 'gpt-4o' (no slash)")
result = AgentRuntime._resolve_caller_key(None, "gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  Expected: 'gpt-4o' (legacy returns model as-is)")
print(f"  VERDICT: {'PASS' if result == 'gpt-4o' else 'FAIL'}")

# ── Scenario 6: mixed-case caller ──
banner("Scenario 6: provider_cfg.caller = 'OpenAI' (mixed case)")
p = make_config("mixed", "OpenAI", "openai/gpt-4o")
result = AgentRuntime._resolve_caller_key(p, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  Expected: 'openai' (lowercased)")
print(f"  In _PROVIDER_CALLERS: {result in _PROVIDER_CALLERS}")
print(f"  VERDICT: {'PASS' if result == 'openai' else 'FAIL'}")

# ── Scenario 7: default_model with multiple slashes ──
banner("Scenario 7: default_model = 'openrouter/owl/alpha' (multi-slash)")
p = make_config("multi", "", "openrouter/owl/alpha")
result = AgentRuntime._resolve_caller_key(p, "openrouter/owl/alpha")
print(f"  Resolved: {result!r}")
print(f"  Expected: 'openrouter' (first segment)")
print(f"  In _PROVIDER_CALLERS: {result in _PROVIDER_CALLERS}")
print(f"  VERDICT: {'PASS' if result == 'openrouter' else 'FAIL'}")

# ── Scenario 8: caller with whitespace ──
banner("Scenario 8: provider_cfg.caller = '  openai  ' (whitespace)")
p = make_config("ws", "  openai  ", "openai/gpt-4o")
result = AgentRuntime._resolve_caller_key(p, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  In _PROVIDER_CALLERS: {result in _PROVIDER_CALLERS}")
if result in _PROVIDER_CALLERS:
    print(f"  VERDICT: NOTE — whitespace stripped (probably not intended)")
else:
    print(f"  VERDICT: PASS — fails loudly on whitespace")

# ── Scenario 9: provider_cfg None, model empty ──
banner("Scenario 9: provider_cfg = None, model = '' (empty)")
try:
    result = AgentRuntime._resolve_caller_key(None, "")
    print(f"  Resolved: {result!r}")
    print(f"  In _PROVIDER_CALLERS: {result in _PROVIDER_CALLERS}")
    print(f"  VERDICT: {'PASS' if result not in _PROVIDER_CALLERS else 'FAIL'}")
except Exception as e:
    print(f"  Exception: {type(e).__name__}: {e}")
    print(f"  VERDICT: PASS — fails loudly")

# ── Scenario 10: caller with slash ──
banner("Scenario 10: provider_cfg.caller = 'openai/v2' (slash in caller)")
p = make_config("slash", "openai/v2", "openai/gpt-4o")
result = AgentRuntime._resolve_caller_key(p, "openai/gpt-4o")
print(f"  Resolved: {result!r}")
print(f"  In _PROVIDER_CALLERS: {result in _PROVIDER_CALLERS}")
print(f"  VERDICT: {'PASS — fails loudly' if result not in _PROVIDER_CALLERS else 'FAIL — slash accepted'}")

# ── Scenario 11: all 5 known callers round-trip ──
banner("Scenario 11: all 5 known callers round-trip correctly")
for caller in ["openai", "minimax", "anthropic", "openrouter", "zai"]:
    p = make_config(f"test-{caller}", caller, f"{caller}/model")
    result = AgentRuntime._resolve_caller_key(p, f"{caller}/model")
    ok = result == caller and result in _PROVIDER_CALLERS and result in _PROVIDER_STREAMERS
    print(f"  {caller}: resolved={result!r}, in callers={result in _PROVIDER_CALLERS}, in streamers={result in _PROVIDER_STREAMERS} → {'PASS' if ok else 'FAIL'}")

# ── Scenario 12: streamer lookup with None/empty caller_key ──
banner("Scenario 12: _PROVIDER_STREAMERS.get('') and .get(None)")
print(f"  _PROVIDER_STREAMERS.get(''): {_PROVIDER_STREAMERS.get('')!r}")
print(f"  _PROVIDER_STREAMERS.get(None): {_PROVIDER_STREAMERS.get(None)!r}")
print(f"  VERDICT: {'PASS — both return None' if _PROVIDER_STREAMERS.get('') is None and _PROVIDER_STREAMERS.get(None) is None else 'FAIL'}")

print("\n" + "="*60)
print("Audit complete.")
print("="*60)
