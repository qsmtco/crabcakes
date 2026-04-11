# Plan: Extract Subsystem Handlers from window.py

**Author:** Qaster, refined by Qrusher
**Additions by:** Lieutenant Qrusher (agent comments, debugging guides, phase ordering) — 2026-04-10
**Clarified by:** Qaster — import guard rule: window importing handlers is correct, the guard is handlers importing each other — 2026-04-10
**Created:** 2026-04-10
**Status:** ALL PHASES COMPLETE ✅

---

## ⚠️ Before Starting: Read This Section

This plan is for agents working on this codebase. Key things to know:

- **window.py is the anchor.** Everything in this refactor is about moving code
  OUT of window.py without changing how the app behaves. If you are debugging
  something and don't know where to look, start with window.py and trace
  outward from there.
- **The handlers/ directory is new.** After Phase 1, a new `ui/handlers/` directory
  will exist. Each handler is self-contained — it does NOT import other handlers.
  If you need data from another handler, ask window.py to wire it in.
- **GLib.idle_add is always required** when calling GTK methods from inside a
  handler (all handlers run callbacks from gateway/STT threads). Each handler
  docstring reminds you of this.
- **Tests live in tests/test_<handler>.py.** Run `pytest` from the project root.
  If a test fails after a phase, the refactor introduced a behavior change —
  go back to the last clean state and re-extract more carefully.
- **ARCHITECTURE.md is the source of truth.** After each phase, update it before
  moving on. If ARCHITECTURE.md and the code disagree, fix ARCHITECTURE.md.

---

## Phase Ordering

```
Phase 1 ✅ → Phase 2 ✅ → Phase 4 ✅ → Phase 3 ✅ → Phase 5 ✅
```

> **Why this order?** Phase 3 (Project Handler) has the most complex
> inter-handler dependencies. Deferring it until after other handlers have
> stabilized means the interface will be clearer when we finally extract it.
> Phase 4 (Media Handler) goes before Phase 3 because it is self-contained —
> it only touches MainContent, no routing logic.

---

## ✅ Phase 1 — Chat Handler (COMPLETE)

**Extracted into:** `ui/handlers/chat_handler.py`

### What moves from window.py

| Method | What it does | Where to find it after extraction |
|--------|-------------|----------------------------------|
| `_on_send()` | Message send logic including project fan-out | `chat_handler.on_send()` |
| `_on_send_clicked()` | GTK signal handler for send button | `chat_handler.on_send_clicked()` |
| `_on_ws_event()` (chat.final part) | Route incoming messages to correct tab | `chat_handler.on_chat_event()` |
| `_switch_to_session_tab()` | Switch notebook to tab for session_key | `chat_handler.switch_to_tab()` |

### What the handler receives via constructor

```python
def __init__(
    self,
    main_content: MainContent,      # For tab ops: append_message, switch_to_tab
    gateway_client: GatewayClient, # For send_message(session_key, text)
    agent_to_project: dict,         # Read-only: maps session_key → project_name
    projects_module: module,        # utils.projects — for load_members()
):
```

> **🔴 Where things go wrong in Phase 1**
> The fan-out code (`if session_key.startswith("project:"):`) is the most
> fragile part. It calls `load_members()` and iterates over results. If
> `load_members()` returns None instead of a list, the for-loop crashes.
> See `tests/test_projects.py` for the round-trip tests — use those as
> a reference for what `load_members` actually returns.
>
> **Debugging tip:** If messages aren't appearing in tabs after fan-out,
> check `_agent_to_project` dict first — it may be stale or empty. Window
> owns it, ChatHandler just reads it.

### Window keeps after Phase 1

- Creating MainContent and wiring send_button → `chat_handler.on_send_clicked()`
- `_on_agent_selected()` — still in window, delegates to left_panel
- All project-related state and handlers (Phase 3 work)

### Verify this phase works

1. Send a DM to a single agent → response appears in correct tab
2. Send a message in a project tab → all members receive it
3. Close a tab → gone, no crash
4. Reconnect gateway → existing tabs still work

### Agent notes for Phase 1

- File to create: `ui/handlers/chat_handler.py`
- Tests to write: `tests/test_chat_handler.py`
- ARCHITECTURE.md section to update: "Handler Architecture" (add chat_handler)
- Import guard test: assert `window.py` does not import `ui.handlers.chat_handler`
- Red flag: if `pytest tests/test_chat_handler.py` fails, behavior changed —
  do NOT proceed to Phase 2 until all tests pass

