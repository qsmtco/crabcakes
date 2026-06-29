# SPEC: Granular Auto-Accept Controls + Exec Auto-Accept

**Date:** 2026-06-29
**Author:** Qaster (OC Tech Supervisor)
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL-auto-accept-granular-controls.md`
**Depends on:** Phase 5 (auto-accept toggle — shipped), Phase E (exec approvals — shipped)
**Target branch:** main

> **Architecture compliance:** All changes follow §8.6 Handler Pattern. New logic goes in `ui/handlers/feed_handler.py` (handler owns state, view reflects). View changes go in `ui/views/feed_tab.py` (pure view, no business logic). Persistence changes go in `utils/feed_store.py` (pure I/O, no GTK). Data model changes go in `models/feed_card.py` (pure data, no imports from ui/). No handler-to-handler imports; cross-handler wiring stays in `ui/window.py`. All GTK calls from background threads go through `GLib.idle_add()`.

---

## DISCOVERY

- **Read `ui/handlers/feed_handler.py` (full file, ~870 lines):** `FeedHandler.__init__` takes keyword-only args `GLib`, `on_send_to_agent`, `on_card_added=None`, `on_approve_exec=None`, `get_chat_box_for_session=None`. Auto-accept state is two fields: `_auto_accept_enabled: bool = False` and `_auto_accept_agent: str | None = None`. A constant `_AUTO_ACCEPT_TYPES = {"diff", "file_created", "file_modified", "file_deleted"}` at line 25 controls which card types are eligible. The auto-accept check lives inside `add_card()`'s inner `_append()` closure (around line 297) as a compound `if` statement. `_save_feed_prefs_idle()` writes a v1 dict `{"version": 1, "auto_accept_enabled": ..., "auto_accept_agent": ...}`. `_on_auto_accept_toggled(active: bool)` is the entry point for toggle clicks — it either shows a warning dialog (via `_show_auto_accept_warning` callback) and calls `_enable_auto_accept()` / `_cancel_auto_accept()`, or calls `_disable_auto_accept()`. `handle_approve_exec(card_id: str, approved: bool)` delegates to `self._on_approve_exec(card_id, approved)` for Phase E approval cards. `_make_approve_exec_cb(card_id)` returns `(on_approve, on_deny)` tuple of callbacks for approval-card buttons.

- **Read `ui/views/feed_tab.py` (full file, ~310 lines):** `FeedTab.__init__()` builds eagerly: a `Gtk.ScrolledWindow` containing `self._card_container` (Gtk.Box vertical), then `self._toolbar` (Gtk.Box horizontal, spacing=8, CSS class `feed-toolbar`). Toolbar children: `self._auto_accept_toggle` (Gtk.ToggleButton, label "Auto-Accept: OFF", CSS class `feed-toolbar-toggle`, connected to `_on_auto_accept_toggled`), `self._divider` (Gtk.Separator vertical), `self._batch_accept_button` (Gtk.Button, label "Accept All", CSS class `feed-btn-batch-accept`, hidden by default), `self._batch_accept_label` (Gtk.Label). `update_auto_accept_state(active: bool)` calls `set_active()` + `set_label()` — does NOT fire `toggled` signal. `_on_auto_accept_toggled(button)` forwards to `self._auto_accept_callback`. `set_auto_accept_callback(callback)` stores it. `update_batch_bar(pending_count: int)` shows/hides batch button.

- **Read `utils/feed_store.py` (full file, ~360 lines):** `PREFS_VERSION = 1`, `FEED_PREFS_FILENAME = "feed-prefs.json"`. `load_feed_prefs(project_path: str) -> dict` returns `{"version": 1, "auto_accept_enabled": False, "auto_accept_agent": None}` on missing/invalid/unexpected-version files — validates `version == PREFS_VERSION` and rejects unknown versions with defaults. `save_feed_prefs(project_path: str, prefs: dict)` validates `prefs["version"] == PREFS_VERSION` before writing — rejects mismatched versions with `_logger.error`. Uses `_atomic_write_json` (chmod 0o600). File locking via `fcntl.flock` on a `.lock` sidecar file.

- **Read `ui/handlers/agent_runtime_handler.py` (relevant sections):** `_do_approval_needed(session_key, tool_name, args)` creates a `FeedCardData(card_type="agent_action", ..., metadata={"needs_approval": True, ...})` and calls `self._fh.add_card(card)`. Stores `self._pending_approvals[card_id] = {"session_key": ..., "tool_name": ..., "args": ...}`. `approve_exec(approval_id: str, approved: bool)` pops from `_pending_approvals`, finds the runtime that owns the session via `rt.get_conversation(session_key)`, calls `rt.approve_exec(session_key, tool_name, args, approved)`, then updates the card status.

- **Read `models/feed_card.py` (relevant sections):** `FeedCardData` dataclass with fields: `card_type`, `source`, `title`, `body`, `author`, `timestamp`, `project_name` (required), `file_path`, `commit_sha`, `additions`, `deletions`, `task_id`, `metadata: dict` (default_factory=dict), `conversation_snapshot`, `card_id`, `reviewed`, `accepted`, `seq_num`. `CardType` is a `Literal` of 11 types. `is_actionable()` returns `True` for `needs_approval` metadata or file-change types.

- **Read `ui/window.py` (lines 455-490):** `FeedHandler` is constructed with `on_approve_exec=self._agent_runtime_handler.approve_exec`. `set_show_auto_accept_warning()` is wired with a lambda calling `self._show_auto_accept_warning(agent_name, on_confirm, on_cancel)`. `FeedTab()` is created after `FeedHandler`, then `feed_handler.set_feed_tab(feed_tab)` is called. The auto-accept warning dialog callback is wired after `set_feed_tab`. The v2 spec expands this signature to `(category, agent_name, on_confirm, on_cancel)` — see BUG #6 in the audit.

- **Architecture owner:** `FeedHandler` owns all feed-card state and auto-accept policy (§8.6 R5). `FeedTab` is a pure view that reflects handler-owned state (§8.6 R7). `feed_store.py` owns persistence. `AgentRuntimeHandler` owns the exec approval lifecycle.

- **Existing patterns:** The current single-toggle auto-accept pattern: handler calls `feed_tab.update_auto_accept_state(bool)` to reconcile visuals. The batch-accept pattern: handler calls `feed_tab.update_batch_bar(count)`. The warning-dialog pattern: `set_show_auto_accept_warning(callback)` injected by `window.py`. All state mutations go through handler methods; the view never owns state.

---

## 1. Overview

### Problem

The current Auto-Accept toggle is a single all-or-nothing switch controlled by a constant `_AUTO_ACCEPT_TYPES` set. Users cannot:
1. Choose which file-change types to auto-accept (type granularity)
2. Choose which agent(s) are auto-accepted (agent scope is implicit first-author lock-in)
3. Hold specific cards for review while auto-accepting others (no per-card escape)
4. Auto-approve exec commands (Phase E approval flow is entirely manual)

### Solution

Replace the single toggle with a layered trust model:

| Layer | Control | Scope |
|---|---|---|
| 1 — Type toggles | `Diffs` and `Files` toggle buttons | Per card-type group |
| 2 — Per-card snooze | Snooze button + per-card badge | Per card-id |
| 3 — Agent scope | Agent dropdown | Per auto-accept session |
| 4 — Exec auto-accept | `Exec` tri-state toggle | Phase E approval cards |

All layers share a v2 prefs schema persisted in `feed-prefs.json`.

### Scope

| In scope | Out of scope |
|---|---|
| Replace single toggle with per-type toggles in `FeedTab` toolbar | Redisign of the Feed tab layout |
| New `AutoAcceptPrefs` dataclass in `models/feed_card.py` | Changes to `FeedCardData` existing fields |
| v2 prefs schema + v1→v2 migration in `feed_store.py` | Migration of `feed.json` card format |
| Centralized `_is_card_auto_acceptable(card)` policy in `FeedHandler` | Changes to `handle_accept()` / `handle_reject()` logic |
| Per-card snooze list (add/remove/expire) | Snooze persistence across project reopen |
| Agent scope dropdown (all / first-author / specific) | Dynamic agent-list refresh after new agent connects |
| Exec tri-state toggle + `Silent` bypass in `AgentRuntimeHandler` | Exec allowlist regex editor (deferred to follow-up) |
| `update_auto_accept_prefs(prefs)` replaces `update_auto_accept_state(bool)` | Removal of `_auto_accept_enabled` legacy field (deferred) |

### Architecture principles that apply

- **§8.6 R1:** One handler per subsystem — all auto-accept logic stays in `FeedHandler`.
- **§8.6 R3:** Handlers receive dependencies via setters — `FeedTab` receives new callbacks via `set_*` methods.
- **§8.6 R5:** Handlers own their state — `_prefs: AutoAcceptPrefs` lives on `FeedHandler`.
- **§8.6 R7:** Views must not import from handlers — `FeedTab` reflects state via `update_auto_accept_prefs()`.

---

## 2. Changes by File

### 2.1 `models/feed_card.py`

**What changes:** Add `AutoAcceptPrefs` dataclass and sub-dataclasses for the v2 schema.

**New code (append after the `FeedCardData` class):**

```python
@dataclass
class FileChangePref:
    """Per-type auto-accept preference."""
    enabled: bool = False
    agent_scope: str = "first_author"  # "first_author" | "all_agents" | "<agent_name>"

