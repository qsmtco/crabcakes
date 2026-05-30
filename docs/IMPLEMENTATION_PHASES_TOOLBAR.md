# Chat Input Toolbar — Implementation Phases

**Spec:** `docs/SPEC_CHAT_INPUT_TOOLBAR.md`
**Prompts:** `prompts/steelFramedCodeWriter.md` (builder), `prompts/adversarialDebugger.md` (auditor)
**Supervisor:** Qaster
**Builder:** QTR

---

## Phase 1: utils/spellcheck.py (NEW)
- Pure Python, no GTK, no network
- `check_words(text)` — enchant-2 -l batch subprocess
- `get_suggestions(word)` — enchant-2 -a ispell pipe subprocess
- Exception handling: FileNotFoundError, TimeoutExpired, Exception
- ~90 lines

## Phase 2: ui/handlers/input_toolbar_handler.py (NEW)
- Pure logic handler, no Gtk.* widget imports (Pango/Gdk data types OK)
- Spell check: toggle, debounce (300ms), tag application, suggestions at iter
- Find/Replace: find, find_next, find_prev, replace_current, replace_all, clear
- File I/O: save_to_file, save_as_prompt, load_file, load_prompt
- Word count: get_word_count → (words, chars, tokens)
- Follows MediaHandler pattern: `__init__(main_content, GLib_module)`
- ~280 lines

## Phase 3: ui/views/chat_input_toolbar.py (NEW)
- Pure view widget, no business logic
- Gtk.Box with icon buttons: Save, Open, Find, Replace, Spell toggle, Word count
- Find bar (collapsible): search entry, match count, prev/next, close
- Replace bar: replace entry, Replace, Replace All
- File dialogs: Gtk.FileDialog save/open (pattern from left_panel.py)
- Open Prompt popover: load_prompts() list
- Callbacks set by window.py
- ~250 lines

## Phase 4: Wire into existing files
- `ui/views/main_content.py`: swap ChatControlBar → ChatInputToolbar import, add toolbar property, add buffer-changed signal
- `ui/window.py`: create InputToolbarHandler, wire all callbacks
- `ui/handlers/activity_handler.py`: remove dead update_control_bar call (line 482)
- `ui/styles.py`: add toolbar CSS classes

## Phase 5: Cleanup + docs
- Delete `ui/views/chat_control_bar.py`
- Update `docs/ARCHITECTURE.md` (§2 file tree, §3 module descriptions)
- Full test suite run
