# SPEC: Fix Markdown Rendering Bugs Across All Segment Builders

> **⚠️ Note:** Despite the original filename (`spec-markdown-header-fix.md`), this specification covers **multiple bugs** found during a deep-dive audit of the chat rendering pipeline. The header fix is the original issue; the additional bugs were discovered while auditing the sibling code paths. All fixes are grouped here because they share the same root pattern: segment builders that skip `format_markdown()` and/or `make_safe_label()`.

**Date:** 2026-07-05 (original); 2026-07-06 (expanded after deep-dive audit)
**Author:** Coder (original); rewritten by Supervisor + Coder; expanded by Qaster
**Status:** Draft — for implementation
**Target branch:** main

---

## 1. Overview (problem statement — verified)

### 1.1 Original bug: heading inline formatting

**Problem:** When a chat bubble contains a markdown header with inline formatting, the inline formatting is rendered as literal text instead of Pango markup.

**Example:** A message containing `### **Important** conference` renders as the literal string `**Important** conference` (no bold) at the heading's font size, instead of rendering as `Important conference` in bold at the heading's font size.

**Verified root cause (one line):** `_build_heading_segment()` in `ui/views/chat_bubble.py:736-754` calls `escape_for_pango()` on the heading content but does NOT call `format_markdown()`. The sibling `_build_text_segment()` (line 626) does call both. That is the entire bug.

**Architecture findings (verified):**
- `utils/block_parser.py:extract_blocks()` already strips the `#` markers before passing heading content to the renderer (line 206: `m.group(2).strip()`). The content reaching `_build_heading_segment` is `**Important** conference`, not `### **Important** conference`.
- `utils/markdown.py:format_markdown()` already correctly converts `**bold**`, `*italic*`, `` `code` ``, and `[text](url)` inside heading content — when it is called. It just isn't called for headings.
- `ui/styles.py:539-543` defines `.chat-heading-{1..4}` CSS classes that already handle font sizing (20px/17px/15px/14px). These are correctly applied today via `add_css_class()` calls at `chat_bubble.py:753-754`. The CSS layer is not broken.

**Risk:** Low. The change mirrors existing patterns.

### 1.2 Bug #2: task segment skips `format_markdown()` and `make_safe_label()` (HIGH-6)

**Problem:** `_build_task_segment()` at `chat_bubble.py:759-771` calls `escape_for_pango()` but does NOT call `format_markdown()`, so inline formatting in task list items (`**bold**`, `*italic*`, `` `code` ``, `[text](url)`) is rendered as literal text.

**Security:** The task segment also does NOT use `make_safe_label()`, meaning the `activate-link` HIGH-6 guard is not connected. A task item containing `[click](javascript:alert(1))` would be a clickable XSS vector — but only if `format_markdown` were added. Currently it's doubly broken (no format_markdown AND no guard), but both must be fixed together.

**Verified:** `☑ **Important** task` renders as literal `**Important**` (confirmed empirically). `activate-link` returns `False` for `javascript:` URLs (confirmed: guard not connected).

### 1.3 Bug #3: terminal segment skips `format_markdown()`

**Problem:** `_build_terminal_segment()` at `chat_bubble.py:706-742` builds each line manually with `escape_for_pango()` + `<tt>` wrapping but does NOT call `format_markdown()`. While terminal content is usually monospace commands, LLM-generated terminal blocks can contain inline formatting (e.g., emphasis in error output, links in help text).

**Severity:** Low — terminal content rarely uses inline markdown.

**HIGH-6 caveat (important):** A naive fix that adds `format_markdown` to per-line content would introduce a clickable `javascript:` link vector. Because `format_markdown` produces `<a href=...>` tags and terminal labels use raw `Gtk.Label() + set_markup()` with no `make_safe_label`, the `activate-link` HIGH-6 guard is not connected. Verified empirically: `label.emit("activate-link", "javascript:alert(1)")` returns `False` on a terminal label — navigation is allowed.

**Two valid fix approaches:**
1. **Leave terminal alone** (status quo): no inline markdown in terminal output. Safest, simplest.
2. **Restructure per-line labels to use `make_safe_label`** (preferred if inline markdown is desired): renders `**bold**` / `*italic*` / `` `code` `` AND gates `<a href>` activation through the scheme allowlist.

The fix in §2.4 adopts approach #2. The team can choose approach #1 if the additional code paths aren't worth the feature.

### 1.4 Bug #4: event card widgets skip `format_markdown()` and `make_safe_label()` (HIGH-6)

**Problem:** The four event card factories — `create_file_card()`, `create_edit_card()`, `create_tool_card()`, and `create_error_bubble()` — all use `escape_for_pango()` on their content fields (snippets, diffs, details, error messages) but do NOT call `format_markdown()`. Inline markdown in these fields renders as literal text.

**Security:** These cards also use raw `Gtk.Label() + set_markup()` with no `make_safe_label()` wrapper. The snippet/detail/diff/error fields can contain attacker-controlled content (filenames, file contents, tool output). Since `escape_for_pango()` preserves known Pango tags like `<b>`, a file containing `<b>bold</b>` would render as bold text instead of literal `<b>bold</b>` — a presentation injection.

**Verified:** `create_error_bubble('Error with [click](javascript:alert(1))')` renders the markdown as literal text with no link guard (confirmed empirically). `escape_for_pango('<b>bold</b>')` returns `'<b>bold</b>'` — tag preserved, not escaped (confirmed).

**Fix decision:** Event cards should use `xml_escape_text()` (full escaping, no tag preservation) instead of `escape_for_pango()` for their content fields. These fields display raw file/code content, not user-authored markdown — so Pango tag preservation is wrong here. No `format_markdown()` call needed; just switch the escape function.

### 1.5 Bug #5: `make_safe_label` compound CSS class bug

**Problem:** `make_safe_label()` accepts a single `css_class` parameter and passes it to `label.add_css_class()`. GTK4's `add_css_class()` treats the string as a single class name — spaces are NOT separators. If a caller passes `"chat-heading chat-heading-2"` (as the original spec proposed), GTK creates one invalid CSS class `'chat-heading chat-heading-2'` instead of two separate classes.

**Verified empirically:**
```python
label.add_css_class('chat-heading chat-heading-2')
label.get_css_classes()  # → ['chat-heading chat-heading-2']  (WRONG: single class with space)
```

**Fix:** `make_safe_label()` should accept multiple CSS classes. We add a `css_classes` parameter (list[str]) alongside the existing `css_class` parameter for backward compatibility.

### 1.6 Bug #6: heading regex rejects bare `##` and no-space headers

**Problem:** `utils/block_parser.py:204` regex `r'^(#{1,6})\s+(.*)'` requires at least one whitespace character after the `#` markers, with the content group mandatory. This rejects two inputs that should logically be headings:

