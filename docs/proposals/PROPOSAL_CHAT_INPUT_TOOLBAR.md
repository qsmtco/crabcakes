# PROPOSAL: Chat Input Toolbar

**Date:** 2026-05-28
**Author:** Qaster
**Status:** ~~Proposal — pending Captain approval~~ **APPROVED & SHIPPED** (Phases 1-9, 2026-06-12). See `docs/post-mortems/2026-06-12-CHAT-INPUT-TOOLBAR-PHASES-1-7-POST-MORTEM.md`.

> **Historical note (2026-06-12):** The references to `ChatControlBar` / `chat_control_bar.py` in this proposal describe the stubbed label that was replaced by `ChatInputToolbar`. The proposal's diagnosis (dead bar, no wiring) and the planned replacement (`ChatInputToolbar`) are accurate. The actual implementation followed the proposal's spec with minor adjustments documented in `docs/specs/SPEC_CHAT_INPUT_TOOLBAR.md`.

> **Status (verified 2026-06-12):** ✅ **DONE** — 
> **status:** `DONE` — sortable tag for `ls | grep STATUS` Fully shipped. Phases 1–9 merged to `origin/main` on 2026-06-12. All features in the proposal are implemented: find/replace, spell check toggle, word count, char count, token estimate, activity indicator. `ChatInputToolbar` replaced `ChatControlBar`. `ChatControlBar` code removed (Phase 6 cleanup). Dead `set_on_buffer_changed` setter removed (Phase 9). `_control_bar` → `_toolbar` rename + public property (Phase 10). Full post-mortem at `docs/post-mortems/2026-06-12-CHAT-INPUT-TOOLBAR-PHASES-1-7-POST-MORTEM.md`.
**Priority:** Medium
**Effort:** ~6-8 hours

---

## Why

### The Problem
The chat input box in CrabCakes is a bare `Gtk.TextView`. It works for typing, but that's it. When you're working with long prompts, iterating on agent instructions, or composing multi-paragraph messages, you're in a raw text field with no tools.

Real workflows hit these friction points daily:

1. **No find/replace.** You write a long prompt, realize you used the wrong variable name throughout, and have to manually scan and fix each one. In a real editor, this is Ctrl+H. In CrabCakes, it's squinting and hoping.

2. **No spell check.** Dictated text from STT or the future Telegram input has typos. You spot "connction" in a 500-word prompt and now you're clicking through the text trying to find it again after fixing it.

3. **No file I/O.** You compose a great prompt in the input box and want to save it as a reusable system prompt. Right now: copy, open terminal, create file, paste. Should be one button. Same in reverse — loading a prompt file means copy-pasting from an editor.

4. **No text stats.** How long is this prompt? How many tokens are you about to send? You don't know until you send it and see the response.

5. **The bar is dead space.** There's already a `ChatControlBar` (a `Gtk.Label`) sitting between the notebook and the input area. It was stubbed out as "Chat Control Bar" placeholder text and never wired to anything. It's completely blank. This dead space should be doing work.

### The Solution
Replace the stubbed `ChatControlBar` label with a proper input toolbar — a compact horizontal bar of icon buttons that give the input box editor-level capabilities. Not a full word processor, just the essentials that make text editing efficient.

**The bar is already there, already positioned exactly where a toolbar should be.** We're transforming dead space into something genuinely useful.

### Why Now
- The `ChatControlBar` is a stub — literally says "stubbed — wire later" in the comments
- The Telegram Remote Input feature (spec written) will dump STT text into the input box, making editing tools more valuable
- The input box is becoming a more important editing surface as CrabCakes handles longer prompts and multi-agent workflows
- The `enchant-2` library is already installed on the system with English and French dictionaries — spell check infrastructure exists

---

## What

### Before (current)
A blank `Gtk.Label` showing nothing, positioned between the chat tabs and the input area. The input box is a bare `Gtk.TextView` with no editing tools.

### After (proposed)
A compact toolbar bar with icon buttons organized in logical groups:

```
[💾 Save ▾] [📂 Open ▾] | [🔍 Find] [🔀 Replace] | [✓ ABC] | [142 words · 1,847 chars]
```

**Button groups:**

| Group | Buttons | Purpose |
|-------|---------|---------|
| **File I/O** | Save ▾, Open ▾ | Save input to file/prompt, load file/prompt into input |
| **Search** | Find, Replace | Find text in buffer, find and replace with inline fields |
| **Quality** | Spell Check (toggle) | Underline misspelled words, right-click for suggestions |
| **Info** | Word/char count | Passive label — always visible, updates on every keystroke |

### Feature Details

**Save ▾ (dropdown menu):**
- **Save as File** — opens `Gtk.FileDialog` to save input text as `.txt` or `.md`
- **Save as Prompt** — saves to `prompts/` directory as a `.md` file, instantly available in the Prompts tab

**Open ▾ (dropdown menu):**
- **Open File** — opens `Gtk.FileDialog` to load a file's contents into the input box (appended at cursor)
- **Open Prompt** — shows a popover listing prompts from the Prompts tab, click to load into input

