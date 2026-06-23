# PROPOSAL: One-Click Diff — File Tree Diff Viewer with Historical Revert

**Date:** 2026-06-22 (revised 2026-06-22)
**Author:** Qaster
**Status:** Proposal — revised per QTR review (REVIEW-ONE-CLICK-DIFF.md). Pending Captain approval.
**Priority:** High
**Effort:** ~10-14 hours (revised upward from 8-12 to account for QTR fixes)

---

## Revision Summary

This proposal was revised to address all 8 issues identified in QTR's adversarial review, plus non-blocking concerns A–F. Every fix was verified against the actual codebase. See the "QTR Issue Resolution" appendix for a point-by-point mapping.

**Key changes from v1:**
- Fixed incorrect `_current_project_path` reference → `_project_handler.get_active_project_path()`
- Fixed critical diff logic bug: added `diff_file_against_working_tree()` for uncommitted changes
- Added architecture decision for revert (new `review_handler.revert_file_to_sha()` method)
- Replaced duplicate diff renderer with reuse of existing `diff_card.py` functions
- Specified exact layout: diff viewer in `main_content`, following `set_review_bar()` pattern
- Added Phase 0 (quick win: wire file click → existing diff card, 1-2 hours)
- Moved file-tree badges to separate proposal
- Added SHA validation note
- Specified post-revert UX

---

## Why

### The Problem

When an agent modifies files in a project, the PM needs to review those changes. Today, the review flow is:

1. Run `/check` in the project chat
2. Scroll through diff cards in the chat feed
3. Accept or reject from there

The `/check` flow already gives per-file diff cards with Accept/Reject buttons — it's functional. But it requires the PM to be in the right chat session, run a command, and review changes in chronological order rather than by file.

The file tree — sitting right there in the left panel showing the project structure — is a **passive browser**. You can see files. You can't *do* anything with them. Clicking a file fires `_on_project_selected` (`ui/window.py:803`), which is a no-op (`pass`).

**The real UX win:** let the PM click any file in the tree and immediately see its diff — without running `/check` first, without being in a specific chat session. The file tree becomes the entry point for code review.

### The Solution

Turn the file tree into an active review surface:

1. **Click a file** → see what changed (current diff vs. checkpoint or HEAD)
2. **View edit history** → a list of commits that touched that file
3. **Click any historical edit** → see that diff, with a **Revert to this version** button

---

## What

### User Flow

```
File Tree (left panel) → Click File → Diff Viewer (main_content) → [History Tab] → Click Historical Edit → See Diff + Revert
```

The file tree stays in the left panel for further navigation. The diff viewer opens in `main_content` (right pane), following the same insert/remove pattern as `set_review_bar()`.

### What the PM Sees

**Layer 1 — Current Diff:**

Click `ui/window.py` in the file tree. A diff viewer opens in the main content area showing:

```
ui/window.py
+12 additions, -3 deletions (since checkpoint abc1234)

  def _on_select_all(self):
+     buf = self._main_content.user_input.get_buffer()
+     buf.select_range(buf.get_end_iter(), buf.get_start_iter())
+     self._main_content.user_input.grab_focus()
```

If no changes: "No changes to this file."

**Layer 2 — Edit History:**

A toggle/tab in the diff viewer shows the file's edit timeline:

```
Edit History — ui/window.py
─────────────────────────────
🔴 a6b07d2  2026-06-22 15:06  "feat: add Select All toolbar button"
⚪ 326c91f  2026-06-22 14:30  "fix: popover leak on tab switch"
⚪ 8f4a2c1  2026-06-22 11:15  "refactor: extract review handler"
⚪ 2b1e3d8  2026-06-21 18:00  "feat: wire review bar accept/reject"
```

Each entry: short SHA, timestamp, commit message.

**Layer 3 — Historical Diff + Revert:**

Click any historical entry → diff viewer shows that commit's changes. Below the diff:

