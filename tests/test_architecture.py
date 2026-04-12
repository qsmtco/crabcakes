"""
Architecture compliance tests.
Verifies: handler isolation, layer separation, no UI imports from models/gateway.
"""
import ast
import os
import sys


def test_handlers_do_not_import_each_other():
    """
    AST guard: handlers must NOT import other handlers.
    window.py importing handlers is correct and expected.
    This guard ensures handlers stay decoupled.
    """
    handlers_dir = os.path.join(os.path.dirname(__file__), "..", "ui", "handlers")
    if not os.path.isdir(handlers_dir):
        pytest.skip("handlers/ directory does not exist yet")

    handler_files = [
        os.path.join(handlers_dir, f)
        for f in os.listdir(handlers_dir)
        if f.endswith(".py") and not f.startswith("_")
    ]

    violations = []
    for filepath in handler_files:
        with open(filepath, "r") as f:
            tree = ast.parse(f.read(), filename=os.path.basename(filepath))

        our_name = os.path.basename(filepath)[:-3]  # e.g. "chat_handler"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("ui.handlers."):
                    imported = node.module.split(".")[-1]
                    if imported != our_name:  # same handler can import itself
                        violations.append(
                            f"{os.path.basename(filepath)} imports ui.handlers.{imported}"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("ui.handlers."):
                        imported = alias.name.split(".")[-1]
                        violations.append(
                            f"{os.path.basename(filepath)} imports {alias.name}"
                        )

    assert not violations, "Handler isolation violated:\n  " + "\n  ".join(violations)


def test_models_and_gateway_do_not_import_ui():
    """
    Layer isolation: models/ and gateway/ must not import ui/ or gi.repository.Gtk.
    Entry points (main.py) and utils/icons.py are exempt (icons needs Gdk for textures).
    """
    violations = []
    root_dir = os.path.dirname(os.path.dirname(__file__))  # project root
    for subdir in ("models", "gateway"):
        subdir_path = os.path.join(root_dir, subdir)
        if not os.path.isdir(subdir_path):
            continue
        for fpath, dirs, files in os.walk(subdir_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                full_path = os.path.join(fpath, fname)
                rel = os.path.relpath(full_path, root_dir)
                with open(full_path) as f:
                    content = f.read()
                for lineno, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if "from ui." in line or "import ui." in line:
                        violations.append(f"{rel}:{lineno}: {stripped}")
                    if "from gi.repository import Gtk" in line:
                        violations.append(f"{rel}:{lineno}: {stripped}")

    assert not violations, "Layer isolation violated:\n  " + "\n  ".join(violations)


def test_all_documented_public_apis_exist():
    """Verify every public method documented in ARCHITECTURE.md exists in code."""
    import importlib

    # AgentListHandler
    from ui.handlers.agent_list_handler import AgentListHandler

    arch_api = [
        "set_agent_mgr",
        "has_agent_mgr",
        "compute_initials",
        "get_agent_color",
        "get_sorted_agents",
        "on_chat_clicked",
        "on_toggle_clicked",
    ]
    missing = [m for m in arch_api if not hasattr(AgentListHandler, m)]
    assert not missing, f"AgentListHandler missing: {missing}"

    # LeftPanel
    from ui.views.left_panel import LeftPanel

    left_panel_api = [
        "set_agents",
        "set_agent_list_handler",
        "set_on_project_opened",
        "refresh_agents_with_project",
        "set_toggle_agent_callback",
    ]
    missing_lp = [m for m in left_panel_api if not hasattr(LeftPanel, m)]
    assert not missing_lp, f"LeftPanel missing: {missing_lp}"
