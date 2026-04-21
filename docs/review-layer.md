# Review Layer — Specification

**Last updated:** 2026-04-19
**Status:** Not implemented — ready for build
**Depends on:** Existing CrabCakes architecture (see `docs/ARCHITECTURE.md`)
**New dependencies:** `gitpython` — Python git library (no CLI calls). Reuses existing `syntax_highlight.py`. Phase 2 adds `agentfs-sdk` for isolated mode.

---

## Overview

CrabCakes includes a built-in git-backed code review system for multi-agent project workflows. When a project tab is open, the PM can start a review session: CrabCakes snapshots the project state, agents work normally, then the PM reviews visual diffs rendered as interactive cards in the project chat tab and clicks Accept or Reject.

**Key design:** Git is the store. GitPython is the engine. CrabCakes is the visual layer. No SQLite, no gateway changes, no filesystem reimagination.

**Constraint acknowledgment:** CrabCakes cannot intercept or prevent agent file writes (agents write through the OpenClaw gateway). Instead, this system works by **snapshotting before** and **diffing after** — the same model as a pull request, but embedded in the chat UI.

---

## Review Modes

Three modes with progressive enforcement. Each mode is strictly stronger than the last.

| Mode | Enforcement | Description |
|------|-------------|-------------|
| `off` | None | Agents work freely. No review UI. Auto-commit gives undo history. Default for new projects. |
| `review` | Snapshot + diff + accept/revert | PM checkpoints state, reviews visual diffs, accepts (commits) or rejects (reverts). |
| `isolated` | AgentFS sandbox + audit trail + accept/reject | Agents never touch real filesystem. All writes to SQLite-backed virtual FS. PM reviews audit trail, accept = write to real filesystem, reject = discard. |

**Mode progression:** Each mode is strictly stronger than the last. `off` → `review` adds git-backed visual review. `review` → `isolated` adds true filesystem isolation via AgentFS.

---

## Architecture

### What Reuses Existing Code

| Existing Module | How It's Used |
|----------------|---------------|
| `ui/handlers/project_handler.py` | Owns the active project. ReviewHandler receives the project path from it. |
| `ui/views/chat_bubble.py` | Diff cards are built with the same widget factory pattern as event cards. |
| `utils/syntax_highlight.py` | Syntax-colors code inside diff hunks (per-line). |
| `utils/escaping.py` | Pango-escaping for all user content in diff cards. |
| `ui/styles.py` | New CSS classes for diff cards added to `APP_CSS`. |
| `ui/handlers/chat_handler.py` | Sends rejection messages to agent sessions via gateway. |
| `models/routing.py` | `AgentRoutingTable` — unchanged. Used to route rejection messages. |

### New Modules

| Module | Package | Responsibility |
|--------|---------|---------------|
| `models/review_state.py` | `models/` | Per-project review session state (checkpoint SHA, mode, dirty flag). Pure data, no GTK. |
| `utils/git_ops.py` | `utils/` | GitPython wrapper for all git operations. Returns structured results, never raises unhandled exceptions. Pure functions, no GTK, no network (git handles its own network). |
| `utils/diff_parser.py` | `utils/` | Parses unified diff output into structured data (files, hunks, lines). Pure function, no GTK. |
| `ui/handlers/review_handler.py` | `ui/handlers/` | Review logic — checkpoint, check changes, accept, reject. Coordinates git_ops, diff_parser, and GTK views. All GTK via `GLib.idle_add()`. |
| `ui/views/review_bar.py` | `ui/views/` | Overlay bar widget at top of project tab. Mode dropdown + status label + action buttons. Pure view. |
| `ui/views/diff_card.py` | `ui/views/` | Diff card widget factories — per-file collapsible cards with syntax-highlighted hunks. Pure view. |

### Directory Impact

```
crabcakes/
├── models/
│   ├── ... (existing)
│   └── review_state.py          # NEW — ReviewState dataclass
├── ui/
│   ├── handlers/
│   │   ├── ... (existing)
│   │   └── review_handler.py    # NEW — review session logic
│   └── views/
│       ├── ... (existing)
│       ├── review_bar.py         # NEW — mode dropdown + status bar
│       └── diff_card.py          # NEW — diff card widget factories
└── utils/
    ├── ... (existing)
    ├── git_ops.py                # NEW — GitPython wrapper
    └── diff_parser.py            # NEW — unified diff parser
```

---

## Module Specifications

### `models/review_state.py`

**Responsibility:** Per-project review session state. Pure data class — no GTK, no git calls, no network.

**Why models/:** Per ARCHITECTURE.md Section 8.4: "If a utility needs to be stateful, it probably belongs in `models/`." ReviewState holds persistent session state.

**Public API:**
```python
from dataclasses import dataclass, field

@dataclass
class ReviewState:
    """Per-project review session state. One instance per open project tab."""
    project_path: str                       # absolute path to project directory
    review_mode: str = "off"                # "off" | "review"
    checkpoint_sha: str | None = None       # git SHA at last checkpoint (None = no active session)
    is_dirty: bool = False                  # True if files changed since checkpoint
    last_check_files: list[str] = field(default_factory=list)  # files changed at last check

    def is_active(self) -> bool:
        """True if a review session is in progress (checkpoint taken, not yet resolved)."""
        return self.checkpoint_sha is not None

    def can_checkpoint(self) -> bool:
        """True if review mode is on and no active session (can start a new one)."""
        return self.review_mode == "review" and self.checkpoint_sha is None
```

**Rules:**
- No imports from `ui/`, `gateway/`, or `subprocess`.
- Immutable except via explicit property assignment.
- One instance per project, stored in `ReviewHandler._states: dict[str, ReviewState]` keyed by project name.

---

### `utils/git_ops.py`

**Responsibility:** GitPython wrapper for all git operations. Returns structured results. Never raises unhandled exceptions — all errors captured in the result object.

**Why utils/:** Pure functions that return data. No state, no GTK. GitPython handles its own network (push/pull). Note: unlike `utils/stt.py` which calls subprocess (`arecord`), this module uses the GitPython library API exclusively — no `subprocess.run()`.

