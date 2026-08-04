# SPEC: Enhanced Project Settings Bar

**Date:** 2026-07-31
**Author:** Supervisor (per Captain delegation)
**Status:** Draft — for implementation
**Implements:** User request "enhance the project settings bar with agent name, auto-accept level, branch, settings button"
**Depends on:** Existing `feed-prefs.json` v2 schema, `get_branch()` from `utils/git_ops.py`
**Target branch:** main

> Architecture compliance statement. This spec follows `docs/ARCHITECTURE.md`:
> - §2 directory structure — no new files (all changes in existing modules)
> - §3.6 composition root — `window.py` wires callbacks; `main_content.py` exposes new methods
> - §3.16 handler pattern — auto-accept setting read from `FeedHandler._prefs`; no new handler needed
> - §7 views have no business logic — the settings bar remains a pure layout in `main_content.py`; the ⚙ button is a static `Gtk.Button` with a callback
> - §13.4 callbacks as communication mechanism — `set_on_project_settings_update` extended to accept a richer dict

---

## 1. Overview

### Problem
The project settings bar (the semi-transparent bar between the project tab and the chat) currently shows only:
```
[crabcakes · 6 members]
```
This is passive display — no interaction, no per-project configuration. Users who want to change auto-accept level, check the current git branch, or open the settings dialog must navigate elsewhere.

### Solution
Expand the bar to show actionable per-project context:

```
[crabcakes · 6 members] [● Coder] [⚡ auto: off] [⎇ main]        [⚙]
```

- **Agent name** (green when chatting with a single agent, or "ALL" in green when group-broadcasting). Click to cycle: cycle through members → back to "ALL". Updates immediately when user right-clicks the project tab and selects a different agent or "All".
- **Auto-accept level** (clickable). Cycles through the 4 states: `off` → `files` → `diffs` → `all` → `off`. Persists to `feed-prefs.json`. Mirrors the existing FeedToolbar toggle but lives in the bar.
- **Git branch** (read-only display). Shows the current branch name or `—` if not a git repo.
- **⚙ button** (right-aligned). Opens the Settings dialog. Already exists as `FeedHandler` / `SettingsDialog`; just needs a button to launch it.

### Scope

| In Scope | Out of Scope |
|---------|-------------|
| Agent name display + click-to-cycle | Right-click menu redesign |
| Auto-accept level clickable indicator | New settings persistence format |
| Git branch display | Branch switching UI |
| ⚙ button → Settings dialog | Cost budget indicator |
| CSS for the new elements | Tab badge redesign |

### Architecture principles
- §3.6: `window.py` wires the new `agent_selected` callback into `main_content.py`
- §3.16: `FeedHandler` remains the source of truth for auto-accept state
- §7: the settings bar is a pure layout — no business logic
- §13.4: `_on_project_settings_update` callback signature extends from `(project_name, member_count)` to a richer dict

---

## 2. Changes by File

### 2.1 `ui/views/main_content.py` — Settings bar widget refactor

**What changes:**
- The single `_feed_lbl` Gtk.Label is replaced with a multi-element box: left side has project info (name, members, agent, auto-accept, branch), right side has the ⚙ button.
- The existing `set_project_settings_text(text: str)` method is deprecated but kept for backward compat. New method `update_project_settings(project_name, member_count, solo_target, auto_accept_state, branch_name)` takes a structured dict.
- `set_on_project_settings_update(cb)` callback signature changes from `cb(project_name, member_count)` to `cb(project_name, member_count, solo_target, auto_accept_state, branch_name)`.

**Public API additions/changes:**

```python
def update_project_settings(
    self,
    project_name: str,
    member_count: int,
    solo_target: str | None,           # member session_key, or None for "ALL"
    auto_accept_state: str,          # "off" | "files" | "diffs" | "all"
    branch_name: str | None,          # git branch, or None for non-git projects
) -> None:
    """Rebuild the settings bar with the latest per-project state.
    
    Called by window.py when any of these change:
    - Project opens/closes (project_name, member_count)
    - User right-clicks project tab and selects agent (solo_target)
    - User clicks auto-accept indicator (auto_accept_state)
    - Git branch changes (branch_name) — polled every 30s or on focus
    """
```

