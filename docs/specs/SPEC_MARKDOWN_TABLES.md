---
status: DONE
---
# SPEC: Markdown Table Rendering in Chat Bubbles

**Date:** 2026-05-28
**Author:** Qaster
**Status:** Draft — for implementation
**Depends on:** None (builds on existing block_parser + chat_bubble pipeline)
**Target branch:** main

---

## 1. Overview

### Problem
When AI agents return markdown tables (e.g. `| Header | Value |`), CrabCakes renders them as raw text with pipes and dashes. Nothing lines up. Columns have no alignment. It's unreadable.

### Solution
Add a `"table"` segment type to the block parser that detects markdown pipe tables. Render tables as GTK4 `Gtk.Grid` widgets with proper columns, styled cells, alternating row backgrounds, and selectable text. This follows the same pipeline as existing block types (code, quote, terminal, heading, task).

### Approach: GTK Grid (Option 2)
Using `Gtk.Grid` gives us real columns that resize, selectable text per cell, proper borders, and native styling. This is the right approach for a native desktop app — not a monospace hack.

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| Detect markdown pipe tables in `block_parser.py` | HTML `<table>` parsing |
| New `"table"` segment type with headers + rows | Merged cells, colspan, rowspan |
| `Gtk.Grid` renderer in `chat_bubble.py` | Sortable columns, interactive headers |
| CSS styling for table cells, borders, alternating rows | Table editing |
| Header separator detection (`\|---\|`) | Column alignment indicators (`:---`, `---:`, `:---:`) |
| Inline markdown in cells (bold, italic, code, links) | Nested tables |
| Fallback: single-column table with no pipes detected | |

---

## 2. Markdown Table Format

The parser must handle standard GFM pipe tables:

```markdown
| Name  | Role    | Status |
|-------|---------|--------|
| Coder | Builder | Active |
| QTR   | Blade   | Active |
```

**Rules:**
1. At least 2 rows: header row + separator row (1+ data rows optional)
2. Separator row: cells contain only `-`, `:`, spaces (`|---|`, `|:---:|`, `|---:|`)
3. Each row starts and ends with `|` (or leading/trailing `|` is optional)
4. Column count determined by header row

**Edge cases handled:**
- Leading/trailing `|` optional
- Extra whitespace around cells
- Empty cells (`| |`)
- Inline markdown in cells (`**bold**`, `*italic*`, `` `code` ``)
- Tables with 0 data rows (just header + separator) → render header only
- Alignment indicators in separator (`:---`, `---:`, `:---:`) → detected but rendered left-aligned for now

---

## 3. Changes by File

### 3.1 `utils/block_parser.py`

**What changes:**
1. Add `_is_markdown_table()` — detect if a paragraph is a markdown table
2. Add `_parse_table()` — parse table rows into structured data
3. Add table classification in `_classify_paragraph()` before "plain text" fallback

**New segment format:**
```python
{
    "type": "table",
    "headers": ["Name", "Role", "Status"],
    "rows": [
        ["Coder", "Builder", "Active"],
        ["QTR", "Blade", "Active"],
    ],
}
```

**Code — `_is_markdown_table()`:**

```python
# Table detection regex components
_TABLE_SEP_RE = re.compile(r'^[\s|:\-]+$')
# A separator row must have at least one dash per cell
_TABLE_SEP_CELL_RE = re.compile(r'^\s*:?-+:?\s*$')

def _is_markdown_table(lines: list[str]) -> bool:
    """Check if a paragraph (list of lines) is a markdown pipe table.

    Requirements:
      - At least 2 lines (header + separator)
      - Line 1 (header) contains at least one pipe |
      - Line 2 (separator) matches |---|---| pattern
    """
    if len(lines) < 2:
        return False

    # Header row must contain at least one pipe
    if '|' not in lines[0]:
        return False

    # Separator row: must be all pipes, colons, dashes, spaces
    sep = lines[1].strip()
    if '|' not in sep:
        return False

    # Check separator cells
    cells = _split_table_row(sep)
    if not cells:
        return False

    # Every separator cell must match the --- pattern
    for cell in cells:
        if not _TABLE_SEP_CELL_RE.match(cell):
            return False

    return True
```

**Code — `_split_table_row()`:**