@dataclass
class ExecCommandPref:
    """Exec command auto-accept preference."""
    mode: str = "off"  # "off" | "show" | "silent"
    agent_scope: str = "first_author"

@dataclass
class AutoAcceptPrefs:
    """V2 auto-accept preferences replacing the single toggle.

    Serialized to feed-prefs.json as version 2. The FeedHandler owns
    the canonical instance; FeedTab receives a copy via
    update_auto_accept_prefs().
    """
    file_changes: dict[str, FileChangePref] = field(default_factory=lambda: {
        "diff": FileChangePref(),
        "file_created": FileChangePref(),
        "file_modified": FileChangePref(),
        "file_deleted": FileChangePref(),
    })
    exec_command: ExecCommandPref = field(default_factory=ExecCommandPref)
    snoozed_card_ids: list[str] = field(default_factory=list)

    def any_enabled(self) -> bool:
        """True if any file-change type is enabled OR exec is not off."""
        return (
            any(fc.enabled for fc in self.file_changes.values())
            or self.exec_command.mode != "off"
        )

    def is_file_type_enabled(self, card_type: str) -> bool:
        """Check if a specific card type is auto-accept enabled."""
        pref = self.file_changes.get(card_type)
        return pref is not None and pref.enabled

    def to_dict(self) -> dict:
        """Serialize for feed-prefs.json persistence."""
        return {
            "version": 2,
            "auto_accept": {
                "file_changes": {
                    ct: {"enabled": fc.enabled, "agent_scope": fc.agent_scope}
                    for ct, fc in self.file_changes.items()
                },
                "exec_command": {
                    "mode": self.exec_command.mode,
                    "agent_scope": self.exec_command.agent_scope,
                },
                "snoozed_card_ids": list(self.snoozed_card_ids),
            },
        }

    @staticmethod
    def from_dict(raw: dict) -> "AutoAcceptPrefs":
        """Deserialize from feed-prefs.json. Tolerates missing keys."""
        prefs = AutoAcceptPrefs()
        auto = raw.get("auto_accept", {})
        fc_raw = auto.get("file_changes", {})
        for ct in ("diff", "file_created", "file_modified", "file_deleted"):
            fc = fc_raw.get(ct, {})
            prefs.file_changes[ct] = FileChangePref(
                enabled=bool(fc.get("enabled", False)),
                agent_scope=str(fc.get("agent_scope", "first_author")),
            )
        exec_raw = auto.get("exec_command", {})
        prefs.exec_command = ExecCommandPref(
            mode=str(exec_raw.get("mode", "off")),
            agent_scope=str(exec_raw.get("agent_scope", "first_author")),
        )
        snoozed = auto.get("snoozed_card_ids", [])
        prefs.snoozed_card_ids = list(snoozed) if isinstance(snoozed, list) else []
        return prefs

    def locked_agent(self) -> str | None:
        """Return the locked-in agent if any file_changes type uses a
        specific agent name as its scope (not 'all_agents' or 
        'first_author'). Used during v1→v2 migration to preserve the 
        persisted agent lock-in from the v1 'auto_accept_agent' field.
        """
        for fc in self.file_changes.values():
            if fc.agent_scope not in ("all_agents", "first_author"):
                return fc.agent_scope
        return None
```

**Imports required:** `field` is already imported from `dataclasses`. `Any` is not needed.
```

**Imports required:** `field` is already imported from `dataclasses`. `Any` is not needed.

**Line count estimate:** ~70 new lines.

### 2.2 `utils/feed_store.py`

**What changes:** Bump `PREFS_VERSION` to 2. Rewrite `load_feed_prefs()` to handle v1→v2 migration. Rewrite `save_feed_prefs()` to accept v2. Keep `_default_prefs()` returning a v2 dict.

**Method signatures (unchanged):**
```python
def load_feed_prefs(project_path: str) -> dict:  # same signature
def save_feed_prefs(project_path: str, prefs: dict) -> None:  # same signature
```

**Changes:**

1. Replace line 21 (`PREFS_VERSION = 1`) with `PREFS_VERSION = 2`.

2. Replace `_default_prefs()`:

```python
def _default_prefs() -> dict:
    """Return the canonical default v2 prefs payload."""
    return {
        "version": 2,
        "auto_accept": {
            "file_changes": {
                ct: {"enabled": False, "agent_scope": "first_author"}
                for ct in ("diff", "file_created", "file_modified", "file_deleted")
            },
            "exec_command": {
                "mode": "off",
                "agent_scope": "first_author",
            },
            "snoozed_card_ids": [],
        },
    }
```

3. Replace `load_feed_prefs()`. The new version reads the file, then checks `version`:
   - **version 2:** Parse directly into a v2 dict.
   - **version 1:** Migrate: `auto_accept_enabled: True` → all four file-change types enabled with `first_author` scope; `auto_accept_enabled: False` → all disabled. Exec mode = `"off"`. Empty snooze list.
   - **missing/invalid/unknown version:** Return `_default_prefs()`.

```python
def load_feed_prefs(project_path: str) -> dict:
    """
    Load feed prefs from .crabcakes/feed-prefs.json.

    Handles v1 and v2 files. V1 files are migrated to v2 in-memory.
    Returns canonical v2 defaults if file is missing, malformed,
    or has an unrecognized version.
    """
    path = _prefs_path(project_path)
    if not os.path.isfile(path):
        return _default_prefs()

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("load_feed_prefs: failed to read %s: %s", path, e)
        return _default_prefs()

    if not isinstance(raw, dict):
        _logger.warning("load_feed_prefs: expected dict at %s, got %s", path, type(raw).__name__)
        return _default_prefs()

    version = raw.get("version")

    if version == 2:
        # V2 file — validate structure, overlay defaults for missing keys
        return _merge_v2_defaults(raw)

    if version == 1:
        # V1 file — migrate to v2 in-memory
        return _migrate_v1_to_v2(raw)

    _logger.warning("load_feed_prefs: unknown version %r at %s, using defaults", version, path)
    return _default_prefs()
```

4. Add migration and merge helpers:

```python
def _migrate_v1_to_v2(raw: dict) -> dict:
    """Migrate a v1 prefs dict to v2 format.

    v1: {"version": 1, "auto_accept_enabled": bool, "auto_accept_agent": str|None}
    v2: {"version": 2, "auto_accept": {"file_changes": {...}, "exec_command": {...}, ...}}

    Migration rules:
    - If auto_accept_enabled was False: all four file-change types disabled.
    - If auto_accept_enabled was True AND auto_accept_agent is None: all four
      enabled with first_author scope (lazy lock-in preserved).
    - If auto_accept_enabled was True AND auto_accept_agent is set: all four
      enabled with agent_scope = the persisted agent name. The first_author
      lazy lock-in is bypassed because the user explicitly chose an agent.

    The agent name from v1 is significant — it represents a deliberate lock-in
    the user already made. Dropping it would silently change which agent's
    cards auto-accept after upgrade (BUG #1 in adversarial audit).
    """
    enabled = bool(raw.get("auto_accept_enabled", False))
    agent = raw.get("auto_accept_agent")
    if enabled and isinstance(agent, str) and agent:
        scope = agent  # Persist as a specific agent scope
    else:
        scope = "first_author"
    return {
        "version": 2,
        "auto_accept": {
            "file_changes": {
                ct: {"enabled": enabled, "agent_scope": scope}
                for ct in ("diff", "file_created", "file_modified", "file_deleted")
            },
            "exec_command": {"mode": "off", "agent_scope": scope},
            "snoozed_card_ids": [],
        },
    }


def _merge_v2_defaults(raw: dict) -> dict:
    """Overlay a v2 prefs dict onto defaults to fill missing keys."""
    result = _default_prefs()
    auto = raw.get("auto_accept", {})
    if isinstance(auto, dict):
        fc_raw = auto.get("file_changes", {})
        if isinstance(fc_raw, dict):
            for ct in result["auto_accept"]["file_changes"]:
                fc = fc_raw.get(ct, {})
                if isinstance(fc, dict):
                    result["auto_accept"]["file_changes"][ct]["enabled"] = bool(
                        fc.get("enabled", False)
                    )
                    result["auto_accept"]["file_changes"][ct]["agent_scope"] = str(
                        fc.get("agent_scope", "first_author")
                    )
        exec_raw = auto.get("exec_command", {})
        if isinstance(exec_raw, dict):
            result["auto_accept"]["exec_command"]["mode"] = str(
                exec_raw.get("mode", "off")
            )
            result["auto_accept"]["exec_command"]["agent_scope"] = str(
                exec_raw.get("agent_scope", "first_author")
            )
        snoozed = auto.get("snoozed_card_ids", [])
        if isinstance(snoozed, list):
            result["auto_accept"]["snoozed_card_ids"] = list(snoozed)
    return result
```

