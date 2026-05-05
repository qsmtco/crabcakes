# agent/tools.py
# Tool definitions and execution for the agent runtime.
#
# Manifest:
#   - File operations: only paths within project_path (sandboxed)
#   - Exec: requires PM approval via registered callback
#   - Web: httpx calls to Brave Search API and arbitrary URLs
#   - No GTK, no LLM calls
#
# Architecture: agent/ is the only package that knows tool capabilities.
# All tools are data + pure functions. No GTK, no state, no network at import time.

from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable

import httpx

# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class ToolDefinition:
    """Definition of a tool available to agents."""
    name: str
    description: str
    parameters: dict          # JSON Schema for LLM function-calling
    requires_approval: bool = False


@dataclass
class ToolResult:
    """Result of executing a tool."""
    success: bool
    output: str = ""              # text output or file contents
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


# ── Internal state ──────────────────────────────────────────────────────────────

# Approval callback: called before exec_command. Returns True to allow, False to deny.
_approval_callback: Callable[[str, str, dict], bool] | None = None
# "special:coder" or "special:debugger", tool_name, {"command": "...", "cwd": "..."}


def set_approval_callback(cb: Callable[[str, str, dict], bool] | None) -> None:
    """Register a callback that asks the PM for exec_command approval.

    Args:
        cb: callback(session_key, tool_name, arguments) -> bool.
            True = allow execution.
            False = deny (tool returns error result).
            None = unregister (exec_command will always be denied without a callback).
    """
    global _approval_callback
    _approval_callback = cb


def _get_approval(session_key: str, tool_name: str, arguments: dict) -> bool:
    """Return True if exec_command is approved, False otherwise."""
    if _approval_callback is None:
        return False
    try:
        return _approval_callback(session_key, tool_name, arguments)
    except Exception:
        return False


# ── Path sandbox ───────────────────────────────────────────────────────────────

MAX_READ_SIZE = 50 * 1024       # 50 KB
MAX_WRITE_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_EXEC_OUTPUT = 100 * 1024     # 100 KB

# Hardcoded blocklist — always denied even with approval.
# Commands matching these patterns (substring match) are rejected before
# the approval callback fires. This catches catastrophic cases.
_BLOCKLIST = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero of=/dev/sda",
    "dd if=/dev/zero of=/dev/nvme",
    "cat /dev/sda",
    "> /dev/sda",
    "chattr -i",
    "wipefs",
    ":(){:|:&};:",    # fork bomb
]


def _is_blocked(command: str) -> bool:
    """Return True if command matches the hardcoded blocklist."""
    lower = command.lower()
    for pattern in _BLOCKLIST:
        if pattern.lower() in lower:
            return True
    return False


def _resolve_project_path(path: str, project_path: str) -> str | None:
    """
    Resolve a path relative to project_path and verify it stays within the sandbox.

    Returns the absolute resolved path if within sandbox, or None if it escapes.
    """
    if os.path.isabs(path):
        # Absolute path — must be under project_path
        resolved = os.path.realpath(path)
        project_real = os.path.realpath(project_path)
        try:
            common = os.path.commonpath([resolved, project_real])
            if common == project_real:
                return resolved
        except ValueError:
            # Different drives on Windows — commonpath raises
            pass
        return None
    else:
        # Relative path — resolved relative to project_path
        resolved = os.path.realpath(os.path.join(project_path, path))
        project_real = os.path.realpath(project_path)
        try:
            common = os.path.commonpath([resolved, project_real])
            if common == project_real:
                return resolved
        except ValueError:
            pass
        return None


# ── Tool implementations ──────────────────────────────────────────────────────


def _read_file(path: str, project_path: str, offset: int | None = None, limit: int | None = None) -> ToolResult:
    """Read a file relative to project_path."""
    resolved = _resolve_project_path(path, project_path)
    if resolved is None:
        return ToolResult(success=False, error=f"Path escapes project sandbox: {path}")

    if not os.path.isfile(resolved):
        return ToolResult(success=False, error=f"Not a file: {path}")

    try:
        size = os.path.getsize(resolved)
        if size > 50 * 1024 * 1024:
            return ToolResult(success=False, error=f"File too large (>50MB): {path}")

        # Binary check
        with open(resolved, "rb") as f:
            header = f.read(512)
        if b"\x00" in header:
            return ToolResult(success=False, error=f"Binary file (not readable as text): {path}")

        # Read with optional offset/limit using binary mode
        # (to correctly handle byte offsets in UTF-8 multi-byte files)
        with open(resolved, "rb") as f:
            if offset is not None:
                f.seek(offset)
            raw = f.read(limit)
        content = raw.decode("utf-8", errors="replace")

        if len(content) >= MAX_READ_SIZE:
            content += f"\n[... truncated at {MAX_READ_SIZE} bytes ...]"

        return ToolResult(success=True, output=content)

    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except UnicodeDecodeError:
        return ToolResult(success=False, error=f"File is not valid UTF-8: {path}")
    except OSError as e:
        return ToolResult(success=False, error=f"Cannot read {path}: {e}")


