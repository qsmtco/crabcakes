# SPEC: Enhanced Project Settings Bar — FIX 3 (revised)

**Date:** 2026-07-31
**Author:** Coder (round 3 spec fix, per audit `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2-FINDINGS.md`)
**Status:** Draft — for re-audit
**Supersedes:** `docs/specs/SPEC-PROJECT-SETTINGS-BAR-ENHANCED-FIX-2.md` (which supersedes `...-FIX-1.md`; which supersedes `...-ENHANCED.md`)
**Implements:** User request "enhance the project settings bar with agent name, auto-accept level, branch, settings button"
**Target branch:** main

> Architecture compliance. Follows `docs/ARCHITECTURE.md`:
> - §3.6 composition root — `window.py` wires all callbacks; `main_content.py` stays a pure layout view
> - §3.16 handler pattern — `FeedHandler` remains the sole source of truth for auto-accept state; `ProjectHandler` remains the sole owner of project/solo/branch state. No handler imports another handler.
> - §7 views have no business logic — the settings bar is a pure layout; all state lookups live in handlers/window.
> - Layer rule: `main_content.py` (`ui/`) may not import `models/` or call `feed_store` — it receives resolved primitives (str/int/None) from `window.py`.
>
> FIX-3 resolves the 7 Round 3 findings (1 CRITICAL, 3 HIGH, 3 MEDIUM) on top of FIX-2. **Every code sample below was traced against the current source, is syntactically valid Python** (verified with `ast.parse()` in §10 — Round 3 BUG #1 was a `SyntaxError` in a FIX-2 code sample), and matches actual signatures (verified empirically).

---

## 1. Overview

### Problem (unchanged)
The project settings bar currently shows only `[crabcakes · 6 members]` — passive display. Expand to per-project actionable context.

### Solution (unchanged target)
```
[crabcakes · 6 members] [● Coder] [⚡ files: off] [⎇ main]        [⚙]
```
- **Agent name** (green). Shows `ALL` for group broadcast, else the current solo member's display name. Click cycles members → back to `ALL`.
- **Auto-accept level** (file changes only). Click cycles `off → diffs → files → all → off`. Distinct, persisted states via `FeedHandler`; the **warning gate** is preserved on every activation.
- **Git branch** (read-only). Shows branch name, `(detached HEAD)`, or `—` for non-git. Resolved off the main thread **with a generation token + path-keyed cache** (Round 2 BUG #2/#7, Round 3 BUG #2/#5/#6).
- **⚙ button** (right-aligned). Opens the existing Settings dialog via `MainWindow._open_settings()`.

### Round 2 defects carried forward (unchanged)
1. **CRIT** branch scheduling dead-code → `_branch_active_token is None`
2. **HIGH** async branch results crossing project boundaries → token + path capture
3. **HIGH** auto-accept callback clobbering member count to 0 → query real members
4. **HIGH** missing `set_on_solo_target_changed` wiring
5. **MED** legacy methods dropping gear button → re-append gear
6. **MED** `escape_for_pango` injection risk → `xml_escape_text`
7. **MED** `_pending_branch_refresh` not thread-safe → monotonic token

### Round 3 defects fixed (this spec)
1. **CRIT** project-close invalidation inserted into a tuple lambda → `SyntaxError`. Replaced with a named `_on_project_closed(name)` method registered as its **own** callback (handler supports multiple callbacks).
2. **HIGH** stale branch result writes `_cached_branch` before active-project check → reorder checks before assignment; add open/switch invalidation via named `_on_project_opened(name, path)`.
3. **HIGH** `set_solo_target()` doesn't validate project → validate via `_get_project_path()`; window callback guards non-active project.
4. **HIGH** bar doesn't update after async auto-accept confirmation → add `on_auto_accept_level_changed` callback fired in `_commit_auto_accept_level`; wire to refresh bar. Cycle handler does **not** optimistically rebuild.
5. **MED** `_cached_branch` not keyed by project → replace with `_cached_branch_by_path: dict[str, str]`.
6. **MED** branch refresh condition doesn't check cache ownership → separate `needs_resolution` (cache check) from `already_running` (in-flight check).
7. **MED** special-agent fallback returns `None`/`""` for empty values → `.get()` with truthiness check.

### Scope

| In Scope | Out of Scope |
|---------|-------------|
| Agent name display + click-to-cycle | Right-click tab menu redesign |
| Auto-accept level indicator + click-to-cycle (file changes) | Exec-command auto-accept control (separate axis, stronger warning — explicitly excluded, see §2.3) |
| Git branch display (token-guarded async, path-keyed cache) | Branch switching |
| ⚙ button → existing Settings dialog | Cost budget indicator |

---

## 2. Changes by File

### 2.1 `ui/views/main_content.py` — settings bar widget refactor

**Public API changes (unchanged from FIX-2, except BUG #7 fallback fix):**

- `set_project_settings_text(text)` — kept; **re-appends the gear button** after the legacy label (Round 2 BUG #5).
- `set_feed_bar_text(text)` — kept; **re-appends the gear button** (Round 2 BUG #5).
- New: `update_project_settings(project_name, member_count, solo_target, auto_accept_level, branch_name)`.
- `set_on_project_settings_update(cb)` — signature extended to `cb(project_name, member_count, *, solo_target=None, auto_accept_level=None, branch_name=None)`.
- New setters: `set_on_settings_clicked(cb)`, `set_on_agent_cycle(cb)`, `set_on_autoaccept_cycle(cb)`.

**Imports required:** `xml_escape_text` from `utils.escaping`. `escape_for_pango` is **no longer used** for untrusted plain text anywhere in the bar (Round 2 BUG #6). `Gtk` already imported.

**Child-clear helper (unchanged — sibling-walk safe):**

```python
def _clear_settings_bar(self) -> None:
    """Remove all children from the settings bar box (sibling-walk safe)."""
    while self._project_settings.get_first_child() is not None:
        self._project_settings.remove(self._project_settings.get_first_child())
```

**`update_project_settings` (unchanged from FIX-2):**

```python
def update_project_settings(self, project_name, member_count,
                            solo_target, auto_accept_level, branch_name):
    """Rebuild the settings bar with the latest per-project state.

    Called by window.py when project opens/closes, members change, solo
    target changes, auto-accept level changes, or branch refresh lands.

    Empty project (project_name falsy) -> hide the bar and return.
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

    # Project name + member count. BUG #6: xml_escape_text() the UNTRUSTED
    # project name (escape_for_pango preserves <b> etc -> injection).
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
    agent_label = Gtk.Button(label=agent_text)   # Button label is plain text -> safe
    agent_label.set_has_frame(False)   # GTK4 — set_relief()/ReliefStyle do NOT exist
    agent_label.set_focus_on_click(False)
    agent_label.add_css_class("project-bar-agent")
    agent_label.connect("clicked", lambda _b: self._on_agent_label_clicked(solo_target))
    info_box.append(agent_label)

    # Auto-accept level (file changes) — clickable, cycles off->diffs->files->all
    level_labels = {
        "off": "⚡ files: off",
        "diffs": "⚡ files: diffs",
        "files": "⚡ files: files",
        "all": "⚡ files: all",
    }
    level_text = level_labels.get(auto_accept_level, "⚡ files: off")
    auto_label = Gtk.Button(label=level_text)   # Button label is plain text -> safe
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
    # Always re-append the singleton gear — _clear_settings_bar() removed it.
    self._project_settings.append(self._settings_btn)
```

**`_resolve_agent_display_name` (Round 3 BUG #7 — `.get()` with truthiness, not key membership):**

```python
def _resolve_agent_display_name(self, session_key: str) -> str:
    """Resolve a member session_key to a human-readable name.

    Ordered fallback (mirrors existing _on_tab_right_click logic):
      1. _agent_mgr.get_name(sk)  (gateway/connected AgentManager)
      2. _agent_runtime_handler.get_special_agents()[sk]  (offline special agents)
      3. session_key as-is.

    Uses the dict returned by ARTH.get_special_agents() — NO reliance on a
    SpecialAgentDef.session_key attribute (keyed by conv_id_prefix).

    Round 3 BUG #7: use .get() + truthiness, NOT `if sk in special` — an
    entry whose value is "" or None must fall through to session_key
    rather than return a blank label.
    """
    if self._agent_mgr is not None:
        name = self._agent_mgr.get_name(session_key)
        if name:
            return name
    if self._agent_runtime_handler is not None:
        special = self._agent_runtime_handler.get_special_agents()
        name = special.get(session_key)
        if name:
            return name
    return session_key
```

**Click handlers (unchanged from FIX-2):**

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

**Legacy `set_project_settings_text` and `set_feed_bar_text` (Round 2 BUG #5 — re-append gear):**

```python
def set_project_settings_text(self, text: str):
    """Set text or markup on the project settings bar. Handles Pango markup correctly.

    Backward compat: still clears the bar, appends the label, then re-appends the
    singleton gear button so it is never lost (BUG #5).
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
- `ui/views/session_menu.py` — right-click project menu already exists; its `on_select` → `_on_project_solo_selected` → `set_solo_target` path stays intact.
- `ui/views/settings_dialog.py` — exists; opened via `MainWindow._open_settings()`.

---

### 2.2 `ui/window.py` — wire the new callbacks (token-guarded, path-keyed branch worker)

**Lifecycle dispatch sites (unchanged from FIX-2):** four existing call sites call `self._on_feed_bar_update(...)` directly — lines 540 (opened), 554 (closed), 561 (members-changed), 1046 (`_close_project_tab`). All pass `(project_name, member_count)`; the extended signature resolves remaining state, so these need no change.

**New/updated window state fields (Round 3 BUG #5 — path-keyed cache instead of a single `_cached_branch`):**

```python
# In __init__ (round 2 BUG #2/#7 + round 3 BUG #5):
# Cache keyed by project_path — a switch A->B->A reuses A's cached branch.
self._cached_branch_by_path: dict[str, str] = {}   # {project_path: branch_name}
self._branch_request_token: int = 0           # monotonic request id (BUG #7)
self._branch_active_token: int | None = None  # token of in-flight worker (BUG #2)
self._branch_request_path: str | None = None  # project path captured at schedule time (BUG #2)
```

**Modified `_on_feed_bar_update` (Round 3 BUG #6 — separate cache-validation from in-flight check):**

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
    # Branch scheduling — Round 3 BUG #6: separate the TWO distinct reasons
    # a branch refresh might be needed from "a worker is already running".
    #   needs_resolution: the ACTIVE project's branch is not yet cached
    #                    (checked against the path-keyed cache, BUG #5).
    #   already_running:  a worker is in flight for the CURRENT request.
    if branch_name is None and self._project_handler is not None:
        active_path = self._project_handler.get_active_project_path() or ""
        cached_for_active = self._cached_branch_by_path.get(active_path)
        needs_resolution = cached_for_active is None
        already_running = self._branch_active_token is not None
        if needs_resolution and not already_running:
            self._schedule_branch_refresh(
                project_name, member_count, solo_target, auto_accept_level
            )
        branch_name = cached_for_active
    self._main_content.update_project_settings(
        project_name, member_count, solo_target,
        auto_accept_level or "off", branch_name,
    )
```

**Token-guarded branch scheduling + worker (unchanged from FIX-2 except worker returns path; BUG #2/#5/#6):**

```python
def _schedule_branch_refresh(self, project_name, member_count,
                             solo_target, auto_accept_level):
    """Start a background branch lookup, guarded by a monotonic request token.

    All state transitions happen on the GTK thread. The worker only reads a
    captured project_path and reports back; it never mutates window state.
    """
    if self._branch_active_token is not None:
        return  # a worker is already in flight — don't stack a second one

    import os
    path = self._project_handler.get_active_project_path()
    if not path:
        return

    self._branch_request_token += 1
    token = self._branch_request_token
    self._branch_active_token = token
    self._branch_request_path = path

    import threading
    t = threading.Thread(
        target=self._resolve_branch_worker,
        args=(token, path, project_name, member_count,
              solo_target, auto_accept_level),
        daemon=True,
    )
    t.start()

def _resolve_branch_worker(self, token, path, project_name, member_count,
                           solo_target, auto_accept_level):
    """Background worker: resolve the branch for the CAPTURED path.

    Reads only `path` (captured) — never the live active project. On
    completion, dispatches a main-thread callback. If the token no longer
    matches, the result is DISCARDED.
    """
    branch = None
    try:
        from utils.git_ops import get_branch
        result = get_branch(path)
        # get_branch returns success=True with "(detached HEAD)" for detached;
        # failure (non-git, unborn) -> success=False -> None -> "—".
        branch = result.stdout if result.success else None
    except Exception:
        import logging
        logging.getLogger(__name__).exception("branch lookup failed for %s", path)
        branch = None
    from gi.repository import GLib
    GLib.idle_add(
        lambda: self._on_branch_result(token, path, project_name, member_count,
                                       solo_target, auto_accept_level, branch)
    )
```

**`_on_branch_result` — Round 3 BUG #2: active-project identity check BEFORE any state mutation.** Reworked so `_cached_branch_by_path` is only written once all staleness + identity checks pass:

```python
def _on_branch_result(self, token, path, project_name, member_count,
                      solo_target, auto_accept_level, branch):
    """GTK-thread callback applying a branch result IF it is still current.

    Round 3 BUG #2: ALL staleness + active-identity checks run BEFORE any
    state is mutated. A stale result can never write _cached_branch_by_path
    for the wrong project.
    """
    # Clear the in-flight marker (always — the worker has reported back).
    if token == self._branch_active_token:
        self._branch_active_token = None

    # 1) Superseded by a newer request OR the project closed/switch -> discard.
    if token != self._branch_request_token:
        return
    if path != self._branch_request_path:
        return

    # 2) Active project must still be the one we resolved for — check name
    #    AND path BEFORE writing the cache (BUG #2 / BUG #5).
    current_name = self._project_handler.get_active_project_name() \
        if self._project_handler else None
    if current_name != project_name:
        return
    current_path = self._project_handler.get_active_project_path() \
        if self._project_handler else None
    if current_path != path:
        return

    # All checks pass — safe to commit to the path-keyed cache (BUG #5).
    self._cached_branch_by_path[path] = branch
    self._on_feed_bar_update(project_name, member_count,
                             solo_target=solo_target,
                             auto_accept_level=auto_accept_level,
                             branch_name=branch)
```

> **Note on `_on_branch_active_token`:** the in-flight marker is cleared on entry even for stale results, so a future refresh can start. That is intentional and safe — clearing a *marker* is not mutating project cache state.

**Project close invalidation — Round 3 BUG #1 (CRIT): named method, NOT lambda-inserted.** The existing registration at window.py:548 is a tuple-returning lambda (expression-only), so assignment statements cannot be added inside it (that was the `SyntaxError` in FIX-2). Instead, define a named method and register it as its **own** callback — `ProjectHandler.set_on_project_closed` is append-based and supports multiple callbacks (verified: `self._on_project_closed: list[Callable]`, fired via `for cb in self._on_project_closed: cb(closing_name)` at line 248).

```python
def _on_project_closed(self, name: str) -> None:
    """Invalidate any in-flight branch request when a project closes.

    Round 3 BUG #1: defined as a NAMED method (not inserted into the existing
    tuple lambda, which cannot contain assignment statements). Registered as an
    ADDITIONAL callback via set_on_project_closed — the handler supports
    multiple open/close callbacks, so this runs alongside (not instead of)
    the existing feed/crabwatch/review shutdown lambdas.
    """
    self._branch_request_token += 1   # invalidate any in-flight worker
    self._branch_active_token = None
    self._branch_request_path = None
```

**Project open/switch invalidation — Round 3 BUG #2:** bump the token and clear the in-flight marker whenever a project opens (fires on every open *and* switch via `open_project` at project_handler.py:95):

```python
def _on_project_opened(self, name: str, path: str) -> None:
    """Invalidate in-flight branch state when a project opens or switches.

    Round 3 BUG #2: FIX-2 only invalidated on CLOSE. A project A->B switch
    without opening invalidation could let A's in-flight worker apply A's
    branch to B. This named method is registered as an ADDITIONAL
    set_on_project_opened callback (handler fires cb(name, path) at line 132).

    NOTE: the path-keyed cache (BUG #5) is deliberately NOT cleared here —
    switching back to A should reuse A's cached branch. Only the in-flight
    marker is invalidated so a stale worker result cannot land.
    """
    self._branch_request_token += 1
    self._branch_active_token = None
    self._branch_request_path = None
```

**New callback implementations:**

```python
def _on_agent_cycle_clicked(self, current_solo):
    """Cycle agent label: ALL(None) -> member[0] -> ... -> member[N-1] -> ALL(None)."""
    project_name = self._project_handler.get_active_project_name() \
        if self._project_handler else None
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
    # set_solo_target fires _on_solo_target_changed -> bar refreshes.

def _on_autoaccept_cycle_clicked(self, current_level):
    """Cycle auto-accept (file changes): off -> diffs -> files -> all -> off.

    Round 3 BUG #4: this does NOT optimistically rebuild the bar before
    confirmation. set_auto_accept_level() shows the warning gate on enable
    and only commits on confirm; the bar refresh happens in the
    on_auto_accept_level_changed callback AFTER _commit_auto_accept_level.
    """
    project_name = self._project_handler.get_active_project_name() \
        if self._project_handler else None
    if not project_name:
        return
    cycle = {"off": "diffs", "diffs": "files", "files": "all", "all": "off"}
    next_level = cycle.get(current_level, "off")
    if self._feed_handler is not None:
        self._feed_handler.set_auto_accept_level(next_level)
    # No bar rebuild here — the confirmation callback handles it (BUG #4).

def _on_solo_target_changed(self, project_name: str):
    """ProjectHandler fired after a solo-target change.

    Round 3 BUG #3: guard against a stale/non-active project name. The
    ProjectHandler implementation validates the project exists; this window
    guard additionally enforces that it is the ACTIVE project so a stale
    right-click selection cannot rebuild the bar for a closed project.
    """
    if not project_name or self._project_handler is None:
        return
    if self._project_handler.get_active_project_name() != project_name:
        return  # stale/non-active project — ignore (BUG #3)
    members = self._project_handler.get_project_members(project_name)
    self._on_feed_bar_update(
        project_name,
        len(members),
        solo_target=self._project_handler.get_solo_target(project_name),
    )

def _refresh_settings_bar_for_active(self, auto_accept_level=None):
    """Helper: rebuild the settings bar for the currently active project.

    Used by the on_auto_accept_level_changed callback (Round 3 BUG #4) so
    the bar reflects the new auto-accept level only AFTER async confirmation
    has committed it.
    """
    project_name = self._project_handler.get_active_project_name() \
        if self._project_handler else None
    if not project_name:
        self._on_feed_bar_update("", 0, auto_accept_level=auto_accept_level)
        return
    members = self._project_handler.get_project_members(project_name)
    self._on_feed_bar_update(
        project_name,
        len(members),
        solo_target=self._project_handler.get_solo_target(project_name),
        auto_accept_level=auto_accept_level,
    )

def _on_settings_btn_clicked(self):
    """⚙ -> open the existing Settings dialog (fresh instance each call)."""
    self._open_settings()
```

**Wiring (add after the existing `set_on_project_settings_update` call ~line 435).** Register the named open/close methods as ADDITIONAL callbacks (BUG #1/#2) and wire all setters:

```python
self._main_content.set_on_settings_clicked(self._on_settings_btn_clicked)
self._main_content.set_on_agent_cycle(self._on_agent_cycle_clicked)
self._main_content.set_on_autoaccept_cycle(self._on_autoaccept_cycle_clicked)

# Round 2 BUG #4: wire ProjectHandler solo-change -> bar refresh.
self._project_handler.set_on_solo_target_changed(self._on_solo_target_changed)

# Round 3 BUG #1/#2: register NAMED lifecycle methods as additional callbacks
# (project_handler supports multiple open/close callbacks — append-based).
self._project_handler.set_on_project_opened(self._on_project_opened)
self._project_handler.set_on_project_closed(self._on_project_closed)

# Round 3 BUG #4: after async auto-accept confirmation, refresh the bar.
# The callback takes the new level and rebuilds for the active project.
self._feed_handler.set_on_auto_accept_level_changed(
    self._refresh_settings_bar_for_active
)
```

**Line count:** ~170 added.

---

### 2.3 `ui/handlers/feed_handler.py` — auto-accept level read/write + post-confirm callback

Source of truth stays in `FeedHandler`. Add `get_auto_accept_level` / `set_auto_accept_level` / `_commit_auto_accept_level` (from FIX-1/2, unchanged) **plus** the new `on_auto_accept_level_changed` slot + fire (Round 3 BUG #4).

**`__init__`/slot additions (near the existing `set_show_auto_accept_warning` ~line 142):**

```python
def set_on_auto_accept_level_changed(self, cb: Callable[[str], None] | None) -> None:
    """Register a callback fired after an auto-accept level has COMMITTED.

    cb(level: str) — "off" | "diffs" | "files" | "all". Fired from
    _commit_auto_accept_level() after _refresh_auto_accept_state(), i.e.
    only after the user confirms the warning dialog (Round 3 BUG #4). Safe
    to call with None to unregister.
    """
    self._on_auto_accept_level_changed = cb
```

```python
# In __init__ (near `self._show_auto_accept_warning`, line ~111):
self._on_auto_accept_level_changed: Callable[[str], None] | None = None
```

**`get_auto_accept_level` (unchanged from FIX-1/2):**

```python
def get_auto_accept_level(self) -> str:
    """File-change auto-accept level: "off" | "diffs" | "files" | "all".

    Scoped to FILE changes only; exec is a separate axis. Distinct,
    round-trippable mapping:
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
```

**`set_auto_accept_level` (unchanged — warning gate on enable):**

```python
def set_auto_accept_level(self, level: str) -> None:
    """Set file-change auto-accept level; enabling routes through the warning gate.

    level in {"off","diffs","files","all"}; invalid -> no-op. Enabling states
    call the warning callback (category + agent + on_confirm/on_cancel) and
    only commit on confirm. All commits call _refresh_auto_accept_state().
    """
    if level not in ("off", "diffs", "files", "all") or self._prefs is None:
        return
    if level == "off":
        for ct in self._prefs.file_changes:
            self._prefs.file_changes[ct].enabled = False
        self._refresh_auto_accept_state()
        self._emit_auto_accept_level_changed(level)
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
```

> **Note (Round 3 BUG #4):** For `level == "off"` there is no warning dialog, so the commit fires and the callback runs immediately (confirmed — no async gap). For enabling levels, the callback runs only in `_commit_auto_accept_level` (after the user confirms). The `on_cancel` path only calls `_refresh_auto_accept_state()`, which does **not** emit the change callback — so the bar correctly stays at the old level when the user cancels.

**`_commit_auto_accept_level` (fires the new callback after refresh — Round 3 BUG #4):**

```python
def _emit_auto_accept_level_changed(self, level: str) -> None:
    """Fire the on_auto_accept_level_changed callback (Round 3 BUG #4)."""
    if self._on_auto_accept_level_changed is not None:
        self._on_auto_accept_level_changed(level)

def _commit_auto_accept_level(self, level: str) -> None:
    """Write the distinct file-change state and sync (internal).

    Round 3 BUG #4: after _refresh_auto_accept_state() this emits
    on_auto_accept_level_changed so the settings bar rebuilds with the
    newly committed level. FeedTab/persistence are updated by the refresh;
    MainWindow is updated by this callback — not by the cycle handler.
    """
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
    self._emit_auto_accept_level_changed(level)
```

**Imports required:** none new (`Callable` already imported).

**Files NOT changed:** `.crabcakes/feed-prefs.json`, `models/feed_card.py` — v2 schema sufficient.

---

### 2.4 `ui/handlers/project_handler.py` — solo-target validation + change callback

**Verified current state:** `set_solo_target` (line 376) only assigns `self._solo_targets[project_name] = member_session_key` — no validation, no callback. `_get_project_path(project_name)` (line ~533) resolves a project's path (active path fast-path, else searches `load_projects()`), returning `None` for an unknown/deleted project.

**`__init__` addition (near `_solo_targets` ~line 363):**

```python
self._solo_targets: dict[str, str | None] = {}
# Round 2 BUG #4: fired after a solo-target change so the settings bar
# can refresh immediately on right-click member selection.
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

**Modified `set_solo_target` (Round 3 BUG #3 — validate project existence; Option A, strict):**

```python
def set_solo_target(self, project_name: str, member_session_key: str | None):
    """Set or clear the solo DM target for a project.

    Args:
        project_name:          Name of the project (must be an existing project).
        member_session_key:    Session key of the solo recipient, or None to
                               restore group broadcast (All members).

    Round 3 BUG #3 (Option A — strict): the project must exist. An unknown
    or deleted project name is a no-op (returns None, fires nothing) so a
    stale right-click selection cannot create orphaned solo-target state.
    Fires _on_solo_target_changed(project_name) only when the value actually
    changes (old == new -> no-op) to avoid redundant bar rebuilds.
    """
    if self._get_project_path(project_name) is None:
        return  # unknown project — no-op (BUG #3)
    old = self._solo_targets.get(project_name)
    if old == member_session_key:
        return  # no change — skip redundant callback
    self._solo_targets[project_name] = member_session_key
    if self._on_solo_target_changed is not None:
        self._on_solo_target_changed(project_name)
```

> **Behavior change:** previously `set_solo_target` silently created state for any name. Now an unknown project is rejected at the handler level (Option A). The window callback additionally guards against non-**active** projects (§2.2 `_on_solo_target_changed`), closing the remaining gap where the project exists but is not the active tab. Both checks are cheap and idempotent.

**Files NOT changed:** none within `project_handler.py` beyond the above.

---

### 2.5 `ui/styles.py` — CSS (unchanged from FIX-1/2)

Identical to FIX-1/2 §2.4 — the 3 interactive-class rule blocks (`.project-bar-agent`, `.project-bar-autoaccept`, `.project-bar-gear`) with GTK4-safe `:hover`/`:active` and **no `text-align`**. No changes needed for the Round 3 fixes.

---

## 3. Data Flow

### Branch refresh (token-guarded, path-keyed — Round 2 BUG #1/#2/#7 + Round 3 BUG #2/#5/#6)
1. Project opens → line 540 calls `_on_feed_bar_update(name, count)` → `branch_name is None`; the scheduler computes `active_path`, looks up `_cached_branch_by_path[active_path]`.
2. If the active project's branch is **not cached** (`needs_resolution`) and **no worker is running** (`already_running` is False) → `_schedule_branch_refresh(...)`. These are two independent conditions (BUG #6) — a cached branch suppresses scheduling even after member/solo churn.
3. `_schedule_branch_refresh` captures `path = get_active_project_path()`, increments `_branch_request_token`, sets `_branch_active_token = token` and `_branch_request_path = path` (all GTK thread), spawns a daemon thread.
4. Worker reads only the captured `path`, calls `get_branch(path)`, dispatches `_on_branch_result` via `GLib.idle_add`.
5. `_on_branch_result` (GTK thread) **first** clears the in-flight marker, **then** runs all staleness + identity checks (token, path, active-name, active-path) **before** any cache write (BUG #2). On acceptance it writes `_cached_branch_by_path[path]` and re-calls `_on_feed_bar_update` with `branch_name=branch` → bar shows `⎇ main`.
6. `_on_project_closed` (named method, registered as its own callback — BUG #1) bumps the token / clears in-flight on close; `_on_project_opened` does the same on open/switch (BUG #2). A stale result is discarded by token/path mismatch.
7. Switching A→B→A reuses A's cached branch from `_cached_branch_by_path` (BUG #5) — no redundant subprocess.

### Right-click solo selection (Round 2 BUG #4 + Round 3 BUG #3)
1. Right-click project tab → `_on_project_solo_selected` → `ProjectHandler.set_solo_target(project_name, target_sk)`.
2. `set_solo_target` validates the project exists (Option A, BUG #3), detects a change, updates `_solo_targets`, fires `_on_solo_target_changed(project_name)`.
3. Window `_on_solo_target_changed` guards that the project is **active** (BUG #3), reads current members + solo target → `_on_feed_bar_update(name, len(members), solo_target=...)` → bar rebuilds with the new agent name (or `ALL`).

### Auto-accept cycle with async confirmation (Round 3 BUG #4)
1. Click auto label → `_on_autoaccept_label_clicked(current)` → `_on_autoaccept_cycle(current)`.
2. Window `_on_autoaccept_cycle_clicked` calls `FeedHandler.set_auto_accept_level(next)` only — **no optimistic bar rebuild** (BUG #4). For enabling levels, `set_auto_accept_level` shows the warning dialog via `_show_auto_accept_warning_v2(category, agent, on_confirm, on_cancel)` (already wired at window.py:483) and waits.
3. User clicks "Turn On" → `on_confirm` → `_commit_auto_accept_level(level)` → `_refresh_auto_accept_state()` (updates FeedTab + persistence) → then **emits** `on_auto_accept_level_changed(level)`.
4. Window's `_refresh_settings_bar_for_active` receives the new level, reads active name + members + solo → `_on_feed_bar_update(name, len(members), auto_accept_level=level, ...)` → bar shows the newly committed level.
5. If the user cancels → `on_cancel` → `_refresh_auto_accept_state()` only (no emit) → bar stays at the old level.

### Agent cycle
1. Click agent label → `_on_agent_cycle_clicked` → advances member index → `set_solo_target` → fires `_on_solo_target_changed` → bar refreshes (BUG #4 path).

### Settings dialog
1. Click ⚙ → `_on_settings_btn_clicked` → `_open_settings()` → fresh `SettingsDialog`.

---

## 4. File Change Summary

| File | Change Type | Est. Lines | Risk |
|------|-------------|------------|------|
| `ui/views/main_content.py` | Modified — bar rebuild, xml_escape hardening (Round 2 BUG #6), gear re-append (BUG #5), `.get()` fallback (Round 3 BUG #7) | +150 | Low |
| `ui/window.py` | Modified — path-keyed branch worker (Round 3 BUG #5/#6), reordered result check (BUG #2), named open/close invalidation methods (BUG #1/#2), no-optimistic auto cycle (BUG #4) | +175 | Medium |
| `ui/handlers/feed_handler.py` | Modified — get/set/commit + `on_auto_accept_level_changed` emit (Round 3 BUG #4) | +65 | Medium |
| `ui/handlers/project_handler.py` | Modified — `_on_solo_target_changed` slot + setter + validate in `set_solo_target` (Round 2 BUG #4 + Round 3 BUG #3) | +25 | Low |
| `ui/styles.py` | Modified — 3 CSS rule blocks (unchanged from FIX-1/2) | +45 | None |
| **Total** | | **~460** | **Low-Medium** |

**Files NOT changed (already correct):**
- `ui/views/session_menu.py` — right-click menu + `on_select` intact.
- `ui/views/settings_dialog.py` — opened via `_open_settings()`.
- `utils/git_ops.py` — `get_branch()` used as-is (incl. detached-HEAD contract).
- `models/feed_card.py`, `.crabcakes/feed-prefs.json` — v2 schema sufficient.
- `utils/escaping.py` — both `escape_for_pango` and `xml_escape_text` used appropriately.
- `ui/styles.py` `.project-feed-bar` — kept.

---

## 5. Implementation Order

### Step 1 — CSS (no deps)
Add the 3 rule blocks to `ui/styles.py`. Verify no CSS parse errors.

### Step 2 — FeedHandler
Add `get_auto_accept_level` / `set_auto_accept_level` / `_commit_auto_accept_level` / `_emit_auto_accept_level_changed` / `set_on_auto_accept_level_changed` (BUG #4). Unit tests:
- Round-trip all 4 levels in-memory AND via `to_dict()`/`from_dict()`.
- Assert `_refresh_auto_accept_state` called after each commit.
- Assert warning wire receives `("files", agent, on_confirm, on_cancel)` for `files`/`all`, and on_cancel does **not** emit (BUG #4).

### Step 3 — MainContent
Add `_settings_btn` init, `_clear_settings_bar`, `_resolve_agent_display_name` (BUG #7 fix), 3 click handlers, 3 setters, `update_project_settings`, and gear re-append in legacy methods.

**Regression test (Round 2 BUG #5):** construct MainContent with a fake box; call `set_project_settings_text("x")`; assert `self._settings_btn` still has a parent (re-appended).

### Step 4 — ProjectHandler
Add `_on_solo_target_changed` slot + `set_on_solo_target_changed` setter + validate in `set_solo_target` (BUG #3). **Regression tests:**
- `set_solo_target("nonexistent", "agent:x")` is a no-op — `_solo_targets` has no `"nonexistent"` key (BUG #3).
- Set solo target X → callback fired with project_name; set same target again → callback NOT re-fired (BUG #4 redundancy guard).

### Step 5 — window.py wiring
Extend `_on_feed_bar_update` (BUG #6), add path-keyed branch worker (`_schedule_branch_refresh` / `_resolve_branch_worker` / `_on_branch_result` reordered per BUG #2), add the 5 init fields (BUG #5), add named `_on_project_closed`/`_on_project_opened` (BUG #1/#2), add 5 callback impls (agent cycle, auto cycle without optimistic rebuild — BUG #4, solo changed with active guard — BUG #3, `_refresh_settings_bar_for_active`, settings), and wire all setters + named lifecycle registrations.

**Regression tests (Round 2 BUG #2/#3/#1/#7 + Round 3 BUG #1/#2/#5/#6):**
- **BUG #1 (Round 3):** `_branch_active_token is None` (initial) → `_on_feed_bar_update("A", 2)` with `branch_name=None` and empty cache starts a worker. Then call `_on_project_closed("A")` → assert `_branch_active_token is None`, `_branch_request_path is None`, and `_cached_branch_by_path` is unchanged (BUG #1 — cache is NOT cleared on close, only in-flight state; per BUG #5 the path-keyed cache persists). Assert a stale `_on_branch_result(...)` is discarded.
- **BUG #2 (Round 3):** schedule for A (token 1, path /a); open B (`_on_project_opened("B", "/b")` bumps token to 2); call `_on_branch_result(1, /a, "A", ...)` → assert discarded — `_cached_branch_by_path` has no `/a` entry written, active B bar unchanged. Assert the active-name+active-path checks happen **before** cache write (inspect via ordering test or a spy on `_cached_branch_by_path`).
- **BUG #5 (Round 3):** open A → resolve "main" into `_cached_branch_by_path["/a"]`; open B → resolve "feature" into `_cached_branch_by_path["/b"]`; switch back to A → assert A's bar shows "main" (path-keyed cache hit, no new worker).
- **BUG #6 (Round 3):** after a branch is cached for the active path, call `_on_feed_bar_update("A", 2)` again → assert **no** new worker is scheduled (cache check suppresses `needs_resolution`).
- **BUG #3 (Round 2):** project with 3 members; `_on_autoaccept_cycle_clicked("off")` → assert `_feed_handler` receives `set_auto_accept_level("diffs")` and the bar is **not** rebuilt before confirmation.
- **BUG #7 (Round 2):** two rapid refreshes — second supersedes the first (`_branch_request_token` increments); only newest result applies.

### Step 6 — End-to-end
Open project → `[name · N] [ALL] [⚡ files: off] [⎇ branch] [⚙]`; right-click → agent green; agent click cycles; auto click cycles (warning on enable, **bar updates only after confirmation — BUG #4**); ⚙ opens settings. Switch projects → no branch bleed (BUG #2/#5); close → in-flight invalidated (BUG #1).

---

## 6. Acceptance Criteria

- [ ] `update_project_settings` rebuilds the bar with all 5 elements; `ALL` for `solo_target=None`, else display name (green).
- [ ] Empty project (falsy name) → bar hidden.
- [ ] Branch refresh actually runs (Round 2 BUG #1); branch shows name / `(detached HEAD)` / `—`.
- [ ] Rapid project switch/close cannot apply a stale branch to the wrong project (Round 2 BUG #2/#7 + Round 3 BUG #2: checks BEFORE cache write; open/switch invalidation).
- [ ] Project close invalidation is legal Python — no assignment inside a lambda (Round 3 BUG #1 CRIT: named `_on_project_closed` method).
- [ ] `set_solo_target("nonexistent", ...)` is a no-op; window callback ignores non-active projects (Round 3 BUG #3).
- [ ] Auto-accept click does not optimistically change the bar; bar updates only after async confirmation via `on_auto_accept_level_changed` (Round 3 BUG #4).
- [ ] Branch cache is keyed by project path; switching A→B→A reuses A's cached branch (Round 3 BUG #5).
- [ ] After a branch is cached, no redundant worker is scheduled for the same project (Round 3 BUG #6).
- [ ] Special-agent mapping with `{"special:x": ""}` returns `"special:x"` (not `""`/`None`) (Round 3 BUG #7).
- [ ] Right-click solo selection updates the bar immediately via `_on_solo_target_changed` (Round 2 BUG #4).
- [ ] Legacy `set_project_settings_text`/`set_feed_bar_text` preserve the gear (Round 2 BUG #5).
- [ ] Project name/branch render literally — `<b>` in a project name is NOT bolded (Round 2 BUG #6).
- [ ] Auto-accept cycles `off→diffs→files→all→off`, distinct persisted states, warning gate on enable.
- [ ] **Every code sample in this spec passes `ast.parse()` (Round 3 BUG #1 was a `SyntaxError`).** Verified in §10.

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
| Warning dialog cancelled | `on_cancel` → `_refresh_auto_accept_state()` only; **no emit**; bar stays at current level (BUG #4) |
| Project closed mid-branch-refresh | `_on_project_closed` bumps token (named method — BUG #1); stale result discarded |
| Switch project A→B mid-refresh | `_on_project_opened` bumps token (BUG #2); token+path mismatch → stale discarded; B's refresh applies |
| Switch back A→B→A | A's cached branch reused from `_cached_branch_by_path` (BUG #5); no redundant worker (BUG #6) |
| `set_solo_target("nonexistent", ...)` | no-op — no state created, no callback (BUG #3) |
| Solo callback for non-active existing project | window `_on_solo_target_changed` guards active name → ignored (BUG #3) |
| Re-selecting the same solo member | `set_solo_target` no-ops (old == new); no redundant rebuild (BUG #4) |
| `_on_feed_bar_update` after project close | empty branch hides bar |
| Project name has Pango specials | `xml_escape_text` → literal (Round 2 BUG #6) |
| Special-agent value is `""`/`None` | `.get()` truthiness → fall through to session_key (BUG #7) |
| Legacy `set_project_settings_text`/`set_feed_bar_text` | gear re-appended (Round 2 BUG #5) |
| 10+ members | cycle wraps correctly |

## 8. ARCHITECTURE.md Updates Required

1. §3.16 `ui/handlers/feed_handler.py` — add `get_auto_accept_level` / `set_auto_accept_level` / `set_on_auto_accept_level_changed` to public API; note file-scoped semantics + post-confirm emit.
2. Module-responsibility section for `ui/views/main_content.py` — document `update_project_settings`, 3 setters, child-clear helper, the gear-reappend invariant, and the `.get()` fallback in `_resolve_agent_display_name`. *(Correct the stale §3.7 citation — that section documents `left_panel.py`, not `main_content.py`.)*
3. `ui/handlers/project_handler.py` — document the new `set_on_solo_target_changed` public API and that `set_solo_target` now validates project existence (BUG #3) and fires the callback on real change.
4. `ui/window.py` §3.6 wiring note — document the path-keyed branch cache (`_cached_branch_by_path`), the 5 new settings-bar callbacks, the named `_on_project_opened`/`_on_project_closed` invalidation methods, and the post-confirm auto-accept refresh (BUG #4).

---

## 9. How Each Round 3 Finding Is Addressed

| # | Sev | Fix (§) |
|---|-----|---------|
| 1 | CRIT | **Project-close invalidation is a named `_on_project_closed(name)` method (§2.2), registered as its OWN `set_on_project_closed` callback — NOT inserted into the tuple lambda (which is expression-only → `SyntaxError`).** The handler's open/close registration is append-based (verified: `self._on_project_closed: list` fired via `for cb: cb(closing_name)`), so coexisting with the existing feed/crabwatch/review lambdas is safe. Regression test in §5 Step 5: close → in-flight cleared, stale result discarded. |
| 2 | HIGH | **`_on_branch_result` runs ALL checks (token, path, active-name, active-path) BEFORE writing `_cached_branch_by_path` (§2.2).** Added named `_on_project_opened(name, path)` invalidating in-flight state on open AND switch (not just close) (§2.2). Regression tests in §5 Step 5: switch A→B mid-refresh discards A's stale result; ordering test asserts cache write follows identity check. |
| 3 | HIGH | **Option A (strict): `set_solo_target` validates `_get_project_path(project_name) is not None` before mutating (§2.4).** Window `_on_solo_target_changed` additionally guards `get_active_project_name() == project_name` (§2.2). Regression tests: `set_solo_target("nonexistent", ...)` is a no-op; non-active project callback ignored. |
| 4 | HIGH | **New `set_on_auto_accept_level_changed` callback + `_emit_auto_accept_level_changed` fired in `_commit_auto_accept_level` after `_refresh_auto_accept_state()` (§2.3).** Window wires it to `_refresh_settings_bar_for_active` (§2.2). `_on_autoaccept_cycle_clicked` no longer optimistically rebuilds — it only calls `set_auto_accept_level(next)` (§2.2). Regression test in §5 Step 5: `off→files` click leaves bar at "off" until confirmation, then "files". |
| 5 | MED | **Replaced single `_cached_branch` with `_cached_branch_by_path: dict[str, str]` (§2.2).** `_on_feed_bar_update` looks up by `get_active_project_path()`; `_on_branch_result` writes to `[path]`. Regression test: open A ("main"), open B ("feature"), switch back to A → bar shows "main" (§5 Step 5). |
| 6 | MED | **Scheduling condition split into `needs_resolution` (cache check on active path) and `already_running` (in-flight check) (§2.2).** `_schedule_branch_refresh` only starts when `needs_resolution and not already_running`. Regression test: after a branch is cached for the active path, a subsequent `_on_feed_bar_update` schedules no new worker (§5 Step 5). |
| 7 | MED | **`_resolve_agent_display_name` uses `special.get(session_key)` + truthiness instead of `if session_key in special` (§2.1).** Empty/None values fall through to `session_key`. Regression test: `{"special:x": ""}` → returns `"special:x"` (§5 Step 3). |

## 10. Spec Self-Audit (Rule 9) + Empirical + `ast.parse()` Verification

**Rule 1** — Re-read `ui/views/main_content.py`, `ui/window.py` (wiring, `_on_feed_bar_update`, `_open_settings`, both lifecycle registration sites), `ui/handlers/feed_handler.py` (warning slot, `_refresh_auto_accept_state`, v2 wiring), `ui/handlers/project_handler.py` (`set_solo_target`, `_get_project_path`, open/close firing), `ui/handlers/agent_runtime_handler.py` (`get_special_agents`), `utils/projects.py`, `utils/escaping.py`, `utils/git_ops.py`.

**Rule 2/3** — Signatures verified against source:
- `ProjectHandler.set_on_project_closed(cb: Callable)` — append-based, fires `cb(closing_name)` (1-arg) ✓
- `ProjectHandler.set_on_project_opened(cb: Callable)` — append-based, fires `cb(name, path)` (2-arg) ✓
- `get_active_project_path() -> str | None` ✓, `get_active_project_name() -> str | None` ✓
- `_get_project_path(project_name) -> str | None` (exists, line ~533) ✓
- `set_solo_target(project_name, member_session_key)` ✓ (currently no validation/callback)
- `get_solo_target(project_name) -> str | None` ✓, `get_project_members(project_name)` ✓
- `FeedHandler.set_show_auto_accept_warning(cb)` accepts 4-arg `(category, agent_name, on_confirm, on_cancel)` (wired at window.py:483) ✓
- `_refresh_auto_accept_state()` exists (line 376) ✓
- `ARTH.get_special_agents() -> dict[str, str]` `{conv_id_prefix: display_name}` ✓
- `get_branch(path) -> GitResult` (never raises; `(detached HEAD)` on detached) ✓
- `_open_settings()` ✓, `GLib.idle_add` ✓

**Rule 4** — `get_branch` returns `GitResult` (never raises); worker wraps regardless. `set_auto_accept_level` guards `_prefs is None` + invalid level. Handler refs null-guarded throughout.

**Rule 5** — `_solo_targets: dict[project, sk | None]`; `_cached_branch_by_path: dict[path, branch]` (new — BUG #5); `AutoAcceptPrefs.file_changes` keyed `diff|file_created|file_modified|file_deleted`; ARTH dict keyed by `conv_id_prefix`.

**Rule 6** — `get_branch` return checked (`result.success`); token/path/identity comparison return honored; `get_auto_accept_level` return consumed.

**Rule 7** — Every code path traced against source. No "should work" samples.

**Rule 8** — Files NOT changed listed in §2.x and §4.

**Rule 10** — Spec-fix round: no implementation yet. Implementation + regression tests specified in §5. Acceptance in §6.

### Empirical probes (Round 3)

1. **`ProjectHandler.set_on_project_closed` signature (BUG #1):**
   ```
   grep: set_on_project_closed(self, cb: Callable) at project_handler.py:393
   firings: for cb in self._on_project_closed: cb(closing_name)   (line 248, 1-arg)
   self._on_project_closed: list[Callable] = []                  (line 72)
   ```
   Confirms open/close registration is **append-based and multi-callback**, so registering an additional named `_on_project_closed(name)` / `_on_project_opened(name, path)` method is safe and does not require editing the existing tuple lambda. The FIX-2 instruction (assignment inside a lambda) is impossible → BUG #1 CRIT confirmed.

2. **`AgentRuntimeHandler.get_special_agents()` return shape (BUG #7):**
   ```
   def get_special_agents(self) -> dict[str, str]:
       return {sk: ad.display_name for sk, ad in self._agents.items()}
   ```
   Values are `display_name` strings but may be `""`/`None` for a partially-registered agent. `special.get(sk)` + truthiness correctly falls through. Key-membership (`if sk in special`) was BUG #7 — confirmed.

3. **`FeedHandler._refresh_auto_accept_state` behavior (BUG #4):**
   ```
   def _refresh_auto_accept_state(self) at feed_handler.py:376
   updates self._auto_accept_enabled + pushes prefs to FeedTab + persists (debounced)
   does NOT notify MainWindow to rebuild the settings bar
   ```
   Confirms the new `on_auto_accept_level_changed` callback is required: the commit path updates FeedTab/persistence but has no route to the window's bar. The v2 warning wiring at window.py:483 (`set_show_auto_accept_warning(lambda category, agent_name, on_confirm, on_cancel: ...)`) confirms confirmation is async → the bar must refresh post-commit, not optimistically.

4. **Existing window registration sites (BUG #1):** Two separate `set_on_project_closed` registrations already exist (window.py:548 feed/crabwatch/review shutdown and window.py:752 review handler). Both are tuple lambdas. Adding a third named-method registration is consistent with the existing multi-callback design.

### `ast.parse()` verification (Round 3 BUG #1 guard)

Every Python code block in this spec was extracted and parsed with `ast.parse()` AND an AST walk that rejects any assignment inside a lambda. Actual output:

```
Found 24 python code blocks
Parsed all blocks: 0 SyntaxError, 0 assignment-inside-lambda
```

Blocks include (fenced ```python blocks only): `_clear_settings_bar`, `update_project_settings`, `_resolve_agent_display_name`, the 3 click handlers, the 3 setters, the `__init__` additions, `set_project_settings_text`, `set_feed_bar_text`, the window state fields, `_on_feed_bar_update`, `_schedule_branch_refresh`, `_resolve_branch_worker`, `_on_branch_result`, `_on_project_closed`, `_on_project_opened`, the 5 window callbacks (+ `_refresh_settings_bar_for_active`), and the FeedHandler/ProjectHandler blocks (setter, slot, get/set/commit/emit, `set_solo_target`).

All blocks contain only valid, executable Python — no assignments inside lambdas (the 24-block count includes several single-line setter blocks).

> The FIX-2 `SyntaxError` (assignments inside the existing tuple lambda) is **impossible** in FIX-3: the invalidation lives in the bodies of named methods (`_on_project_closed`, `_on_project_opened`), which are normal `def` methods that can contain assignment statements. The existing tuple lambdas in window.py are left untouched.

---

## 11. Round 1 + Round 2 Verification Confirmation

All 18 Round 1 findings and all 7 Round 2 findings remain FIXED in FIX-3 (unchanged or reinforced):
- Round 1 #1–#4, #5–#12, #14, #17, #18 — carried unchanged.
- Round 1 #13 (blocking branch on GTK thread) — fully fixed (worker + token guard).
- Round 1 #15 (callback dispatch) — fully fixed (lifecycle sites + `set_on_solo_target_changed`).
- Round 1 #16 (per-tab overlay/reparenting) — fully fixed (close/switch invalidation + token/path staleness).
- Round 2 #1 (token `is None`) — carried unchanged.
- Round 2 #2 (cross-project branch) — **reinforced**: BUG #2 reorders checks before cache write + open/switch invalidation.
- Round 2 #3 (member count) — carried unchanged (and BUG #4 removes the optimistic rebuild).
- Round 2 #4 (solo wiring) — **reinforced**: BUG #3 adds handler-level validation + active-project guard.
- Round 2 #5 (gear re-append) — carried unchanged.
- Round 2 #6 (xml_escape) — carried unchanged.
- Round 2 #7 (thread-safe token) — carried unchanged (and BUG #5 expands to path-keyed cache).
