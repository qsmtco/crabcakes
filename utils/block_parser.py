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
    Classify a paragraph into one or more block segments.

    A paragraph is text between blank lines (no internal blank lines).
    If the first line(s) match a block type (heading, quote, task, terminal),
    extract them as a typed segment, then recursively classify the remaining
    lines. This prevents data loss when a heading is followed by body text
    without a blank-line separator.

    Returns:
        List of segment dicts (always non-empty for non-empty input).
        Empty input returns [{"type": "text", "content": ""}].
    """
    lines = para.split('\n')
    first = lines[0].strip()

    # Heading: starts with # (1-6 levels)
    if first.startswith('#'):
        m = re.match(r'^(#{1,6})(?!#)(.*)$', first)
        if m:
            level = len(m.group(1))
            rest = m.group(2)
            if rest.startswith(' ') or rest.startswith('\t'):
                content = rest[1:]
            else:
                content = rest
            heading_seg = {"type": "heading", "content": content.strip(), "level": level}
            # Recursively classify remaining lines (the body after the heading)
            remaining = '\n'.join(lines[1:]).strip()
            if remaining:
                return [heading_seg] + _classify_paragraph(remaining)
            return [heading_seg]

    # Blockquote: extract contiguous run of lines starting with >
    quote_lines: list[str] = []
    i = 0
    while i < len(lines) and lines[i].lstrip().startswith('>'):
        quote_lines.append(lines[i])
        i += 1
    if quote_lines:
        # Strip > prefixes
        content_lines = []
        for line in quote_lines:
            line = re.sub(r'^>\s?', '', line)
            content_lines.append(line)
        quote_seg = {"type": "quote", "content": "\n".join(content_lines).strip()}
        remaining = '\n'.join(lines[i:]).strip()
        if remaining:
            return [quote_seg] + _classify_paragraph(remaining)
        return [quote_seg]

    # Terminal: first non-empty line starts with $ (output lines may follow without $)
    non_empty = [l for l in lines if l.strip()]
    if non_empty and non_empty[0].lstrip().startswith('$'):
        # Terminal absorbs ALL lines (command + output) — no trailing content to split
        content_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('$'):
                content_lines.append(stripped[1:].lstrip())
            else:
                content_lines.append(stripped)
        return [{"type": "terminal", "content": "\n".join(content_lines).strip()}]

    # Task list: extract contiguous run of task lines
    task_line_re = re.compile(r'^\s*-\s*\[[ xX]\]\s+')
    task_lines: list[str] = []
    i = 0
    while i < len(lines) and task_line_re.match(lines[i]):
        task_lines.append(lines[i])
        i += 1
    if task_lines:
        items = []
        for line in task_lines:
            m = re.match(r'^\s*-\s*\[([ xX])\]\s+(.*)', line)
            if m:
                checked = m.group(1).lower() == 'x'
                items.append({"content": m.group(2).strip(), "checked": checked})
        content = "\n".join(
            f"[{'x' if item['checked'] else ' '}] {item['content']}"
            for item in items
        )
        task_seg = {"type": "task", "content": content}
        remaining = '\n'.join(lines[i:]).strip()
        if remaining:
            return [task_seg] + _classify_paragraph(remaining)
        return [task_seg]

    # Markdown table: at least 2 lines, first has pipes, second is separator
    if '|' in first and _is_markdown_table(lines):
        return [_parse_table(lines)]

    # Plain text — entire paragraph is one text segment
    return [{"type": "text", "content": para}]
