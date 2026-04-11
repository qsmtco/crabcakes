# Usage Map — Trace Code Execution Paths

**Purpose:** Map how code is used, who calls what, and verify wiring before assuming something works.

---

## What Is a Usage Map?

A usage map traces the execution path from user action → your code. It answers:

- Who calls this function?
- What signals connect to this handler?
- Where is this callback registered?
- What's the full execution path?
- Is this code actually wired up?

---

## When to Use

| Situation | Why |
|-----------|-----|
| Before implementing a feature | Understand existing patterns |
| After writing code | Verify it's wired up |
| Debugging "it doesn't work" | Find missing connection |
| Reviewing old code | Understand data flow |
| Refactoring | Identify all call sites |

---

## Usage Map Template

### Function Usage Map

```markdown
## Function: `_on_tab_right_click()`

**Location:** `src/app.py:3502`

**Purpose:** Handle right-click on avatar — show popover with sessions

### Callers

| Who | Where | How |
|-----|-------|-----|
| `_build_tab_button()` | `src/ui/tabs.py:191` | `gesture.connect("pressed", ...)` |

**Trace Path:**
```
User right-clicks avatar
  → GestureClick "pressed" signal
    → lambda calls _on_avatar_right_click_cb(sk, nm, x, y)
      → ChatPanel._on_tab_right_click_cb
        → app.py._on_tab_right_click()
          → Show popover
```

### Dependencies

| What | Why |
|------|-----|
| `AgentManager.get_sessions()` | Get sessions for agent |
| `SessionManager.get()` | Get buffer for session |
| `Gtk.Popover` | Display menu |

### Data Flow

```
session_key → AgentManager → session list → Popover menu → User selection → _switch_to_session()
```
```

---

## Usage Map Commands

### Find Callers

```bash
# Who calls this function?
grep -rn "function_name(" src/

# Who calls this method?
grep -rn "\.method_name(" src/

# Who imports this module?
grep -rn "from.*module_name import\|import.*module_name" src/
```

### Find Signal Connections

```bash
# Who connects to this signal?
grep -rn "connect.*signal_name" src/

# What signals does this widget emit?
grep -rn "emit\|connect" src/ui/widget.py
```

### Find Callback Registrations

```bash
# Who registers this callback?
grep -rn "set_on_.*callback" src/

# Where are callbacks stored?
grep -rn "_on_.*_cb\s*=" src/
```

### Find Class Instantiation

```bash
# Where is this class instantiated?
grep -rn "ClassName(" src/

# Where is this widget created?
grep -rn "Gtk\.WidgetName\|WidgetName(" src/
```

---

## Execution Path Tracing

### Forward Trace (Top-Down)

Start from user action, trace down to implementation:

```bash
# 1. Find the entry point (user action)
grep -rn "on_click\|on_activate\|connect.*clicked" src/

# 2. Find what the handler does
grep -A 10 "def on_click" src/

# 3. Follow the chain
grep -rn "called_function" src/
```

### Backward Trace (Bottom-Up)

Start from function, trace up to caller:

```bash
# 1. Find who calls this
grep -rn "my_function" src/

# 2. Find who calls the caller
grep -rn "caller_function" src/

# 3. Keep going until you hit user action
```

---

## Common Patterns

### GTK Signal Pattern

```python
# Definition
button = Gtk.Button()
button.connect("clicked", self._on_button_clicked)

# Handler
def _on_button_clicked(self, btn):
    # Do something
    pass
```

**Usage Map:**
```
User clicks button
  → "clicked" signal emitted
    → _on_button_clicked() called
```

### Callback Setter Pattern

```python
# Registration
panel.set_on_send(self._on_send)

# Definition (in panel)
def set_on_send(self, cb):
    self._on_send_cb = cb

# Invocation (in panel)
if self._on_send_cb:
    self._on_send_cb(message)
```

**Usage Map:**
```
app.py._on_send()
  ← ChatPanel._on_send_cb(message)
    ← ChatPanel._send_btn "clicked" signal
      ← User clicks send button
```

### Manager Pattern

```python
# Registration
self._agent_mgr.register(session_key, agent_name)

# Query
sessions = self._agent_mgr.get_sessions(agent_name)
```

**Usage Map:**
```
AgentManager.register() stores session
  → AgentManager._agent_sessions[agent_name].append(session_key)
    → AgentManager.get_sessions(agent_name) returns list
```

---

## Verification Checklist

After creating a usage map, verify:

- [ ] Can trace from user action → code
- [ ] All intermediate calls exist
- [ ] Imports are correct
- [ ] Signals are connected
- [ ] Callbacks are registered
- [ ] No gaps in the chain

---

## Example: Full Usage Map

```markdown
## Usage Map: Right-Click Avatar Context Menu

### Entry Point
- **User Action:** Right-click avatar button
- **Widget:** `Gtk.Button` (avatar in AgentTabBar)
- **Signal:** `"pressed"` (GestureClick, button=3)

### Signal Connection
- **File:** `src/ui/tabs.py:191`
- **Code:** `gesture.connect("pressed", lambda g, n, x, y, sk, nm: ...)`
- **Callback:** `self._on_avatar_right_click_cb(sk, nm, x, y)`

### Callback Registration
- **File:** `src/ui/chat.py:374`
- **Code:** `self._agent_tabs_bar.set_on_avatar_right_click(cb)`
- **Callback:** `app.py._on_tab_right_click()`

### Handler Implementation
- **File:** `src/app.py:3502`
- **Function:** `_on_tab_right_click(session_key, agent_name, x, y)`
- **Actions:**
  1. Get sessions from AgentManager
  2. Build Gtk.Popover with session buttons
  3. Add "Close Tab" button
  4. Show popover

### Execution Path
```
User right-clicks avatar (AgentTabBar)
  → GestureClick "pressed" signal
    → _on_avatar_right_click_cb(sk, nm, x, y)
      → ChatPanel._on_tab_right_click_cb
        → app.py._on_tab_right_click(sk, nm, x, y)
          → AgentManager.get_sessions(nm)
          → Build popover menu
          → popover.popup()
```

### Verified Wiring
✅ Signal connected in `_build_tab_button()`
✅ Callback registered in `set_on_tab_right_click()`
✅ Handler exists in app.py
✅ AgentManager used correctly
```

---

## Red Flags

If you find any of these, STOP and investigate:

| Red Flag | What It Means |
|----------|---------------|
| Function exists, no callers | Dead code or missing wire |
| Signal defined, not connected | Feature won't trigger |
| Callback stored, never invoked | Dead callback |
| Import exists, module not found | Will crash at runtime |
| Call site exists, function doesn't | Will crash at runtime |

---

## The Golden Rule

> **If you can't trace the execution path from user action to your code, your code is not wired up.**

Stop. Find the gap. Wire it up. Then proceed.
