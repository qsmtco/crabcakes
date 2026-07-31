# SPEC: Pango Anchor Tag Fix

**Date:** 2026-07-30
**Author:** Supervisor (root cause discovered during GTK container membership fix loop)
**Status:** Ready for implementation
**Implements:** Fix for `Gtk-WARNING **: Failed to set text '...'` (invalid Pango markup)
**Depends on:** None
**Target branch:** main

> **Architecture compliance:** This fix touches only `utils/markdown.py` (the inline-markdown→Pango converter) and its tests. No layer violations. The converter remains pure Python with no GTK dependency.

---

## 1. Overview

### Problem
`format_markdown()` in `utils/markdown.py` generates `<a href="URL"><u>text</u></a>` anchor tags in four code paths (Step 3 markdown links, Step 3a angle-links, Step 3b href-protection, Step 4 auto-linking). **Pango's markup parser does not support the `<a>` element.** `Gtk.Label.set_markup()` / `Pango.parse_markup()` raises `g-markup-error-quark: Unknown tag 'a'` and rejects the **entire** markup string.

When this happens, the label fails to render and the user sees an empty or truncated bubble. This is the actual root cause of the "text cut off after a backtick / heading" symptom that the GTK container membership fix (a real but secondary bug) was originally attributed to.

### Root Cause (verified empirically)
Pango 1.52.1's markup format (`PangoMarkup`) supports these elements: `b`, `big`, `i`, `s`, `span`, `sub`, `sup`, `small`, `tt`, `u`. It does **not** support `<a>`. Any `<a>` tag — regardless of the href value or scheme — causes `Pango.parse_markup` to raise:

```
gi.repository.GLib.GError: g-markup-error-quark: Unknown tag 'a'
```

Verified via:
```python
import gi; gi.require_version('Pango', '1.0')
from gi.repository import Pango
Pango.parse_markup('<a href="x">y</a>', -1, '\x00')  # RAISES
Pango.parse_markup('<a href="https://x.com">y</a>', -1, '\x00')  # RAISES
Pango.parse_markup('<u>y</u>', -1, '\x00')  # ok=True
```

Clickability (`activate-link` signal handling in `make_safe_label`) was intended to make `<a>` work, but the markup is rejected by the parser **before** the signal handler ever runs. The HIGH-6 link-safety guard is therefore unreachable in the current architecture.

### Solution Summary
Replace all `<a href="URL"><u>text</u></a>` emission in `format_markdown()` with **`<u>text</u>`** (underlined, non-clickable). The HIGH-6 scheme validation (`_validate_link_url`) and warning prefix (`_WARNING_PREFIX`) are **preserved** — non-allowlisted schemes still render with the red ⚠ prefix; the URL itself just becomes non-clickable. This unblocks chat rendering immediately.

**Deferred (future spec):** Restore clickable links via `Pango.AttrType.LINK` attribute objects applied through `Gtk.Label.set_attributes()` / an `AttrList`, rather than via markup `<a>` tags. This is a separate, larger change requiring a rewrite of `make_safe_label` to accept both markup and an attribute list.

### Scope

| In scope | Out of scope |
|----------|-------------|
| `utils/markdown.py` — replace `<a href>` emission with `<u>text</u>` in Steps 3, 3a, 3b, 4 | `utils/gtk_safe_link.py` (`make_safe_label`, `on_activate_link`) — unchanged for now |
| `tests/test_markdown.py` — update ~30 assertions from `<a href>` to `<u>` | `tests/test_escaping.py` — `escape_for_pango` still preserves `<a>` (its behavior is orthogonal; it operates on raw HTML passthrough, not Pango generation) |
| Restore chat rendering (Pango accepts `<u>` but not `<a>`) | Clickable links via Pango `AttrType.LINK` (future spec) |
| HIGH-6 validation + warning prefix preserved | Removing HIGH-6 validation |

---

## 2. Changes by File

### 2.1 `utils/markdown.py`

**Total changes:** 4 emission sites edited, ~4 lines changed. The `_validate_link_url`, `_WARNING_PREFIX`, `_ALLOWED_LINK_SCHEMES`, and `_AUTO_LINK_RE` definitions are UNCHANGED.

The strategy: each site currently builds `anchor_html = f'<a href="{safe_url}"><u>{label}</u></a>'` and optionally prepends `_WARNING_PREFIX`. The fix: build `anchor_html = f'<u>{label}</u>'` instead (drop the `<a href>` wrapper, keep the `<u>` underline, keep the warning prefix logic).

#### Site 1 — Step 3: markdown links `[text](url)` (line ~231)

**Current:**
```python
        anchor_html = f'<a href="{safe_url}"><u>{label}</u></a>'
        # HIGH-6: prepend red warning prefix for non-allowlisted schemes
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
```

**Fixed:**
```python
        # Pango does NOT support <a href> in markup (Unknown tag 'a').
        # Render links as underlined text. HIGH-6 validation preserved:
        # non-allowlisted schemes still get the red warning prefix.
        anchor_html = f'<u>{label}</u>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
```

#### Site 2 — Step 3a: angle-bracket auto-links `<https://...>` (line ~258)

**Current:**
```python
        anchor_html = f'<a href="{safe_href}"><u>{display_url}</u></a>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
```

