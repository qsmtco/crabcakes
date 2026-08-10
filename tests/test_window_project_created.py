"""SOR Supervisor Onboarding §2.7 — project-created System bubble wiring.

Static regression tests. window.py is hard to unit-test (requires a live GTK
display which may segfault in headless sandboxes), so these assert the source
contains the required wiring at the composition root. They run without GTK.

See docs/specs/SOR-PHASE-7-INSTRUCTIONS.md.
"""
import pathlib


def test_project_created_system_bubble_wired():
    """SOR §2.7: MainWindow wires set_on_project_created to a named handler."""
    src = pathlib.Path("ui/window.py").read_text()
    assert "set_on_project_created(self._on_project_created_system_bubble)" in src
    assert "def _on_project_created_system_bubble" in src
    assert "New project '" in src  # exact message prefix
    assert "Add the Supervisor agent from the" in src
