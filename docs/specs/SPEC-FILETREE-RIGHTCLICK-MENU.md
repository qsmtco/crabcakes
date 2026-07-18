# File Tree Right-Click Context Menu — Implementation Spec

**Source:** Investigation report by Supervisor (read-only audit of prompts-tab reference impl).
**Target:** `ui/views/file_tree.py` (+ `tests/test_file_tree_columnview.py`).
**Reference impl:** `ui/views/left_panel.py` lines 762–987 (prompts-tab "Copy path" / "Copy prompt" popover menu).

## Goal

Right-click on a file or folder row in the file tree shows a popover menu with:
- **"Copy Path"** — always shown (files and directories).
- **"Copy File"** — shown ONLY when the row is a file (not a directory, not a drawer).

The popover must look and behave exactly like the prompts-tab right-click menu.

---

## CRITICAL Correctness Constraint (read first)

`Gtk.ColumnView` **recycles** `FileTreeRowWidget` instances via `Gtk.SignalListItemFactory`.
The same widget is rebound to different `FileTreeRow` model data on every scroll/expand/collapse.

**DO NOT capture the model row in a gesture closure.** That produces stale-row references
(the exact bug class of BUG #2's stale-position issue, already fixed for the expander).
Instead: attach the `GestureClick` **once** in `FileTreeFactory._on_setup`, and read
`widget._bound_row` **live at click time** inside the handler.

---

## Reference Implementation (Prompts Tab — `ui/views/left_panel.py`)

| Piece | Lines | Role |
|---|---|---|
| Gesture attach | 762–764 | `Gtk.GestureClick()` + `set_button(Gdk.BUTTON_SECONDARY)` per row |
| `_on_prompt_row_right_click` | 866–923 | Builds `Gtk.Popover` + `Gtk.ListBox` of menu rows; each row carries `_action` attr |
| `_on_prompt_menu_row_activated` | 925–944 | Reads `_action` (not label text — i18n-robust), dispatches, `popover.popdown()` |
| `_on_copy_prompt_path` / `_on_copy_prompt_content` | 946–960 | Read row attrs, call `_copy_text_to_clipboard`, call `_show_prompt_copy_status` |
| `_copy_text_to_clipboard` | 962–967 | `Gdk.Display.get_default().get_clipboard().set(text)` |
| `_show_prompt_copy_status` | 970–987 | Sets transient header label ~2.5s via `GLib.timeout_add`, cancels prior source |

Copy the menu-build structure, the `_action`-dispatch pattern, and the popover lifecycle
(`popover.connect("closed", lambda *_: popover.unparent())`) verbatim.

---

## Insertion Points in `ui/views/file_tree.py`

### A. Gesture attach — `FileTreeFactory._on_setup` (currently lines 181–185)

```python
def _on_setup(self, factory, list_item):
    widget = FileTreeRowWidget()
    list_item.set_child(widget)
```

Add a right-click gesture here. Wire it to `self._tree._on_tree_row_right_click(widget)`.

### B. Handler + menu methods on `FileTree` (add near line 1620, after `_on_back_clicked`)

- `_on_tree_row_right_click(self, widget)`:
  - Read `row = widget._bound_row`. Bail if `None`.
  - Bail if `row.props.is_drawer` (drawer rows are inline containers, not files).
  - Bail if `not row.props.full_path` (loading rows at lines 844/1434 have empty paths).
  - Build `Gtk.Popover` parented to `widget` (mirror `_on_prompt_row_right_click`).
  - Always add "Copy Path" row with `_action = "copy_path"`.
  - Add "Copy File" row with `_action = "copy_file"` ONLY when `not row.props.is_dir`.
  - Connect `row-activated` to `_on_tree_menu_row_activated`.
  - `popover.connect("closed", lambda *_: popover.unparent())` — REQUIRED to balance `set_parent`.
  - `popover.popup()`.

- `_on_tree_menu_row_activated(self, _lb, menu_row, popover, source_row)`:
  - `popover.popdown()`.
  - Dispatch on `getattr(menu_row, "_action", None)`:
    - `"copy_path"` → `_on_copy_tree_path(source_row)`
    - `"copy_file"` → `_on_copy_tree_file(source_row)`
  - Unknown action → no-op (defensive).

### C. Copy helpers (add near `_copy_drawer_diff_to_clipboard`, ~line 1367)

file_tree.py has NO generic `_copy_text_to_clipboard` yet. Add:

```python
def _copy_text_to_clipboard(self, text: str) -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    clipboard = display.get_clipboard()
    clipboard.set(text)
```

- `_on_copy_tree_path(self, row)`:
  - `path = row.props.full_path`; `if not path: return`.
  - `self._copy_text_to_clipboard(path)`.
  - Show status (see §D).

- `_on_copy_tree_file(self, row)`:
  - `path = row.props.full_path`; `if not path: return`.
  - Read file contents: `Path(path).read_text(encoding="utf-8")`.
  - **Binary/encoding guard:** on `UnicodeDecodeError` (binary file), copy a notice like
    `"<binary file — not copied>"` OR skip with a status message. Match the drawer's
    "Binary file — not shown" wording for consistency. **Do not crash.**
  - `self._copy_text_to_clipboard(content)`.

### D. Status confirmation label — RECOMMENDED (full parity)

Add a transient status label to the file tree header (`self._header`, lines 296–316),
mirroring `_show_prompt_copy_status` (left_panel.py line 970). Init `self._tree_copy_status_label`
and `self._tree_copy_status_timeout_id = None` in `FileTree.__init__`. Append the label to the
header. Call `_show_tree_copy_status("Copied path")` / `_show_tree_copy_status("Copied file")`
after successful copy. Cancel-previous-source logic must match the prompts impl exactly.

---

## Edge Cases (must handle)

1. **Drawer rows (`is_drawer=True`)** — exclude from the menu entirely.
2. **Loading rows** — `full_path == ""` (created at lines 844, 1434). Guard with `if not full_path`.
3. **Picker-mode project cards** (`_make_project_card` line 483) — OUT OF SCOPE. This feature
   is for tree rows only, not project-picker cards.
4. **Popover leak** — every `set_parent()` MUST be balanced by `unparent()` via the "closed" signal.
5. **Binary files on "Copy File"** — `UnicodeDecodeError` must not crash; copy a notice or skip.
6. **`_bound_row` can be `None`** during unbind→rebind window (line 164 sets it None in `cleanup()`).
   Null-check in the handler.
7. **Double right-click** — guard `n_press != 1` (mirror prompts impl line 880).

---

## Tests — `tests/test_file_tree_columnview.py`

Follow the pattern in `tests/test_left_panel.py` (`TestPromptRowRightClick`, line 11):

- `test_on_copy_tree_path_calls_clipboard_with_full_path` — build a `FileTreeRow`, set
  `full_path`, patch `Gdk.Display.get_default`, call `_on_copy_tree_path`, assert `clipboard.set`
  called with the path.
- `test_on_copy_tree_file_calls_clipboard_with_content` — write a temp file, call
  `_on_copy_tree_file`, assert clipboard got file contents.
- `test_on_copy_tree_file_handles_binary_gracefully` — write bytes that fail UTF-8 decode,
  assert no crash, assert a notice is copied or clipboard not set.
- `test_on_copy_tree_path_skips_empty_path` — `full_path=""` → no clipboard call, no crash.
- `test_menu_shows_copy_path_for_directory` — `_on_tree_row_right_click` on a dir row →
  menu has "Copy Path" but NOT "Copy File".
- `test_menu_shows_both_for_file` — file row → menu has both "Copy Path" and "Copy File".
- `test_menu_skips_drawer_row` — `is_drawer=True` → handler returns early, no popover.
- `test_action_dispatch_uses_action_not_label` — set `_action`, mock the dispatch targets,
  assert correct handler called regardless of label text (i18n robustness).

**NOTE:** `tests/test_file_tree_columnview.py::TestFileTreeRowWidget::test_widget_creation`
segfaults in this sandbox for environmental reasons (predates this work — see context.md
2026-07-17 entry). Do not let that test block you; run the new test class in isolation if needed.

---

## Architecture Conformance

- Stays within `ui/views/file_tree.py` (a view) — no cross-layer imports. ✓
- If any CSS is added it MUST go in `ui/styles.py` only. The popover likely needs no new CSS
  (reuse the prompts popover's implicit styling).
- No handler-module change required — this is pure view-level interaction (§8.6 compliant).
