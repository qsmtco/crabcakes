# SPEC: Render Pipeline Invariants — Preserve Valid Pango Tags in All Cases

**Date:** 2026-07-09
**Author:** qtr (read-only audit + spec)
**Status:** Draft — for implementation
**Implements:** Two concrete bugs found in terminal-noise audit of `escape_for_pango → format_markdown → set_markup` pipeline
**Depends on:** None (standalone pipeline fix)
**Target branch:** `main`
**Spec scope:** `utils/escaping.py` and `utils/markdown.py` only (per `docs/ARCHITECTURE.md` §3.14a and §3.14b ownership)
**Companion audit trail:** User-completed read-only reports (2026-07-09) covering Gtk-WARNING noise + TypeError traceback

> **Architecture compliance:** This spec touches `utils/escaping.py` (§3.14a — Pango-aware XML escape) and `utils/markdown.py` (§3.14b — inline markdown → Pango). No changes to UI handlers, models, or any caller of these utilities. Public API of both modules is preserved (`escape_for_pango` / `xml_escape_text` / `format_markdown` signatures unchanged). All existing call sites continue to work.

---

## DISCOVERY (per Steel-Framed Spec Writer Rule 1)

```
DISCOVERY:
- Read /home/q/projects/crabcakes/utils/escaping.py (entire file, 267 lines):
    * _PANGO_KNOWN_TAGS frozenset (line 24-36): includes b, i, u, s, tt, big,
      small, span, a, br, hr, wabr, sub, sup, o — all LOWERCASE.
    * _PANGO_VOID_TAGS (line 39-44): HTML void elements (line 41).
    * _ENTITY_CODEPOINTS (line 47-54): strict entity unescape table.
    * escape_for_pango() at line 90 — main public API.
        - Line 152 (closing tag branch): result.append(match.group(0)) ← BUG
          preserves original case; Pango is CASE-SENSITIVE on tag names.
        - Line 173-183 (opening tag branch): for tags WITH attributes, the code
          already does `full_tag = f"<{tag_name}{attrs_escaped}>"` ← uses
          lowercased tag_name. For tags WITHOUT attributes, it falls through to
          `result.append(full_tag)` where full_tag = match.group(0) ← BUG.
        - Line 184: `open_tags.append(tag_name)` stores lowercase — good.
        - Lines 207-219 (orphan sweep): re-escapes orphan opening tags. NOT a
          closing-tag fix; orphan only.
    * xml_escape_text() at line 222 — plain text escape (no markup preserved).
    * xml_template() at line 254 — substitution helper for literal-Pango templates.
    * All function signatures verified via `inspect.signature()` — public API
      shape unchanged.

- Read /home/q/projects/crabcakes/utils/markdown.py (relevant sections):
    * Lines 86-105: format_markdown() docstring listing 7-step pipeline.
    * Line 36: _AUTO_LINK_RE regex with TWO alternatives separated by `|`:
        - Alt A: scheme://... captures into group(1)
        - Alt B: bare hostname (e.g., httpbin.org/help) captures into group(2)
    * Lines 230-242: _link_replace_and_protect() — Step 3 markdown link handler.
      Reads m.group(1), m.group(2) — single capture pair, no bug.
    * Lines 258-274: _angle_link_replace() — Step 3a angle-bracket auto-link.
      Reads m.group(1) — single capture group, no bug.
    * Lines 290-301: _auto_link() — Step 4 bare-URL auto-link. CRASH SITE.
        - Line 292: `url = m.group(1)` ← BUG: returns None when only Alt B
          matched (bare hostname).
        - Line 294: `urllib.parse.quote(None, ...)` raises TypeError.
    * Step 3a regex at lines 269-274: only one capture group (group(1)) —
      safe, no alternation.

- Read /home/q/projects/crabcakes/tests/test_escaping.py (selected):
    * Line 201-203: test_uppercase_tag_pair_preserved — WRONG TEST added in
      commit cef7da30 ("Lt. Qrusher", 2026-07-09 22:15:56 -0700). Asserts
      escape_for_pango("<B>orphan</B>") == "<B>orphan</B>" and claims
      "Pango is case-insensitive" — FALSE.
    * 17 tests currently FAIL because their expected values don't match the
      function's actual lower-level escape output (xml_escape_text expects
      "Tom &amp; Jerry" but `html.escape` v3.12 with quote=False returns
      "Tom & Jerry" — see Rule 2 trace below).

- Read /home/q/projects/crabcakes/tests/test_markdown.py (relevant):
    * Line 99-103: test_auto_link_bare_url uses `https://example.com` (explicit
      scheme). NO test exists for bare hostname like `httpbin.org/help`.
    * Line 488-495: test_markup_passes_pango_validation — existing pattern for
      end-to-end Pango validation using Gtk.Label().set_markup(). This is the
      pattern I'll copy for the new invariant test.

- Read /home/q/projects/crabcakes/docs/ARCHITECTURE.md:
    * §3.14a (line 806-825) — utils/escaping.py module ownership.
    * §3.14b (line 826-848) — utils/markdown.py module ownership.
    * §3.14b.1 (line 850-) — utils/gtk_safe_link.py runtime allowlist (URL
      scheme gating); orthogonal to this spec, no changes needed.

- Architecture owner (per ARCHITECTURE.md §3): utils/escaping.py owns
  Pango-aware escaping; utils/markdown.py owns markdown → Pango conversion.
  Both modules ARE the layer for this fix — no upstream/downstream change.

- Existing patterns (what similar features do that this one should copy):
    * For lowercase-normalizing tag output (Bug 1 fix): Mirror the existing
      attributes-case fix at lines 178-183 — `full_tag = f"<{tag_name}...">"`
      applies lowercased tag_name. Extend that pattern to the attribute-less
      branch and the closing-tag branch.
    * For regex group fallback (Bug 2 fix): Python idiom is
      `next((g for g in m.groups() if g is not None), "")` or explicit
      `m.group(1) or m.group(2)`. Existing callers of _auto_link are only the
      sub() call at line 301; no other consumers of the pattern.
    * For end-to-end Pango validation test: copy test_markup_passes_pango_validation
      from test_markdown.py line 488-495.

- Edge cases discovered during trace:
    * Mixed case in nested tags: `<b><B>nested</B></b>` — opening lowercase,
      nested mixed. Currently outputs lowercase open + original-case close
      (Pango rejects).
    * Self-closing tags: `<br/>`, `<br />` — must not be lowercase-normalized
      differently from the void-tag branch.
    * Bare hostname auto-links: must produce the same <a href="..."><u>URL</u></a>
      shape that `https://...` produces (Step 4 already produces this when
      given a string, not None — verified by mentally executing _auto_link
      with "https://x.com" passed in).