def _write_file(path: str, content: str, project_path: str) -> ToolResult:
    """Write content to a file relative to project_path."""
    resolved = _resolve_project_path(path, project_path)
    if resolved is None:
        return ToolResult(success=False, error=f"Path escapes project sandbox: {path}")

    # Create parent directories if needed
    parent = os.path.dirname(resolved)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return ToolResult(success=False, error=f"Cannot create directory {os.path.dirname(path)}: {e}")

    try:
        byte_count = len(content.encode("utf-8"))
        if byte_count > MAX_WRITE_SIZE:
            return ToolResult(success=False, error=f"Content too large ({byte_count} bytes, max {MAX_WRITE_SIZE})")
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(success=True, output=f"OK — wrote {byte_count} bytes to {path}")
    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except OSError as e:
        return ToolResult(success=False, error=f"Cannot write {path}: {e}")


def _exec_command(command: str, project_path: str, timeout: int = 30, session_key: str = "_unknown") -> ToolResult:
    """Run a shell command in the project directory. Requires PM approval."""
    # Hard blocklist check first — always denied before callback fires
    if _is_blocked(command):
        return ToolResult(success=False, error=f"Command blocked by safety policy: {command}")

    # PM approval check via registered callback (Bug #3 fix)
    if not _get_approval(session_key, "exec_command", {"command": command, "cwd": project_path}):
        return ToolResult(success=False, error="exec_command requires PM approval", duration_ms=0)

    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project_path,
            capture_output=True,
            timeout=timeout,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

        if len(output) > MAX_EXEC_OUTPUT:
            output = output[:MAX_EXEC_OUTPUT] + f"\n[... truncated at {MAX_EXEC_OUTPUT} bytes ...]"

        if result.returncode != 0:
            return ToolResult(
                success=False,
                output=output,
                error=f"Exit {result.returncode}",
                duration_ms=duration_ms,
            )

        return ToolResult(success=True, output=output, duration_ms=duration_ms)

    except subprocess.TimeoutExpired:
        return ToolResult(success=False, error=f"Command timed out after {timeout}s", duration_ms=int((time.monotonic() - start) * 1000))
    except OSError as e:
        return ToolResult(success=False, error=f"Cannot execute: {e}", duration_ms=int((time.monotonic() - start) * 1000))


def _list_files(path: str, project_path: str, recursive: bool = False) -> ToolResult:
    """List files in a directory relative to project_path."""
    resolved = _resolve_project_path(path, project_path)
    if resolved is None:
        return ToolResult(success=False, error=f"Path escapes project sandbox: {path}")

    if not os.path.isdir(resolved):
        return ToolResult(success=False, error=f"Not a directory: {path}")

    try:
        lines = []
        if recursive:
            for root, dirs, files in os.walk(resolved):
                # Skip common noise directories
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".pytest_cache")]
                for name in sorted(files):
                    full = os.path.join(root, name)
                    try:
                        size = os.path.getsize(full)
                        rel = os.path.relpath(full, resolved)
                        lines.append(f"{rel}  {size}")
                    except OSError:
                        lines.append(f"{name}  [cannot stat]")
        else:
            for name in sorted(os.listdir(resolved)):
                full = os.path.join(resolved, name)
                try:
                    size = os.path.getsize(full) if os.path.isfile(full) else 0
                    marker = "/" if os.path.isdir(full) else ""
                    lines.append(f"{name}{marker}  {size}")
                except OSError:
                    lines.append(name)

        output = "\n".join(lines) if lines else "(empty)"
        return ToolResult(success=True, output=output)

    except PermissionError:
        return ToolResult(success=False, error=f"Permission denied: {path}")
    except OSError as e:
        return ToolResult(success=False, error=f"Cannot list {path}: {e}")