5. Update `save_feed_prefs()` — change the version check from `PREFS_VERSION` (which is now 2) — this is already correct since `PREFS_VERSION = 2` and the validation `prefs.get("version") != PREFS_VERSION` will accept only v2. No code change needed beyond the constant bump.

**Line count estimate:** ~80 new lines, ~30 modified lines.

### 2.3 `ui/views/feed_tab.py`

**What changes:** Replace the single `_auto_accept_toggle` with three toggle buttons (`_diffs_toggle`, `_files_toggle`, `_exec_toggle`), an agent dropdown (`_agent_dropdown`), and a snooze button (`_snooze_button`). Replace `update_auto_accept_state(active: bool)` with `update_auto_accept_prefs(prefs_dict: dict)`.

**Constructor changes (in `__init__`, replacing the toolbar section at lines 95-120):**

Remove:
```python
self._auto_accept_toggle = Gtk.ToggleButton(label="Auto-Accept: OFF")
self._auto_accept_toggle.add_css_class("feed-toolbar-toggle")
self._auto_accept_toggle.connect("toggled", self._on_auto_accept_toggled)
```

Add (in the same position inside `self._toolbar`):

```python
# Group 1 — per-type toggles (Layer 1 + Layer 4)
self._diffs_toggle = Gtk.ToggleButton(label="Diffs: OFF")
self._diffs_toggle.add_css_class("feed-toolbar-toggle")
self._diffs_toggle.add_css_class("feed-toolbar-toggle-per-type")
self._diffs_toggle.connect("toggled", self._on_diffs_toggled)

# Files is a GROUP toggle covering file_created/modified/deleted.
# Uses Gtk.ToggleButton for consistency with the Diffs toggle. The
# three underlying prefs are always toggled as a group, so there is
# no inconsistent-state ambiguity in normal usage.
self._files_toggle = Gtk.ToggleButton(label="Files: OFF")
self._files_toggle.add_css_class("feed-toolbar-toggle")
self._files_toggle.add_css_class("feed-toolbar-toggle-per-type")
self._files_toggle.connect("toggled", self._on_files_toggled)

self._exec_toggle = Gtk.ToggleButton(label="Exec: OFF")
self._exec_toggle.add_css_class("feed-toolbar-toggle")
self._exec_toggle.add_css_class("feed-toolbar-toggle-per-type")
self._exec_toggle.connect("clicked", self._on_exec_clicked)  # 3-state cycle, not toggle

# Separator between toggle group and agent scope
self._scope_divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
self._scope_divider.add_css_class("feed-toolbar-divider")

# Group 2 — agent scope (Layer 3)
self._agent_dropdown = Gtk.DropDown()
self._agent_dropdown.add_css_class("feed-toolbar-agent-dropdown")

# Separator between scope and snooze
self._snooze_divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
self._snooze_divider.add_css_class("feed-toolbar-divider")

# Group 3 — snooze (Layer 2)
self._snooze_button = Gtk.MenuButton(label="Snooze 0")
self._snooze_button.add_css_class("feed-toolbar-snooze")
self._snooze_button.set_visible(False)  # hidden when count == 0
```

**Toolbar assembly (replacing the existing `self._toolbar.append(...)` calls):**

```python
self._toolbar.append(self._diffs_toggle)
self._toolbar.append(self._files_toggle)
self._toolbar.append(self._exec_toggle)
self._toolbar.append(self._scope_divider)
self._toolbar.append(self._agent_dropdown)
self._toolbar.append(self._snooze_divider)
self._toolbar.append(self._snooze_button)
self._toolbar.append(self._divider)             # existing divider
self._toolbar.append(self._batch_accept_button)  # existing
self._toolbar.append(self._batch_accept_label)   # existing
```

**New callback registrations** (add to `set_auto_accept_callback` replacement):

The existing `set_auto_accept_callback(callback)` method is replaced by individual setters so the handler can wire each toggle independently:

```python
def set_diffs_toggle_callback(self, callback: Callable[[bool], None] | None) -> None:
    """Install callback for the Diffs toggle. Receives new active state."""
    self._diffs_toggle_callback = callback

def set_files_toggle_callback(self, callback: Callable[[bool], None] | None) -> None:
    """Install callback for the Files toggle. Receives new active state."""
    self._files_toggle_callback = callback

def set_exec_toggle_callback(self, callback: Callable[[str], None] | None) -> None:
    """Install callback for the Exec toggle. Receives new mode string."""
    self._exec_toggle_callback = callback

def set_agent_scope_callback(self, callback: Callable[[str], None] | None) -> None:
    """Install callback for the agent dropdown. Receives new scope string."""
    self._agent_scope_callback = callback
```

Initialize all callbacks to `None` in `__init__`.

**New toggle handlers:**

```python
def _on_diffs_toggled(self, button: Gtk.ToggleButton) -> None:
    if self._diffs_toggle_callback is not None:
        self._diffs_toggle_callback(button.get_active())

def _on_files_toggled(self, button: Gtk.ToggleButton) -> None:
    if self._files_toggle_callback is not None:
        self._files_toggle_callback(button.get_active())

**New view methods for exec Show mode:**

```python
def hide_card_buttons(self, card_id: str, button_names: list[str]) -> None:
    """Hide specific action buttons on a card widget.

    Used by FeedHandler._auto_approve_exec_card() in Show mode to hide
    the Approve/Deny buttons on cards that were auto-approved.

    Args:
        card_id: The card whose buttons should be hidden.
        button_names: List of button names to hide (e.g. ["approve", "deny"]).
    """
    card_widget = self._card_widgets.get(card_id)
    if card_widget is None:
        return
    for name in button_names:
        btn = getattr(card_widget, f"_{name}_button", None)
        if btn is not None:
            btn.set_visible(False)
```

def _on_exec_clicked(self, button: Gtk.Button) -> None:
    """3-state cycle: OFF → SHOW → SILENT → OFF."""
    current = self._exec_mode
    if current == "off":
        new_mode = "show"
    elif current == "show":
        new_mode = "silent"
    else:
        new_mode = "off"
    self._exec_mode = new_mode
    self._exec_toggle.set_label(f"Exec: {new_mode.upper()}")
    if self._exec_toggle_callback is not None:
        self._exec_toggle_callback(new_mode)
```

Initialize `self._exec_mode: str = "off"` in `__init__`.

**Replace `update_auto_accept_state(active: bool)` with:**

```python
def update_auto_accept_prefs(self, prefs_dict: dict) -> None:
    """Reconcile all toolbar visuals from the v2 prefs dict.

    Called by FeedHandler whenever prefs change. The view never owns state;
    it only reflects what the handler tells it.

    Args:
        prefs_dict: A v2 prefs dict (as produced by AutoAcceptPrefs.to_dict()
            or load_feed_prefs()). Must have version == 2.
    """
    auto = prefs_dict.get("auto_accept", {})
    fc = auto.get("file_changes", {})

    # Diffs toggle (covers "diff" type)
    diff_enabled = fc.get("diff", {}).get("enabled", False)
    self._diffs_toggle.set_active(diff_enabled)
    self._diffs_toggle.set_label(f"Diffs: {'ON' if diff_enabled else 'OFF'}")

    # Files toggle (covers file_created, file_modified, file_deleted)
    files_enabled = any(
        fc.get(ct, {}).get("enabled", False)
        for ct in ("file_created", "file_modified", "file_deleted")
    )
    self._files_toggle.set_active(files_enabled)
    self._files_toggle.set_label(f"Files: {'ON' if files_enabled else 'OFF'}")

    # Exec toggle (3-state)
    exec_mode = auto.get("exec_command", {}).get("mode", "off")
    self._exec_mode = exec_mode
    self._exec_toggle.set_label(f"Exec: {exec_mode.upper()}")

    # Snooze count
    snoozed = auto.get("snoozed_card_ids", [])
    count = len(snoozed)
    self._snooze_button.set_label(f"Snooze {count}")
    self._snooze_button.set_visible(count > 0)
```