---

## ✅ Phase 2 — Gateway Handler (COMPLETE)

**Extracted into:** `ui/handlers/gateway_handler.py`

### What moves from window.py

| Method | What it does | Where to find it after extraction |
|--------|-------------|----------------------------------|
| `_on_connect_clicked()` | Toolbar connect button handler | `gateway_handler.connect()` |
| `_connect_gateway()` | Create GatewayClient, attach callbacks | `gateway_handler._connect()` |
| `_disconnect_gateway()` | teardown | `gateway_handler.disconnect()` |
| `_on_ws_connect()` | Handle successful WS connect | `gateway_handler.on_connected()` |
| `_on_ws_error()` | Handle WS error | `gateway_handler.on_error()` |
| `GatewayClient` and `AgentManager` instances | State | Both owned by handler |

### What the handler receives via constructor

```python
def __init__(
    self,
    toolbar: Toolbar,             # For connection state: update_connection_state()
    left_panel: LeftPanel,        # For set_agents() after connect
    on_agent_selected: Callable, # Window's callback for agent clicks
):
```

### ⚠️ GLib.idle_add required

All gateway callbacks fire from the gateway's background thread. GTK calls
MUST be dispatched via `GLib.idle_add()`:

```python
# ❌ WRONG — crashes: GTK from wrong thread
self._toolbar.update_connection_state("connected")

# ✅ CORRECT — dispatch to main thread
GLib.idle_add(self._toolbar.update_connection_state, "connected")
```

> **🔴 Where things go wrong in Phase 2**
> Connection state not updating on the toolbar = missed `GLib.idle_add`.
> Agents not appearing in sidebar = `_on_ws_connect` not calling
> `left_panel.set_agents()` or calling it without `idle_add`.
> Reconnect failing = gateway handler not clearing state on disconnect
> before attempting reconnect.
>
> **Debugging tip:** If toolbar shows "disconnected" but gateway IS connected,
> the `_on_ws_connect` callback fired but `idle_add` was missed. If agents
> don't appear after connect, check that `left_panel.set_agents` was called
> with the agent list from `AgentManager.get_names_ref()`.

### Verify this phase works

1. Click Connect → toolbar shows "connecting" → shows "connected"
2. Agents appear in left panel within 2 seconds
3. Click Disconnect → toolbar shows "disconnected"
4. Click Connect again → reconnects cleanly
5. Simulate bad gateway URL → error shown, no crash

### Agent notes for Phase 2

- File to create: `ui/handlers/gateway_handler.py`
- Tests to write: `tests/test_gateway_handler.py`
- ARCHITECTURE.md section to update: "Handler Architecture" (add gateway_handler)
- Import guard test: assert `window.py` does not import `ui.handlers.gateway_handler`
- Red flag: if toolbar connection state never updates, `idle_add` was missed
- Red flag: if agents list is empty after connect, `left_panel.set_agents` not called

---

## ✅ Phase 4 — Media Handler (COMPLETE)

**Extracted into:** `ui/handlers/media_handler.py`

### What moves from window.py

| Method | What it does | Where to find it after extraction |
|--------|-------------|----------------------------------|
| `_on_stt_click()` | Toggle STT recording on/off | `media_handler.on_stt_click()` |
| `_on_stt_partial()` | Stream partial transcripts to input | `media_handler.on_stt_partial()` |
| `_on_improve_click()` | Call improve_prompt API | `media_handler.on_improve_click()` |
| `_on_improve_result()` | Replace input with improved text | `media_handler.on_improve_result()` |
| `STTEngine` instance | Audio capture and transcription | Owned by handler |

### What the handler receives via constructor

```python
def __init__(
    self,
    main_content: MainContent,   # For set_input_text(), update_stt_state()
    improve_module: module,      # utils.improve — for improve_prompt()
    GLib_module: module,         # gi.repository.GLib — for idle_add
):
```

### ⚠️ STT state machine

The STT button has two states: `idle` and `recording`. The state machine lives
in `MainContent.update_stt_state()` but is triggered by this handler. The
handler calls `main_content.update_stt_state("recording")` when recording
starts, and `main_content.update_stt_state("idle")` when it ends.