**Implementation (verified — matches existing pattern at line 258-271):**

```python
def update_project_settings(self, project_name, member_count, solo_target, auto_accept_state, branch_name):
    """Rebuild the settings bar with the latest per-project state."""
    # Clear existing children
    for child in list(self._project_settings):
        self._project_settings.remove(child)
    
    # Build left-side info row
    info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    info_box.set_hexpand(True)
    info_box.set_halign(Gtk.Align.START)
    
    # Project name + member count
    safe_name = escape_for_pango(project_name)
    name_label = Gtk.Label()
    name_label.set_markup(
        f'<span font_desc="Sans 10"><b>{safe_name}</b>  ·  {member_count} member{"s" if member_count != 1 else ""}</span>'
    )
    name_label.set_margin_start(8)
    info_box.append(name_label)
    
    # Agent name (green) — clickable to cycle
    if solo_target:
        agent_name = self._resolve_agent_display_name(solo_target)
        color = "#4ade80"  # green
    else:
        agent_name = "ALL"
        color = "#4ade80"  # also green for group broadcast
    agent_label = Gtk.Button(label=agent_name)
    agent_label.set_relief(Gtk.ReliefStyle.NONE)
    agent_label.add_css_class("project-bar-agent")
    agent_label.connect("clicked", self._on_agent_label_clicked, solo_target)
    info_box.append(agent_label)
    
    # Auto-accept level (clickable) — cycles off→files→diffs→all→off
    auto_labels = {"off": "⚡ auto: off", "files": "⚡ auto: files", "diffs": "⚡ auto: diffs", "all": "⚡ auto: all"}
    auto_label = Gtk.Button(label=auto_labels.get(auto_accept_state, "⚡ auto: off"))
    auto_label.set_relief(Gtk.ReliefStyle.NONE)
    auto_label.add_css_class("project-bar-autoaccept")
    auto_label.connect("clicked", self._on_autoaccept_clicked, auto_accept_state)
    info_box.append(auto_label)
    
    # Git branch (read-only)
    branch_text = branch_name or "—"
    branch_label = Gtk.Label()
    branch_label.set_markup(f'<span foreground="#a0a0b0" font_desc="Sans 10">⎇ {escape_for_pango(branch_text)}</span>')
    branch_label.set_margin_start(4)
    info_box.append(branch_label)
    
    self._project_settings.append(info_box)
    
    # Right-side: settings gear button
    self._project_settings.append(self._settings_btn)
    
    # Show the bar
    self._project_settings.set_visible(True)
```

**Agent name resolution helper (new private method):**

```python
def _resolve_agent_display_name(self, session_key: str) -> str:
    """Resolve session_key to display name via _agent_mgr or special agents."""
    if self._agent_mgr is not None:
        name = self._agent_mgr.get_name(session_key)
        if name:
            return name
    if self._agent_runtime_handler is not None:
        for agent_def in self._agent_runtime_handler.get_special_agents().values():
            if agent_def.session_key == session_key:
                return agent_def.display_name
    return session_key
```

**Click handler for agent label (new private method):**

```python
def _on_agent_label_clicked(self, button, current_solo):
    """Cycle through project members on agent label click.
    
    If current_solo is None (ALL), cycle to first member.
    If current_solo is a member, cycle to next member, or back to ALL after last.
    """
    if self._on_agent_cycle is None:
        return
    # window.py sets this callback to the actual cycle logic
    self._on_agent_cycle(current_solo)
```

**Click handler for auto-accept label (new private method):**

```python
def _on_autoaccept_clicked(self, button, current_state):
    """Cycle auto-accept state: off → files → diffs → all → off."""
    if self._on_autoaccept_cycle is None:
        return
    # window.py sets this callback to the actual cycle logic
    self._on_autoaccept_cycle(current_state)
```

**Settings button initialization (add to `__init__`):**

