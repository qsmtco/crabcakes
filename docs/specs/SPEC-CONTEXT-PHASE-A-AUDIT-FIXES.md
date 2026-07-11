# PHASE A Audit Fixes — 4 bugs to fix

**File:** `ui/handlers/agent_runtime_handler.py`, `ui/views/main_content.py`, `ui/views/settings_dialog.py`

---

## BUG #1 — _on_token_breakdown uses subscript access on required keys

**File:** `ui/handlers/agent_runtime_handler.py`

The logger.info call uses `breakdown["system_prompt_tokens"]` etc. If any key is missing, KeyError crashes the entire handler.

**Fix:** Wrap the entire `_on_token_breakdown` body in try/except. Or replace all `breakdown["key"]` with `breakdown.get("key", 0)`. The simplest approach:

At the top of the method body (after the docstring), add:
```python
        try:
```
And indent the rest of the method body. At the very end, add:
```python
        except Exception:
            logger.exception("_on_token_breakdown: failed for %s", session_key)
```

This matches the pattern already used for `_on_token_breakdown_extra` at line 1322.

---

## BUG #2 — set_context_meter doesn't handle None or NaN

**File:** `ui/views/main_content.py`

The guard `usage_percent < 0` raises TypeError on None, and NaN passes through to GTK.

**Fix:** Replace the guard at the top of `set_context_meter` with:

```python
        if usage_percent is None or not isinstance(usage_percent, (int, float)):
            self._context_meter.set_fraction(0.0)
            self._context_meter_label.set_text("")
            return
        if usage_percent != usage_percent:  # NaN check
            self._context_meter.set_fraction(0.0)
            self._context_meter_label.set_text("")
            return
        if usage_percent < 0:
            self._context_meter.set_fraction(0.0)
            self._context_meter_label.set_text("")
            return
```

---

## BUG #4 — _is_dirty doesn't check compaction_threshold

**File:** `ui/views/settings_dialog.py`

Find the `_is_dirty` method. Add a check for the threshold spin:

```python
        or float(self._compaction_threshold_spin.get_value()) != (p.compaction_threshold or 0.80)
```

Add this to the existing `or` chain in `_is_dirty`.

---

## BUG #5 — _populate_from_provider doesn't update threshold spin

**File:** `ui/views/settings_dialog.py`

Find `_populate_from_provider`. Add this line near the existing `self._max_tokens_spin.set_value(...)` line:

```python
        self._compaction_threshold_spin.set_value(p.compaction_threshold or 0.80)
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read each file before editing.
- These are 4 small mechanical fixes.

## Verification

```bash
cd /home/q/projects/crabcakes

# 1. Syntax
python3 -c "import ast; [ast.parse(open(f).read()) for f in ['ui/handlers/agent_runtime_handler.py', 'ui/views/main_content.py', 'ui/views/settings_dialog.py']]; print('SYNTAX OK')"

# 2. _on_token_breakdown has try/except
grep -n "except.*_on_token_breakdown\|except.*token_breakdown" ui/handlers/agent_runtime_handler.py

# 3. set_context_meter handles None
grep -n "is None\|not isinstance" ui/views/main_content.py | grep context_meter

# 4. _is_dirty checks threshold
grep -n "compaction_threshold" ui/views/settings_dialog.py | grep -i dirty

# 5. _populate_from_provider sets threshold
grep -n "compaction_threshold_spin.set_value" ui/views/settings_dialog.py
```