> **🔴 Where things go wrong in Phase 4**
> - Clicking Prompt button does nothing → `_on_stt_click` not wired in window
> - Transcript appears but input doesn't update → `_on_stt_partial` not calling
>   `main_content.set_input_text()` or not using `idle_add`
> - "Improve" replaces text with error message instead of improved text →
>   check `improve_prompt` callback error handling in `utils/improve.py`
>
> **Debugging tip:** STT requires a real microphone/ALSA device. If you don't
> have one, the STTEngine will fail silently or log ALSA errors. Test STT
> with the actual hardware before declaring Phase 4 done. Mock the STTEngine
> in unit tests if hardware is unavailable.

### Verify this phase works

1. Click Prompt → recording indicator on
2. Speak → partial transcript appears in input
3. Click Prompt again → recording stops, final transcript in input
4. Type text → click Improve → text replaced (or error shown gracefully)

### Agent notes for Phase 4

- File to create: `ui/handlers/media_handler.py`
- Tests to write: `tests/test_media_handler.py`
- ARCHITECTURE.md section to update: "Handler Architecture" (add media_handler)
- Import guard test: assert `window.py` does not import `ui.handlers.media_handler`
- **Hardware note:** STT needs a microphone. If testing on a machine without
  one, mock STTEngine or test manually before considering Phase 4 complete.

---

## ✅ Phase 3 — Project Handler (COMPLETE — 2026-04-11)

**Extract into:** `ui/handlers/project_handler.py`

> ⚠️ **This phase is intentionally last.** Do NOT start Phase 3 until the
> testing period confirms Phases 1, 2, and 4 are stable. The interface
> between ProjectHandler and ChatHandler only becomes clear after real usage.

### What moves from window.py

| Method | What it does | Where to find it after extraction |
|--------|-------------|----------------------------------|
| `_on_project_selected()` | TreeView row activated | `project_handler.on_project_selected()` |
| `_on_project_opened()` | Create/select project tab | `project_handler.open_project()` |
| `_on_project_members_changed()` | Rebuild _agent_to_project | `project_handler.on_members_changed()` |

### What the handler owns

```python
class ProjectHandler:
    _active_project_name: str | None  # Currently open project
    _agent_to_project: dict            # session_key → project_name
```

### What the handler receives via constructor

```python
def __init__(
    self,
    main_content: MainContent,   # For create_chat_tab()
    left_panel: LeftPanel,         # For refresh_agents_with_project()
):
```

### What it exposes to other handlers

```python
def is_project_session(self, session_key: str) -> bool:
    """Used by ChatHandler to determine if a message needs fan-out routing."""

def get_project_members(self, project_name: str) -> list[str]:
    """Used by ChatHandler to get member list for fan-out."""

def get_project_for_agent(self, session_key: str) -> str | None:
    """Used by ChatHandler to route response to correct project tab."""
```

### ⚠️ Inter-handler wiring: the real complexity

Before Phase 3, ChatHandler does fan-out like this:
```python
# In ChatHandler — DIRECT call to projects module
members = self._projects_module.load_members(project_name)
for member_key in members:
    self._gw.send_message(member_key, text)
```

After Phase 3, ChatHandler does fan-out like this:
```python
# In ChatHandler — via ProjectHandler
members = self._project_handler.get_project_members(project_name)
for member_key in members:
    self._gw.send_message(member_key, text)
```

The difference is: before Phase 3, no handler-to-handler dependency exists.
After Phase 3, ChatHandler requires a ProjectHandler reference. Window must
wire this at construction time.

> **🔴 Where things go wrong in Phase 3**
> - Project tab created but no messages appear → `_agent_to_project` dict
>   not updated when members changed, so routing logic can't find the project
> - Double-creation of project tab → `is_project_session()` not checked
>   before calling `open_project()`
> - Response routed to wrong tab → `get_project_for_agent()` returning wrong
>   project name or ChatHandler checking wrong dict
>
> **Debugging tip:** When fan-out routing breaks in Phase 3, trace:
>   1. `_agent_to_project` dict — is it populated? (`load_members` succeeded?)
>   2. `get_project_for_agent(session_key)` — does it return the right project?
>   3. `main_content.create_chat_tab(project_name)` — was the tab created?

### Verify this phase works