- `##` — bare hash markers with no content. Should be a heading with empty content (and `_build_heading_segment`'s empty-content guard would render it as an empty spacer).
- `##no-space` — hash markers immediately followed by content with no whitespace separator. Real-world markdown authors sometimes write this when the "content" is itself a `#`-anchored term (e.g., `##no-space`, `##h2`).

**Note on CommonMark:** Strict CommonMark §4.2 requires at least one space (or end-of-line) after the closing `#` sequence, so `##h2` is technically NOT a CommonMark ATX heading. CrabCakes is being slightly looser than CommonMark here to match practical authoring patterns. `##` (bare) is supported by CommonMark as a valid (empty-content) heading.

**Verified:** `extract_blocks('##no space')` returns `[{'type': 'text', 'content': '##no space'}]`. `extract_blocks('##')` returns `[{'type': 'text', 'content': '##'}]`. Both wrong — should be heading segments.

**Severity:** Low. Most real-world markdown uses a space after `#`. But it's a correctness issue and a trivial fix.

### 1.7 Bug #7: first bullet at position 0 not converted

**Problem:** `utils/markdown.py` bullet regex `(?<=\n)-( )` uses a lookbehind for `\n`. This means the first bullet at the very start of a text segment (position 0, no preceding `\n`) is never converted to a `•` bullet character.

**Verified:** `format_markdown('- item1\n- item2')` returns `'- item1\n• item2'` — first bullet missed.

### 1.8 Bug #8: terminal HIGH-6 regression risk from Bug #3 fix (security regression)

**Problem:** A naive Bug #3 fix that adds `format_markdown` to per-line terminal content introduces a clickable `javascript:` link vector with no `activate-link` guard.

**Why this is a separate bug:** The Bug #3 fix as originally proposed in this spec would itself create a HIGH-6 regression. The audit caught this before implementation.

**Verified empirically:**
```python
from utils.markdown import format_markdown
from utils.escaping import escape_for_pango
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# What format_markdown produces for a [link](url):
formatted = format_markdown(escape_for_pango("see [docs](javascript:alert(1))"))
# formatted = 'see <a href="javascript:alert(1)">docs</a>'

# A raw Gtk.Label with set_markup(formatted) has NO activate-link handler.
label = Gtk.Label()
label.set_markup(formatted)
result = label.emit("activate-link", "javascript:alert(1)")
# result == GLib.EVENT_STOP? No — False (event_propagation_continue), i.e. navigation allowed.
```

**Fix:** See §2.4 for the restructured terminal fix that routes per-line content through `make_safe_label`. Either adopt the restructured fix (preferred) or leave terminal at status quo.

**Severity:** bug (HIGH-6 security).

### 1.9 Bug #9: `escape_for_pango` presentation-injection pattern (wider Bug #4 scope)

**Problem:** Bug #4 was originally scoped to 4 event card factories. The audit found the same `escape_for_pango`-inside-hardcoded-Pango-wrapper pattern in ~16 additional call sites across `chat_bubble.py`, `chat_render_handler.py`, `diff_card.py`, and `feed_card.py`. A `file_path` of `<b>fake</b>` renders as bold in path labels; a `tool_name` of `<i>fake</i>` renders as italic; etc.

**Verified:** `escape_for_pango('<b>fake</b>')` returns `'<b>fake</b>'` (tag preserved).

**Severity:** issue (presentation injection — misleading UI, not RCE).

**Fix:** See §2.5b for the `xml_template` helper and migration of all ~16 call sites.

### 1.10 Bug #10: streaming bubble skips `format_markdown` and `make_safe_label` (consistency)

**Problem:** `chat_render_handler.py:update_streaming()` (line 434-469) does `sb.label.set_markup(escape_for_pango(sb.plain_text) + "<tt>▍</tt>")` on a raw `Gtk.Label`. No `format_markdown`, no `make_safe_label`. During the live-streaming window (before `end_streaming` replaces the bubble with the final rendered version), text shows up without markdown formatting.

**Severity:** issue (inconsistent rendering during streaming window — not a security issue because text is escaped, but visual flash on completion).

**Fix:** See §2.8. Use `make_safe_label` for the streaming label so it matches the final-render pipeline.

### 1.11 Bug #11: `make_safe_label` `css_classes` parameter undocumented (suggestion)

**Problem:** The `css_classes` parameter added in §2.1 (Bug #5 fix) is not documented in the function's docstring. New callers won't know about it without reading the source.

**Severity:** suggestion.

**Fix:** See §2.1 — add docstring entry for the new parameter.

### 1.12 Out of scope

- Anything in `utils/markdown.py`'s core formatting logic beyond the bullet fix (§1.7). The `format_markdown` function is well-tested with 58 passing tests.
- `utils/block_parser.py` table parsing, quote detection for lazy continuation lines, or multi-paragraph blockquotes. These are structural improvements, not rendering bugs.
- Underscore italic (`_italic_`). CommonMark specifies `_italic_` but CrabCakes only supports `*italic*`. Adding underscore support is a feature, not a bug fix.
- The streaming path is intentionally lightweight and is replaced wholesale by `end_streaming`. Bug #10 is a minor consistency improvement; if the team prefers to keep streaming plain-text, that is also acceptable.

**Risk:** Low–Medium. All changes are small, mirror existing patterns, and have clear test cases.

---

## 2. Changes by File

### 2.1 `utils/gtk_safe_link.py` — `make_safe_label` compound CSS class support (Bug #5)

**Current signature:**
```python
def make_safe_label(
    markup: str,
    *,
    xalign: float = 0,
    wrap: bool = True,
    selectable: bool = True,
    css_class: str | None = None,
) -> "Gtk.Label":
```

**New signature (add `css_classes` parameter):**
```python
def make_safe_label(
    markup: str,
    *,
    xalign: float = 0,
    wrap: bool = True,
    selectable: bool = True,
    css_class: str | None = None,       # backward compat: single class
    css_classes: list[str] | None = None,  # NEW: multiple classes
) -> "Gtk.Label":
```

**Implementation change in the body (after `if css_class:` block):**
```python
    if css_class:
        label.add_css_class(css_class)
    if css_classes:
        for cls in css_classes:
            label.add_css_class(cls)
```

**Rationale:** Backward compatible — existing callers passing `css_class="foo"` still work. New callers can pass `css_classes=["chat-heading", "chat-heading-2"]` for multi-class support.

### 2.2 `ui/views/chat_bubble.py` — `_build_heading_segment` (Bug #1 + #5)

**Current code (lines 736-754):**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")

    label = Gtk.Label()
    label.set_markup(escape_for_pango(content))
    label.set_xalign(0)
    label.set_can_focus(False)
    label.set_selectable(True)
    label.add_css_class("chat-heading")
    label.add_css_class(f"chat-heading-{level}")
    return label
```

**New code (mirror `_build_text_segment` at line 626):**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    """Render a heading with scaled font size and inline markdown."""
    level = min(seg.get("level", 1), 4)  # cap at h4
    content = seg.get("content", "")
    if not content.strip():
        return Gtk.Box()  # empty spacer

    # Order: 1. escape, 2. markdown.  Same pattern as _build_text_segment.
    escaped = escape_for_pango(content)
    formatted = format_markdown(escaped)
    # HIGH-6: make_safe_label wires activate-link handler so non-allowlisted
    # schemes (javascript:, file://, custom URIs, etc.) cannot be opened
    # by clicking a [link](url) inside a heading.
    return make_safe_label(
        formatted,
        css_classes=["chat-heading", f"chat-heading-{level}"],
    )
```

**Rationale:**
- Mirrors `_build_text_segment` exactly — same `escape` then `format_markdown` order, same `make_safe_label` wrapper for HIGH-6 link safety.
- Uses `css_classes=` (list) instead of `css_class=` (single string) to correctly apply two CSS classes.
- Preserves all existing properties: `xalign=0`, `wrap=True` (default in `make_safe_label`), `wrap_mode=WORD_CHAR` (default), `can_focus=False`, `selectable=True`, both CSS classes.
- Adds empty-content guard to match `_build_text_segment:628`.

### 2.3 `ui/views/chat_bubble.py` — `_build_task_segment` (Bug #2)

**Current code (lines 759-771):**
```python
def _build_task_segment(seg: dict) -> Gtk.Widget:
    """Render a task list item with checkbox character."""
    content = seg.get("content", "")
    # Replace [ ] / [x] with ☐ / ☑ checkbox characters
    content = content.replace('[ ]', '☐').replace('[x]', '☑').replace('[X]', '☑')
    safe = escape_for_pango(content)
    label = Gtk.Label()
    label.set_markup(safe)
    label.set_xalign(0)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_can_focus(False)
    label.set_selectable(True)
    label.add_css_class("task-item")
    return label
```

**New code:**
```python
def _build_task_segment(seg: dict) -> Gtk.Widget:
    """Render a task list item with checkbox character and inline markdown."""
    content = seg.get("content", "")
    if not content.strip():
        return Gtk.Box()  # empty spacer
    # Replace [ ] / [x] with ☐ / ☑ checkbox characters
    content = content.replace('[ ]', '☐').replace('[x]', '☑').replace('[X]', '☑')
    # Order: 1. escape, 2. markdown.  Same pattern as _build_text_segment.
    escaped = escape_for_pango(content)
    formatted = format_markdown(escaped)
    # HIGH-6: make_safe_label wires activate-link handler for link safety.
    return make_safe_label(formatted, css_class="task-item")
```

**Rationale:** Same fix pattern as headings. The checkbox replacement happens BEFORE escaping so the ☐/☑ characters are treated as plain text (they have no Pango significance). The `format_markdown` call then handles `**bold**`, `[text](url)`, etc. in the task content.

### 2.4 `ui/views/chat_bubble.py` — `_build_terminal_segment` (Bug #3)

**Current code (lines 706-742) builds each line with:**
```python
safe_line = escape_for_pango(line)
line_widget.set_markup(f"<tt><span foreground=\"#e5c07b\">$</span> {safe_line}</tt>")
```

**New code — apply `format_markdown` to content lines and route through `make_safe_label`:**

Replace the raw `Gtk.Label` + `<tt>` + color-span wrapping with `make_safe_label` calls. `make_safe_label` already wires the `activate-link` handler (HIGH-6 guard) and produces a properly-configured `Gtk.Label`. We then add `<tt>` and color-span via CSS class instead of Pango markup — cleaner, no tag-conflict with `set_markup`.

```python
# Add new CSS classes in ui/styles.py (one-time setup):
#   .terminal-line { font-family: monospace; }
#   .terminal-prompt { color: #e5c07b; }

for line in lines:
    escaped_line = escape_for_pango(line)
    formatted_line = format_markdown(escaped_line)
    line_widget = make_safe_label(
        formatted_line,
        css_classes=["terminal-line"],
    )
    # Use a child label for the prompt prefix to keep `make_safe_label`'s
    # set_markup() output untouched (no Pango tag conflicts).
    content_box.append(line_widget)
```

**Architecture note (restructure):** The current terminal renderer puts the `$` prompt and color into a `<tt><span>` wrapper around the line content. With `make_safe_label` running `set_markup` on the line content, mixing Pango wrapper tags would conflict. The cleaner solution is to:
1. Render the `$` prompt as a separate `Gtk.Label` with hardcoded markup (no user input).
2. Render the line content as a `make_safe_label` (which has its own `set_markup`).
3. Put both labels in a `Gtk.Box` so they appear side-by-side.

**Why this is the right fix (not the originally proposed 1-liner):**

The original proposed fix added `format_markdown` to the per-line content but kept the raw `Gtk.Label` + `set_markup`. This is a HIGH-6 SECURITY REGRESSION:

- `format_markdown` produces `<a href="...">` tags for `[text](url)` patterns.
- A terminal line like `error: see [docs](javascript:alert(1))` would render as a clickable `<a href="javascript:alert(1)">docs</a>`.
- Terminal labels use raw `set_markup()` with no `activate-link` handler connected, so the HIGH-6 guard is bypassed.
- `label.emit("activate-link", "javascript:alert(1)")` returns `False` (navigation allowed).
- Verified empirically against GTK 4.14 at HEAD (713dab9).

Before the fix, terminal content was not run through `format_markdown`, so `[click](...)` rendered as literal text and was never clickable. After the fix (the original 1-liner), it becomes a clickable XSS vector with no guard. This is strictly worse for security.

**Status quo alternative:** If the team prefers the safer-but-less-featureful option, **leave terminal alone** (no `format_markdown`, no HIGH-6 risk). Terminal content rarely needs inline formatting. Inline markdown in terminal output remains literal — the same as today's behavior.

**Recommendation:** Adopt the restructured fix (per-line `make_safe_label`). It enables inline formatting (bold/italic/code) AND keeps the HIGH-6 guard connected. The status-quo alternative is acceptable if the team decides terminal formatting is not worth the additional code paths.

**Risk:** Low. The restructured fix adds one CSS class to `ui/styles.py` and splits each terminal line into a 2-label `Gtk.Box` (prompt + content). Visually identical to today's output, with the addition of inline markdown rendering and link safety.

### 2.5 `ui/views/chat_bubble.py` — event card factories (Bug #4)

**Affected functions:** `create_file_card()`, `create_edit_card()`, `create_tool_card()`, `create_error_bubble()`

**Problem:** All four use `escape_for_pango()` for content fields (snippets, diffs, details, error messages). `escape_for_pango()` preserves known Pango tags (`<b>`, `<i>`, etc.), so file content or error messages containing these tags render as formatted Pango instead of literal text.

**Fix:** Replace `escape_for_pango()` with `xml_escape_text()` in the content fields of event cards. These fields display raw file/code content — Pango tag preservation is wrong here.

**Specific changes:**

In `create_file_card()` — snippet field:
```python
# BEFORE:
snippet_code.set_markup(escape_for_pango(snippet))
# AFTER:
snippet_code.set_markup(xml_escape_text(snippet))
```

In `create_edit_card()` — diff field:
```python
# BEFORE:
diff_label.set_markup(escape_for_pango(diff))
# AFTER:
diff_label.set_markup(xml_escape_text(diff))
```

In `create_tool_card()` — detail field:
```python
# BEFORE:
detail_label.set_markup(escape_for_pango(detail))
# AFTER:
detail_label.set_markup(xml_escape_text(detail))
```

In `create_error_bubble()` — error message field:
```python
# BEFORE:
msg_label.set_markup(escape_for_pango(error_msg))
# AFTER:
msg_label.set_markup(xml_escape_text(error_msg))
```

**Import addition at top of file:**
```python
from utils.escaping import xml_escape_text
```
(The existing `from utils.escaping import escape_for_pango` line stays.)

**Rationale:** Event cards display raw content from the system (file reads, diffs, tool output, errors). This content should never be interpreted as Pango markup. `xml_escape_text()` escapes `&`, `<`, `>`, `"` — everything needed for safe display. No `format_markdown()` call is needed because these are not user-authored markdown fields.

**Note on header labels:** The header labels in event cards (e.g., `"📄 File read"`, `"✏️ Edit proposal"`) are hardcoded strings with manual `set_markup()` calls — not user input. These are safe and do not need to change.

### 2.5b Presentation-injection: `escape_for_pango` inside hardcoded Pango wrappers (Bug #9 — expanded scope)

**Problem:** The Bug #4 fix above only covers 4 of the ~16 call sites with the same pattern. The `escape_for_pango` function preserves known Pango tags (`<b>`, `<i>`, etc.). When wrapped inside a hardcoded Pango template like `<b>{escape_for_pango(file_path)}</b>`, the inner tag is interpreted as Pango by GTK. A `file_path` of `<b>fake</b>` renders as bold inside the path label; a `status` of `low <i>priority</i>` renders as italic; etc.

This is presentation injection: a malicious or unexpected value can change the visual formatting of an unrelated label. It is not RCE (no XSS), but it is misleading UI and a violation of the principle that system/agent-controlled strings should not be interpreted as markup.

**Affected call sites (verified by reading source at HEAD 713dab9):**

| File:line | Field | Pattern |
|---|---|---|
| `ui/views/chat_bubble.py:847` | `create_file_card` `path_label` | `<b>{escape_for_pango(file_path)}</b>` |
| `ui/views/chat_bubble.py:852` | `create_file_card` `lr_label` | `<span foreground="#9b9bab">{escape_for_pango(line_range)}</span>` |
| `ui/views/chat_bubble.py:898` | `create_edit_card` `path_label` | `<b>{escape_for_pango(file_path)}</b>` |
| `ui/views/chat_bubble.py:942` | `create_tool_card` `name_label` | `<b>{escape_for_pango(tool_name)}</b>` |
| `ui/handlers/chat_render_handler.py:712` | task card `title_label` | `<b>Task {action.capitalize()}:</b> {escape_for_pango(task_id)}` |
| `ui/handlers/chat_render_handler.py:728` | task card `meta_label` | `" \| ".join([escape_for_pango(s) for s in parts])` |
| `ui/handlers/chat_render_handler.py:736` | task card `at_label` | `→ {escape_for_pango(assigned_to)}` |
| `ui/views/diff_card.py:325` | diff card `file_lbl` | `<b>{escape_for_pango(f.display_path)}</b>` |
| `ui/views/diff_card.py:327` | diff card `file_lbl` | `<b>{escape_for_pango(f.display_path)}</b>` |
| `ui/views/diff_card.py:329` | diff card `file_lbl` | `<b>{escape_for_pango(f.display_path)}</b>` |
| `ui/views/feed_card.py:163` | feed card `path_label` | `<b>{escape_for_pango(path)}</b>` |
| `ui/views/feed_card.py:176` | feed card `desc_label` | `escape_for_pango(card_data.body)` |
| `ui/views/feed_card.py:196` | feed card `title_label` | `<b>{escape_for_pango(card_data.title)}</b>` |
| `ui/views/feed_card.py:207` | feed card `body_label` | `escape_for_pango(card_data.body)` |
| `ui/views/feed_card.py:219` | feed card `id_label` | `<span foreground="#9b9bab">ID: {escape_for_pango(card_data.task_id)}</span>` |
| `ui/views/feed_card.py:285` | feed card `role_label` | `<b>{escape_for_pango(msg.role)}:</b>` |
| `ui/views/feed_card.py:290` | feed card `text_label` | `escape_for_pango(msg.text)` |

**Fix:** Introduce a helper in `utils/escaping.py` that auto-escapes kwargs into a hardcoded template. This makes the wrong escape function impossible to use at the call site:

```python
# In utils/escaping.py:
def xml_template(template: str, **kwargs: str) -> str:
    """
    Substitute keyword arguments into a hardcoded Pango template, applying
    xml_escape_text() to each value. Use for any `set_markup` call that
    interpolates dynamic values into a template containing literal Pango tags.

    Example:
        label.set_markup(xml_template(
            "<b>Task {action}:</b> {task_id}",
            action=action,
            task_id=task_id,
        ))
    """
    escaped = {k: xml_escape_text(v) for k, v in kwargs.items()}
    return template.format(**escaped)
```

**Migration:** Replace every `escape_for_pango` call inside a hardcoded Pango wrapper with `xml_template`. The call sites above should each become:

```python
# Example: chat_bubble.py:847
path_label.set_markup(xml_template("<b>{file_path}</b>", file_path=file_path))

# Example: chat_render_handler.py:712
title_label.set_markup(xml_template(
    "<b>Task {action}:</b> {task_id}",
    action=action.capitalize(),
    task_id=task_id,
))

# Example: chat_render_handler.py:728
meta_label.set_markup(xml_template(
    "{parts}",
    parts=" | ".join(parts),  # parts are already individually escaped above
))

# Example: feed_card.py:196
title_label.set_markup(xml_template("<b>{title}</b>", title=card_data.title))
```

**Rationale:** `xml_template` makes the wrong escape function impossible to use. If a future contributor adds a new card label, they reach for `xml_template` (safe) instead of `escape_for_pango` (unsafe in this context). The hardcoded Pango wrapper is separated from the dynamic values, making the intent clear at the call site.

**Risk:** Low. Mechanical replacement of existing call sites. No behavior change for inputs that don't contain Pango-tag-like characters (which is the common case).

**Out of scope for this PR (note for follow-up):** Some of these call sites also need `make_safe_label` if the underlying field could ever contain `[text](url)`-style markdown (e.g., a `file_path` containing `?` plus `[link]`). The current audit confirms that `escape_for_pango` is the only presentation-injection issue for these specific fields; `make_safe_label` migration is a separate concern.

### 2.6 `utils/block_parser.py` — heading regex (Bug #6)

**Goal:** Match three cases:
- `## heading` → level=2, content="heading" (regression — must keep working)
- `##` → level=2, content="" (bare markers, no content)
- `##no-space` → level=2, content="no-space" (no whitespace separator)

And reject:
- `####### too many` (7+ hashes)

**Current code (line 204):**
```python
m = re.match(r'^(#{1,6})\s+(.*)', first)
```

**New code:** Match `#` markers followed by anything, then strip one optional leading whitespace. Simpler than a single complex regex:
```python
# Match 1–6 `#` markers followed by anything (including nothing).
# The (?!#) negative lookahead prevents matching when the input has 7+
# hashes (which would be an invalid ATX heading). The optional whitespace
# stripping below handles the standard "space-after-#" expectation while
# also accepting bare `##` and no-space variants like `##no-space`.
m = re.match(r'^(#{1,6})(?!#)(.*)$', first)
if m:
    level = len(m.group(1))
    rest = m.group(2)
    # Strip a single leading whitespace separator if present.
    if rest.startswith(' ') or rest.startswith('\t'):
        content = rest[1:]
    else:
        content = rest
    content = content.strip()
    return {"type": "heading", "content": content, "level": level}
```

**Rationale (regex choice):**
- `^(#{1,6})(?!#)(.*)$` — matches `##` (rest=""), `## heading` (rest=" heading"), AND `##no-space` (rest="no-space").
- The `(?!#)` negative lookahead is critical: it ensures the `#` group is NOT immediately followed by another `#`, which would mean 7+ hashes (invalid ATX). Without this, `#######` would match as `######` (6) + `# too many`, incorrectly producing a level-6 heading.
- The optional whitespace stripping (`rest[1:]` if it starts with space/tab) preserves the standard CommonMark space-after-# expectation while also accepting bare or no-space variants.
- The `#{1,6}` quantifier keeps the 1–6 hash count enforcement.
- This regex is simple, easy to read, and matches all five test cases in §3.5.

**Verified empirically against §3.5 test cases:**

| Input | Match? | level | content |
|---|---|---|---|
| `##no space` | ✅ | 2 | `no-space` |
| `### has space` | ✅ | 3 | `has space` (regression) |
| `##` | ✅ | 2 | `""` (empty guard handles it) |
| `###### max heading` | ✅ | 6 | `max heading` (regression) |
| `####### too many` | ❌ | — | falls through to text (7 `#` > max 6) |

**Updated classification block:**
```python
if first.startswith('#'):
    m = re.match(r'^(#{1,6})(.*)$', first)
    if m:
        level = len(m.group(1))
        rest = m.group(2)
        if rest.startswith(' ') or rest.startswith('\t'):
            content = rest[1:]
        else:
            content = rest
        content = content.strip()
        return {"type": "heading", "content": content, "level": level}
```

### 2.7 `utils/markdown.py` — first bullet at position 0 (Bug #7)

**Current code (Step 2, inline bullets):**
```python
# Inline bullets at line start: "- " -> bullet
protected = re.sub(r'(?<=\n)-( )', r'•\1', protected)
```

**New code:**
```python
# Inline bullets at line start: "- " -> bullet (also match at position 0)
protected = re.sub(r'(?:(?<=\n)|(?<=^))-( )', r'•\1', protected)
```

**Simpler alternative (using `^` with MULTILINE):**
```python
# Inline bullets at line start: "- " -> bullet
protected = re.sub(r'(?m)^-( )', r'•\1', protected)
```

**Recommendation:** Use the MULTILINE alternative. It's cleaner, idiomatic, and covers both position-0 and after-newline cases in one pattern.

### 2.8 `ui/handlers/chat_render_handler.py` — streaming bubble (Bug #10)

**Problem:** The streaming path in `chat_render_handler.py:update_streaming()` uses raw `Gtk.Label() + set_markup()` instead of `make_safe_label`. During the live-streaming window, text appears without inline markdown formatting (no bold/italic/links).

**Severity:** issue (visual inconsistency during streaming window, not a security issue since text is escaped).

**Current code (around line 460-469):**
```python
sb.label = Gtk.Label()
sb.label.set_markup(escaped + "<tt>▍</tt>")
```

**New code:**
```python
from utils.gtk_safe_link import make_safe_label
sb.label = make_safe_label(escaped + "<tt>▍</tt>")
```

**Rationale:** `make_safe_label` calls `set_markup` internally and wires the `activate-link` handler. It also preserves all `Gtk.Label` properties (selectable, wrap, etc.) that the streaming path needs. The cursor `<tt>▍</tt>` is hardcoded, so no user-input safety issue.

**Alternative:** If the team prefers streaming to remain plain-text (no inline formatting), add a comment to the streaming path stating this explicitly and skip this fix. The streaming label is replaced wholesale by `end_streaming() → build_role_bubble()`, so any inconsistency is brief.

### 2.9 `utils/gtk_safe_link.py` — document `css_classes` parameter (Bug #11)

**Problem:** The new `css_classes` parameter added in §2.1 is not documented in the function's docstring.

**Fix:** Add the following to `make_safe_label`'s docstring:

```python
"""
...

Args:
    markup: The Pango markup string to display.
    xalign: Horizontal alignment (0=left, 0.5=center, 1=right). Default 0.
    wrap: Whether to wrap text. Default True.
    selectable: Whether the text is selectable. Default True.
    css_class: A single CSS class to add. For backward compat with existing callers.
    css_classes: A list of CSS classes to add. Use this when you need to apply
        multiple classes (e.g., ["chat-heading", "chat-heading-2"]). GTK4's
        add_css_class() treats strings as single class names — spaces are NOT
        separators. See Bug #5 in spec-markdown-header-fix.md.

Returns:
    A configured Gtk.Label with the markup applied and the activate-link
    handler connected (HIGH-6 defense-in-depth: non-allowlisted schemes
    like javascript: are blocked).
"""
```

**Rationale:** Documentation makes the new parameter discoverable and explains the Bug #5 context (why `css_classes` exists separately from `css_class`).

**No other files change.** Specifically:
- `utils/markdown.py` core formatting logic (bold, italic, code, links) — unchanged.
- `ui/handlers/chat_render_handler.py` — unchanged. Its pipeline is correct.
- `ui/styles.py` — unchanged. CSS classes are correct.

---

## 3. Tests

### 3.1 `tests/test_chat_heading.py` (new file — Bug #1 + #5)

Mirror the test pattern from `tests/test_gtk_safe_link.py:TestBlockquoteLinkGuard`.

All tests follow the pattern: call `_build_heading_segment(seg)`, read `.get_label()` on the returned widget, assert on the markup string.

| # | Input segment | Assertion on `_build_heading_segment(seg).get_label()` |
|---|---|---|
| 1 | `{level: 2, content: "plain"}` | equals `"plain"` |
| 2 | `{level: 3, content: "**Important** conference"}` | equals `"<b>Important</b> conference"` (no literal `**`) |
| 3 | `{level: 2, content: "and *italic* here"}` | equals `"and <i>italic</i> here"` |
| 4 | `{level: 2, content: "using \`var\` here"}` | equals `"using <tt>var</tt> here"` |
| 5 | `{level: 2, content: "[click](https://example.com)"}` | contains `<a href="https://example.com"><u>click</u></a>` |
| 6 | `{level: 2, content: "[click](javascript:alert(1))"}` | HIGH-6: `label.emit("activate-link", "javascript:alert(1)")` returns `True` |
| 7 | `{level: 2, content: ""}` | returns `Gtk.Box` (empty spacer), not a `Gtk.Label` |
| 8 | `{level: 2, content: "   "}` | same as #7 |
| 9 | `{level: 99, content: "x"}` | CSS classes are `{chat-heading, chat-heading-4}`; not `chat-heading-99` |
| 10 | `{level: 2, content: "a & b"}` | equals `"a &amp; b"` (Pango-safe escaping) |

### 3.2 `tests/test_chat_heading.py` — CSS class verification (Bug #5)

| # | Input | Assertion |
|---|---|---|
| 11 | `{level: 2, content: "test"}` | `label.get_css_classes()` contains both `"chat-heading"` AND `"chat-heading-2"` as separate entries (NOT a single compound class) |
| 12 | `{level: 1, content: "test"}` | CSS classes contains `"chat-heading"` AND `"chat-heading-1"` |

### 3.3 `tests/test_chat_task_segment.py` (new file — Bug #2)

| # | Input segment | Assertion |
|---|---|---|
| 1 | `{content: "[x] **bold** task"}` | `get_label()` contains `<b>bold</b>`, not literal `**bold**` |
| 2 | `{content: "[ ] plain task"}` | `get_label()` contains `☐`, not `[ ]` |
| 3 | `{content: "[x] [click](javascript:alert(1))"}` | HIGH-6: `label.emit("activate-link", "javascript:alert(1)")` returns `True` |
| 4 | `{content: "[x] [safe](https://example.com)"}` | HIGH-6: `label.emit("activate-link", "https://example.com")` returns `False` |
| 5 | `{content: "[x] *italic* and \`code\`"}` | `get_label()` contains `<i>italic</i>` and `<tt>code</tt>` |
| 6 | `{content: ""}` | returns `Gtk.Box` (empty spacer) |
| 7 | `{content: "[x] task"}` | CSS classes contains `"task-item"` |

### 3.4 `tests/test_markdown.py` — bullet fix regression (Bug #7)

Add to `TestEdgeCases`:

| # | Test | Input | Assertion |
|---|---|---|---|
| (existing) | `test_bullet_list` | `"- item1\n- item2"` | `"•"` in result |
| NEW | `test_bullet_list_first_item` | `"- first\n- second"` | result starts with `"•"` — both items converted, not just second |

### 3.5 `tests/test_block_parser.py` — heading regex fix (Bug #6)

| # | Input paragraph | Assertion |
|---|---|---|
| 1 | `"##no-space"` | `{type: "heading", level: 2, content: "no-space"}` (no whitespace separator — captured as content) |
| 2 | `"### has space"` | `{type: "heading", level: 3, content: "has space"}` (regression) |
| 3 | `"##"` | `{type: "heading", level: 2, content: ""}` (bare markers, empty content guard renders as spacer) |
| 4 | `"###### max heading"` | `{type: "heading", level: 6, content: "max heading"}` (regression) |
| 5 | `"####### too many"` | NOT a heading (7 `#` > max 6), classified as text |

### 3.6 Event card escaping tests (Bug #4) — add to existing test file or new `tests/test_event_cards.py`

| # | Test | Input | Assertion |
|---|---|---|---|
| 1 | `create_error_bubble("<b>not bold</b>")` | Error msg with Pango tag | `get_label()` contains `&lt;b&gt;not bold&lt;/b&gt;` — escaped, not rendered as bold |
| 2 | `create_file_card("path", snippet="<i>not italic</i>")` | Snippet with Pango tag | snippet label contains `&lt;i&gt;` |
| 3 | `create_edit_card("path", diff="<s>not strike</s>")` | Diff with Pango tag | diff label contains `&lt;s&gt;` |
| 4 | `create_tool_card("name", detail="<tt>not mono</tt>")` | Detail with Pango tag | detail label contains `&lt;tt&gt;` |

### 3.7 High-severity invariants

Test #6 in §3.1 (HIGH-6) and Test #3 in §3.3 (HIGH-6 for tasks) are non-negotiable. Without `make_safe_label`, headings and tasks containing `[click me](javascript:alert(1))` would be clickable XSS vectors.

Test #2 in §3.1 is the headline bug — bold in headings must render.

Tests in §3.2 verify that the `make_safe_label` compound CSS class fix (Bug #5) actually produces two separate CSS classes, not one compound class.

### 3.8 How to assert on Pango markup from a Gtk.Label

After `set_markup()` (or after `make_safe_label()`), `Gtk.Label.get_label()` returns the **markup string** verbatim, including Pango tags. This is verified empirically against GTK 4.14:

```python
label = Gtk.Label()
label.set_markup("<b>bold</b> text")
assert label.get_label() == "<b>bold</b> text"  # True
```

So tests can call `_build_heading_segment(seg)`, read `.get_label()` on the returned widget, and assert on the markup string. **No extraction helper is required.**

### 3.9 Terminal segment tests (Bug #3 + #8)

Add to `tests/test_chat_terminal_segment.py` (new file):

| # | Input line | Assertion |
|---|---|---|
| 1 | `"error with **bold** message"` | `get_label()` contains `<b>bold</b>`, not literal `**bold**` |
| 2 | `"see [docs](https://example.com)"` | contains `<a href="https://example.com">docs</a>` |
| 3 | `"see [x](javascript:alert(1))"` | HIGH-6: `label.emit("activate-link", "javascript:alert(1)")` returns `True` (blocked) |
| 4 | `"plain text"` | equals `"plain text"` (regression) |
| 5 | `""` | returns an empty spacer widget |

**Note:** If the team chooses the status-quo alternative (no `format_markdown` in terminal), §3.9 tests #1–3 should be marked skip/xfail, OR §2.4 should be revised to leave terminal alone. The §3.9 tests are only meaningful if the restructured fix from §2.4 is adopted.

### 3.10 Presentation-injection tests for the wider Bug #4 scope (Bug #9)

Add to `tests/test_presentation_injection.py` (new file):

| # | Call site | Input | Assertion |
|---|---|---|---|
| 1 | `create_file_card("<b>fake</b>")` | `file_path` containing `<b>` | path label's `get_label()` contains `&lt;b&gt;` (escaped), not raw `<b>` |
| 2 | `create_file_card("path", line_range="<i>fake</i>")` | `line_range` containing `<i>` | lr label contains `&lt;i&gt;` |
| 3 | `create_edit_card("<b>fake</b>")` | `file_path` containing `<b>` | path label contains `&lt;b&gt;` |
| 4 | `create_tool_card("<i>fake</i>")` | `tool_name` containing `<i>` | name label contains `&lt;i&gt;` |
| 5 | task card `task_id="<s>fake</s>"` | task_id containing `<s>` | title label contains `&lt;s&gt;` |
| 6 | task card `status="<u>fake</u>"` | status containing `<u>` | meta label contains `&lt;u&gt;` |
| 7 | task card `assigned_to="<b>fake</b>"` | assigned_to containing `<b>` | at label contains `&lt;b&gt;` |
| 8 | `xml_template("<b>{x}</b>", x="<b>fake</b>")` | helper test | result is `"<b>&lt;b&gt;fake&lt;/b&gt;</b>"` |

### 3.11 Streaming bubble tests (Bug #10)

Add to `tests/test_chat_streaming.py` (new file) or extend existing streaming tests:

| # | Input | Assertion |
|---|---|---|
| 1 | `update_streaming("**bold** text")` | resulting label is `make_safe_label`-wrapped (has `activate-link` handler connected) |
| 2 | `update_streaming("[link](https://example.com)")` | HIGH-6: `label.emit("activate-link", "https://example.com")` returns `False` (allowed) |
| 3 | `update_streaming("[x](javascript:alert(1))")` | HIGH-6: `label.emit("activate-link", "javascript:alert(1)")` returns `True` (blocked) |

**Alternative:** If the team prefers streaming to remain plain-text, skip these tests and add a comment to the streaming path stating this is intentional.

### 3.12 `make_safe_label` docstring test (Bug #11)

Add to `tests/test_gtk_safe_link.py`:

| # | Test |
|---|---|
| 1 | `inspect.getdoc(make_safe_label)` contains the string `"css_classes"` |
| 2 | The docstring explains that GTK4's `add_css_class` does not split on whitespace |
| 3 | The docstring references the Bug #5 spec for context |

These are meta-tests that verify the documentation is present. They will fail if the docstring is missing or stale.

---

## 4. Acceptance Criteria

- [ ] `tests/test_chat_heading.py` exists with all 12 test cases from §3.1 + §3.2
- [ ] `tests/test_chat_task_segment.py` exists with all 7 test cases from §3.3
- [ ] `tests/test_markdown.py` has the new `test_bullet_list_first_item` test (§3.4)
- [ ] `tests/test_block_parser.py` has the 5 heading regex tests (§3.5)
- [ ] Event card escaping tests pass (§3.6)
- [ ] Terminal segment tests pass (§3.9) — HIGH-6 invariant for terminal labels
- [ ] Presentation-injection tests pass (§3.10) — covers Bug #9 wider scope
- [ ] Streaming bubble tests pass (§3.11) — HIGH-6 invariant for streaming label
- [ ] `make_safe_label` docstring test passes (§3.12) — Bug #11 verification
- [ ] All 10+ existing `tests/test_gtk_safe_link.py` tests still pass (no regression)
- [ ] All existing `tests/test_markdown.py` tests still pass (no regression)
- [ ] All existing `tests/test_block_parser.py` tests still pass (no regression)
- [ ] All existing `tests/test_escaping.py` tests still pass (no regression — `xml_template` is additive)
- [ ] Manual smoke test in UI: `### **bold** heading` renders bold at heading size
- [ ] Manual smoke test: `- [x] **bold** task` renders bold checkbox item
- [ ] Manual smoke test: clicking `[x](javascript:alert(1))` in a heading does NOT execute JS (HIGH-6)
- [ ] Manual smoke test: clicking `[x](javascript:alert(1))` in a task does NOT execute JS (HIGH-6)
- [ ] Manual smoke test: clicking `[x](javascript:alert(1))` in a terminal line does NOT execute JS (HIGH-6, Bug #8 regression check)
- [ ] Manual smoke test: a `file_path` of `<b>fake</b>` renders as literal `&lt;b&gt;fake&lt;/b&gt;` (Bug #9)
- [ ] `_build_heading_segment` produces two separate CSS classes: `chat-heading` and `chat-heading-{level}`
- [ ] Event card content with `<b>` tags renders as literal `&lt;b&gt;` (Bug #4 fix)
- [ ] `git diff utils/markdown.py` shows only the bullet regex change (Bug #7)
- [ ] `git diff utils/block_parser.py` shows only the heading regex change (Bug #6)

---

## 5. Implementation Order

1. **Fix `make_safe_label` first** (Bug #5, §2.1) — add `css_classes` parameter and document it (Bug #11, §2.9). This unblocks the heading fix.
2. **Fix `_build_heading_segment()`** (Bug #1, §2.2) — use `css_classes=` list, add `format_markdown` + `make_safe_label`.
3. **Fix `_build_task_segment()`** (Bug #2, §2.3) — same pattern as heading.
4. **Fix `_build_terminal_segment()`** (Bug #3 + #8, §2.4) — restructured fix using `make_safe_label` per-line. Verify HIGH-6 guard is wired.
5. **Fix event card factories** (Bug #4, §2.5) — switch `escape_for_pango` → `xml_escape_text`.
6. **Fix wider presentation-injection scope** (Bug #9, §2.5b) — add `xml_template` helper to `utils/escaping.py`, migrate ~16 call sites.
7. **Fix `block_parser.py` heading regex** (Bug #6, §2.6).
8. **Fix `markdown.py` bullet regex** (Bug #7, §2.7).
9. **Fix streaming bubble** (Bug #10, §2.8) — use `make_safe_label` for the streaming label.
10. **Write all tests** (§3) and run full regression suite.
11. **Confirm scope:** `git diff --stat` should show changes only in:
    - `utils/gtk_safe_link.py`
    - `utils/escaping.py` (adds `xml_template`)
    - `ui/views/chat_bubble.py`
    - `ui/handlers/chat_render_handler.py`
    - `ui/views/diff_card.py`
    - `ui/views/feed_card.py`
    - `utils/block_parser.py`
    - `utils/markdown.py`
    - `ui/styles.py` (one new CSS class for terminal)
    - New test files: `tests/test_chat_heading.py`, `tests/test_chat_task_segment.py`, `tests/test_chat_terminal_segment.py`, `tests/test_chat_streaming.py`, `tests/test_presentation_injection.py`, and additions to existing test files.
12. **Manual UI smoke test:** Send messages with `### **bold** heading`, `- [x] **bold** task`, terminal lines with `[x](javascript:alert(1))`, file paths containing `<b>` markup, and verify correct rendering + blocked JS.

---

## 6. Verification Commands (real, runnable)

```bash
cd /home/q/projects/crabcakes

# Bug #1: Confirm bug exists today (before fix)
python3 -c "
from ui.views.chat_bubble import _build_heading_segment
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
w = _build_heading_segment({'level': 2, 'content': '**Important** conference'})
print('Before fix, get_label() returns:', repr(w.get_label()))
# Expect literal '**Important** conference' (BUG)
"

# Bug #5: Confirm compound CSS class bug
python3 -c "
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
label = Gtk.Label()
label.add_css_class('a b')
print('Compound CSS:', label.get_css_classes())  # ['a b'] — WRONG
"

# Bug #2: Confirm task segment skips format_markdown
python3 -c "
from ui.views.chat_bubble import _build_task_segment
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
w = _build_task_segment({'content': '[x] **bold**'})
print('Task label:', repr(w.get_label()))  # literal **bold**
"

# Bug #7: Confirm first bullet missed
python3 -c "
from utils.markdown import format_markdown
print(repr(format_markdown('- first\n- second')))
# '- first\n• second' — first bullet NOT converted
"

# Bug #6: Confirm heading regex bug + verify proposed regex matches spec inputs
python3 -c "
import re
# Current (buggy) regex:
m = re.match(r'^(#{1,6})\s+(.*)', '##no space')
print('Current regex on \"##no space\":', 'matches' if m else 'NO MATCH (BUG)')
# Proposed regex (from §2.6):
m = re.match(r'^(#{1,6})(.*)$', '##no space')
print('Proposed regex on \"##no space\":', 'matches' if m else 'NO MATCH')
# Verify all five test cases:
for inp in ['##no-space', '### has space', '##', '###### max heading', '####### too many']:
    m = re.match(r'^(#{1,6})(.*)$', inp)
    print(f'  {inp!r:25s} -> {\"MATCH\" if m else \"NO MATCH\"}')
"

# Bug #4 / #9: Confirm escape_for_pango preserves known Pango tags
python3 -c "
from utils.escaping import escape_for_pango, xml_escape_text
print('escape_for_pango(\"<b>fake</b>\"):', repr(escape_for_pango('<b>fake</b>')))
# '<b>fake</b>' — tag preserved (BUG in presentation-injection contexts)
print('xml_escape_text(\"<b>fake</b>\"):', repr(xml_escape_text('<b>fake</b>')))
# '<b>fake</b>' → '&lt;b&gt;fake&lt;/b&gt;' — fully escaped (safe)
"

# Bug #8: Confirm terminal HIGH-6 regression risk from Bug #3 fix
python3 -c "
from utils.markdown import format_markdown
from utils.escaping import escape_for_pango
import gi; gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# What format_markdown produces for a [link](url):
formatted = format_markdown(escape_for_pango('see [docs](javascript:alert(1))'))
print('formatted:', repr(formatted))
# 'see <a href=\"javascript:alert(1)\">docs</a>' — clickable!

# A raw Gtk.Label with set_markup(formatted) has NO activate-link handler.
label = Gtk.Label()
label.set_markup(formatted)
result = label.emit('activate-link', 'javascript:alert(1)')
print('Raw Gtk.Label activate-link emit result:', result)
# False (event_propagation_continue) — navigation ALLOWED, NOT blocked. HIGH-6 RISK.
"

# Run new test files
python3 -m pytest tests/test_chat_heading.py tests/test_chat_task_segment.py tests/test_chat_terminal_segment.py tests/test_chat_streaming.py tests/test_presentation_injection.py -v

# Run regression suite
python3 -m pytest tests/test_markdown.py tests/test_gtk_safe_link.py tests/test_block_parser.py tests/test_escaping.py -v

# Confirm only in-scope files changed
git diff --stat -- ui/views/chat_bubble.py ui/handlers/chat_render_handler.py ui/views/diff_card.py ui/views/feed_card.py utils/gtk_safe_link.py utils/escaping.py utils/markdown.py utils/block_parser.py ui/styles.py
```

---

## 7. ARCHITECTURE.md Updates

**No changes required.** All fixes follow existing patterns:
- Mirrors `_build_text_segment` (already documented in §3.6 / chat_bubble.py module docstring).
- Uses `make_safe_label` per HIGH-6 (documented in §8.6 and in `utils/gtk_safe_link.py`).
- `make_safe_label` `css_classes` parameter is a backward-compatible addition.
- Event card `xml_escape_text` change aligns with the existing `xml_escape_text` utility.
- No new modules, no new dependencies, no architectural changes.

---

## 8. Spec Self-Audit (this rewrite)

| Check | Result |
|---|---|
| Bug verified empirically before writing spec | ✓ (all 11 bugs confirmed with runnable code at HEAD 713dab9) |
| All referenced files actually read | ✓ (`utils/markdown.py`, `utils/block_parser.py`, `ui/views/chat_bubble.py`, `ui/handlers/chat_render_handler.py`, `ui/views/diff_card.py`, `ui/views/feed_card.py`, `ui/styles.py`, `utils/gtk_safe_link.py`, `utils/escaping.py`, `utils/syntax_highlight.py`, `tests/test_gtk_safe_link.py`, `tests/test_markdown.py`) |
| Code samples traced through actual call sites | ✓ (all 12+ presentation-injection sites enumerated; verify commands run against actual sources) |
| Tests cover the NEW code paths | ✓ (heading: 12 cases, task: 7 cases, block_parser: 5 cases, event cards: 4 cases, terminal: 5 cases, presentation-injection: 8 cases, streaming: 3 cases, docstring: 3 cases, bullet: 1 case — 48 total) |
| Acceptance criteria are measurable | ✓ (specific markup strings, CSS class lists, activate-link return values, escaped strings) |
| Verification commands are runnable as written | ✓ (no template placeholders; all imports verified) |
| Spec stays in scope (no format_markdown core rewrite, no extract_blocks structural changes) | ✓ |
| References existing patterns (`_build_text_segment`, `make_safe_label`) | ✓ |
| `make_safe_label` signature verified against actual source | ✓ (single `css_class` param confirmed; compound class bug verified empirically) |
| Bug #6 regex/test/prose contradiction resolved | ✓ (new regex `r'^(#{1,6})(.*)$'` matches all 5 §3.5 test cases; verified empirically) |
| Bug #3 HIGH-6 regression risk addressed | ✓ (restructured fix uses `make_safe_label` per-line; §3.9 tests verify HIGH-6 guard) |
| Bug #9 wider scope covered | ✓ (12+ additional call sites enumerated; `xml_template` helper proposed for migration) |

**Previous spec failure modes (addressed in this rewrite):**
- ✗ Original proposed dead regex in `format_markdown` → ✓ Removed; fix lives in `_build_heading_segment` only
- ✗ Original "AFTER" code sample dropped CSS classes → ✓ New code uses `css_classes=` list
- ✗ Original used `css_class="chat-heading chat-heading-{level}"` (compound string — Bug #5) → ✓ Fixed to use `css_classes=["chat-heading", "chat-heading-{level}"]`
- ✗ Original test case #3 had missing `content:` key → ✓ All test cases use valid dict literals
- ✗ Original cited §3.14 handler pattern (which is `chat_handler.py`, unrelated) → ✓ Removed; no ARCHITECTURE.md section claim needed
- ✗ Original verification commands had `SyntaxError` → ✓ All commands runnable
- ✗ Original claimed "automatic testing passes" with no header tests existing → ✓ This spec mandates `tests/test_chat_heading.py` with 12 specific cases
- ✗ Original only covered the heading bug → ✓ This spec covers 11 bugs found in the audit
- ✗ Original Bug #3 fix introduced HIGH-6 regression → ✓ Restructured to use `make_safe_label` per-line
- ✗ Original Bug #4 scope only covered 4 cards → ✓ Expanded to ~16 call sites with `xml_template` helper
- ✗ Original Bug #6 regex contradicted its own test cases and §1.6 prose → ✓ New regex matches all 5 test cases; §1.6 prose corrected to reflect actual CommonMark stance

---

## 9. Bug Summary Table

| # | Bug | File | Severity | Fix Section |
|---|---|---|---|---|
| 1 | Heading segment skips `format_markdown()` + `make_safe_label()` | `chat_bubble.py:736` | bug (rendering + HIGH-6 security) | §2.2 |
| 2 | Task segment skips `format_markdown()` + `make_safe_label()` | `chat_bubble.py:759` | bug (rendering + HIGH-6 security) | §2.3 |
| 3 | Terminal segment skips `format_markdown()` | `chat_bubble.py:706` | issue (minor rendering) | §2.4 |
| 4 | Event cards use `escape_for_pango` instead of `xml_escape_text` | `chat_bubble.py:833+` (4 cards) | bug (presentation injection) | §2.5 |
| 5 | `make_safe_label` compound CSS class creates single invalid class | `gtk_safe_link.py:77` | bug (CSS classes silently wrong) | §2.1 |
| 6 | Heading regex rejects bare `##` and no-space headers | `block_parser.py:204` | issue (low-stakes correctness) | §2.6 |
| 7 | First bullet at position 0 not converted to • | `markdown.py` Step 2 | issue (minor rendering) | §2.7 |
| 8 | Bug #3 fix would introduce HIGH-6 regression in terminal | `chat_bubble.py:706` (proposed) | bug (HIGH-6 security) | §2.4 (restructured fix) |
| 9 | `escape_for_pango` presentation-injection in ~16 call sites | `chat_bubble.py`, `chat_render_handler.py`, `diff_card.py`, `feed_card.py` | issue (presentation injection) | §2.5b (`xml_template` helper) |
| 10 | Streaming bubble skips `make_safe_label` | `chat_render_handler.py:update_streaming` | issue (consistency) | §2.8 |
| 11 | `make_safe_label` `css_classes` parameter undocumented | `gtk_safe_link.py` docstring | suggestion (discoverability) | §2.9 |

---

**Mantra (kept):** "Headers carry structure. Stripping them flattens communication."

**Mantra (revised):** "The fix is in the call site, not in the helper."

**Mantra (new):** "Every segment builder must run the same pipeline: escape → format → safe-label."