**New dependency:** `gitpython` (`pip install gitpython`). Import: `import git`.

**Public API:**
```python
from dataclasses import dataclass

@dataclass
class GitResult:
    """Result of a git operation."""
    success: bool
    stdout: str          # textual output (diff, log, status)
    error: str           # error message if success=False
    sha: str | None      # commit SHA when applicable

def is_repo(project_path: str) -> bool:
    """True if project_path contains a valid git repository."""

def init_repo(project_path: str) -> GitResult:
    """Initialize a git repo if not already one."""

def get_head_sha(project_path: str) -> GitResult:
    """Get current HEAD commit SHA."""

def stage_all(project_path: str) -> GitResult:
    """Stage all changes (equivalent to git add -A)."""

def commit(project_path: str, message: str) -> GitResult:
    """Commit staged changes. Returns SHA in result.sha."""

def diff_against(project_path: str, sha: str) -> GitResult:
    """Full unified diff of working tree vs commit at sha."""

def diff_stat_against(project_path: str, sha: str) -> GitResult:
    """Stat summary of diff (--stat output)."""

def diff_file_against(project_path: str, sha: str, file_path: str) -> GitResult:
    """Diff for a single file vs commit at sha."""

def checkout_paths(project_path: str, sha: str, paths: list[str]) -> GitResult:
    """Revert file(s) to their state at sha. Equivalent to git checkout <sha> -- <paths>."""

def log(project_path: str, count: int = 10) -> GitResult:
    """Recent commit log as text."""

def push(project_path: str, remote: str = "origin", branch: str = "main") -> GitResult:
    """Push to remote."""

def status(project_path: str) -> GitResult:
    """git status --porcelain output."""
```

**Implementation pattern:**
```python
import git as gitpython

def commit(project_path: str, message: str) -> GitResult:
    try:
        repo = gitpython.Repo(project_path)
        commit_obj = repo.index.commit(message)
        return GitResult(success=True, stdout="", error="", sha=str(commit_obj.hexsha))
    except Exception as e:
        return GitResult(success=False, stdout="", error=str(e), sha=None)
```

- Every function wraps GitPython calls in try/except — always returns `GitResult`, never raises
- `gitpython.Repo(project_path)` is lightweight — no caching needed for the frequencies we use
- `diff_against()` returns unified diff text via `repo.commit(sha).tree.diff_to_tree()` or `repo.git.diff(sha)` for working-tree diffs
- `checkout_paths()` uses `repo.git.checkout(sha, "--", *paths)` — the one place we use GitPython's `git` command passthrough for path-based checkout, since the Python API for partial checkout is awkward

**Thread safety:** Git operations may block (especially push/pull). `ReviewHandler` runs them in background threads and dispatches results via `GLib.idle_add()`. Same pattern as `GatewayHandler`.

**Security:** No shell injection — GitPython's Python API handles all argument escaping. When using `repo.git.*` passthrough, arguments are passed as separate parameters, not interpolated into shell strings.

---

### `utils/diff_parser.py`

**Responsibility:** Parse unified diff output into structured data for rendering. Pure function — no GTK, no git calls, no file I/O.

**Public API:**
```python
from dataclasses import dataclass

@dataclass
class DiffLine:
    """A single line in a diff hunk."""
    type: str              # "add" | "remove" | "context" | "header"
    content: str           # the actual line content (without +/- prefix)
    old_line_no: int | None
    new_line_no: int | None

@dataclass
class DiffHunk:
    """A contiguous block of changes in a file."""
    header: str            # e.g. "@@ -10,5 +10,7 @@"
    old_start: int
    new_start: int
    lines: list[DiffLine]

@dataclass
class FileDiff:
    """All changes to a single file."""
    old_path: str          # e.g. "a/src/main.py"
    new_path: str          # e.g. "b/src/main.py"
    display_path: str      # e.g. "src/main.py" (cleaned)
    is_binary: bool
    is_new: bool           # newly created file
    is_deleted: bool       # deleted file
    is_renamed: bool       # renamed file
    hunks: list[DiffHunk]
    additions: int         # count of added lines
    deletions: int         # count of removed lines

@dataclass
class ParsedDiff:
    """Complete parsed diff output."""
    files: list[FileDiff]
    total_additions: int
    total_deletions: int
    summary: str           # e.g. "3 files changed, 42 additions(+), 7 deletions(-)"

def parse_diff(diff_text: str) -> ParsedDiff:
    """
    Parse unified diff output into structured data.

    Args:
        diff_text: Raw output from `git diff` or `git diff <sha>`

    Returns:
        ParsedDiff with per-file, per-hunk, per-line breakdown.

    Handles:
        - New files (--- /dev/null)
        - Deleted files (+++ /dev/null)
        - Renamed files (diff --git a/old b/new)
        - Binary files (Binary files differ)
        - Empty diffs (no changes)

    Does NOT handle:
        - Merge conflicts (not expected in review flow)
    """

def parse_diff_stat(stat_text: str) -> list[tuple[str, int, int]]:
    """
    Parse `git diff --stat` output.

    Returns:
        [(file_path, additions, deletions), ...]
    """
```

**Rules:**
- Pure function — no class, no state, no side effects
- No imports from `ui/`, `gateway/`, `subprocess`
- All strings are plain Python strings (not Pango markup — rendering happens in the view)

---

### `ui/handlers/review_handler.py`

**Responsibility:** Review session logic — checkpoint, check changes, accept, reject, mode changes. Coordinates `git_ops`, `diff_parser`, and GTK views. All GTK via `GLib.idle_add()`.

**Handler pattern compliance (per ARCHITECTURE.md Section 8.6):**
- One handler per subsystem (review)
- Does not import other handlers — window wires callbacks
- Receives dependencies via constructor
- Owns its state (`_states` dict)
- All GTK from background threads via `GLib.idle_add()`

