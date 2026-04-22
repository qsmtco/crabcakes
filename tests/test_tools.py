# tests/test_tools.py
# Unit tests for agent/tools.py
#
# Principles:
#   - Test the contract: each tool's documented behavior
#   - Sandbox: paths outside project must be rejected
#   - Truncation: output > limit must be truncated
#   - Approval: exec_command requires approval callback

import os
import tempfile

import pytest

from agent.tools import (
    execute_tool,
    get_all_tools,
    get_tool_definitions_for_api,
    set_approval_callback,
)


# ═══════════════════════════════════════════════════════════════════
#  Tool registry
# ═══════════════════════════════════════════════════════════════════

class TestToolRegistry:
    def test_all_tools_returns_list(self):
        tools = get_all_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_all_tools_have_names(self):
        for tool in get_all_tools():
            assert tool.name
            assert tool.description
            assert tool.parameters

    def test_get_api_definitions_returns_dict_list(self):
        api_defs = get_tool_definitions_for_api()
        assert isinstance(api_defs, list)
        for item in api_defs:
            assert item["type"] == "function"
            assert "function" in item
            assert "name" in item["function"]
            assert "description" in item["function"]
            assert "parameters" in item["function"]

    def test_exec_command_requires_approval(self):
        for tool in get_all_tools():
            if tool.name == "exec_command":
                assert tool.requires_approval is True
                return
        pytest.fail("exec_command not found in tool registry")


# ═══════════════════════════════════════════════════════════════════
#  Sandbox: path escaping
# ═══════════════════════════════════════════════════════════════════

