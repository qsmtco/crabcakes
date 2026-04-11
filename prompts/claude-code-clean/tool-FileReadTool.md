# File Read Tool

Read files from the local filesystem. Use this to understand existing code before modifying it or to retrieve information.

## How to Use

Provide a file path to read. The tool can handle:
- Regular text files
- Source code files
- Configuration files
- Images (returned as image data)
- PDFs (content extracted)
- Jupyter notebooks

## Best Practices

**Read before editing.** Always read a file before modifying it to understand its structure and context.

**Read relevant files first.** Don't propose changes to code you haven't read.

**Understand the context.** Consider how the file fits into the larger project before making changes.

## Tips

**Large files:** You can read specific sections using offset and limit parameters.

**Binary files:** Images are returned as image data; other binaries return metadata only.

**Encoding issues:** If a file fails to read, the error will indicate the problem.
