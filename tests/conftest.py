# tests/conftest.py
# Shared pytest fixtures — all tests use isolated temp directories.

import ast
import os
import sys
import pytest

# Ensure crabcakes package is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """
    Patch ~/.config/crabcakes to point at an isolated temp directory.
    All tests that touch config files use this fixture.
    """
    config_dir = tmp_path / ".config" / "crabcakes"
    config_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path))
    return config_dir


@pytest.fixture
def tmp_prompts_dir(tmp_path, monkeypatch):
    """
    Create an isolated temp prompts directory with some .md files.
    Patch PromptsHandler._get_prompts_dir to return it.
    """
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    # Create a couple of sample .md files
    (prompts_dir / "sample.md").write_text("# Sample\nHello world")
    (prompts_dir / "example.md").write_text("# Example\nTest content")
    return prompts_dir


def test_handlers_do_not_import_each_other():
    """
    Import guard: handlers must NOT import other handlers.
    window.py importing handlers is correct and expected.
    This guard ensures handlers stay decoupled — if one handler imports another,
    the coupling is explicit (window wires them) rather than implicit.
    """
    import os
    handlers_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", "handlers"
    )
    if not os.path.isdir(handlers_dir):
        pytest.skip("handlers/ directory does not exist yet")

    handler_files = [
        os.path.join(handlers_dir, f)
        for f in os.listdir(handlers_dir)
        if f.endswith(".py") and f not in ("__init__.py", "conftest.py")
    ]

    violations = []
    for filepath in handler_files:
        with open(filepath) as f:
            tree = ast.parse(f.read(), filename=filepath)

        our_name = os.path.basename(filepath)[:-3]  # e.g. "chat_handler" from "chat_handler.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("ui.handlers."):
                    imported = node.module.split(".")[-1]
                    if imported != our_name:  # same handler can import itself
                        violations.append(f"{os.path.basename(filepath)} imports ui.handlers.{imported}")

    assert violations == [], f"Handler coupling violations:\n  " + "\n  ".join(violations)


@pytest.fixture
def fake_glib():
    """Provide a GLib-like object for handler tests that need it.
    Provides timeout_add and source_remove with immediate execution (no delay).
    """
    class FakeGLib:
        def timeout_add(self, *args, **kwargs):
            return 1

        def timeout_add_seconds(self, *args, **kwargs):
            return 1

        def source_remove(self, timer_id):
            pass

        def idle_add(self, fn, *args, **kwargs):
            fn(*args)
            return 1

    return FakeGLib()