**Find:**
- Opens an inline search bar below the toolbar
- Text field + next/prev buttons + match count
- Highlights matches in the buffer using a `Gtk.TextTag` with background color
- Enter to jump to next match, Shift+Enter for previous
- Escape or click away to close

**Replace:**
- Extends the Find bar with a second text field and Replace/Replace All buttons
- Same match highlighting as Find
- Replace: replaces current match and jumps to next
- Replace All: replaces all matches in one pass

**Spell Check:**
- Toggle button — on/off state with visual indicator
- When enabled: underlines misspelled words using `enchant-2` CLI (already installed)
- Right-click on underlined word shows suggestion popover
- Uses `enchant-2 -l` to check words and `enchant-2 -a` for suggestions
- Runs on every text change (debounced 300ms to avoid lag)

**Word/Char Count:**
- Passive `Gtk.Label` on the right side of the toolbar
- Updates on every buffer change
- Format: `"142 words · 1,847 chars"`
- Also shows approximate token count: `"142 words · 1,847 chars · ~370 tokens"` (tokens ≈ words × 1.3 for English)

---

## Technical Design

### Spell Check Architecture

**Why `enchant-2` CLI (not pyenchant, not libspelling):**

| Option | Available? | Pros | Cons |
|--------|-----------|------|------|
| `pyenchant` Python binding | ❌ Not installed | Direct API | Requires pip install + venv |
| `libspelling` (GTK4) | ❌ Not installed | Native GTK4 integration | Not in Ubuntu repos for GTK4 |
| `GSpell` (GTK3) | ✅ Installed | Proven library | GTK3 only — doesn't work with GTK4 |
| **`enchant-2` CLI** | ✅ Installed | Zero deps, already works, dictionaries installed | Subprocess call, slightly slower |

`enchant-2` is the pragmatic choice. It's already installed with English and French dictionaries. We call it as a subprocess, parse the output, and apply text tags. The 300ms debounce means we're not spawning processes on every keystroke — only after the user pauses typing.

**How it works:**
1. User types → buffer changes → 300ms debounce timer starts
2. Timer fires → extract all words from buffer → pipe to `enchant-2 -l` → get list of misspelled words
3. Clear previous spell-check tags → apply `Gtk.TextTag` (red underline `Pango.Underline.ERROR`) to misspelled word ranges
4. Right-click on tagged word → extract word → pipe to `enchant-2 -a` → parse suggestions → show popover

**Why not check every word individually:** `enchant-2 -l` takes the entire text on stdin and outputs only misspelled words with line/column info. One subprocess call for the whole buffer, not one per word. Fast enough with the debounce.

### Find/Replace Architecture

**Find bar widget:**
When activated, an inline `Gtk.Box` appears below the toolbar containing:
- Search entry (`Gtk.Entry`)
- Match count label (`"3 of 12"`)
- Previous/Next buttons
- Close button (×)

The find bar is a child of the toolbar container, not a separate window. It slides in when Find is clicked and collapses when closed.

**Match highlighting:**
- `Gtk.TextTag` named `"find-match"` with `background: "#6366f140"` (semi-transparent indigo)
- Current match gets `"find-current"` with `background: "#6366f1"` (solid indigo)
- On search: clear all tags → find all matches → apply `"find-match"` → apply `"find-current"` to active match
- Next/Prev buttons cycle the `"find-current"` tag through matches

**Replace bar:**
Extends the find bar with an additional row:
- Replace entry (`Gtk.Entry`)
- Replace button (replaces current match)
- Replace All button (replaces all matches)

### File I/O Architecture

**Save:**
- `Gtk.FileDialog` (GTK4 async API) for "Save as File"
- Direct file write for "Save as Prompt" — saves to `prompts/` directory, auto-generates filename from first line of text
- Both use standard file I/O — no new dependencies

**Open:**
- `Gtk.FileDialog` for "Open File" — reads file, inserts at cursor position (same `buf.insert_at_cursor()` pattern)
- `Gtk.Popover` with `Gtk.ListView` for "Open Prompt" — lists prompts from `utils/prompts.py`, click to load

---

## Architecture Compliance

**Per ARCHITECTURE.md:**

| Rule | Compliance |
|------|-----------|
| §3.5 CSS in `ui/styles.py` only | ✅ All new CSS classes defined in `styles.py`. Views use `add_css_class()` only. |
| §3.6 `window.py` wires handlers | ✅ Window creates toolbar handler and wires callbacks. No logic in window. |
| §3.9 `main_content.py` is a view | ✅ MainContent exposes `user_input` property. Toolbar handler operates on the buffer. |
| `ui/views/` = views only | ✅ New `chat_input_toolbar.py` is a pure view — creates widgets, emits callbacks. |
| `ui/handlers/` = logic, no GTK | ✅ New `input_toolbar_handler.py` owns find/replace/spell logic, no GTK imports. |
| `utils/` = pure Python, no GTK | ✅ Spell check utility in `utils/spellcheck.py` — pure subprocess wrapper, no GTK. |
| Handler pattern (§3.16) | ✅ Handler receives dependencies via setters. Window wires everything. |

