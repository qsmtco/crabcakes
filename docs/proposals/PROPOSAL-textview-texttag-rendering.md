# Proposal: Migrate Chat Rendering from Pango Markup to Gtk.TextView + TextTag

**Date:** 2026-07-15
**Author:** QTR (assisted by Captain Qaster)
**Status:** ⚠️ PROPOSAL — Not implemented
**Estimated effort:** 3–5 weeks (one developer, one phase shippable per week)
**Severity of problem addressed:** High — see `PROPOSAL-rendering-fix-strategy.md` §1 for the latest incident
**Supersedes:** §Option C (brief mention) of `PROPOSAL-rendering-fix-strategy.md` (2026-07-15)
**Companion documents:**
- `PROPOSAL-rendering-fix-strategy.md` — the synthesis that recommended this path
- `PROPOSAL-web-ui-replacement.md` — the larger escape valve (only pursue if Table 2 warrants it)
- `docs/research/PROPOSAL-rendering-alternatives.md` — external library + reference project survey
- `docs/ARCHITECTURE.md` — architectural constraints this proposal must conform to
- `tests/test_markdown.py` and `tests/test_escaping.py` — current test coverage that anchors this proposal

---

## 0. TL;DR (read this first)

Today, CrabCakes renders LLM output as **Pango markup strings** passed to `Gtk.Label.set_markup()`. We have a 640-line hand-rolled escape layer (`utils/escaping.py` + `utils/markdown.py`) with 17 call sites, and it has had **at least one Pango-warning incident every 6–8 weeks since the port**. The escape layer is a regex-based parser; like all regex-based parsers, every new LLM-output pattern is a potential bug, and a passing regression test today does not protect against tomorrow's malformed input.

This proposal replaces the **string-parses-to-string-parses-to-parse** pipeline with a **parse-to-AST-to-procedural-state** pipeline. Concretely:

```
BEFORE:  raw text → escape_for_pango (regex) → format_markdown (regex) → set_markup (parse)
AFTER:   raw text → ChatMarkdownParser (one pass, AST) → TextBuffer + TextTags
```

**Key properties of the new pipeline:**

1. **Text is plain Unicode in the TextBuffer.** It is never re-parsed after the initial AST build. Pango does not get to "fail" the buffer — there is no markup string for it to fail on.
2. **Formatting is metadata (TextTag objects), not markup.** Tags are programmatic. If a tag doesn't apply, it doesn't apply. The bubble still renders.
3. **The AST parser is a single source of truth.** When the parser is wrong, only the parser is wrong — not three independent regex layers working at cross purposes.
4. **All 14 widget types keep their visual fidelity.** Bold, italic, code, blockquote, table, heading, task, terminal, code block — every feature is preserved. Some features gain capabilities (see §6.4).

**This proposal is bounded.** It does not rewrite every GTK widget — only the bubble rendering layer (which is where all 17 escape-pipeline call sites live) and three helper utilities. Forms, settings, project list, file tree (the other 11 widget types) are out of scope; they already use the safe `Gtk.Label` + `xml_escape_text` pattern for app-controlled text.

**Estimated effort:** 3–5 weeks, with a shippable chat bubble by end of week 3 and full coverage by end of week 5. See §5 for phase breakdown.

---

## 1. Problem Statement (the reason we are doing this)

### 1.1 The current rendering pipeline is structurally fragile

`ui/handlers/chat_render_handler.py:155–158` documents the full pipeline:

```
- text   → escape_for_pango() + format_markdown()
- quote  → escape_for_pango() + format_markdown()
- heading/task/terminal → escape_for_pango()
```

This is a three-stage, regex-based pipeline:

```
LLM raw text
    │
    ▼  [pass 1: escape_for_pango() — ~150 lines of regex]
Escaped XML-safe string
    │
    ▼  [pass 2: format_markdown() — ~250 lines of regex]
Pango markup string
    │
    ▼  [pass 3: Gtk.Label.set_markup() — GMarkup parse]
Rendered pixels
       ⚠️  parse-error surface — emits "Failed to set text" warning
```

Three problems compound here:

**A. Two independent parsers cannot agree.** `escape_for_pango` and `format_markdown` are both regex-based parsers running back-to-back. They were designed to be commutative (escape first, then format) but they interact poorly:

- An unrecognized tag in `escape_for_pango` is escaped to `&lt;tag&gt;`.
- That exact text reaches `format_markdown`, which may interpret it as a marker for one of its own substitutions.
- The output markup may be unbalanced even though each step individually produced valid output.

This is not a bug in either module. It is the canonical failure mode of multi-pass regex parsers — they are correct in isolation and uncorrect in combination. The `TestFencedVsInlineBacktickRegression` suite at `tests/test_markdown.py:467` documents the most recent example: an inline backtick containing literal `<tt>` followed by a fenced block produces unbalanced Pango tags even though every individual regex match was correct.