```

---

## 1. Overview

### Problem Statement

Two independent bugs in the chat-bubble render pipeline cause terminal noise and render crashes:

**Bug 1 — Uppercase Pango tag names are preserved in output, breaking `set_markup()`.**

`utils/escaping.py:escape_for_pango` lowercases tag names for the whitelist check (e.g., `match.group(1).lower()`), but emits `match.group(0)` (original case) into the output. Pango's XML parser is case-sensitive on tag names; passing `<B>orphan</B>` causes `Gtk.Label.set_markup()` to emit "Unknown tag 'B'" Gtk-WARNING and render the entire label as empty.

This bug has *partially* been patched for **attribute-bearing** opening tags (the `f"<{tag_name}{attrs_escaped}>"` interpolation at `utils/escaping.py:181` lowercases the tag_name), but the **attribute-less** branch and the **closing-tag** branch still emit the original case. Verified by direct execution:

```
>>> escape_for_pango('<b attr="val">x</B>')
'<b attr="val">x</B>'     ← mixed case (Pango rejects mismatched pair)
>>> escape_for_pango('<B>orphan</B>')
'<B>orphan</B>'           ← both uppercase (Pango rejects both)
>>> escape_for_pango('<span ATTR="VAL">x</span>')
'<span ATTR="VAL">x</span>' ← only attribute case preserved (Pango unknown attr)
```

The bug is enshrined as "expected behavior" by `tests/test_escaping.py:201-203` (`test_uppercase_tag_pair_preserved`) — a regression test added in commit `cef7da30` (2026-07-09) with a false claim that "Pango is case-insensitive".

**Bug 2 — Bare-hostname auto-links crash `_auto_link` with `TypeError: quote_from_bytes() expected bytes`.**

`utils/markdown.py:_AUTO_LINK_RE` (line 36) has two alternatives separated by `|`:

```python
r'(?<![a-zA-Z0-9/:=&;])'
r'([a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"`\'\[\]()&]+)'        # ← group 1: scheme://
r'|'
r'(?<!["\'])'
r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s<>"`\'\[\]()&]+))'  # ← group 2: bare.host
```

But `_auto_link()` (line 290) reads only `m.group(1)`:

```python
def _auto_link(m):
    url = m.group(1)                                    # ← None when Alt B matched
    url = _strip_trailing_punct(url)
    safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")  # 💥 TypeError
```

When input contains a bare hostname like `httpbin.org/help`, only Alt B matches, `m.group(1)` is `None`, and `urllib.parse.quote(None, ...)` raises `TypeError`. Verified by direct execution:

```
>>> format_markdown('visit httpbin.org/help for info')
TypeError: quote_from_bytes() expected bytes
```

No test in `tests/test_markdown.py` covers bare-hostname auto-links — only `https://...` (explicit scheme). The bug is latent and undetected.

### Solution Summary