def _search_files(pattern: str, project_path: str, path: str | None = None, file_type: str | None = None) -> ToolResult:
    """Search file contents using grep/ripgrep."""
    search_root = _resolve_project_path(path or ".", project_path)
    if search_root is None:
        return ToolResult(success=False, error=f"Path escapes project sandbox: {path or '.'}")

    cmd = ["grep", "-n", "-H", "--directories=skip", "-r"]
    if file_type:
        cmd += ["--include=*." + file_type]
    cmd += [pattern, "."]  # search from resolved path as cwd

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=10,
            cwd=search_root,   # run grep from the search root so paths are relative
            text=True,
        )
        if result.returncode == 1:
            return ToolResult(success=True, output="(no matches)")
        elif result.returncode != 0:
            return ToolResult(success=False, error=f"grep exited with {result.returncode}: {result.stderr[:200]}")

        output = result.stdout
        if len(output) > MAX_EXEC_OUTPUT:
            output = output[:MAX_EXEC_OUTPUT] + f"\n[... truncated ...]"
        return ToolResult(success=True, output=output)

    except subprocess.TimeoutExpired:
        return ToolResult(success=False, error="Search timed out after 10s")
    except FileNotFoundError:
        return ToolResult(success=False, error="grep not found on this system")
    except OSError as e:
        return ToolResult(success=False, error=f"Search failed: {e}")


def _get_brave_api_key() -> str | None:
    """Get Brave Search API key from environment."""
    return os.environ.get("BRAVE_API_KEY") or os.environ.get("OPENCLAW_BRAVE_API_KEY")


def _web_search(query: str, count: int = 5) -> ToolResult:
    """Search the web via Brave Search API."""
    api_key = _get_brave_api_key()
    if not api_key:
        return ToolResult(success=False, error="web_search requires BRAVE_API_KEY environment variable")

    try:
        params = {"q": query, "count": min(count, 10), "freshness": "y"}
        headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params=params,
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code == 401:
            return ToolResult(success=False, error="Brave API key is invalid or expired")
        resp.raise_for_status()
        data = resp.json()

        results = data.get("web", {}).get("results", [])
        if not results:
            return ToolResult(success=True, output="(no results)")

        lines = []
        for item in results[:count]:
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("description", "")
            lines.append(f"## {title}\n{url}\n{snippet}\n")

        return ToolResult(success=True, output="\n".join(lines))

    except httpx.HTTPStatusError as e:
        return ToolResult(success=False, error=f"Brave API error {e.response.status_code}: {e.response.text[:200]}")
    except httpx.RequestError as e:
        return ToolResult(success=False, error=f"web_search failed: {e}")


def _web_fetch(url: str, max_chars: int = 10000) -> ToolResult:
    """Fetch and extract readable content from a URL."""
    try:
        resp = httpx.get(url, timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return ToolResult(success=False, error=f"Cannot fetch non-text content type: {content_type}")

        text = resp.text
        # Basic extraction: strip HTML tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n[... truncated at {max_chars} chars ...]"

        return ToolResult(success=True, output=text)

    except httpx.HTTPStatusError as e:
        return ToolResult(success=False, error=f"web_fetch HTTP {e.response.status_code}: {url}")
    except httpx.RequestError as e:
        return ToolResult(success=False, error=f"web_fetch failed: {e}")


# ── Tool registry ───────────────────────────────────────────────────────────────

# _TOOLS maps name -> (ToolDefinition, handler_fn)
_TOOLS: dict[str, tuple[ToolDefinition, Callable[..., ToolResult]]] = {}


def _register_tools() -> None:
    """Register all available tools. Called once at module load."""

    # read_file
    _TOOLS["read_file"] = (
        ToolDefinition(
            name="read_file",
            description=(
                "Read the contents of a file from the project directory. "
                "Returns the text content, or an error if the file is binary, missing, or inaccessible. "
                "Truncates at 50KB."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the project directory"},
                    "offset": {"type": "integer", "description": "Byte offset to start reading from (optional)"},
                    "limit": {"type": "integer", "description": "Maximum bytes to read (optional)"},
                },
                "required": ["path"],
            },
            requires_approval=False,
        ),
        lambda path, project_path, offset=None, limit=None, **kwargs:  # type: ignore
            _read_file(path, project_path, offset, limit),
    )

    # write_file
    _TOOLS["write_file"] = (
        ToolDefinition(
            name="write_file",
            description=(
                "Write content to a file in the project directory. "
                "Creates parent directories if needed. Overwrites existing files. "
                "Returns the number of bytes written."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the project directory"},
                    "content": {"type": "string", "description": "Text content to write"},
                },
                "required": ["path", "content"],
            },
            requires_approval=False,
        ),
        lambda path, content, project_path, **kwargs:  # type: ignore
            _write_file(path, content, project_path),
    )

    # exec_command
    _TOOLS["exec_command"] = (
        ToolDefinition(
            name="exec_command",
            description=(
                "Run a shell command in the project directory. "
                "The PM must approve each exec_command call before it runs. "
                "Blocked commands (rm -rf /, mkfs, etc.) are always denied. "
                "Returns stdout+stderr, truncated at 100KB. "
                "Timeout defaults to 30s."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
                },
                "required": ["command"],
            },
            requires_approval=True,
        ),
        lambda command, project_path, timeout=30, session_key="_unknown", **kwargs:  # type: ignore
            _exec_command(command, project_path, min(timeout, 120), session_key),
    )

    # list_files
    _TOOLS["list_files"] = (
        ToolDefinition(
            name="list_files",
            description=(
                "List files and subdirectories in a project directory. "
                "Does not recurse by default. Skips .git, node_modules, __pycache__."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path within the project (default '.')"},
                    "recursive": {"type": "boolean", "description": "Recurse into subdirectories (default False)"},
                },
                "required": [],
            },
            requires_approval=False,
        ),
        lambda project_path, path=".", recursive=False, **kwargs:  # type: ignore
            _list_files(path, project_path, recursive),
    )

    # search_files
    _TOOLS["search_files"] = (
        ToolDefinition(
            name="search_files",
            description=(
                "Search for text patterns in project files using grep. "
                "Returns matching lines with file paths and line numbers. "
                "Times out after 10s."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Text pattern or regex to search for"},
                    "path": {"type": "string", "description": "Relative path to search within (default '.')"},
                    "file_type": {"type": "string", "description": "Only match files with this extension (e.g. 'py', 'js')"},
                },
                "required": ["pattern"],
            },
            requires_approval=False,
        ),
        lambda pattern, project_path, path=None, file_type=None, **kwargs:  # type: ignore
            _search_files(pattern, project_path, path, file_type),
    )

    # web_search
    _TOOLS["web_search"] = (
        ToolDefinition(
            name="web_search",
            description=(
                "Search the web using Brave Search. "
                "Requires BRAVE_API_KEY environment variable. "
                "Returns title, URL, and snippet for each result."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "count": {"type": "integer", "description": "Maximum number of results (default 5, max 10)"},
                },
                "required": ["query"],
            },
            requires_approval=False,
        ),
        lambda query, count=5, **kwargs: _web_search(query, count),  # type: ignore
    )

    # web_fetch
    _TOOLS["web_fetch"] = (
        ToolDefinition(
            name="web_fetch",
            description=(
                "Fetch and extract readable text from a URL. "
                "Strips HTML tags and returns plain text, truncated at 10,000 chars. "
                "Only works on HTML/text pages."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 10,000)"},
                },
                "required": ["url"],
            },
            requires_approval=False,
        ),
        lambda url, max_chars=10000, **kwargs: _web_fetch(url, max_chars),  # type: ignore
    )


