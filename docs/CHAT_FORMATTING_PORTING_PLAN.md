# Chat Formatting Porting Plan — Deadcode → CrabCakes

**Date:** 2026-04-11
**Author:** Qaster
**Status:** Plan only — no code changes made

---

## Executive Summary

This is the largest porting effort for CrabCakes. Deadcode's chat formatting spans **~2,550 lines across 5 files** — a markdown-to-Pango converter, syntax highlighter, block segment parser, and a full bubble rendering engine with typing indicators, streaming, error bubbles, code blocks, blockquotes, terminal blocks, file cards, tool call cards, and approval cards.

CrabCakes currently renders messages as **plain `Gtk.Label` with `<b>Role:</b> text`** — no bubbles, no markdown, no formatting at all.

This plan is divided into **5 phases**, each independently verifiable with tests. No phase depends on a later phase. The app must work correctly after each phase.

---

## Current State

### Deadcode (source) — 2,548 lines total

| File | Lines | Responsibility |
|------|-------|---------------|
| `src/formatters.py` | 381 | Markdown→Pango converter, XML escaping, block segment extraction |
| `src/highlight.py` | 106 | Pygments→Pango syntax highlighting |
| `src/ui/chat_render.py` | 702 | ChatRenderer class — all bubble types, typing, streaming |
| `src/ui/chat.py` | 622 | Chat panel management, event routing, input handling |
| `src/ui/feed.py` | 737 | Project feed (uses ChatRenderer for rendering) |

### CrabCakes (target)

| File | Current State |
|------|--------------|
| `ui/views/main_content.py` | `append_message_to_tab()` renders `<b>Role:</b> text` as plain label |
| `ui/handlers/chat_handler.py` | Routes messages to `main_content.append_message_to_tab()` |
| No formatter | No markdown conversion exists |
| No highlighter | No syntax highlighting exists |
| No bubble CSS | No chat bubble styling exists |

---

## Architecture Principles for This Port

**The problem with deadcode:** It grew organically into a monolith. `chat_render.py` (702 lines) does too many things — message rendering, typing bubbles, streaming, scrolling, copy/forward buttons, file cards, tool call cards, approval delegation. It's a god class that became impossible to test or extend safely.

**Our approach:** Each subsystem gets its own module, following Section 8.6 (handler pattern). Views render. Handlers own logic. Utilities own pure functions. No god classes.

**Mapping deadcode → CrabCakes:**

| Deadcode | CrabCakes |
|----------|-----------|
| `formatters.py` (monolithic) | `utils/markdown.py` + `utils/escaping.py` |
| `highlight.py` | `utils/syntax_highlight.py` |
| `chat_render.py` (god class) | `ui/handlers/chat_render_handler.py` + `ui/views/chat_bubble.py` |
| `chat.py` (panel + routing) | Already split: `chat_handler.py` + `main_content.py` |

---

## Phase 1: Text Formatting Foundation

**Goal:** Messages render with proper markdown (bold, italic, code, links, lists) inside styled bubbles. No code blocks yet — just inline formatting.

**Why first:** Everything else builds on top of this. Get text rendering right before adding complex block types.

### Files Created/Modified

| File | Action | Lines (est.) |
|------|--------|-------------|
| `utils/escaping.py` | NEW | ~50 |
| `utils/markdown.py` | NEW | ~150 |
| `ui/views/chat_bubble.py` | NEW | ~200 |
| `ui/handlers/chat_render_handler.py` | NEW | ~80 |
| `ui/views/main_content.py` | MODIFY | ~20 |
| `ARCHITECTURE.md` | MODIFY | — |

### `utils/escaping.py`

Pure Python. No GTK imports.

Port from deadcode's `formatters.py`:
- `escape_for_pango(text)` — escape XML specials while preserving existing Pango markup tags. Tracks open tags on a stack to handle malformed markup gracefully.
- `xml_escape_text(text)` — simple & < > " escaping for plain text.

This is the foundation — every other formatting function calls this first.

### `utils/markdown.py`

Pure Python. No GTK imports.