**Public API:**
```python
class ReviewHandler:
    def __init__(
        self,
        *,
        GLib,                                       # gi.repository.GLib — for idle_add
        main_content,                               # MainContent — for adding/removing ReviewBar
        chat_handler,                               # ChatHandler — for sending rejection messages (via callback)
        project_handler,                            # ProjectHandler — for getting active project path
        on_review_started: Callable[[str], None],   # project_name — window wires to UI updates
        on_review_ended: Callable[[str], None],     # project_name
    ): ...

    # ── Mode management ──────────────────────────────────
    def set_review_mode(self, project_name: str, mode: str) -> None:
        """Set review mode for a project. 'off' or 'review'.
        Called from ReviewBar dropdown change callback."""

    def get_review_mode(self, project_name: str) -> str:
        """Current review mode for a project."""

    # ── Review session lifecycle ─────────────────────────
    def start_review(self, project_name: str) -> None:
        """Start a review session: git add -A && git commit → checkpoint SHA.
        Runs git operations in background thread. Updates ReviewBar on completion.
        Requires: review_mode == "review" and no active session."""

    def check_changes(self, project_name: str) -> None:
        """Check what changed since checkpoint: git diff <sha>.
        Runs git operations in background thread.
        Renders diff cards in project tab on completion."""

    def accept_changes(self, project_name: str, message: str) -> None:
        """Accept all changes: git add -A && git commit -m <message>.
        Optionally git push. Ends review session. Updates ReviewBar."""

    def reject_changes(self, project_name: str, reason: str) -> None:
        """Reject all changes: git checkout <sha> -- .
        Sends rejection reason to all project member sessions via gateway.
        Ends review session. Updates ReviewBar."""

    def reject_file(self, project_name: str, file_path: str) -> None:
        """Reject a single file: git checkout <sha> -- <file_path>.
        Does NOT end review session — other files remain."""

    def get_state(self, project_name: str) -> ReviewState | None:
        """Get current review state for a project."""

    # ── Project lifecycle hooks ──────────────────────────
    def on_project_opened(self, project_name: str, project_path: str) -> None:
        """Called when a project tab opens. Initializes ReviewState.
        Creates ReviewBar if review_mode != 'off'."""

    def on_project_closed(self, project_name: str) -> None:
        """Called when a project tab closes. Cleans up ReviewState.
        Active review sessions are abandoned (checkpoint stays in git history)."""

    def on_project_members_changed(self, project_name: str, members: list[str]) -> None:
        """Called when project membership changes. Updates rejection message targets."""
```

**State ownership:**
```python
self._states: dict[str, ReviewState] = {}  # keyed by project_name
```

**Thread safety:**
- `start_review`, `check_changes`, `accept_changes`, `reject_changes` all run git operations in background threads
- All GTK widget updates (ReviewBar, diff cards, chat bubbles) dispatched via `GLib.idle_add()`
- `_states` dict is only modified from the main thread (all state mutations happen inside `GLib.idle_add()` callbacks)

**Error handling:**
- Git operation fails → error event card in project tab (`.bubble-error` style)
- No checkpoint to diff against → info card: "No active review session"
- No changes since checkpoint → info card: "No changes detected"
- Project not a git repo → `git_init()` called automatically, info card: "Initialized git repo for review"

**Integration points (wired by `window.py`):**
```python
# In window.py _build():

self._review_handler = ReviewHandler(
    GLib=GLib,
    main_content=self._main_content,
    chat_handler=self._chat_handler,
    project_handler=self._project_handler,
    on_review_started=self._on_review_started,
    on_review_ended=self._on_review_ended,
)

# Wire project lifecycle
self._project_handler.set_on_project_opened(
    lambda name, path: self._review_handler.on_project_opened(name, path)
)
# (existing project open callback should also call review_handler)

# Wire ReviewBar callbacks (ReviewBar created by ReviewHandler, added to MainContent)
# ReviewBar.on_mode_changed → ReviewHandler.set_review_mode
# ReviewBar.on_start_clicked → ReviewHandler.start_review
# ReviewBar.on_check_clicked → ReviewHandler.check_changes
```

---

### `ui/views/review_bar.py`

**Responsibility:** Overlay bar at top of project tab chat area. Contains review mode dropdown, status label, and action buttons. Pure view — no logic, no git calls.

**Public API:**
```python
class ReviewBar(Gtk.Box):
    def __init__(
        self,
        *,
        on_mode_changed: Callable[[str], None],       # "off" | "review"
        on_start_clicked: Callable[[], None],          # Start Review button
        on_check_clicked: Callable[[], None],          # Check Changes button
    ): ...

    # ── View updates (called by ReviewHandler) ───────────
    def set_review_mode(self, mode: str) -> None:
        """Update dropdown without firing callback. Called on init and after accept/reject."""

    def set_status(self, text: str) -> None:
        """Update status label. e.g. '3 files changed · awaiting review'"""

    def set_state_idle(self) -> None:
        """No active session. Show: mode dropdown + 'Start Review' button."""

    def set_state_reviewing(self, checkpoint_sha: str) -> None:
        """Active review session. Show: 'Reviewing...' label + 'Check Changes' button + 'End Review' button."""

    def set_state_has_changes(self, file_count: int, additions: int, deletions: int) -> None:
        """Changes detected. Show: 'N files changed (+A/-D)' + 'Check Changes' + 'Accept All' + 'Reject All'."""

    def set_loading(self, loading: bool) -> None:
        """Show/hide a subtle spinner or disable buttons during git operations."""
```

**Layout:**
```
┌──────────────────────────────────────────────────────────────────┐
│  [Review ▾]  │  🔍 No active session  │  [Start Review]         │
└──────────────────────────────────────────────────────────────────┘
```

When review is active:
```
┌──────────────────────────────────────────────────────────────────┐
│  [Review ▾]  │  3 files changed (+42/-7)  │  [Check] [Accept] [Reject]  │
└──────────────────────────────────────────────────────────────────┘
```

