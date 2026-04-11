# Tool Search Tool

Search for and load deferred tool schemas. Until fetched, only the tool name is known.

## How to Use

Query for specific tools:
- `"select:Read,Edit,Grep"` — fetch these exact tools
- `"notebook jupyter"` — keyword search

Returns matched tools' complete parameter schemas.

## Best Practices

Use when you need a tool's full schema to invoke it.