```
[ ← Revert file to this version ]
```

Click revert → confirmation dialog → file restored to its state at that commit.

### What Does NOT Change

- `/check`, `/accept`, `/reject` chat commands work exactly as before
- Existing diff cards in the chat feed still render during `/check`
- `ReviewHandler.reject_file()`, `review_state.py`, and `diff_parser.py` are unchanged
- File tree directory expansion/collapse behavior unchanged

---

## Scope

### In Scope

| Component | Change |
|-----------|--------|
| `ui/views/file_tree.py` | Wire file click → diff view instead of no-op |
| New: `ui/views/diff_viewer.py` | Diff viewer widget (header + diff render + history list + revert) |
| `utils/git_ops.py` | Add `file_log()` and `diff_file_against_working_tree()` |
| `ui/handlers/review_handler.py` | Add `revert_file_to_sha()` method (no session gate) |
| `ui/views/main_content.py` | Add `show_diff_viewer()` / `hide_diff_viewer()` methods |
| `ui/window.py` | Wire `_on_project_selected` to open diff viewer |
| `ui/views/diff_card.py` | Extract `render_diff_hunks()` helper for reuse |
| Tests | Unit tests for new git_ops functions, revert method, wiring |

### Out of Scope

- Breadcrumb Trail (separate proposal)
- Live Attention / file glow (cut — not building)
- File-tree badges/dots on changed files (moved to separate proposal — has its own complexity)
- Cross-file revert (revert multiple files at once)
- Diff comparison between two arbitrary commits
- Syntax highlighting in diffs (future enhancement)
- Rename of `_on_project_selected` → `_on_file_selected` (existing misnaming, separate refactor)

---

## Infrastructure Audit — What Exists vs. What's New

### Already Exists (no new code needed)

| Capability | Location | Notes |
|------------|----------|-------|
| Per-file diff (commit-to-commit) | `git_ops.diff_file_against(path, sha, file)` `git_ops.py:168` | `sha → HEAD`. **Does NOT include uncommitted changes** — see Issue #2 |
| Working tree diff (vs HEAD) | `git_ops.diff_working_tree(path, file)` `git_ops.py:239` | `HEAD → working tree` (unstaged + staged) |
| Diff parsing | `diff_parser.parse_diff(text)` | Structured `FileDiff` with hunks, lines, counts |
| Revert file to SHA | `git_ops.checkout_paths(path, sha, [file])` `git_ops.py:178` | Already used by `review_handler.reject_file()`. **Validates SHA** via `_VALID_SHA_RE` (`git_ops.py:44`) |
| Per-hunk diff rendering | `diff_card._build_hunk_view(hunk, lang)` `diff_card.py:147` | Builds `Gtk.Box` with colored lines, line numbers, hunk headers |
| Per-line diff rendering | `diff_card._build_diff_line(box, line, lang)` `diff_card.py:97` | Adds old/new line numbers + content with CSS classes |
| File diff card (full) | `diff_card.build_file_diff_card(file_diff, ...)` `diff_card.py:166` | Full card with header, badges, hunks, accept/reject |
| Review state (checkpoint SHA) | `ReviewState.checkpoint_sha` | Per-project, set during `/review` |
| Recent commits list | `git_ops.get_recent_commits(path, count)` `git_ops.py:204` | Returns last N commits |
| Active project path | `ProjectHandler.get_active_project_path()` `project_handler.py:471` | Returns path or `None` |
| Review bar insert/remove pattern | `MainContent.set_review_bar(bar)` `main_content.py:884` | Insert/remove widget pattern to follow for diff viewer |

### New Code Required