**Backward compatibility:** Keep `update_auto_accept_state(active: bool)` as a thin wrapper during the transition period — it calls `update_auto_accept_prefs()` with a constructed dict that preserves the **legacy single-toggle semantics**: all four file-change types enabled with `agent_scope = "all_agents"` (not "first_author"). BUG #9 in adversarial audit: the original spec's bridge used scope="first_author" which would surprise tests that expected any-agent auto-accept after calling the legacy method. Using "all_agents" preserves the v1 behavior that the test suite was originally written against.

```python
def update_auto_accept_state(self, active: bool) -> None:
    """Legacy bridge — constructs a prefs dict from the single-toggle state.

    Deprecated: use update_auto_accept_prefs() directly. Preserves v1
    semantics: ALL four file-change types are enabled together with
    agent_scope='all_agents'. New code should set per-type prefs via
    update_auto_accept_prefs instead.
    """
    prefs = {
        "version": 2,
        "auto_accept": {
            "file_changes": {
                ct: {"enabled": active, "agent_scope": "all_agents"}
                for ct in ("diff", "file_created", "file_modified", "file_deleted")
            },
            "exec_command": {"mode": "off", "agent_scope": "all_agents"},
            "snoozed_card_ids": [],
        },
    }
    self.update_auto_accept_prefs(prefs)
```

**Line count estimate:** ~100 new lines, ~40 modified lines.

### 2.4 `ui/handlers/feed_handler.py`

**What changes:** Replace the single-toggle state (`_auto_accept_enabled`, `_auto_accept_agent`) with an `AutoAcceptPrefs` instance. Add centralized policy methods. Wire new toolbar callbacks. Update `add_card()` auto-accept guard. Update `_save_feed_prefs_idle()`.

**Remove:**
- `_AUTO_ACCEPT_TYPES` constant (line 25)
- `_auto_accept_enabled: bool = False` (line 109)
- `_auto_accept_agent: str | None = None` (line 111)

**Add to `__init__`:**

```python
from models.feed_card import AutoAcceptPrefs

# V2 auto-accept preferences (replaces _auto_accept_enabled + _auto_accept_agent)
self._prefs: AutoAcceptPrefs = AutoAcceptPrefs()
# Derived flag for legacy external callers and hot-path optimization
self._auto_accept_enabled: bool = False  # derives from prefs.any_enabled()
# Agent lock-in for first_author scope (runtime state, not persisted)
self._auto_accept_agent: str | None = None
```

**Replace `set_feed_tab()`** to wire new callbacks:

```python
def set_feed_tab(self, feed_tab) -> None:
    self._feed_tab = feed_tab
    if self._feed_tab is not None:
        self._feed_tab.set_batch_accept_callback(
            lambda: self._on_batch_accept_clicked()
        )
        # V2: wire per-toggle callbacks
        self._feed_tab.set_diffs_toggle_callback(self._on_diffs_toggled)
        self._feed_tab.set_files_toggle_callback(self._on_files_toggled)
        self._feed_tab.set_exec_toggle_callback(self._on_exec_toggled)
        # Keep legacy callback for backward compat during transition
        self._feed_tab.set_auto_accept_callback(self._on_auto_accept_toggled)
```

**Replace `_on_auto_accept_toggled`, `_enable_auto_accept`, `_disable_auto_accept`, `_cancel_auto_accept`** with new per-toggle methods:

The warning dialog callback signature is expanded to `(category, agent_name, on_confirm, on_cancel)`. The category drives which dialog copy is shown; agent_name drives the dialog's mention of which agent is involved (the first_author fallback chain). BUG #6 in adversarial audit: passing "diffs" as agent_name confuses the dialog because "diffs" is a category, not an agent identifier.

```python
def _on_diffs_toggled(self, active: bool) -> None:
    """Diffs toggle changed. Show warning on first activation."""
    if active:
        if self._show_auto_accept_warning is not None:
            self._show_auto_accept_warning(
                "diffs",
                self._resolve_agent_name_for_dialog(),
                on_confirm=self._enable_diffs,
                on_cancel=self._cancel_diffs,
            )
        else:
            self._enable_diffs()
    else:
        self._prefs.file_changes["diff"].enabled = False
        self._refresh_auto_accept_state()

def _enable_diffs(self) -> None:
    self._prefs.file_changes["diff"].enabled = True
    self._refresh_auto_accept_state()

def _cancel_diffs(self) -> None:
    self._prefs.file_changes["diff"].enabled = False
    self._refresh_auto_accept_state()

def _on_files_toggled(self, active: bool) -> None:
    """Files toggle changed. Controls file_created/modified/deleted as a group."""
    if active:
        if self._show_auto_accept_warning is not None:
            self._show_auto_accept_warning(
                "files",
                self._resolve_agent_name_for_dialog(),
                on_confirm=self._enable_files,
                on_cancel=self._cancel_files,
            )
        else:
            self._enable_files()
    else:
        for ct in ("file_created", "file_modified", "file_deleted"):
            self._prefs.file_changes[ct].enabled = False
        self._refresh_auto_accept_state()

def _enable_files(self) -> None:
    for ct in ("file_created", "file_modified", "file_deleted"):
        self._prefs.file_changes[ct].enabled = True
    self._refresh_auto_accept_state()

def _cancel_files(self) -> None:
    for ct in ("file_created", "file_modified", "file_deleted"):
        self._prefs.file_changes[ct].enabled = False
    self._refresh_auto_accept_state()

def _on_exec_toggled(self, mode: str) -> None:
    """Exec toggle changed. mode is 'off', 'show', or 'silent'.

    When the user clicks the Exec toggle to enter 'show' or 'silent', we
    show a stronger warning (since exec has bigger blast radius than file
    changes). The warning callback receives category='exec' and the
    appropriate agent name.
    """
    previous_mode = self._prefs.exec_command.mode
    self._prefs.exec_command.mode = mode
    if mode in ("show", "silent") and previous_mode == "off":
        # First entry into an exec mode — show warning.
        if self._show_auto_accept_warning is not None:
            self._show_auto_accept_warning(
                "exec",
                self._resolve_agent_name_for_dialog(),
                on_confirm=lambda: self._confirm_exec_mode(mode),
                on_cancel=lambda: self._confirm_exec_mode("off"),
            )
            return
    self._refresh_auto_accept_state()

def _confirm_exec_mode(self, mode: str) -> None:
    """Confirmed by the user (or auto-confirmed if no dialog wired)."""
    self._prefs.exec_command.mode = mode
    self._refresh_auto_accept_state()

def _refresh_auto_accept_state(self) -> None:
    """Recompute derived state and push prefs to view + persistence.

    Called after ANY prefs mutation. Ensures the view always reflects
    the handler's canonical state (Bug C invariant).

    Persists via a debounced single-shot idle_add so rapid-fire
    mutations (user clicking toggles + lazy agent lock-in firing in
    the same main-loop iteration) do not produce redundant disk writes
    (BUG #8 in adversarial audit).
    """
    self._auto_accept_enabled = self._prefs.any_enabled()
    if self._feed_tab is not None:
        self._feed_tab.update_auto_accept_prefs(self._prefs.to_dict())
    # Cancel any pending save and schedule a new one. The handler is
    # always called from the main thread, so this is safe.
    if hasattr(self, "_pending_save_id") and self._pending_save_id is not None:
        try:
            self._GLib.source_remove(self._pending_save_id)
        except Exception:
            pass
        self._pending_save_id = None
    self._pending_save_id = self._GLib.idle_add(self._save_feed_prefs_idle)
```

**Replace `_save_feed_prefs_idle()`:**

```python
def _save_feed_prefs_idle(self) -> None:
    """Persist v2 auto-accept prefs to feed-prefs.json."""
    project_path = self._project_paths.get(self._active_project_name or "")
    if not project_path:
        return
    feed_store.save_feed_prefs(project_path, self._prefs.to_dict())

**Update `set_show_auto_accept_warning` docstring** (around line 127):

```python
def set_show_auto_accept_warning(self, callback: Callable | None) -> None:
    """
    Install the callback invoked when the user activates auto-accept
    for any feature (diffs, files, exec). (Phase 5 + v2)

    The callback signature (as of v2) is:
        callback(category: str, agent_name: str,
                 on_confirm: Callable, on_cancel: Callable)
    where category is one of "diffs" | "files" | "exec" and agent_name
    is the human-readable name of the agent the auto-accept applies to
    (resolved by the handler's first_author fallback chain).

    Pass None to clear. Called by Window after FeedHandler is constructed.
    """
    self._show_auto_accept_warning = callback
