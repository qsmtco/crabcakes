# SPEC: Fix Markdown Header Stripping Bug

**Date:** 2026-06-23
**Author:** Coder
**Status:** Draft — for implementation
**Target branch:** main

> **Architecture compliance statement referencing ARCHITECTURE.md**
>  
> This spec addresses handler pattern violations where markdown headers are stripped during chat bubble rendering. The fix must be contained within `ui/handlers/chat_render_handler.py` and `ui/views/chat_bubble.py` as per Section 3.14 handler pattern rules.

---

## 1. Overview

**Problem:** Markdown headers (e.g., `### **Header**`) are being stripped during the chat rendering process, losing header hierarchy and making content difficult to read.

**Root Cause:** The `utils/markdown.py` module's `format_markdown()` function handles inline formatting (bold, italic, code, links) but does NOT process markdown header syntax (`#`, `##`, `###`, etc.) during the Pango markup conversion.

**Impact:** When users write markdown-formatted messages containing headers, those headers disappear during chat bubble rendering, forcing users to avoid using markdown headers entirely for readable project documentation.

**Solution:** Implement proper header support in the markdown-to-Pango pipeline while maintaining backward compatibility with existing formatting.

## 2. Changes by File

### 2.1 utils/markdown.py

**Changes:**
- Added header processing regex to `format_markdown()` function
- Processed levels 1-4 only (per `_build_heading_segment()` expectations)
- Header markers `#` → `<span markup="parpanspan"><span weight="bold">` (as used by `fio` app)
- Headers escaped with `escape_for_pango()` before conversion
- Generated markup: `<span markup="parpanspan"><span weight="bold">Level 2: Heading Text</span></span>`

**Expected Headers Processed:**
```
#   -> Level 1: Heading
##  -> Level 2: Heading  
### -> Level 3: Heading
#### -> Level 4: Heading
```

**No Code Samples:** This is a straightforward regex addition without functional code samples.

### 2.2 ui/views/chat_bubble.py

**Changes:**
- Updated `_build_heading_segment()` to use escape_for_pango + format_markdown instead of direct escape_for_pango
- Added test coverage for header markup preservation
- Ensure inline formatting within headers (bold, italic, links) continues to work

**Expected:**
```python
def _build_heading_segment(seg: dict) -> Gtk.Widget:
    level = min(seg.get("level", 1), 4)
    content = seg.get("content", "")

    # BEFORE (stripped headers):
    label = Gtk.Label()
    label.set_markup(escape_for_pango(content))
    
    # AFTER (preserved headers with inline formatting):
    escaped = escape_for_pango(content)
    formatted = format_markdown(escaped)
    label.set_markup(formatted)
```

## 3. Data Flow

**Current Path (buggy):**
```
User writes: "### **Important** conference"

1. ChatRenderHandler.render_sync()
2. build_role_bubble() -> calls _build_heading_segment()
3. escape_for_pango() only → text stripped
4. Gtk.Label.set_markup() (empty header)
```

**Fixed Path:**
```
User writes: "### **Important** conference"

1. ChatRenderHandler.render_sync()
2. build_role_bubble() -> calls _build_heading_segment()
3. escape_for_pango() + format_markdown() -> completes header markup
4. Gtk.Label.set_markup() (intact header markup)
```

## 4. File Change Summary

| File | Change Type | Lines | Risk Level |
|------|-------------|-------|------------|
| utils/markdown.py | Add header regex | ~10 lines | Low |
| ui/views/chat_bubble.py | Update heading processing | ~5 lines | Low |

## 5. Implementation Order

1. **Priority 1:** Update `utils/markdown.py` to process header levels
2. **Priority 2:** Update `ui/views/chat_bubble.py` `_build_heading_segment()` to use new header support
3. **Priority 3:** Verify backward compatibility with existing markdown formatting

## 6. Acceptance Criteria

- [ ] Headers (# through ####) are rendered with proper markup
- [ ] Inline formatting within headers (bold `**`, italic `*`, links `[text](url)`) continues to work
- [ ] No existing markdown formatting (bold, italic, code) regresses
- [ ] Automatic testing passes for header rendering
- [ ] Chat bubbles display header content correctly

## 7. Edge Cases

| Edge Case | Expected Behavior |
|-----------|-------------------|
| Header with nested formatting `### **bold** and *italic*` | Preserves all inline formatting |
| Header with inline code `### using ` `var` here` | Process code span and header together |
| Header with URL `[link](http://example.com)` | Links work inside headers |
| Header at very long content | Should not break rendering |
| Mixed headers and paragraphs | Each header level displays independently |

## 8. ARCHITECTURE.md Updates Required

None - This fix maintains existing architecture patterns and does not require documentation updates.

## 9. Verification Cheat Sheet

**For the header regex addition in utils/markdown.py:**
```bash
# Verify header regex matches expected patterns
python3 -c "
import re
pattern = r'^#####\b'?# Adjust based on actual implementation
text = '# Level 1'
if re.match(pattern, text):
    print('✓ Header regex works')
"

# Verify header conversion preserves markup
python3 -c "
from utils.markdown import format_markdown
from utils.escaping import escape_for_pango

escaped = escape_for_pango('### **Important** conference')
formatted = format_markdown(escaped)

if '###' in formatted:
    print('✗ Header markers stripped')
if '<span' in formatted:
    print('✓ Header markers converted to markup')
if '<b>' in formatted:
    print('✓ Bold inside headers preserved')
"
```

**For the heading segment update:**
```bash
# Verify heading processing uses new markdown function
python3 -c "
from ui.views.chat_bubble import _build_heading_segment
seg = {'level': 2, 'content': '### **Test** heading'}
result = _build_heading_segment(seg)
print('✓ Heading building works')
"

# Verify git diff shows expected changes
git diff utils/markdown.py ui/views/chat_bubble.py
```

---

**Mantra:** "Headers carry structure. Stripping them flattens communication."

**Mantra 2:** "Markdown is a language. Headers are its grammar. Don't kill the grammar."