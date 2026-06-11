# PHASE 10 — P6: test_connection caller kwarg

**Master spec:** `docs/specs/PHASE-10-PROVIDER-CALLER-FIELD.md` (read this FIRST)
**Phase scope:** Section 2.7 of the master spec

---

## Files to change

1. `utils/provider_test.py` — add `caller: str | None = None` kwarg to `test_connection`
2. `ui/handlers/settings_handler.py` — pass `caller=provider.caller` to `test_connection`

## What to do

**In `utils/provider_test.py`:**

Find the `test_connection` function signature (line ~60):
```python
def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
) -> TestResult:
```

Replace with:
```python
def test_connection(
    base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 8.0,
    caller: str | None = None,          # PHASE-10: explicit caller key from ProviderConfig
) -> TestResult:
```

Find the provider detection line (line ~76):
```python
    provider = _provider_name(model).lower()
    bare_model = _model_id(model)
```

Replace with:
```python
    # PHASE-10: prefer explicit caller when provided; fall back to model prefix derivation
    if caller:
        provider = caller.lower()
    else:
        provider = _provider_name(model).lower()
    bare_model = _model_id(model)
```

**In `ui/handlers/settings_handler.py`:**

Find the `test_connection` call inside `test_provider._worker` (line ~136):
```python
                result = test_connection(
                    base_url=provider.base_url,
                    api_key=***
                    model=provider.default_model,
                )
```

Replace with:
```python
                result = test_connection(
                    base_url=provider.base_url,
                    api_key=***
                    model=provider.default_model,
                    caller=provider.caller or None,
                )
```

**Why `provider.caller or None`:** `ProviderConfig.caller` defaults to `""`. We want to pass `None` to `test_connection` when the field is empty so the function falls back to its `model.split("/")[0]` derivation (the legacy behavior for callers that don't have a caller set).

## Rules

- Use the steelFramedCodeWriter prompt at `/home/q/projects/crabcakes/prompts/steelFramedCodeWriter.md`
- Read `utils/provider_test.py` lines 55-85 COMPLETELY before editing
- Read `ui/handlers/settings_handler.py` lines 130-145 COMPLETELY before editing
- Make ONLY the 2 edits described above
- Do NOT touch `_test_openai_compat`, `_test_anthropic`, `_model_id`, or `_provider_name`
- Do NOT touch `_do_request`
- Do NOT change the function call site in `agent_runtime_handler.py` (it's outside scope for P6)

## Verification (mandatory — paste full output)

```bash
cd /home/q/projects/crabcakes
python3 -c "
import inspect
from utils.provider_test import test_connection
sig = inspect.signature(test_connection)
# Verify caller kwarg exists
assert 'caller' in sig.parameters, 'caller kwarg missing from test_connection'
# Verify default is None
assert sig.parameters['caller'].default is None, 'caller default should be None'
# Verify caller comes after timeout_seconds
params = list(sig.parameters.keys())
assert params.index('caller') > params.index('timeout_seconds'), 'caller must come after timeout_seconds'
print('P6 source check: caller kwarg added with default=None, positioned correctly')
"
```

```bash
cd /home/q/projects/crabcakes
grep -n "caller" ui/handlers/settings_handler.py | head -10
```

Expected: at least 2 matches — the new `caller=provider.caller or None` line and the new `# PHASE-10: auto-detect caller` comment block from the earlier P5 fix.

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_provider_test.py -q 2>&1 | tail -6
```

If `test_provider_test.py` doesn't exist:
```bash
ls /home/q/projects/crabcakes/tests/ | grep -i provider
```

```bash
cd /home/q/projects/crabcakes
timeout 30 python3 -m pytest tests/test_settings_handler.py -q 2>&1 | tail -6
```

## Report

- Files changed with line numbers
- Full verification output
- Grep output
- Pytest output
- A COMPLETENESS checklist (mandatory)

## Known-good word marker

Please proceed.