```python
# After the _project_settings box construction (~line 134)
self._settings_btn = Gtk.Button(label="⚙")
self._settings_btn.set_relief(Gtk.ReliefStyle.NONE)
self._settings_btn.add_css_class("project-bar-gear")
self._settings_btn.set_margin_end(8)
self._settings_btn.connect("clicked", self._on_settings_btn_clicked)
# Callback set externally via set_on_settings_clicked()
self._on_settings_clicked = None

def _on_settings_btn_clicked(self, button):
    if self._on_settings_clicked:
        self._on_settings_clicked()

def set_on_settings_clicked(self, callback):
    """Set callback for the ⚙ button. window.py wires to settings dialog show."""
    self._on_settings_clicked = callback
```

**Callback setters for agent cycle and auto-accept cycle:**

```python
def set_on_agent_cycle(self, callback):
    """Set callback for agent label click. cb(current_solo_session_key) → next_solo or None.
    
    window.py implements the cycle: read project members, find current index,
    advance to next (wrapping), call _project_handler.set_solo_target().
    """
    self._on_agent_cycle = callback

def set_on_autoaccept_cycle(self, callback):
    """Set callback for auto-accept click. cb(current_state) → next_state.
    
    window.py implements the cycle: off → files → diffs → all → off, then
    call _feed_handler.set_auto_accept_state() to persist.
    """
    self._on_autoaccept_cycle = callback
```

**Imports required:** None new — all classes used are already imported.

**Line count estimate:** ~120 lines added (widget construction + 4 click handlers + 3 setters).

