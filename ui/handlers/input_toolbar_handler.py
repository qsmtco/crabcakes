# ui/handlers/input_toolbar_handler.py
# Owns all input toolbar logic: find/replace, spell check, file I/O, word count.
#
# Architecture: no Gtk.* widget imports.
# All GTK dispatch via GLib.idle_add.
# Pattern copied from MediaHandler.

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Find / replace state
# ---------------------------------------------------------------------------


class InputToolbarHandler:
    """Owns all input toolbar logic: find/replace, spell check, file I/O, word count.

    No GTK imports — all GTK dispatch via GLib.idle_add callbacks.
    Follows the same pattern as MediaHandler.
    """

    def __init__(
        self,
        main_content,
        GLib_module=None,
    ):
        self._mc = main_content
        self._GLib = GLib_module

        # -- Spell check --------------------------------------------------------
        self._spell_enabled = False
        self._spell_debounce_id = None  # GLib timeout source ID

        # -- Find / replace ------------------------------------------------------
        self._find_matches: list[tuple[int, int]] = []  # (start_offset, end_offset)
        self._find_current = -1
        self._find_text = ""

        # -- Find tag handles (kept in sync with the buffer's tag table) ----------
        self._find_match_tag = None
        self._find_current_tag = None
        self._spell_error_tag = None

    # -------------------------------------------------------------------------
    # Spell check — public
    # -------------------------------------------------------------------------

    def toggle_spell_check(self) -> bool:
        """Toggle spell check on/off. Returns new state (True=on)."""
        self._spell_enabled = not self._spell_enabled
        if self._spell_enabled:
            self._run_spell_check()
        else:
            self._clear_spell_tags()
        return self._spell_enabled

    def on_buffer_changed(self):
        """Called when input buffer text changes. Debounces spell check at 300 ms."""
        if not self._spell_enabled:
            return
        if self._spell_debounce_id is not None and self._GLib:
            self._GLib.source_remove(self._spell_debounce_id)
            self._spell_debounce_id = None
        if self._GLib:
            self._spell_debounce_id = self._GLib.timeout_add(
                300, self._run_spell_check
            )
        else:
            self._run_spell_check()

    def get_suggestions_at_iter(self, text_iter) -> list[str]:
        """Get spell suggestions for the word at the given TextIter.

        Called from the view's right-click handler.
        Returns list of suggestion strings (max 8).
        """
        # Find word boundaries around the iter position
        word_start = text_iter.copy()
        word_end = text_iter.copy()
        if not word_start.inside_word():
            return []
        word_start.backward_word_start()
        word_end.forward_word_end()
        buf = text_iter.get_buffer()
        word = buf.get_text(word_start, word_end, True)
        if not word:
            return []
        from utils.spellcheck import get_suggestions

        return get_suggestions(word)

    def replace_word_at_iter(self, text_iter, replacement: str) -> None:
        """Replace the word at *text_iter* with *replacement*.

        Finds word boundaries around text_iter, deletes the word, and inserts
        *replacement* in its place. After replacement, re-runs spell check if
        enabled so the underline is removed from the corrected word.

        Args:
            text_iter:  Gtk.TextIter — any iter inside the word to replace.
            replacement: str — the corrected word text.
        """
        word_start = text_iter.copy()
        word_end = text_iter.copy()
        if not word_start.inside_word():
            return
        word_start.backward_word_start()
        word_end.forward_word_end()
        buf = self._mc.user_input.get_buffer()
        buf.delete(word_start, word_end)
        buf.insert(word_start, replacement)
        # Re-run spell check to update tags (removes underline if word is now correct)
        if self._spell_enabled:
            self._run_spell_check()

    # -------------------------------------------------------------------------
    # Spell check — internal
    # -------------------------------------------------------------------------

    def _run_spell_check(self):
        """Run spell check against the full buffer text. Schedules tag application."""
        self._spell_debounce_id = None
        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        if not text.strip():
            if self._GLib:
                self._GLib.idle_add(self._clear_spell_tags)
            else:
                self._clear_spell_tags()
            return False

        from utils.spellcheck import check_words

        misspelled = check_words(text)
        if self._GLib:
            self._GLib.idle_add(self._apply_spell_tags, misspelled)
        else:
            self._apply_spell_tags(misspelled)
        return False

    def _apply_spell_tags(self, misspelled: list[str]):
        """Apply spell-error underline to all misspelled words. Runs on GTK thread."""
        buf = self._mc.user_input.get_buffer()

        # Import GTK types here so the module can be imported without GTK present
        import gi
        gi.require_version("Pango", "1.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Pango, Gdk

        tag_table = buf.get_tag_table()
        tag = self._spell_error_tag
        if tag is None:
            tag = buf.create_tag("spell-error")
            tag.set_property("underline", Pango.Underline.ERROR)
            rgba = Gdk.RGBA()
            rgba.parse("rgba(255,77,77,1)")
            tag.set_property("underline-rgba", rgba)
            self._spell_error_tag = tag
        else:
            # Remove existing tags first
            buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())

        if not misspelled:
            return

        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        for word in misspelled:
            # Find every occurrence of this word (case-insensitive)
            for match in re.finditer(r"\b" + re.escape(word) + r"\b", text, re.IGNORECASE):
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

    # -------------------------------------------------------------------------
    # Find / replace — public
    # -------------------------------------------------------------------------

    def find(self, search_text: str) -> tuple[int, int]:
        """Find all occurrences of *search_text* in the buffer.

        Returns (current_match_index, total_matches).
        Applies find-match / find-current TextTags.
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
        """Replace current match with *replacement*. Returns (new_index, new_total)."""
        if not self._find_matches or self._find_current < 0:
            return (-1, 0)

        buf = self._mc.user_input.get_buffer()
        start_off, end_off = self._find_matches[self._find_current]
        start = buf.get_iter_at_offset(start_off)
        end = buf.get_iter_at_offset(end_off)
        buf.delete(start, end)
        buf.insert(start, replacement)

        # Re-run find to recalculate offsets after the replacement
        return self.find(self._find_text)

    def replace_all(self, replacement: str) -> int:
        """Replace all matches. Returns count of replacements made."""
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

    # -------------------------------------------------------------------------
    # Find / replace — internal
    # -------------------------------------------------------------------------

    def _apply_find_tags(self):
        """Apply find-match / find-current tags in the buffer. Runs on GTK thread."""
        buf = self._mc.user_input.get_buffer()
        import gi
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        tag_table = buf.get_tag_table()

        # Get or create find-match tag (semi-transparent indigo)
        match_tag = self._find_match_tag
        if match_tag is None:
            match_tag = buf.create_tag("find-match")
            rgba_match = Gdk.RGBA()
            rgba_match.parse("rgba(99,102,241,0.25)")
            match_tag.set_property("background-rgba", rgba_match)
            self._find_match_tag = match_tag

        # Get or create find-current tag (solid indigo)
        current_tag = self._find_current_tag
        if current_tag is None:
            current_tag = buf.create_tag("find-current")
            rgba_current = Gdk.RGBA()
            rgba_current.parse("rgba(99,102,241,0.75)")
            current_tag.set_property("background-rgba", rgba_current)
            self._find_current_tag = current_tag

        # Clear existing tags
        buf.remove_tag(match_tag, buf.get_start_iter(), buf.get_end_iter())
        buf.remove_tag(current_tag, buf.get_start_iter(), buf.get_end_iter())

        # Apply tags to each match
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
        """Remove all find-match and find-current tags from the buffer."""
        buf = self._mc.user_input.get_buffer()
        tag_table = buf.get_tag_table()
        for tag_name in ("find-match", "find-current"):
            tag = tag_table.lookup(tag_name)
            if tag is not None:
                buf.remove_tag(tag, buf.get_start_iter(), buf.get_end_iter())

    # -------------------------------------------------------------------------
    # File I/O — public
    # -------------------------------------------------------------------------

    def save_to_file(self, file_path: str) -> bool:
        """Save input buffer contents to *file_path*.

        Returns True on success, False on error.
        """
        try:
            buf = self._mc.user_input.get_buffer()
            text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except PermissionError:
            logger.error("Permission denied writing: %s", file_path)
            return False
        except OSError as e:
            logger.error("OS error writing %s: %s", file_path, e)
            return False

    def save_as_prompt(self, filename: str) -> str | None:
        """Save input buffer as a .md prompt in the prompts/ directory.

        *filename* must NOT include the .md extension.
        Returns the absolute path on success, None on error.
        """
        from utils.prompts import PROMPTS_DIR

        buf = self._mc.user_input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        path = os.path.join(PROMPTS_DIR, f"{filename}.md")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return path
        except PermissionError:
            logger.error("Permission denied writing prompt: %s", path)
            return None
        except OSError as e:
            logger.error("OS error writing prompt %s: %s", path, e)
            return None

    def load_file(self, file_path: str) -> bool:
        """Load *file_path* and insert its contents at cursor in the input buffer.

        Returns True on success, False on error.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            self._mc.append_stt_text(text)
            return True
        except UnicodeDecodeError:
            logger.warning("Cannot load binary file as text: %s", file_path)
            return False
        except FileNotFoundError:
            logger.warning("File not found: %s", file_path)
            return False
        except PermissionError:
            logger.warning("Permission denied reading: %s", file_path)
            return False
        except OSError as e:
            logger.warning("OS error reading %s: %s", file_path, e)
            return False

    def load_prompt(self, prompt_name: str) -> bool:
        """Load a named prompt from the prompts/ directory into the input buffer.

        Appends at cursor position.
        Returns True on success, False if the prompt was not found.
        """
        from utils.prompts import PROMPTS_DIR

        path = os.path.join(PROMPTS_DIR, f"{prompt_name}.md")
        if os.path.isfile(path):
            return self.load_file(path)
        logger.warning("Prompt not found: %s", path)
        return False

    # -------------------------------------------------------------------------
    # Word count — public
    # -------------------------------------------------------------------------

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

    def compute_count(self) -> tuple[int, int, int]:
        """Public alias for get_word_count() — used by the wiring layer
        (window.py) to push the count to the toolbar view on every
        buffer change. Kept separate from get_word_count() so the
        existing unit tests at tests/test_input_toolbar_handler.py
        keep passing without modification."""
        return self.get_word_count()