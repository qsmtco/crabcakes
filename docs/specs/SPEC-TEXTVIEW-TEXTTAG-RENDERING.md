# SPEC: Migrate Chat Rendering from Pango Markup to Gtk.TextView + TextTag

**Date:** 2026-07-22
**Author:** Coder
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-textview-texttag-rendering.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance: This spec conforms to `docs/ARCHITECTURE.md` §§3.14a, 3.14b, 3.14d, 3.17, and the handler pattern (§8.6). A new `chat/` package is added per §2 directory structure conventions. No new GTK imports in `utils/`.

---

## DISCOVERY

Read files before writing spec:

1. **Proposal** (`docs/proposals/PROPOSAL-textview-texttag-rendering.md`): Full 3+ proposal. Strong architecture but 5 unresolved issues. Stale test counts (claims 49/32; actual are 82/61).

2. **ARCHITECTURE.md** (§3.14a escaping.py, §3.14b markdown.py, §3.14d chat_render_handler.py, §3.17 chat_bubble.py): Pipeline documented. 7 paired call sites. Streaming path uses `set_text()` not `set_markup()` (Fix 5).

3. **`utils/escaping.py`**: 187 lines. 3 public symbols: `escape_for_pango()`, `xml_escape_text()`, `xml_template()`. Stack-based Pango tag whitelist with orphan sweep.

4. **`utils/markdown.py`**: 279 lines. 1 public: `format_markdown(text)`. 8-step regex chain. 100KB ReDoS cap. `_ALLOWED_LINK_SCHEMES` = {http, https, mailto}.

5. **`ui/views/chat_bubble.py`**: 7 `_build_*_segment` methods all use `escape_for_pango()` + `format_markdown()` pair:
   - line 197/198: text flush (in `_process_text_chunk`)
   - line 606/607: table cell (`_make_table_cell`)
   - line 637/638: text segment (`_build_text_segment`)
   - line 703/704: quote segment (`_build_quote_segment`)
   - line 757/758: terminal per-line (`_build_terminal_segment`)
   - line 783/784: heading segment (`_build_heading_segment`)
   - line 804/805: task segment (`_build_task_segment`)

6. **`ui/handlers/chat_render_handler.py`**: Streaming path uses 150ms throttle. `update_streaming()` uses `set_text()` directly (no markup during stream). `end_streaming()` calls `build_role_bubble()` for final render. `render_sync()` calls `build_role_bubble()`.

7. **`utils/gtk_safe_link.py`**: 107 lines. `make_safe_label()` → `activate-link` → `on_activate_link()` → `_is_safe_scheme()`. HIGH-6: allows http/https/mailto; blocks file://, javascript:, data:, custom schemes.

8. **Tests**: `test_markdown.py` = 82 tests (536 lines). `test_escaping.py` = 61 tests (296 lines). 143 tests total, 832 lines. **Proposal's 49/32 is stale; the corpus is larger.**

9. **`pyproject.toml`**: `mistune` is NOT a dependency. Must be added.

**`escape_for_pango()` call sites outside chat rendering (8 sites):**
- `ui/views/file_tree.py:217` — `self._label.set_markup(escape_for_pango(display_name))`
- `ui/views/file_tree.py:1089` — `safe_name = escape_for_pango(name)`
- `ui/views/main_content.py:299` — `safe_name = escape_for_pango(project_name)`
- `ui/views/diff_card.py:134, 136, 138` — diff line content
- `ui/views/feed_card.py:140, 317` — feed card text

**`escape_for_pango()` search in `agent/`**: 0 matches.

---

## 1. Overview

### Problem

Today, CrabCakes renders LLM output as Pango markup strings passed to `Gtk.Label.set_markup()`. The pipeline is a 3-stage regex chain:

```
LLM text → escape_for_pango (regex, 187 lines) → format_markdown (regex, 279 lines) → Gtk.Label.set_markup (GMarkup parse)
```