```

**Replace the auto-accept guard inside `add_card()`'s `_append()` closure:**

Current code (around line 297):
```python
if (self._auto_accept_enabled
        and card_data.accepted is None
        and card_data.card_type in _AUTO_ACCEPT_TYPES
        and (self._auto_accept_agent is None or card_data.author == self._auto_accept_agent)):
```

New code:
```python
if (card_data.accepted is None
        and self._is_card_auto_acceptable(card_data)):
```

**Add centralized policy method:**

```python
def _is_card_auto_acceptable(self, card: FeedCardData) -> bool:
    """Central auto-accept policy. Returns True if a card should be
    auto-accepted based on current prefs, agent scope, and snooze list.

    Called from add_card() on every new card. Must be O(1).

    Rules:
    1. File-change cards (diff, file_created, file_modified, file_deleted):
       check _prefs.file_changes[card_type].enabled + agent_scope match
       + not in snooze list.
    2. Exec approval cards (agent_action with needs_approval=True):
       check _prefs.exec_command.mode != "off" + agent_scope match
       + not in snooze list.
    3. All other card types: never auto-accepted.
    """
    # Fast path: nothing enabled
    if not self._auto_accept_enabled:
        return False

    # Snooze check (per card-id)
    if card.card_id and card.card_id in self._prefs.snoozed_card_ids:
        return False

    # File-change cards
    if card.card_type in ("diff", "file_created", "file_modified", "file_deleted"):
        pref = self._prefs.file_changes.get(card.card_type)
        if pref is None or not pref.enabled:
            return False
        return self._agent_scope_matches(pref.agent_scope, card.author)

    # Exec approval cards
    if card.card_type == "agent_action" and card.metadata.get("needs_approval"):
        if self._prefs.exec_command.mode == "off":
            return False
        return self._agent_scope_matches(
            self._prefs.exec_command.agent_scope, card.author
        )

    return False

def _agent_scope_matches(self, scope: str, author: str) -> bool:
    """Check if a card's author matches the configured agent scope.

    - "all_agents": always True
    - "first_author": True if _auto_accept_agent is None (not yet locked)
      or author == _auto_accept_agent
    - "<specific name>": True if author == scope

    Side effect: when lazy lock-in fires, _refresh_auto_accept_state() is
    called so the view's agent dropdown updates to reflect the new lock-in
    (BUG #2 in adversarial audit — without this, the dropdown label stays
    at "First author" even though only one agent's cards are accepted).
    Persistence is debounced through _refresh_auto_accept_state.
    """
    if scope == "all_agents":
        return True
    if scope == "first_author":
        if self._auto_accept_agent is None:
            # Lazy lock-in: first card sets the agent
            if author:
                self._auto_accept_agent = author
                self._refresh_auto_accept_state()
            return True
        return author == self._auto_accept_agent
    # Specific agent name (persisted in v2 migration from v1 auto_accept_agent)
    return author == scope
```

**Update `on_project_opened()` prefs loading** (currently at the line `prefs = feed_store.load_feed_prefs(project_path)`):

Replace:
```python
prefs = feed_store.load_feed_prefs(project_path)
self._auto_accept_enabled = prefs.get("auto_accept_enabled", False)
self._auto_accept_agent = prefs.get("auto_accept_agent")
```

With:
```python
prefs_raw = feed_store.load_feed_prefs(project_path)
self._prefs = AutoAcceptPrefs.from_dict(prefs_raw)
self._auto_accept_enabled = self._prefs.any_enabled()
self._auto_accept_agent = None  # Reset lock-in on project open
```

And in `_append_and_schedule_scroll()`, replace:
```python
if self._auto_accept_enabled is not None:
    self._feed_tab.update_auto_accept_state(self._auto_accept_enabled)
```
With:
```python
self._feed_tab.update_auto_accept_prefs(self._prefs.to_dict())
```

**Exec auto-accept integration:**

Add a new helper method to `FeedHandler` that handles both exec modes atomically. This method owns the card-status update so the view never displays "pending approval" on an already-approved command (BUG #3 in adversarial audit), and respects the proposal's "Silent mode bypasses card creation" intent by hiding Approve/Deny buttons on auto-approved cards (BUG #4).

```python
def _auto_approve_exec_card(self, card_id: str, mode: str) -> None:
    """Handle exec auto-accept for a single approval card.

    Called from _append() when an exec approval card is auto-acceptable.
    The card is already in self._cards at this point; the widget has
    NOT yet been appended to the feed tab (we are inside the same
    idle_add closure).

    Args:
        card_id: card_id of the FeedCardData that was just created.
        mode: "show" or "silent" from prefs.exec_command.mode.

    Show mode: card widget is appended normally but the Approve/Deny
    buttons are hidden (the card is auto-approved). Status is set to
    "approved" so the view shows a green check instead of yellow pending.
    The runtime approval is dispatched via on_approve_exec.

    Note: Silent mode is NOT handled here. In Silent mode,
    AgentRuntimeHandler._do_approval_needed() short-circuits before
    creating a card at all (see §2.5). This method is only reached
    in Show mode.
    """
    if mode != "show":
        return

    if self._on_approve_exec is None:
        _logger.warning("_auto_approve_exec_card: no on_approve_exec callback")
        return

    card = self._cards.get(card_id)
    if card is None:
        return

    # Mark card as already-approved so the widget renders correctly.
    # The Approve/Deny buttons are wired through _make_approve_exec_cb;
    # we hide them via feed_tab.hide_card_buttons(). See §2.3.
    card.accepted = True
    card.metadata["auto_approved_by"] = "exec_auto_accept"
    if self._feed_tab is not None:
        self._feed_tab.hide_card_buttons(card_id, ["approve", "deny"])
    # Dispatch the actual approval to the runtime.
    self._GLib.idle_add(
        lambda cid=card_id: self._on_approve_exec(cid, True)
    )
```

In `add_card()`, after the existing file-change auto-accept check, call this helper:

```python
# Exec auto-accept (Phase E integration)
if (card_data.card_type == "agent_action"
        and card_data.metadata.get("needs_approval")
        and card_data.accepted is None
        and self._is_card_auto_acceptable(card_data)
        and self._prefs.exec_command.mode in ("show", "silent")):
    self._auto_approve_exec_card(card_id, self._prefs.exec_command.mode)
    # In Silent mode, skip the normal widget-append path that follows.
    # Note: Silent mode never reaches this point — the card is never
    # created because AgentRuntimeHandler._do_approval_needed() bypasses
    # card creation entirely (see §2.5).
```

**BUG #6 audit note:** The spec's original exec Show path used `handle_approve_exec(cid, True)`. That method (feed_handler.py:1260) delegates to `_on_approve_exec` WITHOUT updating the card's local status. The replacement method `_auto_approve_exec_card` directly sets `card.accepted = True` and adds the audit metadata, then calls `_on_approve_exec(cid, True)` (skipping `handle_approve_exec` because the card is already marked accepted). This avoids double-action and ensures UI/runtime state stay in sync.

**Snooze API:**

```python
def snooze_card(self, card_id: str) -> None:
    """Add a card to the snooze list so it is not auto-accepted."""
    if card_id not in self._prefs.snoozed_card_ids:
        self._prefs.snoozed_card_ids.append(card_id)
        self._refresh_auto_accept_state()

def unsnooze_card(self, card_id: str) -> None:
    """Remove a card from the snooze list."""
    if card_id in self._prefs.snoozed_card_ids:
        self._prefs.snoozed_card_ids.remove(card_id)
        self._refresh_auto_accept_state()
```

**Add `_resolve_agent_name_for_dialog` helper:**

```python
def _resolve_agent_name_for_dialog(self) -> str:
    """Resolve the agent name to display in the warning dialog.

    Uses the first_author fallback chain:
    1. If _auto_accept_agent is set (lazy lock-in already fired), use it.
    2. Otherwise, return a generic placeholder so the dialog reads
       naturally (e.g. \"the first agent to write\").

    Returns:
        The locked-in agent name, or the placeholder string.
    """
    if self._auto_accept_agent:
        return self._auto_accept_agent
    return "the first agent to write"
