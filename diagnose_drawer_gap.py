#!/usr/bin/env python3
"""Diagnostic script to find where the left gap on drawer rows comes from."""
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


def print_widget_tree(widget, indent=0):
    """Print widget tree with margins and paddings."""
    prefix = "  " * indent
    name = type(widget).__name__
    margin_start = widget.get_margin_start()
    margin_end = widget.get_margin_end()
    margin_top = widget.get_margin_top()
    margin_bottom = widget.get_margin_bottom()

    css_classes = widget.get_css_classes()

    try:
        width = widget.get_allocated_width()
        x = widget.get_allocated_x()
    except:
        width = -1
        x = -1

    print(f"{prefix}{name} x={x} w={width} "
          f"margin(start={margin_start}, end={margin_end}, top={margin_top}, bottom={margin_bottom}) "
          f"css={css_classes}")

    # Recurse into children
    if hasattr(widget, 'get_first_child'):
        child = widget.get_first_child()
        while child is not None:
            print_widget_tree(child, indent + 1)
            child = child.get_next_sibling()


def main():
    apply_styles()

    window = Gtk.ApplicationWindow()
    window.set_title("Drawer Gap Diagnostic")
    window.set_default_size(900, 500)

    main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    window.set_child(main_box)

    # Create FileTree
    tree = FileTree()
    main_box.append(tree)

    # Create fake project
    fake_path = "/tmp/fake_project"
    os.makedirs(fake_path, exist_ok=True)
    for name in ["src", "README.md", "main.py"]:
        is_dir = not name.endswith(".py") and not name.endswith(".md")
        full_path = os.path.join(fake_path, name)
        if is_dir:
            os.makedirs(full_path, exist_ok=True)
        else:
            with open(full_path, 'w') as f:
                f.write("# test\n")
        row = FileTreeRow(
            display_name=name,
            full_path=full_path,
            is_dir=is_dir,
            has_children=is_dir,
            expanded=False,
        )
        tree._store.append(row)

    # Open drawer for main.py
    def open_drawer():
        for i in range(tree._store.get_n_items()):
            row = tree._store.get_item(i)
            if not row.props.is_dir and not row.props.is_drawer and row.props.display_name == "main.py":
                tree._toggle_drawer(row.props.full_path)
                return False
        return False

    GLib.idle_add(open_drawer)

    # Diagnostic button
    btn = Gtk.Button(label="Print Widget Tree")
    def on_click(btn):
        print("\n=== Widget Tree for Drawer Row ===")
        # Find the drawer row
        for i in range(tree._store.get_n_items()):
            row = tree._store.get_item(i)
            if row.props.is_drawer:
                print(f"\n--- Drawer Row at index {i} ---")
                # Get the ListItem widget - this is tricky, so just print the column view
                print_widget_tree(tree._column_view)
                break
    btn.connect("clicked", on_click)
    main_box.append(btn)

    window.present()
    return window


if __name__ == "__main__":
    app = Gtk.Application()
    app.connect("activate", lambda a: main().present())
    app.run(None)
