# Crabcakes Formatting Guide

> **Status: ACTIVE REFERENCE** — Formatting pipeline (`extract_blocks()` → `escape_for_pango()` → `format_markdown()`) still works this way as of 2026-05-09.

All inline and block-level formatting supported by the chat renderer.
**Pipeline:** `extract_blocks()` → `escape_for_pango()` → `format_markdown()` → Pango markup
## INLINE — Bold, Italic, Strike, Code
**Input (markdown):**
```
Use **bold** for emphasis, *italic* for nuance, and `inline code` for technical terms.
Also supports ~~strikethrough~~ for deleted content.
```
**Output blocks:**
- `text`:  `Use **bold** for emphasis, *italic* for nuance, and `inline ...`

## INLINE — Links and Auto-URLs
**Input (markdown):**
```
A markdown link: [Crabcakes docs](https://crabcakes.dev)
And a bare URL auto-detected: https://github.com/qsmtco/crabcakes
```
**Output blocks:**
- `text`:  `A markdown link: [Crabcakes docs](https://crabcakes.dev)
And...`

## INLINE — Bullet Lists
**Input (markdown):**
```
Top-level bullets are auto-converted:
- First item
- Second item
- Third item
```
**Output blocks:**
- `text`:  `Top-level bullets are auto-converted:
- First item
- Second ...`

## BLOCK — Fenced Code (Python)
**Input (markdown):**
```
```python
def greet(name: str) -> str:
    """Return a personalized greeting."""
    return f"Hello, {name}!"

print(greet("Qrusher"))
```
```
**Output blocks:**
- `code` lang=`python`:  `def greet(name: str) -> str:
    """Return a personalized gr...`

## BLOCK — Fenced Code (No Language)
**Input (markdown):**
```
```
This is a generic code block with no language tag.
Tabs and spaces are preserved.
```
```
**Output blocks:**
- `code`:  `This is a generic code block with no language tag.
Tabs and ...`

## BLOCK — Shell Terminal
**Input (markdown):**
```
$ echo "Hello from the terminal"
This is the command output
$ python3 --version
Python 3.12.3
```
**Output blocks:**
- `terminal`:  `echo "Hello from the terminal"
This is the command output
py...`

## BLOCK — Blockquote
**Input (markdown):**
```
> This is a blockquote.
> It preserves line breaks and renders
> with a distinct visual style.
```
**Output blocks:**
- `quote`:  `This is a blockquote.
It preserves line breaks and renders
w...`

## BLOCK — Heading (H2)
**Input (markdown):**
```
## Project Architecture

The architecture follows a layered pattern with clear separation of concerns.
```
**Output blocks:**
- `heading` level=2:  `Project Architecture`
- `text`:  `The architecture follows a layered pattern with clear separa...`

## BLOCK — Heading (H3)
**Input (markdown):**
```
### Phase 3: Handler Extraction

Each handler owns one domain and communicates via typed callbacks.
```
**Output blocks:**
- `heading` level=3:  `Phase 3: Handler Extraction`
- `text`:  `Each handler owns one domain and communicates via typed call...`

## BLOCK — Task List
**Input (markdown):**
```
- [ ] Review the gateway protocol
- [x] Implement WebSocket client
- [ ] Add connection state tracking
- [ ] Write integration tests
```
**Output blocks:**
- `task`:  `[ ] Review the gateway protocol
[x] Implement WebSocket clie...`

## MIXED — Code + Text
**Input (markdown):**
```
Here is a working example:

```python
from models import StreamingBubble

sb = StreamingBubble(container=c, label=l, role="Agent")
sb.plain_text = "partial response"
```

And some **bold** text after the code block.
```
**Output blocks:**
- `text`:  `Here is a working example:`
- `code` lang=`python`:  `from models import StreamingBubble

sb = StreamingBubble(con...`
- `text`:  `And some **bold** text after the code block.`

## MIXED — Multiple Blocks
**Input (markdown):**
```
## Overview

Here's the plan:

- [x] Create dataclass
- [x] Export from models
- [ ] Update all unpack sites

```python
@dataclass
class StreamingBubble:
    container: object
    label: object
```

> Note: Always run tests after refactoring.
```
**Output blocks:**
- `heading` level=2:  `Overview`
- `text`:  `Here's the plan:`
- `task`:  `[x] Create dataclass
[x] Export from models
[ ] Update all u...`
- `code` lang=`python`:  `@dataclass
class StreamingBubble:
    container: object
    ...`
- `quote`:  `Note: Always run tests after refactoring.`

## EDGE — Empty Lines in Code Blocks
**Input (markdown):**
```
```python
def example():

    # Two blank lines inside function
    pass

print(example())
```
```
**Output blocks:**
- `code` lang=`python`:  `def example():

    # Two blank lines inside function
    pa...`

## EDGE — Nested Code in Quote
**Input (markdown):**
```
> Use `inline code` in a quote like this:
> ```
> echo "hello"
> ```
```
**Output blocks:**
- `quote`:  `Use `inline code` in a quote like this:`
- `code`:  `> echo "hello"
> `