```python
def _split_table_row(row: str) -> list[str]:
    """Split a pipe-delimited row into cell values.

    Handles optional leading/trailing pipe.
    Returns list of stripped cell strings.
    """
    row = row.strip()
    # Strip leading and trailing pipes
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|'):
        row = row[:-1]
    # Split and strip each cell
    return [cell.strip() for cell in row.split('|')]
```

**Code — `_parse_table()`:**

```python
def _parse_table(lines: list[str]) -> dict:
    """Parse markdown table lines into a table segment dict.

    Args:
        lines: All lines of the table paragraph (header, separator, data rows)

    Returns:
        Segment dict with type='table', headers list, and rows list-of-lists.
    """
    if not lines:
        return {"type": "text", "content": ""}

    headers = _split_table_row(lines[0])
    num_cols = len(headers)

    rows = []
    # Skip header (line 0) and separator (line 1)
    for line in lines[2:]:
        cells = _split_table_row(line)
        # Pad or truncate to match header column count
        if len(cells) < num_cols:
            cells.extend([''] * (num_cols - len(cells)))
        elif len(cells) > num_cols:
            cells = cells[:num_cols]
        rows.append(cells)

    return {
        "type": "table",
        "headers": headers,
        "rows": rows,
    }
```

**Code — insertion in `_classify_paragraph()`:**

Insert **before** the `# Plain text` fallback (the last return), after the task list check:

```python
    # Markdown table: at least 2 lines, first has pipes, second is separator
    if '|' in first and _is_markdown_table(lines):
        return _parse_table(lines)

    # Plain text
    return {"type": "text", "content": para}
```

Verified insertion point: The `# Plain text` return is the last line of `_classify_paragraph()`. The table check goes right before it, after the task list block (ending around line 183 in current code).

**Line count estimate:** ~65 lines added.

**No GTK imports.** Pure Python. Follows architecture rule for `utils/`.

---

### 3.2 `ui/views/chat_bubble.py`

**What changes:**
1. Add `_build_table_segment()` — render a `{"type": "table", ...}` segment as `Gtk.Grid`
2. Wire table type in `_build_segment_widget()` router
3. Wire table type in `build_role_bubble()` main loop (for pre-processed segments)
4. Handle table in `_process_text_chunk()` to pass through structured data

**Code — `_build_table_segment()`:**

```python
def _build_table_segment(seg: dict) -> Gtk.Widget:
    """Render a markdown table as a GTK Grid with styled cells.

    Args:
        seg: Table segment with 'headers' (list[str]) and 'rows' (list[list[str]])

    Returns:
        Gtk.Box wrapping the grid with proper styling.
    """
    headers = seg.get("headers", [])
    rows = seg.get("rows", [])
    num_cols = len(headers)

    if num_cols == 0:
        return Gtk.Box()

    # Outer container
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    outer.add_css_class("table-block")

    grid = Gtk.Grid()
    grid.add_css_class("table-grid")
    grid.set_column_spacing(1)
    grid.set_row_spacing(1)

    # Header row
    for col, header_text in enumerate(headers):
        cell = _make_table_cell(header_text, is_header=True)
        grid.attach(cell, col, 0, 1, 1)

    # Data rows
    for row_idx, row_data in enumerate(rows):
        for col, cell_text in enumerate(row_data):
            is_odd = (row_idx % 2 == 1)
            cell = _make_table_cell(cell_text, is_header=False, is_odd_row=is_odd)
            grid.attach(cell, col, row_idx + 1, 1, 1)

    outer.append(grid)
    return outer
```

**Code — `_make_table_cell()`:**

```python
def _make_table_cell(text: str, is_header: bool = False, is_odd_row: bool = False) -> Gtk.Widget:
    """Create a single table cell widget.

    Supports inline markdown (bold, italic, code, links) in cell text.
    """
    label = Gtk.Label()
    # Apply inline markdown formatting (escape first, then format)
    escaped = escape_for_pango(text)
    formatted = format_markdown(escaped)
    label.set_markup(formatted)
    label.set_xalign(0)
    label.set_valign(Gtk.Align.CENTER)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_can_focus(False)
    label.set_selectable(True)

    # Styling
    if is_header:
        label.add_css_class("table-cell-header")
    else:
        label.add_css_class("table-cell")
        if is_odd_row:
            label.add_css_class("table-cell-alt")

    # Wrap in a box for padding control
    box = Gtk.Box()
    box.append(label)
    box.add_css_class("table-cell-box")
    return box
```