1. Open project → project tab created
2. Add member → member appears in project tab
3. Remove member → member no longer in routing list
4. Send message in project tab → all members receive it
5. Receive response → routed back to correct project tab

### Agent notes for Phase 3

- File to create: `ui/handlers/project_handler.py`
- Tests to write: `tests/test_project_handler.py`
- ARCHITECTURE.md section to update: "Handler Architecture" (add project_handler)
- Import guard test: assert `window.py` does not import `ui.handlers.project_handler`
- **Wait rule:** Do NOT start Phase 3 unless all Phase 1, 2, and 4 tests pass
  AND the codebase has been used in real sessions without routing bugs

---

## Testing Period (Between Phase 4 and Phase 3)

After Phases 1, 2, and 4 are complete and all tests pass, there is a
**testing period** before Phase 3 begins.

**What to do during the testing period:**
- Use the app normally — real sessions, real projects
- Watch for any routing bugs (messages going to wrong tabs)
- Notice if handler interfaces feel awkward or incomplete
- If a new feature is needed, implement it in the handler that makes sense

**When to start Phase 3:**
- At least one full week of clean real usage
- All handler tests passing
- No known routing bugs
- ARCHITECTURE.md fully updated for Phases 1, 2, 4

---

## ✅ Phase 5 — Slim Down window.py (COMPLETE — 2026-04-11)

**Final state:** window.py at 224 lines / 133 code lines. Methods match the target list exactly.
All dead stubs removed, stale section headers removed, direct handler state mutation replaced
with proper public setters. See `docs/ARCHITECTURE.md` for current line counts.

After all extractions, window.py should be:

```
MainWindow
├── __init__()           — create handlers, pass references
├── _build()             — layout only (unchanged)
├── _setup_keyboard_shortcuts()
├── _on_agent_selected() — delegates to chat_handler
└── _on_prompt_selected() — delegates to main_content
```

**Target:** ~80-100 lines. Pure assembly. No business logic.

---

## File Inventory After All Phases

```
ui/
├── handlers/
│   ├── __init__.py         # Re-exports: ChatHandler, GatewayHandler, etc.
│   ├── chat_handler.py     # ~80 lines
│   ├── gateway_handler.py  # ~90 lines
│   ├── media_handler.py    # ~55 lines
│   └── project_handler.py  # ~60 lines  (Phase 3 only)
├── toolbar.py              (unchanged)
├── window.py               # ~80 lines (down from 274)
└── views/                  (unchanged)

tests/
├── conftest.py
├── test_agents.py
├── test_chat_handler.py    (Phase 1)
├── test_gateway_handler.py  (Phase 2)
├── test_media_handler.py    (Phase 4)
├── test_project_handler.py  (Phase 3)
├── test_improve.py
└── test_projects.py
```

---

## Rules for This Refactor

1. **One handler at a time.** Phase 1 complete and tested before Phase 2 starts.
2. **Tests first.** Write tests for each handler before extracting. Handlers take references, not widgets — mock the references.
3. **ARCHITECTURE.md updated each phase.** No phase is done until the doc reflects the new state.
4. **No behavior changes.** This is pure extraction. If something works differently after, the refactor went wrong.
5. **Each phase is a git commit.** Bisectable. Revertable.
6. **Import guard.** Handlers must NOT import other handlers — window.py wires them together. Window.py importing handlers is expected and correct; handlers importing each other is the violation. After each phase, a test asserts that no handler file imports any other handler file.
7. **Phase 3 wait rule.** N/A — Phase 3 is complete.

---

## Quick Reference: Where to Look When Something Breaks

| Symptom | Where to start |
|---------|---------------|
| Messages not appearing in tabs | `chat_handler.on_chat_event()` — is it being called? |
| Gateway won't connect | `gateway_handler._connect()` + `gateway/client.py` |
| Agents not in sidebar | `gateway_handler.on_connected()` — did `set_agents` fire? |
| STT button does nothing | `window.py` — is `_on_stt_click` still wired? |
| Project fan-out broken | `_agent_to_project` dict in window (before Phase 3) |
| Tab not switching | `chat_handler.switch_to_tab()` or `MainContent._switch_tab_session()` |
| Improve replaces with error | `utils/improve.py` — API key set? Network? |
| Import errors after phase | Check `__init__.py` re-exports + `window.py` imports |
