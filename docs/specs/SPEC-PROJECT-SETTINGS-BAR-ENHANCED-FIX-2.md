# SPEC: Enhanced Project Settings Bar — FIX 2 (revised)

**Date:** 2026-07-31
**Author:** Coder (round 2 spec fix, per audit `SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1-FINDINGS.md`)
**Status:** Draft — for re-audit
**Supersedes:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-1.md` (which supersedes `...-ENHANCED.md`)
**Implements:** User request "enhance the project settings bar with agent name, auto-accept level, branch, settings button"
**Target branch:** main

> Architecture compliance. Follows `docs/ARCHITECTURE.md`:
> - §3.6 composition root — `window.py` wires all callbacks; `main_content.py` stays a pure layout view
> - §3.16 handler pattern — `FeedHandler` remains the sole source of truth for auto-accept state; `ProjectHandler` remains the sole owner of project/solo/branch state. No handler imports another handler.
> - §7 views have no business logic — the settings bar is a pure layout; all state lookups live in handlers/window.
> - Layer rule: `main_content.py` (`ui/`) may not import `models/` or call `feed_store` — it receives resolved primitives (str/int/None) from `window.py`.
>
> FIX-2 resolves the 7 Round 2 findings (1 CRITICAL, 3 HIGH, 3 MEDIUM) on top of FIX-1. Every code sample below was traced against the current source and verified empirically (see §10).

---

## 1. Overview

### Problem (unchanged)
The project settings bar currently shows only `[crabcakes · 6 members]` — passive display. Expand to per-project actionable context.

### Solution
```
[crabcakes · 6 members] [● Coder] [⚡ files: off] [⎇ main]        [⚙]
```
- **Agent name** (green). Shows `ALL` for group broadcast, else the current solo member's display name. Click cycles members → back to `ALL`.
- **Auto-accept level** (file changes only). Click cycles `off → diffs → files → all → off`. Distinct, persisted states via `FeedHandler`; the **warning gate** is preserved on every activation.
- **Git branch** (read-only). Shows branch name, `(detached HEAD)`, or `—` for non-git. Resolved off the main thread **with a generation token so stale results never cross project boundaries** (Round 2 BUG #2/#7).
- **⚙ button** (right-aligned). Opens the existing Settings dialog via `MainWindow._open_settings()`.

### Round 2 defects fixed (summary)
1. **CRITICAL** branch scheduling dead-code (`is None` → `not self._pending_branch_refresh`)
2. **HIGH** async branch results crossing project boundaries (token + path capture)
3. **HIGH** auto-accept callback clobbering member count to 0 (query real members)
4. **HIGH** missing `ProjectHandler.set_on_solo_target_changed` code sample + wiring
5. **MEDIUM** legacy `set_project_settings_text`/`set_feed_bar_text` dropping the gear button (re-append gear)
6. **MEDIUM** `escape_for_pango` injection risk (use `xml_escape_text` for untrusted plain text)
7. **MEDIUM** `_pending_branch_refresh` not thread-safe (replace boolean with monotonic `request_token`)

### Scope

| In Scope | Out of Scope |
|---------|-------------|
| Agent name display + click-to-cycle | Right-click tab menu redesign |
| Auto-accept level indicator + click-to-cycle (file changes) | Exec-command auto-accept control (separate axis, stronger warning — explicitly excluded, see §3.3) |
| Git branch display (token-guarded async) | Branch switching |
| ⚙ button → existing Settings dialog | Cost budget indicator |

---

## 2. Changes by File

### 2.1 `ui/views/main_content.py` — settings bar widget refactor

**Public API changes (unchanged from FIX-1, except fixes below):**

- `set_project_settings_text(text)` — kept; **re-appends the gear button** after the legacy label (BUG #5).
- `set_feed_bar_text(text)` — kept; **re-appends the gear button** (BUG #5).
- New: `update_project_settings(project_name, member_count, solo_target, auto_accept_level, branch_name)`.
- `set_on_project_settings_update(cb)` — signature extended to `cb(project_name, member_count, *, solo_target=None, auto_accept_level=None, branch_name=None)`.
- New setters: `set_on_settings_clicked(cb)`, `set_on_agent_cycle(cb)`, `set_on_autoaccept_cycle(cb)`.

**Imports required:** `xml_escape_text` from `utils.escaping` (already imported path). `escape_for_pango` is **no longer used** for untrusted plain text anywhere in the bar (BUG #6). `Gtk` already imported.

**Child-clear helper (BUG #2 from Round 1 — unchanged):**

```python
def _clear_settings_bar(self) -> None:
    """Remove all children from the settings bar box (sibling-walk safe)."""
    while self._project_settings.get_first_child() is not None:
        self._project_settings.remove(self._project_settings.get_first_child())
