# CrabCakes Offline Mode — Implementation Spec

**Date:** 2026-05-10  
**Author:** Qaster  
**Status:** Ready for implementation  
**Estimated effort:** ~2–3 hours across 5 files  
**Architecture alignment:** ✅ Full compliance with `ARCHITECTURE.md` — no violations

---

## Overview

Enable CrabCakes to work fully without connecting to the OpenClaw gateway. Users can launch the app, open/create projects, and work with built-in special agents (Coder, Debugger) immediately — no gateway required. The gateway remains available as an optional Connect button.

**Key insight:** The system already works in offline mode for ~90% of the workflow. The changes below are bug fixes and UX polish, not new architecture.

---

## Implementation Checklist

Execute these steps **in order**. Each step is independently testable.

### Step 0: Verify Baseline (No Code Changes)

Before writing any code, confirm the current state:

```bash
# Make sure gateway is NOT running
openclaw gateway stop 2>/dev/null; true

# Launch crabcakes
cd /home/q/projects/crabcakes && python3 main.py
```

**Expected:**
- [ ] App opens without crash
- [ ] Toolbar shows "● Not connected"
- [ ] Agents tab shows Coder 🛠️ and Debugger 🐛 cards
- [ ] Projects tab shows project directories
- [ ] Double-click a project → project view opens
- [ ] Click + on Coder → added to project members
- [ ] Double-click Coder → chat tab opens
- [ ] Type message → AgentRuntime responds (requires API keys in agent config)

**Known issues to fix in Steps 1–4:**
1. Sending to a non-special-agent session when gateway is down silently fails (no feedback)
2. Activity bar doesn't animate during local agent execution
3. Toolbar says "● Not connected" which may confuse users expecting offline to work
4. Forward button popover crashes — it accesses `agent_mgr` which is `None`

---

### Step 1: Offline Error Feedback in ChatHandler

**File:** `ui/handlers/chat_handler.py`  
**What:** Show an inline error when the user tries to send to a non-special-agent while offline.

**Find this code** (~line 187 in `on_send()`):
```python
        # ── Gateway guard ────────────────────────────────────────────────────────
        if self._gw is None or not self._gw.is_connected():
            return
```

**Replace with:**
```python
        # ── Gateway guard ────────────────────────────────────────────────────────
        if self._gw is None or not self._gw.is_connected():
            # Offline: show error instead of silently failing
            def _show_offline_error():
                chat_box = self._mc.get_chat_box()
                if chat_box is not None:
                    if self._chat_render_handler is not None:
                        def _on_bubble(bubble):
                            if bubble is not None:
                                chat_box.append(bubble)
                            self._mc.scroll_chat_to_bottom()
                        self._chat_render_handler.render_async(
                            "System", "⚠️ Not connected to gateway. Start the gateway or use a local agent.",
                            session_key,
                            on_bubble_ready=_on_bubble,
                        )
            self._dispatch(_show_offline_error)
            buf.set_text("")
            return
```

**Why:** Currently, if you're offline and accidentally send to a gateway session, nothing happens. This gives feedback and clears the input box.

**Test:** With gateway down, type a message in any non-special-agent tab → should see the warning bubble.

---

### Step 2: Wire ActivityHandler for Local Agent Execution

**File 1:** `ui/handlers/agent_runtime_handler.py`  
**What:** Add lifecycle callbacks that fire when a local agent starts/stops processing.

**Add these fields to `__init__`** (after `self._pending_approvals`):
```python
        # Lifecycle callbacks — wired by window.py into ActivityHandler
        self._on_agent_start_cb = None   # set via set_on_agent_start()
        self._on_agent_end_cb = None     # set via set_on_agent_end()
```

**Add these public setters** (after `set_agent_routing`):
```python
    def set_on_agent_start(self, cb):
        """Set callback fired when a local agent starts processing. Signature: cb(session_key)."""
        self._on_agent_start_cb = cb

    def set_on_agent_end(self, cb):
        """Set callback fired when a local agent finishes processing. Signature: cb(session_key)."""
        self._on_agent_end_cb = cb
```

**Fire the callbacks.** Find `_do_text_delta` (the main-thread handler). At the start of streaming, fire start:

