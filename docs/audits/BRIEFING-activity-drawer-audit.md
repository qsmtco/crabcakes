# Debugger Briefing — Activity Drawer Offline + Local-Agent Events

## What changed (the code under audit)

A new handler `ui/handlers/activity_wiring_handler.py` was created to own ALL activity→drawer event routing (previously gated behind gateway-connect inside `connection_sync_handler.sync()`). Local-agent tool/lifecycle events now emit `ActivityBubble` objects to the drawer.

**Changed files:**
1. `ui/handlers/activity_wiring_handler.py` — NEW. Owns gateway + local → drawer wiring. `.wire()` called unconditionally at startup.
2. `ui/handlers/agent_runtime_handler.py` — Added 2 callback slots (`_on_activity_bubble`, `_on_drawer_lifecycle`), `_pending_tool_args` dict. Emits bubbles at: `_do_tool_call_start` (~line 1049), `_do_tool_call_result` (~lines 1142, 1167), `_do_text_delta` (~line 970, agent-start), `_do_response_complete` (~line 1414, agent-end), `_do_error` (~line 1678, agent-end-error).
3. `ui/handlers/connection_sync_handler.py` — Removed `set_activity_drawer`, `_activity_drawer` attr, and 3 adapter closures from `sync()`.
4. `ui/window.py` — Constructs `ActivityWiringHandler`, calls `.wire()` at startup (line 712).

**Known gaps already flagged by Supervisor (do NOT re-report these — focus elsewhere):**
- The 6 spec-required local-emission tests for `AgentRuntimeHandler` were never written.
- ARCHITECTURE.md doc update was not done.

## Adversarial focus areas (priority order)

1. **State-leak in `_pending_tool_args`** — It's populated in `_do_tool_call_start` and popped in `_do_tool_call_result`. What if a tool call never completes (agent cancelled, runtime error mid-loop)? Does the dict grow unbounded? Trace every path that could skip `_do_tool_call_result`.

2. **Double-fire / ordering** — For a single write_file tool call, the drawer receives: tool_start, then tool_end, then patch. Is that ordering guaranteed? Could tool_end and patch fire in the wrong order under any GLib.idle_add reordering? Could a cancelled tool produce tool_start with no matching tool_end?

3. **Thread safety** — `_on_activity_bubble` callbacks fire from `_do_tool_call_start`/`_result` which run via `GLib.idle_add`. The drawer's `append_event` mutates GTK. Is the bubble construction (which imports `models.activity` inside the method) safe from a background thread? Trace the thread each emission site runs on.

4. **`wire()` idempotency claim** — The handler says "idempotent — safe to call twice." Prove or disprove. What if window.py or a reconnect path calls wire() again? Does it re-set callbacks correctly, or stack duplicates?

5. **Offline name resolution edge cases** — `_resolve_local_agent_name` calls `get_agent_name_for_session`. What if the session_key is a gateway key (not in the local registry)? What if the agent was removed mid-turn? What does the drawer show?

6. **Removal completeness** — Grep the entire codebase for any remaining references to `set_activity_drawer`, the old `_bubble_to_row`/`_on_lifecycle`/`_on_command_output` closures, or `_activity_drawer` on ConnectionSyncHandler. Is the removal truly complete, or is there a dangling call site that will now AttributeError?

7. **The drawer's counter-collapse interaction** — The drawer collapses consecutive same-(agent, type) rows. Now that local agents emit tool_start→tool_end→patch in sequence, could the counter-collapse merge a tool_end into a patch (both from same agent), producing a misleading count? Trace through `append_event` + `_mutate_counter_row`.

8. **`is_error` detection in `_do_tool_call_result`** — The new code computes `is_error = (hasattr(result, "error") and result.error) or (hasattr(result, "success") and not result.success)`. What types can `result` be? (ToolResult dataclass, plain string, None?) Does this evaluate correctly for all of them? What if `result.error` is an empty string? What if `result.success` is missing?

9. **ARCHITECTURE.md §8.6 conformance** — Verify the new handler truly receives all deps via constructor (no reaching out), never imports another handler module, and window.py only does composition. Flag any violation.

10. **Test coverage of NEW code paths** — Beyond the 2 known gaps, check: do the 13 new tests in `test_activity_wiring_handler.py` actually exercise the real methods, or do they mock so aggressively they prove nothing? Are there untested branches (e.g., the `is_error` branch in `_on_local_command_output`)?

## Output format

Use the BUG #[N] format from the adversarial debugger prompt. For each bug give severity, the violated assumption, attack vector, exact reproduction steps, root cause, and fix. Be exhaustive — slow but 100% correct.
