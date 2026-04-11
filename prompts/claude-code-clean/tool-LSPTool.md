# LSP Tool

Interact with Language Server Protocol (LSP) servers for code intelligence features.

## Supported Operations

- **goToDefinition**: Find where a symbol is defined
- **findReferences**: Find all references to a symbol
- **hover**: Get documentation and type info for a symbol
- **documentSymbol**: Get all symbols in a document
- **workspaceSymbol**: Search for symbols across the workspace
- **goToImplementation**: Find implementations of an interface or method
- **callHierarchy**: Get call hierarchy (incoming/outgoing calls)

## Requirements

- filePath: The file to operate on
- line: Line number (1-based)
- character: Character offset (1-based)

## Best Practices

LSP servers must be configured for the file type. If no server is available, an error will be returned.