**Code — wire in `_build_segment_widget()`:**

Add before the final `else: return None`:

```python
    elif seg_type == "table":
        return _build_table_segment(seg)
```

Current router code (verified):
```python
def _build_segment_widget(seg: dict) -> Gtk.Widget | None:
    seg_type = seg.get("type", "text")
    if seg_type == "text":
        return _build_text_segment(seg)
    elif seg_type == "quote":
        return _build_quote_segment(seg)
    elif seg_type == "terminal":
        return _build_terminal_segment(seg)
    elif seg_type == "heading":
        return _build_heading_segment(seg)
    elif seg_type == "task":
        return _build_task_segment(seg)
    elif seg_type == "crabcard_placeholder":
        return _build_crabcard_placeholder_segment(seg)
    else:
        return None
```

Insert `elif seg_type == "table"` before `else: return None`.

**Code — wire in `build_role_bubble()` main loop:**

In the segment assembly loop (lines ~424-450), the `else` branch handles "quote, terminal, heading, task". Add table to this branch:

Current:
```python
        else:
            # quote, terminal, heading, task — use original segment builders
            seg_dict = {"type": seg_type, "content": pseg.get("content", "")}
            if "lang" in pseg:
                seg_dict["lang"] = pseg["lang"]
            if "level" in pseg:
                seg_dict["level"] = pseg["level"]
            widget = _build_segment_widget(seg_dict)
            if widget is not None:
                bubble.append(widget)
```

Change to:
```python
        else:
            # quote, terminal, heading, task, table — use segment builders
            if seg_type == "table":
                # Table has structured data (headers, rows), not just content
                seg_dict = pseg
            else:
                seg_dict = {"type": seg_type, "content": pseg.get("content", "")}
                if "lang" in pseg:
                    seg_dict["lang"] = pseg["lang"]
                if "level" in pseg:
                    seg_dict["level"] = pseg["level"]
            widget = _build_segment_widget(seg_dict)
            if widget is not None:
                bubble.append(widget)
```

**Code — handle table in `_process_text_chunk()`:**

In `_process_text_chunk()`, the `else` block handles non-text segments:

Current:
```python
            else:
                # quote, terminal, heading, task — pass through raw content
                processed.append({
                    "type": seg_type,
                    "content": seg.get("content", ""),
                    **({"lang": seg["lang"]} if "lang" in seg else {}),
                    **({"level": seg["level"]} if "level" in seg else {}),
                })
```

Change to:
```python
            else:
                # quote, terminal, heading, task — pass through raw content
                # table — pass through structured data (headers, rows)
                if seg_type == "table":
                    processed.append(seg)
                else:
                    processed.append({
                        "type": seg_type,
                        "content": seg.get("content", ""),
                        **({"lang": seg["lang"]} if "lang" in seg else {}),
                        **({"level": seg["level"]} if "level" in seg else {}),
                    })
```

**Imports:** No new imports needed. `Gtk.Grid` is already available from `gi.repository.Gtk`.

**Line count estimate:** ~70 lines added.

---

### 3.3 `ui/styles.py`

**What changes:**
Add CSS for table blocks.

**Code — add after `.task-item` styles:**

```css
/* ── Markdown table ────────────────────────────────────────────── */

.table-block {
    margin-top: 4px;
    margin-bottom: 4px;
    border-radius: 6px;
    overflow: hidden;
}

.table-grid {
    background-color: @borders;
    /* Grid spacing creates 1px border effect between cells */
}

.table-cell-box {
    padding: 6px 10px;
}

.table-cell-header {
    background-color: shade(@theme_bg_color, 0.85);
    font-weight: bold;
    color: @theme_fg_color;
}

.table-cell {
    background-color: @theme_bg_color;
    color: @theme_fg_color;
}

.table-cell-alt {
    background-color: shade(@theme_bg_color, 0.95);
}

.table-cell-box label {
    font-size: 0.9em;
}
```