**In `_do_text_delta`**, add before the `if not self._crh.is_streaming(...)` check:
```python
    def _do_text_delta(self, session_key: str, text: str) -> None:
        """Main-thread portion of _on_text_delta."""
        if self._crh is None:
            return
        # Accumulate incremental delta into cumulative text
        self._streaming_text[session_key] = self._streaming_text.get(session_key, "") + text
        if not self._crh.is_streaming(session_key):
            chat_box = self._resolve_chat_box(session_key)
            if chat_box is not None:
                self._crh.start_streaming(session_key, chat_box, "Agent")
                # Fire lifecycle: agent started
                if self._on_agent_start_cb:
                    self._on_agent_start_cb(session_key)
        self._crh.update_streaming(session_key, self._streaming_text[session_key])
```

**Find `_do_response_complete`** (where streaming ends). Add the end callback:

Look for `_on_response_complete` and its `_do_response_complete` main-thread handler. At the end of `_do_response_complete`, before any return, add:
```python
                # Fire lifecycle: agent finished
                if self._on_agent_end_cb:
                    self._on_agent_end_cb(session_key)
```

**File 2:** `ui/window.py`  
**What:** Wire the lifecycle callbacks to ActivityHandler.

**Find** (in `_build()`, after the `AgentRuntimeHandler` is created and registered):
```python
        # Register built-in special agents from the registry
        from agent.special_agents import get_special_agents
        for agent_def in get_special_agents():
            self._agent_runtime_handler.add_special_agent(agent_def)

        # Inject into dependents after _agent_runtime_handler is assigned
        self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)
        self._left_panel.set_special_agents(self._agent_runtime_handler)
```

**Add after the `set_special_agents` line:**
```python
        # Wire local agent lifecycle → ActivityHandler (offline mode progress)
        self._agent_runtime_handler.set_on_agent_start(
            lambda sk: self._activity_handler.on_agent_start(sk)
        )
        self._agent_runtime_handler.set_on_agent_end(
            lambda sk: self._activity_handler.on_agent_end(sk)
        )
```

**Why:** ActivityHandler already has `on_agent_start()` and `on_agent_end()` methods that drive the progress bar. We just need to call them from the local agent path, not just the gateway path.

**Note:** `self._activity_handler` is created later in `_build()` (~line 181). This is a **ordering issue** — the lambda captures `self._activity_handler` by reference (late binding), so it will work as long as `_activity_handler` is set before any message is sent. Since `_build()` completes before the user can interact, this is safe. But to be explicit, you could also move the wiring to after `_activity_handler` is created. Either way works.

**Test:** Send a message to Coder in offline mode → activity bar should animate through reasoning → streaming → done.

---

### Step 3: Toolbar Offline State

**File:** `ui/toolbar.py`  
**What:** Show a friendlier "offline" state that indicates local agents are available.

**Find `update_connection_state`** — add a new state:

```python
    def update_connection_state(self, state):
        """
        Update button label and status label based on connection state.
        state: "disconnected" | "connecting" | "connected" | "offline"
        """
        if state == "connecting":
            self._connect_btn.set_label("Connecting…")
            self._status_label.set_markup(
                '<span foreground="#f59e0b" font_desc="Sans 10">● Connecting</span>')
        elif state == "connected":
            self._connect_btn.set_label("Disconnect")
            self._connect_btn.remove_css_class("suggested-action")
            self._connect_btn.add_css_class("destructive-action")
            self._status_label.set_markup(
                '<span foreground="#22c55e" font_desc="Sans 10">● Connected</span>')
        elif state == "offline":
            self._connect_btn.set_label("Connect")
            self._connect_btn.remove_css_class("destructive-action")
            self._connect_btn.add_css_class("suggested-action")
            self._status_label.set_markup(
                '<span foreground="#8b8ba0" font_desc="Sans 10">● Offline — local agents available</span>')
        elif state == "disconnected":
            self._connect_btn.set_label("Connect")
            self._connect_btn.remove_css_class("destructive-action")
            self._connect_btn.add_css_class("suggested-action")
            self._status_label.set_markup(
                '<span foreground="#6b6b7a" font_desc="Sans 10">● Not connected</span>')
```

