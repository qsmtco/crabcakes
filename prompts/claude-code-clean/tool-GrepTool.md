# Content Search Tool

Search for text patterns within files using ripgrep.

## How to Use

Search for specific text patterns across files:
- Keywords
- Code patterns
- Function names
- Variable references
- Any text you need to locate

## Best Practices

**Use for content search.** Find where specific text appears in the codebase.

**Use glob search for filenames.** Use the glob tool to find files by pattern, then grep to find content within them.

**Be specific.** More specific patterns return more useful results.

**Consider context.** Include enough surrounding lines to understand where matches appear.

## Common Uses

- Finding function definitions
- Locating where a variable is used
- Searching for specific strings
- Finding code patterns across files
