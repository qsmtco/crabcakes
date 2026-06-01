# Phase 5 Instructions — Fix test_agent_command_handler.py

## Context
2 tests fail because `resolve_default_target_role()` now returns `"crabcakes"` instead of `"unknown"`. The function finds the crabcakes agent as a writing agent in the user's config. The tests expect `"unknown"`.

## Root Cause
- `test_audit_report_logged_to_review_log` (line 817): asserts `entries[0]["target_role"] == "unknown"`
- `test_audit_report_emits_feed_card_callback` (line 959): asserts `report["target_role"] == "unknown"`
- Both tests create `AgentCommandHandler()` with no agent runtime handler, so `_resolve_target_role` calls `resolve_default_target_role()` which returns `"crabcakes"` from user config.

## Strategy
Patch `utils.feedback_processor.resolve_default_target_role` to return `"unknown"` so the tests are isolated from the agent registry.

**CRITICAL — patch target verification:**
The function `resolve_default_target_role` is defined in `utils/feedback_processor.py` at line 86.
It is imported INSIDE `_resolve_target_role` method at `agent_command_handler.py:483`:
```python
from utils.feedback_processor import (
    resolve_default_target_role,
    ...
)
```
Because it's imported inside the method (not at module level), we patch at the SOURCE module:
`patch("utils.feedback_processor.resolve_default_target_role", return_value="unknown")`

This works because the import gets the function object from the module, and patching the module attribute replaces what the import retrieves.

## Implementation

### Test 1: `test_audit_report_logged_to_review_log` (around line 788)

Wrap the `on_agent_response` call in a patch:

Find the line:
```python
handler.on_agent_response("session:qaster:123", text, "test-project")
```

Change to:
```python
from unittest.mock import patch
with patch("utils.feedback_processor.resolve_default_target_role", return_value="unknown"):
    handler.on_agent_response("session:qaster:123", text, "test-project")
```

Everything else in the test stays the same.

### Test 2: `test_audit_report_emits_feed_card_callback` (around line 930)

Same pattern — find:
```python
handler.on_agent_response("session:qaster:123", text, "test-project")
```

Change to:
```python
from unittest.mock import patch
with patch("utils.feedback_processor.resolve_default_target_role", return_value="unknown"):
    handler.on_agent_response("session:qaster:123", text, "test-project")
```

Everything else stays the same.

## Verification
```bash
python3 -m pytest tests/test_agent_command_handler.py -q --tb=short
```
Expected: all tests pass, 0 failures.
