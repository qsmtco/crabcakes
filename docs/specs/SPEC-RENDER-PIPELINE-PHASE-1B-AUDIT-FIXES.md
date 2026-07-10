# PHASE 1b (Audit Fixes) — Restore Escaping Invariants

**Spec:** `docs/specs/SPEC-RENDER-PIPELINE-INVARIANTS.md` (audit follow-up)
**Files to change:** `utils/escaping.py`

Debugger found 2 critical regressions introduced by the Coder's changes.

---

## BUG #1 — Ampersand in attribute values no longer escaped

**Current (broken):**
The `_escape_attr_ampersands` inner function has `return amp.replace("&", "&")` — a no-op.

**Fix:** Change back to `return amp.replace("&", "&amp;")`.

Search for the `_escape_attr_ampersands` function inside `escape_for_pango`. The replace call should produce `&amp;`, not `&`.

---

## BUG #2 — Literal `<` no longer escaped (3 sites)

**Current (broken):**
Three places where `result.append("&lt;")` was changed to `result.append("<")`.

**Fix:** Change all three back to `result.append("&lt;")`.

Search for `result.append("<")` in `utils/escaping.py` and change each to `result.append("&lt;")`.

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read `utils/escaping.py` before editing.
- Do NOT change anything else. These are 4-character fixes.

## Verification

```bash
cd /home/q/projects/crabcakes

# BUG #1
python3 -c "
from utils.escaping import escape_for_pango
result = escape_for_pango('<a href=\"https://x.com/?a=1&b=2\">x</a>')
assert '&amp;' in result, f'Ampersand not escaped: {result!r}'
print('OK: ampersand escaped')
"

# BUG #2
python3 -c "
from utils.escaping import escape_for_pango
assert escape_for_pango('text <') == 'text &lt;', repr(escape_for_pango('text <'))
print('OK: literal < escaped')
"

# Regression: uppercase tags still work
python3 -c "
from utils.escaping import escape_for_pango
assert escape_for_pango('<B>orphan</B>') == '<b>orphan</b>'
print('OK: uppercase normalization still works')
"

# All tests
python3 -m pytest tests/test_escaping.py tests/test_markdown.py -v -k "not test_markup_passes_pango_validation"
```
