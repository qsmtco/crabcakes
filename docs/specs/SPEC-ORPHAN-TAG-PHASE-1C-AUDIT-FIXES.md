# PHASE 1c (Audit Fixes) — Auto-Link Entity Blindness + Test Gap

**Spec:** `docs/specs/spec-orphan-tag-autolink.md` (audit follow-up)
**Files to change:** `utils/markdown.py`, `tests/test_escaping.py`

---

## BUG #2 — Auto-link regex matches through `&quot;`

**File:** `utils/markdown.py`

**Problem:** When `escape_for_pango` escapes an orphan `<a href="URL">` to `&lt;a href=&quot;URL&quot;&gt;`, `format_markdown`'s auto-link regex sees `URL&quot;` as a URL (because `&`, `q`, `u`, `o`, `t`, `;` are all valid URL characters). This produces corrupt Pango markup.

**Root cause:** The `_AUTO_LINK_RE` URL character class `[^\s<>"\`'\[\]()]` excludes literal `<`, `>`, `"`, `'` but does NOT exclude `&`. After `escape_for_pango`, quotes are `&quot;` and angle brackets are `&lt;`/`&gt;` — the regex doesn't recognize these as delimiters.

**Fix:** Add `&` to the exclusion set in BOTH URL capture groups in `_AUTO_LINK_RE`. This prevents the regex from matching through HTML entities. Legitimate URLs don't contain `&` followed by entity-like text in a way that would be broken by this — `&` in query strings (`?a=1&b=2`) is already escaped to `&amp;` by `escape_for_pango` before `format_markdown` sees it, and `&amp;` would now stop the match. That's correct — the URL `https://example.com?a=1&amp;b=2` should match as `https://example.com?a=1` (the `&amp;` marks the boundary between URL and non-URL content in the escaped text).

**Read the current regex at `utils/markdown.py` around line 36-42 first.**

**Current:**
```python
_AUTO_LINK_RE = re.compile(
    r'(?<![a-zA-Z0-9/:=])'  # not preceded by alphanum, ://, or = (href="URL")
    r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"`\'\[\]()+)'
    r'|'
    r'(?<!["\'])'
    r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>"`\'\[\]()]+))'
    , re.IGNORECASE
)
```

Wait — actually `(` and `)` are already excluded in the current regex but NOT in the exclusion set shown above. Let me check the actual source. The exclusion set may differ. Read the file before editing.

**Change:** Add `&` to both URL character classes. The character class `[^\s<>"\`'\[\]()]` becomes `[^\s<>"\`'\[\]()&]`.

---

## BUG #3 — Uppercase tag pair test gap

**File:** `tests/test_escaping.py` — add to `TestOrphanTagSweep` class.

```python
    def test_uppercase_tag_pair_preserved(self):
        """Pango is case-insensitive on tag names. Uppercase pairs preserved."""
        assert escape_for_pango("<B>orphan</B>") == "<B>orphan</B>"
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- Read `utils/markdown.py` lines 36-42 before editing.
- Do NOT touch anything other than the regex and the test.

## Verification commands

```bash
cd /home/q/projects/crabcakes

# 1. Orphan href doesn't corrupt markdown
python3 -c "
from utils.escaping import escape_for_pango
from utils.markdown import format_markdown
result = format_markdown(escape_for_pango('Found <a href=\"https://x.com\"> in text'))
# Should NOT contain nested <a> tags
assert result.count('<a ') <= 1, f'Nested <a>: {result}'
# Should NOT contain &quot; inside an href
assert 'href=\"https://x.com' not in result or result.count('<a ') == 0, f'Corrupt href: {result}'
print('OK: orphan href does not corrupt markdown')
"

# 2. Plain URLs still link
python3 -c "
from utils.markdown import format_markdown
result = format_markdown('check https://example.com for info')
assert '<a href=\"https://example.com\">' in result
print('OK: plain URLs still link')
"

# 3. All escaping + markdown tests pass
python3 -m pytest tests/test_escaping.py tests/test_markdown.py -v -k "not test_markup_passes_pango_validation"
```

## Deliverables

```
COMPLETENESS:
- [x/not done] BUG #2: & added to auto-link exclusion set — evidence: (command 1)
- [x/not done] BUG #3: uppercase test added — evidence: (command 3)
- [x/not done] Plain URLs still link — evidence: (command 2)
```
