#!/usr/bin/env python3
"""Standalone inspection window for the FileTree diff card.

Run with: python3 inspect_filetree_drawer.py
Or with xvfb-run: xvfb-run -a python3 inspect_filetree_drawer.py
"""
import os
os.environ.setdefault('GDK_BACKEND', 'broadway')

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio, GObject

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.views.file_tree import (
    FileTree, FileTreeRow, FileTreeRowWidget, FileTreeFactory
)
from ui.styles import apply_styles


def create_inspection_window():
    """Create a window showing a file tree with an open drawer."""
    # Apply the app's CSS
    apply_styles()

    window = Gtk.ApplicationWindow()
    window.set_title("FileTree Drawer Inspector")
    window.set_default_size(900, 700)

    # Main container
    main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    window.set_child(main_box)

    # Create a FileTree widget
    tree = FileTree()
    main_box.append(tree)

    # Create a fake project structure
    fake_project_path = os.path.expanduser("~/projects/crabcakes")

    # Load a real project if it exists, otherwise create fake rows
    if os.path.exists(fake_project_path):
        tree.load_project("crabcakes", fake_project_path)
    else:
        # Create fake rows manually
        for name in ["src", "README.md", "tests", "docs", "ui", "main.py"]:
            is_dir = not name.endswith(".py") and not name.endswith(".md")
            row = FileTreeRow(
                display_name=name,
                full_path=f"/fake/{name}",
                is_dir=is_dir,
                has_children=is_dir,
                expanded=False,
            )
            tree._store.append(row)

    # Open a drawer for the first file we can find
    def open_first_file_drawer():
        n = tree._store.get_n_items()
        for i in range(n):
            row = tree._store.get_item(i)
            if not row.props.is_dir and not row.props.is_drawer:
                tree._toggle_drawer(row.props.full_path)
                GLib.idle_add(lambda: print(f"Opened drawer for: {row.props.full_path}"))
                return
        GLib.idle_add(lambda: print("No file found to open drawer"))

    GLib.idle_add(open_first_file_drawer)

    # Add a label with inspection info
    info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    info_box.set_margin_start(20)
    info_box.set_margin_end(20)
    info_box.set_margin_top(20)
    info_box.set_spacing(8)
    main_box.append(info_box)

    title = Gtk.Label()
    title.set_markup("<b>FileTree Drawer Inspector</b>")
    title.set_halign(Gtk.Align.START)
    info_box.append(title)

    info_text = Gtk.Label()
    info_text.set_markup(
        "<b>Current Settings:</b>\n"
        "• Drawer indent (margin_start): 10px\n"
        "• Drawer margin-left: removed (flush to left)\n"
        "• File icon on drawer rows: hidden\n"
        "• Orange border-left: 2px\n\n"
        "<b>What to inspect:</b>\n"
        "1. The gap between the left edge and the orange line\n"
        "2. The file icon visibility on drawer rows\n"
        "3. The overall drawer layout\n\n"
        "<b>CSS Class:</b> .file-tree-drawer\n"
        "<b>Location:</b> ui/styles.py:1350-1355"
    )
    info_text.set_halign(Gtk.Align.START)
    info_text.set_valign(Gtk.Align.START)
    info_box.append(info_text)

    # Add a refresh button
    refresh_btn = Gtk.Button(label="Refresh")
    refresh_btn.connect("clicked", lambda btn: print("Refresh clicked"))
    info_box.append(refresh_btn)

    return window


def main():
    app = Gtk.Application()
    app.connect("activate", lambda a: create_inspection_window().present())
    return app.run(None)


if __name__ == "__main__":
    sys.exit(main())