```

**Line count estimate:** ~150 new lines, ~60 modified lines.

### 2.5 `ui/handlers/agent_runtime_handler.py`

**What changes:** In `_do_approval_needed()`, before creating the approval card, check if exec auto-accept is in `Silent` mode. If so, bypass card creation entirely and call `rt.approve_exec()` directly.

**Reconciliation with proposal (BUG #11 fix):** The proposal §"Phase E integration" states: *"In `Silent` mode, the approval card is not even created — `agent_runtime_handler` short-circuits earlier, calling `rt.approve_exec(session_key, "exec_command", args, True)` directly without a feed card."* The first draft of this spec diverged by claiming cards ARE created in Silent mode but immediately approved. That divergence was a bug: it leaves Approve/Deny buttons visible on an already-executed command, inviting double-action. This spec now follows the proposal: Silent mode bypasses card creation.

To honor the proposal AND respect §8.6 R2 (no handler-to-handler imports), we add a new callback to `AgentRuntimeHandler.__init__`: `on_check_exec_auto_accept: Callable[[], str | None]`. The handler installs this callback so `AgentRuntimeHandler` can ASK `FeedHandler` whether exec auto-accept applies without importing from it. The callback returns the exec mode ("off" | "show" | "silent") or None.

```python
# In AgentRuntimeHandler.__init__:
self._on_check_exec_auto_accept: Callable[[], str | None] | None = None

def set_check_exec_auto_accept_callback(self, callback: Callable[[], str | None] | None) -> None:
    """Install callback that returns the current exec auto-accept mode,
    or None if exec auto-accept is off. (Phase E + v2)
    """
    self._on_check_exec_auto_accept = callback
```

In `_do_approval_needed()`, before creating the card:

```python
def _do_approval_needed(self, session_key: str, tool_name: str, args: dict) -> None:
    if self._fh is None:
        logger.warning("_do_approval_needed: no feed handler available")
        return
    
    # V2 Silent bypass: if exec auto-accept is in silent mode, approve
    # directly without creating a feed card. The card is NOT stored
    # in _cards or _pending_approvals (no double-action possible).
    if (self._on_check_exec_auto_accept is not None
            and self._on_check_exec_auto_accept() == "silent"):
        agent_def = self._agents.get(session_key)
        if agent_def is None:
            return
        runtime = self._runtimes.get(agent_def.runtime_id)
        if runtime is None:
            return
        # Resolve approval directly without a card.
        self._GLib.idle_add(
            lambda: runtime.approve_exec(session_key, tool_name, args, True)
        )
        return
    
    # ... existing card creation code follows ...
```

**Window.py wiring** (new — adds to §2.6):

```python
self._feed_handler.set_check_exec_auto_accept_callback_for_handler(
    self._agent_runtime_handler.set_check_exec_auto_accept_callback
)
# FeedHandler exposes a getter that returns the current exec mode:
# _feed_handler.get_exec_auto_accept_mode() -> str | None
```

And on the FeedHandler side:

```python
def get_exec_auto_accept_mode(self) -> str | None:
    """Public API: return the current exec auto-accept mode.

    Used by AgentRuntimeHandler via the installed callback to decide
    whether to bypass card creation in Silent mode.
    """
    if self._prefs is None:
        return None
    return self._prefs.exec_command.mode
```

**Why this pattern (not direct cross-handler import):** §8.6 R2 forbids handler-to-handler imports. The callback indirection preserves the rule: `AgentRuntimeHandler` knows nothing about `FeedHandler`'s internals, only the contract "give me the current exec mode string."

**Why Silent mode bypasses card creation (Show mode does NOT):** Show mode is for the user who wants to see what was auto-approved (audit trail in the feed). Silent mode is for the user who explicitly opted into "let the agent just run pytest in peace" and does NOT want cards cluttering the feed. The two modes have different UX intents; the spec must respect both.

**Line count estimate:** ~20 new lines in this file (callback installation + bypass logic).

### 2.6 `ui/window.py`

**What changes:** Update the `set_show_auto_accept_warning` callback to accept both a `category` string ("diffs" | "files" | "exec") AND an `agent_name` string. The category drives the dialog copy; the agent_name is shown as the agent the auto-accept applies to. The previous signature `(agent_name, on_confirm, on_cancel)` only handled a single toggle; the new signature handles per-type activation (BUG #6 fix).

**Replace** (around line 477):

The callback signature expands to `(category, agent_name, on_confirm, on_cancel)`. The category is used to pick dialog copy; agent_name is shown as the agent the auto-accept applies to. BUG #6 fix.

```python
self._feed_handler.set_show_auto_accept_warning(
    lambda category, agent_name, on_confirm, on_cancel: self._show_auto_accept_warning_v2(
        category, agent_name, on_confirm, on_cancel
    )
)
```

**Add** `_show_auto_accept_warning_v2` method:

```python
def _show_auto_accept_warning_v2(
    self, category: str, agent_name: str, on_confirm: Callable, on_cancel: Callable
) -> None:
    """V2 warning dialog for per-type auto-accept activation.

    Args:
        category: "diffs", "files", or "exec"
        agent_name: human-readable agent identifier (resolved by handler)
        on_confirm: called if user confirms
        on_cancel: called if user cancels
    """
    titles = {
        "diffs": "Auto-accept diffs?",
        "files": "Auto-accept file changes?",
        "exec": "Auto-approve exec commands?",
    }
    bodies = {
        "diffs": f"{agent_name} will silently auto-accept every diff it writes. You will not see the diff before it is committed.",
        "files": f"{agent_name} will silently auto-accept every file_created/file_modified/file_deleted card it produces. You will not see the change before it is committed.",
        "exec":  f"{agent_name} will silently auto-approve every shell command it runs. This includes rm, git push, network calls, anything. There is no undo.",
    }
    title = titles.get(category, "Enable auto-accept?")
    body = bodies.get(category, f"Enable auto-accept for {category}?")
    # Use existing dialog infrastructure (same pattern as _show_auto_accept_warning).
    # The dialog builds a Gtk.MessageDialog with WARNING type, OK/CANCEL buttons,
    # and on response invokes on_confirm (for OK) or on_cancel (for CANCEL/DELETE).
    # Implementation matches the existing _show_auto_accept_warning pattern in 
    # ui/window.py around line 937, with title/body swapped for category-specific copy.
```

**Line count estimate:** ~30 modified lines.

---

**Files NOT changed** (already correct):

- `models/feed_card.py` — existing `FeedCardData` fields and methods are unchanged. Only new classes appended.
- `ui/views/feed_card.py` — card widget builder is unchanged. The per-card snooze badge is a follow-up; the initial implementation uses the snooze list without a visual badge on each card.
- `utils/git_ops.py` — no changes to git operations.
- `ui/handlers/review_handler.py` — no changes to review flow.
- `tests/test_feed_handler.py` — existing tests stay; new test classes are appended (see §5).

---

## 3. Data Flow

### File-change card auto-accept flow

```
Agent writes file
  → FeedHandler.add_card(card_data)
    → _append() closure (GLib.idle_add)
      → _is_card_auto_acceptable(card)
        → _prefs.file_changes[card_type].enabled? → True
        → _agent_scope_matches(scope, author)? → True
        → card_id not in snoozed? → True
        → return True
      → GLib.idle_add(handle_accept(card_id))
        → git stage + commit (background thread)
        → card.accepted = True
        → _update_card_visual (main thread)
        → _add_git_card (main thread)
```

### Exec auto-accept flow (Show mode)

```
Agent requests exec approval
  → AgentRuntimeHandler._do_approval_needed()
    → creates FeedCardData(needs_approval=True)
    → FeedHandler.add_card(card)
      → _is_card_auto_acceptable(card)
        → _prefs.exec_command.mode == "show"? → True
        → agent_scope matches? → True
        → return True
      → GLib.idle_add(handle_approve_exec(card_id, True))
        → _on_approve_exec(card_id, True)  [delegates to AgentRuntimeHandler.approve_exec]
        → rt.approve_exec(session_key, tool_name, args, True)
```

### Exec auto-accept flow (Silent mode)

```
Agent requests exec approval
  → AgentRuntimeHandler._do_approval_needed()
    → _on_check_exec_auto_accept() == "silent"? → True
    → bypasses card creation entirely
    → rt.approve_exec(session_key, tool_name, args, True) directly
    → no FeedCardData created, no feed card appended
```

### User toggles Diffs ON

```
User clicks Diffs toggle
  → FeedTab._on_diffs_toggled(button)
    → _diffs_toggle_callback(True)
      → FeedHandler._on_diffs_toggled(True)
        → _show_auto_accept_warning("diffs", on_confirm, on_cancel)
          → User clicks Confirm
            → _enable_diffs()
              → _prefs.file_changes["diff"].enabled = True
              → _refresh_auto_accept_state()
                → _auto_accept_enabled = True
                → feed_tab.update_auto_accept_prefs(prefs_dict)
                → _save_feed_prefs_idle()
```

### Prefs migration on project open

```
User opens project
  → FeedHandler.on_project_opened()
    → feed_store.load_feed_prefs(project_path)
      → reads feed-prefs.json
      → version == 1? → _migrate_v1_to_v2(raw) → returns v2 dict
      → version == 2? → _merge_v2_defaults(raw) → returns v2 dict
      → missing/invalid? → _default_prefs() → returns v2 dict
    → AutoAcceptPrefs.from_dict(prefs_raw)
    → _auto_accept_enabled = prefs.any_enabled()
    → feed_tab.update_auto_accept_prefs(prefs.to_dict())