_register_tools()


# ── Public API ─────────────────────────────────────────────────────────────────

def get_all_tools() -> list[ToolDefinition]:
    """Return all available tool definitions."""
    return [defn for defn, _ in _TOOLS.values()]


def get_tool_definitions_for_api(allowed_tools: list[str] | None = None) -> list[dict]:
    """
    Return tool definitions in OpenAI function-calling format.

    Args:
        allowed_tools: If None, returns all tools. If a list, returns only
                      tools whose names are in allowed_tools (order preserved).
    Used by AgentRuntime when calling the LLM API.
    """
    all_tools = get_all_tools()
    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        tools_to_include = [t for t in all_tools if t.name in allowed_set]
    else:
        tools_to_include = all_tools

    result = []
    for defn in tools_to_include:
        entry: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": defn.name,
                "description": defn.description,
                "parameters": defn.parameters,
            },
        }
        result.append(entry)
    return result


def execute_tool(
    name: str,
    arguments: dict,
    project_path: str,
    session_key: str = "_unknown",
) -> ToolResult:
    """
    Execute a tool by name with the given arguments.

    Args:
        name: Tool name (e.g. "read_file")
        arguments: Parsed arguments dict (e.g. {"path": "src/main.py"})
        project_path: Absolute path to the project working directory
        session_key: Session key of the agent (for exec_command approval)

    Returns:
        ToolResult with output or error.

    All file paths are sandboxed to project_path.
    exec_command requires PM approval via the registered callback.
    """
    entry = _TOOLS.get(name)
    if entry is None:
        return ToolResult(success=False, error=f"Unknown tool: {name}")

    defn, handler = entry
    start = time.monotonic()

    try:
        # Inject project_path and session_key into arguments
        args = dict(arguments)
        args["project_path"] = project_path
        args["session_key"] = session_key

        result = handler(**args)
        duration_ms = int((time.monotonic() - start) * 1000)
        if result.duration_ms == 0:
            result = dataclasses.replace(result, duration_ms=duration_ms)
        return result

    except TypeError as e:
        # Missing or unexpected argument
        return ToolResult(
            success=False,
            error=f"Tool {name} received invalid arguments: {e}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Tool {name} raised {type(e).__name__}: {e}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )
