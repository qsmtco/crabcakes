# TOOLBAR-PHASE-6-INSTRUCTIONS.md

PHASE 6 of 7 — Remove dead `ChatControlBar` code path

This is the cleanup phase. Phases 1–5 created the new `ChatInputToolbar` (and its handler + view), swapped it into `main_content.py`, and wired the callbacks in `window.py`. The old `ChatControlBar` code path is now dead. This phase removes it.

## Master Spec

The authoritative spec is `docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md`. Specifically:

- **Section 2.4** (`ui/views/main_content.py` — MODIFIED) — describes the dead-code removals in `main_content.py` (lines 74-75, 201-208)
- **Section 2.6** (`ui/handlers/activity_handler.py` — MODIFIED) — describes the dead-code removal at line 482 in the spec (which is line 603 in the current file — line drift since the spec was written)
- **Section 2.8** (`ui/views/chat_control_bar.py` — DELETED) — file is replaced by `chat_input_toolbar.py`, delete it

## Files to change

1. **`ui/handlers/activity_handler.py`** — remove 4-line block at lines 599-606 (the dead call into the old control bar)
2. **`ui/views/main_content.py`** — remove 2-line attribute block at lines 74-75 and the 8-line method block at lines 201-208
3. **`ui/views/chat_control_bar.py`** — DELETE the file

## Edits (in order)

### Edit 1: `ui/handlers/activity_handler.py` lines 599-606

Read the file first (`sed -n '595,610p' ui/handlers/activity_handler.py`) to confirm the exact text. Then remove this 4-line block (it currently sits inside the `_render_state_label`-style method that ends with `self._feedbar.set_status_text(text)`):

```python
        # Also update the ChatControlBar (sits between chat and input)
        # Extract plain-text message from markup for the control bar
        import re
        plain = re.sub(r'<[^>]+>', '', text)
        self._mc.update_control_bar(state, plain)
```

Note: the local `import re` goes away with this block. The `text` variable above is used by the preceding `set_status_text` call, so do NOT touch anything above or below this block.

### Edit 2: `ui/views/main_content.py` lines 74-75

Remove these two lines:

```python
        # Control bar is updated by ActivityHandler via set_on_control_bar_update()
        self._on_control_bar_update: callable | None = None
```

### Edit 3: `ui/views/main_content.py` lines 201-208

Read the file first (`sed -n '195,215p' ui/views/main_content.py`) to confirm exact text. Then remove the `set_on_control_bar_update` and `update_control_bar` methods (approximately 8 lines). The block looks like:

```python
    def set_on_control_bar_update(self, cb: "Callable[[str, str], None]") -> None:
        ...

    def update_control_bar(self, event_type: str, message: str) -> None:
        ...
        # Phase 4: ChatInputToolbar replaces ChatControlBar. The toolbar is now
        ...
```

Delete the entire block, including the trailing blank line.

### Edit 4: `ui/views/chat_control_bar.py` — DELETE the file

```bash
git rm ui/views/chat_control_bar.py
```

(Use `git rm` so the deletion is staged for commit, not `trash` and not `rm`.)

## Verification Commands (run all of these)