**File:** `ui/window.py`  
**What:** Set initial toolbar state to "offline" instead of default "disconnected".

**In `_build()`**, after `toolbar = Toolbar(...)`:
```python
        toolbar = Toolbar(on_connect_clicked=self._on_connect_clicked)
        self._toolbar = toolbar
        self._toolbar.update_connection_state("offline")
```

**Why:** "Not connected" sounds broken. "Offline — local agents available" tells the user everything is fine.

**Test:** Launch app → toolbar shows "● Offline — local agents available".

---

### Step 4: Fix Forward Button Crash When Offline

**File:** `ui/window.py`  
**What:** Guard `_on_forward_clicked` against `None` `agent_mgr`.

**Find `_on_forward_clicked`** (~line 611):
```python
    def _on_forward_clicked(self, text, anchor_widget, source_session_key=None):
        """Show a popover listing all other agents to forward text to."""
        if self._gateway_handler is None:
            return
        agent_mgr = self._gateway_handler.agent_mgr
        if agent_mgr is None:
            return
```

The guard is already there (`if agent_mgr is None: return`). But it returns silently. Let's also include special agents in the forward list so forwarding works offline:

**Replace the entire method** with:
```python
    def _on_forward_clicked(self, text, anchor_widget, source_session_key=None):
        """Show a popover listing all other agents to forward text to."""
        # Build list of available agents (special agents always, gateway agents if connected)
        other_sessions = []

        # Special agents (always available)
        if self._agent_runtime_handler is not None:
            for sk, name in self._agent_runtime_handler.get_special_agents().items():
                if source_session_key is None or sk != source_session_key:
                    other_sessions.append((sk, name))

        # Gateway agents (only if connected)
        agent_mgr = self._gateway_handler.agent_mgr if self._gateway_handler else None
        if agent_mgr is not None:
            for page_idx, sk in self._main_content._tab_sessions.items():
                name = agent_mgr.get_name(sk)
                if name and (source_session_key is None or sk != source_session_key):
                    if not any(s == sk for s, _ in other_sessions):
                        other_sessions.append((sk, name))

        if not other_sessions:
            return  # nobody to forward to — silently skip

        popover = Gtk.Popover()
        popover.set_parent(anchor_widget)
        popover.set_position(Gtk.PositionType.TOP)

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu_box.set_margin_start(8)
        menu_box.set_margin_end(8)
        menu_box.set_margin_top(4)
        menu_box.set_margin_bottom(4)

        for sk, name in other_sessions:
            btn = Gtk.Button(label=f"→ {name}")
            btn.add_css_class("flat")
            btn.set_has_frame(False)
            btn.connect("clicked", lambda _b, s=sk, t=text, ss=source_session_key, pop=popover: self._forward_to_agent(s, t, ss, pop))
            menu_box.append(btn)

        if not other_sessions:
            lbl = Gtk.Label(label="No other agents available")
            lbl.add_css_class("dim-label")
            menu_box.append(lbl)

        popover.set_child(menu_box)
        popover.popup()
```

**Also fix `_forward_to_agent`** — it accesses `gw` directly. Find it (~line 658):
```python
    def _forward_to_agent(self, target_session_key, text, source_session_key, popover):
        """Send forwarded text to target agent and show it in their tab."""
        popover.popdown()
        if not text:
            return
        gw = self._gateway_handler._gw if self._gateway_handler else None
        if gw is None or not gw.is_connected():
            return
```

**Replace the gateway guard section** with dual-path routing:
```python
    def _forward_to_agent(self, target_session_key, text, source_session_key, popover):
        """Send forwarded text to target agent and show it in their tab."""
        popover.popdown()
        if not text:
            return

        # Route: special agents → local runtime, others → gateway
        is_special = (self._agent_runtime_handler is not None
                      and target_session_key in self._agent_runtime_handler.get_special_agents())
        if is_special:
            self._agent_runtime_handler.send_to_special_agent(target_session_key, text)
        else:
            gw = self._gateway_handler._gw if self._gateway_handler else None
            if gw is None or not gw.is_connected():
                return
            gw.send_message(target_session_key, text)

        # Look up source agent name
        agent_mgr = self._gateway_handler.agent_mgr if self._gateway_handler else None
        source_name = agent_mgr.get_name(source_session_key) if agent_mgr and source_session_key else None
```

