# Phase 1+2 Combined Audit Brief — Pango Placeholder + Escape Fix

## Scope
Two files, two edits (already applied and committed):

### Edit 1 (Phase 1): `utils/escaping.py`
Removed `"a"` from `_PANGO_KNOWN_TAGS`. Now `escape_for_pango` escapes `<a>` to `&lt;a&gt;`.

### Edit 2 (Phase 2): `utils/markdown.py`
Added `_resolve_code_in_label` helper (line 226) inside `format_markdown`. Added `label = _CODE_PLACEHOLDER_RE.sub(_resolve_code_in_label, label)` (line 251) in Step 3's `_link_replace_and_protect`. Resolves code-span placeholders (`\x00CODE{N}\x00`) in markdown link labels to `<tt>code</tt>` before storing in `anchor_html`.

## The bugs being fixed

### Bug A: escape_for_pango preserves unsupported `<a>` tag
Pango 1.52 does NOT support `<a>` in markup. `_PANGO_KNOWN_TAGS` included `"a"`, so `escape_for_pango` passed `<a href="...">` through unchanged. It reached `set_markup` and Pango rejected it. Fix: remove `"a"` from the known set.

### Bug B: Step 3 placeholder-shadowing
When a markdown link label is a code span (`[`code`](url)`), Step 1 replaces it with `\x00CODE0\x00`, Step 3 captures the placeholder as the label, stores it in `anchor_html`. Step 5 can't restore it (consumed from `protected`). Null bytes reach Pango's C-string parser → truncation → unclosed `<u>`. Fix: resolve placeholders in the label before storing.

## Impact (measured against 348-message real conversation)
- Before: 45 segments rejected by Pango
- After Phase 1: 14 rejected
- After Phase 1+2: 4 rejected (all pre-existing data — literal `<a href` in old debug messages)

## Key questions for the auditor
1. Does `_resolve_code_in_label` correctly mirror Step 5's `_restore_code` logic (the `if '&' in content` escape check)?
2. Could `_resolve_code_in_label` produce a malformed `<u><tt>...</tt></u>` nesting that Pango rejects?
3. Does removing `"a"` from `_PANGO_KNOWN_TAGS` have any unintended consequence on the orphan-tag sweep or the nested-tag-preservation logic in `escape_for_pango`?
4. Are there other Step 3 paths (Step 3a angle-links, Step 4 auto-links) that could ALSO receive code-span placeholders and need the same fix?
5. Does the fix handle the case where the ENTIRE label is a placeholder vs. the placeholder is EMBEDDED in longer text (e.g. `[pre \`code\` post](url)`)?

Report BUG #[N] or 'no bugs found'.