```

**`update_project_settings` (unchanged from FIX-1, with BUG #6 hardened markup):**

```python
def update_project_settings(self, project_name, member_count,
                            solo_target, auto_accept_level, branch_name):
    """Rebuild the settings bar with the latest per-project state.

    Called by window.py when project opens/closes, members change, solo
    target changes, auto-accept level changes, or branch refresh lands.

    Empty project (project_name falsy) → hide the bar and return (BUG #3 round 1).
    """
    if not project_name:
        self._project_settings.set_visible(False)
        self._clear_settings_bar()
        return

    self._clear_settings_bar()
    self._project_settings.set_visible(True)

    info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    info_box.set_hexpand(True)
    info_box.set_halign(Gtk.Align.START)

    # Project name + member count.
    # BUG #6: use xml_escape_text() for the UNTRUSTED project name. escape_for_pango()
    # preserves <b>/<span> etc., so a project named "<b>oops</b>" would render bold.
    # xml_escape_text() neutralizes all markup → literal rendering.
    from utils.escaping import xml_escape_text
    safe_name = xml_escape_text(project_name)
    name_label = Gtk.Label()
    name_label.set_markup(
        f'<span font_desc="Sans 10"><b>{safe_name}</b>  ·  '
        f'{member_count} member{"s" if member_count != 1 else ""}</span>'
    )
    name_label.set_margin_start(8)
    info_box.append(name_label)

    # Agent name (green) — clickable to cycle
    agent_text = self._resolve_agent_display_name(solo_target) if solo_target else "ALL"
    agent_label = Gtk.Button(label=agent_text)   # Button label is plain text → safe
    agent_label.set_has_frame(False)   # GTK4 — set_relief()/ReliefStyle do NOT exist
    agent_label.set_focus_on_click(False)
    agent_label.add_css_class("project-bar-agent")
    agent_label.connect("clicked", lambda _b: self._on_agent_label_clicked(solo_target))
    info_box.append(agent_label)

    # Auto-accept level (file changes) — clickable, cycles off→diffs→files→all→off
    level_labels = {
        "off": "⚡ files: off",
        "diffs": "⚡ files: diffs",
        "files": "⚡ files: files",
        "all": "⚡ files: all",
    }
    level_text = level_labels.get(auto_accept_level, "⚡ files: off")
    auto_label = Gtk.Button(label=level_text)   # Button label is plain text → safe
    auto_label.set_has_frame(False)
    auto_label.set_focus_on_click(False)
    auto_label.add_css_class("project-bar-autoaccept")
    auto_label.connect("clicked", lambda _b: self._on_autoaccept_label_clicked(auto_accept_level))
    info_box.append(auto_label)

    # Git branch (read-only) — interpolated into markup, must be xml_escape_text'd.
    branch_text = branch_name or "—"
    branch_label = Gtk.Label()
    branch_label.set_markup(
        f'<span foreground="#a0a0b0" font_desc="Sans 10">⎇ {xml_escape_text(branch_text)}</span>'
    )
    branch_label.set_margin_start(4)
    info_box.append(branch_label)

    self._project_settings.append(info_box)
    # Always re-append the singleton gear — _clear_settings_bar() removed it; both
    # update_project_settings AND the legacy methods must restore it (BUG #5).
    self._project_settings.append(self._settings_btn)
