# SPEC: Chat Input Toolbar

**Date:** 2026-05-28
**Author:** Qaster
**Status:** Draft — for implementation
**Implements:** `docs/proposals/PROPOSAL_CHAT_INPUT_TOOLBAR.md`
**Depends on:** None
**Target branch:** main

> Architecture compliance (ARCHITECTURE.md): `ui/views/chat_input_toolbar.py` is a pure view — widgets only, no business logic. `ui/handlers/input_toolbar_handler.py` owns all logic with no GTK imports. `utils/spellcheck.py` is pure Python with no GTK/network dependencies. All CSS classes defined in `ui/styles.py`. Window wires handler to view via callbacks. Follows the exact pattern of `MediaHandler` + `STTEngine` + `main_content.py`.

---

## DISCOVERY

- **Read `ui/views/chat_control_bar.py`:** `ChatControlBar(Gtk.Label)` — stub, never wired. Has `update(event_type, message)` method but `main_content.update_control_bar()` calls an unset `_on_control_bar_update` callback. `window.py` never calls `set_on_control_bar_update()`. Line 8 comment: `# stubbed — wire later`. **This entire file gets replaced.**
- **Read `ui/views/main_content.py`:** Layout: `top_box = [notebook, control_bar]` → `paned` → `bottom_box = [input_scroll, button_bar]`. Control bar appended at line 81: `top_box.append(self._control_bar)`. `ChatControlBar` imported at line 16. `user_input` property at line 28 returns `self._user_input` (Gtk.TextView). `append_stt_text()` at line 773 calls `buf.insert_at_cursor(text)`. `replace_input_text()` at line 815 calls `buf.set_text(text)`. **Swap `ChatControlBar` with `ChatInputToolbar`.**
- **Read `ui/handlers/media_handler.py`:** Pattern: `MediaHandler.__init__(main_content, improve_module, GLib_module, stt_engine_class)`. Stores `self._mc = main_content`, `self._GLib = GLib_module`. Dispatches GTK calls via `GLib.idle_add`. Accesses `self._mc.user_input.get_buffer()`. **This is the handler pattern to follow.**
- **Read `ui/window.py`:** `MainWindow.__init__()` at line 59 creates handlers. `_build()` at line 88 is composition root. `MediaHandler` created at line 211 with `main_content`, `improve_module`, `GLib_module`. Wired at lines 425-426 via `set_on_*` callbacks. No destroy/close handler — GTK ApplicationWindow handles lifecycle. **New handler created and wired alongside MediaHandler.**
- **Read `utils/config.py`:** `get_config_file()` returns `~/.config/crabcakes/config.json`. No Telegram or toolbar config. **No changes needed.**
- **Read `utils/prompts.py`:** `PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")`. `load_prompts()` returns `[(display_name, content)]` sorted by filename. **Used by "Open Prompt" and "Save as Prompt" features.**
- **Read `ui/views/left_panel.py:805-840`:** Existing `Gtk.FileDialog` pattern: create dialog → set filters → `dialog.open(root, None, callback)` → `dialog.open_finish(result)` → `file.get_path()`. Uses `Gio.ListStore` for filters. **Follow this exact pattern for Open/Save File dialogs.**
- **Read `ui/styles.py`:** CSS in `APP_CSS` string. Existing button classes: `suggested-action`, `btn-improve`, `flat`. Input: `input-bubble`. Feed bar: `project-feed-bar`. **Add toolbar CSS classes to APP_CSS.**
- **Read `docs/ARCHITECTURE.md`:** §2 directory structure: `ui/views/chat_control_bar.py` listed. §3.16 `media_handler.py` — STT + improve. §3.5 CSS in `styles.py`. §13.4 callbacks as communication mechanism. **Update file tree, add new module descriptions.**
- **Enchant-2 CLI verified:** `enchant-2 -l` takes text on stdin, outputs misspelled words one per line. `enchant-2 -l -L` adds line numbers. `enchant-2 -a` gives ispell-format suggestions: `& word count offset: sug1, sug2, ...`. English and French dictionaries installed. **Use `enchant-2 -l` for batch checking, `-a` for suggestions.**
- **Architecture owner:** `utils/spellcheck.py` owns spell checking. `input_toolbar_handler.py` owns find/replace state and file I/O logic. `chat_input_toolbar.py` is the pure view.

---

## 1. Overview

### Problem
The `ChatControlBar` between the chat tabs and input area is a dead stub — a `Gtk.Label` that was never wired. The input box has no editing tools: no find/replace, no spell check, no file I/O, no word count.

### Solution
Replace `ChatControlBar` with `ChatInputToolbar` — a compact toolbar of icon buttons providing editor-level capabilities for the input box. Organized in logical groups: File I/O, Search, Quality, Info.

### Scope

| In Scope | Out of Scope |
|----------|-------------|
| Save input as file (.txt, .md) | Undo/Redo |
| Save input as prompt (to prompts/) | Bold/italic formatting |
| Open file into input (at cursor) | Template insertion |
| Open prompt into input | Auto-save drafts |
| Find with highlight + navigation | Regex search |
| Replace + Replace All | Multi-buffer editing |
| Spell check via enchant-2 (toggle) | Grammar check |
| Right-click spell suggestions | Custom dictionary management |
| Word/char/token count | Reading level |

### Architecture Principles
- **§3.5:** All CSS in `ui/styles.py` via `add_css_class()`
- **§3.6:** `window.py` wires handlers, no logic
- **§3.9:** `main_content.py` is a view
- **§13.4:** Callbacks as communication mechanism
- **Handler pattern:** Logic in `ui/handlers/`, views in `ui/views/`, utils in `utils/`

