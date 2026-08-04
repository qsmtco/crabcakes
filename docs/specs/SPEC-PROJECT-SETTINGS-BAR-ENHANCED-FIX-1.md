# SPEC: Enhanced Project Settings Bar — FIX 1 (revised)

**Date:** 2026-07-31
**Author:** Coder (round 1 spec fix, per audit `SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FINDINGS.md`)
**Status:** Draft — for re-audit
**Supersedes:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED.md`
**Implements:** User request "enhance the project settings bar with agent name, auto-accept level, branch, settings button"
**Target branch:** main

> Architecture compliance. Follows `docs/ARCHITECTURE.md`:
> - §3.6 composition root — `window.py` wires all new callbacks; `main_content.py` stays a pure layout view
> - §3.16 handler pattern — `FeedHandler` remains the sole source of truth for auto-accept state; `ProjectHandler` remains the sole owner of project/solo/branch state. No handler imports another handler.
> - §7 views have no business logic — the settings bar is a pure layout; all state lookups live in handlers/window.
> - Layer rule: `main_content.py` (`ui/`) may not import `models/` or call `feed_store` — it receives resolved primitives (str/int/None) from `window.py`.
>
> This FIX-1 resolves the 18 audit findings (4 CRITICAL, 7 HIGH, 5 MEDIUM, 2 LOW). Every code sample below was traced against the current source.

---

## 1. Overview

### Problem (unchanged)
The project settings bar currently shows only `[crabcakes · 6 members]` — passive display. Expand it to per-project actionable context.

### Solution
```
[crabcakes · 6 members] [● Coder] [⚡ files: off] [⎇ main]        [⚙]
```
- **Agent name** (green). Shows `ALL` when group-broadcasting, else the current solo member's display name. Click cycles members → back to `ALL`.
- **Auto-accept level** (file changes only). Click cycles `off → diffs → files → all → off`. Each state maps to a **distinct, round-trippable** persisted state. Persists to `feed-prefs.json` through `FeedHandler`. The existing **warning gate** is preserved on every activation.
- **Git branch** (read-only). Shows branch name, `(detached HEAD)`, or `—` for non-git. Resolved off the main thread.
- **⚙ button** (right-aligned). Opens the existing Settings dialog via `MainWindow._open_settings()`.

### Scope

| In Scope | Out of Scope |
|---------|-------------|
| Agent name display + click-to-cycle | Right-click tab menu redesign |
| Auto-accept level indicator + click-to-cycle (file changes) | Exec-command auto-accept control (separate axis, stronger warning — explicitly excluded, see §3.3) |
| Git branch display | Branch switching |
| ⚙ button → existing Settings dialog | Cost budget indicator |

---

## 2. Changes by File

### 2.1 `ui/views/main_content.py` — settings bar widget refactor

**Public API changes:**

- `set_project_settings_text(text: str)` — **kept** for backward compat, but its implementation is fixed (BUG #2) to use the sibling-walk clear.
- New: `update_project_settings(project_name, member_count, solo_target, auto_accept_level, branch_name)`.
- `set_on_project_settings_update(cb)` — signature extended to `cb(project_name, member_count, *, solo_target=None, auto_accept_level=None, branch_name=None)`. The main_content stores it as `self._on_feed_bar_update` (existing name preserved).
- New setters: `set_on_settings_clicked(cb)`, `set_on_agent_cycle(cb)`, `set_on_autoaccept_cycle(cb)`.

**Imports required:** none new. `escape_for_pango` already imported (line 31). Gtk already imported.

**New/private methods and helpers (all traced):**

```python
# ── Child-clear helper — replaces the broken `for child in list(box): box.remove(child)` pattern
# (BUG #2). Matches the established codebase pattern used across file_tree.py / diff_viewer.py
# / feed_tab: `while box.get_first_child(): box.remove(box.get_first_child())`.
def _clear_settings_bar(self) -> None:
    """Remove all children from the settings bar box (sibling-walk safe)."""
    while self._project_settings.get_first_child() is not None:
        self._project_settings.remove(self._project_settings.get_first_child())