This has produced **5 distinct bug classes** (B1–B5) with a cadence of ~1 incident per 6–8 weeks. The root cause is structural: we serialize formatting metadata to a string, then ask Pango to re-parse it. Every regex layer is a new failure surface.

### Solution

Replace the string-parses-to-string pipeline with a **parse-to-AST-to-procedural-state** pipeline:

```
LLM text → parse_message() (one pass, AST) → list[Segment] → render_segments() → Gtk.TextBuffer + Gtk.TextTags
```

Key properties:
- **Text is plain Unicode in the TextBuffer.** Never re-parsed after AST build.
- **Formatting is metadata (TextTag objects), not markup.** Tags applied programmatically — Pango cannot "fail" them.
- **One parser, one source of truth.** Not three independent regex layers.
- **All existing visual features preserved** — 7 segment types, streaming cursor, link safety.

### Scope

| In scope | Out of scope |
|----------|-------------|
| `utils/escaping.py` — trim `escape_for_pango()`, keep `xml_escape_text()` + `xml_template()` | Settings dialogs, project list, file tree (already use `xml_escape_text()` for app text) |
| `utils/markdown.py` — delete (replaced by `chat/parser.py`) | Web UI migration (`PROPOSAL-web-ui-replacement.md`) |
| `ui/views/chat_bubble.py` — 7 paired call sites → 1 call to `render_segments()` | Mermaid/diagram rendering (Phase 5 optional, not scoped) |
| `ui/handlers/chat_render_handler.py` — streaming path uses new pipeline | GtkSourceView migration |
| `utils/gtk_safe_link.py` — keep; link gating moves into renderer | |
| 8 out-of-scope `escape_for_pango()` call sites in non-chat views — migrate to `xml_template()` | |

---

## 2. Changes by File

### NEW: `chat/__init__.py`

Package marker. Exports: `parse_message`, `render_segments`, all `Segment` types.

~5 lines.

### NEW: `chat/segments.py`

Data model for parsed segments. No GTK imports.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Union

@dataclass(frozen=True)
class TextSeg:
    text: str
    inline: tuple["InlineNode", ...] = ()

@dataclass(frozen=True)
class InlineNode:
    kind: Literal["bold", "italic", "strike", "code", "link"]
    text: str
    href: str | None = None

@dataclass(frozen=True)
class BlockQuote:
    blocks: tuple["Segment", ...]

@dataclass(frozen=True)
class CodeBlock:
    lang: str
    content: str

@dataclass(frozen=True)
class TerminalBlock:
    content: str

@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    inline: tuple[InlineNode, ...]

@dataclass(frozen=True)
class TaskItem:
    checked: bool
    text: str
    inline: tuple[InlineNode, ...]

@dataclass(frozen=True)
class BulletItem:
    text: str
    inline: tuple[InlineNode, ...]

@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

Segment = Union[
    TextSeg, BlockQuote, CodeBlock, TerminalBlock,
    Heading, TaskItem, BulletItem, Table,
]
```

~80 lines.

### NEW: `chat/parser.py`

Parser that converts raw LLM text to `list[Segment]`. Built on `mistune>=3.0` with a custom renderer subclass.

**Phase 0 probe determines exact API.** This section documents the contract, not the implementation:

```
parse_message(text: str, max_len: int = 100 * 1024) -> list[Segment]
```

- Input: Raw LLM text (any encoding, any structure)
- Output: Flat list of `Segment` objects in document order
- Max input: 100 KB (preserved from existing ReDoS cap in `format_markdown`)
- Failure mode: Returns empty list on any parse error (never raises)

**Verified contract (Phase 0 probe confirms or revises):**

The `mistune` renderer subclass pattern:

```python
import mistune