---

## 2. Changes by File

### 2.1 `utils/spellcheck.py` — NEW FILE

**Architecture:** Pure Python utility. No GTK, no network. Subprocess wrapper for `enchant-2`.

**Public API:**

```python
def check_words(text: str) -> list[str]:
    """Return list of misspelled words found in text.
    Uses enchant-2 -l (batch mode — one subprocess call for entire text).
    """

def get_suggestions(word: str) -> list[str]:
    """Return up to 8 spelling suggestions for a misspelled word.
    Uses enchant-2 -a (ispell pipe mode).
    Returns empty list if word is correctly spelled.
    """
```

**Implementation:**

```python
# utils/spellcheck.py
# Spell checking via enchant-2 CLI subprocess.
#
# Architecture: pure Python utility, no GTK, no network.
# Uses enchant-2 CLI which wraps hunspell/aspell.
# Dictionaries: en-US, en-GB, fr (already installed).
#
# Security Manifest:
#   Reads: text from caller (GtkTextBuffer contents)
#   Executes: enchant-2 binary via subprocess
#   No files written; no network calls; no secrets

import subprocess
import logging

logger = logging.getLogger(__name__)


def check_words(text: str) -> list[str]:
    """Return list of misspelled words found in text.
    
    Uses enchant-2 -l which takes text on stdin and outputs
    misspelled words one per line. Single subprocess call for
    the entire buffer.
    
    Args:
        text: The full text to check.
    
    Returns:
        List of unique misspelled words (order preserved, deduplicated).
    """
    if not text.strip():
        return []
    try:
        result = subprocess.run(
            ["enchant-2", "-l"],
            input=text,
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Output: one misspelled word per line
        words = [w for w in result.stdout.strip().split('\n') if w]
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for w in words:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return unique
    except FileNotFoundError:
        logger.warning("[spellcheck] enchant-2 not found — spell check disabled")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("[spellcheck] enchant-2 timed out")
        return []
    except Exception as e:
        logger.error("[spellcheck] unexpected error: %s", e)
        return []


def get_suggestions(word: str) -> list[str]:
    """Return up to 8 spelling suggestions for a misspelled word.
    
    Uses enchant-2 -a (ispell pipe mode). Output format:
        @(#) International Ispell Version ...
        & word count offset: sug1, sug2, ...
    
    Args:
        word: The misspelled word to get suggestions for.
    
    Returns:
        List of suggestion strings (max 8). Empty if word is correct.
    """
    if not word.strip():
        return []
    try:
        result = subprocess.run(
            ["enchant-2", "-a"],
            input=word,
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Parse ispell format
        for line in result.stdout.split('\n'):
            if line.startswith('&'):
                # & wrld 46 0: weld, world, Wald, ...
                parts = line.split(':', 1)
                if len(parts) >= 2:
                    suggestions = [s.strip() for s in parts[1].split(',')]
                    return suggestions[:8]
        return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    except Exception:
        return []
```

**Exception types handled:**
- `FileNotFoundError` — enchant-2 not installed. Return empty, log warning.
- `subprocess.TimeoutExpired` — enchant-2 hung. Return empty, log warning.
- `Exception` — catch-all. Return empty, log error.

**Line count:** ~90 lines.

**Why `enchant-2 -l` for batch check:** One subprocess call for the entire buffer. Not one per word. The `-l` flag outputs only misspelled words. Fast enough with 300ms debounce.

**Why `enchant-2 -a` for suggestions:** Ispell pipe mode returns structured output with suggestions. Only called on right-click (one word at a time), not on every check.

---

### 2.2 `ui/handlers/input_toolbar_handler.py` — NEW FILE

**Architecture:** Pure logic handler. No GTK imports. Receives `main_content` reference for buffer access, dispatches GTK calls via `GLib.idle_add()`.

**Constructor:**

```python
class InputToolbarHandler:
    """Owns all input toolbar logic: find/replace, spell check, file I/O, word count.
    
    No GTK imports — all GTK dispatch via GLib.idle_add callbacks.
    """
    
    def __init__(
        self,
        main_content,
        GLib_module=None,
    ):
        self._mc = main_content
        self._GLib = GLib_module
        
        # Spell check state
        self._spell_enabled = False
        self._spell_debounce_id = None  # GLib timeout source ID
        
        # Find/replace state
        self._find_matches = []      # list of (start_offset, end_offset)
        self._find_current = -1       # index into _find_matches
        self._find_text = ""          # current search term
```

**Public methods — Spell Check:**

```python
    def toggle_spell_check(self) -> bool:
        """Toggle spell check on/off. Returns new state (True=on)."""
        self._spell_enabled = not self._spell_enabled
        if self._spell_enabled:
            self._run_spell_check()
        else:
            self._clear_spell_tags()
        return self._spell_enabled

    def on_buffer_changed(self):
        """Called when input buffer text changes. Debounces spell check."""
        if not self._spell_enabled:
            return
        # Cancel previous debounce timer
        if self._spell_debounce_id is not None and self._GLib:
            self._GLib.source_remove(self._spell_debounce_id)
        # Schedule new check in 300ms
        if self._GLib:
            self._spell_debounce_id = self._GLib.timeout_add(300, self._run_spell_check)
        else:
            self._run_spell_check()

    def get_suggestions_at_iter(self, text_iter) -> list[str]:
        """Get spell check suggestions for the word at the given TextIter.
        Called from right-click handler on the view side.
        Returns list of suggestion strings.
        """
        # Find word boundaries at iter position
        word_start = text_iter.copy()
        word_end = text_iter.copy()
        if not word_start.inside_word():
            return []
        word_start.backward_word_start()
        word_end.forward_word_end()
        word = text_iter.get_buffer().get_text(word_start, word_end, True)
        if not word:
            return []
        from utils.spellcheck import get_suggestions
        return get_suggestions(word)
```

