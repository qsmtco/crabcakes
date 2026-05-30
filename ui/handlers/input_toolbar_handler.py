"""InputToolbarHandler — owns all chat input toolbar logic.

Pure logic handler. No GTK widget imports.
All GTK calls dispatched via GLib.idle_add from window.py.
Follows the MediaHandler pattern.

Responsibilities:
- Find/replace state and operations on the input buffer
- Spell check scheduling (300ms debounce) and tag application
- File I/O: save input to file, load file into buffer
- Prompt I/O: save/load from prompts/ directory
- Word/char/token count
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


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
        self._find_matches: list[tuple[int, int]] = []  # (start_offset, end_offset)
        self._find_current = -1  # index into _find_matches
        self._find_text = ""  # current search term

        # Tag references (created once, reused)
        self._spell_tag = None
        self._find_match_tag = None
        self._find_current_tag = None

    # ── Spell Check ───────────────────────────────────────────────────────

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
        Called from the view side on right-click.
        Returns list of suggestion strings (max 8).
        """
        buf = self._mc.user_input.get_buffer()
        word_start = text_iter.copy()
        word_end = text_iter.copy()
        if not word_start.inside_word():
            return []
        word_start.backward_word_start()
        word_end.forward_word_end()
        word = buf.get_text(word_start, word_end, True)
        if not word:
            return []

        from utils.spellcheck import get_suggestions
        return get_suggestions(word)

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
        return False  # don't repeat GLib timeout

    def _apply_spell_tags(self, misspelled: list[str]):
        """Apply Pango.Underline.ERROR tag to misspelled words. Runs on GTK thread."""
        buf = self._mc.user_input.get_buffer()

        # Get or create the spell-error tag (once)
        if self._spell_tag is None:
            from gi.repository import Pango, Gdk
            self._spell_tag = buf.create_tag("spell-error")
            self._spell_tag.set_property("underline", Pango.Underline.ERROR)
            self._spell_tag.set_property("underline-rgba", Gdk.RGBA(1, 0.3, 0.3, 1))  # red

        # Clear all existing spell-error tags first
        buf.remove_tag(self._spell_tag, buf.get_start_iter(), buf.get_end_iter())

        # Find and tag each misspelled word
        full_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        for word in misspelled:
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
            for match in pattern.finditer(full_text):
                ws = buf.get_iter_at_offset(match.start())
                we = buf.get_iter_at_offset(match.end())
                buf.apply_tag(self._spell_tag, ws, we)

    def _clear_spell_tags(self):
        """Remove all spell-error tags from the buffer."""
        buf = self._mc.user_input.get_buffer()
        tag_table = buf.get_tag_table()
        tag = tag_table.lookup("spell-error")
        if tag is not None:
            buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())

    # ── Find / Replace ────────────────────────────────────────────────────

    def find(self, search_text: str) -> tuple[int, int]:
        """Find all occurrences of search_text in the buffer.
        Returns (current_match_index, total_matches).
        Applies find-match/find-current tags and highlights first match.
        """
        self._find_text = search_text
        self._find_matches.clear()
        self._find_current = -1

        if not search_text:
            self._clear_find_tags()
            return (-1, 0)

        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)

        pattern = re.compile(re.escape(search_text), re.IGNORECASE)
        for match in pattern.finditer(text):
            self._find_matches.append((match.start(), match.end()))

        if self._find_matches:
            self._find_current = 0
            if self._GLib:
                self._GLib.idle_add(self._apply_find_tags)
            else:
                self._apply_find_tags()

        return (self._find_current, len(self._find_matches))

    def find_next(self) -> tuple[int, int]:
        """Advance to next match. Returns (current_index, total)."""
        if not self._find_matches:
            return (-1, 0)
        self._find_current = (self._find_current + 1) % len(self._find_matches)
        if self._GLib:
            self._GLib.idle_add(self._apply_find_tags)
        else:
            self._apply_find_tags()
        return (self._find_current, len(self._find_matches))

    def find_prev(self) -> tuple[int, int]:
        """Go to previous match. Returns (current_index, total)."""
        if not self._find_matches:
            return (-1, 0)
        self._find_current = (self._find_current - 1) % len(self._find_matches)
        if self._GLib:
            self._GLib.idle_add(self._apply_find_tags)
        else:
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

    def _apply_find_tags(self):
        """Apply find-match/find-current tags in the buffer. Runs on GTK thread."""
        buf = self._mc.user_input.get_buffer()

        # Get or create tags (once)
        tag_table = buf.get_tag_table()
        if self._find_match_tag is None:
            from gi.repository import Gdk
            self._find_match_tag = buf.create_tag("find-match")
            self._find_match_tag.set_property(
                "background-rgba", Gdk.RGBA(0.39, 0.40, 0.95, 0.25)
            )
        if self._find_current_tag is None:
            from gi.repository import Gdk
            self._find_current_tag = buf.create_tag("find-current")
            self._find_current_tag.set_property(
                "background-rgba", Gdk.RGBA(0.39, 0.40, 0.95, 0.75)
            )

        # Clear existing tags
        buf.remove_tag(self._find_match_tag, buf.get_start_iter(), buf.get_end_iter())
        buf.remove_tag(self._find_current_tag, buf.get_start_iter(), buf.get_end_iter())

        # Apply tags to matches
        for i, (start_off, end_off) in enumerate(self._find_matches):
            start = buf.get_iter_at_offset(start_off)
            end = buf.get_iter_at_offset(end_off)
            tag = self._find_current_tag if i == self._find_current else self._find_match_tag
            buf.apply_tag(tag, start, end)

        # Scroll to current match
        if 0 <= self._find_current < len(self._find_matches):
            start_off, _ = self._find_matches[self._find_current]
            buf.place_cursor(buf.get_iter_at_offset(start_off))

    def _clear_find_tags(self):
        """Remove all find-match/find-current tags."""
        buf = self._mc.user_input.get_buffer()
        tag_table = buf.get_tag_table()
        for tag_name in ("find-match", "find-current"):
            tag = tag_table.lookup(tag_name)
            if tag is not None:
                buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())

    # ── File I/O ─────────────────────────────────────────────────────────

    def save_to_file(self, file_path: str):
        """Save input buffer contents to a file.
        Catches file errors and logs them — caller handles UX feedback.
        """
        try:
            buf = self._mc.user_input.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info("Input saved to %s", file_path)
        except PermissionError:
            logger.error("Permission denied writing to %s", file_path)
        except OSError as e:
            logger.error("Failed to save input to %s: %s", file_path, e)

    def save_as_prompt(self, filename: str):
        """Save input buffer as a .md prompt file in the prompts/ directory.
        filename should NOT include .md extension — it's added automatically.
        """
        from utils.prompts import PROMPTS_DIR
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        path = os.path.join(PROMPTS_DIR, f"{filename}.md")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info("Prompt saved to %s", path)
            return path
        except PermissionError:
            logger.error("Permission denied writing prompt to %s", path)
        except OSError as e:
            logger.error("Failed to save prompt to %s: %s", path, e)
        return None

    def load_file(self, file_path: str):
        """Load file contents and insert at cursor position in input buffer.
        Catches file errors and logs them — caller handles UX feedback.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            self._mc.append_stt_text(text)
            logger.info("Loaded file %s into input buffer", file_path)
        except FileNotFoundError:
            logger.error("File not found: %s", file_path)
        except UnicodeDecodeError:
            logger.error("Cannot read binary file as text: %s", file_path)
        except PermissionError:
            logger.error("Permission denied reading %s", file_path)
        except OSError as e:
            logger.error("Failed to load file %s: %s", file_path, e)

    def load_prompt(self, prompt_name: str):
        """Load a named prompt from the prompts/ directory into the input buffer.
        Appends at cursor position.
        """
        from utils.prompts import PROMPTS_DIR
        path = os.path.join(PROMPTS_DIR, f"{prompt_name}.md")
        if os.path.exists(path):
            self.load_file(path)

    # ── Word Count ────────────────────────────────────────────────────────

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