**Fixed:**
```python
        anchor_html = f'<u>{display_url}</u>'
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        anchor_spans.append(anchor_html)
        return f'\x00ANCHOR{len(anchor_spans) - 1}\x00'
```

#### Site 3 — Step 4: bare-URL auto-linking (line ~300)

**Current:**
```python
        anchor_html = f'<a href="{safe_url}"><u>{url}</u></a>'
        # HIGH-6: prepend red warning prefix for non-allowlisted schemes
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        return anchor_html
```

**Fixed:**
```python
        anchor_html = f'<u>{url}</u>'
        # HIGH-6: prepend red warning prefix for non-allowlisted schemes
        if not _validate_link_url(url):
            anchor_html = _WARNING_PREFIX + anchor_html
        return anchor_html
```

#### Site 4 — Step 3b: href-protection (line ~275)

Step 3b protects URLs inside pre-existing `href="..."` attributes so Step 4 doesn't double-link them. After this fix, `format_markdown` no longer emits `<a>` tags at all, so pre-existing `<a>` tags from `escape_for_pango`'s passthrough are the only remaining source.

**Decision:** Leave Step 3b as-is for now. It protects pre-existing `href="URL"` from being re-auto-linked by Step 4 (which would wrap them in `<u>`, creating nested markup). The protection is still correct even though we no longer emit `<a>`. The pre-existing `<a>` tags (from `escape_for_pango` preserving `<a href>` passthrough) will still be rejected by Pango — but that is a separate concern (raw HTML in user input), and `escape_for_pango` already handles it by escaping orphan/invalid `<a>` tags.

**Action for Site 4:** No code change. Document in a comment that the protection still applies.

### 2.2 `tests/test_markdown.py`

**Total changes:** ~30 assertions updated. Each `assert '<a href="...">' in result` becomes `assert '<u>' in result` (the URL text is now underlined, not wrapped in an anchor). The HIGH-6 warning tests update from checking `_WARNING_PREFIX + '<a href'` to `_WARNING_PREFIX + '<u>'`.

**Guiding principles for test updates:**
1. Tests that asserted `'<a href="URL">' in result` → change to assert `'<u>URL_text</u>' in result` (the visible text, underlined).
2. Tests that asserted the `_WARNING_PREFIX` appears for non-allowlisted schemes → unchanged (the prefix logic is preserved).
3. Tests that asserted `<a href>` does NOT appear (nested-link prevention) → change to assert `<u>` count is correct (no nested underlines).
4. The test name `test_link_basic` etc. stay; only the assertion values change.

---

## 3. Acceptance Criteria

### Production code
- [ ] No `<a href` emission remains in `format_markdown()` (grep returns zero)
- [ ] All 4 emission sites (Steps 3, 3a, 4; Step 3b left as-is) produce `<u>text</u>` instead
- [ ] `_validate_link_url` and `_WARNING_PREFIX` are unchanged and still invoked
- [ ] HIGH-6 warning prefix still prepended for non-allowlisted schemes

### Tests
- [ ] All `tests/test_markdown.py` assertions updated and passing
- [ ] New test added: `format_markdown` output for a link-containing message passes `Pango.parse_markup` without error (regression guard — requires importing Pango, may need to be marked `gtk` or run conditionally)

### Verification
- [ ] `grep -n "<a href" utils/markdown.py` returns zero matches
- [ ] `python3 -m pytest tests/test_markdown.py -v` — all pass
- [ ] Empirical: a message containing `context.md` or `http://example.com` no longer triggers `Gtk-WARNING **: Failed to set text`

---

## 4. Why Not Restore Clickability Now?

Pango's clickable-link support uses `Pango.AttrType.LINK` attribute objects (applied via an `AttrList` on `Gtk.Label.set_attributes`), NOT markup tags. Restoring clickability requires:

1. Rewriting `format_markdown` to return both markup AND a list of link spans (text + URL + offset)
2. Rewriting `make_safe_label` to accept the markup + link spans, build an `AttrList`, and apply both `set_markup` and `set_attributes`
3. Rewriting `process_segments` / `build_role_bubble` to thread the link spans through the segment pipeline
4. Updating all callers

This is a 4-6 hour change touching 4+ files. The current fix (drop `<a>`, keep `<u>`) is a 30-minute change touching 1 file + tests. **Chat is broken right now** — unblocking it takes priority.

---

## 5. Edge Cases

| Case | Before fix | After fix |
|------|-----------|-----------|
| `[click](https://example.com)` | `<a href="..."><u>click</u></a>` → Pango rejects | `<u>click</u>` → renders underlined |
| bare `https://example.com` | `<a href="..."><u>https://example.com</u></a>` → Pango rejects | `<u>https://example.com</u>` → renders underlined |
| bare `context.md` (filename misdetected as hostname) | `<a href="context.md"><u>context.md</u></a>` → Pango rejects | `<u>context.md</u>` → renders underlined (filename no longer crashes) |
| `javascript:alert(1)` | `⚠ <a href="...">...</a>` → Pango rejects | `⚠ <u>javascript:alert(1)</u>` → renders with warning prefix |
| `<https://example.com>` (angle auto-link) | `<a href="..."><u>https://example.com</u></a>` → Pango rejects | `<u>https://example.com</u>` → renders underlined |
| No links in message | unaffected | unaffected |