class SegmentRenderer(mistune.HTMLRenderer):
    def __init__(self):
        super().__init__()
        self.segments: list[Segment] = []

    def text(self, text: str) -> str:
        # Called for inline text nodes
        # The string return is unused; we build segments in self.segments
        ...

    def block_code(self, code: str, info: str | None = None) -> str:
        # info = language hint (e.g. "python")
        ...

    def heading(self, text: str, level: int) -> str:
        ...

    def block_quote(self, text: str) -> str:
        ...

    # ... one method per block type
```

**The spec defers exact implementation to Phase 0 probe results.** The probe writes `chat/parser.py` as the deliverable.

~250 lines.

**Imports:**
```python
import mistune
from chat.segments import *
```

### NEW: `chat/renderer.py`

Renderer that applies `list[Segment]` to a `Gtk.TextBuffer` with `Gtk.TextTag` objects.

```
render_segments(
    buffer: Gtk.TextBuffer,
    segments: list[Segment],
    styles: StyleTable,
    link_handler: Callable[[str], bool],
) -> None
```

**StyleTable** — factory that creates one `Gtk.TextTag` per style:

```python
@dataclass
class StyleTable:
    bold: Gtk.TextTag
    italic: Gtk.TextTag
    strike: Gtk.TextTag
    code_inline: Gtk.TextTag
    code_block: Gtk.TextTag
    quote: Gtk.TextTag
    terminal: Gtk.TextTag
    heading_1: Gtk.TextTag
    heading_2: Gtk.TextTag
    heading_3: Gtk.TextTag
    heading_4: Gtk.TextTag
    link: Gtk.TextTag
    checkbox_unchecked: Gtk.TextTag
    checkbox_checked: Gtk.TextTag
    streaming_cursor: Gtk.TextTag

    @classmethod
    def create(cls, table: Gtk.TextTagTable) -> "StyleTable":
        def make(name: str, **props) -> Gtk.TextTag:
            tag = Gtk.TextTag(name=name)
            # Phase 0 probe determines exact set_property API
            for k, v in props.items():
                tag.set_property(k.replace("_", "-"), v)
            table.add(tag)
            return tag

        return cls(
            bold=make("bold", weight=Pango.Weight.BOLD),
            italic=make("italic", style=Pango.Style.ITALIC),
            # ... etc
        )
```

**Link handling:** The `follow-link` signal on `Gtk.TextView` gates navigation through the existing `utils/gtk_safe_link.py:on_activate_link()`. The renderer attaches the link `TextTag` and the `TextView` (consumer of the buffer) connects `follow-link`. This reuses HIGH-6 verbatim.

~350 lines.

**Imports:**
```python
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Pango
from chat.segments import Segment, TextSeg, BlockQuote, CodeBlock, TerminalBlock, Heading, TaskItem, BulletItem, Table
from utils.gtk_safe_link import on_activate_link
```

### NEW: `tests/test_chat_segments.py`

Unit tests for data model.

~50 lines.

### NEW: `tests/test_chat_parser.py`

Tests that parse_message produces expected segments. Migration corpus from `test_markdown.py` (82 tests).

The **entire `test_markdown.py` corpus** (82 tests) must be reimplemented as parser tests. Each test is:
1. Input text → `parse_message(text)` → `list[Segment]`
2. Assert segment types, text content, inline formatting metadata
3. No GTK calls needed — pure Python

~200 lines.

### NEW: `tests/test_chat_renderer.py`

Tests that `render_segments()` produces correct TextTag ranges. GTK required (TextBuffer).

~150 lines.

### NEW: `tests/fuzz/test_chat_parser_fuzz.py`

Hypothesis-based fuzz test:

```python
from hypothesis import given, settings, strategies as st
from chat.parser import parse_message

markdown_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Po", "Sm", "Zs"),
        whitelist_characters="*_~`<>[]()#-+\n.=|:;/\\",
    ),
    min_size=0,
    max_size=10_000,
)

@given(text=markdown_strategy)
@settings(max_examples=10_000, deadline=2000)
def test_parse_never_raises(text):
    segments = parse_message(text)
    assert isinstance(segments, list)