class TestSandbox:
    def test_read_file_absolute_outside_sandbox_rejected(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("read_file", {"path": "/etc/passwd"}, proj)
            assert r.success is False
            assert "escapes" in r.error or "outside" in r.error

    def test_read_file_absolute_inside_sandbox_allowed(self):
        with tempfile.TemporaryDirectory() as proj:
            testfile = os.path.join(proj, "test.txt")
            with open(testfile, "w") as f:
                f.write("hello")
            r = execute_tool("read_file", {"path": testfile}, proj)
            assert r.success is True
            assert r.output == "hello"

    def test_read_file_relative_inside_sandbox(self):
        with tempfile.TemporaryDirectory() as proj:
            subdir = os.path.join(proj, "src")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "a.py"), "w") as f:
                f.write("print('hi')")
            r = execute_tool("read_file", {"path": "src/a.py"}, proj)
            assert r.success is True
            assert r.output == "print('hi')"

    def test_write_file_absolute_outside_sandbox_rejected(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("write_file", {"path": "/tmp/evil.txt", "content": "bad"}, proj)
            assert r.success is False
            assert "escapes" in r.error or "outside" in r.error

    def test_write_file_inside_sandbox(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("write_file", {"path": "new.txt", "content": "world"}, proj)
            assert r.success is True
            with open(os.path.join(proj, "new.txt")) as f:
                assert f.read() == "world"

    def test_list_files_outside_sandbox_rejected(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("list_files", {"path": "/etc"}, proj)
            assert r.success is False

    def test_list_files_inside_sandbox(self):
        with tempfile.TemporaryDirectory() as proj:
            open(os.path.join(proj, "a.txt"), "w").close()
            r = execute_tool("list_files", {"path": "."}, proj)
            assert r.success is True
            assert "a.txt" in r.output

    def test_search_files_outside_sandbox_rejected(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("search_files", {"pattern": "hello", "path": "/etc"}, proj)
            assert r.success is False

    def test_search_files_inside_sandbox(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "a.py"), "w") as f:
                f.write("def hello(): pass")
            r = execute_tool("search_files", {"pattern": "hello", "path": "."}, proj)
            assert r.success is True
            assert "hello" in r.output


# ═══════════════════════════════════════════════════════════════════
#  Tool behaviors
# ═══════════════════════════════════════════════════════════════════

class TestReadFile:
    def test_read_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("read_file", {"path": "noexist.txt"}, proj)
            assert r.success is False
            assert "Not a file" in r.error or "not" in r.error.lower()

    def test_read_truncates_at_50kb(self):
        with tempfile.TemporaryDirectory() as proj:
            large = os.path.join(proj, "large.txt")
            with open(large, "w") as f:
                f.write("x" * 100_000)  # 100 KB
            r = execute_tool("read_file", {"path": "large.txt"}, proj)
            assert r.success is True
            assert "truncated" in r.output

    def test_read_binary_file_rejected(self):
        with tempfile.TemporaryDirectory() as proj:
            binary = os.path.join(proj, "bin.dat")
            with open(binary, "wb") as f:
                f.write(b"\x00\x01\x02\x03")
            r = execute_tool("read_file", {"path": "bin.dat"}, proj)
            assert r.success is False
            assert "Binary" in r.error or "binary" in r.error

    def test_read_with_offset_and_limit(self):
        with tempfile.TemporaryDirectory() as proj:
            f = os.path.join(proj, "test.txt")
            with open(f, "w") as fh:
                fh.write("0123456789abcdefghij")
            r = execute_tool("read_file", {"path": "test.txt", "offset": 5, "limit": 5}, proj)
            assert r.success is True
            assert r.output == "56789"


class TestWriteFile:
    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("write_file", {"path": "a/b/c.txt", "content": "deep"}, proj)
            assert r.success is True
            assert os.path.isfile(os.path.join(proj, "a", "b", "c.txt"))

    def test_write_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as proj:
            f = os.path.join(proj, "f.txt")
            with open(f, "w") as fh:
                fh.write("original")
            r = execute_tool("write_file", {"path": "f.txt", "content": "updated"}, proj)
            assert r.success is True
            with open(f) as fh:
                assert fh.read() == "updated"

    def test_write_reports_bytes_written(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("write_file", {"path": "f.txt", "content": "hello"}, proj)
            assert r.success is True
            assert "5 bytes" in r.output


class TestExecCommand:
    def test_exec_without_callback_denied(self):
        set_approval_callback(None)
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("exec_command", {"command": "echo hi"}, proj, "special:coder")
            assert r.success is False
            assert "approval" in r.error.lower()

    def test_exec_with_callback_allow(self):
        set_approval_callback(lambda sk, tn, args: True)
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("exec_command", {"command": "echo hello"}, proj, "special:coder")
            assert r.success is True
            assert "hello" in r.output

    def test_exec_with_callback_deny(self):
        set_approval_callback(lambda sk, tn, args: False)
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("exec_command", {"command": "echo hi"}, proj, "special:coder")
            assert r.success is False
            assert "approval" in r.error.lower()

    def test_exec_blocklist_rm_rf(self):
        set_approval_callback(lambda sk, tn, args: True)  # would approve
        with tempfile.TemporaryDirectory() as proj:
            # These MUST be blocked regardless of approval
            for cmd in ["rm -rf /", "rm -rf /*", "mkfs", "wipefs"]:
                r = execute_tool("exec_command", {"command": cmd}, proj, "special:coder")
                assert r.success is False, f"{cmd!r} should be blocked"
                assert "blocked" in r.error.lower()

    def test_exec_safe_commands_allowed(self):
        """Commands that touch /dev/null or /tmp are not blocked."""
        set_approval_callback(lambda sk, tn, args: True)
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("exec_command", {"command": "dd if=/dev/zero of=/dev/null count=1"}, proj, "special:coder")
            assert r.success is True, f"Safe dd should succeed, got: {r.error}"

    def test_exec_timeout(self):
        set_approval_callback(lambda sk, tn, args: True)
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("exec_command", {"command": "sleep 10", "timeout": 1}, proj, "special:coder")
            assert r.success is False
            assert "timed out" in r.error.lower()


class TestListFiles:
    def test_list_empty_directory(self):
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("list_files", {"path": "."}, proj)
            assert r.success is True
            assert "(empty)" in r.output

    def test_list_recursive(self):
        with tempfile.TemporaryDirectory() as proj:
            os.makedirs(os.path.join(proj, "a", "b"))
            open(os.path.join(proj, "a", "f.txt"), "w").close()
            open(os.path.join(proj, "a", "b", "nested.txt"), "w").close()
            r = execute_tool("list_files", {"path": ".", "recursive": True}, proj)
            assert r.success is True
            assert "a/f.txt" in r.output
            assert "a/b/nested.txt" in r.output  # nested file shows the dir path


class TestSearchFiles:
    def test_search_finds_match(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "a.py"), "w") as f:
                f.write("def foo():\n    pass")
            r = execute_tool("search_files", {"pattern": "def foo"}, proj)
            assert r.success is True
            assert "foo" in r.output

    def test_search_no_match(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "a.py"), "w") as f:
                f.write("def foo():\n    pass")
            r = execute_tool("search_files", {"pattern": "NOTFOUND"}, proj)
            assert r.success is True
            assert "(no matches)" in r.output

    def test_search_file_type_filter(self):
        with tempfile.TemporaryDirectory() as proj:
            with open(os.path.join(proj, "a.py"), "w") as f:
                f.write("def foo(): pass")
            with open(os.path.join(proj, "b.txt"), "w") as f:
                f.write("def foo(): pass")
            r = execute_tool("search_files", {"pattern": "def foo", "file_type": "py"}, proj)
            assert r.success is True
            assert "a.py" in r.output
            assert "b.txt" not in r.output


class TestWebSearch:
    def test_web_search_without_api_key(self):
        # Remove any API key from environment for this test
        import os
        for key in ("BRAVE_API_KEY", "OPENCLAW_BRAVE_API_KEY"):
            os.environ.pop(key, None)
        r = execute_tool("web_search", {"query": "test"}, "/tmp")
        assert r.success is False
        assert "BRAVE_API_KEY" in r.error


class TestWebFetch:
    def test_web_fetch_success(self):
        r = execute_tool("web_fetch", {"url": "https://example.com"}, "/tmp")
        assert r.success is True
        assert len(r.output) > 0

    def test_web_fetch_truncates(self):
        # The response is small so truncation won't trigger in practice,
        # but verify the parameter is accepted
        r = execute_tool("web_fetch", {"url": "https://example.com", "max_chars": 50}, "/tmp")
        assert r.success is True
        assert len(r.output) <= 50 + 50  # allow for truncation message


# ═══════════════════════════════════════════════════════════════════
#  Approval callback
# ═══════════════════════════════════════════════════════════════════

class TestApprovalCallback:
    def test_callback_receives_correct_args(self):
        received = {}
        def tracker(sk, tn, args):
            received["session_key"] = sk
            received["tool_name"] = tn
            received["args"] = args
            return True
        set_approval_callback(tracker)
        with tempfile.TemporaryDirectory() as proj:
            execute_tool("exec_command", {"command": "echo test"}, proj, "special:coder")
        assert received["session_key"] == "special:coder"
        assert received["tool_name"] == "exec_command"
        assert received["args"]["command"] == "echo test"
        assert received["args"]["cwd"] == proj
        set_approval_callback(None)  # clean up

    def test_callback_exception_returns_false(self):
        set_approval_callback(lambda sk, tn, args: 1 / 0)
        with tempfile.TemporaryDirectory() as proj:
            r = execute_tool("exec_command", {"command": "echo test"}, proj, "special:coder")
        assert r.success is False
        assert "approval" in r.error.lower()
        set_approval_callback(None)
