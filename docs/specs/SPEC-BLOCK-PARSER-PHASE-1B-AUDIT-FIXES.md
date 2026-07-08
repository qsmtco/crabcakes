# PHASE 1b (Audit Fixes) — Iterative Rewrite of _classify_paragraph

**Spec:** `docs/specs/spec-block-parser-mixed-content.md` (audit follow-up)
**Files to change:** `utils/block_parser.py`, `tests/test_block_parser.py` (additions)

These are 2 fixes from the Debugger's adversarial audit of the block parser mixed-content fix. Both share the same root cause and the same fix.

---

## FIX 1 — Replace recursion with iterative left-to-right loop (BUG #1 + #2)

**File:** `utils/block_parser.py`

**Problem:** The current `_classify_paragraph` (lines 191-285) uses recursion to classify trailing lines after a heading/quote/task match. This has two bugs:

1. **BUG #1 (CRITICAL):** `## h1\nbody\n## h2` produces `[heading(h1), text("body\n## h2")]`. The recursive call on `"body\n## h2"` treats the entire remainder as text because "body" (the first line) doesn't match any block type. The second heading becomes literal text — format degradation.

2. **BUG #2 (MEDIUM):** Alternating heading+body pairs (`## h1\nbody\n## h2\nbody\n...`) cause O(N) recursion depth. With 500+ pairs, Python hits its 1000-frame recursion limit.

**Root cause:** The recursion only looks at the FIRST line of the remainder to decide classification. Once the first line is plain text, the entire remainder becomes one text segment — even if later lines contain headings, quotes, or tasks.

**Fix:** Replace the recursive approach with an iterative left-to-right line scanner. The scanner walks through `lines`, accumulating plain-text lines into a buffer. When it encounters a line that starts a block type (heading, quote, task), it flushes the text buffer as a text segment, then classifies the block-type line(s). This is O(N) in time and O(1) in stack depth.

**Read the full current function first** (lines 191-285) before editing. You are replacing the entire function.

**Full replacement code** (replace the entire `_classify_paragraph` function):

```python
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
        if stripped and stripped.startswith('$') and not text_buf and not segments:
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

    # If no segments were produced (all plain text), return the paragraph as text
    if not segments:
        return [{"type": "text", "content": para}]

    return segments
```

**Key changes from the current recursive approach:**

1. **No recursion.** The function is a single `while i < len(lines)` loop. Stack depth is O(1) regardless of input size. Fixes BUG #2.

2. **Left-to-right scanning.** Each line is checked against block-type patterns. If it matches, the text buffer is flushed and the block segment is emitted. If it doesn't match, it accumulates in `text_buf`. Fixes BUG #1 — `## h1\nbody\n## h2` now produces `[heading(h1), text("body"), heading(h2)]` because the scanner encounters `## h2` and classifies it as a heading rather than treating it as part of the text remainder.

3. **Terminal guard:** The terminal classifier only fires when `not text_buf and not segments` (i.e., at the very start of the paragraph). This prevents a `$` in the middle of body text from absorbing all remaining lines as terminal output.

4. **Table guard:** The table classifier only fires when `not text_buf` (no pending text) and there are at least 2 lines remaining. This is more restrictive than before but prevents a `|` in body text from triggering table parsing.

5. **`flush_text()` closure:** Accumulates plain-text lines between block-type matches, joining them with `\n`. This preserves multi-line text segments.

---

## FIX 2 — Add tests for interleaved block types (BUG #6)

**File:** `tests/test_block_parser.py`

**Append these tests** to the existing `TestMixedContentParagraphs` class (before the `TestMixedContentRegressions` class):

