# FileTree ColumnView Migration — Manual Test Plan

Covers the 15 acceptance criteria from `docs/specs/SPEC-FILETREE-COLUMNVIEW-MIGRATION.md` plus the visual layout changes from this session.

---

## Test 1: Project Open
**Action:** Click Projects tab → select a project → click it.

**Expected:** File tree appears with correct icons (folder/file), green expander arrows on directories, no row spacing gap, project name in header.

---

## Test 2: Directory Expand/Collapse
**Action:** Click the green ▶ arrow on a directory.

**Expected:** Arrow flips to ▼, children appear (files + subdirs), loading spinner shows briefly if slow filesystem. Click ▼ again → children disappear.

**Edge case:** Click two directory arrows in rapid succession. Both should load (or the second wins; re-click the first to recover).

---

## Test 3: File Double-Click → Drawer
**Action:** Double-click a file row (one you've modified).

**Expected:** Drawer slides open below the file row with animation. Top bar shows: `[Diff] [History]        [Revert] [Copy diff]`. The Diff tab is active. Spinner shows briefly, then the diff hunks render.

---

## Test 4: Diff Tab Content
**Action:** With the drawer open, read the diff.

**Expected:** Syntax-highlighted hunks (green background for adds, red for removes, gray for context). At least 3 lines visible. Content scrolls if long.

**Edge cases to try:**
- Open a file with NO changes → "No changes to this file."
- Open a binary file (e.g., `.png`) → "Binary file — not shown"
- Open a file in a directory that doesn't exist → error label, no crash

---

## Test 5: History Tab
**Action:** Click the "History" button.

**Expected:** Stack slides to show commit list (SHA, date, message). 3 rows minimum visible. Each row has a 7-char SHA.

**Edge cases:**
- New file never committed → "No commit history for this file."
- Click History tab twice → only loads once (no duplicate API calls)

---

## Test 6: Historical Diff (click commit)
**Action:** In History tab, click a commit row.

**Expected:** Stack slides back to Diff tab, shows the diff for that commit. The "Revert" button appears (right side of top bar).

---

## Test 7: Revert Flow
**Action:** Click "Revert file to this version."

**Expected:** Confirmation dialog with file path and commit SHA. Click "Yes" → file reverts → diff reloads → revert button hides.

**Edge cases:**
- Click "No" → dialog closes, nothing changes
- After revert, double-click the file again → fresh diff loads

---

## Test 8: Escape Key
**Action:** Open a drawer → press **Esc**.

**Expected:** Drawer animates closed, row removed, focus returns to file tree.

---

## Test 9: Ctrl+C (Copy Diff)
**Action:** Open a drawer with a loaded diff → press **Ctrl+C**.

**Expected:** Diff text copied to clipboard. Paste into a text editor to verify.

**Edge case:** Press Ctrl+C BEFORE diff loads → nothing copied (no silent failure), key event propagates.

---

## Test 10: Enter on History Row
**Action:** Open drawer → History tab → use arrow keys to select a commit → press **Enter**.

**Expected:** Same as clicking the row — loads historical diff.

---

## Test 11: Multiple Drawers
**Action:** Double-click file A → drawer opens. Double-click file B → second drawer opens.

**Expected:** Both drawers visible simultaneously. Closing one doesn't affect the other.

---

## Test 12: Copy Button
**Action:** Click the "Copy diff" button.

**Expected:** Same as Ctrl+C — diff text copied to clipboard.

---

## Test 13: Project Switch
**Action:** Open project A → open a drawer → click Back button → open project B.

**Expected:** Project A's tree and drawers cleared. Project B shows clean tree with no stale drawers or leftover state.

---

## Test 14: Visual Layout (Recent Changes)
**Action:** Open any drawer and inspect the layout.

**Expected:**
- No file icon in the drawer row
- Orange vertical line on left edge
- Drawer fills full row width (not right-justified)
- Buttons: minimal padding (1px), right-justified in top bar
- Diff content: 3 lines minimum, 2px padding
- Click a drawer row → highlight is very subtle (not blinding)
- Green arrows on directory expanders

---

## Test 15: Drawer Close + Reopen
**Action:** Open drawer → close it → open it again.

**Expected:** Diff reloads fresh (not cached from first open). History also reloads.

---

## How to Report Results

For each test, note:
- **PASS** — works as expected
- **FAIL** — describe what actually happened
- **PARTIAL** — works but with caveats (describe them)

Report any visual oddities, crashes, or unexpected behavior.
