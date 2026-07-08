# utils/block_parser.py
# Block segment extraction — Phase 2 of Chat Formatting Port.
#
# Security: No secrets, no file I/O, no network calls.
# Pure Python, no GTK imports.
#
# Splits raw message text into typed segments for block-level rendering.
# This is a standalone utility — does NOT handle inline markdown (that's
# utils/markdown.py). This module only does block-level segmentation.
#
# Segments produced:
#   {"type": "text",    "content": "..."}
#   {"type": "code",    "content": "...", "lang": "python"}
#   {"type": "quote",   "content": "..."}
#   {"type": "terminal","content": "..."}
#   {"type": "heading", "content": "...", "level": 2}
#   {"type": "task",    "content": "...", "checked": True}
#   {"type": "table",   "headers": [...], "rows": [[...], ...]}
#
# Order of operations:
#   1. Extract fenced code blocks first ( ``` lang  ...  ``` )
#   2. Split remaining text on blank lines
#   3. Classify each paragraph into block types
#
# Public API:
#   extract_blocks(text) -> list[dict]

import re


def extract_blocks(text: str) -> list[dict]:
    """
    Split raw message text into typed block segments.

    Args:
        text: Raw message text (may contain markdown, code blocks, etc.)

    Returns:
        List of segment dicts in the order they appear in the text.
        Empty text returns [{"type": "text", "content": ""}].

    Processing order:
      1. Extract all fenced code blocks first ( ``` ... ``` )
      2. Split remaining text on blank lines
      3. Classify each non-empty paragraph:
         - Lines starting with # → heading
         - Lines starting with > → quote
         - Lines starting with $ → terminal
         - Lines starting with - [ ] or - [x] → task
         - All other paragraphs → text
    """
    if not text:
        return [{"type": "text", "content": ""}]

    # Step 1: Extract fenced code blocks
    segments, remaining = _extract_fenced_code_blocks(text)

    # Step 2: Split remaining text on blank lines
    paragraphs = re.split(r'\n\s*\n', remaining)

    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        segs = _classify_paragraph(stripped)
        segments.extend(segs)

    return segments if segments else [{"type": "text", "content": ""}]


def _extract_fenced_code_blocks(text: str) -> tuple[list[dict], str]:
    """
    Extract all fenced code blocks from text.
    Returns (code_segments, remaining_text).
    """
    segments: list[dict] = []
    # Match ``` optionally followed by a language tag
    # Captures: (fence_start, lang, content, fence_end)
    fence_re = re.compile(
        r'(```(\w*)\n)(.*?)(```)',
        re.DOTALL
    )

    last_end = 0
    for m in fence_re.finditer(text):
        # Everything before this code block gets classified and appended
        before = text[last_end:m.start()]
        for para in re.split(r'\n\s*\n', before):
            para = para.strip()
            if not para:
                continue
            segs = _classify_paragraph(para)
            segments.extend(segs)
        last_end = m.end()
        lang = m.group(2) or ""
        content = m.group(3)
        segments.append({"type": "code", "content": content.rstrip("\n"), "lang": lang})

    remaining = text[last_end:]
    return segments, remaining


# ── Table detection regexes ──────────────────────────────────────────────────

# A separator row must have at least one dash per cell (with optional colons)
_TABLE_SEP_CELL_RE = re.compile(r'^\s*:?-+:?\s*$')


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


def _classify_paragraph(para: str) -> list[dict]:
    """
    Classify a paragraph into one or more block segments using an iterative
    left-to-right line scanner.

    Walks through lines, accumulating plain-text lines into a buffer. When a
    line starting a block type (heading, quote, task, terminal) is found, the
    text buffer is flushed as a text segment, then the block-type line(s) are
    classified. This prevents data loss when a heading is followed by body
    text without a blank-line separator, and handles interleaved block types
    (e.g. heading + body + heading) within a single paragraph.

    Returns:
        List of segment dicts (always non-empty for non-empty input).
        Empty input returns [{"type": "text", "content": ""}].
    """
    lines = para.split('\n')
    segments: list[dict] = []
    text_buf: list[str] = []

    def flush_text():
        """Flush accumulated plain-text lines as a text segment."""
        if text_buf:
            segments.append({"type": "text", "content": "\n".join(text_buf)})
            text_buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Heading: starts with # (1-6 levels)
        if stripped.startswith('#'):
            m = re.match(r'^(#{1,6})(?!#)(.*)$', stripped)
            if m:
                flush_text()
                level = len(m.group(1))
                rest = m.group(2)
                if rest.startswith(' ') or rest.startswith('\t'):
                    content = rest[1:]
                else:
                    content = rest
                segments.append({"type": "heading", "content": content.strip(), "level": level})
                i += 1
                continue

        # Blockquote: line starts with > (collect contiguous run)
        if stripped.startswith('>'):
            flush_text()
            quote_lines = []
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                quote_lines.append(lines[i])
                i += 1
            content_lines = []
            for ql in quote_lines:
                ql = re.sub(r'^>\s?', '', ql)
                content_lines.append(ql)
            segments.append({"type": "quote", "content": "\n".join(content_lines).strip()})
            continue

        # Terminal: first non-empty line starts with $ (absorbs all remaining lines)
        if stripped and stripped.startswith('$') and not text_buf:
            content_lines = []
            while i < len(lines):
                s = lines[i].strip()
                if s.startswith('$'):
                    content_lines.append(s[1:].lstrip())
                else:
                    content_lines.append(s)
                i += 1
            segments.append({"type": "terminal", "content": "\n".join(content_lines).strip()})
            continue

        # Task list: line starts with - [ ] or - [x] (collect contiguous run)
        if re.match(r'^\s*-\s*\[[ xX]\]\s+', line):
            flush_text()
            task_lines = []
            while i < len(lines) and re.match(r'^\s*-\s*\[[ xX]\]\s+', lines[i]):
                task_lines.append(lines[i])
                i += 1
            items = []
            for tl in task_lines:
                m = re.match(r'^\s*-\s*\[([ xX])\]\s+(.*)', tl)
                if m:
                    checked = m.group(1).lower() == 'x'
                    items.append({"content": m.group(2).strip(), "checked": checked})
            content = "\n".join(
                f"[{'x' if item['checked'] else ' '}] {item['content']}"
                for item in items
            )
            segments.append({"type": "task", "content": content})
            continue

        # Markdown table: requires first line with | and second line separator.
        # Only check if we're at the start of a potential table (text_buf is empty
        # or about to be flushed) and there are at least 2 lines remaining.
        if '|' in stripped and not text_buf and i + 1 < len(lines):
            remaining_lines = lines[i:]
            if _is_markdown_table(remaining_lines):
                flush_text()
                # Count how many lines belong to the table (until a non-table line
                # or a line without |). For simplicity, consume all remaining lines
                # that contain |, plus the separator.
                table_lines = [remaining_lines[0], remaining_lines[1]]
                j = 2
                while j < len(remaining_lines) and '|' in remaining_lines[j]:
                    table_lines.append(remaining_lines[j])
                    j += 1
                segments.append(_parse_table(table_lines))
                i += j
                continue

        # Not a block-type line — accumulate as plain text
        text_buf.append(line)
        i += 1

    # Flush any remaining text
    flush_text()

    return segments