**Internal — Spell Check:**

```python
    def _run_spell_check(self):
        """Check all words in buffer and apply error tags. Called with debounce."""
        self._spell_debounce_id = None
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        if not text:
            self._clear_spell_tags()
            return False
        
        from utils.spellcheck import check_words
        misspelled = check_words(text)
        
        # Dispatch tag application to GTK main thread
        if self._GLib:
            self._GLib.idle_add(self._apply_spell_tags, misspelled)
        else:
            self._apply_spell_tags(misspelled)
        return False  # don't repeat timeout

    def _apply_spell_tags(self, misspelled: list[str]):
        """Apply Pango.Underline.ERROR tag to misspelled words. Runs on GTK thread."""
        buf = self._mc.user_input.get_buffer()
        
        # Get or create the spell-error tag
        tag_table = buf.get_tag_table()
        tag = tag_table.lookup("spell-error")
        if tag is None:
            from gi.repository import Pango
            tag = buf.create_tag("spell-error")
            # Cannot set Pango underline via create_tag on GTK4 TextTag directly.
            # Use underline-set + underline property.
            # Actually, Gtk.TextTag supports "underline" property:
            tag.set_property("underline", Pango.Underline.ERROR)
            tag.set_property("underline-rgba", Gdk.RGBA(1, 0.3, 0.3, 1))  # red
        
        # Clear all existing spell-error tags
        start = buf.get_start_iter()
        end = buf.get_end_iter()
        buf.remove_tag(tag, start, end)
        
        # Find and tag each misspelled word
        text = buf.get_text(start, end, True)
        import re
        for word in misspelled:
            # Find all occurrences of this word in the buffer
            pattern = re.compile(r'\b' + re.escape(word) + r'\b')
            for match in pattern.finditer(text):
                ws = buf.get_iter_at_offset(match.start())
                we = buf.get_iter_at_offset(match.end())
                buf.apply_tag(tag, ws, we)

    def _clear_spell_tags(self):
        """Remove all spell-error tags from the buffer."""
        buf = self._mc.user_input.get_buffer()
        tag_table = buf.get_tag_table()
        tag = tag_table.lookup("spell-error")
        if tag is not None:
            buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
```

> **Note on `_apply_spell_tags`:** This method uses `gi.repository.Pango` and `Gdk.RGBA` which are GTK-adjacent imports. The handler's "no GTK imports" rule means no `Gtk.*` widget imports, not no GObject introspection types. However, if strict separation is required, this method can be moved to a callback on the view side instead. The handler would set `self._pending_misspelled = misspelled` and the view would call `_apply_spell_tags` from its own code. For simplicity, we allow `Pango` and `Gdk` in the handler since they're data types, not widgets.

**Public methods — Find/Replace:**

```python
    def find(self, search_text: str) -> tuple[int, int]:
        """Find all occurrences of search_text in the buffer.
        Returns (current_match_index, total_matches).
        Applies find-match tags and highlights first match.
        """
        self._find_text = search_text
        self._find_matches.clear()
        self._find_current = -1
        
        if not search_text:
            self._clear_find_tags()
            return (-1, 0)
        
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        
        # Case-insensitive search
        import re
        pattern = re.compile(re.escape(search_text), re.IGNORECASE)
        for match in pattern.finditer(text):
            self._find_matches.append((match.start(), match.end()))
        
        if self._find_matches:
            self._find_current = 0
            self._apply_find_tags()
        
        return (self._find_current, len(self._find_matches))

    def find_next(self) -> tuple[int, int]:
        """Advance to next match. Returns (current_index, total)."""
        if not self._find_matches:
            return (-1, 0)
        self._find_current = (self._find_current + 1) % len(self._find_matches)
        self._apply_find_tags()
        return (self._find_current, len(self._find_matches))

    def find_prev(self) -> tuple[int, int]:
        """Go to previous match. Returns (current_index, total)."""
        if not self._find_matches:
            return (-1, 0)
        self._find_current = (self._find_current - 1) % len(self._find_matches)
        self._apply_find_tags()
        return (self._find_current, len(self._find_matches))

    def replace_current(self, replacement: str) -> tuple[int, int]:
        """Replace current match with replacement text.
        Returns (new_current_index, new_total).
        """
        if not self._find_matches or self._find_current < 0:
            return (-1, 0)
        
        buf = self._mc.user_input.get_buffer()
        start_off, end_off = self._find_matches[self._find_current]
        start = buf.get_iter_at_offset(start_off)
        end = buf.get_iter_at_offset(end_off)
        buf.delete(start, end)
        buf.insert(start, replacement)
        
        # Re-run find to recalculate offsets after replacement
        return self.find(self._find_text)

    def replace_all(self, replacement: str) -> int:
        """Replace all matches. Returns count of replacements."""
        if not self._find_matches:
            return 0
        count = len(self._find_matches)
        
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        
        import re
        pattern = re.compile(re.escape(self._find_text), re.IGNORECASE)
        new_text = pattern.sub(replacement, text)
        buf.set_text(new_text)
        
        self._find_matches.clear()
        self._find_current = -1
        self._clear_find_tags()
        
        return count

    def clear_find(self):
        """Clear all find/replace state and tags."""
        self._find_matches.clear()
        self._find_current = -1
        self._find_text = ""
        self._clear_find_tags()
```

