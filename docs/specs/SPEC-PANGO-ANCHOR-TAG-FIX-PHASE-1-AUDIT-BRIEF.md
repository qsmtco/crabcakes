# Phase 1 Audit Brief — Pango Anchor Tag Fix

## Scope
`utils/markdown.py` ONLY. Three edits (already applied, committed at `3157917`).

## The bug being fixed
Pango's markup parser does NOT support the `<a>` element. Any `<a href="...">`
tag in markup causes `Gtk.Label.set_markup()` / `Pango.parse_markup()` to raise
`g-markup-error-quark: Unknown tag 'a'` and reject the ENTIRE markup string.
Result: the user sees an empty or truncated chat bubble. This is the root cause
of the "text cut off after a backtick" symptom.

Verified empirically:
```
Pango.parse_markup('<a href="x">y</a>', -1, '\x00')  # RAISES Unknown tag 'a'
Pango.parse_markup('<u>y</u>', -1, '\x00')            # ok=True
```

## The three edits

Each edit replaces an `anchor_html` assignment that built an `<a href>` tag
with one that builds just `<u>text</u>` (underlined, non-clickable). The
HIGH-6 `_validate_link_url` check and `_WARNING_PREFIX` are PRESERVED in all
three sites.

### Site 1 — Step 3, markdown links (line 235)
```python
# BEFORE:
anchor_html = f'<a href="{safe_url}"><u>{label}</u></a>'
# AFTER:
anchor_html = f'<u>{label}</u>'
```

### Site 2 — Step 3a, angle-bracket auto-links (line 262)
```python
# BEFORE:
anchor_html = f'<a href="{safe_href}"><u>{display_url}</u></a>'
# AFTER:
anchor_html = f'<u>{display_url}</u>'
```

### Site 3 — Step 4, bare-URL auto-linking (line 304)
```python
# BEFORE:
anchor_html = f'<a href="{safe_url}"><u>{url}</u></a>'
# AFTER:
anchor_html = f'<u>{url}</u>'
```

## What is PRESERVED (must NOT be removed)
- `_validate_link_url(url)` — called in all 3 sites (lines 237, 263, 306)
- `_WARNING_PREFIX` — prepended for non-allowlisted schemes
- `_ALLOWED_LINK_SCHEMES` (http, https, mailto)
- Step 3b href-protection logic (protects pre-existing `href="URL"` from Step 4 re-linking)

## What is intentionally LOST (deferred to future spec)
- Link clickability. Links now render as underlined text, not clickable anchors.
  Restoring clickability requires Pango `AttrType.LINK` attribute objects (a
  larger future change to `make_safe_label`).

## Key questions for the auditor
1. Is any link-text or URL information LOST that should be preserved? (e.g.,
   does dropping href break the `_WARNING_PREFIX` semantics — is the warning
   still meaningful without the link?)
2. Are `safe_url` / `safe_href` now unused variables? Could they cause issues?
   (They were used inside the `<a href="{safe_url}">` string.)
3. Did the Step 3b href-protection logic break now that no `<a>` is emitted
   downstream? Does protecting a `href="URL"` still make sense?
4. Any escape-ordering regression? (escape_for_pango runs before format_markdown;
   does removing `<a>` change the escaping contract?)
5. Any re-entrancy or thread-safety concern with the closure-mutated lists
   (code_spans, anchor_spans)?

## Success criteria
- `Pango.parse_markup` accepts the output of `format_markdown` for any
  link-containing input (verified: ok=True)
- HIGH-6 validation still triggers `_WARNING_PREFIX` for non-allowlisted schemes
- No `<a href` in executable code (comments/docstrings OK)
- `tests/test_markdown.py` will be updated in Phase 2 (not this phase)

## Spec
Full spec: `docs/specs/SPEC-PANGO-ANCHOR-TAG-FIX.md`