**CSS classes:**
- `.review-bar` — semi-transparent background (`rgba(0,0,0,0.05)`), rounded corners, padding
- `.review-bar-status` — muted label color
- `.review-bar-btn-start` — accent color (purple/indigo, matches agent color palette)
- `.review-bar-btn-check` — neutral
- `.review-bar-btn-accept` — green (#10b981 from AGENT_COLORS)
- `.review-bar-btn-reject` — red (#f43f5e from AGENT_COLORS)
- `.review-bar-loading` — subtle opacity pulse animation

**Widget hierarchy:**
```
Gtk.Box (horizontal, .review-bar)
├── Gtk.DropDown (mode: off / review)
├── Gtk.Label (status text)
├── Gtk.Button ("Start Review" / contextual buttons)
├── Gtk.Button ("Check Changes")       # only when active
├── Gtk.Button ("Accept All")          # only when has_changes
└── Gtk.Button ("Reject All")          # only when has_changes
```

**Rules:**
- Pure view — no state beyond widget references
- Never calls `git_ops`, `diff_parser`, or any handler directly
- All user actions go through callbacks provided at construction
- When mode is `off`, the bar is hidden (`set_visible(False)`)

---

### `ui/views/diff_card.py`

**Responsibility:** Diff card widget factories. Creates collapsible, syntax-highlighted diff cards for display in the project chat tab. Pure view — no logic, no git calls.

**Public API:**
```python
def build_file_diff_card(
    file_diff: FileDiff,
    on_accept_file: Callable[[str], None] | None = None,  # file_path
    on_reject_file: Callable[[str], None] | None = None,   # file_path
) -> Gtk.Widget:
    """
    Build a collapsible diff card for a single file.

    Card layout:
    ┌─────────────────────────────────────────────┐
    │ 📄 src/main.py  (+12 / -3)  [▼ collapse]   │
    ├─────────────────────────────────────────────┤
    │  10 │ def process(data):                    │  ← context (muted)
    │  11 │-    return data.strip()               │  ← removed (red bg)
    │  11 │+    return data.strip().lower()       │  ← added (green bg)
    │  12 │+    if not result:                    │  ← added (green bg)
    │  12 │         return None                    │  ← context (muted)
    ├─────────────────────────────────────────────┤
    │              [Accept File] [Reject File]     │  ← optional per-file buttons
    └─────────────────────────────────────────────┘

    Syntax highlighting: each line's content is highlighted via
    utils/syntax_highlight.py using the file extension from file_diff.display_path.
    """


def build_diff_summary_card(
    parsed_diff: ParsedDiff,
    on_accept_all: Callable[[], None] | None = None,
    on_reject_all: Callable[[], None] | None = None,
) -> Gtk.Widget:
    """
    Build a summary card shown above all file diff cards.

    Layout:
    ┌─────────────────────────────────────────────┐
    │ 📋 3 files changed (+42 additions, -7 deletions) │
    │                                              │
    │ • src/main.py  (+12/-3)                      │
    │ • src/utils.py  (+30/-4)                     │
    │ • tests/test_main.py  (new file, +15)        │
    │                                              │
    │          [Accept All]  [Reject All]           │
    └─────────────────────────────────────────────┘
    """
```

**CSS classes:**
- `.diff-card` — base card style (dark bg, rounded corners, border)
- `.diff-card-header` — file path + stats row
- `.diff-card-body` — scrollable hunk container
- `.diff-line-add` — green background (`rgba(16,185,129,0.15)`)
- `.diff-line-remove` — red background (`rgba(244,63,94,0.15)`)
- `.diff-line-context` — muted text color
- `.diff-line-number` — fixed-width, muted, right-aligned
- `.diff-hunk-header` — cyan/muted background for `@@ ... @@` lines
- `.diff-badge-add` — green pill badge for "+12"
- `.diff-badge-remove` — red pill badge for "-3"
- `.diff-badge-new` — blue pill badge for "NEW"
- `.diff-badge-deleted` — gray pill badge for "DELETED"
- `.diff-btn-accept-file` — small green button
- `.diff-btn-reject-file` — small red button
- `.diff-btn-accept-all` — full-width green button
- `.diff-btn-reject-all` — full-width red button
- `.diff-collapsed .diff-card-body` — `display: none` (collapsed state)

**Line rendering:**
Each diff line is a horizontal box:
```
Gtk.Box (horizontal)
├── Gtk.Label (old line number, fixed-width, muted)   # e.g. "10"
├── Gtk.Label (new line number, fixed-width, muted)   # e.g. "10"
└── Gtk.Label (line content, syntax-highlighted)       # Pango markup
```

**Syntax highlighting:** Per-line. Extract file extension from `file_diff.display_path`. Use `syntax_highlight.highlight(line_content, lang)` for each add/remove/context line. Context lines get lighter treatment (muted foreground color overrides).

**Collapsing:** Clicking the header toggles `.diff-collapsed` CSS class on the card. The body has `transition: all 150ms ease` for smooth collapse animation.

**Rules:**
- Pure view — no state beyond widget references
- Never calls `git_ops` or `diff_parser`
- All accept/reject actions go through callbacks
- `FileDiff` and `ParsedDiff` are from `utils/diff_parser.py` (pure data, no GTK)

---

## Data Flow

### Full Review Lifecycle

```
PM opens project tab (project: "kalshi-ata")
  → window._on_project_opened(name, path)
    → review_handler.on_project_opened(name, path)
      → creates ReviewState(project_path=path, review_mode="off")
      → ReviewBar not shown (mode is off)


PM selects "review" from ReviewBar dropdown
  → ReviewBar.on_mode_changed → review_handler.set_review_mode(name, "review")
    → state.review_mode = "review"
    → ReviewBar.set_state_idle() — shows "Start Review" button


PM clicks "Start Review"
  → ReviewBar.on_start_clicked → review_handler.start_review(name)
    → background thread:
        → git_ops.git_add_all(project_path)        # stage all current files
        → git_ops.git_commit(project_path, "review checkpoint")  # snapshot
        → git_ops.git_rev_parse_head(project_path)  # get SHA
    → GLib.idle_add:
        → state.checkpoint_sha = sha
        → ReviewBar.set_state_reviewing(sha)
        → info bubble in project tab: "🔍 Review session started — checkpoint abc1234"


Agents work (write files normally through gateway tools)
  → Files change on disk
  → CrabCakes does NOT intercept — agents are unaware of review system


PM clicks "Check Changes"
  → ReviewBar.on_check_clicked → review_handler.check_changes(name)
    → background thread:
        → git_ops.git_diff(project_path, state.checkpoint_sha)
        → diff = diff_parser.parse_diff(result.stdout)
    → GLib.idle_add:
        → state.last_check_files = [f.display_path for f in diff.files]
        → state.is_dirty = True
        → ReviewBar.set_state_has_changes(len(diff.files), diff.total_additions, diff.total_deletions)
        → build_diff_summary_card(diff, on_accept_all, on_reject_all) → append to project tab chat
        → for file_diff in diff.files:
            → build_file_diff_card(file_diff, on_accept_file, on_reject_file) → append to project tab chat


PM reviews diffs visually in chat tab


Accept All:
  → review_handler.accept_changes(name, message="approved: agent changes")
    → background thread:
        → git_ops.git_add_all(project_path)
        → git_ops.git_commit(project_path, message)
        → git_ops.git_push(project_path)  # optional — configurable
    → GLib.idle_add:
        → state.checkpoint_sha = None
        → state.is_dirty = False
        → ReviewBar.set_state_idle()
        → success bubble: "✅ Changes accepted and committed"


Reject All:
  → review_handler.reject_changes(name, reason="needs tests")
    → background thread:
        → git_ops.git_checkout(project_path, f"{state.checkpoint_sha} -- .")  # revert all files
    → GLib.idle_add:
        → send rejection message to all project members via ChatHandler
          → "Changes rejected: needs tests. Files reverted to checkpoint abc1234."
        → state.checkpoint_sha = None
        → state.is_dirty = False
        → ReviewBar.set_state_idle()
        → info bubble: "❌ Changes rejected — files reverted to checkpoint"


Reject Single File:
  → diff_card.on_reject_file → review_handler.reject_file(name, file_path)
    → background thread:
        → git_ops.git_checkout(project_path, f"{state.checkpoint_sha} -- {file_path}")
    → GLib.idle_add:
        → info bubble: "↩ {file_path} reverted to checkpoint"
        → if state still dirty: ReviewBar stays in has_changes
        → if no more changes: ReviewBar transitions to reviewing
```

### PM Edits Files Too

If the PM edits files directly (outside CrabCakes), those changes are also captured by the checkpoint diff. The review system doesn't distinguish between PM changes and agent changes — it shows everything that changed since the checkpoint. The PM is responsible for knowing which changes are theirs.

**Future improvement:** Track agent-specific changes by correlating gateway `tool_call` events with file modification timestamps. Not in scope for v0.1.

---

## CSS Additions to `ui/styles.py`

All new CSS is appended to `APP_CSS` in `ui/styles.py`. Per ARCHITECTURE.md Section 9: no other file may define CSS.

```css
/* Review Bar */
.review-bar {
    background: rgba(0, 0, 0, 0.05);
    border-radius: 8px;
    padding: 6px 12px;
    margin: 4px 8px;
}
.review-bar-status {
    color: alpha(@theme_fg_color, 0.6);
    font-size: 0.9em;
}
.review-bar-btn-start {
    background: #6366f1;
    color: white;
    border-radius: 6px;
    padding: 4px 12px;
}
.review-bar-btn-check {
    background: alpha(@theme_fg_color, 0.1);
    border-radius: 6px;
    padding: 4px 12px;
}
.review-bar-btn-accept {
    background: #10b981;
    color: white;
    border-radius: 6px;
    padding: 4px 12px;
}
.review-bar-btn-reject {
    background: #f43f5e;
    color: white;
    border-radius: 6px;
    padding: 4px 12px;
}
.review-bar-loading {
    opacity: 0.6;
}

/* Diff Cards */
.diff-card {
    background: rgba(0, 0, 0, 0.03);
    border: 1px solid alpha(@theme_fg_color, 0.1);
    border-radius: 8px;
    margin: 4px 0;
    overflow: hidden;
}
.diff-card-header {
    padding: 8px 12px;
    border-bottom: 1px solid alpha(@theme_fg_color, 0.08);
    font-family: monospace;
    font-size: 0.9em;
}
.diff-card-header:hover {
    background: alpha(@theme_fg_color, 0.03);
}
.diff-card-body {
    padding: 4px 0;
}
.diff-line-add {
    background: rgba(16, 185, 129, 0.15);
    padding: 1px 12px;
    font-family: monospace;
    font-size: 0.85em;
}
.diff-line-remove {
    background: rgba(244, 63, 94, 0.15);
    padding: 1px 12px;
    font-family: monospace;
    font-size: 0.85em;
}
.diff-line-context {
    color: alpha(@theme_fg_color, 0.5);
    padding: 1px 12px;
    font-family: monospace;
    font-size: 0.85em;
}
.diff-line-number {
    color: alpha(@theme_fg_color, 0.3);
    font-family: monospace;
    min-width: 3em;
    text-align: right;
}
.diff-hunk-header {
    background: rgba(6, 182, 212, 0.1);
    color: alpha(@theme_fg_color, 0.5);
    padding: 2px 12px;
    font-family: monospace;
    font-size: 0.85em;
}
.diff-badge-add {
    background: rgba(16, 185, 129, 0.2);
    color: #10b981;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.8em;
}
.diff-badge-remove {
    background: rgba(244, 63, 94, 0.2);
    color: #f43f5e;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.8em;
}
.diff-badge-new {
    background: rgba(6, 182, 212, 0.2);
    color: #06b6d4;
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.8em;
}
.diff-badge-deleted {
    background: alpha(@theme_fg_color, 0.1);
    color: alpha(@theme_fg_color, 0.5);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 0.8em;
}
.diff-collapsed .diff-card-body {
    display: none;
}
```

---

## Integration with window.py

Per ARCHITECTURE.md Section 8.6: window.py is the composition root. It creates all handlers and wires their callbacks. No handler imports another handler.

### New instance variables in MainWindow:

```python
self._review_handler: ReviewHandler        # created in _build()
```

### Wiring in `_build()`:

```python
# Review handler — after other handlers are created
self._review_handler = ReviewHandler(
    GLib=GLib,
    main_content=self._main_content,
    project_handler=self._project_handler,
    chat_handler=self._chat_handler,
    on_review_started=self._on_review_started,
    on_review_ended=self._on_review_ended,
)

# Wire project lifecycle — extend existing _on_project_opened callback
# to also call review_handler.on_project_opened(name, path)

# Wire project close — extend existing _on_tab_close to also call
# review_handler.on_project_closed(project_name)

# Wire membership changes — extend existing _on_project_members_changed
# to also call review_handler.on_project_members_changed(name, members)
```

### New callback stubs in window.py:

```python
def _on_review_started(self, project_name: str):
    """Review session started — update any UI that needs to know."""

def _on_review_ended(self, project_name: str):
    """Review session ended (accept or reject) — update UI."""
```

---

## Tests

Per ARCHITECTURE.md Section 8.5: every handler and utility must have tests. Tests live in `tests/`.

### `tests/test_git_ops.py`

Test against a temporary git repo (created via GitPython in setUp, deleted in tearDown).

| Test | What it verifies |
|------|-----------------|
| `test_is_repo` | True for valid repo, False for plain directory |
| `test_init_repo` | Creates valid git repository |
| `test_init_existing_repo` | Idempotent — no error if already a repo |
| `test_commit` | Commit succeeds, returns SHA in result.sha |
| `test_diff_empty` | No changes → empty stdout, success=True |
| `test_diff_changes` | Modify file → diff contains file path and changes |
| `test_diff_stat` | Stat output returned as text |
| `test_get_head_sha` | Returns valid 40-char SHA |
| `test_checkout_paths_revert` | Modify file, checkout SHA -- path → file reverted |
| `test_checkout_paths_multiple` | Revert multiple files at once |
| `test_push_no_remote` | Push fails gracefully (GitResult.success=False, error message) |
| `test_status_porcelain` | New file → status shows `?? filename` |
| `test_log` | Returns commit log text with message |
| `test_error_handling` | Invalid path → GitResult.success=False, no exception raised |

### `tests/test_diff_parser.py`

| Test | What it verifies |
|------|-----------------|
| `test_parse_empty_diff` | Empty string → 0 files |
| `test_parse_single_file_addition` | New file with content → is_new=True, correct additions count |
| `test_parse_single_file_deletion` | Deleted file → is_deleted=True, correct deletions count |
| `test_parse_modification` | Changed lines → correct add/remove counts, hunks with line numbers |
| `test_parse_multiple_files` | 3-file diff → 3 FileDiff objects |
| `test_parse_binary_file` | Binary diff → is_binary=True, no hunks |
| `test_parse_renamed_file` | Renamed diff → is_renamed=True, correct old/new paths |
| `test_parse_hunk_headers` | `@@ -10,5 +10,7 @@` → old_start=10, new_start=10 |
| `test_parse_diff_stat` | Stat output → [(path, additions, deletions), ...] |
| `test_parse_real_git_output` | Use actual `git diff` output from test repo |

### `tests/test_review_handler.py`

Uses mock git_ops (patch `utils.git_ops` functions to return canned `GitResult`).

| Test | What it verifies |
|------|-----------------|
| `test_set_review_mode` | State updates, ReviewBar receives mode change |
| `test_start_review_off_mode` | Mode=off → no checkpoint (no-op) |
| `test_start_review_creates_checkpoint` | Mode=review → git commit called, SHA stored |
| `test_check_changes_no_changes` | Empty diff → "no changes" info card |
| `test_check_changes_with_files` | 2-file diff → 2 diff cards rendered |
| `test_accept_changes` | Git add + commit called, state reset to idle |
| `test_reject_changes` | Git checkout called, rejection message sent to agents |
| `test_reject_single_file` | Only that file reverted, review session stays active |
| `test_project_closed_mid_review` | State cleaned up, no crash |
| `test_non_git_repo_auto_init` | Project without .git → git init called automatically |

---

## Phase Plan — Build Phase 2: Review Layer

Each phase includes updating `docs/ARCHITECTURE.md` (Section 2: directory tree, Section 3: module responsibilities, Section 11: file inventory). A phase is not complete until ARCHITECTURE.md reflects the new code.

**Depends on:** Build Phase 1 (Agent Runtime) — agents must exist to produce changes worth reviewing.

### Step 2.1 — Git Operations + Diff Parsing

**Goal:** Pure utility layer works end-to-end.

**Steps:**
1. Create `utils/git_ops.py` — GitPython wrapper functions
2. Create `utils/diff_parser.py` — unified diff parser
3. Create `models/review_state.py` — ReviewState dataclass
4. Write `tests/test_git_ops.py` — test against temp git repos
5. Write `tests/test_diff_parser.py` — test with real and synthetic diff output
6. Write `tests/test_review_state.py` — dataclass edge cases
7. Update `docs/ARCHITECTURE.md`

**Checkpoint:** A test script can create a temp repo, commit files, modify them, get a structured diff, and revert. All via the new modules. No GTK involved.

### Step 2.2 — Review Bar View

**Goal:** ReviewBar widget renders correctly in a project tab.

**Steps:**
1. Create `ui/views/review_bar.py`
2. Add review bar CSS to `ui/styles.py` (`.review-bar*` classes)
3. Wire ReviewBar creation into `MainContent.create_chat_tab()` for project tabs
4. Test: open project tab → ReviewBar visible with "Start Review" button
5. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Project tab shows ReviewBar. Dropdown toggles between off/review. Buttons are clickable (callbacks fire). No git operations yet.

### Step 2.3 — Diff Card View

**Goal:** Diff cards render beautifully from structured diff data.

**Steps:**
1. Create `ui/views/diff_card.py`
2. Add diff card CSS to `ui/styles.py` (`.diff-*` classes)
3. Build test harness: feed synthetic `ParsedDiff` → render cards in a temp window
4. Verify: added lines green, removed lines red, syntax highlighting works, collapse works
5. Update `docs/ARCHITECTURE.md`

**Checkpoint:** Given a `ParsedDiff` object, `build_file_diff_card()` and `build_diff_summary_card()` produce correct, styled GTK widgets. No git operations yet.

### Step 2.4 — Review Handler Integration

**Goal:** Full lifecycle works end-to-end.

**Steps:**
1. Create `ui/handlers/review_handler.py`
2. Wire in `window.py` — create handler, connect callbacks
3. Wire ReviewBar callbacks to ReviewHandler methods
4. Wire diff card accept/reject buttons to ReviewHandler methods
5. Wire project lifecycle hooks (open/close/members-changed)
6. Write `tests/test_review_handler.py` — mock git_ops, verify state transitions
7. Update `docs/ARCHITECTURE.md`

**Checkpoint:** In a running CrabCakes instance:
- Open project tab → ReviewBar visible
- Start Review → checkpoint created, status updates
- Agent modifies files (manually simulate)
- Check Changes → diff cards appear in chat
- Accept → changes committed, bar resets
- Reject → files reverted, agents notified

### Step 2.5 — Polish

**Goal:** Production-quality UX.

**Steps:**
1. Loading states: disable buttons during git operations, subtle spinner
2. Error cards: git failures, network errors, no-repo errors surfaced in chat
3. Auto-check: optional timer that polls for changes during active review (configurable interval)
4. Keyboard shortcuts: Ctrl+Enter to accept, Escape to reject
5. Diff card improvements: copy-file-path on click, open-in-editor button
6. Edge cases: empty project, binary files, very large diffs (truncate with "show more")
7. Update `docs/ARCHITECTURE.md`
8. Update `docs/PROJECT_STATUS.md`

**Checkpoint:** The review system feels like a native part of CrabCakes, not a bolted-on git client. Errors are handled gracefully. Large diffs don't freeze the UI.

---

## Implementation Notes

- **Git:** GitPython library (`import git`) — no `subprocess.run()` calls. GitPython provides structured access to repositories, commits, diffs, and remotes without shell invocation.
- **New pip package:** `gitpython` — the only new dependency.
- **No gateway changes required.** CrabCakes reads the local filesystem and runs local git commands.
- **Non-review projects unaffected.** Projects with review_mode=off have no ReviewBar, no git operations, no overhead.
- **Checkpoint commits are lightweight.** They're regular git commits — visible in `git log`, can be inspected later. No special git objects.
- **Crash recovery:** If CrabCakes crashes during a review session, the checkpoint commit is still in git history. On restart, ReviewHandler can detect the last checkpoint by looking for commits matching the `review checkpoint` message pattern.
- **Merge conflicts:** Not handled in v0.1. If a PM edits files during a review session and an agent also edits the same files, the diff will show both sets of changes. Accept will attempt to commit; git will merge if possible or fail with a conflict error (surfaced as error card).

---

## What This Doesn't Do (Honestly)

| Feature | Why not |
|---------|----------|
| Prevent agents from writing files (off/review mode) | Requires gateway enforcement — CrabCakes can't intercept. `isolated` mode solves this via AgentFS. |
| Per-agent change attribution | Gateway `tool_call` events have timestamps but no file-level mapping |
| Gated mode (hook blocks unapproved pushes) | Replaced by `isolated` mode — AgentFS provides stronger isolation than git hooks |
| Conflict resolution UI | Complex; v0.1 surfaces the error, PM resolves manually |
| Remote project support | CrabCakes must be on the same machine as the project files |

These are real limitations for off/review modes. They can be addressed in future phases or by extending the gateway, but they're out of scope for this spec.

---

## Isolated Mode — AgentFS Integration (Phase 2)

**Status:** Future — depends on AgentFS (by Turso) reaching stable release.
**What is AgentFS:** A SQLite-backed filesystem for AI agents. Everything an agent does — files, state, tool calls — lives in a single `.db` file. Provides POSIX-like virtual filesystem, key-value store, and audit trail. SDKs in Python, TypeScript, Rust. FUSE mount on Linux, NFS on macOS. See: https://github.com/tursodatabase/agentfs

### Why AgentFS

The `off` and `review` modes share a fundamental limitation: agents write directly to the real filesystem. CrabCakes can't prevent this — it can only observe and revert after the fact (review mode) or not care (off mode).

AgentFS solves this by giving agents their own isolated filesystem. The agent thinks it's writing to `/project/src/main.py`, but it's actually writing to a SQLite database. The real project directory is untouched until the PM explicitly accepts changes.

### How Isolated Mode Works

```
PM sets review mode to "isolated" for project "kalshi-ata"
  → ReviewHandler initializes AgentFS workspace:
    → agentfs init kalshi-ata  (creates .agentfs/kalshi-ata.db)
    → agentfs mount kalshi-ata ./mnt-kalshi-ata  (FUSE mount)
    → Project files copied into virtual FS: cp -r /project/* ./mnt-kalshi-ata/
    → Agent tool sandbox reconfigured: project_path = ./mnt-kalshi-ata


Agent receives task: "Add error handling to on_send()"
  → Agent reads ./mnt-kalshi-ata/src/handlers/chat_handler.py  (from SQLite, not real disk)
  → Agent writes ./mnt-kalshi-ata/src/handlers/chat_handler.py  (to SQLite, not real disk)
  → Agent runs tests: exec_command("cd /mnt-kalshi-ata && python -m pytest")  (against virtual FS)
  → All operations logged in AgentFS audit trail (tool_calls table)


PM clicks "Check Changes"
  → ReviewHandler queries AgentFS audit trail:
    → agentfs timeline kalshi-ata  (all tool calls with timestamps)
  → ReviewHandler diffs virtual FS against real project:
    → For each file modified in virtual FS vs real FS, generate unified diff
  → Render diff cards in project tab (same visual as review mode)


PM clicks "Accept All"
  → ReviewHandler copies accepted files from virtual FS to real filesystem:
    → For each accepted file: cp ./mnt-kalshi-ata/src/file.py /real/project/src/file.py
    → git add -A && git commit -m "approved: agent changes"  (auto-commit)
  → ReviewHandler resets virtual FS to match real project (clean slate for next task)


PM clicks "Reject All"
  → ReviewHandler discards virtual FS changes:
    → agentfs snapshot restore kalshi-ata <pre-task-snapshot-id>
    → OR: delete and reinitialize the virtual FS from real project
  → No real files were ever touched. Zero risk.
```

### New Dependencies

| Dependency | Version | Purpose |
|-----------|---------|----------|
| `agentfs-sdk` (Python) | ≥0.1.0 | AgentFS Python SDK for programmatic FS access |
| `agentfs` CLI | ≥0.1.0 | FUSE mounting and snapshot management |

**System requirements:** Linux with FUSE support (for mount). macOS uses NFS mount. Windows not supported for isolated mode.

### New Modules

| Module | Package | Responsibility |
|--------|---------|---------------|
| `utils/agentfs_ops.py` | `utils/` | AgentFS wrapper — init, mount, snapshot, diff, accept, reject. Returns structured results. Pure functions, no GTK. |

### `utils/agentfs_ops.py` Public API

```python
from dataclasses import dataclass

@dataclass
class AgentFSResult:
    success: bool
    error: str
    data: dict | None = None  # response data

def init_workspace(project_path: str, agentfs_id: str) -> AgentFSResult:
    """Initialize AgentFS workspace for a project. Creates .agentfs/<id>.db."""

def mount_workspace(agentfs_id: str, mount_path: str) -> AgentFSResult:
    """FUSE mount the agent workspace at mount_path."""

def unmount_workspace(mount_path: str) -> AgentFSResult:
    """Unmount the FUSE mount."""

def snapshot_workspace(agentfs_id: str, label: str) -> AgentFSResult:
    """Create a named snapshot of the current workspace state."""

def restore_snapshot(agentfs_id: str, label: str) -> AgentFSResult:
    """Restore workspace to a named snapshot."""

def get_timeline(agentfs_id: str) -> AgentFSResult:
    """Get audit trail — all tool calls with timestamps and status."""

def diff_against_real(virtual_path: str, real_path: str) -> AgentFSResult:
    """Diff the virtual filesystem against the real project directory."""

def accept_files(agentfs_id: str, file_paths: list[str], real_project_path: str) -> AgentFSResult:
    """Copy accepted files from virtual FS to real filesystem."""

def reject_all(agentfs_id: str, real_project_path: str) -> AgentFSResult:
    """Reset virtual FS to match real project (discard all agent changes)."""

def sync_from_real(agentfs_id: str, real_project_path: str) -> AgentFSResult:
    """Update virtual FS to match current real project state (e.g. after PM edits real files)."""
```

### ReviewHandler Changes for Isolated Mode

```python
# In review_handler.py — extended from review mode

class ReviewHandler:
    def set_review_mode(self, project_name: str, mode: str) -> None:
        if mode == "isolated":
            # Initialize AgentFS workspace
            # Mount FUSE
            # Reconfigure agent tool paths to point to mount
            # Snapshot baseline
            ...
        elif mode == "review" or mode == "off":
            # If currently isolated, unmount and clean up
            ...

    def check_changes(self, project_name: str) -> None:
        if state.review_mode == "isolated":
            # Query AgentFS audit trail
            # Diff virtual FS against real project
            # Render diff cards + audit timeline card
            ...
        elif state.review_mode == "review":
            # Existing git diff behavior
            ...

    def accept_changes(self, project_name: str, message: str) -> None:
        if state.review_mode == "isolated":
            # Copy accepted files from virtual FS to real filesystem
            # Auto-commit
            # Reset virtual FS
            ...
        elif state.review_mode == "review":
            # Existing git accept behavior
            ...

    def reject_changes(self, project_name: str, reason: str) -> None:
        if state.review_mode == "isolated":
            # Restore snapshot (discard all virtual FS changes)
            # Send rejection to agents
            ...
        elif state.review_mode == "review":
            # Existing git reject behavior
            ...
```

### ReviewBar Changes for Isolated Mode

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  [Review ▾]  │  🛡️ Isolated  │  3 tool calls · 2 files changed  │  [Check] [Accept] [Reject]  │
└──────────────────────────────────────────────────────────────────────────────┘
```

- Status label shows isolation indicator (🛡️) and tool call count from audit trail
- Same accept/reject buttons as review mode
- Additional "Audit Trail" button that shows full tool call timeline in a card

### Step 2.6 — Isolated Mode (AgentFS Integration) — Future

**Goal:** True filesystem isolation for agent work.

**Steps:**
1. Add `agentfs-sdk` dependency
2. Create `utils/agentfs_ops.py` — AgentFS wrapper
3. Extend `ReviewHandler` with isolated mode lifecycle
4. Extend `ReviewBar` with isolation indicator and audit trail button
5. Reconfigure agent tool paths when isolated mode is active
6. Write `tests/test_agentfs_ops.py` — test against real AgentFS CLI
7. Update `docs/ARCHITECTURE.md`
8. Update `docs/PROJECT_STATUS.md`

**Checkpoint:** Agent works in isolated workspace → PM sees audit trail + diff cards → accept writes to real filesystem → reject discards without touching real files. True zero-risk agent workflow.

---

*This document is the single source of truth for the CrabCakes review system. Previous versions (`git-review-layer.md`, `review-layer.md`) have been removed.*