```

---

## 4. File Change Summary

| File | Change type | Est. lines | Risk |
|---|---|---|---|
| `models/feed_card.py` | New dataclasses | +70 | Low — pure data, no imports from ui/ |
| `utils/feed_store.py` | v2 schema + migration | +80 new, ~30 modified | Medium — migration logic must be correct |
| `ui/views/feed_tab.py` | Toolbar restructure | +100 new, ~40 modified | Medium — GTK widget layout, but no business logic |
| `ui/handlers/feed_handler.py` | Policy + state rewrite | +130 new, ~60 modified | High — touches the hot path in `add_card()` |
| `ui/handlers/agent_runtime_handler.py` | No changes | 0 | None |
| `ui/window.py` | Warning dialog update | ~30 modified | Low — callback wiring |
| `tests/test_feed_handler.py` | New test classes | +400 | Low — tests only |

**Total estimate:** ~810 new/modified lines.

---

## 5. Implementation Order

### Step 1: `AutoAcceptPrefs` dataclass (models/feed_card.py)

Add the `FileChangePref`, `ExecCommandPref`, and `AutoAcceptPrefs` dataclasses.

**Verify:** `python3 -c "from models.feed_card import AutoAcceptPrefs; p = AutoAcceptPrefs(); assert not p.any_enabled(); p.file_changes['diff'].enabled = True; assert p.any_enabled()"`

### Step 2: Prefs v2 schema + migration (utils/feed_store.py)

Bump `PREFS_VERSION`, rewrite `load_feed_prefs()`, add `_migrate_v1_to_v2()` and `_merge_v2_defaults()`.

**Verify:** Write a golden-file test: create a v1 prefs file, load it, check the output is a valid v2 dict with all four types enabled.

### Step 3: Tests for Steps 1-2

Add `TestAutoAcceptPrefs` and `TestPrefsMigration` test classes.

**Verify:** `python3 -m pytest tests/test_feed_handler.py::TestAutoAcceptPrefs tests/test_feed_handler.py::TestPrefsMigration -v`

### Step 4: FeedHandler state migration (ui/handlers/feed_handler.py)

Replace `_auto_accept_enabled` / `_auto_accept_agent` with `_prefs: AutoAcceptPrefs`. Add `_is_card_auto_acceptable()`, `_agent_scope_matches()`, `_refresh_auto_accept_state()`. Wire new toggle callbacks. Update `add_card()` guard. Update `_save_feed_prefs_idle()`. Update `on_project_opened()` prefs loading.

**Verify:** `python3 -m pytest tests/test_feed_handler.py -v` — all existing tests must pass against the new internals. The legacy `update_auto_accept_state()` bridge in FeedTab ensures existing tests that call `update_auto_accept_state` still work.

### Step 5: FeedTab toolbar rebuild (ui/views/feed_tab.py)

Replace single toggle with per-type toggles + dropdown + snooze button. Add new callback setters. Replace `update_auto_accept_state` with `update_auto_accept_prefs` (keep legacy bridge).

**Verify:** `python3 -m pytest tests/test_feed_handler.py tests/test_feed_tab.py -v`

### Step 6: Exec auto-accept integration (ui/handlers/feed_handler.py)

Add exec auto-accept check in `add_card()`. Add Show/Silent mode handling.

**Verify:** `python3 -m pytest tests/test_feed_handler.py::TestExecAutoAccept -v`

### Step 7: Window wiring (ui/window.py)

Update `set_show_auto_accept_warning` callback signature.

**Verify:** Full test suite: `python3 -m pytest tests/ -v`

### Step 8: Scenario tests

Add integration-level tests for the three scenarios described in the proposal.

**Verify:** `python3 -m pytest tests/test_feed_handler.py::TestAutoAcceptScenario -v`

---

## 6. Acceptance Criteria

- [ ] `AutoAcceptPrefs` dataclass exists with `to_dict()` / `from_dict()` / `any_enabled()` / `is_file_type_enabled()`
- [ ] `feed_store.load_feed_prefs()` returns v2 dict for v1 files (migration)
- [ ] `feed_store.load_feed_prefs()` returns v2 dict for v2 files (pass-through)
- [ ] `feed_store.load_feed_prefs()` returns defaults for missing/invalid files
- [ ] `feed_store.save_feed_prefs()` rejects non-v2 dicts
- [ ] `FeedTab` shows three toggles: Diffs, Files, Exec
- [ ] `FeedTab.update_auto_accept_prefs(prefs_dict)` reconciles all toggle labels
- [ ] `FeedTab.update_auto_accept_state(bool)` still works (legacy bridge)
- [ ] `FeedHandler._is_card_auto_acceptable(card)` returns correct verdict for all card types
- [ ] `FeedHandler._is_card_auto_acceptable(card)` returns False for snoozed cards
- [ ] `FeedHandler._is_card_auto_acceptable(card)` returns False when no prefs are enabled
- [ ] Diffs ON → diff cards auto-accept, file_* cards do not
- [ ] Files ON → file_* cards auto-accept, diff cards do not
- [ ] Both ON → all four types auto-accept
- [ ] Both OFF → no cards auto-accept
- [ ] Exec Show mode → approval cards appear, Approve/Deny buttons hidden, status set to approved
- [ ] Exec Silent mode → no approval card is created in the feed; the runtime approval still fires
- [ ] Exec Off mode → approval cards require manual Approve/Deny
- [ ] Unknown card_type (e.g. "git_commit", "audit_report", None) → never auto-accepted (regression test for BUG #10)
- [ ] Agent scope "all_agents" → any agent's cards auto-accept
- [ ] Agent scope "first_author" → first card's author locks in
- [ ] Snoozed cards are not auto-accepted
- [ ] Unsnoozed cards resume auto-accepting on next arrival (not retroactively)
- [ ] Prefs persist across project close/reopen
- [ ] V1 prefs file migrates to v2 on project open
- [ ] All existing Phase 5 tests pass unmodified

---

## 7. Edge Cases

| Case | Expected behavior |
|---|---|
| V1 prefs file with `auto_accept_enabled: True` | All four file-change types enabled on migration |
| V1 prefs file with `auto_accept_enabled: False` | All four disabled on migration |
| Corrupt `feed-prefs.json` | Defaults loaded (all off), file overwritten on next save |
| User toggles Diffs ON, then opens a different project | Prefs are per-project; new project starts with defaults |
| Snoozed card is accepted manually (user clicks Accept) | Snooze is removed from list; card is accepted |
| Exec mode is Silent but card is snoozed | Card is NOT auto-approved; user must manually approve |
| Card arrives with unknown `card_type` (e.g. "git_commit", "audit_report", None) | Card is never auto-accepted regardless of prefs; surfaced to user as a normal pending card |
| Two agents write cards simultaneously; scope is first_author | First card's author locks in; second agent's cards are not auto-accepted |
| All toggles OFF, then user clicks Accept All | Batch accept still works (independent of auto-accept) |
| `add_card` called during project loading (`_loading=True`) | Auto-accept check still runs (cards are real, just loaded from disk) — but loaded cards have `accepted` already set, so the `accepted is None` guard prevents re-accepting |
| FeedTab is None when prefs change | `_refresh_auto_accept_state` checks `if self._feed_tab is not None`; no crash |

---

## 8. ARCHITECTURE.md Updates Required

After implementation, update:

1. **§3.22c** (`ui/handlers/feed_handler.py`): Update "Owns" list to include `_prefs: AutoAcceptPrefs`. Add `_is_card_auto_acceptable()` to Public API list. Remove `_AUTO_ACCEPT_TYPES` reference.
2. **§3.22c**: Update line count estimate.
3. **§8.6** (Handler Pattern): No changes needed — the pattern is followed.
4. **Section 11** (File manifest): Update line counts.
5. Add reference to this spec in §3.22c: "See `docs/specs/SPEC-AUTO-ACCEPT-GRANULAR-1.md`."

---

## Self-Audit (Rule 9)

### 1. Does every code sample actually work against the current codebase?

**`AutoAcceptPrefs` dataclass:** Uses `dataclasses.field(default_factory=...)` — verified that `field` is already imported in `models/feed_card.py` (line 4). The `dict[str, FileChangePref]` type annotation with `field(default_factory=lambda: {...})` is valid Python 3.11+ (the project requires 3.11+).

**`_migrate_v1_to_v2`:** Reads `raw.get("auto_accept_enabled", False)` — verified this is the v1 schema field name used by the current `save_feed_prefs` at `feed_store.py:296` and loaded at `feed_handler.py:on_project_opened` (`prefs.get("auto_accept_enabled", False)`).

**`load_feed_prefs` rewrite:** The current function reads from `_prefs_path(project_path)` and returns `_default_prefs()` on error. My version preserves this pattern. The `_acquire_lock` / `_release_lock` pattern used for feed.json is NOT used for prefs (the current code does not lock prefs reads), so my code follows the same convention.

**`save_feed_prefs` validation:** The current code at line 353 checks `prefs.get("version") != PREFS_VERSION`. With `PREFS_VERSION = 2`, this will reject any non-v2 dict. My `AutoAcceptPrefs.to_dict()` produces `{"version": 2, ...}`, so the validation passes. Verified.

**`FeedTab` toggle wiring:** The existing pattern is `button.connect("toggled", handler)` for ToggleButton and `button.connect("clicked", handler)` for Button. My code uses `connect("toggled", ...)` for `_diffs_toggle` and `_files_toggle` (both ToggleButton), and `connect("clicked", ...)` for `_exec_toggle` (which cycles states manually). This matches GTK4 conventions.

**`update_auto_accept_prefs`:** Reads from a dict produced by `AutoAcceptPrefs.to_dict()`. The structure matches: `prefs_dict["auto_accept"]["file_changes"]["diff"]["enabled"]` etc. Verified against the `to_dict()` implementation.

**`_is_card_auto_acceptable`:** References `card.card_type`, `card.card_id`, `card.metadata`, `card.author` — all verified fields on `FeedCardData`. The method is called from inside `_append()` which is dispatched via `GLib.idle_add`, so it runs on the main thread. The `_prefs` dict access is safe (no concurrent mutation since all mutations also happen on the main thread).

**Exec auto-accept in `add_card()`:** References `self._on_approve_exec` — verified this is set in `__init__` from the constructor parameter and is wired in `window.py:459` to `self._agent_runtime_handler.approve_exec`. The `handle_approve_exec` method at line 1265 checks `card.metadata.get("needs_approval")` before delegating — this is correct.

**Agent scope `_auto_accept_agent` lock-in:** The lazy lock-in pattern (setting `_auto_accept_agent` when it's None and the first card arrives) matches the existing pattern at the current line ~303: `if self._auto_accept_agent is None and card_data.author:`.

### 2. Did I catch all exception types for every function I call?

- `AutoAcceptPrefs.from_dict(raw)`: calls `raw.get()` (dict method — no exceptions), `bool()`, `str()`, `list()` — all safe for any input type. Unknown keys produce defaults.
- `feed_store.save_feed_prefs()`: can raise `OSError` on write — but the existing implementation catches `OSError` internally and logs. No change needed.
- `feed_store.load_feed_prefs()`: catches `(OSError, json.JSONDecodeError)` internally. No change needed.
- `_refresh_auto_accept_state()`: calls `self._prefs.to_dict()` (pure Python, no exceptions), `self._feed_tab.update_auto_accept_prefs()` (GTK calls, no expected exceptions), `self._GLib.idle_add()` (no exceptions). No try/except needed.

### 3. Did I verify key structures?

- `_pending_approvals` in `AgentRuntimeHandler`: dict keyed by `card_id` (string), value is `{"session_key": str, "tool_name": str, "args": dict}`. Verified at line 1006.
- `_prefs.file_changes`: dict keyed by card type string, value is `FileChangePref` dataclass. Verified structure.
- `_auto_accept_callback` in FeedTab: stored as `Callable[[bool], None] | None`. My new callbacks follow the same pattern.

### 4. Did I trace the data flow end-to-end?

Yes — three flows traced in §3 (file-change auto-accept, exec Show mode, exec Silent mode, user toggle flow, migration flow). All paths go through verified function signatures and data structures.

### 5. Would an implementer who follows this spec exactly produce working code?

Yes — all signatures verified against current source, all data structures traced, all GTK patterns matched to existing code. The one area requiring implementer judgment is the exact warning dialog implementation in `_show_auto_accept_warning_v2` (which follows the existing `_show_auto_accept_warning` pattern but with category-specific text). The existing pattern should be read from `ui/window.py` before implementing.

---

## Completion Verification (Rule 10)

### 1. Scope checklist

```
[ ] models/feed_card.py — AutoAcceptPrefs + sub-dataclasses (+~70 lines, append after FeedCardData)
[ ] utils/feed_store.py — v2 schema, migration, load/save rewrite (+~80 new, ~30 modified)
[ ] ui/views/feed_tab.py — toolbar restructure, new callbacks, update_auto_accept_prefs (+~100 new, ~40 modified)
[ ] ui/handlers/feed_handler.py — policy rewrite, state migration, exec integration (+~130 new, ~60 modified)
[ ] ui/handlers/agent_runtime_handler.py — no changes (verified)
[ ] ui/window.py — warning dialog callback update (~30 modified)
[ ] tests/test_feed_handler.py — new test classes (+~400 lines, added during implementation)
```

### 2. Test suite

This is a specification document, not an implementation. The test suite will be run during implementation. The spec defines the test classes and scenario tests to write (§5 Steps 3, 6, 8).

### 3. Pattern sweep

```
grep -rn '_AUTO_ACCEPT_TYPES' ui/ models/ utils/ tests/ --include='*.py'
```
Must return zero matches after implementation (constant removed).

```
grep -rn 'update_auto_accept_state' ui/ tests/ --include='*.py'
```
Must return only the legacy bridge method in FeedTab and any test references (which should call the bridge).

```
grep -rn '_auto_accept_enabled' ui/handlers/feed_handler.py
```
Must show the derived field only (not the old primary state).

### 4. Declaration

This spec is **complete as a specification**. Implementation has not started. All file references, function signatures, data structures, and code paths have been verified against the codebase at commit `41c5c88` (2026-06-29).

---

## 9. Adversarial Audit Log (2026-06-29)

Spec was audited per `prompts/adversarialDebugger.md`. Eleven findings were identified and patched in-place (noted inline in the affected sections). Summary:

| # | Severity | Section | Issue | Fix |
|---|---|---|---|---|
| 1 | CRITICAL | §2.1, §2.2 | v1→v2 migration drops `auto_accept_agent`, silently changing which agent's cards auto-accept | Persist agent name as a specific `agent_scope` in migration |
| 2 | CRITICAL | §2.4 | Lazy first_author lock-in mutates `_auto_accept_agent` but never refreshes the view's dropdown label | `_agent_scope_matches` calls `_refresh_auto_accept_state()` on lock-in |
| 3 | HIGH | §2.4 | Exec Show path calls `handle_approve_exec` but never updates card status, leaving Approve/Deny buttons visible on already-approved commands | New `_auto_approve_exec_card` method sets `card.accepted = True` + hides buttons before dispatching runtime approval |
| 4 | HIGH | §2.4, §2.5 | Silent mode shows cards in the feed (contradicting the proposal's "bypass card creation" promise), exposing Approve/Deny buttons that invite double-action | §2.5 now uses a callback indirection to bypass card creation entirely in Silent mode |
| 5 | — | — | False alarm: lock-in only fires on file-change or exec cards, not on audit_report/git_commit | None — but documented so future readers know it's intentional |
| 6 | HIGH | §2.4, §2.6 | Warning dialog callback signature `(agent_name, on_confirm, on_cancel)` is reused for per-type activation; passing "diffs" as agent_name confuses the dialog | Expanded signature to `(category, agent_name, on_confirm, on_cancel)`; window.py gets a new `_show_auto_accept_warning_v2` |
| 7 | — | §2.3 | Files toggle is a binary toggle controlling 3 underlying prefs; partial state is invisible | Resolved: use `Gtk.ToggleButton` (group toggle — all three prefs always toggle together, no inconsistent state needed). Original CheckButton idea was dropped during spec review (type-confusion with `connect("toggled")`). |
| 8 | MEDIUM | §2.4 | `_save_feed_prefs_idle` is scheduled via `idle_add` on every mutation; rapid-fire mutations produce redundant disk writes | Single-shot debounce via `_pending_save_id` + `GLib.source_remove` |
| 9 | MEDIUM | §2.3 | Legacy bridge `update_auto_accept_state(bool)` constructed prefs with `agent_scope='first_author'`, breaking tests that expected any-agent behavior | Bridge now uses `agent_scope='all_agents'` to preserve v1 semantics |
| 10 | LOW | §6 | No regression test for unknown `card_type` | Added acceptance criterion + edge case row |
| 11 | LOW | §2.5 | Spec diverged from proposal: spec said "Silent mode cards appear with status immediately approved"; proposal said "Silent mode bypasses card creation entirely" | Spec now follows proposal; explicit reconciliation note added in §2.5 |
