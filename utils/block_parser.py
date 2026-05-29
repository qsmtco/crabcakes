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
        seg = _classify_paragraph(stripped)
        if seg:
            segments.append(seg)

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
            seg = _classify_paragraph(para)
            if seg:
                segments.append(seg)
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


def _classify_paragraph(para: str) -> dict | None:
    """
    Classify a paragraph (non-empty, no blank lines) into a block type.
    Returns a segment dict, or None if the paragraph is empty.
    """
    lines = para.split('\n')
    first = lines[0].strip()

    # Heading: starts with # (1-6 levels)
    if first.startswith('#'):
        m = re.match(r'^(#{1,6})\s+(.*)', first)
        if m:
            level = len(m.group(1))
            return {"type": "heading", "content": m.group(2).strip(), "level": level}

    # Blockquote: every line starts with >
    if all(line.lstrip().startswith('>') for line in lines):
        # Strip > prefixes
        content_lines = []
        for line in lines:
            # Remove leading > and optional space
            line = re.sub(r'^>\s?', '', line)
            content_lines.append(line)
        return {"type": "quote", "content": "\n".join(content_lines).strip()}

    # Terminal: first non-empty line starts with $ (output lines may follow without $)
    non_empty = [l for l in lines if l.strip()]
    if non_empty and non_empty[0].lstrip().startswith('$'):
        # Strip $ from command lines; preserve output lines as-is
        content_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('$'):
                content_lines.append(stripped[1:].lstrip())
            else:
                content_lines.append(stripped)
        return {"type": "terminal", "content": "\n".join(content_lines).strip()}

    # Task list: lines starting with - [ ] or - [x]
    if all(re.match(r'^\s*-\s*\[[ xX]\]\s+', l) for l in lines):
        items = []
        for line in lines:
            m = re.match(r'^\s*-\s*\[([ xX])\]\s+(.*)', line)
            if m:
                checked = m.group(1).lower() == 'x'
                items.append({"content": m.group(2).strip(), "checked": checked})
        # Merge consecutive task items into one segment
        content = "\n".join(
            f"[{'x' if item['checked'] else ' '}] {item['content']}"
            for item in items
        )
        return {"type": "task", "content": content}

    # Markdown table: at least 2 lines, first has pipes, second is separator
    if '|' in first and _is_markdown_table(lines):
        return _parse_table(lines)

    # Plain text
    return {"type": "text", "content": para}
