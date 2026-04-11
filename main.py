#!/usr/bin/env python3
# main.py
# Application entry point — creates and runs the CrabcakesApp

import sys
import gi
# Require GTK 4.0 — must be called before importing Gtk
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

# Import the main window (assembles all UI components)
from ui.window import MainWindow

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

    def on_activate(self, app):
        """
        Called when the application is activated.
        Creates the main window and displays it.
        """
        win = MainWindow(application=app)  # Pass app as the application instance
        win.present()  # Show the window (GTK4 uses present() instead of show_all())

# Standard Python entry point guard
# Runs only when this file is executed directly (not imported)
if __name__ == "__main__":
    app = CrabcakesApp()  # Create application instance
    sys.exit(app.run(None))  # Run the application (None = use default sys.argv)