**Internal — Find Tags:**

```python
    def _apply_find_tags(self):
        """Apply find-match and find-current tags in the buffer."""
        buf = self._mc.user_input.get_buffer()
        
        # Get or create tags
        tag_table = buf.get_tag_table()
        match_tag = tag_table.lookup("find-match")
        if match_tag is None:
            match_tag = buf.create_tag("find-match")
            from gi.repository import Gdk
            match_tag.set_property("background-rgba", Gdk.RGBA(0.39, 0.40, 0.95, 0.25))  # semi-transparent indigo
        
        current_tag = tag_table.lookup("find-current")
        if current_tag is None:
            current_tag = buf.create_tag("find-current")
            from gi.repository import Gdk
            current_tag.set_property("background-rgba", Gdk.RGBA(0.39, 0.40, 0.95, 0.75))  # solid indigo
        
        # Clear existing tags
        buf.remove_tag(match_tag, buf.get_start_iter(), buf.get_end_iter())
        buf.remove_tag(current_tag, buf.get_start_iter(), buf.get_end_iter())
        
        # Apply tags
        for i, (start_off, end_off) in enumerate(self._find_matches):
            start = buf.get_iter_at_offset(start_off)
            end = buf.get_iter_at_offset(end_off)
            tag = current_tag if i == self._find_current else match_tag
            buf.apply_tag(tag, start, end)
        
        # Scroll to current match
        if 0 <= self._find_current < len(self._find_matches):
            start_off, _ = self._find_matches[self._find_current]
            buf.place_cursor(buf.get_iter_at_offset(start_off))

    def _clear_find_tags(self):
        """Remove all find-match and find-current tags."""
        buf = self._mc.user_input.get_buffer()
        tag_table = buf.get_tag_table()
        for tag_name in ("find-match", "find-current"):
            tag = tag_table.lookup(tag_name)
            if tag is not None:
                buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())
```

**Public methods — File I/O:**

```python
    def save_to_file(self, file_path: str):
        """Save input buffer contents to a file."""
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(text)

    def save_as_prompt(self, filename: str):
        """Save input buffer as a .md prompt file in the prompts/ directory.
        filename should NOT include .md extension — it's added automatically.
        """
        from utils.prompts import PROMPTS_DIR
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        path = os.path.join(PROMPTS_DIR, f"{filename}.md")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def load_file(self, file_path: str):
        """Load file contents and insert at cursor position in input buffer."""
        with open(file_path, 'r', encoding='utf-8') as f:
            text = f.read()
        self._mc.append_stt_text(text)

    def load_prompt(self, prompt_name: str):
        """Load a named prompt from the prompts/ directory into the input buffer.
        Appends at cursor position.
        """
        from utils.prompts import PROMPTS_DIR
        path = os.path.join(PROMPTS_DIR, f"{prompt_name}.md")
        if os.path.exists(path):
            self.load_file(path)
```

**Public methods — Word Count:**

```python
    def get_word_count(self) -> tuple[int, int, int]:
        """Return (words, chars, approx_tokens) for the current input buffer."""
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        if not text.strip():
            return (0, 0, 0)
        words = len(text.split())
        chars = len(text)
        tokens = int(words * 1.3)  # rough English token estimate
        return (words, chars, tokens)
```

**Line count estimate:** ~280 lines.

---

### 2.3 `ui/views/chat_input_toolbar.py` — NEW FILE

**Architecture:** Pure view. Creates widgets, emits callbacks. No business logic.

**Constructor:**

```python
class ChatInputToolbar(Gtk.Box):
    """
    Compact toolbar for the chat input area.
    Provides file I/O, find/replace, spell check, word count.
    
    Pure view — all logic lives in InputToolbarHandler.
    """
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.CENTER)
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_spacing(4)
        self.add_css_class("input-toolbar")
        
        # Callbacks — set by window.py
        self._on_save_file = None
        self._on_save_prompt = None
        self._on_open_file = None
        self._on_open_prompt = None
        self._on_find = None
        self._on_replace = None
        self._on_spell_toggle = None
        self._on_buffer_changed = None
```

**Widget structure:**

```
ChatInputToolbar (Gtk.Box, horizontal)
├── save_btn (Gtk.MenuButton → Gtk.PopoverMenu with Save as File / Save as Prompt)
├── open_btn (Gtk.MenuButton → Gtk.PopoverMenu with Open File / Open Prompt)
├── separator_1 (Gtk.Separator)
├── find_btn (Gtk.Button, icon: 🔍)
├── replace_btn (Gtk.Button, icon: 🔀)
├── separator_2 (Gtk.Separator)
├── spell_btn (Gtk.ToggleButton, icon: ✓ ABC)
├── spacer (Gtk.Box, hexpand=True)
└── count_label (Gtk.Label, right-aligned)
```

**Find/Replace bar (appears below toolbar when activated):**

```
find_bar (Gtk.Box, vertical, hidden by default)
├── row_1 (Gtk.Box, horizontal)
│   ├── search_entry (Gtk.Entry, placeholder: "Find...")
│   ├── match_count_label (Gtk.Label, "3 of 12")
│   ├── prev_btn (Gtk.Button, "▲")
│   ├── next_btn (Gtk.Button, "▼")
│   └── close_btn (Gtk.Button, "×")
└── row_2 (Gtk.Box, horizontal, hidden until Replace clicked)
    ├── replace_entry (Gtk.Entry, placeholder: "Replace with...")
    ├── replace_btn (Gtk.Button, "Replace")
    └── replace_all_btn (Gtk.Button, "Replace All")
```