Port from deadcode's `formatters.py`:
- `format_markdown(text)` — converts Markdown to Pango Markup:
  - `**bold**` → `<b>bold</b>`
  - `*italic*` → `<i>italic</i>`
  - `` `code` `` → `<tt>code</tt>` (with placeholder protection so inner underscores aren't mangled)
  - `~~strike~~` → `<s>strike</s>`
  - `[text](url)` → `<a href="url"><u>text</u></a>`
  - Auto-detect bare URLs → clickable links
  - Bullet lists: `- item` → `• item`
  - Ordered lists: `1. item` preserved

Key difference from deadcode: **code block extraction is NOT in this file.** Code blocks need segment parsing (Phase 2). This file only handles inline formatting that applies within a single text segment.

### `ui/views/chat_bubble.py`

GTK4 widget code. Creates and returns bubble widgets.

Port from deadcode's `ChatRenderer.append_message()` — but only the basic bubble shell:
- `create_bubble(role, content_markup, agent_name=None, ts=None, agent_color=None)` → returns `Gtk.Widget`
  - Creates outer box (alignment), header (name + timestamp), bubble box (with CSS class), content label
  - CSS class: `bubble-mine` (user) or `bubble-theirs` (agent)
  - Header shows colored dot + agent name + timestamp for agent messages
  - User messages right-aligned, agent messages left-aligned
- `create_system_message(text)` → returns `Gtk.Widget` (centered, muted)

This is a **view** — it only creates widgets. No logic, no state, no callbacks beyond what's needed for widget construction.

### `ui/handlers/chat_render_handler.py`

Per Section 8.6 — owns rendering logic and state.

- Receives agent color/name lookups via constructor callbacks
- `render_message(role, content, ts, agent_name, session_key, event_type, event_data, container)`:
  1. Calls `format_markdown(escape_for_pango(content))` to get Pango markup
  2. Calls `create_bubble()` to get the widget
  3. Appends to container
  4. Scrolls to bottom

### Modify `ui/views/main_content.py`

Replace `append_message_to_tab()` and `append_message_to_current_tab()`:
- Instead of creating plain `Gtk.Label`, delegate to `ChatRenderHandler.render_message()`
- Handler reference set via `set_chat_render_handler(handler)`

### Modify `ui/handlers/chat_handler.py`

Wire `ChatRenderHandler` into the chat event flow:
- `on_chat_event()` passes messages to render handler instead of directly to main_content
- Render handler creates the widget and appends to the correct container

### Add CSS

Port bubble CSS from deadcode's `styles.py`:
- `.bubble-mine` — indigo gradient, rounded corners (14/14/2/14)
- `.bubble-theirs` — dark gradient, rounded corners (14/14/14/2)
- `.msg-header` — small muted text

### Tests

**`tests/test_escaping.py`** (new):
- Plain text → unchanged
- `Tom & Jerry` → `Tom &amp; Jerry`
- `<b>Tom</b>` → preserved (tags intact)
- `</b>` alone → escaped (malformed closing)
- Mixed: `<b>Tom & Jerry</b>` → text escaped, tags preserved

**`tests/test_markdown.py`** (new):
- `**bold**` → `<b>bold</b>`
- `*italic*` → `<i>italic</i>`
- `` `code` `` → `<tt>code</tt>`
- Mixed formatting preserved
- Inline code protected from italic/bold regex interference
- Bare URLs converted to links
- Empty string → empty string

**`tests/test_chat_render_handler.py`** (extend existing):
- Render user message → bubble created with correct alignment
- Render agent message → bubble with colored header
- Render system message → centered

### Verification Checkpoint

- [ ] Run `pytest` — all tests pass (existing 95 + new)
- [ ] Run app → connect → send message → see styled bubble (not plain text)
- [ ] Markdown renders: bold, italic, code, links visible
- [ ] User bubbles right-aligned, agent bubbles left-aligned
- [ ] Commit: `"feat: Phase 1 — markdown formatting and chat bubbles"`

---

## Phase 2: Block-Level Formatting

**Goal:** Code blocks, blockquotes, terminal blocks, headings, and task lists render with proper styling.

**Why second:** Block parsing builds on the inline formatter. Code blocks with syntax highlighting are the most visually impactful feature and the most complex to get right.

### Files Created/Modified

| File | Action | Lines (est.) |
|------|--------|-------------|
| `utils/block_parser.py` | NEW | ~120 |
| `utils/syntax_highlight.py` | NEW | ~100 |
| `ui/views/chat_bubble.py` | MODIFY | ~150 |
| `ARCHITECTURE.md` | MODIFY | — |

### `utils/block_parser.py`

Pure Python. No GTK imports.

Port from deadcode's `formatters.py` `extract_blocks()`:
- `extract_blocks(text)` → returns list of segment dicts:
  - `{"type": "text", "content": "...", "lang": ""}`
  - `{"type": "code", "content": "...", "lang": "python"}`
  - `{"type": "quote", "content": "..."}`
  - `{"type": "terminal", "content": "..."}`
  - `{"type": "heading", "content": "...", "level": 2}`
  - `{"type": "task", "content": "...", "checked": true/false}`

Logic:
1. Split on ` ``` ` fenced code blocks first
2. Within text segments, detect consecutive blockquote lines (`> `), consecutive terminal lines (`$ `), heading lines (`# `), and task list items (`- [ ] / - [x]`)
3. Return ordered list of typed segments

**Key difference from deadcode:** This is a standalone utility function. Deadcode buries this in `formatters.py` alongside the inline converter. We separate them — `utils/markdown.py` for inline, `utils/block_parser.py` for block extraction.

### `utils/syntax_highlight.py`

Pure Python. No GTK imports. Optional dependency on Pygments.

Port from deadcode's `highlight.py`:
- `highlight(code, lang="")` → returns Pango Markup string
- Uses Pygments to lex code, maps token types to foreground colors via `<span foreground="...">`
- Color palette tuned for dark background
- Falls back to plain escaped monospace if no lexer found or Pygments not installed

**Important:** Pygments is an **optional** dependency. If not installed, code blocks still render — just without syntax colors. The function must handle `ImportError` gracefully.

### Modify `ui/views/chat_bubble.py`

Add segment rendering to `create_bubble()`:
- Instead of one label, iterate segments from `extract_blocks(content)`
- Each segment type gets its own widget:
  - `text` → `Gtk.Label` with `format_markdown(escape_for_pango(content))`
  - `code` → Code block widget (header bar with language label + copy button, monospace label with syntax highlighting)
  - `quote` → Blockquote widget (left border, italic muted text)
  - `terminal` → Terminal block widget (amber left border, `$ ` prefix on each line)
  - `heading` → Label with scaled font size
  - `task` → Label with ☑/☐ checkbox character

**Code block widget structure:**
```
code-block (CSS class, per-language color variant)
├── header (language label + copy button)
└── content (monospace, syntax-highlighted, selectable, wrap)
```

Copy button: uses `Gdk.Display.get_default().get_clipboard().set()` — GTK4 clipboard API.

### Add CSS

Port from deadcode:
- `.code-block` — dark background, left border
- `.code-block-header` — colored header bar (color varies by language)
- `.code-block-content` — monospace, light text
- Per-language variants: `.lang-python`, `.lang-javascript`, `.lang-bash`, etc.
- `.blockquote`, `.blockquote-text` — left border, italic, muted
- `.terminal-block`, `.terminal-header` — amber left border

### Tests

**`tests/test_block_parser.py`** (new):
- Plain text → single text segment
- Code block → code segment with lang
- Code block without lang → code segment with empty lang
- Mixed text + code → multiple segments in order
- Blockquote lines → quote segment
- Terminal `$ ` lines → terminal segment
- Heading `# ` → heading segment with correct level
- Task `- [ ] / - [x]` → task segment with checked state
- Empty input → single empty text segment

**`tests/test_syntax_highlight.py`** (new):
- Python code → highlighted output contains `<span foreground=` tags
- Unknown language → falls back to plain escaped text
- Empty string → empty string
- Pygments not installed → graceful fallback (mock ImportError)

### Verification Checkpoint

- [ ] `pytest` — all tests pass
- [ ] Send message with code block → renders with header, syntax colors, copy button
- [ ] Blockquotes render with left border and italic text
- [ ] Terminal commands render with `$ ` prefix and amber border
- [ ] Headings render at correct sizes
- [ ] Task lists render with ☐/☑
- [ ] Commit: `"feat: Phase 2 — block-level formatting (code, quotes, terminals)"`

---

## Phase 3: Streaming and Typing Indicators

**Goal:** Typing bubbles (animated dots) and streaming bubbles (text appears incrementally with cursor) work correctly.

**Why third:** These are dynamic UI elements that require timer-based updates and careful lifecycle management. They don't depend on block formatting — they use simpler text-only rendering.

### Files Created/Modified

| File | Action | Lines (est.) |
|------|--------|-------------|
| `ui/handlers/chat_render_handler.py` | MODIFY | ~80 |
| `ui/views/chat_bubble.py` | MODIFY | ~60 |

### Modify `ui/handlers/chat_render_handler.py`

Add state tracking:
- `_typing_bubbles: dict[str, tuple]` — session_key → (widget, label, GLib source_id)
- `_streaming_bubbles: dict[str, tuple]` — session_key → (widget, label, content_box)

Add methods:
- `show_typing(session_key, container)` — create animated dot bubble, start GLib timer (500ms cycle)
- `clear_typing(session_key)` — remove bubble, cancel timer
- `start_streaming(session_key, container, agent_name)` — create streaming bubble with cursor `▍`
- `update_streaming(session_key, delta_text)` — append text, keep cursor
- `end_streaming(session_key)` — remove cursor, finalize text

**Thread safety:** All GTK widget manipulation happens on main thread. If gateway callbacks come from background thread, use `GLib.idle_add()` (already in `GatewayHandler.dispatch()`).

### Modify `ui/views/chat_bubble.py`

Add widget factories:
- `create_typing_bubble()` → returns widget with animated dots label
- `create_streaming_bubble()` → returns widget with mutable label for incremental text

### Modify `ui/handlers/chat_handler.py`

Wire streaming events from gateway:
- `"typing"` event → `chat_render_handler.show_typing()`
- `"chat"` event with `state="delta"` → `chat_render_handler.update_streaming()`
- `"chat"` event with `state="final"` → `chat_render_handler.end_streaming()` then render final message
- `"chat"` event without prior streaming → just render normally (backward compatible)

### Tests

**`tests/test_chat_render_handler.py`** (extend):
- `show_typing()` → creates bubble in container, source_id tracked
- `clear_typing()` → removes bubble, source_id cancelled
- `start_streaming()` → creates streaming bubble
- `update_streaming()` → text appended correctly
- `end_streaming()` → cursor removed
- Double `start_streaming()` → no duplicate (idempotent)

### Verification Checkpoint

- [ ] `pytest` — all tests pass
- [ ] Send message → see typing dots before response starts
- [ ] Streaming response → text appears incrementally with cursor
- [ ] Streaming ends → cursor removed, final message renders
- [ ] No GLib timer leaks (typing bubbles clean up properly)
- [ ] Commit: `"feat: Phase 3 — streaming and typing indicators"`

---

## Phase 4: Special Event Cards

**Goal:** File read cards, edit proposal cards, tool call cards, and error bubbles render with proper styling.

**Why fourth:** These are structured event types from the gateway. They require the bubble infrastructure from Phase 1 but add specialized layouts. Less critical than core formatting.

### Files Created/Modified

| File | Action | Lines (est.) |
|------|--------|-------------|
| `ui/views/chat_bubble.py` | MODIFY | ~120 |
| `ui/handlers/chat_render_handler.py` | MODIFY | ~40 |

### Modify `ui/views/chat_bubble.py`

Add widget factories:
- `create_file_card(file_path, snippet, line_range)` → code-block-style card with 📄 icon, filename, optional line range, code snippet
- `create_edit_card(file_path, diff)` → code-block-style card with ✏️ icon, filename, diff content
- `create_tool_card(tool_name, detail)` → code-block-style card with 🔧 icon, tool name, detail text
- `create_error_bubble(error_msg)` → red-tinted bubble with ❌ icon

All follow the same pattern: header bar with icon + label, content area with monospace text.

### Modify `ui/handlers/chat_render_handler.py`

Add to `render_message()`:
- `event_type="file_read"` → calls `create_file_card()`
- `event_type="edit_proposal"` → calls `create_edit_card()`
- `event_type="tool_call"` → calls `create_tool_card()`
- `event_type="error"` → calls `create_error_bubble()`

### Add CSS

Port from deadcode:
- `.bubble-error` — red background, red border
- `.bubble-theirs.bubble-thinking` — amber left border
- `.bubble-theirs.bubble-streaming` — indigo left border
- `.bubble-theirs.bubble-file-read` — green left border
- `.bubble-theirs.bubble-tool-call` — slate left border
- `.bubble-theirs.bubble-edit-proposal` — amber left border

### Tests

**`tests/test_chat_render_handler.py`** (extend):
- File card renders with filename and snippet
- Edit card renders with filename and diff
- Tool card renders with tool name
- Error bubble renders with error message
- Unknown event_type → falls back to text rendering

### Verification Checkpoint

- [ ] `pytest` — all tests pass
- [ ] File read event → card with filename and snippet
- [ ] Tool call event → card with tool name
- [ ] Error → red bubble with error text
- [ ] Commit: `"feat: Phase 4 — special event cards (file, tool, error)"`

---

## Phase 5: Polish — Copy/Forward Buttons and Auto-Scroll

**Goal:** Agent bubbles get hover-to-show copy and forward buttons. Auto-scroll works reliably. Message grouping (consecutive messages from same sender share a header).

**Why last:** These are UX polish features. The app is fully functional without them.

### Files Created/Modified

| File | Action | Lines (est.) |
|------|--------|-------------|
| `ui/views/chat_bubble.py` | MODIFY | ~60 |
| `ui/handlers/chat_render_handler.py` | MODIFY | ~30 |

### Copy/Forward Buttons

On agent bubbles (not user, not system), add a button row below content:
- **Copy button** — `Gtk.Image` (copy.svg icon), opacity 0.25, hover → 1.0
- **Forward button** — `Gtk.Image` (forward.svg icon), same opacity behavior

Implementation via `Gtk.EventControllerMotion` on each button — enter/leave callbacks toggle opacity.

Copy: `Gdk.Display.get_default().get_clipboard().set(content)`

Forward: calls `on_forward_message` callback (wired by `window.py` to show agent picker popover).

**Icons:** Deadcode loads SVG files from an `icons/` directory. CrabCakes needs either:
- Copy the icon SVGs into a `ui/icons/` directory, OR
- Use GTK4 symbolic icons (`"edit-copy-symbolic"`, `"edit-redo-symbolic"`) — simpler, no file dependencies

Recommendation: Use symbolic icons. No file management needed.

### Auto-Scroll

After every `render_message()`, `show_typing()`, `start_streaming()`, and `update_streaming()`:
- Get container's parent `ScrolledWindow`
- Get `VAdjustment`
- Set value to `upper - page_size`
- Use `GLib.timeout_add(30, scroll_fn)` to defer slightly (lets GTK complete layout first)

### Message Grouping

Track `_last_header_key` (e.g., `f"{role}:{agent_name}"`) in handler:
- If current message has same key as previous → skip header (no name/timestamp repeated)
- Different key → show header

Reset on session switch.

### Tests

**`tests/test_chat_render_handler.py`** (extend):
- Consecutive messages from same agent → second has no header
- Message from different agent → header shown
- Session switch → header shown again

### Verification Checkpoint

- [ ] `pytest` — all tests pass
- [ ] Hover over agent bubble → copy/forward buttons appear
- [ ] Click copy → content in clipboard
- [ ] Messages auto-scroll to bottom on new content
- [ ] Consecutive agent messages grouped (single header)
- [ ] Commit: `"feat: Phase 5 — copy/forward buttons, auto-scroll, message grouping"`

---

## Summary: File Map

### New Files (all phases)

| File | Phase | Purpose |
|------|-------|---------|
| `utils/escaping.py` | 1 | Pango/XML escape utilities |
| `utils/markdown.py` | 1 | Inline Markdown → Pango converter |
| `utils/block_parser.py` | 2 | Block segment extraction |
| `utils/syntax_highlight.py` | 2 | Pygments → Pango syntax highlighting |
| `ui/views/chat_bubble.py` | 1-5 | All bubble widget factories |
| `ui/handlers/chat_render_handler.py` | 1-5 | Rendering logic, state, lifecycle |
| `tests/test_escaping.py` | 1 | Escaping tests |
| `tests/test_markdown.py` | 1 | Markdown conversion tests |
| `tests/test_block_parser.py` | 2 | Block parser tests |
| `tests/test_syntax_highlight.py` | 2 | Highlighter tests |

### Modified Files

| File | Phase | Change |
|------|-------|--------|
| `ui/views/main_content.py` | 1 | Delegate to render handler |
| `ui/handlers/chat_handler.py` | 1, 3 | Wire render handler, streaming events |
| `ui/window.py` | 1 | Create and wire `ChatRenderHandler` |
| `ARCHITECTURE.md` | 1-5 | Document all new files and APIs |

---

## Architecture Compliance

**Handler pattern (Section 8.6):**
- `chat_render_handler.py` owns ALL rendering logic and state (typing timers, streaming state, message grouping)
- `chat_bubble.py` is a VIEW — it only creates widgets. No state, no timers, no callbacks beyond widget signals
- `chat_handler.py` does NOT render — it routes events to the render handler

**Layer separation:**
- `utils/escaping.py`, `utils/markdown.py`, `utils/block_parser.py` — pure Python, no GTK
- `utils/syntax_highlight.py` — pure Python, optional Pygments dependency
- `ui/views/chat_bubble.py` — GTK4 only, no gateway imports
- `ui/handlers/chat_render_handler.py` — GTK4 + utils, no gateway imports
- `gateway/` — untouched by this entire plan

**No handler-to-handler imports:**
- `ChatRenderHandler` does NOT import `ChatHandler`
- `ChatHandler` calls `ChatRenderHandler` methods via reference (set by `window.py`)
- Forward button callback → set by `window.py`, NOT imported from another handler

**No god classes:**
Deadcode's `ChatRenderer` is 702 lines doing everything. CrabCakes splits it:
- Text processing → `utils/` (pure functions, testable without GTK)
- Widget creation → `ui/views/chat_bubble.py` (stateless factories)
- Rendering orchestration → `ui/handlers/chat_render_handler.py` (state + logic)

---

## Dependency: Pygments

Phase 2 (syntax highlighting) requires Pygments. This is an **optional** dependency:
- If installed: code blocks get syntax colors
- If not installed: code blocks render as plain monospace text

Add to project documentation but don't hard-require it in imports.

```bash
pip install pygments  # optional, for syntax-highlighted code blocks
```

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Pango markup injection (malformed agent output) | `escape_for_pango()` with stack-based tag tracking handles malformed markup |
| GLib timer leaks (typing bubbles) | `clear_typing()` always calls `GLib.source_remove()`. Handler `stop()` cleans up all timers. |
| Pygments not installed | `syntax_highlight.py` catches `ImportError`, falls back to plain text |
| Large messages (100KB+ agent output) | `extract_blocks()` processes in one pass. Labels use `set_wrap(True)`. No buffer accumulation. |
| Streaming delta events out of order | `end_streaming()` is idempotent. Missing `start_streaming()` → render normally. |
| CSS conflicts with existing styles | All bubble CSS classes are namespaced (`.bubble-*`, `.code-block*`, `.blockquote*`) |

---

## What We're NOT Porting

These deadcode features are deliberately excluded:

1. **Approval cards** — complex UI with approve/deny buttons, requires gateway approval protocol integration. Future work.
2. **Forward menu** — requires agent picker popover that doesn't exist yet. Stub only in Phase 5.
3. **File lock integration** — deadcode's `FileTreePanel` has lock management. Not a formatting feature.
4. **Feed-specific rendering** — deadcode's `feed.py` (737 lines) is a separate subsystem. May be ported later but not part of chat formatting.
5. **Toast notifications** — already have a deadcode `widgets.py` implementation but not a formatting concern.

These can be future porting plans if needed.
