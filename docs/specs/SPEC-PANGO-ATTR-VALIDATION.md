---
status: DONE
---
# SPEC-PANGO-ATTR-VALIDATION: Attribute validation for Pango markup escaping + guard coverage for all dynamic set_markup sites

**Implements:** Fix for the 2026-08-21 Pango markup warning investigation (docs/investigations/2026-08-21-PANGO-WARNINGS-AND-SSL-RETRY.md)
**Estimated effort:** ~4 hours (as implemented: 2 phases, 1 send-back, 2 audits)
**Depends on:** SPEC (2026-07-31) Pango Markup Guard — commit `898062a` established the `Pango.parse_markup` pre-validation pattern in `make_safe_label`
**Status:** DONE — Phase 1 commit `6fda382`, Phase 2 commit `3e2cebc`

---

## 1. Problem Statement

Five `Gtk-WARNING **: Failed to set text ...` errors were collected from the terminal over a four-day window. Investigation (read-only, docs/investigations/) reproduced all five character-for-character and traced them to one root cause with two contributing gaps:

### Root cause: `escape_for_pango` validates tag names but not attribute names

`utils/escaping.py:escape_for_pango()` preserves tags in `_PANGO_KNOWN_TAGS` (`b, i, u, s, tt, big, small, span, sub, sup, o`) **with their attributes intact**, applying only attribute-name lowercasing and ampersand escaping. It does not check whether the attribute *names* are ones Pango actually accepts.

Agent output routinely contains JSX/TSX source code. When that code passes through the chat/feed render pipeline, tags like `<span classname="field-error">` or `<span style={{ color: "red" }}>` survive escaping intact, reach `Gtk.Label.set_markup()`, and Pango's markup parser rejects them:

```
Attribute 'classname' is not allowed on the <span> tag on line 3 char 41
Error on line 4 char 18: Odd character "{", expected an open quote mark
```

`Gtk.Label.set_markup()` does not raise a catchable Python exception on malformed markup — it logs the `Gtk-WARNING` and **renders the label empty**. The user-visible symptom is silent content loss: feed cards and chat bubbles containing code snippets render blank.

### Contributing gap 1: unguarded `set_markup` call sites

Commit `898062a` (2026-07-31) added the correct defense — `make_safe_label()` pre-validates via `Pango.parse_markup()` (which DOES raise a catchable `GLib.Error`) and falls back to `set_text()`. But only chat-bubble *text* paths used it. An audit of every `set_markup` call site found dynamic-content sites still calling it directly:

- `ui/views/feed_card.py` — card body label and diff card label (the likely source of all five logged warnings)
- `ui/views/chat_bubble.py:391` — code-block label (safe today only because `syntax_highlight.highlight()` happens to escape values and emit only `foreground=` attrs)
- `ui/views/file_tree.py:217, :1092` — file row label and project title label

### Contributing gap 2: per-line blast radius in diff cards

The diff card joined all lines into one markup string before a single `set_markup` call. One malformed line invalidated the whole string, so the guard's fallback degraded the **entire diff** to plain text — destroying color markup on all valid lines because of one bad line.

### Non-goal (explicitly out of scope)

Value validation. Attributes whose *name* is allowlisted but whose *value* Pango rejects (`<span foreground=noquotes>`) still pass the escaper by design. Enforcing value shapes would require per-attribute value grammars — invasive, and the downstream guard already handles the failure. This limitation is documented in the test docstring (`test_valid_name_invalid_value_preserved_guard_handles`) rather than hidden.

---

## 2. Design

### 2.1 Attribute-name allowlist (Phase 1, `utils/escaping.py`)

A `_SPAN_ALLOWED_ATTRS` frozenset of the 33 attributes Pango's markup parser accepts on `<span>`, each verified by probing `Pango.parse_markup('<span ATTR="v">t</span>')`:

```
foreground, background, alpha, bgalpha, underline, underline_color, rise,
strikethrough, strikethrough_color, fallback, lang, font, font_desc,
font_family, face, size, font_size, font_weight, weight, font_style, style,
font_stretch, stretch, font_variant, variant, font_features, gravity,
gravity_hint, letter_spacing, show, insert_hyphens, allow_breaks, line_height,
color (Pango-deprecated alias for foreground; used by diff_card.py templates)
```