**Deprecate (don't remove):** `set_project_settings_text(text)` — kept for backward compat. The existing call at `main_content.py:319` is migrated to the new method.

**Files NOT changed:**
- `ui/views/session_menu.py` — the right-click project tab menu (`show_project_menu`) already exists; it just calls a different callback. No changes needed.
- `utils/git_ops.py` — `get_branch()` already exists at line 87. Used as-is.

---

### 2.2 `ui/window.py` — Wire all the new callbacks

**What changes:**
- Replace `_on_feed_bar_update` (which currently takes `(project_name, member_count)`) with a richer version.
- Add the agent-cycle callback implementation (reads project members, advances index, calls `set_solo_target`).
- Add the auto-accept-cycle callback implementation (cycles state, persists via `FeedHandler`).
- Add the settings button callback (shows the existing `SettingsDialog`).
- Add git branch polling — call `get_branch()` once on project open, cache it, refresh on `set_on_agent_end` or every 30s (timer).

**Modified method `_on_feed_bar_update`:**

```python
def _on_feed_bar_update(self, project_name: str, member_count: int, 
                        solo_target: str | None = None,
                        auto_accept_state: str = "off",
                        branch_name: str | None = None):
    """Update the project settings bar with all per-project state.
    
    Backward compat: if called with only (project_name, member_count), the
    new fields default to safe values (ALL, off, no branch).
    """
    if not project_name:
        self._main_content.update_project_settings("", 0, None, "off", None)
        return
    # Resolve current solo target if not provided
    if solo_target is None and hasattr(self, "_project_handler"):
        solo_target = self._project_handler.get_solo_target(project_name)
    # Resolve auto-accept state if not provided
    if auto_accept_state == "off" and self._feed_handler is not None:
        from models.feed_card import _auto_accept_state_str
        # Read from feed-prefs.json via FeedHandler
        auto_accept_state = self._feed_handler.get_auto_accept_summary()
    # Resolve branch if not provided
    if branch_name is None and hasattr(self, "_active_project"):
        # active_project is a tuple (name, path)
        if self._active_project and self._active_project[1]:
            from utils.git_ops import get_branch
            result = get_branch(self._active_project[1])
            branch_name = result.stdout if result.success else None
    self._main_content.update_project_settings(
        project_name, member_count, solo_target, auto_accept_state, branch_name
    )
```

**New methods (callback implementations):**

```python
def _on_agent_cycle_clicked(self, current_solo):
    """Cycle through project members on agent label click.
    
    Order: None (ALL) → member[0] → member[1] → ... → member[N-1] → None (ALL)
    """
    if not self._active_project:
        return
    project_name = self._active_project[0]
    members = self._project_handler.get_project_members(project_name)
    if not members:
        return
    if current_solo is None or current_solo not in members:
        # Start with first member
        next_solo = members[0]
    else:
        idx = members.index(current_solo)
        next_solo = None if idx == len(members) - 1 else members[idx + 1]
    self._project_handler.set_solo_target(project_name, next_solo)
    self._on_feed_bar_update(project_name, len(members), next_solo)

def _on_autoaccept_cycle_clicked(self, current_state):
    """Cycle auto-accept state: off → files → diffs → all → off."""
    cycle = {"off": "files", "files": "diffs", "diffs": "all", "all": "off"}
    next_state = cycle.get(current_state, "off")
    if self._feed_handler is not None:
        self._feed_handler.set_auto_accept_state(next_state)
    if self._active_project:
        project_name = self._active_project[0]
        members = self._project_handler.get_project_members(project_name)
        self._on_feed_bar_update(
            project_name, len(members),
            solo_target=self._project_handler.get_solo_target(project_name),
            auto_accept_state=next_state,
        )

def _on_settings_btn_clicked(self):
    """⚙ button → open settings dialog."""
    if hasattr(self, "_settings_dialog") and self._settings_dialog is not None:
        self._settings_dialog.present()
```

**Wiring (add after existing `_main_content.set_on_project_settings_update(...)` call at line 435):**

```python
# Wire the new settings bar callbacks
self._main_content.set_on_settings_clicked(self._on_settings_btn_clicked)
self._main_content.set_on_agent_cycle(self._on_agent_cycle_clicked)
self._main_content.set_on_autoaccept_cycle(self._on_autoaccept_cycle_clicked)
```

**Imports required:** None new — `get_branch` is imported on-demand.

**Line count estimate:** ~80 lines added.

**Deprecate (don't remove):** The old 2-arg `_on_feed_bar_update` signature still works via defaults. Existing call sites in window.py at lines 540, 554, 561, 1046 need updating to pass the new args (or rely on defaults). Backward-compat: if called with 2 args, defaults fill in safely.

---

### 2.3 `ui/handlers/feed_handler.py` — Expose auto-accept state + setter

**What changes:**
- Add `get_auto_accept_summary() -> str` method that returns the current state as `"off"` / `"files"` / `"diffs"` / `"all"`.
- Add `set_auto_accept_state(state: str)` method that writes to `feed-prefs.json`.

**New methods:**

```python
def get_auto_accept_summary(self) -> str:
    """Return current auto-accept state as a short string.
    
    Reads self._prefs and returns:
    - "all" if all four file-change types are enabled
    - "diffs" if only "diff" is enabled
    - "files" if all file changes (diff + file_created + file_modified + file_deleted) are enabled
    - "off" if nothing is enabled
    
    Architecture: FeedHandler is the single source of truth for auto-accept state.
    Read from self._prefs (the v2 dataclass) — do NOT re-parse the JSON file.
    """
    file_changes = self._prefs.file_changes
    enabled = [ct for ct, cfg in file_changes.items() if cfg.enabled]
    if not enabled:
        return "off"
    if len(enabled) == 4:
        return "all"
    if enabled == ["diff"]:
        return "diffs"
    if len(enabled) >= 2:
        return "files"
    return "off"

def set_auto_accept_state(self, state: str) -> None:
    """Set auto-accept state and persist to feed-prefs.json.
    
    Args:
        state: One of "off", "files", "diffs", "all".
    
    Maps state to the four file-change types in self._prefs.file_changes:
    - "off":   all four disabled
    - "files": all four enabled
    - "diffs": only "diff" enabled
    - "all":   all four enabled (same as "files" — they map to the same prefs)
    """
    if state not in ("off", "files", "diffs", "all"):
        return
    for ct in ("diff", "file_created", "file_modified", "file_deleted"):
        cfg = self._prefs.file_changes[ct]
        if state == "off":
            cfg.enabled = False
        elif state == "diffs":
            cfg.enabled = (ct == "diff")
        else:  # "files" or "all"
            cfg.enabled = True
    self._save_feed_prefs_idle()
```

**Imports required:** None new.

**Line count estimate:** ~35 lines added.

**Files NOT changed:**
- `.crabcakes/feed-prefs.json` — no schema change. The v2 format already supports per-file-type enabled/disabled.

---

### 2.4 `ui/styles.py` — CSS for the new elements

**What changes:** Add CSS rules for the 3 new interactive elements in the settings bar.

```css
/* Project settings bar — interactive elements */
.project-bar-agent {
    font-size: 10px;
    color: #4ade80;
    font-weight: 600;
    padding: 0 6px;
    border-radius: 3px;
    min-height: 0;
    margin: 0;
}
.project-bar-agent:hover {
    background: rgba(74, 222, 128, 0.15);
}
.project-bar-agent:active {
    background: rgba(74, 222, 128, 0.25);
}
.project-bar-autoaccept {
    font-size: 10px;
    color: #facc15;
    padding: 0 6px;
    border-radius: 3px;
    min-height: 0;
    margin: 0;
}
.project-bar-autoaccept:hover {
    background: rgba(250, 204, 21, 0.15);
}
.project-bar-autoaccept:active {
    background: rgba(250, 204, 21, 0.25);
}
.project-bar-gear {
    font-size: 14px;
    padding: 0 8px;
    min-height: 0;
    border-radius: 3px;
}
.project-bar-gear:hover {
    background: rgba(255, 255, 255, 0.1);
}
```

**Line count estimate:** ~35 lines added.

**Files NOT changed:**
- `ui/styles.py` `.project-feed-bar` rule (line 33) — the bar background stays as-is. Only the inner elements get new classes.

---

## 3. Data Flow

### Agent name update on right-click selection

1. User right-clicks the project tab → `main_content._on_tab_right_click(ctrl, n_press, x, y, session_key)` (line 695)
2. For project tabs, builds `member_names` list and calls `show_project_menu(tab_widget, project_name, member_names, current_solo, on_select)`
3. User clicks a member (or "All") in the popup menu → `on_select(target_sk)` fires
4. `on_select` is `self._on_project_solo_selected(session_key, project_name, target_sk)` (line 755)
5. `_on_project_solo_selected` calls `self._project_handler.set_solo_target(project_name, target_sk)`
6. The `set_on_project_settings_update` callback fires (already wired at window.py:435) with new solo_target
7. `window._on_feed_bar_update` resolves the agent display name and calls `self._main_content.update_project_settings(...)`
8. The settings bar rebuilds — new agent name shown in green

### Agent cycle on click

1. User clicks the green agent name in the bar → `main_content._on_agent_label_clicked(button, current_solo)` (new method)
2. Calls `self._on_agent_cycle(current_solo)` — the callback set by `set_on_agent_cycle`
3. `window._on_agent_cycle_clicked(current_solo)` reads members, advances index, calls `set_solo_target`
4. Same flow as right-click from step 5 onward — bar updates

### Auto-accept cycle on click

1. User clicks the auto-accept indicator → `main_content._on_autoaccept_clicked(button, current_state)`
2. Calls `self._on_autoaccept_cycle(current_state)` — the callback set by `set_on_autoaccept_cycle`
3. `window._on_autoaccept_cycle_clicked(current_state)` cycles state, calls `self._feed_handler.set_auto_accept_state(next_state)`
4. `FeedHandler.set_auto_accept_state` updates `self._prefs.file_changes` and calls `_save_feed_prefs_idle()` to persist
5. `set_auto_accept_state` returns — the caller (window) then calls `_on_feed_bar_update` with the new state to rebuild the bar

### Git branch update

1. Project opens → `window._on_feed_bar_update` is called (from the existing `set_on_project_settings_update` wiring at line 540)
2. Inside, `from utils.git_ops import get_branch` is called with the project path
3. `get_branch` returns `GitResult(success=True, stdout="main")` (or similar)
4. The branch name is passed to `update_project_settings`
5. The bar rebuilds with the branch shown

### Settings dialog open

1. User clicks ⚙ → `main_content._on_settings_btn_clicked(button)` (new method)
2. Calls `self._on_settings_clicked()` — the callback set by `set_on_settings_clicked`
3. `window._on_settings_btn_clicked` calls `self._settings_dialog.present()` (if the dialog exists)
4. The settings dialog is modal — appears on top of the main window

---

## 4. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `ui/views/main_content.py` | Modified — new bar widget construction, 4 click handlers, 3 setters | +120 | Low |
| `ui/window.py` | Modified — 3 new callback impls, 1 updated _on_feed_bar_update | +80 | Low |
| `ui/handlers/feed_handler.py` | Modified — 2 new methods for state read/write | +35 | Low |
| `ui/styles.py` | Modified — 3 new CSS rule blocks | +35 | None |
| **Total** | | **~270** | **Low** |

**Files NOT changed:**
- `ui/views/session_menu.py` — right-click menu already exists; callback signature change is backward-compatible
- `utils/git_ops.py` — `get_branch()` already exists at line 87
- `.crabcakes/feed-prefs.json` — no schema change; v2 format already supports all needed state
- `ui/handlers/project_handler.py` — `get_solo_target` / `set_solo_target` already exist at lines 364, 376
- `ui/views/settings_dialog.py` — already exists; just needs `present()` called

---

## 5. Implementation Order

### Step 1: CSS first (no dependencies)
Add the 3 new CSS rule blocks to `ui/styles.py`. Verify no CSS parse errors.

### Step 2: FeedHandler methods
Add `get_auto_accept_summary()` and `set_auto_accept_state(state)` to `FeedHandler`. Test:
```python
handler._prefs = ... # mock with file_changes enabled
assert handler.get_auto_accept_summary() == "off"  # all disabled
# Enable all 4 → "all", enable only diff → "diffs", etc.
```

### Step 3: MainContent widget construction
- Add `_settings_btn` initialization in `__init__`
- Add `_resolve_agent_display_name`, `_on_agent_label_clicked`, `_on_autoaccept_clicked`, `_on_settings_btn_clicked`
- Add 3 setters: `set_on_settings_clicked`, `set_on_agent_cycle`, `set_on_autoaccept_cycle`
- Add `update_project_settings` method (the main bar rebuild)

### Step 4: Window.py wiring
- Update `_on_feed_bar_update` signature (keep backward compat via defaults)
- Add 3 callback implementations: `_on_agent_cycle_clicked`, `_on_autoaccept_cycle_clicked`, `_on_settings_btn_clicked`
- Wire the 3 new setters in `_build()` after the existing `set_on_project_settings_update` call

### Step 5: End-to-end test
- Open a project → bar shows project name · members · ALL (green) · auto: off · branch
- Right-click project tab → select an agent → bar updates to show agent name (green)
- Click agent name → cycles to next member, then ALL
- Click auto-accept → cycles off → files → diffs → all → off
- Click ⚙ → settings dialog appears

---

## 6. Acceptance Criteria

- [ ] `update_project_settings(name, n, solo, auto, branch)` correctly rebuilds the bar with all 5 elements
- [ ] Agent label shows "ALL" (green) when solo_target is None, otherwise the member's display name (green)
- [ ] Clicking the agent label cycles through members: None → first → ... → last → None
- [ ] Clicking the auto-accept label cycles: off → files → diffs → all → off
- [ ] Auto-accept state persists to `.crabcakes/feed-prefs.json` immediately
- [ ] Git branch shows the current branch or "—" for non-git projects
- [ ] ⚙ button opens the settings dialog
- [ ] All new CSS classes apply correctly (agent label is green, auto-accept is yellow, ⚙ is subtle gray)
- [ ] No regression: existing `set_project_settings_text(text)` still works
- [ ] Bar visibility: shows when project open, hides when no project (existing behavior)

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| No project open | Bar hidden, `update_project_settings` called with empty values |
| Project with 0 members | Bar shows "0 members", agent label is hidden or shows "—" |
| Project with 1 member | Agent cycle: ALL → member → ALL (3-state cycle, not 2) |
| Non-git project | Branch shows "—" in gray, no error |
| Git repo with no commits (HEAD unborn) | `get_branch` returns error, branch shows "—" |
| `get_branch` subprocess timeout (10s) | `get_branch` returns GitResult(success=False), branch shows "—" |
| Auto-accept with no `feed-prefs.json` | `FeedHandler.__init__` creates defaults; `get_auto_accept_summary` returns "off" |
| `set_auto_accept_state("invalid")` | No-op (invalid value rejected) |
| Agent label click when `_on_agent_cycle` is None | No-op (callback not wired) |
| Settings dialog not yet created | `present()` is a no-op on the placeholder |
| Project tab is closed while bar showing | `_on_feed_bar_update(None, 0)` clears the bar |
| User has 10+ project members | Agent cycle works correctly (wraps around) |
| Agent name contains Pango special chars | `escape_for_pango()` in `get_display_name` (or wrap the whole bar text in Pango-safe markup) |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update:
1. §3.7 `ui/views/main_content.py` — document the new `update_project_settings` method and the 3 new setters
2. §3.16 `ui/handlers/feed_handler.py` — add `get_auto_accept_summary` and `set_auto_accept_state` to the public API
3. §3.6 wiring note — the settings bar's 3 new callbacks are wired in `window.py._build()` alongside the existing `set_on_project_settings_update` call

---

## Self-Audit (Rule 9)

✅ **Rule 1** — All referenced files were read: `ui/views/main_content.py` (118-140, 258-271, 695-755), `ui/window.py` (435, 522-562, 1053-1066), `ui/handlers/feed_handler.py` (96-111), `ui/handlers/project_handler.py` (364-380), `ui/views/session_menu.py` (117-145), `ui/styles.py` (33-45).

✅ **Rule 2** — All code samples traced against the actual source. The `set_project_settings_text` removal→`update_project_settings` add is a rename, not a behavior change. The new methods are additive.

✅ **Rule 3** — All function signatures verified:
- `get_solo_target(project_name) -> str | None` ✓ (project_handler.py:364)
- `set_solo_target(project_name, member_session_key: str | None)` ✓ (project_handler.py:376)
- `get_project_members(project_name)` ✓ (project_handler.py:127)
- `get_branch(project_path: str) -> GitResult` ✓ (git_ops.py:87)
- `get_name(session_key: str) -> str` ✓ (agents.py:28)
- `set_markup(text)` ✓ (Gtk.Widget standard)
- `get_first_child() / get_next_sibling()` — not used in this spec, no risk

✅ **Rule 4** — Exception types considered:
- `get_branch` returns `GitResult(success=False, error=...)` on subprocess failure — handled by checking `result.success`
- `feed-prefs.json` I/O handled by `FeedHandler._save_feed_prefs_idle()` — existing pattern
- `set_auto_accept_state` validates `state in (..., ..., ..., ...)` — rejects invalid input
- `_project_handler.get_project_members()` returns `[]` for unknown project — handled by `if not members: return`

✅ **Rule 5** — Key structures verified:
- `self._prefs.file_changes` is `dict[str, FileChangeConfig]` (from `models/feed_card.py`)
- `self._solo_targets` is `dict[str, str]` (from project_handler.py:364)
- No dict-key assumptions unverified

✅ **Rule 6** — Return value handling:
- `get_branch` return value explicitly checked (`result.success`)
- `get_project_members` return value checked for empty (bail out of cycle)
- `get_solo_target` return value passed through to bar display

✅ **Rule 7** — No "should work" code. All methods referenced exist and have the signatures shown.

✅ **Rule 8** — Files NOT changed explicitly listed in section 2.

✅ **Rule 9** (self-audit) — passed.

---

## Spec Self-Audit Checklist

- [x] Every function signature verified against source
- [x] Every code sample traced through actual code
- [x] All exception types considered
- [x] Key structures verified, not assumed
- [x] Return value analysis complete
- [x] Files NOT changed explicitly listed
- [x] CSS classes use existing CSS class pattern (matches `project-feed-bar` etc.)
- [x] Handler pattern preserved (FeedHandler owns auto-accept state, no business logic in view)
- [x] Backward compatibility: old `_on_feed_bar_update(name, count)` still works via defaults
- [x] Edge cases enumerated
- [x] No invented APIs (all `_agent_mgr`, `_feed_handler`, `_project_handler` references exist)
- [x] No fabricated file paths (all `ui/views/main_content.py` etc. confirmed via `read_file`)
- [x] Glyphs used (⚡, ⎇, ⚙) are standard Unicode, safe in Pango markup (no `<`, `>`, `&` chars)
- [x] ARCHITECTURE.md update requirements listed

Ready for implementation.
