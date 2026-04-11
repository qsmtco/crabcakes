# File Edit Tool

Edit existing files by replacing a specific section of text with new content.

## How to Use

Identify the smallest unique section of text to replace. Use 2-4 adjacent lines that clearly distinguish the target from surrounding code.

**Find unique context.** If the target appears in multiple places, include enough surrounding lines to make your edit unique.

**Avoid over-matching.** Don't include 10+ lines of context when less uniquely identifies the target.

## Before Editing

**Always read the file first.** You must understand the existing code before modifying it.

**Understand the structure.** Know how the code fits together before making changes.

## Making Edits

1. Identify the exact text to replace
2. Provide the replacement
3. Verify the edit produces the intended result

## Best Practices

**Small, targeted edits.** Change exactly what's needed. Don't refactor surrounding code unless it directly relates to your task.

**Preserve formatting.** Match the existing code style, indentation, and structure.

**Test after editing.** Run tests, linters, or verification steps to confirm the edit works.

## Common Mistakes

**Editing the wrong location** because the target text wasn't unique enough.

**Overwriting unrelated code** because too much context was included.

**Forgetting to read first** and making incorrect assumptions about the code.
