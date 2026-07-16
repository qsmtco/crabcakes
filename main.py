#!/usr/bin/env python3
# main.py
# Application entry point — creates and runs the CrabcakesApp

import sys
import os
import gi
import logging

# Configure logging early — before any module imports that might use logging
_log_level = logging.DEBUG if os.environ.get("CRABCAKES_DEBUG") else logging.WARNING
logging.basicConfig(
    level=_log_level,
    format="%(name)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
# Require GTK 4.0 — must be called before importing Gtk
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# Import the main window (assembles all UI components)
from ui.window import MainWindow
from ui.styles import apply_styles

class CrabcakesApp(Gtk.Application):
    """
    Main application class.
    Gtk.Application handles:
      - Application lifecycle (startup, activate, shutdown)
      - Desktop integration (app menu, uniqueness, FAROS registration)
      - Command-line argument handling
    """

    def __init__(self):
        # Reverse-domain application ID — required by GTK for app identity
        # Convention: com.<org>.<app>
        super().__init__(application_id='com.crabcakes.app')
        # Connect the 'activate' signal — fired when app is first started
        self.connect('activate', self.on_activate)
        # Set application icon for taskbar/dock (installed in hicolor icon theme)
        Gtk.Window.set_default_icon_name('crabcakes')

    def on_activate(self, app):
        """
        Called when the application is activated.
        Creates the main window and displays it.
        """
        apply_styles()  # Register global CSS before any widgets are created
        win = MainWindow(application=app)  # Pass app as the application instance
        win.present()  # Show the window (GTK4 uses present() instead of show_all())

# Standard Python entry point guard
# Runs only when this file is executed directly (not imported)
if __name__ == "__main__":
    app = CrabcakesApp()  # Create application instance
    sys.exit(app.run(None))  # Run the application (None = use default sys.argv)
# test change
# actual test change