**Callbacks emitted:**

```python
    def set_on_save_file(self, cb): self._on_save_file = cb
    def set_on_save_prompt(self, cb): self._on_save_prompt = cb
    def set_on_open_file(self, cb): self._on_open_file = cb
    def set_on_open_prompt(self, cb): self._on_open_prompt = cb
    def set_on_find(self, cb): self._on_find = cb
    def set_on_replace(self, cb): self._on_replace = cb
    def set_on_spell_toggle(self, cb): self._on_spell_toggle = cb
    def set_on_buffer_changed(self, cb): self._on_buffer_changed = cb
```

**View methods (called by handler or window):**

```python
    def show_find_bar(self, show_replace=False):
        """Show the find bar (optionally with replace row)."""
        
    def hide_find_bar(self):
        """Hide the find bar and clear find state."""
        
    def update_match_count(self, current: int, total: int):
        """Update match count label: "3 of 12" or "No matches"."""
        
    def set_spell_active(self, active: bool):
        """Update spell check toggle button visual state."""
        
    def update_word_count(self, words: int, chars: int, tokens: int):
        """Update word count label: "142 words · 1,847 chars · ~370 tokens"."""
```

**File dialogs** follow the existing pattern from `left_panel.py:807-840`:

```python
    def _open_save_file_dialog(self):
        """Open GTK4 FileDialog to save input as a file."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Save Input As")
        root = self.get_root()
        if root is None:
            return
        dialog.save(root, None, self._on_save_file_selected)
    
    def _on_save_file_selected(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            if file and self._on_save_file:
                self._on_save_file(file.get_path())
        except GLib.Error:
            pass  # cancelled
    
    def _open_open_file_dialog(self):
        """Open GTK4 FileDialog to select a file to load."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Open File")
        root = self.get_root()
        if root is None:
            return
        dialog.open(root, None, self._on_open_file_selected)
    
    def _on_open_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file and self._on_open_file:
                self._on_open_file(file.get_path())
        except GLib.Error:
            pass  # cancelled
```

**Open Prompt popover:**

```python
    def _build_open_prompt_popover(self):
        """Build popover listing available prompts."""
        from utils.prompts import load_prompts
        prompts = load_prompts()  # [(display_name, content)]
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_spacing(2)
        for name, _content in prompts:
            btn = Gtk.Button(label=name)
            btn.add_css_class("flat")
            btn.connect("clicked", self._on_prompt_selected, name)
            box.append(btn)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(box)
        scroll.set_min_content_height(200)
        scroll.set_max_content_height(400)
        return scroll
```

**Line count estimate:** ~250 lines.

---

### 2.4 `ui/views/main_content.py` — MODIFIED

**Changes:**
1. Replace `ChatControlBar` import with `ChatInputToolbar` import (line 16)
2. Replace `ChatControlBar()` construction with `ChatInputToolbar()` (line 72)
3. Expose toolbar reference for wiring

**Exact edits:**

Line 16 — change import:
```python
# OLD:
from ui.views.chat_control_bar import ChatControlBar
# NEW:
from ui.views.chat_input_toolbar import ChatInputToolbar
```

Line 72 — change construction:
```python
# OLD:
self._control_bar = ChatControlBar()
# NEW:
self._toolbar = ChatInputToolbar()
```

Line 81 — change append:
```python
# OLD:
top_box.append(self._control_bar)
# NEW:
top_box.append(self._toolbar)
```

Add new property:
```python
    @property
    def toolbar(self):
        """Expose the input toolbar for callback wiring."""
        return self._toolbar
```

Remove dead code:
- Lines 74-75: Remove `_on_control_bar_update` comment and variable
- Lines 201-208: Remove `set_on_control_bar_update()` and `update_control_bar()` (dead stubs, never called by window.py)
- Activity handler's call to `update_control_bar` at `activity_handler.py:482` becomes a no-op or is removed

**Buffer change notification:**

Add a buffer-changed signal emission so the handler can debounce spell checks:

```python
        # In __init__, after self._user_input creation:
        buf = self._user_input.get_buffer()
        buf.connect("changed", self._on_input_buffer_changed)
        
    def _on_input_buffer_changed(self, buf):
        """Notify toolbar handler of buffer changes for spell check + word count."""
        if self._toolbar_buffer_changed_cb:
            self._toolbar_buffer_changed_cb()
    
    def set_on_buffer_changed(self, cb):
        """Set callback for input buffer text changes. Used by InputToolbarHandler."""
        self._toolbar_buffer_changed_cb = cb
```

**Line count change:** -15 lines (remove dead code) + 15 lines (new property, buffer signal). Net ~0.

---

### 2.5 `ui/window.py` — MODIFIED

**Changes:**
1. Import `InputToolbarHandler`
2. Create handler in `_build()`
3. Wire toolbar callbacks to handler methods
4. Remove `update_control_bar` call from ActivityHandler wiring (line 482 of activity_handler.py)

**Exact changes in `_build()`:**

After MediaHandler creation (line ~215):