```

```python
def update_project_settings(self, project_name, member_count,
                            solo_target, auto_accept_level, branch_name):
    """Rebuild the settings bar with the latest per-project state.

    Called by window.py when project opens/closes, members change, solo
    target changes, auto-accept level changes, or branch refresh lands.

    Empty project (project_name falsy) → hide the bar and return (BUG #3).
    """
    if not project_name:
        self._project_settings.set_visible(False)
        self._clear_settings_bar()
        return

    self._clear_settings_bar()
    self._project_settings.set_visible(True)

    # Left-side info row
    info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    info_box.set_hexpand(True)
    info_box.set_halign(Gtk.Align.START)

    # Project name + member count
    safe_name = escape_for_pango(project_name)
    name_label = Gtk.Label()
    name_label.set_markup(
        f'<span font_desc="Sans 10"><b>{safe_name}</b>  ·  '
        f'{member_count} member{"s" if member_count != 1 else ""}</span>'
    )
    name_label.set_margin_start(8)
    info_box.append(name_label)

    # Agent name (green) — clickable to cycle
    agent_text = self._resolve_agent_display_name(solo_target) if solo_target else "ALL"
    agent_label = Gtk.Button(label=agent_text)
    agent_label.set_has_frame(False)   # GTK4 — set_relief()/ReliefStyle do NOT exist (BUG #8)
    agent_label.set_focus_on_click(False)
    agent_label.add_css_class("project-bar-agent")
    agent_label.connect("clicked", lambda _b: self._on_agent_label_clicked(solo_target))
    info_box.append(agent_label)

    # Auto-accept level (file changes) — clickable, cycles off→diffs→files→all→off
    from utils.escaping import xml_escape_text
    level_labels = {
        "off": "⚡ files: off",
        "diffs": "⚡ files: diffs",
        "files": "⚡ files: files",
        "all": "⚡ files: all",
    }
    level_text = level_labels.get(auto_accept_level, "⚡ files: off")
    auto_label = Gtk.Button(label=level_text)
    auto_label.set_has_frame(False)
    auto_label.set_focus_on_click(False)
    auto_label.add_css_class("project-bar-autoaccept")
    auto_label.connect("clicked", lambda _b: self._on_autoaccept_label_clicked(auto_accept_level))
    info_box.append(auto_label)

    # Git branch (read-only)
    branch_text = branch_name or "—"
    branch_label = Gtk.Label()
    branch_label.set_markup(
        f'<span foreground="#a0a0b0" font_desc="Sans 10">⎇ {xml_escape_text(branch_text)}</span>'
    )
    branch_label.set_margin_start(4)
    info_box.append(branch_label)

    self._project_settings.append(info_box)
    self._project_settings.append(self._settings_btn)
```

```python
def _resolve_agent_display_name(self, session_key: str) -> str:
    """Resolve a member session_key to a human-readable name.

    Ordered fallback (mirrors the existing _on_tab_right_click logic):
      1. _agent_mgr.get_name(sk)  (gateway/connected AgentManager)
      2. _agent_runtime_handler.get_special_agents()[sk]  (offline special agents)
      3. session_key as-is.
    Uses the dict returned by ARTH.get_special_agents() — NO reliance on a
    SpecialAgentDef.session_key attribute (BUG #7). SpecialAgentDef has
    conv_id_prefix/display_name, and ARTH keys its dict by conv_id_prefix,
    so this lookup is correct for offline special-agent members.
    """
    if self._agent_mgr is not None:
        name = self._agent_mgr.get_name(session_key)
        if name:
            return name
    if self._agent_runtime_handler is not None:
        special = self._agent_runtime_handler.get_special_agents()
        if session_key in special:
            return special[session_key]
    return session_key
```

```python
def _on_agent_label_clicked(self, current_solo):
    """Callback: agent label clicked → invoke the window-supplied cycle cb."""
    if self._on_agent_cycle is None:
        return
    self._on_agent_cycle(current_solo)

def _on_autoaccept_label_clicked(self, current_level):
    """Callback: auto-accept label clicked → invoke window-supplied cycle cb."""
    if self._on_autoaccept_cycle is None:
        return
    self._on_autoaccept_cycle(current_level)

def _on_settings_btn_clicked(self, _btn):
    if self._on_settings_clicked:
        self._on_settings_clicked()
```

**Setters:**

```python
def set_on_settings_clicked(self, callback):
    """Set callback for the ⚙ button. window.py wires to MainWindow._open_settings()."""
    self._on_settings_clicked = callback

def set_on_agent_cycle(self, callback):
    """Set callback for agent label click. cb(current_solo_session_key) — window owns cycle logic."""
    self._on_agent_cycle = callback

def set_on_autoaccept_cycle(self, callback):
    """Set callback for auto-accept click. cb(current_level) — window owns cycle logic."""
    self._on_autoaccept_cycle = callback