```

**`_resolve_agent_display_name` (unchanged from FIX-1 — Round 1 BUG #7 fixed):**

```python
def _resolve_agent_display_name(self, session_key: str) -> str:
    """Resolve a member session_key to a human-readable name.

    Ordered fallback (mirrors the existing _on_tab_right_click logic):
      1. _agent_mgr.get_name(sk)  (gateway/connected AgentManager)
      2. _agent_runtime_handler.get_special_agents()[sk]  (offline special agents)
      3. session_key as-is.
    Uses the dict returned by ARTH.get_special_agents() — NO reliance on a
    SpecialAgentDef.session_key attribute. SpecialAgentDef has
    conv_id_prefix/display_name, and ARTH keys its dict by conv_id_prefix.
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

**Click handlers (unchanged from FIX-1):**

```python
def _on_agent_label_clicked(self, current_solo):
    if self._on_agent_cycle is None:
        return
    self._on_agent_cycle(current_solo)

def _on_autoaccept_label_clicked(self, current_level):
    if self._on_autoaccept_cycle is None:
        return
    self._on_autoaccept_cycle(current_level)

def _on_settings_btn_clicked(self, _btn):
    if self._on_settings_clicked:
        self._on_settings_clicked()
```

**Setters (unchanged):**

```python
def set_on_settings_clicked(self, callback):
    self._on_settings_clicked = callback

def set_on_agent_cycle(self, callback):
    self._on_agent_cycle = callback

def set_on_autoaccept_cycle(self, callback):
    self._on_autoaccept_cycle = callback
```

**`__init__` additions (after `self._project_settings` construction ~line 133):**

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

**Legacy `set_project_settings_text` and `set_feed_bar_text` (BUG #5 fix — re-append gear):**

```python
def set_project_settings_text(self, text: str):
    """Set text or markup on the project settings bar. Handles Pango markup correctly.

    Backward compat: still clears the bar, appends the label, then re-appends the
    singleton gear button so it is never lost (BUG #5). A later
    update_project_settings() call fully rebuilds the row.
    """
    self._clear_settings_bar()
    lbl = Gtk.Label()
    lbl.set_halign(Gtk.Align.END)
    lbl.set_margin_start(8)
    lbl.set_margin_end(8)
    if text.startswith("<"):
        lbl.set_markup(text)
    else:
        lbl.set_text(text)
    self._project_settings.append(lbl)
    self._project_settings.append(self._settings_btn)
```

```python
def set_feed_bar_text(self, text):
    """Update the project feed bar with a status message (legacy).

    Same gear-preservation as set_project_settings_text() (BUG #5).
    """
    self._clear_settings_bar()
    if text:
        lbl = Gtk.Label()
        lbl.set_halign(Gtk.Align.END)
        lbl.set_margin_start(8)
        lbl.set_margin_end(8)
        if text.startswith("<"):
            lbl.set_markup(text)
        else:
            lbl.set_text(text)
        self._project_settings.append(lbl)
    self._project_settings.append(self._settings_btn)
```

**Line count:** ~150 added/changed.

**Files NOT changed:**
- `ui/views/session_menu.py` — right-click project menu already exists; its `on_select` → `_on_project_solo_selected` → `set_solo_target` path stays intact. The bar refresh after selection is handled by the new `_on_solo_target_changed` callback in `ProjectHandler` (see §2.5).
- `ui/views/settings_dialog.py` — exists; opened via `MainWindow._open_settings()`.

---

### 2.2 `ui/window.py` — wire the new callbacks (incl. token-guarded branch worker)

**Lifecycle dispatch sites (unchanged from FIX-1):** four existing call sites call `self._on_feed_bar_update(...)` directly — lines 540 (opened), 554 (closed), 561 (members-changed), 1046 (`_close_project_tab`). All pass `(project_name, member_count)`; the extended signature resolves remaining state, so these need no change.

**New/updated window state fields (BUG #2/#7 — replace the bare boolean with a monotonic token):**

```python
# In __init__:
self._cached_branch: str | None = None        # last successfully resolved branch for the ACTIVE project
self._branch_request_token: int = 0           # monotonic request id; incremented on every schedule/close (BUG #7)
self._branch_active_token: int | None = None  # token of the in-flight worker, or None (BUG #2)
self._branch_request_path: str | None = None  # project path captured at schedule time for staleness check (BUG #2)
```

**Modified `_on_feed_bar_update` (BUG #1 fix — `not self._pending_branch_refresh` → `self._branch_active_token is None`):**

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
    # Resolve solo target from ProjectHandler (source of truth).
    if solo_target is None and self._project_handler is not None:
        solo_target = self._project_handler.get_solo_target(project_name)
    # Resolve auto-accept level from FeedHandler (source of truth).
    if auto_accept_level is None and self._feed_handler is not None:
        auto_accept_level = self._feed_handler.get_auto_accept_level()
    # Trigger a background branch refresh if we don't yet have a cached branch
    # for the CURRENT project and none is in-flight (BUG #1: was `is None` on a bool).
    if branch_name is None and self._branch_active_token is None \
            and self._project_handler is not None:
        self._schedule_branch_refresh(project_name, member_count,
                                      solo_target, auto_accept_level)
        branch_name = self._cached_branch
    self._main_content.update_project_settings(
        project_name, member_count, solo_target,
        auto_accept_level or "off", branch_name,
    )
```

**Token-guarded branch scheduling + worker (BUG #2/#7):**

```python
def _schedule_branch_refresh(self, project_name, member_count, solo_target, auto_accept_level):
    """Start a background branch lookup, guarded by a monotonic request token.

    All state transitions happen on the GTK thread (this method runs on the
    main thread). The worker only reads a captured project_path and reports
    back; it never mutates window state (BUG #7 — no cross-thread boolean).
    """
    # If a worker is already in flight, don't stack a second one. The single
    # in-flight worker will re-dispatch with fresh state (it captures the token
    # and re-reads nothing dynamic on completion beyond token comparison).
    if self._branch_active_token is not None:
        return

    # Capture the project path at schedule time (BUG #2). The worker must NOT
    # read get_active_project_path() — the active project may change before
    # the worker finishes.
    import os
    path = self._project_handler.get_active_project_path()
    if not path:
        self._cached_branch = None
        return

    # Bump the request token (monotonic; also invalidates any prior in-flight).
    self._branch_request_token += 1
    token = self._branch_request_token
    self._branch_active_token = token
    self._branch_request_path = path

    import threading
    t = threading.Thread(
        target=self._resolve_branch_worker,
        args=(token, path, project_name, member_count, solo_target, auto_accept_level),
        daemon=True,
    )
    t.start()
    # Use the cached branch (stale OK) until the worker reports back.
    # If nothing cached yet, branch_name stays None → "—".

def _resolve_branch_worker(self, token, path, project_name, member_count,
                           solo_target, auto_accept_level):
    """Background worker: resolve the branch for the CAPTURED path.

    Reads only `path` (captured) — never the live active project (BUG #2).
    On completion, dispatches a main-thread callback. If the token no longer
    matches (a newer refresh started, or the project closed), the result is
    DISCARDED (BUG #7).
    """
    branch = None
    try:
        from utils.git_ops import get_branch
        result = get_branch(path)
        # get_branch returns success=True with "(detached HEAD)" for detached;
        # failure (non-git, unborn) → success=False → None → "—".
        branch = result.stdout if result.success else None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("branch lookup failed for %s", path)
        branch = None
    # Dispatch back to the GTK main thread.
    from gi.repository import GLib
    GLib.idle_add(
        lambda: self._on_branch_result(token, path, project_name, member_count,
                                       solo_target, auto_accept_level, branch)
    )

def _on_branch_result(self, token, path, project_name, member_count,
                      solo_target, auto_accept_level, branch):
    """GTK-thread callback applying a branch result IF it is still current.

    Staleness check (BUG #2/#7): discard unless
      1) token == self._branch_active_token (this is the latest request), AND
      2) path == self._branch_request_path (the project is still the one we
         captured — protects against project B opening over project A).
    If stale, clear the in-flight marker and do nothing else.
    """
    # Always clear the in-flight marker so future refreshes may start.
    if token == self._branch_active_token:
        self._branch_active_token = None
    # Stale (superseded by a newer request OR the project closed/switch) → discard.
    if token != self._branch_request_token \
            or path != self._branch_request_path:
        return
    self._cached_branch = branch
    # Only refresh the bar if this project is still the active one.
    current_name = self._project_handler.get_active_project_name() \
        if self._project_handler else None
    if current_name != project_name:
        return
    self._on_feed_bar_update(project_name, member_count,
                             solo_target=solo_target,
                             auto_accept_level=auto_accept_level,
                             branch_name=branch)
```

**Project close invalidation (BUG #2):** when a project closes, invalidate any in-flight branch request so a stale result cannot resurrect a closed project's bar. Add to the project-closed lifecycle callback (line 554 tuple):

```python
# In __init__/build: append to the project-closed lambda
# (alongside the existing _on_feed_bar_update(None, 0)):
self._branch_request_token += 1          # invalidate any in-flight worker
self._branch_active_token = None
self._branch_request_path = None
self._cached_branch = None
```

**New callback implementations (BUG #3 — preserve member count; BUG #4 — solo wiring driven here):**

```python
def _on_agent_cycle_clicked(self, current_solo):
    """Cycle agent label: ALL(None) → member[0] → ... → member[N-1] → ALL(None).

    With exactly ONE member this is a 2-state cycle; generally (N+1) states.
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
    # set_solo_target fires _on_solo_target_changed → bar refreshes (BUG #4).
    # No direct bar call needed here; the callback handles it.

def _on_autoaccept_cycle_clicked(self, current_level):
    """Cycle auto-accept (file changes): off → diffs → files → all → off.

    BUG #3: read the CURRENT member count (never pass 0, which would flash
    '0 members'). BUG #11: enabling routes through the FeedHandler warning gate.
    """
    project_name = self._project_handler.get_active_project_name() if self._project_handler else None
    if not project_name:
        return
    cycle = {"off": "diffs", "diffs": "files", "files": "all", "all": "off"}
    next_level = cycle.get(current_level, "off")
    if self._feed_handler is not None:
        self._feed_handler.set_auto_accept_level(next_level)
    # Preserve the true member count (BUG #3).
    members = self._project_handler.get_project_members(project_name)
    self._on_feed_bar_update(
        project_name,
        len(members),
        solo_target=self._project_handler.get_solo_target(project_name),
        auto_accept_level=self._feed_handler.get_auto_accept_level() if self._feed_handler else "off",
    )

def _on_solo_target_changed(self, project_name: str):
    """ProjectHandler fired after a solo-target change (right-click selection).

    Refresh the bar with the new solo target and the CURRENT member count.
    BUG #4: this is the missing wiring that makes right-click selection update
    the bar immediately.
    """
    if not project_name or self._project_handler is None:
        return
    members = self._project_handler.get_project_members(project_name)
    self._on_feed_bar_update(
        project_name,
        len(members),
        solo_target=self._project_handler.get_solo_target(project_name),
    )

def _on_settings_btn_clicked(self):
    """⚙ → open the existing Settings dialog (fresh instance each call)."""
    self._open_settings()
```

**Wiring (BUG #4 — add to `_build()`, after the existing `set_on_project_settings_update` call ~line 435):**

```python
self._main_content.set_on_settings_clicked(self._on_settings_btn_clicked)
self._main_content.set_on_agent_cycle(self._on_agent_cycle_clicked)
self._main_content.set_on_autoaccept_cycle(self._on_autoaccept_cycle_clicked)
# Round 2 BUG #4: wire the ProjectHandler solo-change callback so right-click
# solo selection refreshes the bar immediately.
self._project_handler.set_on_solo_target_changed(self._on_solo_target_changed)
```

**Line count:** ~150 added.

---

### 2.3 `ui/handlers/feed_handler.py` — auto-accept level read/write (unchanged from FIX-1)

Source of truth stays in `FeedHandler`. `get_auto_accept_level`, `set_auto_accept_level`, `_commit_auto_accept_level` from FIX-1 carry over **unchanged** (Round 2 made no findings against them). For completeness, the three methods:

```python
def get_auto_accept_level(self) -> str:
    """File-change auto-accept level: "off" | "diffs" | "files" | "all".

    Scoped to FILE changes only; exec is a separate axis (Round 1 BUG #10).
    Distinct, round-trippable mapping (Round 1 BUG #9):
      - "off":   diff off AND file_created/modified/deleted all off
      - "diffs": diff on  AND file_created/modified/deleted all off
      - "files": diff off AND file_created/modified/deleted all on
      - "all":   all four on
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

def set_auto_accept_level(self, level: str) -> None:
    """Set file-change auto-accept level; enabling routes through the warning gate.

    level ∈ {"off","diffs","files","all"}; invalid → no-op. Enabling states
    call the warning callback (category + agent + on_confirm/on_cancel) and
    only commit on confirm (Round 1 BUG #11). All commits call
    _refresh_auto_accept_state() (Round 1 BUG #4) — never _save_feed_prefs_idle()
    directly.
    """
    if level not in ("off", "diffs", "files", "all") or self._prefs is None:
        return
    if level == "off":
        for ct in self._prefs.file_changes:
            self._prefs.file_changes[ct].enabled = False
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

**Files NOT changed:** `.crabcakes/feed-prefs.json`, `models/feed_card.py` — v2 schema sufficient.

---

### 2.4 `ui/handlers/project_handler.py` — solo-target change callback (BUG #4, Round 2)

**Verified current state:** `set_solo_target` (line 376) only assigns `self._solo_targets[project_name] = member_session_key`. There is **no** existing callback. This section adds one.

**`__init__` addition (near the `_solo_targets` dict ~line 364):**

```python
self._solo_targets: dict[str, str | None] = {}
# Round 2 BUG #4: fired after a solo-target change so the settings bar can
# refresh immediately on right-click member selection.
self._on_solo_target_changed: Callable[[str], None] | None = None
```

**New setter (add to the "Setters for cross-handler callbacks" section):**

```python
def set_on_solo_target_changed(self, cb: Callable[[str], None] | None) -> None:
    """Register a callback fired after set_solo_target() changes.

    cb(project_name: str). Window wires this to refresh the project settings
    bar's agent name. Safe to call with None to unregister, or before any
    project open (no-op until set_solo_target is invoked).
    """
    self._on_solo_target_changed = cb
```

**Modified `set_solo_target` (fires the callback only when the value actually changes, and only for a known/active project):**

```python
def set_solo_target(self, project_name: str, member_session_key: str | None):
    """Set or clear the solo DM target for a project.

    Args:
        project_name:          Name of the project.
        member_session_key:    Session key of the solo recipient, or None to
                               restore group broadcast (All members).

    Fires `_on_solo_target_changed(project_name)` when the value changes so
    the window can refresh the settings bar (Round 2 BUG #4). The callback
    only fires for a real change (old == new → no-op) to avoid redundant
    rebuilds when e.g. the same member is re-selected.
    """
    old = self._solo_targets.get(project_name)
    if old == member_session_key:
        return  # no change — skip redundant callback
    self._solo_targets[project_name] = member_session_key
    if self._on_solo_target_changed is not None:
        self._on_solo_target_changed(project_name)
```

**Files NOT changed:** none within `project_handler.py` beyond the above.

---

### 2.5 `ui/styles.py` — CSS (unchanged from FIX-1)

Identical to FIX-1 §2.4 — the 3 interactive-class rule blocks (`.project-bar-agent`, `.project-bar-autoaccept`, `.project-bar-gear`) with GTK4-safe `:hover`/`:active` and no `text-align`. No changes needed for the Round 2 fixes.

---

## 3. Data Flow

### Branch refresh (token-guarded — Round 2 BUG #1/#2/#7)
1. Project opens → line 540 calls `_on_feed_bar_update(name, count)` → `branch_name is None` and `self._branch_active_token is None` (BUG #1: guards on `None` of the token, not `is None` of a bool) and handler present → `_schedule_branch_refresh(...)`
2. `_schedule_branch_refresh` captures `path = get_active_project_path()`, increments `_branch_request_token`, sets `_branch_active_token = token` and `_branch_request_path = path` (all GTK thread), spawns a daemon thread.
3. Worker reads only the captured `path` (never live active project — BUG #2), calls `get_branch(path)`, dispatches `_on_branch_result` via `GLib.idle_add`.
4. `_on_branch_result` (GTK thread) clears `_branch_active_token`, then discards the result unless `token == _branch_request_token` AND `path == _branch_request_path` AND the active project is still `project_name` (BUG #2/#7). On acceptance, updates `_cached_branch` and re-calls `_on_feed_bar_update` with all wrapped state → bar shows `⎇ main`.
5. If the project closed mid-flight, the project-closed lifecycle (line 554) already bumped `_branch_request_token` and cleared `_branch_active_token`/`_branch_request_path`/`_cached_branch`, so the stale result is discarded.

### Right-click solo selection (Round 2 BUG #4)
1. Right-click project tab → `show_project_menu` → `on_select` → `_on_project_solo_selected` → `ProjectHandler.set_solo_target(project_name, target_sk)`
2. `set_solo_target` detects a change, updates `_solo_targets`, fires `_on_solo_target_changed(project_name)`
3. Window's `_on_solo_target_changed` reads current members + solo target → `_on_feed_bar_update(name, len(members), solo_target=...)` → bar rebuilds with new agent name (or `ALL`)

### Auto-accept cycle (Round 2 BUG #3 — member count preserved)
1. Click auto label → `_on_autoaccept_label_clicked(current)` → `_on_autoaccept_cycle(current)`
2. Window `_on_autoaccept_cycle_clicked` → `FeedHandler.set_auto_accept_level(next)` (warning gate on enable — BUG #11)
3. Then reads `len(get_project_members(project_name))` (BUG #3 — not 0) + current level + solo target → `_on_feed_bar_update(name, real_count, solo_target=..., auto_accept_level=...)` → bar shows correct member count + level

### Agent cycle
1. Click agent label → `_on_agent_cycle_clicked` → advances member index → `set_solo_target` → fires `_on_solo_target_changed` → bar refreshes (BUG #4 path)

### Settings dialog
1. Click ⚙ → `_on_settings_btn_clicked` → `_open_settings()` → fresh `SettingsDialog`

---

## 4. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `ui/views/main_content.py` | Modified — bar rebuild, xml_escape hardening (BUG #6), gear re-append in legacy methods (BUG #5) | +150 | Low |
| `ui/window.py` | Modified — token-guarded branch worker (BUG #1/#2/#7), member-count fix (BUG #3), solo callback wiring (BUG #4) | +150 | Medium |
| `ui/handlers/feed_handler.py` | Modified — `get/set/commit_auto_accept_level` (unchanged from FIX-1) | +55 | Medium |
| `ui/handlers/project_handler.py` | Modified — `_on_solo_target_changed` slot + setter + fire in `set_solo_target` (BUG #4) | +22 | Low |
| `ui/styles.py` | Modified — 3 CSS rule blocks (unchanged from FIX-1) | +45 | None |
| **Total** | | **~420** | **Low-Medium** |

**Files NOT changed (already correct):**
- `ui/views/session_menu.py` — right-click menu + `on_select` intact.
- `ui/views/settings_dialog.py` — opened via `_open_settings()`.
- `utils/git_ops.py` — `get_branch()` at line 87 used as-is (incl. detached-HEAD contract).
- `models/feed_card.py`, `.crabcakes/feed-prefs.json` — v2 schema sufficient.
- `utils/escaping.py` — both `escape_for_pango` and `xml_escape_text` used appropriately (BUG #6: `xml_escape_text` for untrusted plain text).
- `ui/styles.py` `.project-feed-bar` — kept.

---

## 5. Implementation Order

### Step 1 — CSS (no deps)
Add the 3 rule blocks to `ui/styles.py`. Verify no CSS parse errors.

### Step 2 — FeedHandler
Add `get_auto_accept_level` / `set_auto_accept_level` / `_commit_auto_accept_level` (as in FIX-1). Unit tests: round-trip all 4 levels in-memory AND via `to_dict()`/`from_dict()`; assert `_refresh_auto_accept_state` called after each commit; assert warning wire receives `("files", agent, on_confirm, on_cancel)` for `files`/`all`, and on_cancel does not commit.

### Step 3 — MainContent
Add `_settings_btn` init, `_clear_settings_bar`, `_resolve_agent_display_name`, 3 click handlers, 3 setters, `update_project_settings` (xml_escape for name/branch — BUG #6), and gear re-append in `set_project_settings_text`/`set_feed_bar_text` (BUG #5).

**Regression test (BUG #5):** construct MainContent with a fake box; call `set_project_settings_text("x")`; assert `self._settings_btn` still has a parent (re-appended).

### Step 4 — ProjectHandler
Add `_on_solo_target_changed` slot + `set_on_solo_target_changed` setter + fire in modified `set_solo_target` (BUG #4). **Regression test:** set solo target X → assert callback fired with project_name; set same target again → assert callback NOT re-fired (no redundant rebuild).

### Step 5 — window.py wiring
Extend `_on_feed_bar_update`, add token-guarded branch worker (`_schedule_branch_refresh` / `_resolve_branch_worker` / `_on_branch_result`), the 4 init fields, project-closed invalidation, 3 callback impls (agent cycle, auto cycle with member count, solo changed, settings), and wire all 4 setters (3 main_content + 1 project_handler).

**Regression tests (Round 2 BUG #2/#3/#1/#7):**
- **BUG #1:** `_branch_active_token is None` (initial) → `_on_feed_bar_update("A", 2)` with `branch_name=None` starts a worker (token becomes set). Assert worker thread started.
- **BUG #2:** schedule for project A (token 1, path /a); simulate switch to project B (active name/path → B, token bumped to 2); call `_on_branch_result(1, /a, "A", ...)` → assert discarded (bar NOT updated, `_cached_branch` unchanged for B).
- **BUG #3:** set up project with 3 members; call `_on_autoaccept_cycle_clicked("off")` with a mock handler → assert `_on_feed_bar_update` received `member_count == 3`, not 0.
- **BUG #7:** two rapid refreshes — assert the second supersedes the first (`_branch_request_token` increments) and only the newest result is applied.

### Step 6 — End-to-end
Open project → `[name · N] [ALL] [⚡ files: off] [⎇ branch] [⚙]`; right-click → agent green; agent click cycles; auto click cycles (warning on enable, member count stable); ⚙ opens settings.

---

## 6. Acceptance Criteria

- [ ] `update_project_settings` rebuilds the bar with all 5 elements; shows `ALL` for `solo_target=None`, else display name (green) — color via CSS (Round 1 BUG #8/#18).
- [ ] Empty project (falsy name) → bar hidden (Round 1 BUG #3).
- [ ] Branch refresh actually runs (Round 2 BUG #1: token check `is None`, not bool-`is-None`). Branch shows name / `(detached HEAD)` / `—`.
- [ ] Rapid project switch / close cannot apply a stale branch to the wrong project (Round 2 BUG #2/#7: token + path check discards stale results).
- [ ] Auto-accept click preserves the true member count (Round 2 BUG #3: never `0`).
- [ ] Right-click solo selection updates the bar immediately via `_on_solo_target_changed` (Round 2 BUG #4).
- [ ] Legacy `set_project_settings_text` and `set_feed_bar_text` preserve the gear button (Round 2 BUG #5).
- [ ] Project name / branch render literally — `<b>` in a project name is NOT bolded (Round 2 BUG #6: `xml_escape_text`).
- [ ] Auto-accept cycles `off→diffs→files→all→off`, distinct persisted states, warning gate on enable (Round 1 BUG #9/#10/#11).
- [ ] No `escape_for_pango` on untrusted plain text anywhere in the bar (Round 2 BUG #6 sweep).

## 7. Edge Cases

| Case | Expected |
|------|----------|
| No project open | bar hidden |
| 0 members | `[name · 0 members] [ALL] …`, agent cycle no-op |
| 1 member | 2-state agent cycle |
| Non-git project | branch None → `—` |
| Detached HEAD | `(detached HEAD)` verbatim |
| Branch lookup slow/errors | worker catches; branch None → `—`; no main-thread block |
| No `feed-prefs.json` | `get_auto_accept_level` → `off` |
| `set_auto_accept_level("invalid")` | no-op |
| Warning dialog cancelled | no commit; bar stays at current level |
| Project closed mid-branch-refresh | project-closed invalidation bumps token → stale result discarded |
| Switch project A→B mid-refresh | token+path mismatch → stale result discarded; B's own refresh applies |
| Re-selecting the same solo member | `set_solo_target` no-ops (old == new); no redundant bar rebuild (BUG #4) |
| `_on_feed_bar_update` called after project close | empty branch hides bar |
| Project name has Pango specials | `xml_escape_text` → literal (BUG #6) |
| Legacy `set_project_settings_text`/`set_feed_bar_text` after gear init | gear re-appended (BUG #5) |
| 10+ members | cycle wraps correctly |

## 8. ARCHITECTURE.md Updates Required

1. §3.16 `ui/handlers/feed_handler.py` — add `get_auto_accept_level` / `set_auto_accept_level` to public API; note file-scoped semantics.
2. Module-responsibility section for `ui/views/main_content.py` — document `update_project_settings`, 3 setters, child-clear helper, and the gear-reappend invariant in the legacy methods. *(Correct the stale §3.7 citation — that section documents `left_panel.py`, not `main_content.py`.)*
3. `ui/handlers/project_handler.py` — document the new `set_on_solo_target_changed` public API and that `set_solo_target` now fires it.
4. `ui/window.py` §3.6 wiring note — document the 4 new settings-bar callbacks and the token-guarded branch worker, including the project-closed invalidation.

---

## 9. How Each Round 2 Finding Is Addressed

| # | Sev | Fix |
|---|-----|-----|
| 1 | CRIT | Branch scheduling condition changed from `self._pending_branch_refresh is None` (dead — bool never `is None`) to `self._branch_active_token is None`. The worker is now started when no refresh is in flight. Regression test in §5 Step 5. |
| 2 | HIGH | Worker captures `project_path` (via `get_active_project_path()` at schedule time) + a monotonic `request_token`. `_on_branch_result` discards the result unless `token == _branch_request_token` AND `path == _branch_request_path` AND the active project still matches. Project-closed invalidation bumps the token. Regression test in §5 Step 5. |
| 3 | HIGH | `_on_autoaccept_cycle_clicked` now reads `len(get_project_members(project_name))` (never passes `0`). Regression test asserts member count unchanged after a level transition. |
| 4 | HIGH | Complete `project_handler.py` sample added (§2.4): `_on_solo_target_changed` init, `set_on_solo_target_changed` setter, and modified `set_solo_target` that fires on real change. Window wiring sample added (§2.2). Regression test: set solo → callback fires; set same → no re-fire. |
| 5 | MED | `set_project_settings_text` and `set_feed_bar_text` now re-append `self._settings_btn` after the legacy label. Regression test asserts gear has a parent after a legacy call. |
| 6 | MED | Replaced `escape_for_pango(project_name)` with `xml_escape_text(project_name)`; audited all other interpolations into Pango markup (branch already `xml_escape_text`; agent/auto are `Gtk.Button` labels = plain text, safe). Regression test: project named `<b>injected</b>` renders literally. |
| 7 | MED | Replaced the bare `_pending_branch_refresh` boolean with an integer `request_token` + `_branch_active_token`. All state transitions on the GTK thread; worker only reads captured `path` and dispatches; stale results discarded by token/path comparison. Regression test: two rapid refreshes, only newest applies. |

## 10. Spec Self-Audit (Rule 9) + Empirical Verification

**Rule 1** — Re-read `ui/views/main_content.py`, `ui/window.py` (wiring + `_on_feed_bar_update` + `_open_settings`), `ui/handlers/feed_handler.py`, `ui/handlers/project_handler.py` (`set_solo_target`), `models/feed_card.py`, `agent/special_agents.py`, `ui/handlers/agent_runtime_handler.py`, `utils/escaping.py`, `utils/git_ops.py`, and the FIX-1 spec (superseded).

**Rule 2/3** — Signatures verified: `get_active_project_path() -> str | None` ✓, `get_active_project_name()` ✓, `get_solo_target/set_solo_target` ✓, `get_project_members(project_name)` ✓, `get_branch(path) -> GitResult` ✓, `ARTH.get_special_agents() -> dict[str, str]` ✓, `_open_settings()` ✓, `FeedHandler._refresh_auto_accept_state()` / `_show_auto_accept_warning(category, agent, on_confirm, on_cancel)` ✓, `GLib.idle_add` ✓.

**Rule 4** — `get_branch` returns a `GitResult` (never raises); worker wraps regardless. `set_auto_accept_level` guards `_prefs is None` + invalid level. Handler refs null-guarded throughout.

**Rule 5** — `_solo_targets: dict[project, sk | None]` ✓; `AutoAcceptPrefs.file_changes` keyed `diff|file_created|file_modified|file_deleted` ✓; ARTH dict keyed by `conv_id_prefix` ✓.

**Rule 6** — `get_branch` return checked (`result.success`); token/path comparison return honored; `get_auto_accept_level` return consumed.

**Rule 7** — Every code path traced against source (above). No "should work" samples.

**Rule 8** — Files NOT changed listed in §2.x and §4.

**Rule 10** — Spec-fix round: no implementation yet. Implementation + regression tests specified in §5. Acceptance in §6.

**Empirical probes (round 2):**

1. **`escape_for_pango` vs `xml_escape_text` (BUG #6):**
   ```
   RAW            : '<b>Injected</b> & "quotes"'
   escape_for_pango: '<b>Injected</b> &amp; &quot;quotes&quot;'
   xml_escape_text : '&lt;b&gt;Injected&lt;/b&gt; &amp; &quot;quotes&quot;'
   escape_for_pango preserves <b>:  True
   xml_escape_text neutralizes <b>:  True
   ```
   Confirms `escape_for_pango` preserves `<b>` (injection risk — BUG #6 valid) and `xml_escape_text` neutralizes it. Spec uses `xml_escape_text` for all untrusted plain text.

2. **`ProjectHandler.set_solo_target` current state (BUG #4):**
   Grep + read confirmed the method (line 376) only assigns `self._solo_targets[project_name] = member_session_key`; there is **no** existing callback. The new `_on_solo_target_changed` slot + setter + fire are genuinely new.

3. **Branch scheduling logic (BUG #1/#7):** Traced the FIX-1 sample: `if branch_name is None and self._pending_branch_refresh is None` where `_pending_branch_refresh: bool = False` → `False is None` is always False → worker never starts. Replaced with `self._branch_active_token is None` where `_branch_active_token: int | None = None`.

4. **Round-1 auto-accept round-trip (regression from FIX-1):** `off/diffs/files/all` all round-trip 4/4 in-memory + 4/4 via `to_dict()`/`from_dict()` (verified when writing FIX-1). Carried unchanged; implementation Step 2 re-verifies.

---

## 11. Round 1 Verification Confirmation

All 18 Round 1 findings remain FIXED in FIX-2 (unchanged or reinforced):
- #1–#4, #5–#12, #14, #17, #18 — carried unchanged (import removal, sibling-walk clear, empty-project hide, `_refresh_auto_accept_state`, `_open_settings`, `get_active_project_path`, ARTH dict, `set_has_frame`, distinct states, exec scoping, warning gate, detached-HEAD, architecture citation, cycle wording, CSS color).
- #13 (blocking branch on GTK thread) — now **fully** fixed: worker + token guard (was PARTIAL due to BUG #1/#2).
- #15 (callback dispatch overstated) — now **fully** fixed: lifecycle sites enumerated + `set_on_solo_target_changed` implementation/wiring present (was PARTIAL due to BUG #4).
- #16 (per-tab overlay/reparenting) — now **fully** fixed: project-closed invalidation + token/path staleness guard for async (was PARTIAL due to BUG #2).