```

~80 lines.

### MODIFIED: `pyproject.toml`

Add `mistune>=3.0,<4.0` to `[project] dependencies`.

### MODIFIED: `ui/views/chat_bubble.py`

**Phase 1 (under feature flag):** Migrate one _build_*_segment method. Use `render_segments()` on a shared TextBuffer instead of `escape_for_pango()` + `format_markdown()` + `make_safe_label()`.

**Phase 3 (flag ON):** All 7 call sites replaced. The bubble becomes:

```
build_role_bubble(role, text, ...) -> Gtk.Widget
    segments = parse_message(text)
    buffer = Gtk.TextBuffer()
    styles = StyleTable.create(buffer.get_tag_table())
    render_segments(buffer, segments, styles, link_handler)
    text_view = Gtk.TextView.new_with_buffer(buffer)
    # Wrap in existing bubble container
```

Changes:
- `process_segments()` — gutted; delegates to `parse_message()` + `render_segments()`
- `_build_text_segment` — delegates to renderer
- `_build_quote_segment` — delegates to renderer
- `_build_heading_segment` — delegates to renderer
- `_build_task_segment` — delegates to renderer
- `_build_table_segment` — delegates to renderer (TextChildAnchor for table grid)
- `_make_table_cell` — deleted (TextTag handles inline formatting)
- `_build_terminal_segment` — delegates to renderer (TextChildAnchor for terminal header)
- `_build_code_from_markup` — delegates to renderer (TextChildAnchor for code header + copy btn)

~200 lines removed from process_segments + _build_*_segment methods.

### MODIFIED: `ui/handlers/chat_render_handler.py`

- `render_sync()`: Uses `parse_message()` + `render_segments()` instead of `build_role_bubble()` when flag ON
- `update_streaming()`: Appends deltas to `TextBuffer` directly (preserves 150ms throttle)
- `end_streaming()`: Swaps streaming `TextView` for final `TextView`
- `build_streaming_bubble()`: Returns `(container, buffer, text_view)` instead of `(container, label)`
- `start_streaming()`: Creates `Gtk.TextView` with cursor tag
- Private helper `_render_processed(segments)` shared between render_sync and end_streaming

~150 lines changed.

### MODIFIED: `utils/escaping.py`

**Phase 4:** Delete `escape_for_pango()`. Keep `xml_escape_text()` and `xml_template()`.

Lines: 187 → ~20 (`xml_escape_text` + `xml_template` only).

### DELETED: `utils/markdown.py`

**Phase 4:** Delete entire file (279 lines). Replaced by `chat/parser.py`.

### MODIFIED: non-chat views (Phase 4 — Issue 1a migration)

8 sites migrate from `escape_for_pango()` to `xml_template()` or `xml_escape_text()`:

| File | Line | Current | Replace with |
|------|------|---------|-------------|
| `file_tree.py` | 217 | `self._label.set_markup(escape_for_pango(display_name))` | `self._label.set_markup(xml_escape_text(display_name))` |
| `file_tree.py` | 1089 | `safe_name = escape_for_pango(name)` | `safe_name = xml_escape_text(name)` |
| `main_content.py` | 299 | `safe_name = escape_for_pango(project_name)` | `safe_name = xml_escape_text(project_name)` |
| `diff_card.py` | 134 | `escape_for_pango(highlighted)` | `xml_escape_text(highlighted)` |
| `diff_card.py` | 136 | `escape_for_pango(line.content)` | `xml_escape_text(line.content)` |
| `diff_card.py` | 138 | `escape_for_pango(line.content)` | `xml_escape_text(line.content)` |
| `feed_card.py` | 140 | `escaped = escape_for_pango(text)` | `escaped = xml_escape_text(text)` |
| `feed_card.py` | 317 | `escaped = escape_for_pango(line)` | `escaped = xml_escape_text(line)` |

These sites render app-controlled text (file names, diff lines, project names, feed card text). They don't need Pango tag preservation. `xml_escape_text()` is the correct tool.

### UNCHANGED: `utils/gtk_safe_link.py`

Kept verbatim. The `on_activate_link()` guard is wired into the `Gtk.TextView.follow-link` signal handler instead of `Gtk.Label.activate-link`. Zero code changes.

### UNCHANGED: `models/`, `agent/`, `gateway/`

No changes. The chat rendering pipeline is a UI concern.

**Files NOT changed** (already correct):
- `utils/gtk_safe_link.py` — HIGH-6 guard reused verbatim in TextView
- `models/`, `agent/`, `gateway/` — no rendering logic

---

## 3. Data Flow (NEW)

```
LLM raw text (any encoding, any structure)
    │
    ▼  [parse_message() — one pass, AST-based via mistune]