**Design rationale:**
- `@borders` color as grid background creates 1px borders between cells (gap between cells shows the grid's background)
- Header row slightly darker than body
- Alternating row tint for readability
- Cell padding via `.table-cell-box`
- No hardcoded colors — uses GTK theme variables for light/dark mode compatibility

**Verified insertion point:** After `.task-item` CSS block. Search for `.task-item` in styles.py to find the location.

**Line count estimate:** ~30 lines added.

---

### 3.4 `tests/test_block_parser.py`

**What changes:**
Add tests for table detection and parsing.

**Test cases:**

```python
class TestTableDetection:
    """Test markdown table detection in block_parser."""

    def test_basic_table(self):
        """Standard 3-column table with header and 2 data rows."""
        text = "| Name | Role | Status |\n|------|------|--------|\n| Coder | Builder | Active |\n| QTR | Blade | Active |"
        segments = extract_blocks(text)
        assert len(segments) == 1
        assert segments[0]["type"] == "table"
        assert segments[0]["headers"] == ["Name", "Role", "Status"]
        assert segments[0]["rows"] == [["Coder", "Builder", "Active"], ["QTR", "Blade", "Active"]]

    def test_table_no_leading_pipes(self):
        """Table without leading/trailing pipes."""
        text = "Name | Role\n-----|------\nCoder | Builder"
        segments = extract_blocks(text)
        assert len(segments) == 1
        assert segments[0]["type"] == "table"
        assert segments[0]["headers"] == ["Name", "Role"]

    def test_table_header_only(self):
        """Table with header + separator but no data rows."""
        text = "| A | B |\n|---|---|"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "table"
        assert segments[0]["headers"] == ["A", "B"]
        assert segments[0]["rows"] == []

    def test_table_with_alignment(self):
        """Separator with alignment indicators (:---:, ---:)."""
        text = "| Left | Center | Right |\n|:-----|:------:|------:|\n| a | b | c |"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "table"

    def test_not_a_table_single_line(self):
        """Single line with pipes is NOT a table (no separator)."""
        text = "| not a table |"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "text"

    def test_not_a_table_pipe_in_text(self):
        """Text containing a pipe character is not classified as table."""
        text = "Use cmd | grep to filter"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "text"

    def test_not_a_table_separator_without_dashes(self):
        """Second line has pipes but no dashes — not a separator."""
        text = "| A | B |\n| x | y |"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "text"

    def test_table_with_empty_cells(self):
        """Table with empty cells."""
        text = "| A | B |\n|---|---|\n|  | filled |"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "table"
        assert segments[0]["rows"][0] == ["", "filled"]

    def test_table_mixed_with_text(self):
        """Table surrounded by text paragraphs."""
        text = "Before\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAfter"
        segments = extract_blocks(text)
        assert len(segments) == 3
        assert segments[0]["type"] == "text"
        assert segments[1]["type"] == "table"
        assert segments[2]["type"] == "text"

    def test_table_column_mismatch_padded(self):
        """Data row with fewer columns gets padded."""
        text = "| A | B | C |\n|---|---|---|\n| x | y |"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "table"
        assert segments[0]["rows"][0] == ["x", "y", ""]

    def test_table_column_mismatch_truncated(self):
        """Data row with more columns gets truncated."""
        text = "| A | B |\n|---|---|\n| x | y | z |"
        segments = extract_blocks(text)
        assert segments[0]["type"] == "table"
        assert segments[0]["rows"][0] == ["x", "y"]
```

**Line count estimate:** ~70 lines added.

---

## 4. Data Flow

### Agent sends table:
1. Agent message arrives with text containing `| ... | ... |` block
2. `process_segments()` → `_process_text_chunk()` → `extract_blocks()`
3. `extract_blocks()` splits on blank lines → `_classify_paragraph()` for each
4. `_classify_paragraph()` detects pipe table → `_parse_table()` → `{"type": "table", "headers": [...], "rows": [[...], ...]}`
5. `_process_text_chunk()` sees `seg_type == "table"` → passes through structured data as-is
6. `build_role_bubble()` sees `seg_type == "table"` → passes full segment to `_build_segment_widget()`
7. `_build_segment_widget()` → `_build_table_segment()` → creates `Gtk.Grid` with cells
8. `_make_table_cell()` renders each cell with inline markdown support
9. Grid appended to bubble

### Fallback — not a table:
1. If `_is_markdown_table()` returns False → falls through to `"text"` type
2. Pipes render as literal `|` characters in text (same as current behavior)

---

## 5. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `utils/block_parser.py` | Modified | ~65 | Low — pure Python, no GTK |
| `ui/views/chat_bubble.py` | Modified | ~70 | Medium — new widget type, grid layout |
| `ui/styles.py` | Modified | ~30 | Low — CSS only |
| `tests/test_block_parser.py` | Modified | ~70 | None — tests only |

**Total:** ~235 lines across 4 files.

---

## 6. Implementation Order

1. **Add table parsing to `block_parser.py`** — `_split_table_row()`, `_is_markdown_table()`, `_parse_table()`, classification in `_classify_paragraph()`
2. **Add tests to `test_block_parser.py`** — verify all detection/parsing edge cases
3. **Run tests** — all new tests pass, no regressions
4. **Add `_build_table_segment()` + `_make_table_cell()` to `chat_bubble.py`** — GTK Grid renderer
5. **Wire table type in routers** — `_build_segment_widget()`, `build_role_bubble()`, `_process_text_chunk()`
6. **Add CSS to `styles.py`** — table block styling
7. **Visual test** — run CrabCakes, send a table message, verify rendering
8. **Commit and push**

**Verification at each step:**
1. `python3 -c "from utils.block_parser import extract_blocks; print(extract_blocks('| A | B |\\n|---|---|\\n| 1 | 2 |'))"` → shows table segment
2. `python3 -m pytest tests/test_block_parser.py -q` → all tests pass
3. Visual: table renders with aligned columns, header bold, alternating rows

---

## 7. Acceptance Criteria

- [ ] Markdown pipe tables detected and parsed into `{"type": "table", ...}` segments
- [ ] Tables render as GTK Grid with proper column alignment
- [ ] Header row visually distinct (bold, darker background)
- [ ] Alternating row colors for readability
- [ ] Cell text supports inline markdown (bold, italic, code, links)
- [ ] Empty cells render correctly
- [ ] Column count mismatch handled (pad/truncate)
- [ ] Tables surrounded by text render correctly (3 segments: text, table, text)
- [ ] Non-table pipe usage NOT misidentified as table
- [ ] Single-line pipe text NOT classified as table
- [ ] Header-only tables (no data rows) render correctly
- [ ] Table styling respects dark/light theme (uses GTK theme variables)
- [ ] All new tests pass
- [ ] No regressions in existing tests
- [ ] No GTK imports in `block_parser.py` (architecture rule)

---

## 8. ARCHITECTURE.md Updates Required

- Section 3.14g (`block_parser.py`): Add `table` to segment types table
- Section 3.14g (chat_bubble.py Phase 2+): Add table to rendering pipeline description
- File tree section: note new table rendering capability

---

## 9. Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `_classify_paragraph()` insertion point verified: after task list check, before `# Plain text` return
   - `_build_segment_widget()` router verified: 7-way if/elif chain ending with `else: return None`
   - `build_role_bubble()` main loop verified: `else` branch at line ~442 handles non-text/non-code types
   - `_process_text_chunk()` verified: `else` branch at line ~154 passes through non-text segments
   - CSS insertion point: after `.task-item` in styles.py
   - `Gtk.Grid.attach()` signature: `(widget, col, row, width, height)` — verified against GTK4 docs
   - `escape_for_pango()` + `format_markdown()` already imported in chat_bubble.py

2. **Did I catch all exception types?**
   - `_parse_table()`: no exceptions possible — pure string splitting
   - `_build_table_segment()`: no exceptions — safe dict access with `.get()`
   - `_make_table_cell()`: `escape_for_pango()` + `format_markdown()` are safe for any string input
   - No new exception paths introduced

3. **Did I verify key structures?**
   - Table segment: `{"type": "table", "headers": list[str], "rows": list[list[str]]}` — simple, flat
   - `_split_table_row()` always returns `list[str]` — verified with edge cases
   - Grid coordinates: `col` from 0 to num_cols-1, `row` from 0 (header) to len(rows)

4. **Did I trace the data flow end-to-end?**
   - Message text → `extract_blocks()` → `_classify_paragraph()` → `_is_markdown_table()` → `_parse_table()` → segment → `_process_text_chunk()` (pass-through) → `build_role_bubble()` → `_build_segment_widget()` → `_build_table_segment()` → `Gtk.Grid`. Full path traced.

5. **Would an implementer produce working code?**
   - Yes. All functions specified with exact logic, insertion points verified, edge cases enumerated.

6. **Architecture compliance verified?**
   - `block_parser.py`: no GTK imports ✓ (pure Python utility)
   - `chat_bubble.py`: GTK widget construction ✓ (view layer)
   - `styles.py`: CSS only ✓ (styling layer)
   - No business logic in views ✓
   - No cross-layer violations ✓