```

**`__init__` additions (after the `self._project_settings` construction ~line 133):**

```python
self._settings_btn = Gtk.Button(label="⚙")
self._settings_btn.set_has_frame(False)
self._settings_btn.set_focus_on_click(False)
self._settings_btn.add_css_class("project-bar-gear")
self._settings_btn.set_margin_end(8)
self._settings_btn.connect("clicked", self._on_settings_btn_clicked)
self._on_settings_clicked = None
self._on_agent_cycle = None
self._on_autoaccept_cycle = None
```

**Fix to existing `set_project_settings_text` / `set_feed_bar_text` (BUG #2):** replace `for child in list(self._project_settings): self._project_settings.remove(child)` with `self._clear_settings_bar()`.

**Line count:** ~130 added/changed.

**Files NOT changed:**
- `ui/views/session_menu.py` — right-click project menu already exists; its `on_select` → `_on_project_solo_selected` → `set_solo_target` path stays untouched. (BUG #15: the bar is updated by the lifecycle dispatch sites in window.py, not synthesized here.)
- `ui/views/settings_dialog.py` — already exists; opened via `MainWindow._open_settings()` (BUG #5).

---

### 2.2 `ui/window.py` — wire the new callbacks

**Lifecycle dispatch sites (verified, per BUG #15):** the bar is updated by four existing call sites that directly call `self._on_feed_bar_update(...)`:
- line 540 — project-opened tuple
- line 554 — project-closed tuple
- line 561 — members-changed `lambda n, m: self._on_feed_bar_update(n, len(m))`
- line 1046 — `_close_project_tab` explicit `self._on_feed_bar_update(None, 0)`

All four pass `(project_name, member_count)`. The extended signature resolves the remaining state from handlers, so these call sites need **no change** — they remain backward compatible.

**Modified `_on_feed_bar_update`:**

```python
def _on_feed_bar_update(self, project_name: str, member_count: int,
                        *, solo_target=None, auto_accept_level=None,
                        branch_name=None):
    """Update the project settings bar with all per-project state.

    Backward compatible: the four lifecycle call sites pass
    (project_name, member_count) and the remaining state is resolved here.
    """
    if not project_name:
        self._main_content.update_project_settings("", 0, None, "off", None)
        return
    # Resolve solo target (BUG #7): from ProjectHandler (source of truth).
    if solo_target is None and self._project_handler is not None:
        solo_target = self._project_handler.get_solo_target(project_name)
    # Resolve auto-accept level (BUG #9/#10): from FeedHandler (source of truth).
    if auto_accept_level is None and self._feed_handler is not None:
        auto_accept_level = self._feed_handler.get_auto_accept_level()
    # Resolve branch lazily when requested (BUG #6/#13): see below.
    if branch_name is None and self._pending_branch_refresh is None \
            and self._project_handler is not None:
        self._schedule_branch_refresh(project_name, member_count,
                                      solo_target, auto_accept_level)
        branch_name = self._cached_branch
    self._main_content.update_project_settings(
        project_name, member_count, solo_target,
        auto_accept_level or "off", branch_name,
    )
```

**Background branch resolution (BUG #13 — off the GTK main thread):** `get_branch()` shells out to GitPython/`git`; must not run on the main thread. Add `_cached_branch: str | None = None` and `_pending_branch_refresh: bool = False` to `__init__`.

```python
def _schedule_branch_refresh(self, project_name, member_count, solo_target, auto_accept_level):
    """Resolve the git branch in a background thread; refresh the bar when done.

    Guards against a re-entrant rebuild: _pending_branch_refresh is set while
    the thread runs so _on_feed_bar_update cannot spawn a second branch
    worker. On completion we call _on_feed_bar_update again with the same
    state plus the resolved branch — idempotent because update_project_settings
    recomputes the full row each call (BUG #16: always main-thread; the bar is
    a singleton box reparented across overlays, so main-thread rebuild is safe).
    """
    if self._pending_branch_refresh:
        return
    self._pending_branch_refresh = True
    import threading
    t = threading.Thread(
        target=self._resolve_branch_worker,
        args=(project_name, member_count, solo_target, auto_accept_level),
        daemon=True,
    )
    t.start()