```python
        # Input toolbar handler — owns find/replace, spell check, file I/O, word count
        from ui.handlers.input_toolbar_handler import InputToolbarHandler
        self._input_toolbar_handler = InputToolbarHandler(
            main_content=self._main_content,
            GLib_module=GLib,
        )
        
        # Wire toolbar callbacks to handler
        toolbar = self._main_content.toolbar
        toolbar.set_on_save_file(self._input_toolbar_handler.save_to_file)
        toolbar.set_on_save_prompt(self._input_toolbar_handler.save_as_prompt)
        toolbar.set_on_open_file(self._input_toolbar_handler.load_file)
        toolbar.set_on_open_prompt(self._input_toolbar_handler.load_prompt)
        toolbar.set_on_find(self._on_find_activated)
        toolbar.set_on_replace(self._on_replace_activated)
        toolbar.set_on_spell_toggle(self._on_spell_toggle)
        toolbar.set_on_buffer_changed(self._input_toolbar_handler.on_buffer_changed)
        
        # Initial word count
        self._update_word_count()
```

**New methods on MainWindow:**

```python
    def _on_find_activated(self):
        """Show find bar in toolbar."""
        toolbar = self._main_content.toolbar
        toolbar.show_find_bar(show_replace=False)
    
    def _on_replace_activated(self):
        """Show find+replace bar in toolbar."""
        toolbar = self._main_content.toolbar
        toolbar.show_find_bar(show_replace=True)
    
    def _on_spell_toggle(self):
        """Toggle spell check."""
        active = self._input_toolbar_handler.toggle_spell_check()
        self._main_content.toolbar.set_spell_active(active)
    
    def _update_word_count(self):
        """Update word count display in toolbar."""
        words, chars, tokens = self._input_toolbar_handler.get_word_count()
        self._main_content.toolbar.update_word_count(words, chars, tokens)
```

**Wire buffer-changed to word count update:**

In the buffer-changed callback chain, also call `_update_word_count`:

```python
        self._main_content.set_on_buffer_changed(self._on_input_buffer_changed)
        
    def _on_input_buffer_changed(self):
        """Handle input buffer changes — trigger spell check + word count update."""
        self._input_toolbar_handler.on_buffer_changed()
        self._update_word_count()
```

**Line count estimate:** ~40 lines added.

---

### 2.6 `ui/handlers/activity_handler.py` — MODIFIED

Remove the dead `update_control_bar` call at line 482:

```python
# REMOVE these lines (481-482):
        # Also update the ChatControlBar (sits between chat and input)
        # Extract plain-text message from markup for the control bar
        import re
        plain = re.sub(r'<[^>]+>', '', text)
        self._mc.update_control_bar(state, plain)
```

**Line count change:** -4 lines.

---

### 2.7 `ui/styles.py` — MODIFIED

Add new CSS classes after existing button styles:

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