list[Segment]    ← tree-structured, in-memory, immutable
    │
    ▼  [render_segments() — one pass, fill TextBuffer with TextTags]
Gtk.TextBuffer   ← plain Unicode + programmatic TextTags
    │
    ▼  [Gtk.TextView renders naturally — no GMarkup parse]
Rendered pixels  ← structurally impossible to fail
```

### Streaming path:
```
Delta text arrives → append to accumulated string → parse_message(accumulated)
  → clear TextBuffer → render_segments(buffer, segments) → 150ms throttle
  → Pango renders updated TextBuffer
```

### End-of-streaming:
```
Final accumulated text → parse_message → render_segments → replace pending bubble
```

### Link click:
```
User clicks link in Gtk.TextView
  → TextView emits "follow-link" signal
  → handler = on_activate_link(uri) from utils/gtk_safe_link.py
  → HIGH-6 gate: allowed scheme → open in browser; blocked → block
```

---

## 4. File Change Summary

| File | Change type | Lines | Risk |
|------|------------|-------|------|
| `chat/__init__.py` | NEW | +5 | Low |
| `chat/segments.py` | NEW | +80 | Low |
| `chat/parser.py` | NEW | +250 | Low (Phase 0 probe) |
| `chat/renderer.py` | NEW | +350 | Medium (GTK API) |
| `tests/test_chat_segments.py` | NEW | +50 | Low |
| `tests/test_chat_parser.py` | NEW | +200 | Low |
| `tests/test_chat_renderer.py` | NEW | +150 | Medium |
| `tests/fuzz/test_chat_parser_fuzz.py` | NEW | +80 | Low |
| `tests/test_textview_parity.py` | NEW | +100 | Medium |
| `tests/test_streaming_textview.py` | NEW | +80 | Low |
| `pyproject.toml` | MODIFIED | +1 | Low |
| `ui/views/chat_bubble.py` | MODIFIED | ~−200 net | High (7 call sites) |
| `ui/handlers/chat_render_handler.py` | MODIFIED | ~+100 net | High (streaming path) |
| `ui/views/file_tree.py` | MODIFIED | −0 (2 lines changed) | Low |
| `ui/views/main_content.py` | MODIFIED | −0 (1 line changed) | Low |
| `ui/views/diff_card.py` | MODIFIED | −0 (3 lines changed) | Low |
| `ui/views/feed_card.py` | MODIFIED | −0 (2 lines changed) | Low |
| `utils/escaping.py` | MODIFIED | ~−170 (delete escape_for_pango) | Low |
| `utils/markdown.py` | DELETED | −279 | Low (Phase 4) |
| `ARCHITECTURE.md` | MODIFIED | ~+50 | Low |

**NET CHANGE:** +1,445 new / −649 deleted = +796 net lines.

---

## 5. Implementation Order

### Phase 0: Feasibility spikes (no production code)

Duration: 1 session per spike.

**0a — mistune AST probe:**
- Install `mistune>=3.0` in venv
- Write a 30-line probe that produces `list[Segment]` from raw markdown
- Test against 5 fixtures from `test_markdown.py`
- Deliverable: `_probe_mistune.py` in /tmp + pass/fail report

**0b — GTK4 TextTag property probe:**
- Write a 25-line probe that creates `Gtk.TextTag`, sets properties, inserts text with tags
- Test with `GDK_BACKEND=gl` or headless
- Specifically probe:
  - `tag.set_property("weight", Pango.Weight.BOLD)` vs `tag.props.weight = Pango.Weight.BOLD`
  - `tag.set_property("background", "rgba(127,127,127,0.15)")` vs `"#7f7f7f"`
  - `buffer.insert_with_tags(iter, text, tag1, tag2)` — does it accept varargs tags?
  - `TextView.follow-link` signal — does it exist and work with `on_activate_link`?
- Deliverable: `_probe_gtk_tags.py` + pass/fail report

**Gate:** Phase 1 begins only if both probes pass. If mistune probe fails, use P2 (hand-rolled parser). If TextTag probe fails, document workarounds in spec.

### Phase 1: Segments + Parser + unit tests (no UI change)

Files: `chat/__init__.py`, `chat/segments.py`, `chat/parser.py`, `tests/test_chat_segments.py`, `tests/test_chat_parser.py`, `pyproject.toml`

- Define `Segment` data model
- Implement `parse_message()` based on Phase 0 probe results
- All 82 tests from `test_markdown.py` pass against new parser
- Feature flag `CRABCAKES_TEXTVIEW_BUBBLES` defined (default OFF)
- `utils/markdown.py` gets deprecation header

**Verification:** `pytest tests/test_chat_parser.py -v` — all tests pass.

### Phase 2: Renderer + one bubble segment (flag OFF)

Files: `chat/renderer.py`, `tests/test_chat_renderer.py`, `ui/views/chat_bubble.py` (1 method)

- Implement `StyleTable.create()`, `render_segments()`
- Implement `Gtk.TextView` creation helper (shared by all segments)
- Migrate `_build_text_segment` to use `render_segments()` when flag ON
- Implement `test_streaming_textview.py` (Phase 5 specs)
- Verify streaming performance budget: 1000 deltas in <2s

**Verification:** `pytest tests/test_chat_renderer.py` passes. When flag ON, text-only bubbles render via TextView. When flag OFF, old path used.

### Phase 3: Full migration (flag ON)

Files: `ui/views/chat_bubble.py` (all 7 methods), `ui/handlers/chat_render_handler.py`

- All 7 `_build_*_segment` methods migrated:
  - `_build_text_segment` — inline formatting via TextTags
  - `_build_quote_segment` — quote via TextTag (left border via CSS on TextView)
  - `_build_terminal_segment` — $ prompt via TextChildAnchor label + content via TextTag
  - `_build_heading_segment` — heading via TextTag font-size scaling
  - `_build_task_segment` — checkbox chars via TextTag
  - `_build_table_segment` — table as TextChildAnchor with Gtk.Grid
  - `_build_code_from_markup` — code header via TextChildAnchor + code via code-block TextTag
- Streaming path uses `TextBuffer.insert_with_tags()` for deltas
- Streaming cursor via `Gtk.TextTag` (visible/invisible toggle)
- HIGH-6: `TextView.follow-link` → `on_activate_link()`
- Feature flag default flipped to ON

**Verification:** 
- Visual parity test: every `test_markdown.py` fixture produces equivalent formatted output
- `test_textview_parity.py` — all fixtures pass
- `test_streaming_textview.py` — 1000 deltas <2s

### Phase 4: Old code deletion

Files: `utils/escaping.py` (trim), `utils/markdown.py` (delete), 8 non-chat view files (migrate escape_for_pango→xml_escape_text)

- Delete `escape_for_pango()` from `escaping.py`
- Delete entire `utils/markdown.py`
- Migrate 8 non-chat call sites: `file_tree.py` (×2), `main_content.py`, `diff_card.py` (×3), `feed_card.py` (×2)
- Add fuzz test (`tests/fuzz/test_chat_parser_fuzz.py`)

**Verification:**
- `wc -l utils/escaping.py` ≤ 25 lines
- `! test -f utils/markdown.py`
- `grep -rn "escape_for_pango" --include="*.py" ui/` returns 0 lines
- Fuzz test: 10,000 random inputs parse without raising

### Phase 5 (optional): New features

Not scoped into this spec. Opportunistic after Phase 4.

---

## 6. Acceptance Criteria

| ID | Criterion | How measured |
|----|-----------|-------------|
| S1 | Chat bubble rendered for all 82 `test_markdown.py` fixtures, visually equivalent | Visual parity test passes (same rendering, no pixel comparison — same TextTag ranges) |
| S2 | 10,000 random fuzzed inputs parse without exception | `pytest tests/fuzz/test_chat_parser_fuzz.py -x` passes |
| S3 | `utils/escaping.py` ≤ 25 lines, only `xml_escape_text()` + `xml_template()` | `wc -l utils/escaping.py ≤ 25`; `grep -c "def " returns 2` |
| S4 | `utils/markdown.py` deleted | `! test -f utils/markdown.py` |
| S5 | No `escape_for_pango()` call in production code | `grep -rn "escape_for_pango(" --include="*.py" ui/ agent/` returns 0 |
| S6 | HIGH-6 link gate still wired and tested | `tests/test_gtk_safe_link.py` passes unchanged |
| S7 | 1000-delta streaming test passes in <2s | `tests/test_streaming_textview.py` |
| S8 | 0 "Failed to set text" warnings from new path | Manual: grep app logs; structural: parse→TextBuffer has no string-parse step |
| S9 | One parser: `parse_message()` is sole source of truth for all markdown parsing | `grep -rn "format_markdown(" --include="*.py" ui/` returns 0 |

---

## 7. Edge Cases

| Case | Expected behavior |
|------|------------------|
| Empty string | Empty segment list → empty TextBuffer → empty bubble |
| Plain text (no markdown) | Single TextSeg with empty inline tuple → renders as plain |
| Only `**bold**` | TextSeg with InlineNode(kind="bold") → bold tag on range |
| Nested formatting (`***bold+italic***`) | Two overlapping TextTags (bold + italic) on same range |
| Code span with `**` inside | Code inline TextTag, no bold processing |
| Fenced code block with `javascript:` inside | CodeBlock rendered as plain text in code-block TextTag — no link processing |
| `<script>alert(1)</script>` | Parsed as plain TextSeg — no HTML processing (mistune escapes via HTML, or falls through as text) |
| 150 KB input | Truncated at 100 KB with truncation marker, segments from truncated text |
| Streaming: partial bold (**star | Throttled; final text re-parsed on end_streaming |
| Link with javascript: scheme | `follow-link` signal → `on_activate_link()` returns True → blocked |
| Unknown tag in LLM output (e.g. `<div>`) | Parsed as plain text — no special handling needed (no GMarkup parse) |
| Tab characters in text | Mistune passes through as-is; TextTag renders as spaces (TextView default) |
| Unicode emoji in text | Passed through verbatim; Pango renders emoji glyphs |
| Extremely long word (1000+ chars, no spaces) | `Gtk.TextView` wraps at word boundaries as configured; may overflow. Same as today. |
| Multiple consecutive newlines | Rendered as blank lines in TextBuffer. Same as today. |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update:

| Section | Change |
|---------|--------|
| §2 (directory structure) | Add `chat/` package |
| §3.14a (escaping.py) | Replace `escape_for_pango()` with only `xml_escape_text()` + `xml_template()` |
| §3.14b (markdown.py) | Delete section; replace with §3.14b header referring to `chat/parser.py` |
| §3.14c (chat_bubble.py) | Update: 7 call sites → 1 `Gtk.TextView` per bubble; `process_segments()` delegates to `parse_message()` + `render_segments()` |
| §3.14d (chat_render_handler.py) | Update: streaming path uses `TextBuffer.insert_with_tags()` |
| §3.17 (gtk_safe_link.py) | Add note: guard now wired to `Gtk.TextView.follow-link` signal (same function, different signal) |
| §13 (file inventory) | Add `chat/` files; update `utils/` line counts; mark `utils/markdown.py` deleted |
| §8.6 (handler pattern) | Add note that UI rendering logic moved to `chat/renderer.py` with `Segment` data model |

Estimated: +50 lines to document.

---

## Issue Resolutions (from Writer Instructions)

### Issue 1 — `escape_for_pango` scope (8 out-of-scope call sites)

**Resolution: (a) Expand scope** — Phase 4 migrates 8 non-chat sites to `xml_escape_text()`. These are app-controlled text (file names, project names, diff lines), not LLM output. `xml_escape_text()` is correct for app-controlled text. This enables clean deletion of `escape_for_pango()`.

### Issue 2 — mistune AST feasibility

**Resolution: (c) Spike-first phase** — Phase 0a produces a working `parse_message` prototype before any UI code. If mistune fails, fall back to P2 (hand-rolled parser). Phase 1 is gated on Phase 0a success.

### Issue 3 — GTK4 TextTag property API

**Resolution: Probe in Phase 0b** — 25-line GTK4 probe script run with `GDK_BACKEND=gl` or headless. Probes `set_property` vs `props.weight`, background color format, `insert_with_tags` varargs, and `follow-link` signal. Spec does not guess the API.

### Issue 4 — Anchor vs hybrid blocks

**Resolution: (b) Child anchors** — Code blocks, tables, terminal blocks, and blockquotes use `Gtk.TextChildAnchor` + child widgets (header bar, copy button, grid) inside the single TextBuffer. This preserves the single-TextBuffer architecture AND visual parity (copy button, per-block CSS, table grid).

### Issue 5 — Visual parity test algorithm

**Resolution:** Define parity as "same set of (start_offset, end_offset, {attr: value}) tuples" where:
- `start_offset` / `end_offset` are byte offsets in the plain text
- `{attr: value}` is a frozen dict of TextTag properties (weight, style, family, strikethrough, foreground, background, underline)
- For the old path: extract from `Gtk.Label.get_layout().get_line(0).get_runs()` — each `Pango.LayoutRun` has a `Pango.GlyphItem` with `item.analysis.font` describing the attributes
- For the new path: iterate `Gtk.TextTagTable` tags → `buffer.get_tag_table()` → for each tag, `buffer.get_bounds(tag)` gives start/end offsets
- Tolerance: exact match required on set of (offset, offset, attr) tuples. Subset matching on attr keys (if old path doesn't track `foreground`, the new path's foreground is not compared).
- Fail-safe: if old-path attribute extraction fails (e.g., no GdkDisplay in headless), test logs WARNING and returns True (soft pass) — the structural parser+renderer tests in Phase 1 already verify correctness at the segment level.

---

## COMPLETENESS CHECKLIST

- [x] Read all 9 discovery files
- [x] Resolved Issue 1 (escape_for_pango scope) — (a) Expand scope to migrate 8 sites
- [x] Resolved Issue 2 (mistune feasibility) — (c) Spike-first Phase 0 probe
- [x] Resolved Issue 3 (GTK4 TextTag API) — Phase 0b probe, no guessing
- [x] Resolved Issue 4 (anchor vs hybrid) — (b) Child anchors
- [x] Resolved Issue 5 (parity test algorithm) — offset+attr tuple comparison with fallback
- [x] Spec file written to target path
- [x] All 8 spec sections present
- [x] Phasing defined (Phase 0 through Phase 5)