```python
    def test_heading_text_heading_single_paragraph(self):
        """BUG #1: ## h1\nbody\n## h2 → [heading(h1), text(body), heading(h2)].
        The second heading must NOT become literal text."""
        result = extract_blocks("## h1\nbody\n## h2")
        assert len(result) == 3, f"Expected 3 segments, got {len(result)}: {result}"
        assert result[0]["type"] == "heading"
        assert result[0]["content"] == "h1"
        assert result[1]["type"] == "text"
        assert result[1]["content"] == "body"
        assert result[2]["type"] == "heading"
        assert result[2]["content"] == "h2"

    def test_heading_then_task_then_text(self):
        """### H\n- [ ] task\nplain → [heading, task, text]."""
        result = extract_blocks("### H\n- [ ] task\nplain")
        assert len(result) == 3, f"Expected 3 segments, got {len(result)}: {result}"
        assert result[0]["type"] == "heading"
        assert result[1]["type"] == "task"
        assert "task" in result[1]["content"]
        assert result[2]["type"] == "text"
        assert result[2]["content"] == "plain"

    def test_heading_then_multi_task(self):
        """### H\n- [ ] a\n- [x] b\nplain → [heading, task(2 items), text]."""
        result = extract_blocks("### H\n- [ ] a\n- [x] b\nplain")
        assert len(result) == 3
        assert result[0]["type"] == "heading"
        assert result[1]["type"] == "task"
        assert "a" in result[1]["content"]
        assert "b" in result[1]["content"]
        assert result[2]["type"] == "text"

    def test_alternating_headings_deep(self):
        """BUG #2: 50 alternating heading+body pairs must not stack overflow."""
        parts = []
        for n in range(50):
            parts.append(f"## h{n}\nbody{n}")
        text = "\n".join(parts)
        result = extract_blocks(text)
        # Each pair produces 2 segments (heading + text)
        assert len(result) == 100, f"Expected 100 segments, got {len(result)}"
        # Spot-check: first and last heading
        assert result[0]["type"] == "heading"
        assert result[0]["content"] == "h0"
        assert result[98]["type"] == "heading"
        assert result[98]["content"] == "h49"

    def test_quote_then_text_then_quote(self):
        """> q1\nplain\n> q2 → [quote, text, quote]."""
        result = extract_blocks("> q1\nplain\n> q2")
        assert len(result) == 3
        assert result[0]["type"] == "quote"
        assert result[1]["type"] == "text"
        assert result[2]["type"] == "quote"

    def test_task_then_text_then_task(self):
        """- [ ] a\nplain\n- [x] b → [task, text, task]."""
        result = extract_blocks("- [ ] a\nplain\n- [x] b")
        assert len(result) == 3
        assert result[0]["type"] == "task"
        assert result[1]["type"] == "text"
        assert result[2]["type"] == "task"
```

---

## Rules

- Use the `steelFramedCodeWriter` prompt at `prompts/steelFramedCodeWriter.md`.
- **Read `utils/block_parser.py` in full before editing.** You are replacing the entire `_classify_paragraph` function (lines 191-285).
- Make ONLY the changes described above. Do not refactor, rename, or reformat anything else.
- Do NOT touch any other file. The call sites (lines 65-66, 92-93) already use `extend` — they do not need to change.
- The terminal classifier has a new guard: `not text_buf and not segments`. This means terminal only fires at the start of a paragraph. If a `$` appears in the middle of body text, it stays as text. This is intentional.

## Verification commands (run these, paste the output)

```bash
cd /home/q/projects/crabcakes

# 1. BUG #1 fix: interleaved heading+text+heading
python3 -c "
from utils.block_parser import extract_blocks
result = extract_blocks('## h1\nbody\n## h2')
print('Segments:', [(s['type'], s['content'][:20]) for s in result])
assert len(result) == 3, f'Expected 3, got {len(result)}'
assert result[2]['type'] == 'heading', 'Second heading lost!'
print('OK: BUG #1 fixed — interleaved headings work')
"

# 2. BUG #2 fix: deep alternation doesn't crash
python3 -c "
from utils.block_parser import extract_blocks
parts = [f'## h{n}\nbody{n}' for n in range(50)]
result = extract_blocks('\n'.join(parts))
assert len(result) == 100, f'Expected 100, got {len(result)}'
print('OK: BUG #2 fixed — 50 alternating pairs (100 segments)')
"

# 3. Full test suite (existing + new)
python3 -m pytest tests/test_block_parser.py -v

# 4. Broader regression — rendering pipeline
xvfb-run -a python3 -m pytest tests/test_block_parser.py tests/test_chat_heading.py tests/test_chat_render_handler.py tests/test_chat_terminal_segment.py tests/test_chat_task_segment.py tests/test_markdown.py -q

# 5. Pattern sweep — no recursion in _classify_paragraph
grep -n '_classify_paragraph(remaining)\|_classify_paragraph(' utils/block_parser.py
# Expected: ONLY the def line and the 2 call sites in extract_blocks/_extract_fenced_code_blocks.
# No recursive calls inside _classify_paragraph itself.
```

## Deliverables (COMPLETENESS checklist required)

When done, report:
1. Files changed with line numbers
2. Full output of all 5 verification commands above
3. `git diff utils/block_parser.py` output (the actual changes)
4. COMPLETENESS checklist:
```
COMPLETENESS:
- [x/not done] Fix 1: _classify_paragraph rewritten as iterative loop (no recursion) — evidence: (command 1+2 output)
- [x/not done] Fix 2: 6 new tests for interleaved block types — evidence: (command 3 output)
- [x/not done] Existing tests pass (no regressions) — evidence: (command 3 output)
- [x/not done] Broader regression passes — evidence: (command 4 output)
- [x/not done] No recursive calls in _classify_paragraph — evidence: (command 5 output)
```
