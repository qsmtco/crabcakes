# CrabCakes — Project Status

**Last updated:** 2026-04-11

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

### Phase 3 — Handler Extraction (Remaining)
- Still some logic in `window.py` that could be extracted
- See `docs/HANDLER_EXTRACTION_PLAN.md`

---

## Planned (Not Started)

### CSS Migration
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

- **116 tests**, all passing
- Run: `cd /home/q/projects/crabcakes && pytest`

---

*This file tracks what's been done and what's planned. For architecture rules, see `ARCHITECTURE.md`.*