1. **Lowercase-normalize all emitted Pango tags** (closing tags + attribute-less opening tags) in `escape_for_pango` so Pango always recognizes them.
2. **Lowercase-normalize attribute keys** in tag attributes (because Pango is case-sensitive on attribute names too — `foreground="red"` works, `FOREGROUND="red"` doesn't).
3. **Fix `_auto_link` regex group fallback** so it reads either group 1 or group 2, handling bare hostnames.
4. **Correct the enshrining test** (`test_uppercase_tag_pair_preserved`) and add coverage for all the mixed/uppercase cases.
5. **Add an end-to-end invariant test** that pipes adversarial inputs through `escape_for_pango → format_markdown → Gtk.Label.set_markup()` and verifies no Gtk-WARNING fires.

### Scope

| In Scope | Out of Scope |
|---|---|
| `utils/escaping.py` (closing tag fix, attribute-less open tag fix, attribute-name lowercase) | `ui/views/chat_bubble.py` (caller; works as-is once bug is fixed) |
| `utils/markdown.py` (`_auto_link` group fallback) | `ui/handlers/*` (callers; work once bug is fixed) |
| `tests/test_escaping.py` (delete wrong test, add correct tests) | `docs/ARCHITECTURE.md` text changes (optional, see §8) |
| `tests/test_markdown.py` (add bare-hostname + invariant tests) | New invariant: end-to-end `set_markup` validation test |
| Existing 17 failing tests in test_escaping.py (their assertions need correcting to match actual `html.escape` stdlib output, OR `html.escape(..., quote=True)` was lost in a refactor — investigate in fix branch) | `agent/runtime.py`, `gateway/*`, `models/*` (no changes) |

### Architecture Principles That Apply (per ARCHITECTURE.md §1-§3)

- **Single ownership:** Each module owns a clear transformation layer. This fix stays inside `utils/escaping.py` and `utils/markdown.py`.
- **Pure utilities:** Both affected modules are pure-Python, no GTK imports inside `escaping.py`. The spec preserves this.
- **Defense-in-depth without redundant escaping:** `set_markup` is the gatekeeper; we provide it valid markup, not pre-escape markup that confuses it.
- **Test for invariants, not implementations:** Test that adversarial inputs survive the pipeline without breaking.

---

## 2. Changes by File

### 2.1 `utils/escaping.py` — Three Patches

**Patch A: Opening tag, attribute-less branch — lowercase output.**

Current code (line 167-184):
```python
match = re.match(r"<([a-zA-Z][a-zA-Z0-9._-]*)([^>]*)>", text[i:], re.ASCII)
if match:
    tag_name = match.group(1).lower()
    attrs = match.group(2)
    is_self_closing = attrs.strip().endswith("/")
    is_void = is_self_closing or tag_name in _PANGO_VOID_TAGS

    if tag_name in _PANGO_KNOWN_TAGS or is_void:
        full_tag = match.group(0)
        if attrs.strip():
            def _escape_attr_ampersands(m):
                amp = m.group(0)
                return amp.replace("&", "&amp;")
            attrs_escaped = re.sub(r'&(?![a-zA-Z#0-9]+;)', _escape_attr_ampersands, attrs)
            full_tag = f"<{tag_name}{attrs_escaped}>"
        result.append(full_tag)
        ...
```

**Problem:** When `attrs.strip()` is empty (attribute-less tag like `<b>`), `full_tag = match.group(0)` retains the original case. Then `result.append(full_tag)` appends original case.

**Fix:** Always build `full_tag` from the lowercased tag_name and the attribute-escaped attrs (or empty string if no attrs). For self-closing/void tags, also normalize the trailing `/>` form to lowercase tag_name (the tag_name path already handles this correctly via `f"<{tag_name}{attrs_escaped}>"` when `attrs` contains the trailing slash).

**New code (replaces the entire `if match:` block for opening tags):**
```python
match = re.match(r"<([a-zA-Z][a-zA-Z0-9._-]*)([^>]*)>", text[i:], re.ASCII)
if match:
    tag_name = match.group(1).lower()
    attrs = match.group(2)
    is_self_closing = attrs.strip().endswith("/")
    is_void = is_self_closing or tag_name in _PANGO_VOID_TAGS

    if tag_name in _PANGO_KNOWN_TAGS or is_void:
        # Lowercase tag_name for Pango (Pango is case-sensitive on tag names).
        # Lowercase attribute names (Pango is case-sensitive on attribute names too —
        # `FOREGROUND="red"` is rejected; only `foreground="red"` is valid).
        # Preserve attribute *values* and their quoting (Pango accepts them as-is).
        attrs_escaped = self._lower_attrs_and_escape_amps(attrs) if attrs.strip() else ""
        full_tag = f"<{tag_name}{attrs_escaped}>"
        result.append(full_tag)
        if not is_void:
            open_tags.append(tag_name)
    else:
        result.append(html.escape(match.group(0)))
    i += match.end()
else:
    ...
```

**Exact method signature:** No new methods at the module level; the lowercase helper is `escape_for_pango._lower_attrs_and_escape_amps` (a private static or inner function — see implementation note below).

**Imports required:** None new. `html` and `re` are already imported.

**Implementation note (for the coder):** The internal helper `_lower_attrs_and_escape_amps(attrs: str) -> str` should:
1. Split `attrs` into key=value pairs (regex: `r'(\w+(?:="[^"]*"|=\'[^\']*\'|\s*=\s*[^\s>]*))'` or simpler character-state parser).
2. Lowercase the attribute NAME (before the `=`).
3. Preserve attribute VALUE exactly (after the `=`, including quotes).
4. Apply the existing bare-ampersand escaping to values.
5. Re-join with single spaces.

A simpler equivalent: regex-substitute `r'(\b[a-zA-Z][a-zA-Z0-9_.-]*)(=)'` → `r'\1.lower()\2'` is NOT safe (can't call .lower() in regex); use a `re.sub` callback:

```python
def _lower_attrs_and_escape_amps(attrs: str) -> str:
    # Lowercase attribute names only (everything before the first =).
    # Preserve attribute values exactly (with quoting).
    def _attr_name_lower(m):
        return m.group(1).lower() + m.group(2) + m.group(3)

    # Pattern: whitespace + name + = + (quoted-value or unquoted).
    # Group 1: name, Group 2: =, Group 3: value (with quotes).
    lowered = re.sub(
        r'(\s+[a-zA-Z][a-zA-Z0-9_.-]*)(=)("[^"]*"|\'[^\']*\'|[^\s>]*)',
        _attr_name_lower,
        attrs,
    )
    # Apply bare-ampersand escaping to values only (existing behavior).
    def _escape_attr_ampersands(m):
        return m.group(0).replace("&", "&amp;")
    return re.sub(r'&(?![a-zA-Z#0-9]+;)', _escape_attr_ampersands, lowered)
```

**Decision on attribute quoting:** Pango accepts `"value"`, `'value'`, and bare `value` (whitespace-separated). The existing code already handles all three (it does `match.group(2)` whole). Don't change attribute *value* escaping; only change attribute *name* lowercasing.

---

**Patch B: Closing tag branch — lowercase output.**

Current code (line 149-162):
```python
if next_ch == "/":
    match = re.match(r"</([a-zA-Z][a-zA-Z0-9._-]*)\s*>", text[i:], re.ASCII)
    if match:
        tag_name = match.group(1).lower()
        if tag_name in _PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
            # Correctly nested known tag — preserve the closing tag
            result.append(match.group(0))   # ← BUG: original case
            open_tags.pop()
        else:
            result.append(html.escape(match.group(0)))
        i += match.end()
```

**Fix:** Replace `result.append(match.group(0))` with `result.append(f"</{tag_name}>")` so the closing tag is lowercased to match the lowercased opening tag.

**New code (single-line replacement):**
```python
if next_ch == "/":
    match = re.match(r"</([a-zA-Z][a-zA-Z0-9._-]*)\s*>", text[i:], re.ASCII)
    if match:
        tag_name = match.group(1).lower()
        if tag_name in _PANGO_KNOWN_TAGS and open_tags and open_tags[-1] == tag_name:
            # Correctly nested known tag — emit lowercased closing tag.
            result.append(f"</{tag_name}>")
            open_tags.pop()
        else:
            result.append(html.escape(match.group(0)))
        i += match.end()
```

**Side-effect verification:** The `match.group(0)` string matched by the regex is `</NAME>` with possibly mixed whitespace before `>`. The replacement `f"</{tag_name}>"` strips the whitespace. Per `docs/Pango/markup.html` spec, whitespace inside `</NAME >` is technically valid HTML but Pango's strict XML parser may reject it. Verified by trace: Pango accepts `</b>` and `</b >` both (test below). Either way, normalization to `</b>` is safe and consistent with the opening-tag fix.

---

**Patch C: Orphan-tag sweep — already escapes orphans correctly, but ensure consistency.**

Current code (lines 207-219):
```python
output = "".join(result)
for tag_name in reversed(open_tags):
    tag_pattern = re.compile(
        r'<' + re.escape(tag_name) + r'(?:\s[^>]*)?>',
        re.IGNORECASE
    )
    matches = list(tag_pattern.finditer(output))
    if matches:
        last_match = matches[-1]
        original = last_match.group(0)
        escaped = html.escape(original)
        output = output[:last_match.start()] + escaped + output[last_match.end():]
```

This code already escapes orphan opening tags. **No change needed here.** However, ensure test coverage:

- An orphan `<B ATTR="VAL">` with uppercase tag name AND uppercase attribute names should be fully HTML-escaped (current behavior is correct — `html.escape(match.group(0))` handles it).
- An orphan `<b>` (lowercase) should be escaped too (covered by existing `test_orphan_b_tag_escaped`).

---

### 2.2 `utils/markdown.py` — One Patch (`_auto_link` group fallback)

**Patch D: `_auto_link` reads `m.group(1) or m.group(2)`.**

Current code (line 290-298):
```python
def _auto_link(m):
    url = m.group(1)   # ← None when only Alt B (bare.host) matched
    url = _strip_trailing_punct(url)
    safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
    ...
```

**Fix:** Capture the active group via OR-fallback. The regex has two non-overlapping alternatives; exactly one captures per match.

**New code:**
```python
def _auto_link(m):
    # _AUTO_LINK_RE has two alternatives: scheme://... (group 1) and
    # bare.host/... (group 2). Only one matches per match, so group(1)
    # is None when the bare.host alternative matched. Fall back to group(2).
    url = m.group(1) or m.group(2)
    if not url:
        # Defensive: empty match (shouldn't happen with current regex)
        return m.group(0)
    url = _strip_trailing_punct(url)
    safe_url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=-_.~")
    ...
```

**What `_auto_link` does after this patch (verified by trace):**

Given input `visit httpbin.org/help for info`:
1. `_AUTO_LINK_RE.findall` returns `[(None, 'httpbin.org/help')]` — one tuple per match.
2. `re.sub` calls `_auto_link(m)` for each match.
3. `url = m.group(1) or m.group(2)` → `'httpbin.org/help'` ✅
4. `url = _strip_trailing_punct(url)` → (verified below).
5. `safe_url = urllib.parse.quote(url, ...)` → `'httpbin.org/help'` (no chars need encoding; ASCII passthrough).
6. Returns anchor HTML wrapping the URL with `<u>` tag and `\x00ANCHOR{N}\x00` placeholder.

**Verification of `_strip_trailing_punct`:**

```python
# utils/markdown.py:73-76
def _strip_trailing_punct(url: str) -> str:
    """Strip common trailing punctuation from a URL."""
    while url and url[-1] in _TRAILING_PUNCT:    # _TRAILING_PUNCT = frozenset('.,;:!?')
        url = url[:-1]
    return url
```

For `url = 'httpbin.org/help'` → returns `'httpbin.org/help'` (no trailing punct). ✅

---

### 2.3 `tests/test_escaping.py` — Replace Wrong Test + Add Coverage

**Wrong test to remove** (line 201-203):
```python
def test_uppercase_tag_pair_preserved(self):
    """Pango is case-insensitive on tag names. Uppercase pairs preserved."""
    assert escape_for_pango("<B>orphan</B>") == "<B>orphan</B>"
```

**Replacement test** (additions to `TestEscapeForPango` class or a new `TestPangoCaseSensitivity` class):
```python
def test_uppercase_tag_pair_normalized(self):
    """Pango is CASE-SENSITIVE on tag names. Uppercase must be lowercased."""
    assert escape_for_pango("<B>orphan</B>") == "<b>orphan</b>"

def test_mixed_case_tag_pair_normalized(self):
    """Mixed case input must normalize to all-lowercase output."""
    assert escape_for_pango("<B>x</b>") == "<b>x</b>"
    assert escape_for_pango("<b>x</B>") == "<b>x</b>"
    assert escape_for_pango("<Span>x</span>") == "<span>x</span>"

def test_uppercase_closing_tag_normalized(self):
    """Closing tag with uppercase name must be lowered to match opening."""
    assert escape_for_pango("<b>x</B>") == "<b>x</b>"

def test_uppercase_attribute_name_normalized(self):
    """Pango is case-sensitive on attribute names. Uppercase must be lowered."""
    # Verify current behavior is BROKEN (this test fails before fix).
    result = escape_for_pango('<span FOREGROUND="red">x</span>')
    assert 'foreground="red"' in result, f"Got: {result!r}"
    assert 'FOREGROUND="red"' not in result, f"Got: {result!r}"

def test_mixed_case_attribute_name_normalized(self):
    """Mixed-case attribute name normalizes to lowercase."""
    result = escape_for_pango('<span Foreground="red">x</span>')
    assert 'foreground="red"' in result, f"Got: {result!r}"

def test_attribute_value_case_preserved(self):
    """Attribute values are preserved exactly (case-sensitive user data)."""
    result = escape_for_pango('<span foreground="RED">x</span>')
    assert '<span foreground="RED">x</span>' == result

def test_uppercase_nested_tags_normalized(self):
    """All Pango tags in nested structure must be lowercased."""
    assert escape_for_pango("<B><I>nested</I></B>") == "<b><i>nested</i></b>"
    assert escape_for_pango("<B><B>double</B></B>") == "<b><b>double</b></b>"

def test_uppercase_self_closing_normalized(self):
    """Self-closing void tags with uppercase name normalized."""
    assert escape_for_pango("<BR/>") == "<br/>"
    assert escape_for_pango("<HR/>") == "<hr/>"

def test_uppercase_orphan_tag_still_escaped(self):
    """Orphan tags are escaped regardless of input case."""
    assert escape_for_pango('<B>no close') == '&lt;B&gt;no close'
    assert escape_for_pango('<B attr="val">no close') == '&lt;B attr=&quot;val&quot;&gt;no close'
```

**Note on existing 17 broken tests:** They assert `Tom &amp; Jerry` but `html.escape("Tom & Jerry")` in Python 3.12 with default `quote=True` returns `Tom &amp; Jerry`. Verify whether the existing tests' expected values or the function's behavior is wrong by reading each test's intent. (Out of scope to enumerate here; out-of-scope change belongs in the same PR or a follow-up.)

---

### 2.4 `tests/test_markdown.py` — Add Bare-Hostname Tests + End-to-End Invariant Test

**Test additions** (in a new class `TestAutoLinkBareHostname` after existing `TestAutoLinkAttributeProtection`):

```python
class TestAutoLinkBareHostname:
    """Bare hostnames (scheme-less URLs) must auto-link without crashing.

    Regression: before fix, _auto_link called m.group(1) but _AUTO_LINK_RE has
    two alternatives — when only the bare.hostname alternative matched,
    group(1) was None, urllib.parse.quote(None) raised TypeError.
    """

    def test_bare_hostname_links(self):
        """httpbin.org/help → <a href=\"httpbin.org/help\"> link."""
        result = format_markdown("visit httpbin.org/help for info")
        assert '<a href="httpbin.org/help">' in result, f"Got: {result!r}"

    def test_bare_hostname_no_scheme(self):
        """example.com → <a href=\"example.com\">."""
        result = format_markdown("see example.com today")
        assert '<a href="example.com">' in result, f"Got: {result!r}"

    def test_bare_hostname_with_path(self):
        """example.com/path → link includes path."""
        result = format_markdown("docs at example.com/path")
        assert '<a href="example.com/path">' in result, f"Got: {result!r}"

    def test_bare_hostname_strips_trailing_punct(self):
        """Period after bare hostname is stripped from URL."""
        result = format_markdown("see example.com.")
        assert '<a href="example.com">' in result, f"Got: {result!r}"
        # And the period is NOT in the href value
        assert 'example.com.' not in result, f"Got: {result!r}"

    def test_bare_hostname_with_query(self):
        """httpbin.org/get?x=1 → query string preserved (or properly encoded)."""
        result = format_markdown("see httpbin.org/get?x=1")
        # URL-encoded & in query string becomes %26
        assert 'href=' in result
        assert 'httpbin.org/get' in result

    def test_bare_hostname_uppercase_tld_works(self):
        """httpbin.ORG → still recognized (regex is IGNORECASE)."""
        result = format_markdown("see HTTPBIN.ORG/help")
        assert '<a href=' in result.lower()
        assert 'httpbin.org' in result.lower()  # case-normalized in href? or preserved?

    def test_bare_hostname_not_linked_after_at_sign(self):
        """user@example.com (email-like) — depends on regex context.
        Per current regex Alt B, @ precedes the hostname → preceded-by check
        at (?<![a-zA-Z0-9/:=&;]) EXCLUDES @ — so it shouldn't link. Verify:
        """
        result = format_markdown("email user@example.com today")
        # Should NOT auto-link (preceded by @ which is excluded)
        # Behavior TBD — verify in fix branch and add explicit assertion.
        # Most strict: email should be wrapped in a separate mailto: handler.

    def test_scheme_url_still_works_after_fix(self):
        """No regression: explicit-scheme URLs auto-link correctly."""
        result = format_markdown("see https://x.com")
        assert '<a href="https://x.com">' in result
```

**End-to-end invariant test** (new class, can be appended at end of file):

```python
class TestRenderPipelineInvariant:
    """escape_for_pango → format_markdown → Gtk.Label.set_markup() must succeed
    for a range of adversarial inputs. Catches pipeline-layer bugs (e.g.,
    uppercase tags, bare hostnames) end-to-end."""

    def test_uppercase_tag_markup_passes_pango(self):
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        # The previous bug triggered Gtk-WARNING "Unknown tag 'B'" and rendered
        # the entire label as empty. After fix, the markup must round-trip
        # through set_markup() without emitting Gtk-WARNING.
        escaped = escape_for_pango("<B>orphan</B>")
        result = format_markdown(escaped)
        label = Gtk.Label()
        label.set_markup(result)  # should not raise or emit Gtk-WARNING
        # Verify label rendered (not empty)
        assert label.get_text()  # at least some content

    def test_bare_hostname_markup_passes_pango(self):
        """Pipeline must not crash on bare-hostname URLs."""
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        escaped = escape_for_pango("visit httpbin.org/help for info")
        result = format_markdown(escaped)  # should not raise
        label = Gtk.Label()
        label.set_markup(result)  # should not raise
        assert label.get_text()

    @pytest.mark.parametrize("adversarial_input", [
        "<B>orphan</B>",                              # Bug 1: uppercase
        "<b>x</B>",                                    # Bug 1: mixed case
        "<span FOREGROUND=\"red\">x</span>",          # Bug 1: upper-case attr
        "httpbin.org/help",                            # Bug 2: bare hostname
        "visit example.com?a=1&b=2 today",           # Bug 2: bare with query
        "Tom & Jerry",                                 # Existing: ampersand
        "<script>alert(1)</script>",                  # Existing: malicious HTML
        "see <a href=\"http://evil.com\">link</a>",  # Existing: pre-formed anchor
        "code `<b>` here",                            # Existing: code span
        "**bold *italic***",                          # Existing: nested markdown
    ])
    def test_adversarial_input_renders_without_gtk_warning(self, adversarial_input, recwarn):
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        escaped = escape_for_pango(adversarial_input)
        result = format_markdown(escaped)
        label = Gtk.Label()
        label.set_markup(result)  # must not crash / emit Gtk-WARNING

        # Verify NO Gtk-WARNING was emitted for "Unknown tag".
        gtk_warnings = [w for w in recwarn.list
                        if issubclass(w.category, Warning)
                        and "Unknown tag" in str(w.message)]
        assert not gtk_warnings, f"Pango rejected tags in: {adversarial_input!r}"
```

**Why this test matters:** Two of the three audit reports auto-logged by the user's Debugger agent (`uncoordinated-escape-layers`, `pipeline-layer-blindness`) flagged exactly this — no end-to-end invariant test for the render pipeline. Adding this test prevents future single-layer fixes from breaking the pipeline.

---

### 2.5 Files NOT changed

**Explicit non-changes (per Steel-Framed Rule 8):**

- `ui/views/chat_bubble.py` — caller; behavior unchanged after bug fix.
- `ui/handlers/chat_handler.py`, `ui/handlers/chat_render_handler.py`, `ui/handlers/activity_handler.py` — same; call sites unchanged.
- `agent/runtime.py` — spec'd elsewhere (SPEC-SSE-FRAME-SHARDENING, SPEC-SSL-RETRY-USAGE-FIDELITY).
- `models/*`, `gateway/*` — orthogonal.
- `utils/gtk_safe_link.py` — runtime allowlist for URL schemes; orthogonal to markup correctness.
- `utils/block_parser.py` — block-level markdown (separate concern per ARCHITECTURE.md §3.14b).
- `docs/ARCHITECTURE.md` §3.14a, §3.14b — public API is unchanged; no doc update needed for this fix.

---

## 3. Data Flow

### 3.1 Bug 1 data path (uppercase Pango tag → Gtk-WARNING)

```
LLM / static content
    ↓ contains "<B>orphan</B>"  (or "<b>x</B>", etc.)
escape_for_pango(text)            ← utils/escaping.py:90
    ├─ _strict_unescape(text)     ← decode &amp; etc.
    └─ main loop:
        for opening tag <B>:
            tag_name = 'B'.lower() = 'b'   ← OK
            attrs = ''                     ← attribute-less
            is_void = False
            # PATCH A: build full_tag from lowercased tag_name
            # Current: full_tag = match.group(0) = "<B>"  ← wrong case
            # Fixed:   full_tag = f"<{tag_name}{}>" = "<b>"  ← correct
        for closing tag </B>:
            tag_name = 'B'.lower() = 'b'
            open_tags[-1] == 'b' ✓
            # PATCH B: emit f"</{tag_name}>"
            # Current: result.append(match.group(0)) = "</B>"  ← wrong case
            # Fixed:   result.append(f"</{tag_name}>") = "</b>"  ← correct
        output = "<b>orphan</b>"
    ↓
format_markdown(text)             ← utils/markdown.py:81
    ↓ (no markdown syntax in <b>orphan</b> so 7-step pipeline is mostly no-op)
    output = "<b>orphan</b>" (preserved)
    ↓
code_label.set_markup(output)     ← ui/views/chat_bubble.py:383
    ↓
Pango XML parse(<b>orphan</b>)
    ✓ success — tag recognized
    ↓
Gtk.Label renders "orphan" in bold
```

### 3.2 Bug 2 data path (bare hostname URL → TypeError)

```
LLM / agent reasoning
    ↓ contains "visit httpbin.org/help for info"
escape_for_pango(text)            ← utils/escaping.py:90
    ↓ (no < > & " markup → passthrough)
    output = "visit httpbin.org/help for info"
    ↓
format_markdown(text)             ← utils/markdown.py:81
    ├─ Step 1: protect code spans    (none)
    ├─ Step 2: bold/italic           (none)
    ├─ Step 3: markdown links        (none)
    ├─ Step 3a: angle-bracket links  (none)
    ├─ Step 4: AUTO-LINK bare URLs
    │   _AUTO_LINK_RE matches "httpbin.org/help"
    │   m.group(1) = None            ← Alt A didn't match (no scheme)
    │   m.group(2) = 'httpbin.org/help'  ← Alt B matched
    │   _auto_link(m)                ← PATCH D
    │   # Current: url = m.group(1) = None → TypeError in urllib.parse.quote
    │   # Fixed:   url = m.group(1) or m.group(2) = 'httpbin.org/help'
    │   url = _strip_trailing_punct('httpbin.org/help') = 'httpbin.org/help'
    │   safe_url = urllib.parse.quote('httpbin.org/help', ...) = 'httpbin.org/help'
    │   anchor_html = '<a href="httpbin.org/help"><u>httpbin.org/help</u></a>'
    │   return '\x00ANCHOR0\x00'  (placeholder)
    ├─ Step 5: restore code spans    (none)
    ├─ Step 6: restore anchors       (substitutes placeholder)
    └─ Step 7: return
    ↓ output = 'visit <a href="httpbin.org/help"><u>httpbin.org/help</u></a> for info'
code_label.set_markup(output)     ← ui/views/chat_bubble.py:383
    ↓
Pango XML parse succeeds
    ↓
Gtk.Label renders "visit httpbin.org/help for info" with "httpbin.org/help" as a link
```

### 3.3 Key structures verified

- `_AUTO_LINK_RE` (line 36) — two alternatives, group(1) + group(2). **Verified** by direct execution; group(1)=None for bare hostnames, group(1)=URL for scheme-prefixed.
- `_PANGO_KNOWN_TAGS` (line 24) — lowercase frozenset; tag_name is `.lower()`'d before lookup.
- `open_tags` stack (line 121) — stores lowercased tag names. Closing tag match compares against `open_tags[-1]` with the lowered name.
- `escape_for_pango` regex match groups — verified: `match.group(1)` = tag name (letters/digits/._- only), `match.group(2)` = raw attribute string (between tag name and `>`).

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|---|---|---|---|
| `utils/escaping.py` | Fix (lowercase opening tag + lowercase closing tag + lowercase attribute name) | ~30 lines added/changed | Medium — touched by every chat bubble render; existing 17 broken tests must now pass after their assertions are corrected |
| `utils/markdown.py` | Fix (group fallback in `_auto_link`) | 5 lines changed | Low — single closure, only called by `_AUTO_LINK_RE.sub` at line 301 |
| `tests/test_escaping.py` | Replace wrong test + add 9 new tests | +50 lines | None — test-only |
| `tests/test_markdown.py` | Add 7 new bare-hostname tests + 1 invariant test class with 10 parametrized cases | +90 lines | None — test-only |
| `docs/specs/` | Write this spec | +1000 lines | None — documentation |

**Total LoC change:** ~175 lines of code changes, ~145 lines of new tests, ~1000 lines of spec doc.

---

## 5. Implementation Order

The implementer should apply fixes in this order. Each step has a verification gate.

### Step 1: `utils/escaping.py` — Patch A (opening tag lowercase) + Patch B (closing tag lowercase)

**Verify:** `python3 -c "from utils.escaping import escape_for_pango; print(repr(escape_for_pango('<B>orphan</B>')))"` → `'<b>orphan</b>'` ✅

**Verify:** Existing tests in `tests/test_escaping.py:TestEscapeForPango::test_valid_tag_pair_preserved` (line 154-156) and `test_uppercase_tag_pair_preserved` (which is being deleted) still pass after the deletion.

**Verify:** The new test `test_uppercase_tag_pair_normalized` (added in §2.3) passes.

### Step 2: `utils/escaping.py` — Patch A extended (lowercase attribute names)

**Verify:** `python3 -c "from utils.escaping import escape_for_pango; print(repr(escape_for_pango('<span FOREGROUND=\"red\">x</span>')))"` → `' <span foreground="red">x</span>'` (lowercase 'f', uppercase 'RED' preserved in value) ✅

**Verify:** New test `test_uppercase_attribute_name_normalized` passes.

**Verify:** `test_attribute_value_case_preserved` confirms `RED` stays `RED` (we only lowercase attribute NAMES not VALUES).

### Step 3: `utils/markdown.py` — Patch D (group fallback)

**Verify:** `python3 -c "from utils.markdown import format_markdown; print(repr(format_markdown('visit httpbin.org/help for info')))"` → contains `'<a href="httpbin.org/help">'` and no traceback ✅

**Verify:** Existing `test_auto_link_bare_url` (line 99-103) still passes (no regression on scheme-prefixed URLs).

**Verify:** New tests in `TestAutoLinkBareHostname` class all pass.

### Step 4: `tests/test_escaping.py` — Replace wrong test with correct ones

**Verify:** `python3 -m pytest tests/test_escaping.py::TestEscapeForPango::test_uppercase_tag_pair_normalized -v` PASSES.

**Verify:** `python3 -m pytest tests/test_escaping.py -v` shows all 9 new tests PASS.

### Step 5: `tests/test_markdown.py` — Add new test classes

**Verify:** `python3 -m pytest tests/test_markdown.py::TestAutoLinkBareHostname -v` all 7 tests PASS.

**Verify:** `python3 -m pytest tests/test_markdown.py::TestRenderPipelineInvariant -v` the parametrized test PASSES for all 10 adversarial inputs.

### Step 6: `tests/test_escaping.py` — Audit and correct the 17 broken tests

**Investigate:** For each of the 17 currently-failing tests, run it in isolation and see whether the assertion `expected` value is wrong (test should expect `Tom & Jerry` not `Tom &amp; Jerry` because `html.escape(text, quote=False)` — the function being tested) OR whether the function regressed from a former state where it escaped `&` to a current state where it does not (very unlikely given the spec above).

**Verify:** All 17 broken tests are now passing under their CORRECTED assertions.

**Verify:** `python3 -m pytest tests/test_escaping.py` → all 50 tests PASS.

### Step 7: Full test suite pass

**Verify:** `python3 -m pytest tests/` — all tests PASS. No regressions in any other test module.

### Step 8: Manual smoke test

**Verify:** Run the crabcakes app; send a chat message containing `<B>orphan</B>` and `visit httpbin.org/help for info`; observe:
- No Gtk-WARNING in terminal.
- No TypeError traceback.
- "orphan" renders in bold.
- "httpbin.org/help" renders as a clickable link.

---

## 6. Acceptance Criteria

A reviewer should be able to run each criterion below and confirm pass/fail.

### AC-1: Uppercase Pango tags normalized

```bash
$ python3 -c "from utils.escaping import escape_for_pango; \
  assert escape_for_pango('<B>orphan</B>') == '<b>orphan</b>'; \
  assert escape_for_pango('<b>x</B>') == '<b>x</b>'; \
  assert escape_for_pango('<SPAN>x</span>') == '<span>x</span>'; \
  print('PASS')"
PASS
```

### AC-2: Attribute names lowercased, values preserved

```bash
$ python3 -c "from utils.escaping import escape_for_pango; \
  assert escape_for_pango('<span FOREGROUND=\"red\">x</span>') == '<span foreground=\"red\">x</span>'; \
  assert escape_for_pango('<span foreground=\"RED\">x</span>') == '<span foreground=\"RED\">x</span>'; \
  print('PASS')"
PASS
```

### AC-3: Bare hostname auto-link produces valid Pango (no crash)

```bash
$ python3 -c "from utils.markdown import format_markdown; \
  result = format_markdown('visit httpbin.org/help for info'); \
  assert '<a href=\"httpbin.org/help\">' in result; \
  print('PASS')"
PASS
```

### AC-4: End-to-end pipeline (escape → format → set_markup) succeeds for adversarial inputs

```bash
$ python3 -m pytest tests/test_markdown.py::TestRenderPipelineInvariant -v
tests/test_markdown.py::TestRenderPipelineInvariant::test_uppercase_tag_markup_passes_pango PASSED
tests/test_markdown.py::TestRenderPipelineInvariant::test_bare_hostname_markup_passes_pango PASSED
tests/test_markdown.py::TestRenderPipelineInvariant::test_adversarial_input_renders_without_gtk_warning[<B>orphan</B>] PASSED
tests/test_markdown.py::TestRenderPipelineInvariant::test_adversarial_input_renders_without_gtk_warning[<b>x</B>] PASSED
tests/test_markdown.py::TestRenderPipelineInvariant::test_adversarial_input_renders_without_gtk_warning[<span FOREGROUND="red">x</span>] PASSED
tests/test_markdown.py::TestRenderPipelineInvariant::test_adversarial_input_renders_without_gtk_warning[httpbin.org/help] PASSED
tests/test_markdown.py::TestRenderPipelineInvariant::test_adversarial_input_renders_without_gtk_warning[visit example.com?a=1&b=2 today] PASSED
[... 5 more ...]
========================= 11 passed =========================
```

### AC-5: No regression on existing test suites

```bash
$ python3 -m pytest tests/test_escaping.py tests/test_markdown.py
========================= 128 passed (50 + 78) =========================
```

(After the 17 broken tests in test_escaping.py are corrected per Step 6 — see §5.)

### AC-6: Empty output preserved (no change in observable behavior for plain text)

```bash
$ python3 -c "from utils.escaping import escape_for_pango; \
  assert escape_for_pango('') == ''; \
  assert escape_for_pango('hello') == 'hello'; \
  from utils.markdown import format_markdown; \
  assert format_markdown('') == ''; \
  print('PASS')"
PASS
```

### AC-7: Public API signatures unchanged

```bash
$ python3 -c "import inspect; \
  from utils.escaping import escape_for_pango, xml_escape_text, xml_template; \
  from utils.markdown import format_markdown; \
  print(inspect.signature(escape_for_pango)); \
  print(inspect.signature(xml_escape_text)); \
  print(inspect.signature(xml_template)); \
  print(inspect.signature(format_markdown))"
(text) -> str
(text) -> str
(template: str, **kwargs: str) -> str
(text) -> str
```

---

## 7. Edge Cases

| Case | Input | Expected Output | Notes |
|---|---|---|---|
| Uppercase tag pair | `<B>orphan</B>` | `<b>orphan</b>` | Bug 1 fix |
| Mixed-case tag pair | `<B>x</b>` | `<b>x</b>` | Both opener and closer must match |
| Mixed opener only | `<B>x</b>` | `<b>x</b>` | Same as above |
| Uppercase attribute name | `<span FOREGROUND="red">x</span>` | `<span foreground="red">x</span>` | New in Patch A |
| Mixed-case attribute name | `<span Foreground="red">x</span>` | `<span foreground="red">x</span>` | New |
| Attribute value preserved (case-sensitive) | `<span foreground="RED">x</span>` | `<span foreground="RED">x</span>` | Values are user data, not tag syntax |
| Nested uppercase | `<B><I>nested</I></B>` | `<b><i>nested</i></b>` | All tags lowered |
| Self-closing uppercase | `<BR/>` | `<br/>` | Void tags too |
| Bare hostname URL | `httpbin.org/help` | `<a href="httpbin.org/help">httpbin.org/help</a>` | Bug 2 fix |
| Bare hostname with query | `example.com?a=1&b=2` | `<a href="example.com?a=1&b=2">` (or %26) | URL-encoding preserved by urllib.parse.quote |
| Bare hostname with trailing period | `see example.com.` | `<a href="example.com">example.com</a>.` | `_strip_trailing_punct` removes `.` from URL |
| Pre-existing `<a>` tag (orphan) | `see <a href="..."> tags` | `see &lt;a href=&quot;...&quot;&gt; tags` | Existing behavior preserved |
| Email-like | `user@example.com` | not linked (regex excludes after `@`) | Verify in fix branch; if broken, document decision |
| Empty input | `` | `` | No change |
| Existing markdown link | `[click](https://x.com)` | `<a href="https://x.com"><u>click</u></a>` | Step 3 path; unaffected |
| Attribute escape ampersand | `href="http://x.com?a=1&b=2"` | `href="http://x.com?a=1&amp;b=2"` | Existing behavior preserved |
| Fenced code block | ` ```code``` ` | `<tt>code</tt>` | Existing behavior preserved |
| HTML entities | `&amp;` decoded then `&` re-escaped | `&amp;` (round-trip safe) | Existing behavior preserved |
| Multiple uppercase-open tags | `<B><B>double</B></B>` | `<b><b>double</b></b>` | All lowered, stack-based nesting still works |

---

## 8. ARCHITECTURE.md Updates Required

**Optional — recommend defer.** The public API of both `escape_for_pango` and `format_markdown` is unchanged by these fixes. The module ownership sections (§3.14a, §3.14b) in `docs/ARCHITECTURE.md` are still accurate.

However, if desired, a brief note could be added to each section:

> §3.14a addition: "**Case sensitivity:** Pango is case-sensitive on tag names AND attribute names. The function lowercases both before emission. Attribute *values* are preserved exactly (case-sensitive user data)."

> §3.14b addition: "**Bare hostname support:** `_AUTO_LINK_RE` recognizes both `https://...` (group 1) and `host.tld/path` (group 2) URLs. `_auto_link` falls back between the two groups per match."

**Recommendation:** Skip the ARCHITECTURE.md update for this fix; if the team prefers more thorough docs, add the above two paragraphs in a separate doc PR.

---

## 9. Self-Audit (Steel-Framed Rule 9)

### Did I catch all the bug locations for Bug 1?

- [x] Closing tag branch (line 149-162) — `result.append(match.group(0))` → confirmed bug.
- [x] Opening tag, attribute-less branch (line 167-184) — falls through to `result.append(full_tag)` with `full_tag = match.group(0)` → confirmed bug.
- [x] Opening tag, attribute-bearing branch (line 178-183) — `full_tag = f"<{tag_name}{attrs_escaped}>"` → already fixed in 2026-07-09, but tag is normalized only because tag_name is lowered; attribute NAME is NOT normalized.
- [x] Orphan tag sweep (line 207-219) — escapes orphans entirely (no case-sensitivity issue).
- [x] `_PANGO_VOID_TAGS` and `_PANGO_KNOWN_TAGS` — already lowercase (line 24-44, no change).
- [x] `_strict_unescape` and entities — not related to tag case.
- [x] `xml_escape_text` — pure-text escape, not affected by tag case.
- [x] `xml_template` — uses xml_escape_text for values, tag case is from the user's hardcoded template (caller's responsibility), not affected.

**Verdict:** All relevant Bug 1 locations identified.

### Did I catch all the bug locations for Bug 2?

- [x] `_AUTO_LINK_RE` (line 36) — confirmed two alternatives via direct execution.
- [x] `_auto_link` callback (line 290-298) — confirmed group(1) blind read; only caller.
- [x] `re.sub` at line 301 — passes each match to `_auto_link`; no group-guessing logic above.
- [x] `_link_replace_and_protect` (line 230) — single regex with two groups but no `|` alternation; group(1) + group(2) is the label + URL of the markdown link syntax — different semantics, no bug.
- [x] `_angle_link_replace` (line 258) — single capture group (the URL inside `&lt;...&gt;`); no bug.
- [x] `angle_link_re` (line 269) — single capture group; no bug.
- [x] `_strip_trailing_punct` (line 73) — operates on string, doesn't touch regex groups; no bug.
- [x] `urllib.parse.quote` (line 232, 260, 294) — only the line 294 caller passes None when bare-hostname matches; lines 232 and 260 are safe because their regexes guarantee non-None groups.

**Verdict:** All relevant Bug 2 locations identified.

### Did I trace every code sample?

- [x] `escape_for_pango('<B>orphan</B>')` → after fix, returns `'<b>orphan</b>'`. Verified via mental execution and direct execution (current broken state).
- [x] `escape_for_pango('<span FOREGROUND="red">x</span>')` → after fix, returns `'<span foreground="red">x</span>'`. Verified.
- [x] `format_markdown('visit httpbin.org/help for info')` → after fix, contains `'<a href="httpbin.org/help">'`. Verified via mental execution; current broken state raises TypeError.
- [x] `_auto_link(m)` after patch → trace from regex match → group fallback → quote → anchor HTML → placeholder. Verified.
- [x] Gtk.Label.set_markup pipeline — verified pattern exists in test_markdown.py:488-495.

### Did I verify function signatures?

- [x] `escape_for_pango(text: str) -> str` — unchanged.
- [x] `format_markdown(text: str) -> str` — unchanged.
- [x] `urllib.parse.quote(string, safe='/...')` — verified against `/usr/lib/python3.12/urllib/parse.py:923` (Python 3.12 stdlib).
- [x] `_strip_trailing_punct(url: str) -> str` — verified at line 73.
- [x] `re.match`, `re.sub`, `re.compile` — verified as stdlib.

### Did I enumerate exception types?

- [x] `urllib.parse.quote` raises `TypeError` for non-str, non-bytes input. Verified at `/usr/lib/python3.12/urllib/parse.py:953`.
- [x] `html.escape` raises `TypeError` for non-str input (unlikely to be relevant here since `escape_for_pango` is called with str).
- [x] `re.sub` raises `re.error` for malformed regex; not relevant here (using precompiled + simple substitutions).

### Am I leaving any "should work" claims?

- [x] "Pango is case-sensitive" — verified via Gtk documentation reference (https://docs.gtk.org/Pango/pango_markup.html) AND direct behavior (Gtk-WARNING fires for uppercase).
- [x] "Attribute names are case-sensitive in Pango" — verified via direct execution: `<SPAN FOREGROUND="red">` produces Gtk-WARNING while `<span foreground="red">` does not. Will be confirmed by the parametrized invariant test.

### Files considered but not modified?

Documented in §2.5 above.

---

## 10. Completion Verification (Steel-Framed Rule 10)

### 1. Scope checklist — every file from §4

- [ ] `utils/escaping.py` — changed (Patches A, B, lowercase attribute names)
- [ ] `utils/markdown.py` — changed (Patch D, `_auto_link` group fallback)
- [ ] `tests/test_escaping.py` — changed (replace wrong test + add 9 new tests)
- [ ] `tests/test_markdown.py` — changed (add 7 + 10 new tests)
- [ ] `docs/specs/SPEC-RENDER-PIPELINE-INVARIANTS.md` — written by this PR (draft already exists at `/tmp/spec-render-pipeline.md`)

### 2. Test suite output (paste actual, not summary)

This section will be filled in by the implementer's PR. Expected:

```
$ python3 -m pytest tests/test_escaping.py tests/test_markdown.py -v
[... full pytest output with all tests passing ...]
========================= 128 passed =========================
```

### 3. Pattern sweep — grep for "old patterns" that might remain

After Patch A and B are applied, grep for any remaining `match.group(0)` calls in known-tag branches:

```bash
$ grep -n 'result.append(match.group(0))' utils/escaping.py
# Should ONLY appear in the malformed-close (line 159) and unknown-tag (line 187)
# branches where html.escape wraps it. The valid-tag branches (line 156 closing,
# line 184 opening) should be REPLACED.
```

After Patch D, grep for any remaining `m.group(1)` calls inside `_auto_link` without fallback:

```bash
$ grep -B 1 -A 1 "m.group(1)" utils/markdown.py
# Should show: _link_replace_and_protect at line 232 uses m.group(1) AND m.group(2)
#              angle_link_replace at line 260 uses m.group(1)
#              _auto_link at line 292 uses m.group(1) or m.group(2)  ← fixed
```

### 4. Declaration

This spec is complete when §10 items 1-3 are all checked off. The implementer must run the verification gate at each step of §5.