| Capability | Location | Notes |
|------------|----------|-------|
| Per-file commit history | `git_ops.file_log(path, file)` → **new function** | `git log --follow --format="%H\|%cI\|%s" -n <count> -- <file>` |
| Per-file diff vs. working tree | `git_ops.diff_file_against_working_tree(path, sha, file)` → **new function** | `git diff <sha> -- <file>` (sha → working tree, includes uncommitted) |
| Diff viewer widget | `ui/views/diff_viewer.py` → **new file** | GTK4 widget: header + reused diff renderer + history list + revert |
| Revert to arbitrary SHA | `review_handler.revert_file_to_sha(project, file, sha)` → **new method** | No session gate. Posts audit message to chat. Uses `checkout_paths` |
| Diff viewer slot in main content | `main_content.show_diff_viewer(widget)` / `hide_diff_viewer()` → **new methods** | Follows `set_review_bar()` insert/remove pattern |
| Reusable diff hunks renderer | `diff_card.render_diff_hunks(hunks, lang)` → **extract from existing** | Refactor: extract from `build_file_diff_card` so both card and viewer share it |
| File click wiring | `ui/window.py:803` | Replace `pass` with diff viewer open call |

---

## Technical Design

### 1. `git_ops.diff_file_against_working_tree()` — New

