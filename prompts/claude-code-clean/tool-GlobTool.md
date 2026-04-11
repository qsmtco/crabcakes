# Glob File Search Tool

Find files by name patterns using glob matching.

## How to Use

Use glob patterns to match files:
- `**/*.js` — all JavaScript files recursively
- `src/**/*.ts` — TypeScript files in src directory
- `*.json` — JSON files in current directory
- `**/test*` — files starting with "test" anywhere

## Best Practices

**Match by pattern.** Use when you know the file name or extension but not the exact location.

**Combine with read.** After finding files, read the ones you need to understand their content.

**For open-ended searches** that may require multiple rounds of globbing and grepping, consider using a sub-agent instead.

## Common Uses

- Finding all files of a certain type
- Locating test files
- Finding configuration files
- Finding files in specific directories