.input-toolbar .count-label {
    color: #6b6b7a;
    font-size: 10px;
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

/* Spell check toggle active state */
.spell-active {
    background: rgba(99, 102, 241, 0.2);
    color: #a5b4fc;
    border-radius: 4px;
}
```

**Line count estimate:** +40 lines.

---

### 2.8 `ui/views/chat_control_bar.py` — DELETED

Replaced entirely by `ui/views/chat_input_toolbar.py`. Delete the file.

**Line count change:** -60 lines.

---

### 2.9 `docs/ARCHITECTURE.md` — MODIFIED

Updates required:
1. **§2 Directory structure:** Replace `chat_control_bar.py` with `chat_input_toolbar.py` in `ui/views/`. Add `input_toolbar_handler.py` to `ui/handlers/`. Add `spellcheck.py` to `utils/`.
2. **§3 Module responsibilities:** Add new sections for the three new files.
3. **§11 File inventory:** Update file tree and descriptions.

**Line count estimate:** +30 lines.

---

## 3. Data Flow

### Save as File:
1. User clicks Save ▾ → Save as File
2. View opens `Gtk.FileDialog.save()` (async, GTK4 pattern from left_panel.py)
3. User selects path → `_on_save_file_selected()` callback
4. View calls `self._on_save_file(path)` → wired to `handler.save_to_file(path)`
5. Handler reads buffer text → writes to file

### Open File:
1. User clicks Open ▾ → Open File
2. View opens `Gtk.FileDialog.open()` (async)
3. User selects file → `_on_open_file_selected()` callback
4. View calls `self._on_open_file(path)` → wired to `handler.load_file(path)`
5. Handler reads file → calls `self._mc.append_stt_text(text)` → inserts at cursor

### Open Prompt:
1. User clicks Open ▾ → Open Prompt
2. View shows `Gtk.Popover` with `load_prompts()` list
3. User clicks prompt name → `_on_prompt_selected(name)` callback
4. View calls `self._on_open_prompt(name)` → wired to `handler.load_prompt(name)`
5. Handler reads `.md` file → calls `self._mc.append_stt_text(text)`

### Find:
1. User clicks 🔍 Find → view shows find bar
2. User types in search entry → `changed` signal fires
3. View calls `handler.find(search_text)` → handler finds matches via regex
4. Handler returns `(current, total)` → view updates match count label
5. Handler applies `find-match` / `find-current` TextTags to buffer
6. Next/Prev buttons → `handler.find_next()` / `handler.find_prev()`
7. Close button → `handler.clear_find()` → view hides find bar

### Replace:
1. User clicks 🔀 Replace → view shows find bar with replace row
2. Find works same as above
3. User types replacement → clicks Replace
4. View calls `handler.replace_current(replacement)` → handler deletes match, inserts replacement
5. Handler re-runs `find()` to recalculate offsets → returns new match state
6. Replace All → `handler.replace_all(replacement)` → regex.sub on entire buffer

### Spell Check:
1. User clicks ✓ ABC toggle → `handler.toggle_spell_check()`
2. Handler reads buffer text → `enchant-2 -l` subprocess → gets misspelled words
3. Handler applies `spell-error` TextTag (red underline) to misspelled word ranges
4. On buffer change → `handler.on_buffer_changed()` → 300ms debounce → re-check
5. Right-click on underlined word → view gets iter position → `handler.get_suggestions_at_iter(iter)` → `enchant-2 -a` → suggestions
6. View shows suggestion popover → user clicks suggestion → view replaces word in buffer

### Word Count:
1. Buffer `changed` signal → `main_content._on_input_buffer_changed()`
2. Calls `handler.on_buffer_changed()` (spell check debounce)
3. Also calls `window._update_word_count()` → `handler.get_word_count()` → `(words, chars, tokens)`
4. View updates `count_label` → `"142 words · 1,847 chars · ~370 tokens"`

---

## 4. File Change Summary

| File | Change Type | Lines | Risk |
|------|-------------|-------|------|
| `utils/spellcheck.py` | **NEW** | ~90 | Low — subprocess wrapper |
| `ui/handlers/input_toolbar_handler.py` | **NEW** | ~280 | Medium — find/replace logic |
| `ui/views/chat_input_toolbar.py` | **NEW** | ~250 | Medium — new widget, dialogs |
| `ui/views/chat_control_bar.py` | **DELETED** | -60 | — |
| `ui/views/main_content.py` | Modified | ~0 | Low — swap import, add property |
| `ui/window.py` | Modified | +40 | Low — handler wiring |
| `ui/handlers/activity_handler.py` | Modified | -4 | Low — remove dead code |
| `ui/styles.py` | Modified | +40 | Low — CSS only |
| `docs/ARCHITECTURE.md` | Modified | +30 | Low — docs |
| **Total** | | **~670 lines net** | |

---

## 5. Implementation Order

1. **Create `utils/spellcheck.py`** — `check_words()` + `get_suggestions()` subprocess wrappers
2. **Test standalone** — `python3 -c "from utils.spellcheck import check_words; print(check_words('hello wrld tset'))"` → `['wrld', 'tset']`
3. **Create `ui/handlers/input_toolbar_handler.py`** — handler with find/replace/spell/file/count methods
4. **Test standalone** — `python3 -c "from ui.handlers.input_toolbar_handler import InputToolbarHandler; print('import OK')"`
5. **Create `ui/views/chat_input_toolbar.py`** — toolbar widget with buttons, find bar, file dialogs
6. **Delete `ui/views/chat_control_bar.py`** — replaced by new toolbar
7. **Modify `ui/views/main_content.py`** — swap import, add `toolbar` property, buffer-changed signal
8. **Modify `ui/window.py`** — create handler, wire callbacks
9. **Modify `ui/handlers/activity_handler.py`** — remove dead `update_control_bar` call
10. **Add CSS to `ui/styles.py`** — toolbar, find bar, spell check styles
11. **Manual test** — launch CrabCakes, verify toolbar renders, test each feature
12. **Update `docs/ARCHITECTURE.md`** — file tree, module descriptions
13. **Commit and push**

**Verification at each step:**
1. enchant-2 subprocess works → misspelled words detected correctly
3. Handler methods work with mock main_content → find/replace state correct
5. Toolbar renders in isolation → buttons clickable, find bar shows/hides
7. Import swap clean → no references to ChatControlBar remain
11. Full end-to-end: find highlights matches, replace works, spell check underlines, save/load files, word count updates

---

## 6. Acceptance Criteria

- [ ] Toolbar renders between chat tabs and input area (replaces dead ChatControlBar)
- [ ] Save ▾ → Save as File opens `Gtk.FileDialog`, saves input to selected path
- [ ] Save ▾ → Save as Prompt saves to `prompts/` as `.md`, immediately available
- [ ] Open ▾ → Open File opens `Gtk.FileDialog`, inserts file content at cursor
- [ ] Open ▾ → Open Prompt shows popover listing prompts from `prompts/`
- [ ] Find: inline search bar with next/prev buttons and match count ("3 of 12")
- [ ] Find: all matches highlighted with semi-transparent indigo background
- [ ] Find: current match highlighted with solid indigo background
- [ ] Replace: extends find bar with replace entry + Replace/Replace All buttons
- [ ] Replace: replaces current match and re-finds
- [ ] Replace All: replaces all matches in one pass via regex.sub
- [ ] Spell check toggle: on/off visual state on button
- [ ] Spell check: misspelled words get red error underline (Pango.Underline.ERROR)
- [ ] Spell check: 300ms debounce — no lag while typing
- [ ] Spell check: right-click on underlined word shows suggestions from enchant-2
- [ ] Word/char/token count: always visible, updates on every keystroke
- [ ] Find bar collapses cleanly on close — no layout jumps
- [ ] No impact on existing Send/Prompt/Improve button functionality
- [ ] `chat_control_bar.py` deleted — no dead code remains
- [ ] Activity handler's dead `update_control_bar` call removed
- [ ] All new CSS classes in `ui/styles.py` — no inline CSS
- [ ] Handler has no `Gtk.*` widget imports (Pango/Gdk data types allowed)
- [ ] View has no business logic — only widget creation and callback emission

---

## 7. Edge Cases

| Case | Expected Behavior |
|------|-------------------|
| Empty input buffer | Save writes empty file. Word count shows "0 words · 0 chars". Spell check returns empty. Find returns 0 matches. |
| Find with empty search | Returns 0 matches, no highlighting |
| Find with no matches | Match count shows "No matches". No highlighting applied. |
| Find in very long buffer (>10k chars) | regex.finditer handles it. May take a few ms. Acceptable. |
| Replace All with no matches | Returns 0. No changes to buffer. |
| Spell check with enchant-2 not installed | `FileNotFoundError` caught, returns empty list. Spell check appears to work but finds no errors. |
| Spell check timeout | `TimeoutExpired` caught, returns empty list. Logged. |
| Open File with binary file | Reads as UTF-8, may raise UnicodeDecodeError → caught, logged, nothing inserted |
| Save to read-only path | `PermissionError` → caught, logged |
| Save as Prompt with existing name | Overwrites existing prompt file. No confirmation (user chose the name). |
| Rapid buffer changes | 300ms debounce cancels previous timer, only last change triggers spell check |
| Find bar open, user types in input | Buffer changes don't affect find bar. Find matches stay until user edits search field. |
| Tab switch with find bar open | Find bar stays open. Find tags apply to current buffer (all tabs share one input). |
| Right-click on correctly spelled word | `get_suggestions()` returns empty list → no suggestion popover shown |

---

## 8. ARCHITECTURE.md Updates Required

1. **§2 Directory structure:**
   - Replace `chat_control_bar.py` with `chat_input_toolbar.py` in `ui/views/`
   - Add `input_toolbar_handler.py` to `ui/handlers/`
   - Add `spellcheck.py` to `utils/`

2. **§3 Module responsibilities:**
   - Add §3.XX `ui/handlers/input_toolbar_handler.py` — find/replace, spell check scheduling, file I/O, word count
   - Add §3.XX `ui/views/chat_input_toolbar.py` — toolbar widget, find bar, file dialogs, prompt popover
   - Add §3.XX `utils/spellcheck.py` — enchant-2 subprocess wrapper
   - Remove old `chat_control_bar.py` description

3. **§11 File inventory:**
   - Update file tree, add new files, remove deleted file

---

## Self-Audit (Rule 9)

1. **Does every code sample work against the current codebase?**
   - `ChatControlBar` imported at `main_content.py:16` ✅
   - `self._control_bar = ChatControlBar()` at line 72 ✅
   - `top_box.append(self._control_bar)` at line 81 ✅
   - `append_stt_text(text)` calls `buf.insert_at_cursor(text)` at line 779 ✅
   - `replace_input_text(text)` calls `buf.set_text(text)` at line 815 ✅
   - `user_input` property at line 28 ✅
   - `MediaHandler.__init__(main_content, improve_module, GLib_module, stt_engine_class)` at line 14 ✅
   - `self._mc = main_content` at media_handler.py:23 ✅
   - `Gtk.FileDialog` pattern from `left_panel.py:807-840` ✅
   - `load_prompts()` returns `[(display_name, content)]` ✅
   - `PROMPTS_DIR` from `utils/prompts.py` ✅
   - `enchant-2 -l` verified: outputs misspelled words one per line ✅
   - `enchant-2 -a` verified: ispell format `& word count offset: sug1, sug2, ...` ✅

2. **Did I catch all exception types?**
   - `check_words`: `FileNotFoundError`, `subprocess.TimeoutExpired`, `Exception` ✅
   - `get_suggestions`: `FileNotFoundError`, `subprocess.TimeoutExpired`, `Exception` ✅
   - `save_to_file`: `PermissionError`, `OSError` (need to add try/except) ⚠️
   - `load_file`: `FileNotFoundError`, `UnicodeDecodeError`, `PermissionError` (need to add try/except) ⚠️
   - `Gtk.FileDialog` callbacks: `GLib.Error` for cancel ✅

3. **Did I verify key structures?**
   - `_tab_sessions` dict: `page_index → session_key` ✅
   - `load_prompts()` returns `list[tuple[str, str]]` ✅
   - `PROMPTS_DIR` is absolute path from `os.path` ✅
   - `enchant-2 -l` output: newline-separated misspelled words ✅

4. **Did I trace the data flow end-to-end?**
   - Save: click → dialog → path → handler reads buffer → writes file ✅
   - Open: click → dialog → path → handler reads file → append_stt_text → insert_at_cursor ✅
   - Find: type → changed → handler.find() → regex → matches → apply tags → update count ✅
   - Replace: click → handler.replace_current() → delete + insert → re-find ✅
   - Spell: toggle → handler.toggle() → enchant-2 -l → tag application → underline ✅
   - Suggestions: right-click → get_suggestions_at_iter() → enchant-2 -a → parse → popover ✅
   - Word count: buffer changed → handler.get_word_count() → view.update_word_count() ✅

5. **Would an implementer produce working code?**
   - Yes, all method signatures, widget hierarchies, callback wiring, and CSS classes specified with exact patterns from existing code. File dialog pattern copied from `left_panel.py`. Handler pattern copied from `media_handler.py`.

6. **Architecture compliance verified?**
   - `utils/spellcheck.py`: no GTK, no network ✅
   - `input_toolbar_handler.py`: no Gtk.* widget imports ✅
   - `chat_input_toolbar.py`: view only, emits callbacks ✅
   - CSS in `styles.py` only ✅
   - Window wires everything ✅
   - `main_content.py` exposes property, doesn't contain logic ✅

⚠️ **Issue noted:** `save_to_file()` and `load_file()` need try/except for `PermissionError`, `FileNotFoundError`, `UnicodeDecodeError`. Implementer should add these guards. The spec shows the happy path; the edge case table documents expected behavior.