def _resolve_branch_worker(self, project_name, member_count, solo_target, auto_accept_level):
    try:
        path = self._project_handler.get_active_project_path()  # BUG #6
        branch = None
        if path:
            from utils.git_ops import get_branch
            result = get_branch(path)
            # get_branch returns success=True with "(detached HEAD)" for detached
            # (BUG #12); display it verbatim. Failure (non-git, unborn) → None → "—".
            branch = result.stdout if result.success else None
        self._pending_branch_refresh = False
        self._cached_branch = branch
        from gi.repository import GLib
        # Resolve vars fresh on main thread at dispatch time to avoid stale refs.
        GLib.idle_add(
            lambda: self._on_feed_bar_update(project_name, member_count,
                                             solo_target=solo_target,
                                             auto_accept_level=auto_accept_level,
                                             branch_name=branch),
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("branch refresh failed")
        self._pending_branch_refresh = False
```

**New callback implementations (window owns all cycle logic):**

```python
def _on_agent_cycle_clicked(self, current_solo):
    """Cycle agent label: ALL(None) → member[0] → ... → member[N-1] → ALL(None).

    ORDER: current None/ALL → first member; current member → next member;
    last member → None/ALL. With exactly ONE member this is a 2-state cycle
    (BUG #17 — not 3-state); generally (N+1) distinct states.
    """
    project_name = self._project_handler.get_active_project_name() if self._project_handler else None
    if not project_name:
        return
    members = self._project_handler.get_project_members(project_name)
    if not members:
        return
    if current_solo is None or current_solo not in members:
        next_solo = members[0]
    else:
        idx = members.index(current_solo)
        next_solo = members[idx + 1] if idx < len(members) - 1 else None
    self._project_handler.set_solo_target(project_name, next_solo)
    # Refresh members-changed-equivalent bar update.
    self._on_feed_bar_update(project_name, len(members), solo_target=next_solo)

def _on_autoaccept_cycle_clicked(self, current_level):
    """Cycle auto-accept (file changes): off → diffs → files → all → off.

    Delegates to FeedHandler.set_auto_accept_level() which owns persistence,
    the warning gate (BUG #11), and _refresh_auto_accept_state() (BUG #4).
    """
    cycle = {"off": "diffs", "diffs": "files", "files": "all", "all": "off"}
    next_level = cycle.get(current_level, "off")
    if self._feed_handler is not None:
        self._feed_handler.set_auto_accept_level(next_level)
    self._on_feed_bar_update(
        self._project_handler.get_active_project_name() or "",
        0,
        auto_accept_level=self._feed_handler.get_auto_accept_level() if self._feed_handler else "off",
    )

def _on_settings_btn_clicked(self):
    """⚙ → open the existing Settings dialog (BUG #5: no persistent instance)."""
    self._open_settings()
```

**Wiring (after existing `set_on_project_settings_update` call ~line 435):**

```python
self._main_content.set_on_settings_clicked(self._on_settings_btn_clicked)
self._main_content.set_on_agent_cycle(self._on_agent_cycle_clicked)
self._main_content.set_on_autoaccept_cycle(self._on_autoaccept_cycle_clicked)
```

**`__init__` additions:** `self._cached_branch = None`, `self._pending_branch_refresh = False`.

**Line count:** ~110 added.

---

### 2.3 `ui/handlers/feed_handler.py` — auto-accept level read/write

Source of truth stays in `FeedHandler` (BUG #9/#10/#11). Two new public methods + one private commit helper. All routed through the existing v2 machinery.

```python
def get_auto_accept_level(self) -> str:
    """Return the file-change auto-accept level as a single string.

    Values: "off" | "diffs" | "files" | "all". Scoped to FILE changes only;
    exec_command is a separate axis with its own toggle and is intentionally
    NOT collapsed into this label (BUG #10 — we document this explicitly and
    reflect it in the label "⚡ files: ..." so it is not presented as a
    complete auto-accept summary).

    Mapping over the four file_changes entries (BUG #9 — each level maps to
    a DISTINCT persisted state, so get/set round-trip losslessly):
      - "off":   diff off AND file_created/modified/deleted all off
      - "diffs": diff on  AND file_created/modified/deleted all off
      - "files": diff off AND file_created/modified/deleted all on
      - "all":   all four on
    Any other combination (partial/mixed) reads back deterministically as
    "all" if diff is on and "files" otherwise — a defensive fallback only;
    set_auto_accept_level never writes mixed states.
    """
    fc = self._prefs.file_changes
    diff = fc["diff"].enabled
    group = all(fc[ct].enabled for ct in ("file_created", "file_modified", "file_deleted"))
    group_off = not any(fc[ct].enabled for ct in ("file_created", "file_modified", "file_deleted"))
    if not diff and group_off:
        return "off"
    if diff and group_off:
        return "diffs"
    if diff and group:
        return "all"
    return "files"
```

```python
def set_auto_accept_level(self, level: str) -> None:
    """Set file-change auto-accept level and persist via feed-prefs.json.

    level ∈ {"off","diffs","files","all"}; invalid → no-op.

    Enabling states ("diffs"/"files"/"all") route through the existing
    warning gate (BUG #11) — the same `set_show_auto_accept_warning`
    category/agent/confirm/cancel contract used by the v2 toggles — and
    only commit on confirm, exactly like `_on_diffs_toggled`/`_on_files_toggled`.

    All successful commits call `_refresh_auto_accept_state()` (BUG #4),
    which syncs the FeedTab view and schedules the debounced persistence
    save. This setter does NOT call `_save_feed_prefs_idle()` directly —
    that is `_refresh_auto_accept_state`'s job.
    """
    if level not in ("off", "diffs", "files", "all") or self._prefs is None:
        return
    if level == "off":
        for ct in self._prefs.file_changes:
            self._prefs.file_changes[ct].enabled = False
        # exec untouched — bar is file-scoped (BUG #10)
        self._refresh_auto_accept_state()
        return
    category = "diffs" if level == "diffs" else "files"
    if self._show_auto_accept_warning is not None:
        self._show_auto_accept_warning(
            category,
            self._resolve_agent_name_for_dialog(),
            on_confirm=lambda lvl=level: self._commit_auto_accept_level(lvl),
            on_cancel=lambda: self._refresh_auto_accept_state(),
        )
    else:
        self._commit_auto_accept_level(level)

def _commit_auto_accept_level(self, level: str) -> None:
    """Write the distinct file-change state and sync (internal)."""
    fc = self._prefs.file_changes
    if level == "diffs":
        fc["diff"].enabled = True
        for ct in ("file_created", "file_modified", "file_deleted"):
            fc[ct].enabled = False
    elif level == "files":
        fc["diff"].enabled = False
        for ct in ("file_created", "file_modified", "file_deleted"):
            fc[ct].enabled = True
    elif level == "all":
        for ct in self._prefs.file_changes:
            fc[ct].enabled = True
    self._refresh_auto_accept_state()
```

**Imports required:** none new.

**Line count:** ~55 added.

**Files NOT changed:**
- `.crabcakes/feed-prefs.json` — v2 schema unchanged; `from_dict`/`to_dict` already handle all four file_changes + exec.
- `models/feed_card.py` — `AutoAcceptPrefs`/`FileChangePref` need no schema change.

---

### 2.4 `ui/styles.py` — CSS

Use GTK4-compatible `:hover`/`:active` pseudo-classes. No `text-align` (unsupported in GTK4 CSS — use padding/halign). CSS classes: `project-bar-agent`, `project-bar-autoaccept`, `project-bar-gear`.

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
    background: transparent;
    border: none;
    box-shadow: none;
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
    background: transparent;
    border: none;
    box-shadow: none;
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
    background: transparent;
    border: none;
    box-shadow: none;
}
.project-bar-gear:hover {
    background: rgba(255, 255, 255, 0.1);
}
```

**Files NOT changed:** `ui/styles.py` `.project-feed-bar` rule (the bar background) stays as-is; only inner interactive elements get the new classes.

---

## 3. Data Flow

### Agent name update on the four lifecycle dispatch sites (BUG #15)
1. `ProjectHandler.open_project/close_project/toggle_agent` run → fire their window callbacks (lines 540/554/561)
2. Callback calls `self._on_feed_bar_update(n, len(m))` → new signature resolves `solo_target` from `ProjectHandler.get_solo_target(project_name)`
3. `window._on_feed_bar_update` → `main_content.update_project_settings(...)`
4. Bar rebuilds; agent label shows `ALL` or the resolved display name (via `_resolve_agent_display_name`)

### Solo selection via right-click menu (unchanged, now reflected)
1. Right-click project tab → `show_project_menu` → `on_select` → `_on_project_solo_selected` → `ProjectHandler.set_solo_target`
2. `toggle_agent`/member-change isn't fired, so the bar needs a refresh. **New:** wire a solo-change refresh. The cleanest hook is `set_solo_target` itself: after it sets `self._solo_targets[project_name]`, it calls `self._on_solo_target_changed(project_name)` — a new callback slot (None by default). window.py wires it to a lambda that recomputes members + calls `_on_feed_bar_update`. *(In `project_handler.py` — see §2.5.)*

### Agent cycle on click
1. Click agent label → `main_content._on_agent_label_clicked(current_solo)` → `self._on_agent_cycle(current_solo)`
2. `window._on_agent_cycle_clicked` reads members, advances index (or to None), calls `ProjectHandler.set_solo_target`
3. `set_solo_target` fires `_on_solo_target_changed` (new) → bar refreshes

### Auto-accept cycle
1. Click auto label → `main_content._on_autoaccept_label_clicked(current)` → `self._on_autoaccept_cycle(current)`
2. `window._on_autoaccept_cycle_clicked` → `FeedHandler.set_auto_accept_level(next)`
3. If enabling and a warning callback is wired, the warning dialog shows; on confirm → `_commit_auto_accept_level` → `_refresh_auto_accept_state()` → FeedTab synced + debounced save
4. window then calls `_on_feed_bar_update` with the new level → bar rebuilds

### Branch
1. On project-open `_on_feed_bar_update`, branch_name not supplied → `_schedule_branch_refresh` spawns a daemon thread
2. Thread calls `ProjectHandler.get_active_project_path()` + `git_ops.get_branch(path)`; handles detached HEAD (display `(detached HEAD)`, BUG #12) and non-git (None → `—`)
3. `GLib.idle_add` → `_on_feed_bar_update` again with branch → bar shows `⎇ main` / `⎇ (detached HEAD)` / `⎇ —`

### Settings dialog
1. Click ⚙ → `main_content._on_settings_btn_clicked` → `self._on_settings_clicked()`
2. `window._on_settings_btn_clicked` → `self._open_settings()` → creates a fresh `SettingsDialog` (BUG #5: reuse existing factory, no persistent instance)

---

## 4. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `ui/views/main_content.py` | Modified — new bar widgets, 3 click handlers, 3 setters, clear helper, fix `list(box)` pattern | +130 | Low |
| `ui/window.py` | Modified — extended `_on_feed_bar_update`, 3 callback impls, branch worker, wiring, 2 init fields | +110 | Medium (integration) |
| `ui/handlers/feed_handler.py` | Modified — `get_auto_accept_level` / `set_auto_accept_level` / `_commit_auto_accept_level` | +55 | Medium |
| `ui/handlers/project_handler.py` | Modified — `_on_solo_target_changed` slot fired by `set_solo_target` + setter | +12 | Low |
| `ui/styles.py` | Modified — 3 new CSS rule blocks | +45 | None |
| **Total** | | **~350** | **Low-Medium** |

**Files NOT changed (all already correct):**
- `ui/views/session_menu.py` — right-click menu + `on_select` path intact.
- `ui/views/settings_dialog.py` — opened via `_open_settings()`.
- `utils/git_ops.py` — `get_branch()` at line 87 used as-is (incl. detached-HEAD contract).
- `models/feed_card.py`, `.crabcakes/feed-prefs.json` — v2 schema sufficient.
- `ui/styles.py` `.project-feed-bar` — kept.

---

## 5. Implementation Order

### Step 1 — CSS (no deps)
Add the 3 rule blocks to `ui/styles.py`. Verify no CSS parse errors (no `text-align`, GTK4-safe).

### Step 2 — FeedHandler
Add `get_auto_accept_level` / `set_auto_accept_level` / `_commit_auto_accept_level`. Unit test against a real `AutoAcceptPrefs`:
```python
prefs = AutoAcceptPrefs()                     # all off
assert handler.get_auto_accept_level() == "off"
handler.set_auto_accept_level("diffs")        # (no warning callback wired → commits directly)
assert prefs.file_changes["diff"].enabled and not prefs.file_changes["file_created"].enabled
assert handler.get_auto_accept_level() == "diffs"
handler.set_auto_accept_level("files")
assert prefs.file_changes["diff"].enabled is False
assert all(prefs.file_changes[ct].enabled for ct in ("file_created","file_modified","file_deleted"))
assert handler.get_auto_accept_level() == "files"
handler.set_auto_accept_level("all")
assert all(fc.enabled for fc in prefs.file_changes.values())
assert handler.get_auto_accept_level() == "all"
handler.set_auto_accept_level("bogus")        # no-op
handler.set_auto_accept_level("off")
assert not any(fc.enabled for fc in prefs.file_changes.values())
```
Also assert `_refresh_auto_accept_state` was called after each commit (spy on it), and that a wired `set_show_auto_accept_warning` receives `("files", agent, on_confirm, on_cancel)` for `"files"`/`"all"` and that on_cancel does NOT commit.

### Step 3 — MainContent
Add `_settings_btn` init, `_clear_settings_bar`, `_resolve_agent_display_name`, 3 click handlers, 3 setters, `update_project_settings`, and fix `set_project_settings_text`/`set_feed_bar_text`.

### Step 4 — ProjectHandler
Add `_on_solo_target_changed` slot + fire in `set_solo_target`; add `set_on_solo_target_changed` setter. Wire in window.py.

### Step 5 — window.py wiring
Extend `_on_feed_bar_update`, add 3 callback impls, branch worker, wire the 3 main_content setters + the project_handler solo-change callback.

### Step 6 — End-to-end
Open a project → `[name · N] [ALL] [⚡ files: off] [⎇ branch] [⚙]`; right-click → agent shows green; click agent cycles; click auto-accept cycles (warning on enable); ⚙ opens settings.

---

## 6. Acceptance Criteria

- [ ] `update_project_settings` rebuilds the bar with all 5 elements; shows `ALL` for `solo_target=None`, else the resolved display name (green) (BUG #8/#18: color via CSS, not a dead `color` var).
- [ ] Empty project (falsy name) → bar hidden (BUG #3).
- [ ] Agent click cycles `None → m0 → … → mN-1 → None`; exactly 1 member → 2-state cycle (BUG #17).
- [ ] Auto-accept click cycles `off → diffs → files → all → off`; each state persists distinctly and round-trips via `get_auto_accept_level` (BUG #9).
- [ ] Enabling file auto-accept shows the existing warning gate and only commits on confirm (BUG #11); state also reflects in FeedTab via `_refresh_auto_accept_state` (BUG #4).
- [ ] Label reads `⚡ files: …` and exec mode is documented/excluded, not mislabeled as a complete summary (BUG #10).
- [ ] Branch shows name / `(detached HEAD)` / `—`; resolved off the main thread (BUG #12/#13); uses `get_active_project_path()` not an invented `_active_project` tuple (BUG #6).
- [ ] ⚙ opens a fresh Settings dialog via `_open_settings()` (BUG #5).
- [ ] No `Gtk.ReliefStyle`, `set_relief()`, `Gtk.Container`, or `list(Gtk.Box)` in changed code (BUG #8/#2); agent name uses ARTH `get_special_agents()` dict (BUG #7).
- [ ] Existing `set_project_settings_text(text)` still works (deprecated, unfixed callers).
- [ ] Tab switching during a branch refresh is safe (main-thread rebuild, BUG #16).

## 7. Edge Cases

| Case | Expected |
|------|----------|
| No project open | `_on_feed_bar_update("",0)` → bar hidden (BUG #3) |
| 0 members | `[name · 0 members] [ALL] …`, agent cycle no-ops (`get_project_members` empty) |
| 1 member | 2-state agent cycle (BUG #17) |
| Non-git project | branch None → `—` |
| Detached HEAD | `(detached HEAD)` displayed verbatim (BUG #12) |
| Branch resolve slow/errors | worker catches, branch None → `—`; no main-thread block (BUG #13) |
| No `feed-prefs.json` | FeedHandler defaults; `get_auto_accept_level` → `off` |
| `set_auto_accept_level("invalid")` | no-op |
| Warning dialog cancelled | no commit; bar stays at current level |
| Agent label click w/o `_on_agent_cycle` | no-op |
| Auto label click w/o `_on_autoaccept_cycle` | no-op |
| Project tab closed mid-branch-refresh | worker dispatches with captured state; `_on_feed_bar_update("",0)` hides bar |
| Agent name has Pango specials | `escape_for_pango` on name/branch (name via Button label = plain text, branch via `xml_escape_text` in markup) |
| 10+ members | cycle wraps correctly |

## 8. ARCHITECTURE.md Updates Required

1. §3.16 `ui/handlers/feed_handler.py` — add `get_auto_accept_level` / `set_auto_accept_level` to the public API; note the file-scoped (files-only) semantics and that exec is a separate axis.
2. The module-responsibility section covering `ui/views/main_content.py` — document `update_project_settings`, the 3 new setters, and the child-clear helper. *(Correct the stale §3.7 citation that the original spec misused — BUG #14: §3.7 documents `left_panel.py`, not `main_content.py`; add the MainContent API under the actual MainContent responsibility section.)*
3. §3.6 wiring note — document the settings bar's 3 new callbacks + the project_handler `_on_solo_target_changed` slot wired in `window.py`.

---

## 9. How Each Audit Finding Is Addressed

| # | Sev | Fix |
|---|-----|-----|
| 1 | CRIT | Removed the nonexistent `from models.feed_card import _auto_accept_state_str` import entirely; state read via `FeedHandler.get_auto_accept_level()` |
| 2 | CRIT | Replaced `for child in list(self._project_settings)` with `_clear_settings_bar()` sibling-walk; fixed existing `set_project_settings_text`/`set_feed_bar_text` |
| 3 | CRIT | `update_project_settings` hides the bar on empty project and returns |
| 4 | CRIT | `set_auto_accept_level` commits via `_refresh_auto_accept_state()` (syncs FeedTab + debounced save); does not call `_save_feed_prefs_idle()` as a substitute |
| 5 | HIGH | ⚙ routes to `MainWindow._open_settings()` (fresh `SettingsDialog` each call); no invented `_settings_dialog` instance |
| 6 | HIGH | Branch via `ProjectHandler.get_active_project_path()`; no `_active_project` tuple |
| 7 | HIGH | Name via `ARTH.get_special_agents()` dict (keyed by `conv_id_prefix`); no `AgentDefinition.session_key` |
| 8 | HIGH | Replaced `Gtk.ReliefStyle`/`set_relief()` with `set_has_frame(False)` + CSS |
| 9 | HIGH | Distinct, round-trippable states: `diffs`=diff-only, `files`=3-file-group-only, `all`=all four |
| 10 | HIGH | bar scoped to file changes, labeled `⚡ files: …`, exec excluded & documented |
| 11 | HIGH | activation routes through `_show_auto_accept_warning` gate; commit only on confirm |
| 12 | MED | detached-HEAD contract documented + displayed verbatim; non-git → `—` |
| 13 | MED | branch resolved in background thread, dispatched via `GLib.idle_add` |
| 14 | MED | corrected architecture citation; MainContent API added under actual section |
| 15 | MED | lifecycle dispatch sites (window 540/554/561/1046) specified; no overclaimed callback dispatch |
| 16 | MED | reparenting invariant documented; all bar rebuilds main-thread; re-entrancy guard in branch worker |
| 17 | LOW | 1-member → 2-state cycle; general (N+1)-state wording |
| 18 | LOW | removed dead `color` var; color via CSS class |

---

## 10. Spec Self-Audit (Rule 9)

- **Rule 1** — Read `ui/views/main_content.py` (full), `ui/window.py` (wiring + `_on_feed_bar_update` + `_open_settings`), `ui/handlers/feed_handler.py` (prefs + v2 toggles + `_refresh_auto_accept_state`), `ui/handlers/project_handler.py` (solo + members + active path), `models/feed_card.py` (AutoAcceptPrefs), `agent/special_agents.py` (SpecialAgentDef), `ui/handlers/agent_runtime_handler.py` (`get_special_agents`), `utils/escaping.py` (`escape_for_pango`/`xml_escape_text`), `utils/git_ops.py` (`get_branch`), `ui/styles.py`-adjacent CSS patterns, `ui/wiring.py`.
- **Rule 2/3** — All signatures traced: `get_solo_target(project_name)` ✓, `set_solo_target(project_name, sk|None)` ✓, `get_project_members(project_name)` ✓, `get_active_project_name()` ✓, `get_active_project_path()` ✓, `get_branch(path)->GitResult` ✓, `ARTH.get_special_agents()->dict[str,str]` ✓, `_open_settings()` ✓. GTK4 APIs `set_has_frame(False)`/`set_focus_on_click(False)` used (no relief/ReliefStyle/Container).
- **Rule 4** — `get_branch` returns GitResult (never raises); worker wraps in try/except; `set_auto_accept_level` guards `_prefs is None` and invalid level; handlers null-guarded.
- **Rule 5** — `AutoAcceptPrefs.file_changes` keyed `diff|file_created|file_modified|file_deleted`; `_solo_targets: dict[project, sk|None]`; `ARTH` dict keyed by `conv_id_prefix` — all verified.
- **Rule 6** — `get_branch` return checked (`result.success`); `get_auto_accept_level` return consumed; `set_auto_accept_level` side-effects documented.
- **Rule 7** — Every code path traced above against source. No "should work" samples.
- **Rule 8** — Files NOT changed listed in §2.x and §4.
- **Rule 10** — This is a *spec* fix (no files to change yet). Implementation acceptance + test guidance in §5/§6. The round-trip and warning-gate unit tests are specified in Step 2.