**Why this is needed (QTR Issue #2):**

The existing `diff_file_against(path, sha, file)` does `git diff <sha> HEAD -- <file>` — a commit-to-commit diff. During an active review, agents are editing files but haven't committed yet. The PM clicks a file expecting to see "what changed since checkpoint" — but gets nothing because `HEAD` hasn't moved.

**New function:**

```python
def diff_file_against_working_tree(project_path: str, sha: str, file_path: str) -> GitResult:
    """Diff for a single file between commit sha and working tree (includes uncommitted)."""
    try:
        repo = gitpython.Repo(project_path)
        diff_text = repo.git.diff(sha, "--", file_path)  # sha → working tree
        return GitResult(success=True, stdout=diff_text, error="", sha=repo.head.commit.hexsha)
    except Exception as e:
        return GitResult(success=False, stdout="", error=_safe_error(e), sha=None)
```

**Diff strategy by state:**

| State | Function called | What it shows |
|---|---|---|
| Active review (checkpoint set) | `diff_file_against_working_tree(path, checkpoint_sha, file)` | Checkpoint → working tree (includes uncommitted agent edits) |
| No review (no checkpoint) | `diff_working_tree(path, file)` | HEAD → working tree (uncommitted changes only) |
| Historical commit selected | `diff_file_against(path, parent_sha, file)` | Parent of selected commit → selected commit (what that commit changed) |

### 2. `git_ops.file_log()` — New

```python
def file_log(project_path: str, file_path: str, count: int = 20) -> GitResult:
    """
    Get commit history for a single file.
    Returns: GitResult with stdout = lines of "SHA|ISO_DATE|MESSAGE"

    Note: --follow tracks renames but NOT copies. Git's rename detection
    depends on diff.renames config (default: true in modern git). For files
    in small-to-medium repos (<10K commits), --follow is reliable and fast.
    """
    try:
        repo = gitpython.Repo(project_path)
        log_text = repo.git.log("--follow", f"--format=%H|%cI|%s", f"-n {count}", "--", file_path)
        return GitResult(success=True, stdout=log_text, error="", sha=None)
    except Exception as e:
        return GitResult(success=False, stdout="", error=_safe_error(e), sha=None)
```

**SHA safety:** SHAs returned by `file_log()` are full 40-char hex strings from `git log --format=%H`. When passed to `checkout_paths()`, they pass the existing `_VALID_SHA_RE` validation (`git_ops.py:44`: `^(HEAD|[0-9a-fA-F]{4,40})$`). No injection vector.

**Performance note:** `--follow` walks full history but `-n 20` caps output count. For CrabCakes projects (typically <1K commits), this is sub-100ms. No max-walk-depth safeguard needed at current scale. If projects grow beyond 10K commits, consider adding `--max-count` with `--since` as a depth limit.

### 3. Diff Rendering — Reuse Existing `diff_card.py` (QTR Issue #4)

**No new `Gtk.TextView`-based renderer.** Instead, refactor `diff_card.py` to extract a reusable function:

**Current** (`diff_card.py:166`):
```python
def build_file_diff_card(file_diff, on_accept_file=None, on_reject_file=None):
    # header + badges + hunks + action buttons — all inline
```

**After refactor:**
```python
def render_diff_hunks(hunks: list[DiffHunk], lang: str | None = None) -> Gtk.Widget:
    """Render diff hunks as a Gtk.Box. Reusable by diff_card and diff_viewer."""
    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    for hunk in hunks:
        vbox.append(_build_hunk_view(hunk, lang))
    return vbox

def build_file_diff_card(file_diff, on_accept_file=None, on_reject_file=None):
    # header + badges + render_diff_hunks(file_diff.hunks) + action buttons
```

This is a ~30 minute refactor. `_build_hunk_view` and `_build_diff_line` are already modular — we just lift the hunk-loop out of `build_file_diff_card`.

The diff viewer then calls:
```python
diff_widget = render_diff_hunks(file_diff.hunks, lang)
```

Zero duplication. Single source of truth for diff rendering.

### 4. `ui/views/diff_viewer.py` — New Widget

```
┌─────────────────────────────────────────────────┐
│  [← Back]  ui/window.py            [Diff|History]│  Header: back + filename + tab toggle
│  +12 -3 since checkpoint abc1234                 │
├─────────────────────────────────────────────────┤
│                                                  │
│  (render_diff_hunks() output OR history list)    │  Content: reused diff renderer or ListBox
│                                                  │
├─────────────────────────────────────────────────┤
│  [← Revert file to this version]                 │  Action bar (contextual)
└─────────────────────────────────────────────────┘
```

**Diff tab:** Calls `render_diff_hunks(file_diff.hunks, lang)` — same renderer as chat diff cards.

**History tab:** `Gtk.ListBox` populated from `git_ops.file_log()`. Each row: short SHA (monospace), timestamp (relative: "2h ago"), commit message (ellipsized). Clicking a row loads that commit's diff.

**Revert button:** Contextual — only shown when viewing a historical commit (not the current diff). Calls `review_handler.revert_file_to_sha()` (see below).

**Threading:** All git calls on background threads (matching `review_handler.py` pattern). UI updates via `GLib.idle_add()`. Loading spinner shown during git calls.

### 5. Layout — `main_content` Slot (QTR Issues #5, #6, #7)

**Decision: Diff viewer opens in `main_content` (right pane), NOT in the left panel's nested notebook.**

The file tree stays in the left panel. The diff viewer appears in the main content area, following the same pattern as `set_review_bar()` (`main_content.py:884`): insert/remove a widget above the chat notebook.

**New methods on `MainContent`:**

```python
def show_diff_viewer(self, viewer_widget: Gtk.Widget) -> None:
    """Insert diff viewer above the chat notebook. Follows set_review_bar() pattern."""
    # Store reference, insert at top of top_box (above _chat_notebook)
    # Chat notebook remains visible below — PM can see both

def hide_diff_viewer(self) -> None:
    """Remove diff viewer from main_content."""
    # Remove widget, restore normal layout
```

**What happens to existing UI state:**
- **Chat notebook:** Stays visible. Diff viewer is inserted above it, chat moves down. PM doesn't lose chat context.
- **Chat scroll position:** Preserved — we're inserting above, not replacing.
- **Input box:** Untouched. Stays at the bottom. PM can still type.
- **Review bar:** Stays if present. Diff viewer sits between review bar and chat notebook.

**Why not a notebook sub-tab in the left panel?** The left panel's nested notebook (`left_panel.py:210`) has "File Tree" and "Feed" tabs. Adding a "Diff" tab there means the PM can't see the file tree and the diff at the same time — defeating the browse-review use case. Main content insertion keeps the file tree visible.

**Back button:** The diff viewer's "← Back" button calls `main_content.hide_diff_viewer()`. This removes the viewer and restores normal chat layout. The PM is back where they were.

### 6. File Tree Wiring (QTR Issue #1)

**Current** (`ui/window.py:803`):
```python
def _on_project_selected(self, path):
    """Handle file tree selection — no-op; project card clicks route via ProjectHandler."""
    pass
```

**Proposed:**
```python
def _on_project_selected(self, path):
    """Handle file tree selection — open diff viewer for the clicked file."""
    project_path = self._project_handler.get_active_project_path()
    if project_path is None:
        return  # no project open — shouldn't happen (tree only shows in open project)

    # Get checkpoint SHA if review is active
    review_state = self._review_handler.get_state(self._project_handler.get_active_project_name())
    checkpoint_sha = review_state.checkpoint_sha if review_state and review_state.is_active() else None

    # Build and show diff viewer
    viewer = DiffViewer(
        file_path=path,
        project_path=project_path,
        checkpoint_sha=checkpoint_sha,
        on_back=lambda: self._main_content.hide_diff_viewer(),
        on_revert=self._on_revert_from_history,
    )
    self._main_content.show_diff_viewer(viewer)
```

**Note:** `_project_handler.get_active_project_path()` is the correct accessor (`project_handler.py:471`). The v1 proposal's `self._current_project_path` was wrong — that attribute does not exist on `MainWindow`.

### 7. Revert Architecture (QTR Issue #3)

**Decision: New `review_handler.revert_file_to_sha()` method — no session gate, with audit trail.**

**Why not reuse `reject_file()`?**
`reject_file()` (`review_handler.py:426`) has a hard gate: `if state is None or not state.is_active(): return`. It also always reverts to `checkpoint_sha`, ignoring any other SHA. Historical revert needs to work on arbitrary SHAs, with or without an active review session.

**Why not inline in `diff_viewer.py`?**
That would bypass all existing audit/state infrastructure. Bad separation of concerns.

**New method:**

```python
def revert_file_to_sha(self, project_name: str, file_path: str, target_sha: str) -> None:
    """
    Revert a single file to its state at an arbitrary commit SHA.
    Does NOT require an active review session.

    Unlike reject_file() (which reverts to checkpoint_sha and requires active review),
    this method works on any commit in the file's history.
    """
    project_path = self._ph.get_active_project_path()
    if project_path is None:
        return

    session_key = f"project:{project_name}"

    def _do():
        result = git_ops.checkout_paths(project_path, target_sha, [file_path])
        if not result.success:
            self._GLib.idle_add(lambda sk=session_key: self._on_display_text(
                sk, f"⚠ Failed to revert {file_path}: {result.error}"))
            return

        self._GLib.idle_add(lambda sk=session_key: self._on_display_text(
            sk, f"↩ {file_path} reverted to {target_sha[:7]}"))

    threading.Thread(target=_do, daemon=True).start()
```

**Interaction with active review sessions:**

| Scenario | Behavior |
|---|---|
| No active review | Revert works. Posts "↩ file reverted to abc1234" in project chat. |
| Active review, reverting to checkpoint_sha | Works — equivalent to `reject_file()` for that file. |
| Active review, reverting to non-checkpoint SHA | Works, but posts a different message. Does NOT change review state. The checkpoint is unaffected — the file is now at the historical SHA, which may differ from checkpoint. If PM later runs `/reject` (all files), this file reverts to checkpoint, overriding the historical revert. |

**SHA validation:** `target_sha` flows through `git_ops.checkout_paths()` which validates via `_VALID_SHA_RE` (`git_ops.py:44`). No injection risk.

### 8. Post-Revert UX (QTR Concern C)

After revert, the diff viewer:

1. **Clears the historical selection** — returns to "current diff" view
2. **Re-fetches the current diff** — now shows the reverted state vs. checkpoint
3. **Shows a toast:** "Reverted `ui/window.py` to `a6b07d2` (2026-06-22 15:06)"
4. **Does NOT close** — PM stays in the diff viewer to verify the result

If the reverted file now matches checkpoint state → diff shows "No changes to this file."
If the reverted file differs from checkpoint → diff shows the new difference.

---

## Edge Cases

| Case | Handling |
|------|----------|
| File not tracked by git | "File is not tracked by git. No history available." Disable history tab. |
| No review session active (no checkpoint) | Diff against HEAD via `diff_working_tree(path, file)`. |
| File has no changes since checkpoint | "No changes since checkpoint." History tab still available. |
| File is new (untracked) | "New file — not yet committed." No history, no diff. |
| File deleted in working tree | Show the deletion diff (all lines removed). History available. |
| Binary file | "Binary file — diff not available." History available. |
| Revert when no checkpoint active | `revert_file_to_sha()` works without session. Posts audit message. |
| Revert would discard uncommitted changes | Confirmation dialog: "This will discard any uncommitted changes to this file." |
| Very large diff (>1000 lines) | Truncate with "Showing first 1000 lines. Full diff: [copy to clipboard]" |
| Project has no git repo | "Not a git repository." Disable diff and history. |
| No project open | `_on_project_selected` returns early. Cannot happen in practice — file tree only shows inside an open project. |
| `git log --follow` misses renames | Depends on `diff.renames` config (default: true). Reliable for standard workflows. Documented limitation: does not track copies. |

---

## Build Phases

### Phase 0 — Quick Win: File Click → Existing Diff Card (1-2 hours)

**80% of the value in 1-2 hours.** Wire file tree click to show a diff using the *existing* diff card infrastructure. No new widget, no history, no revert.

- Wire `_on_project_selected` → call `diff_file_against_working_tree()` or `diff_working_tree()` → `parse_diff()` → `build_file_diff_card()` → show in main_content via `show_diff_viewer()`
- Add `show_diff_viewer()` / `hide_diff_viewer()` to `main_content.py` (simple insert/remove)
- Add `diff_file_against_working_tree()` to `git_ops.py`
- **Result:** PM clicks file → sees diff immediately. Done.

### Phase 1 — Edit History Timeline (3-4 hours)

- Add `git_ops.file_log()` function
- Extract `render_diff_hunks()` from `diff_card.py`
- Build `diff_viewer.py` with diff tab + history tab
- History tab: `Gtk.ListBox` from `file_log()` results
- Click historical entry → load that commit's diff
- Tests for `file_log()` and history rendering

### Phase 2 — Revert from History (2-3 hours)

- Add `review_handler.revert_file_to_sha()` method
- Add revert button to diff viewer (contextual: only on historical entries)
- Confirmation dialog
- Post-revert UX: clear selection, refresh diff, show toast
- Tests for revert flow (mock `git_ops`)

### Phase 3 — Polish (2-3 hours)

- Keyboard navigation (arrow keys in history list, Enter to select)
- Copy-diff-to-clipboard button
- Loading spinners during git calls
- Error handling for all edge cases

**Total: 8-12 hours** (Phase 0 + 1 + 2 + 3)

---

## Risks

| Risk | Mitigation |
|------|------------|
| `git log --follow` slow on large repos | Cap at 20 entries; background thread. CrabCakes projects are typically <1K commits. |
| Revert breaks project state | Confirmation dialog; single-file only; audit message posted to chat. |
| Diff rendering performance on huge files | Truncate at 1000 lines; `Gtk.Box` append is efficient. |
| File tree click behavior change | Only files open diff viewer; directories still expand/collapse. Double-click required (existing `set_activate_on_single_click(False)`). |
| Historical revert during active review conflicts with checkpoint | Documented: revert changes file to historical SHA; `/reject` would later override to checkpoint. No state corruption — just potential confusion. Toast message clarifies what happened. |
| `render_diff_hunks()` refactor breaks existing diff cards | Extract is purely mechanical (lift loop). Existing `build_file_diff_card` tests validate no regression. |

---

## Dependencies

- No new Python packages
- No new system libraries
- Uses existing GTK4, GitPython, and CrabCakes infrastructure only

---

## Success Criteria

1. PM clicks any file in the file tree → sees its diff within 1 second
2. PM can browse the file's full edit history
3. PM can revert a file to any previous commit version from the history view
4. All existing review flows (`/check`, `/accept`, `/reject`) continue to work unchanged
5. All existing tests pass; new tests cover `file_log()`, `diff_file_against_working_tree()`, `revert_file_to_sha()`, and diff viewer widget
6. Diff rendering uses a single shared codepath (`render_diff_hunks()`) — no duplication between chat cards and diff viewer

---

## Appendix: QTR Issue Resolution

Mapping every QTR finding to where it's addressed in this revision.

| # | Severity | QTR Finding | How Addressed |
|---|----------|-------------|---------------|
| 1 | 🔴 HIGH | `_current_project_path` doesn't exist | **Fixed.** All references replaced with `self._project_handler.get_active_project_path()`. Verified: `project_handler.py:471`. |
| 2 | 🔴 HIGH | `diff_file_against` misses uncommitted changes | **Fixed.** New `diff_file_against_working_tree(path, sha, file)` added to scope. Diff strategy table specifies which function for each state. |
| 3 | 🔴 HIGH | Revert bypasses `reject_file` session gate | **Fixed.** New `review_handler.revert_file_to_sha()` method with explicit architecture decision. Interaction table covers all review-session scenarios. Audit trail preserved via chat message. |
| 4 | 🟠 MED | Diff rendering duplicates `diff_card.py` | **Fixed.** No `Gtk.TextView` renderer. Extracted `render_diff_hunks()` from existing `diff_card.py`. Single codepath. |
| 5 | 🟠 MED | "Replace chat view" under-specified | **Fixed.** Diff viewer inserts above chat notebook via `show_diff_viewer()`, following `set_review_bar()` pattern. Chat stays visible. Input box untouched. Scroll position preserved. |
| 6 | 🟠 MED | Project tab slot ambiguous | **Fixed.** Diff viewer in `main_content` (right pane), NOT in left panel's nested notebook. File tree stays visible for further navigation. Rationale documented. |
| 7 | 🟡 LOW | `show_diff_viewer` doesn't exist | **Addressed.** Method signature specified: `show_diff_viewer(widget)` / `hide_diff_viewer()`. Follows existing `set_review_bar()` insert/remove pattern (`main_content.py:884`). |
| 8 | 🟡 LOW | SHA validation not addressed | **Fixed.** One-liner in `file_log()` section: SHAs from `git log --format=%H` are 40-char hex, pass `_VALID_SHA_RE` (`git_ops.py:44`). No injection vector. |
| A | Note | `--follow` rename detection edge cases | **Documented** in `file_log()` spec. Renames tracked, copies not. Depends on `diff.renames` config (default: true). |
| B | Note | `--follow` walks full history | **Documented.** `-n 20` caps output. Sub-100ms for <1K commit projects. No safeguard needed at current scale. |
| C | Note | Post-revert UX ambiguous | **Specified.** Clear historical selection → refresh current diff → show toast → stay in viewer. |
| D | Note | Phase 4 badges are separate feature | **Moved** to separate proposal. Phase 3 (polish) is keyboard nav, clipboard, spinners only. |
| E | Note | Phase 0 suggestion (quick win) | **Adopted.** Phase 0 added: wire file click → existing `build_file_diff_card`, 1-2 hours, 80% of value. |
| F | Note | `_on_project_selected` misnaming | **Acknowledged** in Out of Scope. Existing misnaming from `left_panel.py:102`. Separate refactor. |