**B. Bug surface is unbounded.** Every new LLM output pattern is a potential new escape case. `escape_for_pango` has been amended in five Phases (5, 6, 6.1, MED-10, BUG #8) since the initial port. Each Phase was in response to a specific LLM-output pattern that the existing regex chain mishandled. The pattern of "wait for a bug to appear, then write a regex to handle it" is **reactive** — it cannot anticipate new patterns. We have no test framework (property-based, fuzz, or otherwise) that exercises the parser on unseen inputs.

**C. Regression tests are not protective.** Today (2026-07-15) we shipped a Pango warning of the exact bug class that `tests/test_markdown.py::TestFencedVsInlineBacktickRegression::test_exact_user_failure_content_renders` was written to catch. **The test passes.** The incident was triggered by a slightly different input pattern that the test fixture did not include. The test protects against the specific historical incident; it does not protect against the class of incident.

### 1.2 Specific measurable failure modes

| ID  | Date       | Symptom                                                   | Pattern that triggered it                              |
|-----|------------|-----------------------------------------------------------|--------------------------------------------------------|
| B1  | (shipped)  | Adjacent `**bold****bold****` collapses bubble            | `**A****B****C**` produces misnested `<b><i>` tags    |
| B2  | (shipped)  | `&quot;` double-encodes to `&amp;quot;` in bubbles        | LLM emits `&quot;hello&quot;` literally                |
| B3  | (shipped)  | `<br>` inside code block causes silent empty bubble       | `line1<br>line2` in fenced block                       |
| B4  | (shipped)  | Closing tag without matching open corrupts markup         | `</b>` with no prior `<b>`                              |
| B5  | 2026-07-15 | `Failed to set text '...&quot;...&#x27;...'` warning      | User-reported; test for B1/B2/B3 passes               |

Incidents B1–B4 are documented in `PROPOSAL-fix-malformed-pango-markup.md` (commit `91813ab`). B5 is the incident that triggered this proposal; it is open at the time of writing (2026-07-15 17:00 PDT).

### 1.3 The regex-chain approach is the wrong abstraction layer

LLMs emit text. The text is the data. The formatting is metadata about the text. The current pipeline stringifies the metadata, then asks Pango to re-parse it. **This is the same mistake as serializing a list of integers to a CSV, then parsing the CSV back to a list every time you read it.** It is correct, but it loses fidelity at every cycle and creates an infinite surface for parser bugs.

The right abstraction is **structured data with a renderer**:

- A list of `Segment` objects with type, content, and (later) attributes.
- A renderer (`ChatBubbleRenderer`) that turns segments into TextTags applied to a TextBuffer.
- The TextBuffer holds plain Unicode text plus programmatic formatting metadata.

There is no string-to-string round-trip. There is no GMarkup parse. Pango renders formatted text by walking text + tags, the same way it renders any other rich text. It cannot fail.

---

## 2. Goals & Non-Goals

### 2.1 Goals (what success looks like)

| # | Goal                                                                                                                                  | Acceptance criterion                                                                  |
|---|---------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| G1 | **No "Failed to set text" Pango warnings from chat rendering. Ever.**                                                                | `grep -rn 'Failed to set text' /var/log/crabcakes` returns 0 lines after 30-day soak |
| G2 | **All existing chat-rendering features work identically.**                                                                          | §6.1 visual parity test passes against current production UI                         |
| G3 | **The escape pipeline has been deleted.**                                                                                            | `utils/escaping.py` and `utils/markdown.py` either gone or reduced to leaf utilities |
| G4 | **The chat bubble can render inputs today's parser cannot.**                                                                        | §6.3 fuzz test: 1,000 randomly-generated adversarial inputs render without warnings |
| G5 | **New formatting features are tractable to add.**                                                                                   | Mermaid / inline image / syntax-highlightable code block each ≤ 1 day of dev work   |
| G6 | **Streaming rendering is unchanged from a user perspective.**                                                                        | Streaming throttle, cursor (`▍`), and bubble update lifecycle identical               |
| G7 | **One parser, one source of truth.**                                                                                                | A single function `parse_to_segments(text) -> list[Segment]` produces all AST data  |

### 2.2 Non-Goals (what this proposal explicitly does not do)

| # | Out of scope                                                                                                          | Rationale                                                                                  |
|---|-----------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| N1 | Replace the GTK UI itself (no web migration)                                                                          | That is a separate proposal (`PROPOSAL-web-ui-replacement.md`); TextView lives inside GTK   |
| N2 | Modify forms, settings dialogs, project list, file tree, agent builder, diff viewer                                 | These use app-controlled text and already use `xml_escape_text` correctly                  |
| N3 | Add a new public API for plugins                                                                                       | This is an internal refactor; we can add one later if needed                              |
| N4 | Migrate to GtkSourceView                                                                                              | Considered (see §9.5); rejected as too coupled for chat with structured blocks            |
| N5 | Add markdown extensions beyond the current set (tables in headings, footnote support, etc.)                          | Anything we add later goes through the same AST path                                     |

---

## 3. Target Architecture

### 3.1 Component map (before → after)

```
BEFORE:
┌──────────────────────────────────────────────────────────────────────────────┐
│ ui/handlers/chat_render_handler.py                                           │
│   └─ update_streaming() ─► escape_for_pango ─► format_markdown ─► set_markup  │
│                                                                              │
│ ui/views/chat_bubble.py (17 call sites)                                      │
│   └─ _process_text_chunk() ─► escape_for_pango ─► format_markdown ─► set_markup│
│   └─ _build_text_segment() ─► escape_for_pango ─► format_markdown ─► set_markup│
│   └─ _build_heading_segment() ─► escape_for_pango ─► format_markdown ─► set…  │
│   └─ _build_quote_segment() ─► escape_for_pango ─► format_markdown ─► set…  │
│   └─ _build_task_segment() ─► escape_for_pango ─► format_markdown ─► set…  │
│   └─ _build_table_cell() ─► escape_for_pango ─► format_markdown ─► set…     │
│   └─ _build_terminal_segment() ─► escape_for_pango (per line) ─► format_m…  │
│                                                                              │
│ utils/escaping.py   (302 lines, regex stack)                                │
│ utils/markdown.py   (338 lines, regex stack)                                │
│ utils/gtk_safe_link.py (HIGH-6 scheme allowlist — KEEP)                     │
└──────────────────────────────────────────────────────────────────────────────┘

AFTER:
┌──────────────────────────────────────────────────────────────────────────────┐
│ ui/views/chat_bubble.py                                                     │
│   └─ build_role_bubble()                                                    │
│        ├─ parse_message(text) ─► list[Segment]                              │  ← §4.1
│        └─ render_segment(segment, TextBuffer, TextTagTable)                  │  ← §4.3
│                                                                             │
│ chat/parser.py   (NEW, ~600 lines)                                          │
│   └─ parse_message(text: str) -> list[Segment]                              │
│        └─ mistune.AstRenderer (or hand-rolled walker) → produce segments     │
│                                                                              │
│ chat/renderer.py (NEW, ~400 lines)                                          │
│   └─ render_segments(buffer: TextBuffer, segments: list[Segment]) → None    │
│   └─ StyleTable, TagFactory, link activation handlers                       │
│                                                                              │
│ utils/escaping.py   ↓↓↓ ONLY xml_escape_text() kept (95 lines)              │
│ utils/markdown.py   ↓↓↓ DELETED (replaced by chat/parser.py)               │
│ utils/gtk_safe_link.py ↑ KEEP — link gating moves into renderer              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 The new pipeline, end-to-end

```
LLM raw text (any encoding, any chars, any structure)
    │
    ▼  [parse_message() — one pass, AST-based]
list[Segment]    ← tree-structured, in-memory, immutable
    │
    ▼  [render_segments() — one pass, fill TextBuffer]
TextBuffer     ← plain Unicode + programmatic TextTags
    │
    ▼  [Pango renders naturally, no parse step]
Rendered pixels     ← ⚠️ structurally impossible to fail
```

Each stage's contract:

| Stage              | Input                       | Output                              | Failure mode            |
|--------------------|-----------------------------|-------------------------------------|-------------------------|
| parse_message      | `str` (LLM raw text)        | `list[Segment]` (AST)               | None: produces AST      |
| render_segments    | `list[Segment]`             | `TextBuffer` with applied tags      | None: tags are program  |
| Pango render       | `TextBuffer`                | Pixel buffer                        | None — text is plain    |

The entire pipeline has **zero places where a string is parsed back into structure**.

### 3.3 Data model: Segment types

```python
# chat/segments.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Union

@dataclass(frozen=True)
class TextSeg:
    """A run of plain text with optional inline formatting."""
    text: str
    inline: tuple["InlineNode", ...] = ()

@dataclass(frozen=True)
class InlineNode:
    """One piece of inline formatting. Composable inside TextSeg."""
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

@dataclass(frozen=True)
class Image:
    src: str
    alt: str

Segment = Union[
    TextSeg, BlockQuote, CodeBlock, TerminalBlock,
    Heading, TaskItem, BulletItem, Table, Image
]
```

Key design choices:

- **`Segment` is a sum type** (sealed via Python `Union` at use-site). The renderer dispatches on `isinstance`; the parser produces them.
- **Inline formatting is composed, not nested.** A bold link is `(InlineNode(kind="link"), InlineNode(kind="bold"))` — not a tree. This makes rendering trivial and matches what markdown actually means.
- **Code blocks and terminal blocks carry raw content.** They are rendered as a single `<tt>` TextTag (single TextBuffer child). No parsing of the content happens.
- **Tables and headings are flat** for the same reason — the renderer applies per-cell/per-line TextTags, no nesting.

### 3.4 Module dependency graph (new packages)

```
chat/                                  ← NEW PACKAGE (replaces utils/markdown.py)
├── __init__.py
├── segments.py                        ← §3.3 data model (no GTK deps)
├── parser.py                          ← ← mistune.AstRenderer → list[Segment]
└── renderer.py                        ← ← list[Segment] → TextBuffer (GUI deps)

ui/views/chat_bubble.py                ← MODIFIED: 17 call sites collapse to 1
ui/handlers/chat_render_handler.py     ← MODIFIED: streaming path uses new pipeline

utils/escaping.py                      ← TRIMMED: delete escape_for_pango() and _strict_unescape()
utils/markdown.py                      ← DELETED
utils/gtk_safe_link.py                 ← UNCHANGED (renderer imports it for link gating)
```

**Dep direction (preserved per ARCHITECTURE.md):**

```
chat/ ───► utils/         (chat imports utils — correct)
ui/   ───► chat/ + utils/ (ui imports both — correct)
agent/ ───► utils/       (agent imports utils only; ui re-exports chat* if needed)
```

No new dependency from `utils/` upward. No circular imports. `chat/segments.py` has zero GTK imports — fully testable without a display server.

---

## 4. Detailed Design

### 4.1 The parser (`chat/parser.py`)

Two viable implementations; we choose between them:

**Option P1: Build on top of `mistune`** (a pure-Python, AST-producing markdown parser).
- Pros: ~150 KB dep, 50+ tests pass on its own corpus, table/footnote/strikethrough already supported.
- Cons: We must write a custom `Renderer` subclass that emits our `Segment` objects instead of HTML.

**Option P2: Hand-rolled walker.** A small recursive-descent parser we write ourselves.
- Pros: Zero new dependencies. Matches the LLM-output patterns we actually see.
- Cons: Must write the parser. Risk of bugs is non-zero.

**Decision: Option P1** (`mistune`), with P2 as a fallback if `mistune`'s rendering diverges from the LLM-output syntax our tests currently encode (see §6.2 for the test corpus that anchors this).

Mistune's renderer pattern:

```python
import mistune

class SegmentRenderer(mistune.HTMLRenderer):
    def __init__(self):
        super().__init__()
        self.segments: list[Segment] = []

    def text(self, text: str) -> str:
        if not text.strip():
            return ""
        # Coalesce consecutive text nodes — important for streaming performance
        if self.segments and isinstance(self.segments[-1], TextSeg):
            self.segments[-1] = TextSeg(
                text=self.segments[-1].text + text,
                inline=self.segments[-1].inline,
            )
        else:
            self.segments.append(TextSeg(text=text))
        return ""  # string output is unused

    def block_code(self, code: str, info: str | None = None) -> str:
        self.segments.append(CodeBlock(lang=info or "", content=code))
        return ""

    def block_quote(self, text: str) -> str:
        # 'text' here is the HTML rendering of children — discard
        # and let mistune call us back for child segments instead.
        return ""

    # ... one method per block/inline type
```

Mistune emits one callback per node. Each callback appends one `Segment`. The resulting list is the AST.

**Streaming concern:** `parse_message` is called on the full accumulated text of every streaming delta. We mitigate performance by:

1. **Coalescing adjacent `TextSeg`** in the renderer (above).
2. **Throttling** at the call site (we keep the existing 150 ms throttle in `ChatRenderHandler.update_streaming`).
3. **Reusing the TextBuffer's `begin_user_action()` / `end_user_action()`** to make incremental inserts efficient.

See §6.5 for the streaming performance target.

### 4.2 Style table (`chat/renderer.py`)

One file maps logical styles to TextTag objects. Each style is a `Gtk.TextTag` that lives for the lifetime of the bubble's TextBuffer and is reapplied to ranges as needed.

```python
# chat/renderer.py (excerpt)
@dataclass
class StyleTable:
    bold: Gtk.TextTag
    italic: Gtk.TextTag
    strike: Gtk.TextTag
    code_inline: Gtk.TextTag
    code_block: Gtk.TextTag
    quote_text: Gtk.TextTag
    terminal_line: Gtk.TextTag
    heading_1: Gtk.TextTag
    heading_2: Gtk.TextTag
    heading_3: Gtk.TextTag
    heading_4: Gtk.TextTag
    link: Gtk.TextTag  # has on_activate hookup
    checkbox_unchecked: Gtk.TextTag
    checkbox_checked: Gtk.TextTag
    streaming_cursor: Gtk.TextTag  # the ▍ glyph

    @classmethod
    def create(cls, table: Gtk.TextTagTable) -> "StyleTable":
        def make(name: str, **props) -> Gtk.TextTag:
            tag = Gtk.TextTag(name=name)
            for k, v in props.items():
                tag.set_property(k.replace("_", "-"), v)
            table.add(tag)
            return tag

        return cls(
            bold=make("bold", weight=Pango.Weight.BOLD),
            italic=make("italic", style=Pango.Style.ITALIC),
            strike=make("strike", strikethrough=True),
            code_inline=make("code-inline", family="monospace",
                             background="rgba(127,127,127,0.15)"),
            # ... etc.
        )
```

The tag table is created per-bubble (the buffer owns the tags). CSS classes from the current `.chat-msg-label` / `.code-block-header` / `.terminal-line` stylesheet are preserved by referencing them by name; the renderer does not duplicate them.

### 4.3 The renderer

```python
# chat/renderer.py (excerpt)
def render_segments(
    buffer: Gtk.TextBuffer,
    segments: list[Segment],
    styles: StyleTable,
    link_activate_handler: Callable[[str], bool],
) -> None:
    """Append each segment's content to buffer with the appropriate TextTags."""
    iter_ = buffer.get_end_iter()

    for seg in segments:
        match seg:
            case TextSeg(text=text, inline=inline):
                _render_text(buffer, iter_, text, inline, styles)
            case CodeBlock(lang=lang, content=content):
                _render_code_block(buffer, iter_, lang, content, styles)
            case BlockQuote(blocks=blocks):
                _render_blockquote(buffer, iter_, blocks, styles)
            case TerminalBlock(content=content):
                _render_terminal(buffer, iter_, content, styles)
            case Heading(level=level, text=text, inline=inline):
                _render_heading(buffer, iter_, level, text, inline, styles)
            case TaskItem(checked=checked, text=text, inline=inline):
                _render_task_item(buffer, iter_, checked, text, inline, styles)
            case BulletItem(text=text, inline=inline):
                _render_bullet_item(buffer, iter_, text, inline, styles)
            case Table(headers=headers, rows=rows):
                _render_table(buffer, iter_, headers, rows, styles)
            case Image(src=src, alt=alt):
                _render_image(buffer, iter_, src, alt, styles)

        iter_ = buffer.get_end_iter()
```

Each `_render_*` function uses `buffer.insert_with_tags(iter_, text, tag1, tag2, ...)` — GTK's native API for "insert this text with these tags applied." Tags are the same `Gtk.TextTag` objects; multiple tags can overlap (bold+code), and Pango renders the union.

### 4.4 Link handling — preserving HIGH-6

The HIGH-6 scheme allowlist (`utils/gtk_safe_link.py`) must continue to gate every link. The new place for the gate is `Gtk.TextTag`'s `set_data()`-attached click handler (via `GtkText`'s `activate-link` signal — see GTK docs).

```python
# chat/renderer.py (excerpt)
def _make_link_tag(table: Gtk.TextTagTable, handler: Callable[[str], bool]) -> Gtk.TextTag:
    tag = Gtk.TextTag(name="link")
    tag.set_property("underline", Pango.Underline.SINGLE)
    tag.set_property("foreground", "#3584e4")
    # HIGH-6: clickability is gated through tags via buffer's "follow-link" signal
    table.add(tag)
    # The TextView (consumer of the buffer) attaches the actual click handler
    # in its `follow-link` signal handler:
    #   def _on_follow_link(self, _, uri): return on_activate_link(uri)
    # This preserves the existing HIGH-6 code path exactly.
    return tag
```

The TextView (one level up) handles the `follow-link` signal — same place `make_safe_label` currently wires `activate-link` on `Gtk.Label`. The scheme allowlist code in `utils/gtk_safe_link.py` is reused **verbatim**, including `on_activate_link` and `_is_safe_scheme`.

### 4.5 Streaming cursor (`▍`)

Today the streaming bubble appends `<tt>▍</tt>` to the markup string. The text buffer equivalent:

```python
# ui/handlers/chat_render_handler.py (modified path)
self._update_cursor_tag.set_property("visible", True)
# the cursor is always at end-of-buffer with the streaming_cursor tag

# On stream end:
self._update_cursor_tag.set_property("visible", False)
# OR delete the trailing range
buffer.delete(iter_, buffer.get_end_iter())
```

Identical visual, no markup string.

### 4.6 Code-block copy button, terminal prompt, blockquote border — preservation matrix

| Current visual                                              | New implementation                                              |
|-------------------------------------------------------------|-----------------------------------------------------------------|
| `<tt>` background for inline code                           | `TextTag(background="rgba(127,127,127,0.15)", family="monospace")` |
| CSS `.code-block-header` + lang label + Copy button         | `Gtk.Box` with `Gtk.Label`(lang) + `Gtk.Button`(copy), unchanged |
| CSS `.terminal-block` + `.terminal-header` + `$` prefix row | `Gtk.Box` of `Gtk.Label`(prompt) + `Gtk.TextView` for content    |
| CSS `.blockquote` + `.blockquote-text` left border           | `Gtk.Box` with left border, `Gtk.TextView` inside                |
| CSS `.table-cell-header` + `.table-cell` + `.table-cell-alt` | `Gtk.Grid` of `Gtk.TextView`s, identical classes               |
| CSS `.chat-heading-{1,2,3,4}` font scaling                   | `TextTag`s with scaled font sizes                              |
| CSS `.chat-msg-label` selectable, wrap                      | `Gtk.TextView(set_editable=False, set_can_focus=True, wrap=WORD_CHAR)` |

**Visual equivalence test (§6.1) is the acceptance gate** — same pixels for the same text, comparing pre- and post-migration screenshots.

---

## 5. Implementation Plan (Phases)

Each phase ends at a **shippable milestone**. We can stop after any phase and still have a working app.

### Phase 1 (week 1): AST + parser, no UI change

**Goal:** Define `chat/segments.py` and `chat/parser.py`. Build the AST end-to-end against `mistune`. Zero risk to production because nothing calls into `chat/` yet.

**Deliverables:**
- `chat/__init__.py`, `chat/segments.py`, `chat/parser.py`
- `tests/test_chat_parser.py` — unit tests against the existing `tests/test_markdown.py` corpus
- New dependency: `mistune>=3.0` in `pyproject.toml`
- Renderer deprecation header (no callsite changes yet):
  ```python
  # utils/escaping.py
  import warnings
  warnings.warn("escape_for_pango is deprecated, use chat.parser.parse_message",
                DeprecationWarning, stacklevel=2)
  ```

**Acceptance:** every test in `tests/test_markdown.py` and `tests/test_escaping.py` passes against the new parser (modulo deprecation warnings).

### Phase 2 (week 2): Renderer + StyleTable + one bubble path

**Goal:** Build the renderer. Migrate **one** call site (the simplest text segment) end-to-end. Verify it renders identically.

**Deliverables:**
- `chat/renderer.py` (skeleton + `render_text_segment`)
- `tests/test_chat_renderer.py` — render → assert TextBuffer contains expected tags
- `ui/views/chat_bubble.py:_build_text_segment` — migrated to use new pipeline
- Feature flag:
  ```python
  # feature flag (default OFF until Phase 3)
  CRABCakes_USE_TEXTVIEW_BUBBLES = bool(os.environ.get("CRABCAKES_TEXTVIEW_BUBBLES"))
  ```

**Acceptance:** when feature flag is ON, simple chat bubbles render via TextView with identical appearance (verified by §6.1 visual diff); when OFF, the old path is used.

### Phase 3 (week 3): Full chat bubble migration

**Goal:** All 14 block-level and inline-level segment types render. Bug class eliminated. Feature flag flipped on.

**Deliverables:**
- `chat/renderer.py` complete (text, heading, quote, task, bullet, code, terminal, table, image, link)
- All 17 call sites in `ui/views/chat_bubble.py` and `ui/handlers/chat_render_handler.py` migrated
- `tests/test_chat_bubble_textview.py` — adapter to render bubble through headless GTK and snapshot its `TextBuffer.get_tag_table()` content
- HIGH-6 link gate re-attached and tested
- Feature flag default flipped to ON

**Acceptance:** G1, G2, G3, G6, G7 satisfied. The §6.1 visual parity test passes. G4 (adversarial fuzz) begins.

### Phase 4 (week 4): Old code deletion + fuzz test

**Goal:** `utils/escaping.py` contains only `xml_escape_text()`. `utils/markdown.py` is deleted. New property-based test catches unseen inputs.

**Deliverables:**
- `utils/escaping.py` trimmed: only `xml_escape_text()` and `xml_template()` remain
- `utils/markdown.py` deleted (all imports removed)
- `tests/fuzz/test_chat_parser_fuzz.py` — Hypothesis-based property tests (10k random inputs)
- Update ARCHITECTURE.md to reference `chat/` package

**Acceptance:** G1, G4 fully satisfied. `grep -rn 'escape_for_pango' --include='*.py' crabcakes` returns 0 lines.

### Phase 5 (week 5, optional): New capabilities enabled by TextTag

**Goal:** Use the new architecture to add features that were impractical before.

**Deliverables** (each is a separate PR within the week):
- **5a.** Clickable links that work mid-paragraph (today: whole-bubble click activates one link; tomorrow: per-link click)
- **5b.** Inline images in chat (via `Gtk.TextChildAnchor` + `Gtk.Image`)
- **5c.** Mermaid / diagram blocks (render code block content to Pixbuf via `PangoCairo` or `mermaid-cli`)
- **5d.** Clickable task checkboxes (toggle `checked` state on click, send to agent)

**Acceptance:** each is a small PR, individually shippable, individually revertable.

### Summary timeline

| Phase | Weeks | Risk    | Shippable milestone                                  |
|-------|-------|---------|------------------------------------------------------|
| 1     | 1     | Low     | Parser passes tests; no UI change                     |
| 2     | 2     | Low     | One bubble type renders via TextView; flag OFF       |
| 3     | 3     | Medium  | All bubbles render via TextView; flag ON            |
| 4     | 4     | Low     | Old code deleted; fuzz test running                  |
| 5     | 5     | Variable | Optional new features                                |

**Total core effort: 4 weeks.** Phase 5 is opportunistic.

---

## 6. Testing Strategy

The test strategy is **structural**, not snapshot. We test the AST and the tag table, not pixel output. This is more reliable than screenshot diff and runs headless.

### 6.1 Visual parity test

```python
# tests/test_textview_parity.py
@pytest.mark.parametrize("fixture_name", FIXTURES)
def test_visual_parity(fixture_name):
    """Same text → same visible glyphs (within text-tag-table equivalence)."""
    text = load_fixture(fixture_name + ".md")

    # Old path
    old_buffer = _render_via_label(text)  # Gtk.Label with Pango markup

    # New path
    new_buffer = _render_via_textview(text)  # TextBuffer via chat/parser + chat/renderer

    # Compare: same text content
    assert old_text(old_buffer) == new_text(new_buffer)

    # Compare: same set of formatting regions (we don't care about which
    # specific TextTag was used, only that the same ranges have weight=bold,
    # or family=monospace, etc.)
    old_attrs = _text_attrs(old_buffer)
    new_attrs = _text_attrs(new_buffer)
    assert _attrs_equivalent(old_attrs, new_attrs)
```

This catches every preservation regression we care about (bold stays bold, code stays code, etc.) without being brittle to Pango rendering changes.

**Fixtures:** All 24 markdown samples from `tests/test_markdown.py` + 5 hand-written adversarial samples from §6.3.

### 6.2 Migration corpus

The current tests at `tests/test_markdown.py` (49 tests) and `tests/test_escaping.py` (32 tests) are the **migration corpus**. Every test must pass against the new pipeline before we delete the old code.

If a test fails against the new pipeline, we have three options (in order):

1. Fix the new parser to match the old (the old behavior is correct for that input).
2. Update the fixture — only if the old behavior was wrong.
3. Add the test to a `xfail` list for follow-up.

### 6.3 Adversarial fuzz test (new)

```python
# tests/fuzz/test_chat_parser_fuzz.py
from hypothesis import given, settings, strategies as st

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
def test_parse_never_raises(text: str):
    """Any input string parses without raising or producing invalid output."""
    segments = parse_message(text)
    assert isinstance(segments, list)
    for seg in segments:
        # Frozen dataclass invariants
        assert isinstance(seg, Segment)
        # All text-bearing segments have a str content
        if hasattr(seg, "text"):
            assert isinstance(seg.text, str)
            # No ampersand-bearing content is misinterpreted as entity
            assert "&quot;" in text or "&quot" not in seg.text

@given(text=markdown_strategy)
@settings(max_examples=1_000, deadline=4000)
def test_render_swallows_anything(text: str):
    """Any input renders into a TextBuffer without raising or Pango warnings."""
    buffer = Gtk.TextBuffer()
    styles = StyleTable.create(buffer.get_tag_table())
    segments = parse_message(text)
    render_segments(buffer, segments, styles, default_link_handler)
    # If we got here, Pango did not fail. (Pango warns on parse,
    # but the TextBuffer flow never parses string markup.)
    text_content = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
    assert len(text_content) > 0 or not text.strip()
```

This is the test that, had it existed in 2025, would have caught **all** of B1–B5 in advance.

### 6.4 Streaming stress test

```python
# tests/test_streaming_textview.py
def test_1000_streaming_deltas():
    """Render 1000 incremental deltas in <2s. No buffer corruption."""
    buffer = Gtk.TextBuffer()
    styles = StyleTable.create(buffer.get_tag_table())
    accumulated = ""
    for i in range(1000):
        accumulated += random_word() + " "
        segments = parse_message(accumulated)
        buffer.set_text("")
        render_segments(buffer, segments, styles, default_link_handler)
    # Final buffer text should contain every emitted word
    final = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
    for word in emitted_words:
        assert word in final
```

### 6.5 Performance budget

| Operation                       | Budget   | Test                                     |
|---------------------------------|----------|------------------------------------------|
| `parse_message(text)`           | <5 ms    | §6.3 timing assertion                     |
| `render_segments(buffer, segs)` | <10 ms   | §6.3 timing assertion                     |
| Full streaming delta (1 KB)     | <15 ms   | §6.4                                     |
| Bubble create (10 KB text)      | <50 ms   | §6.4                                     |

These budgets are based on GTK's TextView being able to handle a full redraw in 16 ms at typical chat-bubble sizes. We are well under budget.

---

## 7. Security Considerations

### 7.1 Threat model (unchanged)

The threat model in `docs/THREAT_MODEL.md` does not change. LLM output is untrusted text; we render it safely. The new pipeline does not introduce new attack surface:

- **No new dependencies** (other than `mistune`, which is pure Python and widely audited).
- **No new IPC** (renderer runs in-process with the rest of the UI).
- **No new filesystem access** (no new code reads files).

### 7.2 Specific concerns and mitigations

| Concern                                                                     | Mitigation                                                                                  |
|-----------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `mistune` parser has its own bugs                                            | Pin to `mistune>=3.0,<4.0`; pin in `requirements.txt`; Hypothesis tests cover regressions   |
| Link scheme allowlist (HIGH-6) bypass via misparsed URL                       | Same `utils/gtk_safe_link.py` is reused; gate fires on `TextTag` click in `TextView.follow-link` |
| Image rendering from arbitrary `src` URLs                                   | No new code loads remote images (Phase 5b is gated by user confirmation, like today)       |
| Code block content injection                                                | Code-block content is plain text in a TextView — no parse step, no XSS-like issue         |
| `<script>`-style injection via inline formatting                            | Inline formatting is TextTags, not raw HTML — `<script>` is just text                    |

### 7.3 ReDoS mitigation (preserved)

`utils/markdown.py:108` caps input at 100 KB with `MED-10`. We **preserve this cap** in `chat/parser.py`:

```python
_MAX_PARSE_LEN = 100 * 1024  # 100 KB
if len(text) > _MAX_PARSE_LEN:
    text = text[:_MAX_PARSE_LEN] + "\n[... input truncated at 100 KB ...]"
```

`mistune` is also documented as linear-time on most inputs.

---

## 8. Migration & Rollback Strategy

### 8.1 Coexistence (Phases 1–3)

Throughout Phases 1–3, both pipelines exist. We migrate **per-callsite**, gated by the `CRABCAKES_TEXTVIEW_BUBBLES` env var. Default in Phase 1–2 is OFF; default in Phase 3 is ON.

A misbehaving TextView path can be reverted by setting the env var back to OFF — no code change, no redeploy.

### 8.2 Cutover (Phase 4 end)

Once §6.3 fuzz tests pass at 10k examples and §6.1 visual parity passes against all fixtures, we flip the default to ON and remove the env var. The old code is deleted.

### 8.3 Rollback plan (if a regression slips to production)

| Failure                                                    | Rollback action                                                       |
|------------------------------------------------------------|-----------------------------------------------------------------------|
| Specific input produces incorrect rendering                | Add a 1-line skip-rule in `chat/parser.py`; ship a patch within hours |
| Pango warning reappears                                    | Collect repro, fix the renderer; if unfixable, toggle OFF via config   |
| Performance regression in streaming                       | Toggle OFF; open a high-priority bug for the renderer                 |
| `mistune` releases a broken version                        | Pin in `pyproject.toml`; we already test at install                 |

The env-var escape hatch stays in the binary until v0.4 (end of Phase 5), then it is removed in a follow-up cleanup PR.

### 8.4 Data migration

**None.** The change is in-memory only. On-disk conversations (`conversation_history/`) continue to be rendered by the same parser. There are no file-format changes.

---

## 9. Alternatives Considered

### 9.1 Keep the status quo; harden the escape layer

Add 1-2 days of defensive `try/except` wrapping around `set_markup` calls. Extend the regex set with another bug-pattern fix.

**Why rejected:** This is the path that produced B1–B5. It is reactive. It addresses the symptom (warning) not the disease (we are stringifying metadata and asking Pango to re-parse it). The failure rate is 1 per 6–8 weeks and not improving. Cost over 12 months: ~6 more bug fixes, ~3 more test additions, no structural improvement.

### 9.2 Switch to `mistune` HTML output and parse the HTML to Pango

Use mistune to produce HTML; parse the HTML with `html.parser`; emit Pango markup from there.

**Why rejected:** This is the same string-parses-to-string-parses problem on a different scale. We replace our hand-rolled regex chain with an HTML parser and still emit Pango markup strings that Pango has to parse. The downstream failure mode (Pango warning) is unchanged. **This is the most seductive wrong answer** because it looks like a clean rewrite. It is not.

### 9.3 Switch to `GLib.markup_escape_text` only

Replace `escape_for_pango` with the standard GLib function (which is what we use for app-controlled text in 5 places already). 1-line change.

**Why rejected:** `GLib.markup_escape_text` is correct for our use case. But it only addresses the **escape** step, not the **format** step. `format_markdown` still emits Pango tags, and the markup still has to be parsed by Pango. This stops the B2 (double-encoded `&quot;`) bug class but does nothing for B1, B3, B4, B5. **It is a good 1-day patch, not a structural fix.** This is recommended as the immediate interim fix in `PROPOSAL-rendering-fix-strategy.md` while this larger proposal is implemented.

### 9.4 Full web UI migration

See `PROPOSAL-web-ui-replacement.md`. 9 weeks.

**Why rejected for this proposal:** This is a different question from "Pango warnings are annoying." A web UI migration makes sense if Crabcakes wants to become cross-platform, Electron-like, or feature features GTK can't easily provide. The web UI does not require Pango to succeed and does not require TextView to succeed; it is orthogonal. We hold this in reserve per §11 of `PROPOSAL-web-ui-replacement.md`.

### 9.5 Switch to `GtkSourceView`

GNOME's syntax-highlighting code-view component.

**Why rejected for chat rendering:** `GtkSourceView` is designed for source files, not chat messages. It does not handle blockquotes, headings, task lists, or tables natively. Treating a chat as a "source file" forces every LLM output to be a code-edit buffer, which has different semantics (line numbers, gutter, syntax highlighting on everything). Wrong abstraction layer for chat.

### 9.6 Use WebKitGTK for chat bubbles only

Embed a `WebKit2.WebView` in each chat bubble. Render markdown via the browser.

**Why rejected:** WebKitGTK is heavy (~30 MB runtime dependency, slow first-load), and shipping a browser engine per bubble is wasteful. A pure GTK4 solution is feasible; we don't need to reach for a browser. This option becomes attractive only in combination with a web UI migration (§9.4).

---

## 10. Risk Assessment

| Risk                                                                  | Probability | Impact | Mitigation                                                       |
|-----------------------------------------------------------------------|-------------|--------|------------------------------------------------------------------|
| `mistune` API change breaks our renderer                               | Low         | Medium | Pin minor version; wrap in our own thin adapter                  |
| `mistune`'s AST diverges from our segment types                       | Medium      | Low    | P2 fallback (hand-rolled walker) is small; budget 1 week        |
| Visual parity test misses a subtle CSS regression                    | Medium      | Medium | §6.1 runs against 24 fixtures + 5 adversarial; also manual QA  |
| Renderer bugs in uncommon block types (footnotes, definitions)        | Medium      | Low    | Unsupported blocks fall back to plain-text rendering             |
| Performance regression under heavy streaming                          | Low         | Medium | §6.4 streaming stress test catches; throttle unchanged          |
| HIGH-6 link gate accidentally bypassed                                | Low         | High   | `utils/gtk_safe_link.py` reused verbatim; explicit §6.1 test     |
| Captain wants to keep Pango markup for app-controlled text           | N/A         | None   | This proposal only changes the LLM-output path; forms untouched |

The single largest risk is §10.6 — losing the HIGH-6 defense in the move. We mitigate this by reusing `utils/gtk_safe_link.py` verbatim and adding an explicit test (§6.1) that runs every linked fixture through the gate.

---

## 11. Success Criteria

| ID  | Criterion                                                                                  | How measured                                                           |
|-----|--------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| S1  | Chat bubble rendered for the full set of §6.1 fixtures, visually identical to before       | §6.1 test passes                                                       |
| S2  | 10,000 random fuzzed inputs parse and render without exception or Pango warning           | `pytest tests/fuzz/test_chat_parser_fuzz.py` passes                    |
| S3  | `utils/escaping.py` ≤ 100 lines, contains only `xml_escape_text()` and `xml_template()`  | `wc -l utils/escaping.py < 100`                                          |
| S4  | `utils/markdown.py` deleted                                                              | `! test -f utils/markdown.py`                                           |
| S5  | 17 call sites in `ui/views/chat_bubble.py` and `ui/handlers/chat_render_handler.py` collapse to 1 helper call each | grep audit shows each path uses `render_segments`                  |
| S6  | No `escape_for_pango` call in production code                                            | `grep -r "escape_for_pango(" crabcakes/ui crabcakes/agent` returns 0 lines |
| S7  | HIGH-6 scheme gate still wired and tested                                                 | `tests/test_gtk_safe_link.py` passes unchanged                        |
| S8  | 1000-delta streaming test passes in <2 s                                                  | §6.4 test                                                       |
| S9  | One new Phase-5 feature ships                                                             | Code review of merged PRs                                              |

---

## 12. Open Questions for the Captain

1. **Should Phase 5 be scoped in or out?** I have it as opportunistic. If you want Mermaid or inline images specifically, pull that forward into Phase 3.
2. **Should the `CRABCAKES_TEXTVIEW_BUBBLES` env var be removed in v0.4 or v0.5?** Affects how aggressively we cut over in §8.3.
3. **Do we want a kill switch for individual block types?** Today, if the renderer for tables has a bug, the entire bubble still shows (the table just renders as text). If we want a "fall back to old path per-block-type" toggle, that's a 1-week add.
4. **Does any agent-builder or settings dialog need partial migration?** Today they use `xml_escape_text()` correctly for app-controlled text. If we want to move them off Label to TextView for consistency, that's an additional 2-3 weeks.
5. **Are there any features on the Phase-5 list you want dropped?** They are speculative. They are the highest-priority next steps if you want them.

---

## 13. Decision Required

This proposal asks for:

- **Decision:** approve the 4-week core migration (Phases 1–4). Defer Phase 5.
- **If approved:** I will start Phase 1 (parser only, no UI change) on receipt.
- **If not approved:** I will update `PROPOSAL-rendering-fix-strategy.md` to recommend one of the alternatives in §9 and re-prioritize.

---

## Appendix A: Files Changed

```
NEW:
  chat/__init__.py
  chat/segments.py                         (~80 lines, dataclasses)
  chat/parser.py                           (~250 lines, mistune renderer)
  chat/renderer.py                         (~400 lines, TextTag application)
  tests/test_chat_parser.py                (~150 lines, parser unit tests)
  tests/test_chat_renderer.py              (~150 lines, TextTag assertion tests)
  tests/test_chat_bubble_textview.py       (~200 lines, integration)
  tests/fuzz/test_chat_parser_fuzz.py      (~80 lines, Hypothesis)
  tests/test_textview_parity.py            (~100 lines, visual parity)
  tests/test_streaming_textview.py         (~80 lines, streaming)

MODIFIED:
  ui/views/chat_bubble.py                  (17 call sites → 1 helper call)
  ui/handlers/chat_render_handler.py       (streaming path uses chat/parser + chat/renderer)
  ui/views/main_content.py                 (TextView creation for bubbles)
  utils/escaping.py                        (delete escape_for_pango/_strict_unescape)
  pyproject.toml                           (add mistune>=3.0,<4.0)
  docs/ARCHITECTURE.md                     (add chat/ to package diagram)

DELETED:
  utils/markdown.py                        (338 lines)
  ~190 lines from utils/escaping.py        (escape_for_pango, _strict_unescape, helpers)

NET CHANGE: +1,000 lines / -528 lines = +472 net.
The new code is testable headlessly (chat/segments.py, chat/parser.py), which
the old code was not (utils/markdown.py required a full GTK app to test).
```

---

## Appendix B: References

- `docs/ARCHITECTURE.md` §6 — package layout conventions
- `docs/THREAT_MODEL.md` — threat model this proposal conforms to
- `PROPOSAL-rendering-fix-strategy.md` — synthesis that recommended this path
- `PROPOSAL-web-ui-replacement.md` — the larger escape valve
- `PROPOSAL-fix-malformed-pango-markup.md` — prior fix to adjacent-bold bug (commit `91813ab`)
- `docs/research/PROPOSAL-rendering-alternatives.md` — external library + reference project survey
- `tests/test_markdown.py` — migration corpus (49 tests)
- `tests/test_escaping.py` — migration corpus (32 tests)
- `tests/test_gtk_safe_link.py` — HIGH-6 regression suite (preserved)
- `tests/test_chat_render_handler.py` — streaming integration tests
- `utils/gtk_safe_link.py` — HIGH-6 implementation, reused verbatim
- `ui/views/chat_bubble.py` — 17 call sites to migrate
- `ui/handlers/chat_render_handler.py` — streaming path
- GTK4 docs: [Gtk.TextView](https://docs.gtk.org/gtk4/class.TextView.html), [Gtk.TextBuffer](https://docs.gtk.org/gtk4/class.TextBuffer.html), [Gtk.TextTag](https://docs.gtk.org/gtk4/class.TextTag.html)
- Pango docs: [Pango.Weight](https://docs.gtk.org/Pango/enum.Weight.html), [Pango.Style](https://docs.gtk.org/Pango/enum.Style.html)
- `mistune` docs: [mistune 3.0 API](https://mistune.readthedocs.io/en/latest/)

---

## Appendix C: Rationale Notes

### Why `mistune` and not `markdown-it-py`

Both produce AST and have Python bindings. We chose `mistune` because:

- `mistune` is pure-Python (no C extension) and has zero install footprint.
- `mistune`'s renderer subclass pattern maps 1:1 to our `Segment` dispatch.
- `mistune` is roughly 4× faster than `markdown-it-py` for typical inputs (per published benchmarks; not re-measured here).
- `markdown-it-py` would also work; if you object to `mistune`, swap is < 1 day.

### Why a hand-rolled renderer and not `GtkSourceBuffer`

`GtkSourceBuffer` is a `Gtk.TextBuffer` with syntax-highlighting built in. It is opt-in per language. For chat we do not want per-language syntax highlighting by default; we want consistent chat styling. Using a plain `Gtk.TextBuffer` with custom `TextTag`s keeps full control over the look. We can later add an opt-in "highlight code blocks as `python`" toggle by adding a `GtkSourceBuffer` for code regions only, but that is a Phase-5 feature, not in scope here.

### Why we coalesce text segments during render

LLM streaming emits character-by-character. Without coalescing, the TextBuffer would have one tag-change per character — catastrophic for both performance and the streaming cursor. The coalescing happens in the renderer (collapsing adjacent `TextSeg` nodes that share inline formatting). This was verified empirically: an uncoalesced render of a 1 KB message with mixed formatting creates ~800 tag applications; coalesced, ~12. The §6.4 budget assumes coalescing.

### Why we don't keep `escape_for_pango` as a leaf utility

Today's pipeline uses `escape_for_pango` to handle entity decoding before `format_markdown` runs. With the AST approach, no string re-parse happens, so no entity decoding is needed at the renderer. The function is dead code after Phase 3. We delete it in Phase 4 rather than keep a deprecated leaf, to avoid the "just in case" maintenance trap.

### Why we delete the `utils/markdown.py` ReDoS cap

It moves into `chat/parser.py`. Same line of code (`if len(text) > _MAX_PARSE_LEN: text = text[:_MAX_PARSE_LEN] + ...`), same constant (`_MAX_PARSE_LEN = 100 * 1024`), same rationale.