Deliberately excluded despite appearing in some Pango C-API references: `bg` (Pango's markup parser rejects it — only `background` is valid; caught by adversarial audit), `fgcolor`/`bgcolor` (aliases not currently needed; noted as future additions if observed in the wild).

Non-span known tags (`b`, `i`, `u`, `s`, `tt`, `big`, `small`, `sub`, `sup`, `o`) take **no attributes**: any attribute on them escapes the whole tag.

**Behavior:** if any attribute name on a known tag is not in the allowlist (case-insensitive, after existing lowercasing), the **entire tag is escaped as literal text** — identical treatment to unknown tags. No per-attribute stripping (partial preservation would still risk parse failure and is harder to reason about).

`utils/` stays GTK-free: the validation is pure string work; no Gtk/Pango import in `escaping.py`.

### 2.2 Guard pattern (Phase 1 + Phase 2)

Every dynamic-content `set_markup` site uses the pattern proven in `898062a`:

```python
try:
    Pango.parse_markup(markup, -1, "\x00")
    label.set_markup(markup)
except Exception:
    label.set_text(fallback_text)
```

Sites and their fallbacks:

| Site | Fallback | Rationale |
|---|---|---|
| `feed_card.py` body label | `set_text(text)` — raw input | Single text block; losing formatting acceptable, content never lost |
| `feed_card.py` diff card | **Per-line**: each line's markup validated individually; failed line falls back to its own escaped text | One malformed line costs only its own color, never the whole diff |
| `chat_bubble.py` code-block label | `set_text(raw_content)` — raw source, not the escaped markup | User sees real source code, not `&lt;` entities |
| `file_tree.py` row label | `set_text(display_name)` | Prefix is applied via CSS margin, not the string — identical rendering |
| `file_tree.py` project title | `set_text(name)` | Bold lost, content kept |

### 2.3 Two-layer invariant (documented, not hidden)

- Layer 1 (escaper): validates attribute **names**. Unknown name → tag escaped at the source; no downstream guard needed.
- Layer 2 (guard): catches everything Layer 1 lets through — malformed values, entity edge cases, future regressions. Degrades to plain text rather than an empty label.

---

## 3. Files Modified

| File | Change |
|---|---|
| `utils/escaping.py` | `_SPAN_ALLOWED_ATTRS` frozenset + attribute-name validation in the opening-tag branch; stale `href` comment replaced with a realistic `font=` example |
| `ui/views/feed_card.py` | Body label guard; per-line diff validation |
| `ui/views/chat_bubble.py` | Code-block label guard (Phase 2) |
| `ui/views/file_tree.py` | `Pango` import; row-label and title-label guards (Phase 2) |
| `tests/test_escaping.py` | `TestSpanAttributeValidation` — 8 tests |
| `tests/test_pango_guard_sites.py` | 18 tests (NEW, Phase 2) |

---

## 4. Test Plan (as implemented)

**Escaping tests (Phase 1):** unknown attr escaped; JSX `style={{...}}` escaped; valid attrs preserved; `<b>` with any attr escaped; `ClassName` case-normalized then escaped; `bg` escaped (audit-added); `color` deprecated alias preserved (audit-added); name-valid/value-invalid preserved with the guard contract documented in the docstring.

**Guard-site tests (Phase 2):** pure `Pango.parse_markup` branch logic; source-inspection tests per site that **fail if a guard is removed** (mutation-verified by the auditor); branch tests via mocks.

**Environmental note:** the sandbox segfaults on real `Gtk.Label` construction at process exit (pre-existing, documented). `test_file_tree_sort_filter.py` segfaults on stashed (unmodified) code too — verified via `git stash` probe during this loop.

---

## 5. Verification

- Reproduction probe: all five originally-failing inputs now parse clean (`<span classname=...>`, `style={{...}}`, `bg=`, `color=`, `foreground=noquotes` cases).
- Full app-generated markup sweep: every `<span ...>` literal in `ui/` (feed_card diff colors, markdown warning prefix, toolbar, chat_input_toolbar, main_content, left_panel, activity_handler, file_tree, feedbar) probed against Pango — all still parse. No over-escaping regression.
- Tests: `TestSpanAttributeValidation` 8/8; `test_pango_guard_sites.py` 18/18; `test_feed_card.py` 70/70; `test_escaping.py` 68 pass + 1 pre-existing environmental deselect; `test_file_tree_handler` 17/17; `test_file_tree_helpers` 33/33.

---

## 6. Acceptance Criteria

1. ✅ All five investigated warning inputs render without `Gtk-WARNING` (verified via `Pango.parse_markup` probe).
2. ✅ No legitimate app-generated markup is escaped (33-attr allowlist + full `ui/` sweep).
3. ✅ No `set_markup` call on dynamic content lacks the guard (all sites audited; static/`xml_template` sites exempt by design).
4. ✅ One malformed diff line cannot destroy color on valid lines (per-line validation).
5. ✅ `utils/` purity preserved (`escaping.py` imports only `re`, `html`).
6. ✅ Value-validation limitation documented in a test docstring, not silently ignored.
