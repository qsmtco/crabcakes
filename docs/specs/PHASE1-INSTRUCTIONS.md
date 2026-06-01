# Phase 1 Instructions — ARCHITECTURE.md Update

You are updating ARCHITECTURE.md to reflect all changes from the extraction refactor and audit fixes (Phases 2-7).

## File to Change
- docs/ARCHITECTURE.md — ONLY file

## Rules
- Use the steelFramedCodeWriter prompt at prompts/steelFramedCodeWriter.md
- Do NOT change any code files
- Read every section that needs updating FIRST, then make targeted edits

## Changes Required

### 1. Section 2 — Directory Structure tree

**models/__init__.py** line: Update exports comment to include all 28 symbols:
```
__init__.py  # Exports: AgentManager, AgentRoutingTable, Command, CommandResult, CommandRegistry,
             #   StreamingBubble, FeedCardData, ActivityBubble, ToolStatus, Conversation, Message,
             #   MessageRole, ToolCall, ToolCallStatus, ConversationSnapshot, SnapshotMessage,
             #   ReviewState, TeamMember, ProjectTeam, Task, TaskStore, TASK_STATUS_LABELS,
             #   PRIORITY_LABELS, next_agent_color, reset_color_indices
```

**agent/__init__.py** line: Update exports comment to include all symbols:
```
__init__.py  # Exports: AgentRuntime, LLMProviderConfig, EnforcementConfig, AgentConfig,
             #   load_agent_config, get_api_key, SpecialAgentDef, SPECIAL_AGENTS,
             #   get_special_agents, reload_registry, ToolDefinition, ToolResult,
             #   build_system_prompt, build_file_context, check
```

### 2. Section 3.6 — window.py

Update the description. The "callback handlers not yet extracted" list should NOT include:
- `_on_audit_report_card` (now in FeedHandler)
- `_on_agent_saved` (now handled by AgentRuntimeHandler.reload_agents_and_mcp)
- `_on_agent_deleted` (now handled by AgentRuntimeHandler.reload_agents_and_mcp)
- `_confirm_delete_agent` (now in AgentBuilderHandler.delete_agent_with_confirmation)
- `_register_stub_commands` (now auto-registered in CommandHandler.__init__)

Update the line count from "~1026 lines" to "~833 lines".

### 3. Section 10 — Environment Variables

Update STT_MODEL_SIZE entry from "reserved, not yet implemented" to implemented:
```
| STT_MODEL_SIZE | "tiny.en" | faster-whisper model size: "tiny.en", "base.en", "small.en", etc. | No |
```

### 4. Section 12 — File Inventory

Update these line counts:
- `ui/window.py` from "~1026 lines" to "~833 lines"
- `models/__init__.py` update exports comment
- `agent/__init__.py` update exports comment
- `utils/stt.py` description: change "model hardcoded to tiny.en" to "model from STT_MODEL_SIZE env var (default tiny.en)"

### 5. Section 3 — Module Responsibilities

Add/update public API entries for new handler methods where they're documented:

**FeedHandler** (wherever it's documented): Add:
```python
def add_audit_report_card(report, project_name=None) -> str  # render audit report as feed card
```

**AgentRuntimeHandler** (wherever it's documented): Add:
```python
def reload_agents_and_mcp(on_complete=None) -> None  # reload agent defs + MCP servers, callback on done
```

**AgentBuilderHandler** (wherever it's documented): Add:
```python
def delete_agent_with_confirmation(name) -> None  # GTK4 confirmation dialog then delete
```

**CommandHandler** constructor: Update to include new params:
```python
CommandHandler(gateway_client, agent_manager, project_handler, GLib_module,
               on_display_card, on_display_text,
               collab_handler, task_handler, review_handler, session_handler)
```

### 6. Verify file existence

Run: `find . -name "*.py" -path "./models/*" -o -path "./agent/*" -o -path "./ui/*" | sort`
Compare against Section 2 directory tree. Any file that exists but isn't listed should be added. Any file listed that doesn't exist should be removed.

## Verification

```bash
# Every .py file listed in the directory tree actually exists
grep -oP '[a-z_/]+\.py' docs/ARCHITECTURE.md | sort -u | while read f; do
  [ -f "$f" ] || echo "MISSING: $f"
done

# Line counts match
wc -l ui/window.py

# No extracted methods still listed as window.py methods
grep -c '_on_audit_report_card\|_register_stub_commands' docs/ARCHITECTURE.md
```

## COMPLETENESS checklist at end