*(Rest of method stays the same — the target_name lookup and tab creation logic is already fine.)*

**Why:** Currently, forwarding is gateway-only. This makes it work for special agents in offline mode and doesn't break the gateway path.

**Test:** In offline mode, open a project with Coder + Debugger as members. Send a message → see forward buttons on response bubbles → click forward → popover shows the other agent.

---

### Step 5: Final Integration Test

Run through the complete offline workflow:

```bash
# Ensure gateway is stopped
openclaw gateway stop 2>/dev/null; true

# Launch
cd /home/q/projects/crabcakes && python3 main.py
```

**Checklist:**
- [ ] App launches, toolbar shows "● Offline — local agents available"
- [ ] Agents tab shows Coder 🛠️ and Debugger 🐛
- [ ] Projects tab shows project directories
- [ ] Double-click a project → opens, file tree shows contents
- [ ] Click + on Coder → added to project
- [ ] Click + on Debugger → added to project
- [ ] Send message in project tab → fan-out to both agents
- [ ] Activity bar animates (sending → reasoning → streaming → done)
- [ ] Open Coder directly → chat tab → send message → response renders
- [ ] Tool calls show as feed cards
- [ ] Forward button on agent bubble shows other agents
- [ ] Click Connect → gateway connects → gateway agents appear alongside special agents
- [ ] Disconnect → returns to offline mode, special agents still work

**Then connect the gateway and verify nothing broke:**
- [ ] Click Connect → gateway agents populate agents tab
- [ ] Send to gateway agent → works
- [ ] Send to special agent → still works
- [ ] Project fan-out to mixed local+remote → works

---

## Files Changed Summary

| File | Change Type | Approx Lines |
|------|-------------|-------------|
| `ui/handlers/chat_handler.py` | Modified (gateway guard → error feedback) | +15 |
| `ui/handlers/agent_runtime_handler.py` | Modified (add lifecycle callbacks) | +15 |
| `ui/window.py` | Modified (wire lifecycle + fix forward + toolbar init) | +30 / -10 |
| `ui/toolbar.py` | Modified (add "offline" state) | +5 |

**Total: ~65 lines changed across 4 files. Zero new files.**

---

## Architecture Compliance

| Principle | Status |
|-----------|--------|
| Gateway is foundational, independent of UI | ✅ Gateway untouched — we just don't require it |
| Models are pure data | ✅ No model changes |
| UI is composed, not inherited | ✅ Changes in handler methods |
| Callbacks for cross-component comms | ✅ New lifecycle callbacks follow existing pattern |
| Handler pattern for new logic | ✅ Changes go into existing handlers |
| CSS in `styles.py` only | ✅ No CSS changes |
| No handler imports another handler | ✅ Window wires everything via callbacks |

---

## What NOT to Change

These files need **zero modifications** — they already work correctly in offline mode:

- `agent/runtime.py` — calls LLM APIs directly
- `agent/special_agents.py` — static registry
- `agent/tools.py` — local file/exec tools
- `agent/context.py` — local prompt builder
- `agent/enforcement.py` — local verification
- `models/` (all) — pure data
- `utils/` (all) — file I/O
- `gateway/client.py` — simply not instantiated
- `ui/views/` (all widgets) — pure GTK
- `ui/styles.py` — CSS
- Review layer — git operations
- Feed system — local events
- CrabWatch — filesystem monitor

---

## Optional Enhancements (Future)

1. **`--offline` CLI flag** — Skip auto-connect attempt on launch (if auto-connect is ever added)
2. **Agent config validation** — Check API keys are configured at startup, show warning in agents tab if not
3. **Conversation restore on startup** — `restore_conversations()` exists but may need testing for the offline-first path
4. **Toolbar "Offline" → "Connected" animation** — Smooth transition when gateway connects mid-session

---

*Implementation spec prepared for the Qontinuum Bridge crew. Hand this to Coder and let it rip.*
