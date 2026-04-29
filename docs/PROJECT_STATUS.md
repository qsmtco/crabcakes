# CrabCakes — Project Status

**Last updated:** 2026-04-21

---

## Completed Phases

### Phase 1 — Chat Handler Extraction ✅
- `ui/handlers/chat_handler.py` — send, fan-out, routing
- Extracted from `window.py`

### Phase 2 — Gateway Handler Extraction ✅
- `ui/handlers/gateway_handler.py` — connect, agents, lifecycle
- Extracted from `window.py`

### Phase 4 — Media Handler Extraction ✅
- `ui/handlers/media_handler.py` — STT + prompt improvement
- Extracted from `window.py`

### Phase 5 — CrabWatch Filesystem Watcher ✅ (2026-04-28)
- `ui/handlers/crabwatch_handler.py` — Gio.FileMonitor filesystem watcher with debouncing and path filtering
- `models/feed_card.py` — FeedCardData dataclass + css_class_for_type() for all card types
- `ui/views/feed_card.py` — feed card widget factory (file_created, file_modified, file_deleted, dir_created, dir_deleted, commit, agent_joined, agent_left, member_joined, member_left, system)
- `ui/handlers/feed_handler.py` — FeedHandler managing feed store + gateway/fs event routing to project tab
- `ui/handlers/feed_store.py` — FeedStore with FIFO eviction + project scoping
- `tests/test_crabwatch_handler.py` — 21 passing tests (init, watch, ignore patterns, debounce)
- `tests/test_feed_handler.py` — FeedHandler tests (add/clear cards, event routing)
- `tests/test_feed_card.py` — feed_card view tests (card type rendering)
- `tests/test_feed_store.py` — FeedStore tests (FIFO eviction, project scoping)
- Wired into `ui/window.py` via `set_on_project_opened`/`set_on_project_tab_close` callbacks
- ARCHITECTURE.md updated: Section 3 (3.22a/3.22b/3.22c/3.24), Section 2 (directory structure), Section 11 (file inventory)


### Agent Card Port ✅ (2026-04-11)
- `utils/icons.py` — SVG avatar rendering (circle + hexagon + initials)
- `ui/handlers/agent_list_handler.py` — initials, color, sorting
- `ui/views/left_panel.py` — avatar cards with chat/toggle buttons
- `tests/test_icons.py` + `tests/test_agent_list_handler.py`
- `tests/test_architecture.py` — AST guard tests for handler isolation
- Commit: `7a40dc9`

### Button Bar Visual Port ✅ (2026-04-11)
- `Improve ✦` button with `.btn-improve` CSS (indigo tint)
- `Send ↵` button with `.suggested-action` CSS (solid indigo)
- Input area with `.input-bubble` CSS (dark background, rounded corners)

---

## In Progress

### Agent Runtime ✅ (2026-04-21)
- `agent/runtime.py` — tool loop, 3 providers (OpenAI/MiniMax/Anthropic), streaming SSE, cost tracking, conversation persistence
- `agent/tools.py` — 8 tools (read_file, write_file, exec_command, list_files, search_files, web_search, web_fetch)
- `agent/config.py` — LLM provider config with chmod security check
- `agent/context.py` — system prompt + file context builder, .gitignore parsing
- `agent/special_agents.py` — Coder + Debugger agent definitions
- `agent/__init__.py` — exports AgentRuntime
- `models/conversation.py` — Conversation, Message, ToolCall dataclasses
- `ui/handlers/agent_runtime_handler.py` — UI bridge, all callbacks via GLib.idle_add
- Phase 1.1–1.5 all implemented per `docs/agent-runtime.md`
- 21 bugs found + fixed in adversarial audit (`docs/ADVERSARIAL_AUDIT_AGENT_RUNTIME.md`)
- **Gap:** exec approval UI (Allow/Deny card) is logged but not rendered in chat tab

---

## Planned (Not Started)

### Review Layer ✅ (2026-04-21)
- `utils/git_ops.py` — GitPython wrapper (add, commit, diff, checkout, checkpoint)
- `utils/diff_parser.py` — unified diff → FileDiff/ParsedDiff data
- `ui/handlers/review_handler.py` — checkpoint, check changes, accept, reject
- `ui/views/review_bar.py` — mode dropdown + status + action buttons
- `ui/views/diff_card.py` — per-file collapsible diff cards with syntax highlighting
- Spec: `docs/review-layer.md`
- Create `ui/styles.py` with all CSS in one place
- Remove inline CSS from `main_content.py` and `left_panel.py`
- ARCHITECTURE.md Section 9 already documents the target pattern

### Porting Plans
- **Agent Cards** ✅ DONE
- **Project Cards** — see `docs/PROJECT_CARD_PORTING_PLAN.md`
- **Prompts Tab** — see `docs/PROMPTS_TAB_PORTING_PLAN.md`
- **Chat Formatting** — see `docs/CHAT_FORMATTING_PORTING_PLAN.md` (5-phase, largest effort)

### Stubs to Implement
- `ui/views/chat_control_bar.py` — `update()` not wired
- `ui/views/feedbar.py` — `update()` not wired

---

## Dead Files Removed (2026-04-10 Audit)

| File | Reason |
|------|--------|
| `gateway/dispatch.py` | EventDispatcher never instantiated |
| `gateway/protocol.py` | All constants/functions dead; window uses string literals |
| `gateway/session.py` | SessionManager never instantiated |
| `models/app_state.py` | AppState placeholder never used |
| `models/chat_buffer.py` | ChatBuffer never instantiated |
| `utils/helpers.py` | Empty placeholder |

---

## Test Status

- **1112 tests passing**, 6 failing
- Run: `cd /home/q/projects/crabcakes && pytest`

**Failing tests:**
- `test_convergence.py` — 5 parametrized cases (quick-close + edge cases) — convergence detection is **dead code**, nothing imports it
- `test_command_models.py::TestRegistryGetHelp::test_alias_resolves_to_canonical_help` — help text registry issue

**Note:** "116 tests" was from before the agent runtime test suite was added. Current count reflects all tests.

---

*This file tracks what's been done and what's planned. For architecture rules, see `ARCHITECTURE.md`.*
