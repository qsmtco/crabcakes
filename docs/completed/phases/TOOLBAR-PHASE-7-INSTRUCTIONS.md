# TOOLBAR-PHASE-7-INSTRUCTIONS.md

PHASE 7 of 7 — CSS + ARCHITECTURE docs + finalize

This is the final phase. The code is complete from Phases 1–6. This phase adds the visual styling for the new toolbar and updates the project documentation to reflect the final state.

## Master Spec

`docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md`:

- **Section 2.7** (`ui/styles.py` — MODIFIED) — the exact CSS block to add
- **Section 2.9** (`docs/ARCHITECTURE.md` — MODIFIED) — the exact changes needed

## Files to change

1. **`ui/styles.py`** — add input-toolbar CSS to `APP_CSS`
2. **`docs/ARCHITECTURE.md`** — remove two `chat_control_bar.py` references from the file tree

## Edits (in order)

### Edit 1: `ui/styles.py` — add input-toolbar CSS

Read the file first (`sed -n '1095,1105p' ui/styles.py`) to confirm the exact end of `APP_CSS`. The CSS block goes **inside** the `APP_CSS` string, right before the closing `"""` at line 1103.

Insert this exact block **between** the existing last rule (`.settings-empty-state { ... }`) and the closing `"""`:

```css
/* -- Input toolbar ------------------------------------------------------ */
.input-toolbar {
    background: rgba(17, 17, 20, 0.6);
    border-radius: 6px;
    min-height: 28px;
    padding: 2px 4px;
}

.input-toolbar button,
.input-toolbar .flat {
    min-width: 28px;
    min-height: 24px;
    padding: 2px 6px;
    font-size: 11px;
}

.input-toolbar .toolbar-separator {
    margin: 2px 4px;
    opacity: 0.3;
}

/* Find bar */
.find-bar {
    background: rgba(17, 17, 20, 0.8);
    border-radius: 4px;
    padding: 4px 8px;
}

.find-bar entry {
    min-width: 200px;
    font-size: 11px;
}

.find-bar .char-count {
    color: #6b6b7a;
    font-size: 10px;
}

/* Spell check toggle active state */
.spell-active {
    background: rgba(99, 102, 241, 0.2);
    color: #a5b4fc;
    border-radius: 4px;
}
```

The block is copied verbatim from spec §2.7. Do not reformat or rephrase it.

### Edit 2: `docs/ARCHITECTURE.md` — remove two `chat_control_bar.py` lines

Read the file first (`sed -n '128,135p' docs/ARCHITECTURE.md`) to confirm line 131. Then remove this line:

```
│       ├── chat_control_bar.py # ChatControlBar — planned stub (update() not wired)
```

Then read the file again (`sed -n '3130,3136p' docs/ARCHITECTURE.md`) to confirm line 3132. Then remove this line:

```
│       ├── chat_control_bar.py   # ~58 lines — ChatControlBar (stub — update() not wired)
```

**Do not touch any other line in ARCHITECTURE.md.** Do not update module descriptions, do not rewrite the §3 prose. Only remove these two lines.

## Verification Commands (run all of these)

```bash
cd /home/q/projects/crabcakes

# 1. CSS block is present
echo "=== .input-toolbar CSS present (should be 1) ==="
grep -c "\.input-toolbar" ui/styles.py

echo "=== .find-bar CSS present (should be 1) ==="
grep -c "\.find-bar" ui/styles.py

echo "=== .spell-active CSS present (should be 1) ==="
grep -c "\.spell-active" ui/styles.py

# 2. No chat_control_bar.py in ARCHITECTURE.md file tree
echo "=== chat_control_bar.py in ARCHITECTURE.md (should be 0) ==="
grep -c "chat_control_bar\.py" docs/ARCHITECTURE.md

# 3. chat_input_toolbar.py still referenced correctly
echo "=== chat_input_toolbar.py in ARCHITECTURE.md (should be 2) ==="
grep -c "chat_input_toolbar\.py" docs/ARCHITECTURE.md

# 4. App imports cleanly
xvfb-run -a python3 -c "from ui.window import MainWindow; print('imports OK')"

# 5. App launches with no Gtk-CRITICAL
G_DEBUG=fatal-criticals xvfb-run -a python3 -c "
import sys; sys.path.insert(0, '/home/q/projects/crabcakes')
from ui.window import MainWindow
m = MainWindow(application=None)
m.present()
import time; time.sleep(2)
print('launch OK')
"

# 6. Run targeted toolbar tests
xvfb-run -a python3 -m pytest tests/test_chat_input_toolbar.py tests/test_input_toolbar_handler.py tests/test_spellcheck.py -q --tb=short 2>&1 | tail -10
```

## Rules

- **Use the [steelFramedCodeWriter](../../prompts/steelFramedCodeWriter.md) prompt at `prompts/steelFramedCodeWriter.md`**
- Read each file BEFORE editing to confirm the exact text
- Do NOT touch any file other than the two listed
- Do NOT add any new functionality — this is a polish phase
- Do NOT rewrite ARCHITECTURE.md module descriptions or §3 prose — only remove the two `chat_control_bar.py` lines
- The CSS block from spec §2.7 must be inserted verbatim — do not reformat

## What to report back

- The diff for each of the 2 files
- The output of all 6 verification commands
- The COMPLETENESS checklist (see below)
- Any related issues found (do NOT silently fix them)

## Related-Bug Scan (per steelFramedCodeWriter Step 6.6)

After completing the 2 edits, scan for any remaining `chat_control_bar` or `ChatControlBar` references anywhere in the codebase (not just `ui/` and `tests/`). List any that remain — they are in documentation/proposals and are out of scope for this phase, but should be flagged.

Also scan `ui/styles.py` for any duplicate CSS class definitions (e.g., if `.input-toolbar` was already defined somewhere else in the file). If duplicates exist, list them.

## COMPLETENESS Checklist (mandatory)

```
COMPLETENESS:
- [x/not done] Edit 1: added input-toolbar CSS to ui/styles.py — evidence: grep + diff
- [x/not done] Edit 2: removed 2 chat_control_bar.py lines from docs/ARCHITECTURE.md — evidence: grep + diff
- [x/not done] .input-toolbar CSS present — evidence: grep -c
- [x/not done] .find-bar CSS present — evidence: grep -c
- [x/not done] .spell-active CSS present — evidence: grep -c
- [x/not done] chat_control_bar.py in ARCHITECTURE.md = 0 — evidence: grep -c
- [x/not done] chat_input_toolbar.py in ARCHITECTURE.md = 2 — evidence: grep -c
- [x/not done] App imports cleanly — evidence: python3 output
- [x/not done] App launches with no Gtk-CRITICAL — evidence: G_DEBUG output
- [x/not done] Targeted toolbar tests pass — evidence: pytest output
- [x/not done] No files modified other than the 2 listed — evidence: git diff --stat
- [x/not done] Related issues scanned and reported — evidence: yes/no
```

## Important Reminders

- The word marker for this delegation is: **"please write"**
- You are operating from the authorized crabcakes CLI channel
- This is the FINAL phase — after this, write the post-mortem
- Maximum 15 lines edited before re-reading
