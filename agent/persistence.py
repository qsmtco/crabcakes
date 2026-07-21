"""Conversation persistence — disk I/O for conversation state.

Extracted from agent/runtime.py (Phase 6). Stateless module-level helpers
for saving/loading conversations to ~/.config/crabcakes/conversations/.

Security:
  - HIGH-3: api_key is NEVER serialized. Re-resolved from providers.yaml on load.
  - LOW-2: session workspace validation prevents path escapes.
  - Conversation files are chmod 0600 after write.

Pure Python — no GTK, no network, no agent.runtime imports.
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)


# ── Conversation persistence ──────────────────────────────────────────────────

def conversations_dir() -> str:
    """Return the conversations directory, creating it if needed.

    HIGH-3: parent dir is chmod 0o700 (owner only). Each conversation file
    is chmod 0o600 after write (in save_conversation_to_disk).
    """
    from utils.config import get_config_dir
    d = os.path.join(get_config_dir(), "conversations")
    parent_existed = os.path.isdir(d)
    os.makedirs(d, exist_ok=True)
    if not parent_existed:
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
    return d


def save_conversation_to_disk(conv: "Conversation", session_key: str) -> str:
    """Save a conversation to <conversations_dir>/<session_key>.json.

    HIGH-3: api_key is NOT serialized. The api_key is re-resolved on load
    from providers.yaml (atomic+0600) keyed by conv.model/conv.provider.
    Conversation files should never contain raw secrets.
    """
    path = os.path.join(conversations_dir(), f"{session_key}.json")
    data = {
        "session_key": session_key,
        "agent_name": conv.agent_name,
        "project_path": conv.project_path,
        "model": conv.model,
        "provider": getattr(conv, "provider", None),  # HIGH-3: for api_key re-resolution on load
        "messages": [
            {
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "content": m.content,
                "tool_calls": [
                    {
                        "call_id": tc.call_id,
                        "tool_name": tc.tool_name,
                        "arguments": tc.arguments,
                    }
                    for tc in (m.tool_calls or [])
                ],
                "tool_call_id": getattr(m, "tool_call_id", None),
                "tokens_used": m.tokens_used,
                "timestamp": m.timestamp.isoformat() if hasattr(m.timestamp, "isoformat") else m.timestamp,
            }
            for m in conv.messages
        ],
        "system_prompt": conv.system_prompt,
        "total_tokens": conv.total_tokens,
        "total_cost": conv.total_cost,
        "step_count": conv.step_count,
        "allowed_tools": conv.allowed_tools,
        # HIGH-3: api_key NOT serialized — re-resolved from providers.yaml on load
        "mcp_servers": list(conv.mcp_servers) if conv.mcp_servers else [],
        "si_enforcement": conv.si_enforcement,
        "agent_role": conv.agent_role,
        "fallback_provider": conv.fallback_provider,
        "fallback_model": conv.fallback_model,
        "app_title": conv.app_title,
        "created_at": conv.created_at.isoformat() if hasattr(conv.created_at, "isoformat") else conv.created_at,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # HIGH-3: chmod 0600 after write — conversation files contain model/provider
    # but must NOT contain raw api_key.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # non-POSIX filesystem
    return path


def resolve_api_key_for_conversation(data: dict) -> str | None:
    """Resolve the api_key for a loaded conversation from providers.yaml.

    HIGH-3: never read api_key from the saved file. Re-resolve from the
    provider store keyed by `provider` field (or extracted from `model`).
    Returns None if no matching provider is configured.

    Args:
        data: The raw JSON data dict loaded from the conversation file.
              Expected to have a "model" key (e.g., "openai/gpt-4o") and
              optionally a "provider" key.
    """
    try:
        from utils.providers_store import load_providers
        providers = load_providers()
        if not providers:
            return None
        # Prefer explicit provider field
        provider_name = data.get("provider")
        if not provider_name:
            model = data.get("model", "")
            if "/" in model:
                provider_name = model.split("/")[0]
        if not provider_name:
            return None
        # Look up matching provider
        for p in providers:
            if p.name == provider_name:
                return p.api_key
        return None
    except Exception:
        logger.exception("[persistence] failed to resolve api_key for conversation")
        return None


def load_conversation_from_disk(session_key: str) -> tuple["Conversation", dict] | None:
    """Load a conversation from disk. Returns (Conversation, metadata) or None.

    HIGH-3: api_key is re-resolved from providers.yaml (atomic+0600) keyed
    by conv.model. Saved api_key in old files is ignored (and stripped
    on next save by the one-time migration).
    """
    path = os.path.join(conversations_dir(), f"{session_key}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    from models.conversation import Conversation, Message, MessageRole

    messages = []
    for mdata in data.get("messages", []):
        from models.conversation import ToolCall
        tool_calls = []
        for tcdata in mdata.get("tool_calls", []):
            tool_calls.append(
                ToolCall(
                    call_id=tcdata["call_id"],
                    tool_name=tcdata["tool_name"],
                    arguments=tcdata.get("arguments", {}),
                )
            )
        msg = Message(
            role=MessageRole(mdata["role"]),
            content=mdata.get("content", ""),
            tool_calls=tool_calls,
            tool_call_id=mdata.get("tool_call_id"),
            tokens_used=mdata.get("tokens_used", 0),
        )
        messages.append(msg)

    # HIGH-3: re-resolve api_key from providers.yaml, NOT from saved data
    api_key = resolve_api_key_for_conversation(data)

    conv = Conversation(
        agent_name=data["agent_name"],
        # Option C+: project_path and system_prompt are NOT loaded from disk.
        # The persisted values may be stale (from a previous project the user
        # had open). They are re-applied by _rebuild_conversation_context
        # on first send, against the currently-active project. The persisted
        # values are still written on save so a manual audit can read them
        # back, but the runtime never trusts them.
        project_path=None,
        model=data.get("model", ""),
        provider=data.get("provider"),  # HIGH-3: stored so we can re-resolve api_key
        system_prompt="",
        messages=messages,
        total_tokens=data.get("total_tokens", 0),
        total_cost=data.get("total_cost", 0.0),
        step_count=data.get("step_count", 0),
        allowed_tools=data.get("allowed_tools"),
        api_key=api_key,  # HIGH-3: re-resolved from providers.yaml
        app_title=data.get("app_title", ""),
        mcp_servers=data.get("mcp_servers", []),
        si_enforcement=data.get("si_enforcement"),
        agent_role=data.get("agent_role", ""),
        fallback_provider=data.get("fallback_provider"),
        fallback_model=data.get("fallback_model"),
    )
    # allowed_tools fallback: if the persisted conversation has no
    # allowed_tools (pre-fix conversations or post-YAML-edit), fall back
    # to the live agent definition's tools list. Mirrors the HIGH-3
    # api_key re-resolution pattern: do not trust persisted state when
    # live config is available. Without this, the execute_tool gate is
    # a no-op for any conversation created before the gate shipped.
    if conv.allowed_tools is None:
        try:
            from agent.special_agents import get_special_agent
            agent_def = get_special_agent(session_key)
            if agent_def is not None and agent_def.tools:
                conv.allowed_tools = list(agent_def.tools)
        except Exception:
            pass  # Best-effort: leave None if lookup fails (gate skips)

    return conv, data


# ── HIGH-3: One-time migration ──────────────────────────────────────────────────

# Module-level flag — migration runs once per process
_CONVERSATION_MIGRATION_DONE: bool = False


def migrate_conversation_files() -> int:
    """One-time sweep: remove api_key from existing conversation files.

    HIGH-3: scans ~/.config/crabcakes/conversations/*.json, removes the
    "api_key" field if present, writes back atomically with chmod 0600.
    New saves never include api_key. Idempotent — safe to call multiple times.

    Returns the number of files migrated.
    """
    global _CONVERSATION_MIGRATION_DONE
    if _CONVERSATION_MIGRATION_DONE:
        return 0
    _CONVERSATION_MIGRATION_DONE = True

    d = conversations_dir()
    count = 0
    try:
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            path = os.path.join(d, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "api_key" in data:
                    del data["api_key"]
                    # Atomic write
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp, path)
                    # Ensure 0600
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
                    count += 1
            except (OSError, json.JSONDecodeError):
                # Skip unreadable files — don't crash the migration
                continue
    except OSError:
        pass
    if count > 0:
        logger.info(
            "[persistence] HIGH-3 migration: removed api_key from %d conversation file(s)",
            count,
        )
    return count


# ── LOW-2: Per-session secure workspace ─────────────────────────────────────


def resolve_session_workspace(project_path: str | None, session_key: str) -> str:
    """Return a per-session secure workspace under the project's .crabcakes/ dir.

    LOW-2: never fall back to /tmp — raise if project_path is empty.
    The workspace dir is created with 0o700 permissions (owner-only).

    Args:
        project_path: The project directory (must not be empty).
        session_key: Must be non-empty, whitespace-free, and contain only
            [a-zA-Z0-9._:-]. Path separators and ".." are rejected.
            Colons (e.g. "special:coder") are allowed and sanitized for
            filesystem safety.

    Returns:
        Absolute path to the session's scratch workspace directory.
    """
    if not project_path:
        raise ValueError(
            f"LOW-2: project_path is empty for session {session_key!r}; "
            "refusing to use a world-writable default"
        )
    # session_key validation — prevent empty keys, path escapes, and traversal
    if not session_key or not session_key.strip():
        raise ValueError(f"LOW-2: session_key must be non-empty and contain no whitespace: {session_key!r}")
    if ".." in session_key:
        raise ValueError(f"LOW-2: session_key must not contain '..': {session_key!r}")
    if not re.fullmatch(r"[a-zA-Z0-9._:-]+", session_key):
        raise ValueError(f"LOW-2: session_key must match [a-zA-Z0-9._:-]+, got: {session_key!r}")
    # Sanitize colon for filesystem safety (e.g. "special:coder" → "special-coder")
    fs_safe_key = session_key.replace(":", "-")
    workspace = os.path.join(project_path, ".crabcakes", "tmp", fs_safe_key)
    os.makedirs(workspace, mode=0o700, exist_ok=True)
    return workspace