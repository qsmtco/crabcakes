with open('ARCHITECTURE.md', 'r') as f:
    content = f.read()

old_312 = """### 3.12 `ui/handlers/media_handler.py` — Media Handler (Phase 4)

**Responsibility:** All media I/O — STT (whisper.cpp push-to-talk) and prompt improvement. Extracted from `window.py` in Phase 4.

**Owns:**
- `STTEngine` instance (`_stt_engine`) — owns its own background capture thread
- Sync callback (`_sync_callback`) — window sets this to trigger `ChatHandler.on_send()` after voice input

**Thread safety:** `_on_stt_partial` fires from the STT background thread. GTK calls go through `GLib.idle_add()`.

**Public API:**
```python
def on_stt_click():
    """Toggle STT recording — start or stop. On stop, appends transcript and calls sync callback."""

def on_improve_click():
    """Send current input text to MiniMax improve API. Disables button, calls _on_improve_result on response."""

def set_on_send_callback(cb: Callable):
    """Window sets this so voice input automatically triggers ChatHandler.on_send()."""
```

**What it owns:** `STTEngine` background thread, button state during improve.

**Responsibility:** All gateway lifecycle — connecting, disconnecting, agent discovery, error handling, and thread-safe state dispatch to GTK. Extracted from `window.py` in Phase 2.

**Owns:**
- `GatewayClient` instance (`_gw`)
- `AgentManager` instance (`_agent_mgr`)
- Sync callback (`_sync_callback`) — window uses this to sync `_gw` reference into `ChatHandler`

**Key invariant:** All GTK calls go through `GLib.idle_add()`. Gateway callbacks fire from the gateway's background thread; GTK is not thread-safe.

**Public API:**
```python
def connect() -> None:
    """Create GatewayClient, start it, set connection state to 'connecting'. 
    Calls on_connected() on the gateway thread — that fires sync callback + dispatches agent list to left panel."""

def disconnect() -> None:
    """Stop GatewayClient, set connection state to 'disconnected', clear AgentManager."""

def is_connected() -> bool:
    """True if GatewayClient is running and connected."""

@property
def agent_mgr() -> AgentManager | None:
    """Returns AgentManager if connected, else None."""

def set_sync_callback(cb: Callable) -> None:
    """Window calls this to receive the live GatewayClient reference after connect succeeds."""

def dispatch(fn: Callable, *args, **kwargs) -> None:
    """Thread-safe dispatch to main thread via GLib.idle_add(fn, *args, **kwargs)."""

def on_error(err_msg: str) -> None:
    """Called by gateway thread — dispatches 'disconnected' state to toolbar via GLib.idle_add."""

def on_connected() -> None:
    """Called by gateway thread — dispatches 'connected' state + agent list to left panel."""

def _on_event(event: str, payload: dict) -> None:
    """Called by gateway thread for ALL events — routes to window's on_event handler."""
```

**What it owns:** `STTEngine` background thread, button state during improve.

**Public API:**
```python
handler = ChatHandler(
    main_content=main_content,     # MainContent instance
    gateway_client=gateway_client, # GatewayClient instance
    agent_to_project={},           # {session_key: project_name} — read-only reference
    projects_module=projects_mod,  # utils.projects module
    GLib_module=GLib,             # gi.repository.GLib — for thread-safe GTK dispatch
)

handler.on_send_clicked()    # GTK signal handler — delegates to on_send()
handler.on_send()            # Read input, display, send (DM or fan-out)
handler.on_chat_event(e, p)  # Route incoming chat.final to correct tab
handler.switch_to_tab(sk)    # Switch notebook to tab matching session_key
```

**Thread safety:** `on_chat_event()` fires from the gateway background thread. All GTK operations (tab switching, appending messages) are dispatched via `GLib.idle_add()` when `GLib_module` is provided. Pass `GLib=None` in tests for synchronous calls.

**Fan-out design:** ChatHandler calls `projects_module.load_members()` directly — no ProjectHandler needed (Phase 3 work).

**Rules:**
- Handler does NOT import other handlers — window wires them together
- Handler does NOT own `_agent_to_project` — it reads from the injected dict
- Handler calls GTK methods only through `_dispatch()` for thread safety"""

new_312 = """### 3.12 `ui/handlers/media_handler.py` — Media Handler (Phase 4)

**Responsibility:** All media I/O — STT (whisper.cpp push-to-talk) and prompt improvement. Extracted from `window.py` in Phase 4.

**Owns:**
- `STTEngine` instance (`_stt_engine`) — owns its own background capture thread
- Sync callback (`_sync_callback`) — window sets this to trigger `ChatHandler.on_send()` after voice input
- Improve button state (`_improved_button.set_sensitive()`) during API calls

**Thread safety:** `_on_stt_partial` fires from the STT background thread. All GTK operations go through `GLib.idle_add()`.

**Public API:**
```python
def on_stt_click(_btn=None):
    """Toggle STT recording — start or stop. On stop, appends transcript and calls sync callback."""

def on_improve_click(_btn=None):
    """Send current input text to MiniMax improve API. Disables button, calls _on_improve_result on response."""

def set_on_send_callback(cb: Callable):
    """Window sets this so MediaHandler can trigger ChatHandler.on_send() after voice input."""
```

**Rules:**
- Handler does NOT import other handlers — window wires them together
- STTEngine runs its own background thread; handler dispatches all GTK calls via `GLib.idle_add()`
- improve_prompt() callback is already GLib-dispatched when `GLib_module` is provided"""

if old_312 not in content:
    print("ERROR: old_312 not found in content!")
    import sys
    sys.exit(1)

content = content.replace(old_312, new_312)

with open('ARCHITECTURE.md', 'w') as f:
    f.write(content)

print("Section 3.12 replaced successfully")