### File Responsibilities

**New files:**
- `ui/views/chat_input_toolbar.py` — Pure view. Builds toolbar widgets, emits callbacks for button clicks.
- `ui/handlers/input_toolbar_handler.py` — Pure logic. Owns find/replace state, spell check scheduling, file I/O. No GTK imports.
- `utils/spellcheck.py` — Pure Python. Subprocess wrapper for `enchant-2`. No GTK, no network.

**Modified files:**
- `ui/views/chat_control_bar.py` — Removed (replaced by `chat_input_toolbar.py`), OR repurposed as a re-export. Cleaner to replace.
- `ui/views/main_content.py` — Swap `ChatControlBar` import to `ChatInputToolbar`. Wire toolbar to handler.
- `ui/window.py` — Create `InputToolbarHandler`, wire to `MainContent`.
- `ui/styles.py` — New CSS classes for toolbar buttons, find bar, spell check underlines.

---

## Scope

| In Scope | Out of Scope |
|----------|-------------|
| Save input as file (.txt, .md) | Undo/Redo (Gtk.TextView can enable this independently) |
| Save input as prompt (to prompts/) | Bold/italic formatting (we send plain text) |
| Open file into input (at cursor) | Template insertion |
| Open prompt into input | Auto-save drafts |
| Find with highlighting and navigation | Regex search (future enhancement) |
| Replace + Replace All | Multi-file editing |
| Spell check via enchant-2 (toggle) | Grammar check |
| Right-click spell suggestions | Custom dictionary management |
| Word/char/token count | Reading level estimation |
| Clear input button | Version history |

---

## File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `ui/views/chat_input_toolbar.py` | **NEW** | ~200 | Medium — new widget, layout |
| `ui/handlers/input_toolbar_handler.py` | **NEW** | ~180 | Medium — find/replace logic, spell check |
| `utils/spellcheck.py` | **NEW** | ~60 | Low — subprocess wrapper |
| `ui/views/chat_control_bar.py` | **DELETED** | -60 | Low — removing dead stub |
| `ui/views/main_content.py` | Modified | ~20 | Low — swap import, wire toolbar |
| `ui/window.py` | Modified | ~25 | Low — create handler, wire callbacks |
| `ui/styles.py` | Modified | ~30 | Low — new CSS classes |
| `docs/ARCHITECTURE.md` | Modified | ~40 | Low — docs update |
| **Total** | | **~495 lines net** | |

---

## Acceptance Criteria

- [ ] Toolbar appears between chat tabs and input area (replaces dead `ChatControlBar`)
- [ ] Save ▾ dropdown: "Save as File" opens file dialog and saves input text
- [ ] Save ▾ dropdown: "Save as Prompt" saves to `prompts/` as `.md`
- [ ] Open ▾ dropdown: "Open File" opens file dialog and inserts content at cursor
- [ ] Open ▾ dropdown: "Open Prompt" shows popover of available prompts
- [ ] Find: inline search bar with next/prev navigation and match count
- [ ] Find: all matches highlighted in the buffer with distinct current-match style
- [ ] Replace: extends find bar with replace field + Replace/Replace All buttons
- [ ] Replace All: replaces all matches in one pass
- [ ] Spell check toggle: on/off with visual state
- [ ] Spell check: misspelled words underlined in red (Pango.Underline.ERROR)
- [ ] Spell check: right-click on misspelled word shows suggestions
- [ ] Spell check: 300ms debounce — no lag while typing
- [ ] Word/char/token count: always visible, updates on every keystroke
- [ ] All toolbar buttons have hover effects matching existing button styles
- [ ] Find bar collapses cleanly when closed — no layout jumps
- [ ] No impact on send/prompt/improve button functionality below the input
- [ ] Follows ARCHITECTURE.md: view/handler separation, CSS in styles.py, no cross-layer imports

---

## Future Enhancements (Not In Scope)

1. **Regex search** — Allow regex patterns in find field
2. **Undo/Redo** — Enable `Gtk.TextView` built-in undo stack
3. **Custom dictionaries** — "Add to dictionary" for project-specific terms
4. **Template insertion** — Quick-insert common prompt structures
5. **Auto-save drafts** — Periodically save input buffer to temp file
6. **Keyboard shortcuts** — Ctrl+F for find, Ctrl+H for replace, Ctrl+S for save

---

## Why This Is The Right Scope

This is the "minimum lovable toolbar" — enough features to genuinely improve the daily workflow without overbuilding. Find/replace alone saves minutes per editing session. Spell check catches STT errors. File I/O bridges the gap between the input box and the file system. Word count gives awareness.

The bar is already there, sitting empty. This proposal fills it with tools that make the input box feel like a real editing surface instead of a raw text field.