```bash
cd /home/q/projects/crabcakes

# 1. Old name must be gone (expect 0)
echo "=== ChatControlBar (should be 0) ==="
grep -rn "ChatControlBar" --include="*.py" ui/ tests/ 2>&1 | wc -l

# 2. Dead call must be gone (expect 0)
echo "=== update_control_bar calls (should be 0) ==="
grep -rn "update_control_bar" --include="*.py" ui/ tests/ 2>&1 | wc -l

# 3. Dead setter must be gone (expect 0)
echo "=== set_on_control_bar_update (should be 0) ==="
grep -rn "set_on_control_bar_update" --include="*.py" ui/ tests/ 2>&1 | wc -l

# 4. Dead attribute must be gone (expect 0)
echo "=== _on_control_bar_update (should be 0) ==="
grep -rn "_on_control_bar_update" --include="*.py" ui/ tests/ 2>&1 | wc -l

# 5. File must be gone
ls -la ui/views/chat_control_bar.py 2>&1   # expect "No such file"

# 6. ChatInputToolbar still wired correctly
echo "=== ChatInputToolbar wiring (should show window.py + main_content.py) ==="
grep -rn "ChatInputToolbar\|_control_bar" --include="*.py" ui/ 2>&1 | head -10

# 7. App imports cleanly
xvfb-run -a python3 -c "from ui.window import MainWindow; print('imports OK')"

# 8. App launches with no Gtk-CRITICAL (fatal-criticals would crash on any)
G_DEBUG=fatal-criticals xvfb-run -a python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
from ui.window import MainWindow
m = MainWindow(application=None)
m.present()
import time; time.sleep(2)
print('launch OK')
"

# 9. Full test suite
xvfb-run -a python3 -m pytest tests/ -q --tb=short 2>&1 | tail -20
```

## Rules

- **Use the [steelFramedCodeWriter](../../prompts/steelFramedCodeWriter.md) prompt at `prompts/steelFramedCodeWriter.md`**
- Read each file BEFORE editing to confirm the exact text (line numbers in this doc may have drifted)
- Maximum 15 lines edited before re-reading
- Do NOT touch any file other than the three listed
- Do NOT rename `_control_bar` to `_toolbar` — that's a deviation from the spec but the rename is out of scope for this phase. Flag it in the COMPLETENESS checklist as a related issue.
- Do NOT add the buffer-changed signal wiring — that's Phase 7
- Do NOT touch docs/ARCHITECTURE.md — that's Phase 7
- Do NOT touch ui/styles.py — that's Phase 7

## What to report back

- The diff for each of the 3 files
- The output of all 9 verification commands
- The COMPLETENESS checklist (see below)
- Any related issues found (do NOT silently fix them)

## Related-Bug Scan (per steelFramedCodeWriter Step 6.6)

After completing the 3 edits, scan adjacent code in each file for the same dead-code pattern. Specifically:

- In `activity_handler.py`, scan for any other method that still calls `self._mc.update_control_bar` or imports `re` purely for the control bar's `re.sub(r'<[^>]+>', '', text)` — if any survive, list them.
- In `main_content.py`, scan for any other reference to `chat_control_bar`, `control_bar_update`, or `set_on_control_bar` — if any survive, list them.

Report these as "Related issue found, not fixed in this phase" — do NOT fix them.

## COMPLETENESS Checklist (mandatory)

End your response with this block, filled in:

```
COMPLETENESS:
- [x/not done] Edit 1: removed 4-line block from activity_handler.py:599-606 — evidence: grep + diff
- [x/not done] Edit 2: removed 2-line attribute from main_content.py:74-75 — evidence: grep + diff
- [x/not done] Edit 3: removed 2 methods from main_content.py:201-208 — evidence: grep + diff
- [x/not done] Edit 4: deleted ui/views/chat_control_bar.py — evidence: ls + git status
- [x/not done] ChatControlBar references = 0 — evidence: grep -c
- [x/not done] update_control_bar references = 0 — evidence: grep -c
- [x/not done] set_on_control_bar_update references = 0 — evidence: grep -c
- [x/not done] _on_control_bar_update references = 0 — evidence: grep -c
- [x/not done] App imports cleanly — evidence: python3 output
- [x/not done] App launches with no Gtk-CRITICAL — evidence: G_DEBUG output
- [x/not done] Full test suite passes — evidence: pytest output
- [x/not done] No files modified other than the 3 listed — evidence: git diff --stat
- [x/not done] Related issues scanned and reported — evidence: yes/no
```

## Important Reminders

- The word marker for this delegation is: **"please write"**
- You are operating from the authorized crabcakes CLI channel
- Maximum 15 lines edited before re-reading
- This is a CLEANUP phase — no new features, no new signals, no new tests
